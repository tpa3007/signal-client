"""Polymarket CLOB whale order detector.

A "whale" is a market participant placing orders large enough to indicate
either insider information or extreme high-conviction positioning.

Detection logic (three independent signals, any triggers):

  1. RESTING_ORDER  — single price level in the order book where
     size * price >= RESTING_THRESHOLD_USD ($50k default).
     A $50k bid at price 0.15 = 333,333 YES contracts = someone is
     betting $50k on a 15% outcome.  That is unusual.

  2. DEPTH_ACCUMULATION — total side depth >= DEPTH_THRESHOLD_USD ($75k)
     AND one side dominates >3x the other.  Sustained smart-money build.

  3. PRICE_CONVICTION — adjusted threshold for low-probability markets:
       conviction_usd = size_usd / price
     At price 0.10, a $25k order has conviction_usd = $250k because the
     bettor expects a 10x return — far higher implied certainty than a
     $50k bet at 0.50.  Threshold: conviction_usd >= CONVICTION_THRESHOLD.

Also tries trade history via Polymarket Activity API:
  GET https://data-api.polymarket.com/activity
     ?limit=100&condition_id={cid}&type=TRADE
  A recent single fill >= FILL_THRESHOLD_USD ($30k) within last 2h is a
  confirmed whale execution (not just a resting intention).

Escalation:
  When called from Command B, a detected whale causes:
    - [WHALE ALERT 🐋] block prepended to Forager seed_query
    - recursive_rounds bumped to 3 (from 2)
    - max_queries_per_round bumped to 7 (from 5)
    - max_sources_per_round bumped to 12 (from 8)
    - Candidate tagged with whale_alert=True for Signal review
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

# ── Thresholds ────────────────────────────────────────────────────────────────

RESTING_THRESHOLD_USD    = 50_000   # single level: size * price >= this
DEPTH_THRESHOLD_USD      = 75_000   # total side depth for accumulation signal
DEPTH_RATIO_MIN          = 3.0      # one side must dominate other by this ratio
CONVICTION_THRESHOLD_USD = 200_000  # size_usd / price (conviction-adjusted)
FILL_THRESHOLD_USD       = 30_000   # single recent trade fill >= this
FILL_WINDOW_HOURS        = 2.0      # look-back window for fills

# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class WhaleSignal:
    signal_type: str        # RESTING_BID | RESTING_ASK | DEPTH_BUY | DEPTH_SELL | CONVICTION_BID | FILL_BUY | FILL_SELL
    size_usd: float         # USD value of the order/fill
    price: float            # price of the order/fill (probability 0-1)
    size_contracts: float   # raw contract count
    conviction_usd: float   # size_usd / price (conviction-adjusted exposure)
    token_id: str           # which token (YES/NO)
    side: str               # YES | NO
    note: str = ""          # human-readable explanation


@dataclass
class WhaleReport:
    condition_id: str
    yes_price: float        # current best bid for YES token
    signals: list[WhaleSignal] = field(default_factory=list)
    max_size_usd: float = 0.0
    dominant_side: str = ""  # YES | NO | MIXED
    escalate: bool = False   # True if any signal crosses escalation threshold

    @property
    def summary(self) -> str:
        if not self.signals:
            return "No whale activity detected."
        lines = [f"🐋 WHALE ALERT — {len(self.signals)} signal(s) detected:"]
        for s in self.signals:
            lines.append(
                f"  [{s.signal_type}] ${s.size_usd:,.0f} on {s.side} "
                f"@ price {s.price:.3f} | conviction ${s.conviction_usd:,.0f} | {s.note}"
            )
        lines.append(
            f"  Dominant side: {self.dominant_side} | "
            f"Max single order: ${self.max_size_usd:,.0f}"
        )
        return "\n".join(lines)


# ── CLOB helpers ──────────────────────────────────────────────────────────────

def _fetch_book(token_id: str, timeout: int = 6) -> dict:
    """Fetch full CLOB order book for a token."""
    try:
        r = requests.get(
            f"https://clob.polymarket.com/book?token_id={token_id}",
            timeout=timeout,
            headers={"User-Agent": "Signal/1.0"},
        )
        if r.status_code == 200:
            return r.json()
    except Exception:  # noqa: BLE001
        pass
    return {}


def _fetch_last_price(token_id: str, timeout: int = 5) -> float | None:
    """Fetch last traded price for a token."""
    try:
        r = requests.get(
            f"https://clob.polymarket.com/last-trades-price?token_id={token_id}",
            timeout=timeout,
            headers={"User-Agent": "Signal/1.0"},
        )
        if r.status_code == 200:
            data = r.json()
            p = data.get("price")
            if p:
                return float(p)
    except Exception:  # noqa: BLE001
        pass
    return None


def _fetch_recent_fills(condition_id: str, timeout: int = 8) -> list[dict]:
    """Fetch recent trade fills via Polymarket Activity API.

    Endpoint: GET https://data-api.polymarket.com/activity
    Returns list of fill dicts: {side, price, size, timestamp, usd_value}
    """
    try:
        r = requests.get(
            "https://data-api.polymarket.com/activity",
            params={
                "limit": 100,
                "condition_id": condition_id,
                "type": "TRADE",
            },
            timeout=timeout,
            headers={"User-Agent": "Signal/1.0"},
        )
        if r.status_code != 200:
            return []
        items = r.json()
        if isinstance(items, dict):
            items = items.get("data") or items.get("activity") or []
        return list(items) if isinstance(items, list) else []
    except Exception:  # noqa: BLE001
        return []


# ── Core analysis ─────────────────────────────────────────────────────────────

def _analyse_book(
    token_id: str,
    side: str,          # "YES" | "NO"
    book: dict,
) -> list[WhaleSignal]:
    """Scan order book levels for whale signals."""
    signals: list[WhaleSignal] = []
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    # Determine current mid-price
    try:
        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        mid = (best_bid + best_ask) / 2
    except Exception:  # noqa: BLE001
        mid = 0.5

    # ── Signal 1: Resting order whale ─────────────────────────────────────
    all_levels = [("BID", b) for b in bids] + [("ASK", a) for a in asks]
    for level_side, level in all_levels:
        try:
            price = float(level["price"])
            size = float(level["size"])
        except (KeyError, ValueError):
            continue
        if price <= 0 or price > 1:
            continue
        size_usd = size * price
        conviction_usd = size_usd / price if price > 0 else 0  # = size (contracts)

        if size_usd >= RESTING_THRESHOLD_USD:
            signal_type = f"RESTING_{level_side}"
            order_side = side if level_side == "BID" else ("NO" if side == "YES" else "YES")
            signals.append(WhaleSignal(
                signal_type=signal_type,
                size_usd=round(size_usd, 0),
                price=round(price, 4),
                size_contracts=round(size, 0),
                conviction_usd=round(conviction_usd, 0),
                token_id=token_id[:20] + "…",
                side=order_side,
                note=(
                    f"{size:,.0f} contracts @ {price:.3f} "
                    f"({'want to buy' if level_side == 'BID' else 'want to sell'})"
                ),
            ))
        elif conviction_usd >= CONVICTION_THRESHOLD_USD and size_usd >= 10_000:
            # Low-probability large bet: flagged by conviction, not raw USD
            order_side = side if level_side == "BID" else ("NO" if side == "YES" else "YES")
            signals.append(WhaleSignal(
                signal_type=f"CONVICTION_{level_side}",
                size_usd=round(size_usd, 0),
                price=round(price, 4),
                size_contracts=round(size, 0),
                conviction_usd=round(conviction_usd, 0),
                token_id=token_id[:20] + "…",
                side=order_side,
                note=(
                    f"Low-price high-conviction: ${size_usd:,.0f} @ {price:.3f} "
                    f"= ${conviction_usd:,.0f} conviction-adjusted"
                ),
            ))

    # ── Signal 2: Depth accumulation whale ────────────────────────────────
    total_bid_usd = sum(float(b["size"]) * float(b["price"]) for b in bids if b.get("size") and b.get("price"))
    total_ask_usd = sum(float(a["size"]) * float(a["price"]) for a in asks if a.get("size") and a.get("price"))

    dominant_side_usd = max(total_bid_usd, total_ask_usd)
    weak_side_usd = min(total_bid_usd, total_ask_usd) + 1.0  # avoid div/0

    if (dominant_side_usd >= DEPTH_THRESHOLD_USD
            and dominant_side_usd / weak_side_usd >= DEPTH_RATIO_MIN):
        is_buy_dominated = total_bid_usd > total_ask_usd
        signal_type = "DEPTH_BUY" if is_buy_dominated else "DEPTH_SELL"
        order_side = side if is_buy_dominated else ("NO" if side == "YES" else "YES")
        signals.append(WhaleSignal(
            signal_type=signal_type,
            size_usd=round(dominant_side_usd, 0),
            price=round(mid, 4),
            size_contracts=0,
            conviction_usd=0,
            token_id=token_id[:20] + "…",
            side=order_side,
            note=(
                f"{'Buy' if is_buy_dominated else 'Sell'} side dominates "
                f"${dominant_side_usd:,.0f} vs ${weak_side_usd:,.0f} "
                f"(ratio {dominant_side_usd/weak_side_usd:.1f}x)"
            ),
        ))

    return signals


def _analyse_fills(
    fills: list[dict],
    condition_id: str,
) -> list[WhaleSignal]:
    """Scan recent fills for single large executions."""
    signals: list[WhaleSignal] = []
    now = time.time()
    cutoff = now - FILL_WINDOW_HOURS * 3600

    for fill in fills:
        # Timestamp: various field names
        ts = fill.get("timestamp") or fill.get("createdAt") or fill.get("time") or 0
        try:
            ts_float = float(ts) / 1000 if float(ts) > 1e10 else float(ts)
        except (TypeError, ValueError):
            continue
        if ts_float < cutoff:
            continue

        try:
            price = float(fill.get("price") or 0)
            size = float(fill.get("size") or fill.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if not price or not size:
            continue

        size_usd = size * price
        if size_usd < FILL_THRESHOLD_USD:
            continue

        outcome = (fill.get("outcome") or fill.get("side") or "YES").upper()
        side = "YES" if "YES" in outcome or "BUY" in outcome else "NO"
        signal_type = f"FILL_{side.replace('YES', 'BUY').replace('NO', 'SELL')}"

        signals.append(WhaleSignal(
            signal_type=signal_type,
            size_usd=round(size_usd, 0),
            price=round(price, 4),
            size_contracts=round(size, 0),
            conviction_usd=round(size_usd / price if price else 0, 0),
            token_id="(trade)",
            side=side,
            note=f"Confirmed fill: {size:,.0f} contracts @ {price:.3f}",
        ))

    return signals


# ── Public API ────────────────────────────────────────────────────────────────

def detect_whale_activity(
    tokens: list[str],
    condition_id: str = "",
    *,
    resting_threshold: float = RESTING_THRESHOLD_USD,
    check_fills: bool = True,
) -> WhaleReport | None:
    """Full whale scan for a Polymarket market.

    Args:
        tokens:           [yes_token_id, no_token_id] from market data
        condition_id:     market condition ID (for fill history lookup)
        resting_threshold: USD threshold for resting order whale
        check_fills:      whether to check trade history (slower)

    Returns WhaleReport if any signal detected, None otherwise.
    """
    if not tokens:
        return None

    yes_token = tokens[0]
    no_token  = tokens[1] if len(tokens) > 1 else None

    # Fetch order books
    yes_book = _fetch_book(yes_token)
    no_book  = _fetch_book(no_token) if no_token else {}

    if not yes_book and not no_book:
        return None

    # Current YES price
    yes_price = 0.5
    yes_bids = yes_book.get("bids") or []
    if yes_bids:
        try:
            yes_price = float(yes_bids[0]["price"])
        except Exception:  # noqa: BLE001
            pass

    all_signals: list[WhaleSignal] = []

    # Analyse YES book
    if yes_book:
        all_signals.extend(_analyse_book(yes_token, "YES", yes_book))

    # Analyse NO book (mirror signals — large NO bids = bearish conviction)
    if no_book:
        all_signals.extend(_analyse_book(no_token, "NO", no_book))

    # Analyse recent fills
    if check_fills and condition_id:
        fills = _fetch_recent_fills(condition_id)
        if fills:
            all_signals.extend(_analyse_fills(fills, condition_id))

    if not all_signals:
        return None

    # Aggregate
    max_size = max(s.size_usd for s in all_signals)
    yes_signals = [s for s in all_signals if s.side == "YES"]
    no_signals  = [s for s in all_signals if s.side == "NO"]
    yes_usd = sum(s.size_usd for s in yes_signals)
    no_usd  = sum(s.size_usd for s in no_signals)

    if yes_usd > no_usd * 1.5:
        dominant = "YES"
    elif no_usd > yes_usd * 1.5:
        dominant = "NO"
    else:
        dominant = "MIXED"

    # Escalate if any strong signal (>= 2x resting threshold or fill)
    escalate = (
        max_size >= resting_threshold * 2
        or any(s.signal_type.startswith("FILL") for s in all_signals)
        or any(s.signal_type.startswith("CONVICTION") and s.conviction_usd >= 500_000
               for s in all_signals)
    )

    report = WhaleReport(
        condition_id=condition_id,
        yes_price=yes_price,
        signals=all_signals,
        max_size_usd=max_size,
        dominant_side=dominant,
        escalate=escalate,
    )
    return report


def format_whale_for_forager(report: WhaleReport) -> str:
    """Format a WhaleReport as a Forager seed context block."""
    lines = [
        "🐋 POLYMARKET WHALE ACTIVITY DETECTED",
        f"  YES price: {report.yes_price:.3f} | Dominant side: {report.dominant_side}",
        f"  Signals: {len(report.signals)} | Max single order: ${report.max_size_usd:,.0f}",
        "",
    ]
    for s in report.signals:
        lines.append(
            f"  [{s.signal_type}] ${s.size_usd:,.0f} on {s.side} @ {s.price:.3f} | {s.note}"
        )
    lines += [
        "",
        "  INTERPRETATION: Large smart-money positioning detected before resolution.",
        "  Research focus: What information might a large player have that the",
        "  market has not yet priced in?  Check for non-public signals, insider",
        "  leaks, or structural information asymmetry.",
    ]
    return "\n".join(lines)
