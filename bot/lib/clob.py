"""Polymarket CLOB / Gamma helpers for historical price backfill."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


async def resolve_yes_token(client: httpx.AsyncClient, condition_id: str) -> str | None:
    """Return the YES clob-token-id for a market, or None if not found."""
    r = await client.get(f"{GAMMA}/markets", params={"condition_ids": condition_id}, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return None
    m = items[0]
    tokens = m.get("clobTokenIds")
    if isinstance(tokens, str):
        try:
            tokens = json.loads(tokens)
        except Exception:
            return None
    if not tokens:
        return None
    return str(tokens[0])  # YES token is index 0


async def fetch_prices_history(client: httpx.AsyncClient, token_id: str,
                               interval: str = "1d",
                               fidelity: int = 60) -> list[dict]:
    """Pull CLOB /prices-history for a YES token.

    Returns list of ``{"t": unix_seconds, "p": yes_price}``. Empty on error
    or no data. ``interval`` ∈ {1m, 5m, 1h, 6h, 1d, 1w, max}. ``fidelity``
    caps the number of buckets returned.
    """
    try:
        r = await client.get(
            f"{CLOB}/prices-history",
            params={"market": token_id, "interval": interval, "fidelity": fidelity},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    history = data.get("history") if isinstance(data, dict) else None
    if not history:
        return []
    out = []
    for pt in history:
        t = pt.get("t")
        p = pt.get("p")
        if t is None or p is None:
            continue
        try:
            out.append({"t": int(t), "p": float(p)})
        except (TypeError, ValueError):
            continue
    return out


def unix_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
