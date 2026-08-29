#!/usr/bin/env python3
"""Vuelos — sync de datasets OpenFlights a SQLite.

Lee data/{airports,airlines,routes}.dat y construye vuelos.db.
Uso:  python3 sync_data.py
"""
import csv
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
DB = os.path.join(BASE, "vuelos.db")


def _clean(v):
    if v is None:
        return None
    v = v.strip()
    return None if v in ("", "\\N") else v


def load_airports(conn):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS airports")
    cur.execute(
        """CREATE TABLE airports (
            id INTEGER PRIMARY KEY,
            iata TEXT, icao TEXT, name TEXT, city TEXT,
            country TEXT, lat REAL, lon REAL
        )"""
    )
    rows = []
    with open(os.path.join(DATA, "airports.dat"), encoding="utf-8", newline="") as f:
        for r in csv.reader(f):
            if len(r) < 12:
                continue
            rows.append(
                (
                    int(r[0]),
                    _clean(r[4]),  # iata
                    _clean(r[5]),  # icao
                    r[1].strip(),
                    r[2].strip(),
                    r[3].strip(),
                    float(r[6]) if r[6] else None,
                    float(r[7]) if r[7] else None,
                )
            )
    cur.executemany(
        "INSERT INTO airports (id,iata,icao,name,city,country,lat,lon) "
        "VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    cur.execute("CREATE INDEX idx_airports_iata ON airports(iata)")
    cur.execute("CREATE INDEX idx_airports_icao ON airports(icao)")
    cur.execute("CREATE INDEX idx_airports_country ON airports(country)")
    return len(rows)


def load_airlines(conn):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS airlines")
    cur.execute(
        """CREATE TABLE airlines (
            id INTEGER PRIMARY KEY,
            iata TEXT, icao TEXT, name TEXT, callsign TEXT,
            country TEXT, active TEXT
        )"""
    )
    rows = []
    with open(os.path.join(DATA, "airlines.dat"), encoding="utf-8", newline="") as f:
        for r in csv.reader(f):
            if len(r) < 8:
                continue
            rows.append(
                (
                    int(r[0]),
                    _clean(r[3]),  # iata
                    _clean(r[4]),  # icao
                    r[1].strip(),
                    _clean(r[5]),  # callsign
                    _clean(r[6]),  # country
                    _clean(r[7]),  # active
                )
            )
    cur.executemany(
        "INSERT INTO airlines (id,iata,icao,name,callsign,country,active) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    cur.execute("CREATE INDEX idx_airlines_iata ON airlines(iata)")
    cur.execute("CREATE INDEX idx_airlines_icao ON airlines(icao)")
    return len(rows)


def load_routes(conn):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS routes")
    cur.execute(
        """CREATE TABLE routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            airline TEXT, src TEXT, dst TEXT,
            stops INTEGER, equipment TEXT
        )"""
    )
    rows = []
    seen = set()
    with open(os.path.join(DATA, "routes.dat"), encoding="utf-8", newline="") as f:
        for r in csv.reader(f):
            if len(r) < 9:
                continue
            al = _clean(r[0])
            src = _clean(r[2])
            dst = _clean(r[4])
            stops = _clean(r[7])
            equip = _clean(r[8])
            if not (al and src and dst):
                continue
            key = (al, src, dst)
            if key in seen:
                continue
            seen.add(key)
            try:
                n = int(stops) if stops else 0
            except ValueError:
                n = 0
            rows.append((al, src, dst, n, equip))
    cur.executemany(
        "INSERT INTO routes (airline,src,dst,stops,equipment) VALUES (?,?,?,?,?)",
        rows,
    )
    cur.execute("CREATE INDEX idx_routes_src ON routes(src)")
    cur.execute("CREATE INDEX idx_routes_airline ON routes(airline)")
    cur.execute("CREATE INDEX idx_routes_dst ON routes(dst)")
    return len(rows)


def main():
    conn = sqlite3.connect(DB)
    try:
        na = load_airports(conn)
        nl = load_airlines(conn)
        nr = load_routes(conn)
        conn.commit()
        print(f"OK: {na} aeropuertos, {nl} aerolíneas, {nr} rutas -> {DB}")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
