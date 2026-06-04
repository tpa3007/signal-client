"""Kalshi prediction market client — CFTC-regulated US market.

No API key required for reading public market prices.
Particularly strong divergence on: US elections, Fed rate decisions,
macro events (CPI, NFP, debt ceiling).  Kalshi's participant base skews
toward institutional / financially-literate traders, producing systematic
divergences from Polymarket's more global retail crowd.

Endpoint: https://trading-api.kalshi.com/trade-api/v2/markets
Docs:     https://trading-api.kalshi.com/trade-api/v2/redoc
"""
from __future__ import annotations

import re
import requests

_MARKETS_URL = "https://trading-api.kalshi.com/trade-api/v2/markets"

_STOP = frozenset({
    "will", "the", "be", "a", "an", "of", "in", "on", "by", "to", "for",
    "is", "are", "was", "were", "has", "have", "had", "at", "from", "that",
    "this", "it", "its", "with", "or", "and", "not", "no", "yes",
    "next", "new", "first", "last", "win", "won", "lose", "lost",
    "before", "after", "during", "when", "who", "which", "where", "how",
    "what", "if", "then", "than", "more", "most", "any", "some", "all",
    "get", "got", "may", "might", "could", "would", "should",
    "between", "above", "below", "over", "under",
    "does", "do", "did", "end", "year", "month", "week", "day",
    "least", "many", "much", "their", "they", "about", "into",
    "other", "another", "also", "only", "just", "even", "still",
    "2024", "2025", "2026", "2027", "there", "been", "being", "least",
})


def _tokenize(text: str) -> frozenset[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return frozenset(t for t in tokens if t not in _STOP and len(t) >= 3)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def fetch_all_markets(timeout: int = 20) -> list[dict]:
    """Fetch all active Kalshi yes/no markets.

    Returns list of {ticker, title, yes_price, url} dicts.
    yes_price is normalised to 0.0–1.0.
    Returns empty list on auth failure or network error (fails silently).
    """
    markets: list[dict] = []
    cursor: str | None = None
    headers = {"Accept": "application/json"}

    for _ in range(10):  # 200/page → up to 2,000 markets
        params: dict = {"limit": 200, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(_MARKETS_URL, params=params, headers=headers, timeout=timeout)
        except Exception as exc:
            print(f"[Kalshi] network error: {exc}")
            return markets

        if r.status_code in (401, 403):
            # Kalshi trading API requires auth even for reads.
            # Set KALSHI_API_KEY env var (get from kalshi.com → Settings → API)
            import os  # noqa: PLC0415
            api_key = os.environ.get("KALSHI_API_KEY", "").strip()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
                continue  # retry with auth
            print("[Kalshi] Auth required — no KALSHI_API_KEY set. Skipping.")
            return markets
        if r.status_code != 200:
            print(f"[Kalshi] unexpected status {r.status_code}")
            break

        try:
            data = r.json()
        except Exception as exc:
            print(f"[Kalshi] parse error: {exc}")
            break

        for m in data.get("markets", []):
            # Only binary (yes/no) markets
            if m.get("market_type") not in ("yes_no", None):
                continue
            # yes_bid can be 0–100 (cents) or 0.0–1.0 depending on API version
            raw_yes = (
                m.get("yes_bid")
                or m.get("last_price")
                or m.get("yes_price")
                or m.get("yes_ask")
                or 0
            )
            try:
                raw_yes = float(raw_yes)
            except (TypeError, ValueError):
                continue
            # Normalise: if >1.0 it's in cents (0–100 scale)
            yes_price = raw_yes / 100.0 if raw_yes > 1.0 else raw_yes
            if not (0.01 <= yes_price <= 0.99):
                continue

            event_ticker = m.get("event_ticker") or m.get("ticker", "")
            title = m.get("title") or m.get("short_name") or m.get("subtitle") or ""
            if not title:
                continue
            markets.append({
                "ticker": m.get("ticker", ""),
                "title": title,
                "yes_price": round(yes_price, 4),
                "url": f"https://kalshi.com/markets/{event_ticker}",
            })

        cursor = data.get("cursor")
        if not cursor or not data.get("markets"):
            break

    return markets


def find_match(
    question: str,
    markets: list[dict],
    min_jaccard: float = 0.40,
) -> dict | None:
    """Find best-matching Kalshi market for a Polymarket question.

    Raised from 0.28→0.40 (2026-05-27) to reduce false-match divergence.
    Returns {ticker, title, yes_price, url, match_score} or None.
    """
    q_tokens = _tokenize(question)
    if not q_tokens:
        return None
    best: dict | None = None
    best_score = 0.0
    for m in markets:
        title = m.get("title", "")
        if not title:
            continue
        score = _jaccard(q_tokens, _tokenize(title))
        if score > best_score:
            best_score = score
            best = m
    if best is None or best_score < min_jaccard:
        return None
    return {**best, "match_score": round(best_score, 3)}
