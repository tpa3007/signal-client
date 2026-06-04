"""Smart-money detection from Polymarket public activity (realized-PnL based).

The old Command W score was 28% timing_alpha + win_rate + HHI, with no
realized-PnL term and no market-type filter. Result: weather / "X Up or Down"
5-minute crypto bots maxed out the score (timing_alpha≈1.0, win_rate≈1.0 on
deterministic micro-markets) and were labelled "insider" — despite trading
$2 bets with NEGATIVE edge and ZERO research-category markets.

This module fixes the foundation:

  1. is_casino_market() — flags HFT/casino markets (weather, hourly/5-min
     crypto up-down, sports scores) that carry no insider signal.
  2. reconstruct_pnl() — rebuilds REALIZED PnL per market from the public
     /activity feed (BUY out, SELL/REDEEM in). A market counts as "closed"
     only if it has a SELL or REDEEM (open positions are excluded from
     realized PnL and win-rate).
  3. smart_money_profile() — splits realized performance into research vs
     casino buckets and returns the metrics that actually matter.
  4. smart_money_score() — ranks on realized research profit + research
     win-rate + early entry, and HARD-GATES the insider/smart labels behind
     a minimum number of CLOSED research markets and positive realized PnL.

Everything is computed from data the public data-api already returns; no new
keys or scraping required.
"""
from __future__ import annotations

import math
import re
from typing import Any

try:
    import requests
except Exception:  # noqa: BLE001
    requests = None

DATA_API = "https://data-api.polymarket.com"
LB_API = "https://lb-api.polymarket.com"


def fetch_leaderboard(window: str = "all", limit: int = 100) -> list[dict]:
    """Polymarket realized-profit leaderboard — the canonical smart-money list.
    Returns [{proxyWallet, amount, name, pseudonym}, ...] sorted by profit."""
    if requests is None:
        return []
    try:
        r = requests.get(f"{LB_API}/profit", params={"window": window, "limit": limit}, timeout=20)
        d = r.json()
        return d if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


def fetch_activity(wallet: str, limit: int = 200, offset: int = 0) -> list[dict]:
    if requests is None:
        return []
    try:
        r = requests.get(f"{DATA_API}/activity",
                         params={"user": wallet, "limit": limit, "offset": offset}, timeout=20)
        d = r.json()
        return d if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


def fetch_positions(wallet: str, limit: int = 500) -> list[dict]:
    if requests is None:
        return []
    try:
        r = requests.get(f"{DATA_API}/positions",
                         params={"user": wallet, "limit": limit}, timeout=20)
        d = r.json()
        return d if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


# Above this portfolio "value" a holder is the negRisk/AMM/settlement plumbing,
# not a human trader. The real profit leaderboard tops out around $22M, so any
# address reporting >$100M is a contract artifact (they hold the complementary
# "No" side of every outcome by mechanism, not conviction).
AMM_VALUE_THRESHOLD = 100_000_000.0


def fetch_portfolio_value(wallet: str) -> float | None:
    if requests is None:
        return None
    try:
        r = requests.get(f"{DATA_API}/value", params={"user": wallet}, timeout=15)
        d = r.json()
        if isinstance(d, list) and d:
            return _f(d[0].get("value"))
    except Exception:  # noqa: BLE001
        return None
    return None


def is_amm_or_contract(wallet: str, value: float | None = None) -> bool:
    """True if the address is AMM/negRisk/settlement plumbing, not a trader."""
    if value is None:
        value = fetch_portfolio_value(wallet)
    return value is not None and value >= AMM_VALUE_THRESHOLD


def fetch_market_holders(condition_id: str, limit: int = 20) -> list[dict]:
    """Top holders per outcome token for a market — answers 'who is in THIS
    market and on which side'. Returns the raw [{token, holders:[...]}] list."""
    if requests is None:
        return []
    try:
        r = requests.get(f"{DATA_API}/holders",
                         params={"market": condition_id, "limit": limit}, timeout=20)
        d = r.json()
        return d if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


