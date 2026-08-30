#!/usr/bin/env python3
"""Vuelos — buscador de vuelos para VATSIM + liveries + SimBrief.

Patrón task-tracker/medicacion: FastAPI de archivo único + SQLite.
Rutas relativas (/api/*, /static/*) para que el gateway agregue el prefijo.

Endpoints:
  GET  /                      → UI
  GET  /api/airports?q=       → autocomplete aeropuertos
  GET  /api/airlines?q=       → autocomplete aerolíneas
  GET  /api/countries         → países con aeropuertos
  GET  /api/search?...        → rutas reales (origen/país/aerolínea/max_hours)
  GET  /api/aircraft          → tipos de avión presentes en liveries
  GET  /api/liveries?aircraft=→ liveries instaladas (filtro por avión)
  POST /api/liveries          → agregar livery
  DELETE /api/liveries/<id>   → quitar livery
  GET  /api/plan?...          → planear vuelo (ruta real o inventada + fltnum + SimBrief)
  GET  /api/vatsim/callsign?cs= → chequeo callsign en VATSIM en vivo
"""
import json
import math
import os
import random
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import uvicorn

BASE = Path(__file__).parent
DB = BASE / "vuelos.db"
LIVERIES_FILE = BASE / "liveries.json"
PORT = int(os.environ.get("VUELOS_PORT", "18652"))

# Velocidad crucero típica para estimar duración (kt). Ajustable.
CRUISE_KT = 450.0
# Bloque de numeración para vuelos inventados (pax estándar).
FLTNUM_LO, FLTNUM_HI = 1000, 5999


# ── Liveries (persistencia JSON) ───────────────────────────────────
# Cada livery: {id, aircraft (tipo ICAO), airline (ICAO), airline_name,
#               matricula (registro), folder (carpeta MSFS), notes}
_lock = threading.Lock()
_liveries = []


def load_liveries():
    global _liveries
    if LIVERIES_FILE.exists():
        try:
            data = json.loads(LIVERIES_FILE.read_text())
            _liveries = data.get("liveries", [])
        except Exception:
            _liveries = []
    else:
        _liveries = []
    return _liveries


def save_liveries():
    LIVERIES_FILE.write_text(json.dumps({"liveries": _liveries}, indent=2, ensure_ascii=False))


def next_livery_id():
    return max((l.get("id", 0) for l in _liveries), default=0) + 1


# ── VATSIM live (cache corto) ──────────────────────────────────────
_vatsim = {"ts": 0.0, "callsigns": set()}


def vatsim_callsigns(force=False):
    now = time.time()
    if force or now - _vatsim["ts"] > 120:
        try:
            req = urllib.request.urlopen(
                "https://data.vatsim.net/v3/vatsim-data.json", timeout=15
            )
            data = json.loads(req.read().decode())
            cs = set()
            for p in data.get("pilots", []):
                cs.add(p.get("callsign", ""))
            for p in data.get("prefiles", []):
                cs.add(p.get("callsign", ""))
            _vatsim["callsigns"] = cs
            _vatsim["ts"] = now
        except Exception:
            pass  # mantener cache vieja / vacía
    return _vatsim["callsigns"]


# ── DB helpers ─────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def haversine_km(a, b):
    if not (a and b):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def airport_by(code):
    code = code.strip().upper()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM airports WHERE icao=? OR iata=? LIMIT 1", (code, code)
        ).fetchone()
    return dict(row) if row else None


def liveries_airlines(aircraft: str = ""):
    """Códigos de aerolínea (ICAO/IATA) que tienen liveries cargadas.
    Si se pasa `aircraft`, solo las aerolíneas con liveries de ese tipo de avión.
    Devuelve un set de códigos (vacío = no filtrar)."""
    acft = aircraft.strip().upper()
    codes = set()
    for l in _liveries:
        if acft and l.get("aircraft", "").upper() != acft:
            continue
        al = l.get("airline", "").strip().upper()
        if al:
            codes.add(al)
    return codes


def liveries_aircraft_types():
    """Tipos de avión (ICAO) presentes en las liveries cargadas."""
    return {l.get("aircraft", "").upper() for l in _liveries if l.get("aircraft")}


