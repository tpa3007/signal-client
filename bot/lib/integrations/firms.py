"""NASA FIRMS — Active fire / thermal anomaly data.

Auth: MAP_KEY in URL path. Free from
https://firms.modaps.eosdis.nasa.gov/api/map_key/
Returns CSV. We parse to dicts.

API docs: https://firms.modaps.eosdis.nasa.gov/api/
"""
from __future__ import annotations

import csv
import io
import math
import os

from lib.integrations import _safe_get

API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Available source datasets:
#   MODIS_NRT, MODIS_SP, VIIRS_NOAA20_NRT, VIIRS_SNPP_NRT, LANDSAT_NRT.
# Default = VIIRS_SNPP_NRT (375m, near real-time, best for conflict zones).
DEFAULT_SOURCE = "VIIRS_SNPP_NRT"


def _bbox_around(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    d_lat = radius_km / 111.0
    d_lon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    # FIRMS expects west,south,east,north
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


async def thermal_anomalies(client, lat: float, lon: float, *,
                             radius_km: float = 30,
                             days_back: int = 7,
                             source: str = DEFAULT_SOURCE) -> dict:
    """Active fire / thermal anomaly detections in a radius.

    Args:
        radius_km: 5-200 (FIRMS area endpoint allows up to ~10 deg span).
        days_back: 1-10 (FIRMS area NRT covers last ~10 days).
        source: see module DEFAULT_SOURCE.
    """
    key = os.getenv("NASA_FIRMS_MAP_KEY")
    if not key:
        return {"error": "NASA_FIRMS_MAP_KEY missing in env"}
    days_back = max(1, min(5, days_back))  # NRT area endpoint limit
    west, south, east, north = _bbox_around(lat, lon, radius_km)
    bbox_str = f"{west},{south},{east},{north}"
    url = f"{API_BASE}/{key}/{source}/{bbox_str}/{days_back}"
    r = await _safe_get(client, url, timeout=45)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        text = r.text
    except Exception as e:
        return {"error": f"read body: {e}"}
    if text.strip().lower().startswith("invalid"):
        return {"error": "FIRMS rejected request", "detail": text[:200]}
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        try:
            rlat = float(row.get("latitude", 0))
            rlon = float(row.get("longitude", 0))
        except (TypeError, ValueError):
            continue
        rows.append({
            "lat": rlat,
            "lon": rlon,
            "brightness": _to_float(row.get("bright_ti4") or row.get("brightness")),
            "confidence": row.get("confidence"),
            "acq_date": row.get("acq_date"),
            "acq_time": row.get("acq_time"),
            "satellite": row.get("satellite"),
            "frp": _to_float(row.get("frp")),
            "daynight": row.get("daynight"),
        })
    # Sort newest first
    rows.sort(key=lambda x: (x["acq_date"] or "", x["acq_time"] or ""), reverse=True)
    return {
        "source": source,
        "bbox": {"south": south, "north": north, "west": west, "east": east},
        "days_back": days_back,
        "count": len(rows),
        "detections": rows[:200],  # cap for readability
    }


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