def category_mix(activity: list[dict]) -> dict[str, Any]:
    """Robust even from a partial activity window: classify each event's market
    title as casino vs research. Returns shares by event count."""
    if not activity:
        return {"n": 0, "casino_share": None, "research_share": None}
    cas = sum(1 for a in activity if is_casino_market(a.get("title", ""), a.get("slug", "")))
    n = len(activity)
    return {"n": n, "casino_share": round(cas / n, 3), "research_share": round(1 - cas / n, 3)}


def realized_from_positions(positions: list[dict]) -> dict[str, Any]:
    """Sum realizedPnl from current /positions, split research vs casino by title.
    Reliable per-position (unlike activity-flow which can split BUY/REDEEM across
    pagination windows). Note: only covers positions still held/redeemable."""
    research_pnl = casino_pnl = 0.0
    research_n = casino_n = 0
    for p in positions:
        rp = _f(p.get("realizedPnl"))
        if is_casino_market(p.get("title", ""), p.get("slug", "")):
            casino_pnl += rp
            casino_n += 1
        else:
            research_pnl += rp
            research_n += 1
    return {
        "research_realized_pnl": round(research_pnl, 2),
        "casino_realized_pnl": round(casino_pnl, 2),
        "research_positions": research_n,
        "casino_positions": casino_n,
    }

# Categories that are bot/casino territory — fast, deterministic, no insider edge.
_CASINO_PATTERNS = re.compile(
    r"up or down"
    r"|highest temperature|lowest temperature|will it rain|°[cf]\b"
    r"|\bhourly\b|\b\d{1,2}:\d{2}\s?(am|pm)\b|\b\d{1,2}(am|pm)-\d{1,2}(am|pm)\b"
    r"|\b(5|10|15|30)\s?-?\s?min(ute)?\b"
    r"|\bnba\b|\bnfl\b|\bnhl\b|\bmlb\b|\bncaa\b|premier league|la liga|serie a"
    r"|\bvs\.?\b.*\b(win|beat|cover|spread|score)\b|\bmatch\b|\bgame \d"
    r"|\bf1\b|grand prix|ufc|boxing",
    re.I,
)

# Categories we actually research and where insider/asymmetry edges live.
_RESEARCH_HINTS = re.compile(
    r"election|president|mayor|governor|parliament|minister|referendum|senate|"
    r"valuation|ipo|fed|inflation|gdp|rate|central bank|ceasefire|war|sanction|"
    r"nuclear|treaty|coup|nomination|impeach|resign|cabinet|summit|deal|acquir|merger",
    re.I,
)


def is_casino_market(title: str, slug: str = "") -> bool:
    text = f"{title or ''} {slug or ''}"
    return bool(_CASINO_PATTERNS.search(text))


def is_research_market(title: str, slug: str = "") -> bool:
    """A market is 'research' if it is NOT casino and matches a research hint,
    or is simply not casino (default-include non-casino markets)."""
    if is_casino_market(title, slug):
        return False
    return True  # non-casino → eligible as research (research hints used for boosting)


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def reconstruct_pnl(activity: list[dict]) -> dict[str, dict]:
    """Return {condition_id: {flow, title, slug, casino, closed, buys, sells,
    redeems, first_ts, n_events}} from a wallet's /activity feed.

    flow = (SELL + REDEEM usd) - (BUY usd)   → realized cash flow.
    closed = has at least one SELL or REDEEM event.
    """
    per: dict[str, dict] = {}
    for a in activity or []:
        cid = a.get("conditionId")
        if not cid:
            continue
        typ = (a.get("type") or "").upper()
        usd = _f(a.get("usdcSize"))
        title = a.get("title") or ""
        slug = a.get("slug") or a.get("eventSlug") or ""
        ts = a.get("timestamp") or 0
        rec = per.get(cid)
        if rec is None:
            rec = per[cid] = {
                "flow": 0.0, "title": title, "slug": slug,
                "casino": is_casino_market(title, slug),
                "closed": False, "buys": 0.0, "sells": 0.0,
                "redeems": 0.0, "first_ts": ts, "n_events": 0,
            }
        rec["n_events"] += 1
        rec["first_ts"] = min(rec["first_ts"] or ts, ts) if ts else rec["first_ts"]
        if typ == "BUY":
            rec["flow"] -= usd
            rec["buys"] += usd
        elif typ == "SELL":
            rec["flow"] += usd
            rec["sells"] += usd
            rec["closed"] = True
        elif typ == "REDEEM":
            rec["flow"] += usd
            rec["redeems"] += usd
            rec["closed"] = True
    return per


