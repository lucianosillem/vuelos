#!/usr/bin/env python3
"""Vuelos — parsear carpetas de liveries de MSFS 2024 a registros estructurados.

Lee data/liveries_folders.txt (formato "Nivel1\\Nivel2") y produce liveries.json
con campos: id, aircraft (tipo ICAO), airline (ICAO), airline_name, matricula, folder, notes.
Solo procesa carpetas de liveries (descarta .txt/.zip sueltos).

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
    "FBW A320": "A20N",
    "FBW A380": "A388",
    "Fenix": "A20N",     # Fenix A32x — default A320neo (ajustable)
    "FSLabs": "A20N",
    "iFly": "B38M",
    "Inibuilds": "A359",
    "Microsoft": "A332",
    "TFDi": "MD11",
}

# ── Aerolíneas por keywords en el nombre (orden: más específico primero) ──
AIRLINES = [
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
    ("delta", "DAL", "Delta Air Lines"),
]

# ── Patrones de matrícula ──────────────────────────────────────────
# Se aplica a cada TOKEN (separado por no-alfanumérico, incl. guion bajo)
TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")
# Prefijos de matrícula reconocibles por país/región
_REG_PREFIXES = {
    "CC": "CC-", "LV": "LV-", "A6": "A6-", "EC": "EC-",
    "G": "G-", "D-A": "D-A", "N": "",
}
# Palabras que NUNCA son matrícula
_NON_REG = {
    "clean", "dirty", "commons", "missmatch", "mismatch", "farewell",
    "liveries", "livery", "pack", "fleet", "new", "design", "aircraft",
    "installation", "instructions", "2pack", "4k", "a320", "a320nx",
    "a319", "a321", "a380", "a330", "a350", "a32x", "737", "737max8",
    "md11", "md11f", "max8", "neo", "arg", "ibe", "fnx", "fsl", "sl",
    "up", "td", "ia", "ge", "pw", "fge", "fpw", "ea",
}


def tokenize(full):
    # conserva guiones para matrículas tipo CC-DBL, LV-KKD
    return [t for t in re.split(r"[^A-Za-z0-9-]+", full) if t]


# ── Overrides manuales (nombres de carpeta ambiguos) ───────────────
# clave = substring del path completo; valor = (matricula, airline_icao, airline_name)
# Se aplican ANTES del auto-detect.
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
    ("FNX_320_IAE_SL_JetSmartCCAWA_4K", ("CC-AWA", "JAT", "JetSMART")),
    ("FNX_320_IAE_SL_JetSmartLVHEK_4K", ("LV-HEK", "JAT", "JetSMART")),
    ("fnx-aircraft-320-JESLV-KDP-IAE", ("LV-KDP", "JAT", "JetSMART")),
    ("fnx-aircraft-320-jetsmart-lv-ivo-sl", ("LV-IVO", "JAT", "JetSMART")),
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

# ups n###up auto (no override necesario): tfdidesign-md11f-ups-n250up → N250UP
# md11f-gec? none. La lista UPS n2xxup cubierta por auto-detect + estos:
for _n in range(250, 296):
    if _n == 272 or _n == 277 or _n == 279 or _n == 280 or _n == 282 or _n == 283 or _n == 285:
        continue  # matrículas que no existen según la lista real
    OVERRIDES.append((f"tfdidesign-md11f-ups-n{_n}up", (f"N{_n}UP", "UPS", "UPS")))


def apply_overrides(full):
    """Busca un override por substring; devuelve (matricula, airline_icao, airline_name) o None."""
    fl = full.lower()
    for key, val in OVERRIDES:
        if key.lower() in fl:
            return val
    return None


def matricula_from_tokens(tokens):
    """Busca el primer token que sea una matrícula válida."""
    for t in tokens:
        tl = t.lower()
        if tl in _NON_REG:
            continue
        u = t.upper()
        # estándar con guion: CC-ABC, LV-ABC, A6-ABC, D-AABC, G-ABCD, N123AB, EC-ABC
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
        # compacto sin guion: GXLEL, A6EOK, CCAWA, LVHEK, DAIMG, LVKID, N840TD
        if re.fullmatch(r"(?:CC|LV|A6|EC)[A-Z]{3}", u) and tl not in _NON_REG:
            return f"{u[:2]}-{u[2:]}"
        if re.fullmatch(r"D-A[A-Z]{3}", u):
            return u
        if re.fullmatch(r"G[A-Z]{4}", u):
            return f"G-{u[1:]}"
        if re.fullmatch(r"N\d{3}[A-Z]{2}", u):
            return u
    return ""


def normalize_matricula(raw):
    return raw.upper() if raw else raw


def parse():
    entries = []
    with open(SRC, encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]

    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        parts = line.split("\\")
        top = parts[0].strip()
        name = parts[-1].strip() if len(parts) > 1 else line.strip()
        full = line.replace("\\", " ")

        # descartar archivos sueltos
        if name.lower().endswith((".txt", ".zip")):
            continue

        aircraft = AIRCRAFT_BY_TOP.get(top, "")

        # 1) override manual (cubre matrícula Y aerolínea)
        ov = apply_overrides(full)
        if ov:
            mat, airline_icao, airline_name = ov
            entries.append(
                {
                    "aircraft": aircraft,
                    "airline": airline_icao,
                    "airline_name": airline_name,
                    "matricula": mat,
                    "folder": line,
                    "notes": "",
                }
            )
            continue

        # 2) auto-detect aerolínea
        airline_icao, airline_name = "", ""
        for kw, icao, nm in AIRLINES:
            if kw in full.lower():
                airline_icao, airline_name = icao, nm
                break
        # "AR" suelto = Aerolíneas Argentinas (microsoft-aircraft-a330-200-AR)
        if not airline_icao and re.search(r"(?i)(?:^|[-_ ])ar(?:[-_ ]|$)", full):
            airline_icao, airline_name = "ARG", "Aerolíneas Argentinas"

        # 3) matrícula por tokens (robusto a guiones bajos/espacios)
        mat = matricula_from_tokens(tokenize(full))

        entries.append(
            {
                "aircraft": aircraft,
                "airline": airline_icao,
                "airline_name": airline_name,
                "matricula": mat,
                "folder": line,
                "notes": "",
            }
        )
    return entries


def main():
    dry = "--dry" in sys.argv
    entries = parse()
    # ids secuenciales
    for i, e in enumerate(entries, 1):
        e["id"] = i
    print(f"Pareseadas {len(entries)} liveries.")
    if dry:
        for e in entries:
            print(f"  {e['aircraft']:6} {e['airline'] or '?':4} {e['matricula'] or '?':10} | {e['folder']}")
        return
    payload = {"liveries": entries}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
