"""OpenSky Network — ADS-B flight tracking. Anonymous read.

Anonymous limit: 400 credits/day. Each call costs 1-4 credits depending
on bbox size. Authenticated accounts get 4000 credits/day.

Docs: https://opensky-network.org/apidoc/rest.html
"""
from __future__ import annotations

from lib.integrations import _safe_get

API = "https://opensky-network.org/api"


async def states_in_bbox(client, *, south: float, north: float,
                          west: float, east: float) -> dict:
    """All aircraft positions in a bounding box. Snapshot, not historical."""
    params = {
        "lamin": south,
        "lamax": north,
        "lomin": west,
        "lomax": east,
    }
    r = await _safe_get(client, f"{API}/states/all", params=params, timeout=30)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "states": []}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}", "states": []}
    states = d.get("states") or []
    # Position vector order (per docs):
    # 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
    # 5 lon, 6 lat, 7 baro_altitude, 8 on_ground, 9 velocity, 10 heading,
    # 11 vertical_rate, 12 sensors, 13 geo_altitude, 14 squawk, 15 spi, 16 position_source
    out = []
    for s in states:
        if len(s) < 17:
            continue
        out.append({
            "icao24": s[0],
            "callsign": (s[1] or "").strip(),
            "origin_country": s[2],
            "lon": s[5],
            "lat": s[6],
            "baro_altitude_m": s[7],
            "on_ground": s[8],
            "velocity_ms": s[9],
            "heading_deg": s[10],
            "geo_altitude_m": s[13],
            "squawk": s[14],
        })
    return {
        "snapshot_time_unix": d.get("time"),
        "count": len(out),
        "states": out[:200],  # cap output
    }


async def flights_in_window(client, *, begin_unix: int, end_unix: int,
                              airport_icao: str | None = None) -> dict:
    """Arrivals or departures over a time window for a specific airport.
    Window must be <= 7 days. Without airport, lists all flights (heavy)."""
    if (end_unix - begin_unix) > 7 * 86400:
        return {"error": "window must be ≤ 7 days"}
    if airport_icao:
        url = f"{API}/flights/departure"
        params = {"airport": airport_icao, "begin": begin_unix, "end": end_unix}
    else:
        url = f"{API}/flights/all"
        params = {"begin": begin_unix, "end": end_unix}
    r = await _safe_get(client, url, params=params, timeout=30)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "flights": []}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}", "flights": []}
    flights = d if isinstance(d, list) else []
    return {
        "count": len(flights),
        "flights": [
            {
                "icao24": f.get("icao24"),
                "callsign": (f.get("callsign") or "").strip(),
                "first_seen_unix": f.get("firstSeen"),
                "last_seen_unix": f.get("lastSeen"),
                "est_departure_airport": f.get("estDepartureAirport"),
                "est_arrival_airport": f.get("estArrivalAirport"),
            }
            for f in flights[:100]
        ],
    }