def smart_money_profile(activity: list[dict]) -> dict[str, Any]:
    """Realized performance split into research vs casino buckets.

    Only CLOSED markets (have SELL/REDEEM) count toward realized PnL and
    win-rate, so open positions don't inflate the numbers.
    """
    per = reconstruct_pnl(activity)

    def bucket(items: list[dict]) -> dict[str, Any]:
        closed = [v for v in items if v["closed"] and v["buys"] > 0]
        pnl = sum(v["flow"] for v in closed)
        invested = sum(v["buys"] for v in closed)
        wins = sum(1 for v in closed if v["flow"] > 0)
        n = len(closed)
        return {
            "realized_pnl": round(pnl, 2),
            "invested": round(invested, 2),
            "roi": round(pnl / invested, 4) if invested > 0 else None,
            "closed_n": n,
            "wins": wins,
            "win_rate": round(wins / n, 4) if n else None,
        }

    research_items = [v for v in per.values() if not v["casino"]]
    casino_items = [v for v in per.values() if v["casino"]]
    research = bucket(research_items)
    casino = bucket(casino_items)

    total_markets = len(per)
    casino_share = round(len(casino_items) / total_markets, 3) if total_markets else 0.0

    return {
        "research": research,
        "casino": casino,
        "total_markets": total_markets,
        "casino_share": casino_share,
        "is_casino_bot": casino_share >= 0.80 and (research["closed_n"] or 0) < 5,
    }


# minimum CLOSED research markets before we trust a win-rate / label a wallet
MIN_RESEARCH_CLOSED = 8
SMART_PNL_MIN = 2_000.0      # realized research profit to be "smart"
INSIDER_PNL_MIN = 10_000.0   # realized research profit to be "insider" candidate


def smart_money_score(profile: dict[str, Any]) -> dict[str, Any]:
    """Score 0-100 driven by REALIZED research performance, plus a hard gate.

    Components (only research-category, closed markets):
      50%  realized PnL (log-scaled, $1k→low … $100k→full)
      30%  win-rate above market baseline (0.50→0, 0.75→full), confidence-damped
      20%  ROI quality (0→0, 0.5→full)
    Casino-bot wallets are forced to score 0 for insider/smart purposes.
    """
    r = profile.get("research", {})
    n = r.get("closed_n") or 0
    pnl = r.get("realized_pnl") or 0.0
    wr = r.get("win_rate")
    roi = r.get("roi")

    if profile.get("is_casino_bot") or n == 0:
        return {"score": 0.0, "label": "casino_or_noise", "gate": "no_research_history",
                "research_pnl": pnl, "research_closed_n": n, "research_win_rate": wr}

    score = 0.0
    # 50% realized PnL, log-scaled
    if pnl > 0:
        score += 50 * min(1.0, math.log10(max(1.0, pnl)) / math.log10(100_000))
    # 30% win-rate above 0.50, confidence-damped by sample size
    if wr is not None and n >= 3:
        conf = min(1.0, math.sqrt(n / 20))
        score += 30 * max(0.0, min(1.0, (wr - 0.50) / 0.25)) * conf
    # 20% ROI
    if roi is not None and roi > 0:
        score += 20 * min(1.0, roi / 0.5)

    score = round(min(100.0, score), 1)

    # ── Hard-gated labels ────────────────────────────────────────────────────
    gate = "ok"
    if n < MIN_RESEARCH_CLOSED:
        label = "thin_sample"
        gate = f"need >= {MIN_RESEARCH_CLOSED} closed research markets (have {n})"
    elif pnl >= INSIDER_PNL_MIN and (wr or 0) >= 0.60:
        label = "insider"
    elif pnl >= SMART_PNL_MIN and (wr or 0) >= 0.55:
        label = "smart"
    elif pnl > 0:
        label = "profitable"
    else:
        label = "unprofitable"

    return {
        "score": score, "label": label, "gate": gate,
        "research_pnl": pnl, "research_closed_n": n,
        "research_win_rate": wr, "research_roi": roi,
        "casino_share": profile.get("casino_share"),
    }
