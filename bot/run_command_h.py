"""Command H — Portfolio Intelligence: Kelly Sizing + Correlation Analysis.

Pulls all open positions, fetches live Polymarket prices, computes
full Kelly breakdown for each, identifies correlated clusters,
and emits an actionable portfolio intelligence report.

Pipeline:
  1. Load all open positions from DB
  2. Fetch live YES prices from Polymarket Gamma API
  3. Compute Kelly stake, edge, and EV for each position
  4. Cluster by vertical + expiry month (correlation proxy)
  5. Apply portfolio Kelly (sqrt(n) shrinkage within clusters)
  6. Output ranked portfolio table + sizing recommendations
  7. Flag any positions that no longer have edge (price drifted)

Usage:
    cd C:\\Signal\\bot && python run_command_h.py
"""
import sys, os, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")
sys.path.insert(0, "../forager")
from dotenv import load_dotenv
load_dotenv(".env")
load_dotenv("../forager/.env", override=False)

import db; db.init()
from lib.kelly import kelly_stake, portfolio_kelly_stakes, kelly_edge_breakdown
import config
from urllib.request import Request, urlopen
from urllib.parse import urlencode

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ── Configuration ─────────────────────────────────────────────────────────────

GAMMA_API = "https://gamma-api.polymarket.com"
LIVE_PRICE_TIMEOUT = 15
MIN_EDGE_WARN = 0.03          # below this edge → yellow flag
MIN_EDGE_EXIT = 0.0           # at or below this → red flag (no edge)
PRICE_DRIFT_THRESHOLD = 0.05  # if price moved >5% since entry → re-evaluate


# ── Polymarket live price fetching ────────────────────────────────────────────

def _fetch_live_prices(condition_ids: list[str]) -> dict[str, float | None]:
    """Fetch current YES prices for a batch of condition IDs from Gamma API."""
    prices: dict[str, float | None] = {cid: None for cid in condition_ids}
    if not condition_ids:
        return prices

    def _extract_yes_price(m: dict) -> float | None:
        # Prefer the actual YES outcome price; lastTradePrice can be stale or
        # side-ambiguous on some Gamma responses.
        outcome_prices = m.get("outcomePrices") or m.get("outcome_prices")
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except Exception:
                outcome_prices = None
        if isinstance(outcome_prices, list) and outcome_prices:
            try:
                return float(outcome_prices[0])
            except (TypeError, ValueError):
                pass
        best_ask = m.get("bestAsk") or m.get("best_ask")
        last_price = m.get("lastTradePrice") or m.get("last_trade_price")
        raw = last_price or best_ask
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    # Gamma API accepts comma-separated condition IDs
    try:
        params = urlencode({
            "condition_ids": ",".join(condition_ids[:50]),
        })
        req = Request(
            f"{GAMMA_API}/markets?{params}",
            headers={"User-Agent": "Signal-Bot/1.0", "Accept": "application/json"},
        )
        with urlopen(req, timeout=LIVE_PRICE_TIMEOUT) as resp:
            markets = json.loads(resp.read().decode("utf-8"))
        for m in markets:
            cid = m.get("conditionId") or m.get("condition_id")
            if cid and cid in prices:
                prices[cid] = _extract_yes_price(m)
    except Exception as exc:
        print(f"  [warning] Live price fetch failed: {exc}")

    # Gamma's condition_id filter can silently miss old/expired slugs.  Fall
    # back to the canonical slug from our DB so H never does Kelly on stale
    # entry prices without saying so.
    missing = [cid for cid, price in prices.items() if price is None]
    if missing:
        try:
            with db.connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT condition_id, slug FROM markets
                    WHERE condition_id IN ({','.join('?' for _ in missing)})
                    """,
                    missing,
                ).fetchall()
            slug_by_cid = {r["condition_id"]: r["slug"] for r in rows if r["slug"]}
        except Exception:
            slug_by_cid = {}
        recovered = 0
        for cid in missing:
            slug = slug_by_cid.get(cid)
            if not slug:
                continue
            try:
                req = Request(
                    f"{GAMMA_API}/markets/slug/{slug}",
                    headers={"User-Agent": "Signal-Bot/1.0", "Accept": "application/json"},
                )
                with urlopen(req, timeout=LIVE_PRICE_TIMEOUT) as resp:
                    market = json.loads(resp.read().decode("utf-8"))
                price = _extract_yes_price(market) if isinstance(market, dict) else None
                if price is not None:
                    prices[cid] = price
                    recovered += 1
            except Exception:
                continue
        if recovered:
            print(f"  [fallback] Recovered {recovered}/{len(missing)} prices by slug")

    return prices


def _fetch_market_details(condition_ids: list[str]) -> dict[str, dict]:
    """Fetch market details (question, volume, end_date) from Gamma API."""
    details: dict[str, dict] = {}
    if not condition_ids:
        return details
    try:
        params = urlencode({"condition_ids": ",".join(condition_ids[:50])})
        req = Request(
            f"{GAMMA_API}/markets?{params}",
            headers={"User-Agent": "Signal-Bot/1.0"},
        )
        with urlopen(req, timeout=LIVE_PRICE_TIMEOUT) as resp:
            markets = json.loads(resp.read().decode("utf-8"))
        for m in markets:
            cid = m.get("conditionId") or m.get("condition_id") or ""
            if cid:
                details[cid] = m
    except Exception:
        pass
    return details


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_open_positions() -> list[dict]:
    """Load all open positions with signal context."""
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT
                p.id AS position_id,
                p.condition_id,
                p.intended_side,
                p.intended_entry_price,
                p.intended_stake_usd,
                p.end_date,
                p.thesis_snapshot_text,
                p.signal_id,
                s.yes_price_at_signal AS entry_yes_price,
                s.claude_prob AS entry_prob,
                s.confidence AS entry_confidence,
                s.edge AS entry_edge,
                COALESCE(s.edge_archetype, p.primary_archetype) AS primary_archetype,
                m.vertical,
                m.question,
                m.end_date AS market_end_date
            FROM positions p
            LEFT JOIN signals s ON p.signal_id = s.id
            LEFT JOIN markets m ON p.condition_id = m.condition_id
            WHERE p.status = 'open'
            ORDER BY p.end_date ASC NULLS LAST
        """).fetchall()
    return [dict(r) for r in rows]


