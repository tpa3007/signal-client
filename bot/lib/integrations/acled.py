"""ACLED client - new developer-portal OAuth2 scheme.

Auth flow:
  POST https://acleddata.com/oauth/token
    body: grant_type=password&client_id=acled&username=<email>&password=<pwd>
  -> access_token (Bearer, ~1 hour)

Data:
  GET https://acleddata.com/api/acled/read
    Authorization: Bearer <access_token>
    plus query params: event_date=...|...|asc, country=Ukraine, etc.

Docs: https://acleddata.com/api-documentation/
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from lib.integrations import _safe_get, USER_AGENT

OAUTH_URL = "https://acleddata.com/oauth/token"
API_BASE = "https://acleddata.com/api/acled/read"


# In-memory token cache (one Python process; lives for token lifetime)
_TOKEN_CACHE: dict = {"access_token": None, "expires_at": 0.0}


_LAST_AUTH_ERROR: str | None = None


async def _get_token(client) -> str | None:
    """Return a valid bearer token (cached for its lifetime), or None on failure.
    On failure, stores the reason in module global _LAST_AUTH_ERROR.
    """
    global _LAST_AUTH_ERROR
    now = time.time()
    if _TOKEN_CACHE["access_token"] and _TOKEN_CACHE["expires_at"] > now + 60:
        return _TOKEN_CACHE["access_token"]
    email = os.getenv("ACLED_EMAIL")
    password = os.getenv("ACLED_PASSWORD")
    if not email or not password:
        _LAST_AUTH_ERROR = "ACLED_EMAIL / ACLED_PASSWORD not set"
        return None
    try:
        r = await client.post(
            OAUTH_URL,
            data={
                "grant_type": "password",
                "client_id": "acled",
                "scope": "authenticated",  # required per official docs
                "username": email,
                "password": password,
            },
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=20,
        )
        if r.status_code != 200:
            _LAST_AUTH_ERROR = f"oauth status {r.status_code}: {r.text[:200]}"
            return None
        body = r.json()
    except Exception as e:
        _LAST_AUTH_ERROR = f"{type(e).__name__}: {e}"
        return None
    token = body.get("access_token")
    expires = float(body.get("expires_in", 3600))
    if token:
        _TOKEN_CACHE["access_token"] = token
        _TOKEN_CACHE["expires_at"] = now + expires
        _LAST_AUTH_ERROR = None
    else:
        _LAST_AUTH_ERROR = f"no access_token in response: {body}"
    return token


def _bbox_around(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return (south, north, west, east) bbox for an approximate radius."""
    # Rough: 1 deg lat = 111km. Longitude scales with cos(lat).
    import math
    d_lat = radius_km / 111.0
    d_lon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return (lat - d_lat, lat + d_lat, lon - d_lon, lon + d_lon)


def _date_window(days_back: int) -> tuple[str, str]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(1, days_back))
    return start.isoformat(), end.isoformat()


async def _read(client, params: dict) -> dict:
    """Authenticated GET to ACLED read endpoint with Bearer token."""
    token = await _get_token(client)
    if not token:
        return {
            "error": "ACLED auth failed",
            "detail": _LAST_AUTH_ERROR,
            "hint": "Confirm ACLED_EMAIL / ACLED_PASSWORD in bot/.env.",
        }
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    r = await _safe_get(client, API_BASE, params=params, headers=headers, timeout=30)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        if r.status_code == 403:
            return {
                "error": "ACLED account API access not yet approved",
                "detail": r.text[:200],
                "hint": ("Login + OAuth token both succeed, but read returns 403. "
                         "ACLED approves API access manually per account. "
                         "Contact access@acleddata.com or use the support form at "
                         "https://acleddata.com/contact/ requesting API access for "
                         "your registered email. No code change needed - adapter "
                         "will work automatically once approved."),
            }
        if r.status_code != 200:
            return {
                "error": f"ACLED read status {r.status_code}",
                "detail": r.text[:200],
            }
        return r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}


async def events_near(client, lat: float, lon: float, *, radius_km: float = 30,
                       days_back: int = 14, limit: int = 50) -> dict:
    """Events within radius_km of (lat,lon) in the last N days."""
    south, north, west, east = _bbox_around(lat, lon, radius_km)
    start, end = _date_window(days_back)
    params = {
        "latitude": f"{south}|{north}",
        "longitude": f"{west}|{east}",
        "event_date": f"{start}|{end}",
        "limit": max(1, min(500, limit)),
    }
    data = await _read(client, params)
    if "error" in data:
        return data
    events = data.get("data") or []
    out = []
    for ev in events[:limit]:
        out.append({
            "event_date": ev.get("event_date"),
            "event_type": ev.get("event_type"),
            "sub_event_type": ev.get("sub_event_type"),
            "actor1": ev.get("actor1"),
            "actor2": ev.get("actor2"),
            "location": ev.get("location"),
            "admin1": ev.get("admin1"),
            "admin2": ev.get("admin2"),
            "country": ev.get("country"),
            "fatalities": ev.get("fatalities"),
            "lat": ev.get("latitude"),
            "lon": ev.get("longitude"),
            "notes": (ev.get("notes") or "")[:200],
            "source": ev.get("source"),
        })
    return {
        "count": len(out),
        "bbox": {"south": south, "north": north, "west": west, "east": east},
        "date_range": {"start": start, "end": end},
        "events": out,
    }


async def events_by_country(client, country: str, *, days_back: int = 14,
                             limit: int = 100,
                             event_type: str | None = None) -> dict:
    """Events in a country (e.g. 'Ukraine', 'Israel') in the last N days."""
    start, end = _date_window(days_back)
    params = {
        "country": country,
        "event_date": f"{start}|{end}",
        "limit": max(1, min(500, limit)),
    }
    if event_type:
        params["event_type"] = event_type
    data = await _read(client, params)
    if "error" in data:
        return data
    events = data.get("data") or []
    return {
        "country": country,
        "date_range": {"start": start, "end": end},
        "count": len(events),
        "events": [
            {
                "event_date": e.get("event_date"),
                "event_type": e.get("event_type"),
                "sub_event_type": e.get("sub_event_type"),
                "location": e.get("location"),
                "admin1": e.get("admin1"),
                "fatalities": e.get("fatalities"),
                "actor1": e.get("actor1"),
            }
            for e in events[:limit]
        ],
    }


async def actor_search(client, actor: str, *, days_back: int = 30,
                        limit: int = 50) -> dict:
    """Events involving a named actor (partial match), recent window."""
    start, end = _date_window(days_back)
    params = {
        "actor1": actor,
        "event_date": f"{start}|{end}",
        "limit": max(1, min(500, limit)),
    }
    data = await _read(client, params)
    if "error" in data:
        return data
    events = data.get("data") or []
    return {
        "actor": actor,
        "date_range": {"start": start, "end": end},
        "count": len(events),
        "events": [
            {
                "event_date": e.get("event_date"),
                "event_type": e.get("event_type"),
                "location": e.get("location"),
                "country": e.get("country"),
                "fatalities": e.get("fatalities"),
                "actor2": e.get("actor2"),
            }
            for e in events[:limit]
        ],
    }