def est_duration_hours(km):
    if not km:
        return None
    return km / (CRUISE_KT * 1.852)


# ── Lógica de plan de vuelo ────────────────────────────────────────
def invent_flight_number(airline_icao, n_tries=60):
    """Número de vuelo inventado: nomenclatura estándar (3-4 dígitos),
    sin colisión con VATSIM en vivo."""
    live = vatsim_callsigns()
    seen = set()
    for _ in range(n_tries):
        n = random.randint(FLTNUM_LO, FLTNUM_HI)
        if n in seen:
            continue
        seen.add(n)
        cs = f"{airline_icao}{n}"
        if cs not in live:
            return n, cs
    n = random.randint(FLTNUM_LO, FLTNUM_HI)
    return n, f"{airline_icao}{n}"


def simbrief_url(airline_icao, fltnum, acft_type, orig_icao, dest_icao, deph=None, depm=None):
    p = [
        ("airline", airline_icao),
        ("fltnum", str(fltnum)),
        ("type", acft_type),
        ("orig", orig_icao),
        ("dest", dest_icao),
    ]
    if deph is not None:
        p.append(("deph", str(deph).zfill(2)))
    if depm is not None:
        p.append(("depm", str(depm).zfill(2)))
    q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in p)
    return f"https://dispatch.simbrief.com/options/custom?{q}"


# ── FastAPI app ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    load_liveries()
    yield