def _days_to_expiry(end_date_str: str | None) -> float | None:
    if not end_date_str:
        return None
    try:
        if "T" in str(end_date_str):
            dt = datetime.fromisoformat(str(end_date_str).replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(str(end_date_str)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (dt - datetime.now(timezone.utc)).total_seconds() / 86400
    except Exception:
        return None


# ── Formatting ────────────────────────────────────────────────────────────────

def _edge_flag(edge: float) -> str:
    if edge >= 0.08:
        return "🟢 STRONG"
    if edge >= 0.05:
        return "🟡 SOLID"
    if edge >= 0.02:
        return "🟠 THIN"
    if edge > 0:
        return "🔴 MARGINAL"
    return "⛔ NO EDGE"


def _price_drift_flag(entry: float | None, live: float | None, side: str) -> str:
    if entry is None or live is None:
        return ""
    drift = abs(live - entry)
    if drift < 0.01:
        return ""
    direction = "↑" if live > entry else "↓"
    if drift >= PRICE_DRIFT_THRESHOLD:
        # Adverse drift for our position
        if (side == "YES" and live < entry) or (side == "NO" and live > entry):
            return f"  ⚠️ ADVERSE DRIFT {direction}{drift*100:.1f}pp"
        else:
            return f"  ✅ FAVORABLE DRIFT {direction}{drift*100:.1f}pp"
    return f"  ({direction}{drift*100:.1f}pp drift)"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("COMMAND H: Portfolio Intelligence — Kelly Sizing + Correlation")
    print("=" * 65)
    print(f"  Bankroll: ${config.BANKROLL_USD:,.0f} | Kelly fraction: {config.KELLY_FRACTION:.2f}")
    print(f"  Min edge: {config.EDGE_THRESHOLD:.2f} | Max stake: ${config.BET_MAX_USD:.0f}")
    print()

    # 1. Load open positions
    positions = _load_open_positions()
    if not positions:
        print("No open positions found.")
        return

    print(f"Open positions: {len(positions)}")

    # 2. Fetch live prices
    condition_ids = [p["condition_id"] for p in positions if p.get("condition_id")]
    print(f"Fetching live prices from Polymarket for {len(condition_ids)} markets...")
    live_prices = _fetch_live_prices(condition_ids)
    live_fetched = sum(1 for v in live_prices.values() if v is not None)
    print(f"  Live prices fetched: {live_fetched}/{len(condition_ids)}")
    print()

    # 3. Compute Kelly for each position
    kelly_inputs = []
    position_analysis = []

    for pos in positions:
        cid = pos.get("condition_id", "")
        side = (pos.get("intended_side") or "YES").upper()
        entry_price = float(pos.get("entry_yes_price") or pos.get("intended_entry_price") or 0.5)
        our_prob = float(pos.get("entry_prob") or 0.5)
        live_price = live_prices.get(cid)
        current_price = live_price if live_price is not None else entry_price

        dte = _days_to_expiry(pos.get("end_date") or pos.get("market_end_date"))
        vertical = pos.get("vertical") or "unknown"
        end_date = (pos.get("end_date") or pos.get("market_end_date") or "")[:10]
        question = pos.get("question") or f"Market {cid[:16]}..."

        # Kelly at CURRENT price (re-evaluation)
        kr = kelly_stake(
            our_prob=our_prob,
            market_price=current_price,
            side=side,
            bankroll=config.BANKROLL_USD,
            kelly_fraction=config.KELLY_FRACTION,
            min_stake=config.BET_MIN_USD,
            max_stake=config.BET_MAX_USD,
        )

        # Original entry edge
        entry_kr = kelly_stake(
            our_prob=our_prob,
            market_price=entry_price,
            side=side,
            bankroll=config.BANKROLL_USD,
            kelly_fraction=config.KELLY_FRACTION,
            min_stake=config.BET_MIN_USD,
            max_stake=config.BET_MAX_USD,
        )

        analysis = {
            "position_id": pos.get("position_id"),
            "condition_id": cid,
            "question": question[:70],
            "side": side,
            "entry_price": entry_price,
            "live_price": live_price,
            "current_price": current_price,
            "our_prob": our_prob,
            "entry_edge": entry_kr.edge,
            "current_edge": kr.edge,
            "current_kelly": kr,
            "dte": dte,
            "end_date": end_date,
            "vertical": vertical,
            "archetype": pos.get("primary_archetype") or "unknown",
            "original_stake": float(pos.get("intended_stake_usd") or 0),
        }
        position_analysis.append(analysis)

        # Portfolio Kelly input
        kelly_inputs.append({
            "condition_id": cid,
            "our_prob": our_prob,
            "market_price": current_price,
            "side": side,
            "vertical": vertical,
            "end_date": end_date,
        })

    # 4. Portfolio Kelly with correlation shrinkage
    portfolio_result = portfolio_kelly_stakes(
        kelly_inputs,
        bankroll=config.BANKROLL_USD,
        kelly_fraction=config.KELLY_FRACTION,
        max_portfolio_fraction=0.40,
    )

    # 5. Print individual position analysis
    print("─" * 65)
    print("POSITION-LEVEL KELLY ANALYSIS")
    print("─" * 65)

    no_edge_count = 0
    adverse_count = 0
    strong_count = 0

    for i, pa in enumerate(position_analysis):
        kr = pa["current_kelly"]
        portfolio_kr = portfolio_result.positions[i]
        adj_factor = portfolio_result.correlation_adjustments.get(pa["condition_id"], 1.0)

        edge_flag = _edge_flag(pa["current_edge"])
        drift_note = _price_drift_flag(pa["entry_price"], pa["live_price"], pa["side"])

        dte_str = f"{pa['dte']:.0f}d" if pa["dte"] is not None else "?"
        price_str = f"${pa['current_price']:.3f}"
        if pa["live_price"] is not None:
            price_str = f"${pa['live_price']:.3f} (live)"
        else:
            price_str = f"${pa['entry_price']:.3f} (entry)"

        print(f"\n[{pa['side']}] {pa['question']}")
        print(f"  Price: {price_str} | Our prob: {pa['our_prob']*100:.0f}% | DTE: {dte_str}")
        print(f"  Edge: {pa['current_edge']*100:+.1f}pp {edge_flag}{drift_note}")
        print(f"  Kelly: full={kr.kelly_f*100:.1f}% | fractional={kr.fractional_kelly_f*100:.1f}%")
        print(f"  Stake: ${kr.recommended_stake:.2f} → portfolio-adjusted: ${portfolio_kr.recommended_stake:.2f} (corr. factor: {adj_factor:.2f})")
        print(f"  EV/dollar: {kr.ev_per_dollar*100:+.2f}%  |  Vertical: {pa['vertical']}")

        if pa["current_edge"] <= 0:
            print(f"  ⛔ EDGE GONE — review position (entry edge was {pa['entry_edge']*100:+.1f}pp)")
            no_edge_count += 1
        elif pa["current_edge"] < MIN_EDGE_WARN:
            print(f"  ⚠️  THIN EDGE — monitor closely")
        elif pa["current_edge"] >= 0.08:
            strong_count += 1

        if pa["live_price"] is not None and pa["entry_price"]:
            drift = abs(pa["live_price"] - pa["entry_price"])
            if (pa["side"] == "YES" and pa["live_price"] < pa["entry_price"] - 0.03) or \
               (pa["side"] == "NO" and pa["live_price"] > pa["entry_price"] + 0.03):
                adverse_count += 1

    # 6. Correlation cluster analysis
    print("\n" + "─" * 65)
    print("CORRELATION CLUSTER ANALYSIS")
    print("─" * 65)

    clusters: dict[str, list[str]] = {}
    for pa in position_analysis:
        month = pa["end_date"][:7]
        key = f"{pa['vertical']}:{month}"
        clusters.setdefault(key, []).append(pa["question"][:50])

    multi_clusters = {k: v for k, v in clusters.items() if len(v) > 1}
    if multi_clusters:
        print("\nCorrelated position clusters (same vertical + expiry month):")
        for cluster_key, questions in multi_clusters.items():
            vertical, month = cluster_key.split(":", 1)
            shrink = round(1.0 / (len(questions) ** 0.5), 2)
            print(f"\n  [{vertical} / {month}] — {len(questions)} positions → shrinkage: {shrink:.2f}x")
            for q in questions:
                print(f"    • {q}")
    else:
        print("  No correlated clusters detected — all positions are uncorrelated.")

    # 7. Portfolio summary
    print("\n" + "─" * 65)
    print("PORTFOLIO SUMMARY")
    print("─" * 65)
    total_original_stake = sum(pa["original_stake"] for pa in position_analysis)
    total_kelly_recommended = portfolio_result.total_recommended
    bankroll_pct = portfolio_result.total_bankroll_fraction * 100

    print(f"\n  Positions:         {len(positions)}")
    print(f"  Strong edge (≥8%): {strong_count}")
    print(f"  No edge:           {no_edge_count}")
    print(f"  Adverse drift:     {adverse_count}")
    print()
    print(f"  Total staked (original):     ${total_original_stake:.2f}")
    print(f"  Total Kelly-recommended:     ${total_kelly_recommended:.2f}")
    print(f"  Portfolio bankroll fraction: {bankroll_pct:.1f}%")
    print(f"  Bankroll remaining:          ${config.BANKROLL_USD - total_original_stake:.2f}")

    # 8. Action recommendations
    print("\n" + "─" * 65)
    print("RECOMMENDED ACTIONS")
    print("─" * 65)
    actions: list[str] = []

    for pa in position_analysis:
        kr = pa["current_kelly"]
        if pa["dte"] is not None and pa["dte"] < 0:
            actions.append(
                f"  🧾 RESOLVE [{pa['side']}] {pa['question'][:55]} — expiry passed; "
                "do not treat as fresh edge"
            )
        elif pa["current_edge"] <= 0:
            actions.append(f"  ⛔ EXIT   [{pa['side']}] {pa['question'][:55]} — edge gone ({pa['current_edge']*100:+.1f}pp)")
        elif pa["current_edge"] < MIN_EDGE_WARN and pa["dte"] and pa["dte"] < 7:
            actions.append(f"  🔴 REVIEW [{pa['side']}] {pa['question'][:55]} — thin edge + <7d DTE")
        elif pa["live_price"] and pa["entry_price"] and pa["current_edge"] >= 0.10:
            actions.append(f"  🟢 HOLD   [{pa['side']}] {pa['question'][:55]} — strong edge {pa['current_edge']*100:.0f}pp")

    if actions:
        for action in actions:
            print(action)
    else:
        print("  All positions within normal parameters. HOLD.")

    # 9. New sizing recommendations for next batch
    print("\n" + "─" * 65)
    print("SIZING REFERENCE (for new positions at current bankroll)")
    print("─" * 65)
    examples = [
        (0.10, "YES", 0.20, "10% edge, 20¢ market"),
        (0.35, "YES", 0.25, "Compounder: 35% edge"),
        (0.05, "NO",  0.90, "5% edge on high-prob NO"),
        (0.15, "NO",  0.80, "Strong NO bet"),
    ]
    print(f"\n  {'Example':<35} {'Kelly':>8} {'Stake':>8} {'EV/$ ':>8}")
    print(f"  {'─'*35} {'─'*8} {'─'*8} {'─'*8}")
    for our_p, side, mkt_p, label in examples:
        kr = kelly_stake(our_p, mkt_p, side, bankroll=config.BANKROLL_USD,
                         kelly_fraction=config.KELLY_FRACTION,
                         min_stake=config.BET_MIN_USD, max_stake=config.BET_MAX_USD)
        print(f"  {label:<35} {kr.kelly_f*100:>7.1f}% ${kr.recommended_stake:>7.2f} {kr.ev_per_dollar*100:>+7.2f}%")

    print(f"\nDone. Run Command B → D → H pipeline for full research → sizing cycle.")
    print("=" * 65)

    return position_analysis, portfolio_result


if __name__ == "__main__":
    main()
