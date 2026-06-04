"""External keyless integration clients.

Each module exports an async client function. All clients:
  - use a stable User-Agent identifying Signal so the public APIs accept us
  - return clean Python dicts/lists (no raw HTTP objects)
  - have a hard timeout
  - swallow transient errors into structured {"error": ...} dicts
  - never block on rate limits - return what they have plus a warning
"""
from __future__ import annotations

import logging
import os

# Prevent INFO-level httpx logs from printing full URLs with query-string API keys.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Stable identifying UA - many free APIs require an identifying header.
# Email is optional; set SIGNAL_CONTACT_EMAIL env var to populate.
_CONTACT = os.getenv("SIGNAL_CONTACT_EMAIL", "noreply@signal.local")
USER_AGENT = f"SignalResearchBot/1.0 (+{_CONTACT})"


async def _safe_get(client, url, params=None, headers=None, timeout=20):
    """Thin GET wrapper with consistent network error handling.

    Deliberately does not call raise_for_status(): individual adapters often
    need status_code to distinguish rate limits, bad query syntax, and approval
    gates (e.g. ACLED/ReliefWeb) without losing the response body.
    """
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    try:
        return await client.get(url, params=params, headers=h, timeout=timeout)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


async def _safe_post(client, url, params=None, json=None, data=None, headers=None, timeout=20):
    """Thin POST wrapper mirroring _safe_get."""
    h = {"User-Agent": USER_AGENT}
    if json is not None:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    try:
        return await client.post(url, params=params, json=json, data=data, headers=h, timeout=timeout)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}