app = FastAPI(title="Vuelos", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/static/{path:path}")
def static(path: str):
    file = (BASE / "static" / path).resolve()
    if not str(file).startswith(str((BASE / "static").resolve())):
        raise HTTPException(403)
    if not file.is_file():
        raise HTTPException(404)
    return FileResponse(file)


# ── Autocomplete ───────────────────────────────────────────────────
@app.get("/api/airports")
def api_airports(q: str = Query("", max_length=40), limit: int = Query(12, le=25)):
    q = q.strip().upper()
    if len(q) < 2:
        return []
    with get_db() as conn:
        rows = conn.execute(
            """SELECT iata, icao, name, city, country FROM airports
               WHERE iata LIKE ? OR icao LIKE ? OR upper(name) LIKE ? OR upper(city) LIKE ?
               ORDER BY CASE WHEN iata=? OR icao=? THEN 0 ELSE 1 END, name
               LIMIT ?""",
            (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", q, q, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/airlines")
def api_airlines(q: str = Query("", max_length=40), limit: int = Query(12, le=25)):
    q = q.strip().upper()
    if len(q) < 2:
        return []
    with get_db() as conn:
        rows = conn.execute(
            """SELECT iata, icao, name, callsign, country FROM airlines
               WHERE iata LIKE ? OR icao LIKE ? OR upper(name) LIKE ? OR upper(callsign) LIKE ?
               ORDER BY CASE WHEN iata=? OR icao=? THEN 0 ELSE 1 END, name
               LIMIT ?""",
            (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", q, q, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/countries")
def api_countries():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT country, COUNT(*) n FROM airports
               WHERE country IS NOT NULL AND country != ''
               GROUP BY country ORDER BY country"""
        ).fetchall()
    return [{"country": r["country"], "n": r["n"]} for r in rows]


# ── Rutas reales ───────────────────────────────────────────────────
@app.get("/api/search")
def api_search(
    origin: str = "",
    country: str = "",
    airline: str = "",
    aircraft: str = "",
    max_hours: float = Query(2.0, ge=0.5, le=12),
    limit: int = Query(60, le=200),
):
    # Filtrar por aerolíneas que tienen liveries cargadas (si hay alguna).
    # Si se especificó un tipo de avión, solo aerolíneas con liveries de ese tipo.
    allowed = liveries_airlines(aircraft)
    with get_db() as conn:
        sql = """SELECT r.airline, r.src, r.dst, r.equipment,
                        a.name src_name, a.city src_city, a.country src_country,
                        a.lat src_lat, a.lon src_lon, a.icao src_icao,
                        d.name dst_name, d.city dst_city, d.country dst_country,
                        d.lat dst_lat, d.lon dst_lon, d.icao dst_icao,
                        al.icao airline_icao, al.name airline_name
                 FROM routes r
                 JOIN airports a ON a.iata = r.src
                 JOIN airports d ON d.iata = r.dst
                 LEFT JOIN airlines al ON al.iata = r.airline
                 WHERE 1=1"""
        params = []
        if origin:
            ap = airport_by(origin)
            if not ap or not ap.get("iata"):
                raise HTTPException(404, f"Aeropuerto no encontrado: {origin}")
            sql += " AND r.src = ?"
            params.append(ap["iata"])
        elif country:
            sql += " AND upper(a.country) LIKE ?"
            params.append(f"%{country.upper()}%")
        if airline:
            al = airline.strip().upper()
            sql += " AND (r.airline = ? OR r.airline IN (SELECT iata FROM airlines WHERE icao=?))"
            params.extend([al, al])
        if allowed:
            # solo rutas cuya aerolínea tenga livery (por ICAO o IATA)
            placeholders = ",".join("?" * len(allowed))
            sql += (
                f" AND (al.icao IN ({placeholders}) OR r.airline IN ({placeholders}))"
            )
            params.extend(list(allowed) * 2)
        sql += " GROUP BY r.airline, r.src, r.dst ORDER BY a.country, r.airline, r.dst"
        sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql, params).fetchall()

    out = []
    for r in rows:
        a = {"lat": r["src_lat"], "lon": r["src_lon"]}
        b = {"lat": r["dst_lat"], "lon": r["dst_lon"]}
        km = haversine_km(a, b)
        dur = est_duration_hours(km)
        if dur is not None and dur > max_hours:
            continue
        out.append(
            {
                "airline": r["airline"],
                "airline_icao": r["airline_icao"],
                "airline_name": r["airline_name"],
                "src": r["src"],
                "dst": r["dst"],
                "src_icao": r["src_icao"],
                "dst_icao": r["dst_icao"],
                "src_name": f"{r['src_city']}, {r['src_country']}" if r["src_city"] else r["src_name"],
                "dst_name": f"{r['dst_city']}, {r['dst_country']}" if r["dst_city"] else r["dst_name"],
                "equipment": r["equipment"],
                "km": round(km) if km else None,
                "hours": round(dur, 1) if dur else None,
                "real": True,
            }
        )
    return out


# ── Números de vuelo asociados a una ruta ──────────────────────────
@app.get("/api/route/flights")
def api_route_flights(
    airline: str = "",
    src: str = "",
    dst: str = "",
    aircraft: str = "",
    n: int = Query(4, ge=1, le=8),
):
    """Dada una ruta (airline + src + dst), genera números de vuelo plausibles
    en la nomenclatura estándar de la aerolínea, verificados contra VATSIM,
    cada uno con su URL de SimBrief."""
    if not src or not dst:
        raise HTTPException(400, "src y dst son obligatorios")
    ap = airport_by(src)
    dp = airport_by(dst)
    if not ap or not ap.get("icao"):
        raise HTTPException(404, f"Aeropuerto de origen no encontrado: {src}")
    if not dp or not dp.get("icao"):
        raise HTTPException(404, f"Aeropuerto de destino no encontrado: {dst}")

    # aerolínea: si viene IATA o ICAO, resolver ICAO (callsign)
    airline_icao = airline.strip().upper()
    airline_name = None
    if airline_icao:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM airlines WHERE icao=? OR iata=? LIMIT 1",
                (airline_icao, airline_icao),
            ).fetchone()
        if row:
            airline_icao = row["icao"] or airline_icao
            airline_name = row["name"]
    if not airline_icao:
        raise HTTPException(400, "airline es obligatoria para generar el callsign")

    acft = aircraft.strip().upper() or "B738"
    live = vatsim_callsigns()

    results = []
    tried = set()
    while len(results) < n:
        num = random.randint(FLTNUM_LO, FLTNUM_HI)
        if num in tried:
            continue
        tried.add(num)
        cs = f"{airline_icao}{num}"
        results.append(
            {
                "flight_number": num,
                "callsign": cs,
                "in_use": cs in live,
                "simbrief_url": simbrief_url(airline_icao, num, acft, ap["icao"], dp["icao"]),
            }
        )
    return {
        "src": ap["icao"],
        "dst": dp["icao"],
        "airline": airline_icao,
        "airline_name": airline_name,
        "aircraft": acft,
        "flights": results,
    }


# ── Liveries ───────────────────────────────────────────────────────
@app.get("/api/aircraft")
def api_aircraft():
    types = sorted({l.get("aircraft", "") for l in _liveries if l.get("aircraft")})
    return types


@app.get("/api/liveries")
def api_liveries(aircraft: str = ""):
    if aircraft:
        return [l for l in _liveries if l.get("aircraft", "").upper() == aircraft.strip().upper()]
    return _liveries


@app.post("/api/liveries")
def api_liveries_add(payload: dict):
    aircraft = str(payload.get("aircraft", "")).strip().upper()
    airline = str(payload.get("airline", "")).strip().upper()
    matricula = str(payload.get("matricula", "")).strip().upper()
    if not aircraft:
        raise HTTPException(400, "aircraft es obligatorio")
    with _lock:
        entry = {
            "id": next_livery_id(),
            "aircraft": aircraft,
            "airline": airline,
            "airline_name": str(payload.get("airline_name", "")).strip(),
            "matricula": matricula,
            "folder": str(payload.get("folder", "")).strip(),
            "notes": str(payload.get("notes", "")).strip(),
        }
        _liveries.append(entry)
        save_liveries()
    return entry


@app.delete("/api/liveries/{lid}")
def api_liveries_del(lid: int):
    global _liveries
    with _lock:
        before = len(_liveries)
        _liveries = [l for l in _liveries if l.get("id") != lid]
        if len(_liveries) == before:
            raise HTTPException(404, "livery no encontrado")
        save_liveries()
    return {"ok": True}


# ── Chequeo VATSIM ─────────────────────────────────────────────────
@app.get("/api/vatsim/callsign")
def api_vatsim_cs(cs: str):
    cs = cs.strip().upper()
    live = vatsim_callsigns(force=True)
    return {"callsign": cs, "in_use": cs in live, "checked_at": int(time.time())}


# ── Plan de vuelo ──────────────────────────────────────────────────
@app.get("/api/plan")
def api_plan(
    origin: str,
    dest: str = "",
    airline: str = "",
    aircraft: str = "",
    max_hours: float = Query(2.0, ge=0.5, le=12),
    invent: bool = Query(False),
):
    """Planea un vuelo: busca ruta real desde origin; si no hay (o invent=True),
    inventa una ruta plausible dentro de max_hours + número de vuelo libre en
    VATSIM + URL SimBrief."""
    ap = airport_by(origin)
    if not ap:
        raise HTTPException(404, f"Aeropuerto de origen no encontrado: {origin}")
    if not ap.get("icao"):
        raise HTTPException(400, f"{origin}: sin código ICAO para SimBrief")
    orig_icao = ap["icao"]

    # aerolínea
    airline_row = None
    if airline:
        with get_db() as conn:
            airline_row = conn.execute(
                "SELECT * FROM airlines WHERE icao=? OR iata=? LIMIT 1",
                (airline.strip().upper(), airline.strip().upper()),
            ).fetchone()
        if not airline_row:
            raise HTTPException(404, f"Aerolínea no encontrada: {airline}")
    if airline_row and not airline_row["icao"]:
        raise HTTPException(400, f"{airline}: sin código ICAO para callsign/SimBrief")
    airline_icao = airline_row["icao"] if airline_row else None

    # tipo de avión para SimBrief
    acft = aircraft.strip().upper()
    if not acft and _liveries:
        # default: primer tipo con livery
        acft = sorted({l["aircraft"] for l in _liveries})[0]

    # 1) buscar ruta real directa
    route = None
    if dest:
        dp = airport_by(dest)
        if not dp or not dp.get("iata"):
            raise HTTPException(404, f"Aeropuerto de destino no encontrado: {dest}")
        with get_db() as conn:
            sql = "SELECT * FROM routes WHERE src=? AND dst=?"
            params = [ap["iata"], dp["iata"]]
            if airline_row and airline_row["iata"]:
                sql += " AND (airline=? OR airline=?)"
                params.extend([airline_row["iata"], airline])
            route = conn.execute(sql + " LIMIT 1", params).fetchone()
        dest_ap = dp
    else:
        # 2) buscar rutas reales desde origen dentro de max_hours
        candidates = api_search(origin=origin, max_hours=max_hours, airline=airline, limit=80)
        if candidates and not invent:
            pick = random.choice(candidates[:20])
            dest_ap = airport_by(pick["dst"])
            route = {"airline": pick["airline"], "src": ap["iata"], "dst": pick["dst"]}
        else:
            # 3) inventar destino: aeropuerto dentro del radio, ideal mismo país
            km_max = max_hours * CRUISE_KT * 1.852
            dest_ap = invent_destination(ap, km_max, exclude=ap.get("iata"))
            route = None
            if not dest_ap:
                raise HTTPException(404, "No encontré un destino plausible dentro del radio")

    if not dest_ap:
        raise HTTPException(404, "No encontré destino")

    real = route is not None

    # aerolínea: ruta real → su aerolínea; inventada → la pedida o una local
    if real and not airline_row:
        with get_db() as conn:
            airline_row = conn.execute(
                "SELECT * FROM airlines WHERE iata=? LIMIT 1", (route["airline"],)
            ).fetchone()
        if airline_row:
            airline_icao = airline_row["icao"] or airline_row["iata"]

    if not airline_icao:
        airline_icao = dest_ap.get("country", "XX").upper()[:2] + "X"

    fltnum, callsign = invent_flight_number(airline_icao)

    km = haversine_km(
        {"lat": ap["lat"], "lon": ap["lon"]},
        {"lat": dest_ap["lat"], "lon": dest_ap["lon"]},
    )
    dur = est_duration_hours(km)
    url = simbrief_url(airline_icao, fltnum, acft or "B738", orig_icao, dest_ap["icao"])

    return {
        "origin": {"icao": orig_icao, "iata": ap.get("iata"), "name": ap["name"]},
        "dest": {
            "icao": dest_ap["icao"],
            "iata": dest_ap.get("iata"),
            "name": dest_ap["name"],
            "city": dest_ap.get("city"),
            "country": dest_ap.get("country"),
        },
        "airline": {"icao": airline_icao, "name": airline_row["name"] if airline_row else None},
        "aircraft": acft or None,
        "flight_number": fltnum,
        "callsign": callsign,
        "route_real": real,
        "km": round(km) if km else None,
        "hours": round(dur, 1) if dur else None,
        "vatsim": {"callsign": callsign, "in_use": callsign in vatsim_callsigns()},
        "simbrief_url": url,
    }


def invent_destination(origin_ap, km_max, exclude=None, tries=15):
    """Elige un aeropuerto dentro del radio, preferentemente del mismo país
    del origen y con código IATA (aeropuertos comerciales), que no sea el origen
    y que NO tenga ruta real directa desde el origen (para no inventar algo que existe)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM airports WHERE lat IS NOT NULL AND lon IS NOT NULL "
            "AND icao IS NOT NULL AND icao != ''"
        ).fetchall()
        real_dests = set(
            r["dst"]
            for r in conn.execute(
                "SELECT DISTINCT dst FROM routes WHERE src=?", (origin_ap["iata"],)
            ).fetchall()
        )
    same_country = [r for r in rows if r["country"] == origin_ap["country"] and r["iata"] != exclude]
    other_country = [r for r in rows if r["country"] != origin_ap["country"] and r["iata"] != exclude]
    # prioridad: mismo país con IATA → otro país con IATA → resto
    pool = (
        [r for r in same_country if r["iata"]]
        + [r for r in other_country if r["iata"]]
        + [r for r in same_country if not r["iata"]]
        + [r for r in other_country if not r["iata"]]
    )
    random.shuffle(pool)
    for r in pool:
        if r["iata"] in real_dests:
            continue
        km = haversine_km(
            {"lat": origin_ap["lat"], "lon": origin_ap["lon"]},
            {"lat": r["lat"], "lon": r["lon"]},
        )
        if km and km <= km_max and km >= 50:
            return dict(r)
    return None


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
