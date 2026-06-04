"""OSM Nominatim geocoding — place name -> lat/lon/bbox.

Nominatim usage policy:
  - max 1 req/s (we sleep 1.1s between calls in batch)
  - identifying User-Agent required
  - no heavy automated use without self-hosted
Docs: https://nominatim.org/release-docs/latest/api/Search/
"""
from __future__ import annotations

import asyncio

from lib.integrations import _safe_get

NOMINATIM = "https://nominatim.openstreetmap.org/search"


async def geocode_place(client, place: str, *, country: str | None = None,
                         limit: int = 5) -> dict:
    """Return geocoding candidates for a place name.

    Args:
        place: free-text query ("Rodynske, Ukraine").
        country: optional 2-letter ISO filter.
        limit: 1-10.
    Returns: {"results": [{"name", "lat", "lon", "bbox", "type",
                           "importance", "address"}], "count": N}
    """
    if not place.strip():
        return {"error": "place is required"}
    params = {
        "q": place,
        "format": "json",
        "addressdetails": 1,
        "limit": max(1, min(10, limit)),
    }
    if country:
        params["countrycodes"] = country.lower()
    r = await _safe_get(client, NOMINATIM, params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "results": []}
    try:
        data = r.json()
    except Exception as e:
        return {"error": f"parse: {e}", "results": []}
    out = []
    for item in data:
        bbox = item.get("boundingbox") or []  # [south, north, west, east]
        try:
            bbox_floats = [float(x) for x in bbox]
        except (TypeError, ValueError):
            bbox_floats = []
        out.append({
            "name": item.get("display_name"),
            "lat": float(item["lat"]) if item.get("lat") else None,
            "lon": float(item["lon"]) if item.get("lon") else None,
            "bbox_south_north_west_east": bbox_floats if len(bbox_floats) == 4 else None,
            "type": item.get("type"),
            "importance": item.get("importance"),
            "address": item.get("address"),
            "osm_id": item.get("osm_id"),
            "osm_type": item.get("osm_type"),
        })
    return {"count": len(out), "results": out}


async def geocode_batch(client, places: list[str], country: str | None = None) -> list[dict]:
    """Sequential batch geocode honouring 1 req/s Nominatim policy."""
    out = []
    for p in places:
        res = await geocode_place(client, p, country=country, limit=1)
        out.append({"query": p, "result": (res.get("results") or [None])[0]})
        await asyncio.sleep(1.1)
    return out
