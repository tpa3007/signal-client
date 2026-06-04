"""Polymarket Gamma API client - filtered for geopolitics/politics, long-resolution."""
from __future__ import annotations
import json
import re
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import httpx

import config

GAMMA = "https://gamma-api.polymarket.com"
LAST_FETCH_STATS: dict[str, int] = {}
CLOB = "https://clob.polymarket.com"


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    yes_price: float
    volume: float
    liquidity: float | None
    end_date: str
    days_to_end: float
    tokens: list[str]
    vertical: str = "unknown"
    theme_tags: list[str] | None = None
    no_price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    yes_entry_price: float | None = None
    no_entry_price: float | None = None
    start_date: str | None = None   # ISO timestamp from Gamma startDate field


def classify_theme_tags(q: str) -> list[str]:
    """Return thematic risk tags such as iran_cluster or us_primary_2026."""
    ql = q.lower()
    tags = []
    for tag, keywords in config.THEME_TAGS.items():
        if any(_keyword_in_question(kw, ql) for kw in keywords):
            tags.append(tag)
    return sorted(set(tags))


def _keyword_in_question(keyword: str, ql: str) -> bool:
    """Match short ticker-like keywords as whole terms to avoid substring leaks."""
    kw = keyword.lower()
    if kw.strip() != kw:
        return kw in ql
    if " " not in kw and kw.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", ql) is not None
    return kw in ql


def _classify_vertical(q: str) -> str | None:
    """Return vertical name if question matches, else None. Excludes sports/esports leaks."""
    ql = q.lower()
    if any(ex in ql for ex in config.VERTICAL_EXCLUDE_KEYWORDS):
        return None

    scores = {}
    for vertical, kws in config.VERTICALS.items():
        score = sum(1 for kw in kws if _keyword_in_question(kw, ql))
        if score:
            scores[vertical] = score
    if not scores:
        return None

    # US state/local/election language should not be swallowed by the old broad
    # geopolitics bucket just because candidate names overlap with national news.
    us_score = scores.get("us_politics", 0)
    intl_score = scores.get("international_geopolitics", 0)
    if us_score and not intl_score:
        return "us_politics"
    if intl_score and not us_score:
        return "international_geopolitics"
    if us_score and intl_score:
        if any(kw in ql for kw in ("primary", "governor", "senate", "ballot", "nominee", "nomination")):
            return "us_politics"
        return "international_geopolitics"

    return max(scores.items(), key=lambda item: item[1])[0]


def _matches_vertical(q: str) -> bool:
    return _classify_vertical(q) is not None


def _days_until(iso: str) -> float | None:
    if not iso:
        return None
    try:
        end = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    return (end - now).total_seconds() / 86400


def _market_age_days(iso: str | None) -> float | None:
    """Return how many days ago an ISO timestamp was (positive = in the past)."""
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    return (now - ts).total_seconds() / 86400


