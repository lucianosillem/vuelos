#!/usr/bin/env python3
"""Vuelos — parsear carpetas de liveries de MSFS 2024 a registros estructurados.

Lee data/liveries_folders.txt (formato "Tipo\\nombre livery") y produce liveries.json.

Nomenclaturas reales (MSFS 2024, PC escritorio):
  Fenix  : "baw-g-dbcb-cd61"  →  airline_icao | matricula | hash (los últimos 4 se omiten)
           "ava-n538av-fd33"  →  N-numbers sin prefijo de país
           "jetsmart-cc-awa"  →  sin ICAO aerolínea, matrícula presente
  PMDG   : "aerolineas_argentinas_lvgvc_or_2024" → aerolinea_matricula_or_anio
           "PMDG 737-800 Aerolineas Argentinas CXS" → nombre libre con matrícula corta

Uso:  python3 parse_liveries.py [--dry]
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "liveries_folders.txt")
OUT = os.path.join(BASE, "liveries.json")

# ── Tipos de avión por carpeta nivel-1 ─────────────────────────────
AIRCRAFT_BY_TOP = {
    "Fenix-319": "A319",
    "Fenix-320": "A320",
    "Fenix-321": "A321",
    "PMDG-738": "B738",
    # respaldo para las que venían de la lista vieja
    "FBW A320": "A20N",
    "FBW A380": "A388",
    "Fenix": "A320",
    "FSLabs": "A320",
    "iFly": "B38M",
    "Inibuilds": "A359",
    "Microsoft": "A332",
    "TFDi": "MD11",
}

# ── Aerolíneas por código ICAO (Fenix usa ICAO real de la aerolínea) ──
Airlines = {
    "AAL": ("AAL", "American Airlines"),
    "AVA": ("AVA", "Avianca"),
    "AWE": ("AWE", "US Airways"),
    "BAW": ("BAW", "British Airways"),
    "CFG": ("CFG", "Condor"),
    "DLH": ("DLH", "Lufthansa"),
    "DSM": ("DSM", "LATAM Argentina"),
    "EWG": ("EWG", "Eurowings"),
    "EWL": ("EWL", "Eurowings Europe"),
    "EZY": ("EZY", "easyJet"),
    "FOO": ("FOO", "FlyOne"),
    "IBE": ("IBE", "Iberia"),
    "IBS": ("IBS", "Iberia Express"),
    "ITY": ("ITY", "ITA Airways"),
    "JAT": ("JAT", "JetSMART"),
    "JES": ("JES", "JetSMART"),
    "LAN": ("LAN", "LATAM Chile"),
    "QTR": ("QTR", "Qatar Airways"),
    "SWR": ("SWR", "Swiss"),
    "TAM": ("TAM", "LATAM Brasil"),
    "TAP": ("TAP", "TAP Portugal"),
    "VLG": ("VLG", "Vueling"),
    "VIV": ("VIV", "Viva Aerobus"),
    "WZZ": ("WZZ", "Wizz Air"),
    "ARG": ("ARG", "Aerolíneas Argentinas"),
    "AMX": ("AMX", "Aeroméxico"),
    "UPS": ("UPS", "UPS"),
    "GEC": ("GEC", "GECAS"),
}

# ── Parsing de una línea ───────────────────────────────────────────
FENIX_RE = re.compile(
    r"^(?P<airline>[a-z]{3})-(?P<matricula>[a-z0-9-]+?)(?:-[a-z0-9]{4})?$",
    re.IGNORECASE,
)
# PMDG: "aerolineas_argentinas_lvgvc_or_2024" → matrícula LV-GVC
#       "mrliveries_arg_lvggq_2026" → LV-GGQ (5 letras)
PMDG_UNDER_RE = re.compile(
    r"^(?P<airline>[a-z_]+?)_(?P<matricula>(?:lv|xa|cc|ec)-?[a-z0-9]{3,4}|[a-z0-9]{4,6})(?:_(?:or_)?\d{4})?$",
    re.IGNORECASE,
)
# matrícula con guión estándar
REG_STD = re.compile(r"\b(?P<m>(?:LV|CC|EC|EI|D-|G-|N|XA|HK|CS|OE|PR|PT|HB|A6|9H)-?[A-Z0-9]{2,5})\b")


def normalize_matricula(raw):
    if not raw:
        return raw
    m = raw.strip().upper().replace("_", "")
    # LVGVC → LV-GVC, CCBAW → CC-BAW
    if re.fullmatch(r"(LV|CC|EC|EI|XA|HK|CS|OE|PR|PT|HB)[A-Z]{3}", m):
        return f"{m[:2]}-{m[2:]}"
    # N538AV → N538AV (ya ok), N750AV → N750AV
    if re.fullmatch(r"N\d{3}[A-Z]{2}", m):
        return m
    if re.fullmatch(r"D-A[A-Z]{3}", m):
        return m
    if re.fullmatch(r"G-[A-Z]{4}", m):
        return m
    return m


def parse_airline_icao(raw):
    """Mapea código ICAO de aerolínea (2-3 letras) a (icao, nombre)."""
    k = raw.strip().upper()
    if k in Airlines:
        return Airlines[k]
    # puede venir con prefijo: arg → ARG
    if len(k) == 3:
        return (k, None)
    return ("", None)


def parse_line(top, name):
    aircraft = AIRCRAFT_BY_TOP.get(top, "")
    airline_icao, airline_name, matricula = "", "", ""

    if top.startswith("PMDG"):
        # forma 1: aerolineas_argentinas_lvgvc_or_2024
        m = PMDG_UNDER_RE.match(name)
        if m:
            al_key = m.group("airline").upper()
            if "AEROLINEAS" in al_key or "ARG" in al_key:
                airline_icao, airline_name = "ARG", "Aerolíneas Argentinas"
            elif "AEROMEXICO" in al_key:
                airline_icao, airline_name = "AMX", "Aeroméxico"
            mat = normalize_matricula(m.group("matricula"))
            # solo matrícula si parece real (LV-GVC, XA-AMG)
            if re.fullmatch(r"(LV|XA)-?[A-Z]{3}", mat):
                matricula = mat
        else:
            # forma 2: "PMDG 737-800 Aerolineas Argentinas CXS"
            low = name.lower()
            if "aerolineas" in low:
                airline_icao, airline_name = "ARG", "Aerolíneas Argentinas"
                tok = name.split()[-1].upper()
                if re.fullmatch(r"[A-Z]{3}", tok):
                    matricula = f"LV-{tok}"

    elif top.startswith("Fenix"):
        low = name.lower().strip()
        # jetsmart sin ICAO: "jetsmart-lv-ivo-sl" o "jetsmart-cc-awa"
        if low.startswith("jetsmart"):
            airline_icao, airline_name = "JAT", "JetSMART"
            m = re.search(r"(lv-[a-z0-9]{3}|cc-[a-z0-9]{3})", low)
            if m:
                matricula = normalize_matricula(m.group(1))
        else:
            m = FENIX_RE.match(name)
            if m:
                al = m.group("airline")
                airline_icao, airline_name = parse_airline_icao(al)
                matricula = normalize_matricula(m.group("matricula"))
            else:
                # fallback: buscar matrícula con guion estándar
                m2 = REG_STD.search(name)
                if m2:
                    matricula = normalize_matricula(m2.group("m"))

    return {
        "aircraft": aircraft,
        "airline": airline_icao,
        "airline_name": airline_name,
        "matricula": matricula,
        "folder": f"{top}\\{name}",
        "notes": "",
    }


def parse():
    entries = []
    with open(SRC, encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        parts = line.split("\\", 1)
        top = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else line.strip()
        if name.lower().endswith((".txt", ".zip")):
            continue
        entries.append(parse_line(top, name))
    return entries


def main():
    dry = "--dry" in sys.argv
    entries = parse()
    for i, e in enumerate(entries, 1):
        e["id"] = i
    print(f"Pareseadas {len(entries)} liveries.")
    if dry:
        for e in entries:
            print(f"  {e['aircraft']:6} {e['airline'] or '?':4} {e['matricula'] or '?':10} | {e['folder']}")
        return
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"liveries": entries}, f, ensure_ascii=False, indent=2)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
