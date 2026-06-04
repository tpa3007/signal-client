"""Open-Meteo — keyless weather API. Free for non-commercial.

Docs: https://open-meteo.com/en/docs
"""
from __future__ import annotations

from lib.integrations import _safe_get

FORECAST_API = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"


async def forecast(client, lat: float, lon: float, *, days: int = 7) -> dict:
    """7-16 day forecast (temp, precip, wind) for a point."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
        "forecast_days": max(1, min(16, days)),
        "timezone": "UTC",
    }
    r = await _safe_get(client, FORECAST_API, params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    daily = d.get("daily") or {}
    days_out = []
    for i, day in enumerate(daily.get("time", [])):
        days_out.append({
            "date": day,
            "temp_max": (daily.get("temperature_2m_max") or [None])[i] if i < len(daily.get("temperature_2m_max", [])) else None,
            "temp_min": (daily.get("temperature_2m_min") or [None])[i] if i < len(daily.get("temperature_2m_min", [])) else None,
            "precip_mm": (daily.get("precipitation_sum") or [None])[i] if i < len(daily.get("precipitation_sum", [])) else None,
            "wind_max": (daily.get("windspeed_10m_max") or [None])[i] if i < len(daily.get("windspeed_10m_max", [])) else None,
        })
    return {"lat": lat, "lon": lon, "days": days_out, "count": len(days_out)}


async def historical(client, lat: float, lon: float, *,
                      start_date: str, end_date: str) -> dict:
    """Historical daily weather. start_date and end_date in YYYY-MM-DD."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "UTC",
    }
    r = await _safe_get(client, ARCHIVE_API, params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    return d