def _float_or_none(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if 0.0 <= out <= 1.0 else None


def _execution_prices(
    yes_price: float,
    no_price: float,
    best_bid: float | None,
    best_ask: float | None,
    spread: float | None,
) -> tuple[float, float, float | None]:
    """
    Approximate executable entry prices.

    Gamma exposes YES best bid/ask on many markets. Buying YES uses YES ask.
    Buying NO can be approximated as 1 - YES bid when a YES bid is present.
    Falls back to outcome prices when orderbook fields are unavailable.
    """
    computed_spread = spread
    if computed_spread is None and best_bid is not None and best_ask is not None:
        computed_spread = max(0.0, best_ask - best_bid)
    yes_entry = best_ask if best_ask is not None else yes_price
    no_entry = (1.0 - best_bid) if best_bid is not None else no_price
    return yes_entry, no_entry, computed_spread


async def fetch_active_markets(
    client: httpx.AsyncClient,
    max_pages: int = 20,
    vertical: str | None = None,
    sort: str = "volume",
    min_volume_usd: float | None = None,
    days_min: int | None = None,
    days_max: int | None = None,
    discovery_mode: bool = False,
    min_yes_price: float = 0.02,
    max_yes_price: float = 0.98,
) -> list[Market]:
    """Pull active markets, filter to vertical + volume + resolution window.

    Args:
        sort: 'volume' (default) sorts by volume desc.
              'none' preserves Gamma's order.
              'liquidity_asc' sorts by liquidity ascending — finds neglected
              markets that big desks haven't priced efficiently yet.
        min_volume_usd: override config.MIN_VOLUME_USD floor.
        days_min / days_max: override the resolution window.
        discovery_mode: if True, skips vertical filter entirely — returns ALL
              structured binary markets including economics, health, crypto etc.
              Use this in Command G to avoid blind spots.
        min_yes_price / max_yes_price: executable price window. Discovery scans
              can widen this to keep cheap optionality and high-confidence bubble
              shorts in the candidate universe.
    """
    min_volume_usd = min_volume_usd if min_volume_usd is not None else config.MIN_VOLUME_USD
    days_min = days_min if days_min is not None else config.MIN_DAYS_TO_RESOLUTION
    days_max = days_max if days_max is not None else config.MAX_DAYS_TO_RESOLUTION

    # For discovery: scan both volume-sorted (popular) AND liquidity-sorted (neglected)
    # to avoid only seeing the heavily-watched top-volume markets.
    if sort == "liquidity_asc":
        api_order, api_asc = "liquidity", "true"
    else:
        api_order, api_asc = "volume", "false"

    # Gamma API silently caps limit at 100 items per page.
    # Use PAGE_SIZE=100 and offset accordingly to avoid skipping markets.
    PAGE_SIZE = 100
    out: list[Market] = []
    seen: set[str] = set()
    stats = {
        "raw": 0,
        "sports_esports": 0,
        "vertical": 0,
        "duplicate": 0,
        "volume": 0,
        "date_window": 0,
        "bad_prices": 0,
        "price_extreme": 0,
        "accepted": 0,
    }
    for page in range(max_pages):
        try:
            r = await client.get(f"{GAMMA}/markets", params={
                "limit": PAGE_SIZE, "offset": page * PAGE_SIZE,
                "active": "true", "closed": "false",
                "order": api_order, "ascending": api_asc,
            }, timeout=30)
            r.raise_for_status()
            data = r.json()
            page_data = data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            print(f"[markets] page {page} error: {e}")
            break
        if not page_data:
            break

        for m in page_data:
            stats["raw"] += 1
            q = m.get("question", "") or ""

            # Exclude sports/esports unconditionally
            if any(ex in q.lower() for ex in config.VERTICAL_EXCLUDE_KEYWORDS):
                stats["sports_esports"] += 1
                continue

            if discovery_mode:
                # Accept everything that passes the sports exclude, classify best-effort
                v = _classify_vertical(q) or "other"
            else:
                v = _classify_vertical(q)
                if v is None:
                    stats["vertical"] += 1
                    continue
                if vertical:
                    if vertical == "geopolitics":
                        if v not in config.GEOPOLITICS_VERTICALS:
                            stats["vertical"] += 1
                            continue
                    elif v != vertical:
                        stats["vertical"] += 1
                        continue

            cid = m.get("conditionId") or m.get("id")
            if not cid or cid in seen:
                stats["duplicate"] += 1
                continue

            try:
                vol = float(m.get("volumeNum") or m.get("volume") or 0)
            except (TypeError, ValueError):
                stats["volume"] += 1
                continue
            if vol < min_volume_usd:
                stats["volume"] += 1
                continue

            days = _days_until(m.get("endDate") or "")
            if days is None or not (days_min <= days <= days_max):
                stats["date_window"] += 1
                continue

            prices = m.get("outcomePrices")
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except Exception:
                    stats["bad_prices"] += 1
                    continue
            if not prices or len(prices) < 2:
                stats["bad_prices"] += 1
                continue
            try:
                yes = float(prices[0])
            except (TypeError, ValueError):
                stats["bad_prices"] += 1
                continue
            if not (min_yes_price < yes < max_yes_price):
                stats["price_extreme"] += 1
                continue
            try:
                no = float(prices[1])
            except (TypeError, ValueError):
                no = 1.0 - yes

            best_bid = _float_or_none(m.get("bestBid"))
            best_ask = _float_or_none(m.get("bestAsk"))
            spread = _float_or_none(m.get("spread"))
            yes_entry, no_entry, spread = _execution_prices(
                yes, no, best_bid, best_ask, spread
            )

            tokens = m.get("clobTokenIds")
            if isinstance(tokens, str):
                try:
                    tokens = json.loads(tokens)
                except Exception:
                    tokens = []

            try:
                liq = float(m.get("liquidityNum") or m.get("liquidity") or 0) or None
            except (TypeError, ValueError):
                liq = None

            theme_tags = classify_theme_tags(q)

            seen.add(cid)
            stats["accepted"] += 1
            out.append(Market(
                condition_id=cid,
                question=q,
                slug=m.get("slug") or "",
                yes_price=yes,
                volume=vol,
                liquidity=liq,
                end_date=m.get("endDate") or "",
                days_to_end=days,
                tokens=tokens or [],
                vertical=v,
                theme_tags=theme_tags,
                no_price=no,
                best_bid=best_bid,
                best_ask=best_ask,
                spread=spread,
                yes_entry_price=yes_entry,
                no_entry_price=no_entry,
                start_date=m.get("startDate") or None,
            ))
        await asyncio.sleep(0.2)

    if sort == "volume":
        out.sort(key=lambda x: x.volume, reverse=True)
    global LAST_FETCH_STATS
    LAST_FETCH_STATS = stats
    return out
