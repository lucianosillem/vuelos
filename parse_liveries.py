#!/usr/bin/env python3
"""Vuelos — parsear carpetas de liveries de MSFS 2024 a registros estructurados.

Lee dos fuentes y las combina en liveries.json:
  data/liveries_folders.txt       → Fenix (A319/A320/A321) y PMDG 738, nomenclatura real:
                                     "ICAO_Aerolinea-Matricula-hash4" (omitir últimos 4)
  data/liveries_folders_legacy.txt→ liveries previas (FBW, FSLabs, iFly, Inibuilds,
                                     Microsoft, TFDi) con nombres libres + overrides.

Uso:  python3 parse_liveries.py [--dry]
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "liveries_folders.txt")
LEGACY = os.path.join(BASE, "data", "liveries_folders_legacy.txt")
OUT = os.path.join(BASE, "liveries.json")

# ── Tipos de avión por carpeta nivel-1 (formato nuevo) ─────────────
AIRCRAFT_BY_TOP = {
    "Fenix-319": "A319",
    "Fenix-320": "A320",
    "Fenix-321": "A321",
    "PMDG-738": "B738",
}
# ── Tipos de avión por carpeta nivel-1 (formato legacy) ────────────
AIRCRAFT_BY_TOP_LEGACY = {
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

# ── Parsing formato nuevo ──────────────────────────────────────────
FENIX_RE = re.compile(
    r"^(?P<airline>[a-z]{3})-(?P<matricula>[a-z0-9-]+?)(?:-[a-z0-9]{4})?$",
    re.IGNORECASE,
)
PMDG_UNDER_RE = re.compile(
    r"^(?P<airline>[a-z_]+?)_(?P<matricula>(?:lv|xa|cc|ec)-?[a-z0-9]{3,4}|[a-z0-9]{4,6})(?:_(?:or_)?\d{4})?$",
    re.IGNORECASE,
)


def normalize_matricula(raw):
    if not raw:
        return raw
    m = raw.strip().upper().replace("_", "")
    if re.fullmatch(r"(LV|CC|EC|EI|XA|HK|CS|OE|PR|PT|HB|A6|9H)[A-Z]{3}", m):
        return f"{m[:2]}-{m[2:]}"
    if re.fullmatch(r"N\d{3}[A-Z]{2}", m):
        return m
    if re.fullmatch(r"D-A[A-Z]{3}", m):
        return m
    if re.fullmatch(r"G-[A-Z]{4}", m):
        return m
    return m


def parse_airline_icao(raw):
    k = raw.strip().upper()
    if k in Airlines:
        return Airlines[k]
    if len(k) == 3:
        return (k, None)
    return ("", None)


def parse_new(top, name):
    """Formato nuevo: Fenix-3XX / PMDG-738 con nomenclatura real."""
    aircraft = AIRCRAFT_BY_TOP.get(top, "")
    airline_icao, airline_name, matricula = "", "", ""

    if top.startswith("PMDG"):
        m = PMDG_UNDER_RE.match(name)
        if m:
            al_key = m.group("airline").upper()
            if "AEROLINEAS" in al_key or "ARG" in al_key:
                airline_icao, airline_name = "ARG", "Aerolíneas Argentinas"
            elif "AEROMEXICO" in al_key:
                airline_icao, airline_name = "AMX", "Aeroméxico"
            mat = normalize_matricula(m.group("matricula"))
            if re.fullmatch(r"(LV|XA)-?[A-Z]{3}", mat):
                matricula = mat
        else:
            low = name.lower()
            if "aerolineas" in low:
                airline_icao, airline_name = "ARG", "Aerolíneas Argentinas"
                tok = name.split()[-1].upper()
                if re.fullmatch(r"[A-Z]{3}", tok):
                    matricula = f"LV-{tok}"

    elif top.startswith("Fenix"):
        low = name.lower().strip()
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
                m2 = re.search(r"\b(?P<m>(?:LV|CC|EC|EI|D-|G-|N|XA|HK|CS|OE|PR|PT|HB|A6|9H)-?[A-Z0-9]{2,5})\b", name)
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


# ── Parsing formato legacy (v2: keywords + overrides) ──────────────
AIRLINES_KEY = [
    ("lufthansa", "DLH", "Lufthansa"),
    ("british", "BAW", "British Airways"),
    ("emirates", "UAE", "Emirates"),
    ("aerolineas argentinas", "ARG", "Aerolíneas Argentinas"),
    ("aerolineas", "ARG", "Aerolíneas Argentinas"),
    ("arg", "ARG", "Aerolíneas Argentinas"),
    ("jetsmart", "JAT", "JetSMART"),
    ("sky airline", "SKU", "Sky Airline"),
    ("easyjet", "EZY", "easyJet"),
    ("vueling", "VLG", "Vueling"),
    ("latambrazil", "TAM", "LATAM Brasil"),
    ("latamchile", "LAN", "LATAM Chile"),
    ("latam", "LAN", "LATAM"),
    ("ups", "UPS", "UPS"),
    ("gec", "GEC", "GECAS"),
    ("dalc", "GEC", "GECAS"),
    ("ibe", "IBE", "Iberia"),
]
OVERRIDES = [
    ("FBW A320NX Sky Airline CC-DBL", ("CC-DBL", "SKU", "Sky Airline")),
    ("fbw-easyjetneo", ("", "EZY", "easyJet")),
    ("FlyByWire_A320neo_DLH Pack 4K", ("", "DLH", "Lufthansa")),
    ("flybywire-a320neo-LatamBrazil_Pack", ("", "TAM", "LATAM Brasil")),
    ("flybywire-a320neo-LatamChile_Pack", ("", "LAN", "LATAM Chile")),
    ("flybywire-a320neo-Vueling_2Pack", ("", "VLG", "Vueling")),
    ("raimbotrax_a380_British_Airways_GXLEL_Clean", ("G-XLEL", "BAW", "British Airways")),
    ("raimbotrax_a380_British_Airways_GXLEL_Dirty", ("G-XLEL", "BAW", "British Airways")),
    ("raimbotrax_a380_Emirates_New_livery_A6EOK", ("A6-EOK", "UAE", "Emirates")),
    ("raimbotrax_a380_Lufthansa_DAIMG", ("D-AIMG", "DLH", "Lufthansa")),
    ("iFly Boeing 737 MAX 8 Aerolineas Argentinas LV-KKD", ("LV-KKD", "ARG", "Aerolíneas Argentinas")),
    ("iFly Boeing 737 MAX 8 Aerolineas Argentinas LV-KKE", ("LV-KKE", "ARG", "Aerolíneas Argentinas")),
    ("ifly-aircraft-737max8-arg-lvgvd", ("LV-GVD", "ARG", "Aerolíneas Argentinas")),
    ("ifly-aircraft-737max8-ARG-LVKID", ("LV-KID", "ARG", "Aerolíneas Argentinas")),
    ("inibuilds-aircraft-a350-900-ibe-njm", ("EC-NJM", "IBE", "Iberia")),
    ("IniBuilds A330-200 ARG LV-GKP", ("LV-GKP", "ARG", "Aerolíneas Argentinas")),
    ("IniBuilds A330-200 ARG LV-KAO", ("LV-KAO", "ARG", "Aerolíneas Argentinas")),
    ("microsoft-aircraft-a330-200-AR", ("", "ARG", "Aerolíneas Argentinas")),
    ("tfdidesign-aircraft-md-11fge-n840td", ("N840TD", "", "")),
    ("tfdidesign-aircraft-md-11fpw-n850td", ("N850TD", "", "")),
    ("tfdidesign-aircraft-md-11ge-n820td", ("N820TD", "", "")),
    ("tfdidesign-aircraft-md-11pw-n830td", ("N830TD", "", "")),
    ("tfdidesign-md11f-ups-commons", ("", "UPS", "UPS")),
    ("tfdidesign-md11-gec-new-commons", ("", "GEC", "GECAS")),
    ("tfdidesign-md11-gec-new-dalca-missmatch", ("", "GEC", "GECAS")),
    ("tfdidesign-md11-gec-new-dalcb-missmatch", ("", "GEC", "GECAS")),
    ("tfdidesign-md11-gec-new-dalcb", ("", "GEC", "GECAS")),
    ("tfdidesign-md11-gec-new-dalcc-farewell", ("", "GEC", "GECAS")),
    ("tfdidesign-md11-gec-new-dalcc", ("", "GEC", "GECAS")),
    ("tfdidesign-md11-gec-new-dalcd-missmatch", ("", "GEC", "GECAS")),
    ("tfdidesign-md11-gec-new-dalcd", ("", "GEC", "GECAS")),
]
for _n in range(250, 296):
    if _n in (272, 277, 279, 280, 282, 283, 285):
        continue
    OVERRIDES.append((f"tfdidesign-md11f-ups-n{_n}up", (f"N{_n}UP", "UPS", "UPS")))

TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_NON_REG = {
    "clean", "dirty", "commons", "missmatch", "mismatch", "farewell",
    "liveries", "livery", "pack", "fleet", "new", "design", "aircraft",
    "installation", "instructions", "2pack", "4k", "a320", "a320nx",
    "a319", "a321", "a380", "a330", "a350", "a32x", "737", "737max8",
    "md11", "md11f", "max8", "neo", "arg", "ibe", "fnx", "fsl", "sl",
    "up", "td", "ia", "ge", "pw", "fge", "fpw", "ea",
}


def matricula_from_tokens(tokens):
    for t in tokens:
        tl = t.lower()
        if tl in _NON_REG:
            continue
        u = t.upper()
        if re.fullmatch(r"(CC|LV|A6|EC)-[A-Z]{3}", u):
            return u
        if re.fullmatch(r"D-A[A-Z]{3}", u):
            return u
        if re.fullmatch(r"G-[A-Z]{4}", u):
            return u
        if re.fullmatch(r"N\d{3}[A-Z]{2}", u):
            return u
        if re.fullmatch(r"N\d{4}[A-Z]?", u):
            return u
        if re.fullmatch(r"(?:CC|LV|A6|EC)[A-Z]{3}", u) and tl not in _NON_REG:
            return f"{u[:2]}-{u[2:]}"
        if re.fullmatch(r"G[A-Z]{4}", u):
            return f"G-{u[1:]}"
        if re.fullmatch(r"N\d{3}[A-Z]{2}", u):
            return u
    return ""


def apply_overrides(full):
    fl = full.lower()
    for key, val in OVERRIDES:
        if key.lower() in fl:
            return val
    return None


def parse_legacy(top, name):
    aircraft = AIRCRAFT_BY_TOP_LEGACY.get(top, "")
    full = f"{top}\\{name}"
    ov = apply_overrides(full)
    if ov:
        mat, airline_icao, airline_name = ov
        return {
            "aircraft": aircraft, "airline": airline_icao,
            "airline_name": airline_name, "matricula": mat,
            "folder": full, "notes": "",
        }
    airline_icao, airline_name = "", ""
    for kw, icao, nm in AIRLINES_KEY:
        if kw in full.lower():
            airline_icao, airline_name = icao, nm
            break
    if not airline_icao and re.search(r"(?i)(?:^|[-_ ])ar(?:[-_ ]|$)", full):
        airline_icao, airline_name = "ARG", "Aerolíneas Argentinas"
    mat = matricula_from_tokens([t for t in TOKEN_SPLIT.split(full) if t])
    return {
        "aircraft": aircraft, "airline": airline_icao,
        "airline_name": airline_name, "matricula": mat,
        "folder": full, "notes": "",
    }


def parse_file(path, kind):
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        parts = line.split("\\", 1)
        top = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else line.strip()
        if name.lower().endswith((".txt", ".zip")):
            continue
        if kind == "new":
            entries.append(parse_new(top, name))
        else:
            entries.append(parse_legacy(top, name))
    return entries


def main():
    dry = "--dry" in sys.argv
    entries = parse_file(SRC, "new") + parse_file(LEGACY, "legacy")
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
