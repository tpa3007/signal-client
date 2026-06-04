"""Stage 2: Discovery Engine - surfaces new hidden-gem candidates."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

import config
import db
from markets import fetch_active_markets, classify_theme_tags
from lib.discovery import (
    ALL_STRATEGY_NAMES,
    STRATEGIES,
    cheap_optionality,
    compounder_research_candidate,
    low_volume_research_sweetspot,
    stale_price,
    _market_age_days,
)
from lib.discovery_scoring import (
    attention_gap_score,
    combined_raw_discoverability,
    liquidity_score,
    spread_score,
    stale_price_score,
)


def _ensure_db() -> None:
    db.init()


def _price_series(conn, condition_id: str, window_days: int) -> list[float]:
    rows = conn.execute("""
        SELECT yes_price FROM snapshots
        WHERE condition_id = ?
          AND julianday(captured_at) >= julianday('now', ?)
        ORDER BY captured_at
    """, (condition_id, f"-{window_days} days")).fetchall()
    return [float(r["yes_price"]) for r in rows]


def _open_position_cids(conn) -> set[str]:
    return {r["condition_id"] for r in conn.execute(
        "SELECT DISTINCT condition_id FROM positions "
        "WHERE status IN ('open','filled','partially_filled')"
    ).fetchall()}


def _recently_reviewed_cids(conn, days: int) -> set[str]:
    rows = conn.execute("""
        SELECT DISTINCT condition_id FROM hidden_gem_reviews
        WHERE julianday(created_at) >= julianday('now', ?)
          AND decision != 'reject'
    """, (f"-{days} days",)).fetchall()
    return {r["condition_id"] for r in rows}


def _market_to_dict(m, first_seen_at: str | None = None) -> dict:
    """Convert a markets.Market dataclass into the dict shape strategies want."""
    return {
        "condition_id": m.condition_id,
        "question": m.question,
        "slug": m.slug,
        "vertical": m.vertical,
        "theme_tags": m.theme_tags or classify_theme_tags(m.question),
        "yes_price": m.yes_price,
        "no_price": m.no_price,
        "best_bid": m.best_bid,
        "best_ask": m.best_ask,
        "spread": m.spread,
        "yes_entry_price": m.yes_entry_price,
        "no_entry_price": m.no_entry_price,
        "volume": m.volume,
        "liquidity": m.liquidity,
        "days_to_end": m.days_to_end,
        "end_date": m.end_date,
        "first_seen_at": first_seen_at,
    }


def register(mcp):
    @mcp.tool()
    async def discovery_scan(strategies: list[str] | None = None,
                              max_per_strategy: int = 10,
                              vertical: str | None = None,
                              max_pages: int = 6) -> dict:
        """
        Discovery Engine: surface NEW market candidates ranked by objective
        signals (not by volume - that buries hidden gems).

        Runs four strategies in parallel:
          - low_volume_research_sweetspot: $5-30k volume, 14-90d to resolve,
            non-extreme prices, normal spread. Where big desks ignore.
          - stale_price: market age > 30d, price stdev over 14d < 3%. Ripe for
            catalyst-driven repricing. Needs backfill_price_history first.
          - cheap_optionality: yes_price <= 0.15 or >= 0.85 with real liquidity
            and 7-90d to resolve. Powell / Yemen-style asymmetric payout.
          - compounder_research_candidate: 0.22-0.60 on either side,
            adequate liquidity, normal spread. High-confidence research lane.

        Pre-filters: skips markets already in an OPEN position and markets with
        a non-reject hidden_gem_review in the last DISCOVERY_RECENT_REVIEW_DAYS
        days. Returns a flat ranked list plus a per-strategy summary.

        Args:
            strategies: subset of {low_volume_research_sweetspot, stale_price,
                cheap_optionality, compounder_research_candidate}; default = all four.
            max_per_strategy: cap on candidates per strategy.
            vertical: optional restrict to one vertical.
            max_pages: Gamma pages to scan (default 6 = top 3000 by Gamma order).
        """
        _ensure_db()
        if strategies is None:
            strategies = list(ALL_STRATEGY_NAMES)
        unknown = [s for s in strategies if s not in ALL_STRATEGY_NAMES]
        if unknown:
            return {"error": f"unknown strategies: {unknown}"}

        # Discovery floor: take the loosest threshold across all strategies so
        # we don't pre-filter sweetspot markets out.
        scan_min_vol = min(
            config.DISCOVERY_LOW_VOL_MIN,
            config.MIN_VOLUME_USD,
            config.MOONSHOT_LIQUIDITY_NORM * 0.5,
            config.DISCOVERY_COMPOUNDER_VOL_MIN,
        )
        scan_days_min = min(
            config.DISCOVERY_LOW_VOL_DAYS_MIN,
            config.DISCOVERY_CHEAP_OPT_DAYS_MIN,
            config.DISCOVERY_COMPOUNDER_DAYS_MIN,
            config.MIN_DAYS_TO_RESOLUTION,
        )
        scan_days_max = max(
            config.DISCOVERY_LOW_VOL_DAYS_MAX,
            config.DISCOVERY_CHEAP_OPT_DAYS_MAX,
            config.DISCOVERY_COMPOUNDER_DAYS_MAX,
            config.MAX_DAYS_TO_RESOLUTION,
        )
        async with httpx.AsyncClient() as http:
            raw_markets = await fetch_active_markets(
                http, max_pages=max_pages, vertical=vertical, sort="none",
                min_volume_usd=scan_min_vol,
                days_min=scan_days_min, days_max=scan_days_max,
            )

        with db.connect() as conn:
            persisted_markets = 0
            persisted_snapshots = 0
            for m in raw_markets:
                theme_tags = m.theme_tags or classify_theme_tags(m.question)
                db.upsert_market(
                    conn,
                    condition_id=m.condition_id,
                    question=m.question,
                    slug=m.slug,
                    end_date=m.end_date,
                    vertical=m.vertical,
                )
                db.set_market_tags(conn, condition_id=m.condition_id, tags=theme_tags)
                db.add_snapshot(
                    conn,
                    condition_id=m.condition_id,
                    yes_price=m.yes_price,
                    volume=m.volume,
                    liquidity=m.liquidity,
                    no_price=m.no_price,
                    best_bid=m.best_bid,
                    best_ask=m.best_ask,
                    spread=m.spread,
                    yes_entry_price=m.yes_entry_price,
                    no_entry_price=m.no_entry_price,
                    source="discovery",
                )
                persisted_markets += 1
                persisted_snapshots += 1

            open_cids = _open_position_cids(conn)
            recent_cids = _recently_reviewed_cids(conn, config.DISCOVERY_RECENT_REVIEW_DAYS)
            # First-seen lookup for market age (needed by stale_price + auto attention_gap)
            first_seen_map: dict[str, str | None] = {}
            if raw_markets:
                placeholders = ",".join("?" for _ in raw_markets)
                rows = conn.execute(
                    f"SELECT condition_id, first_seen_at FROM markets "
                    f"WHERE condition_id IN ({placeholders})",
                    [m.condition_id for m in raw_markets],
                ).fetchall()
                first_seen_map = {r["condition_id"]: r["first_seen_at"] for r in rows}

            results: dict[str, dict] = {}  # condition_id -> enriched dict
            strategy_counts: dict[str, int] = {s: 0 for s in strategies}

            for m in raw_markets:
                cid = m.condition_id
                if cid in open_cids or cid in recent_cids:
                    continue
                first_seen = first_seen_map.get(cid)
                md = _market_to_dict(m, first_seen_at=first_seen)

                matched: list[str] = []
                if "low_volume_research_sweetspot" in strategies:
                    if low_volume_research_sweetspot(md):
                        matched.append("low_volume_research_sweetspot")
                if "cheap_optionality" in strategies:
                    if cheap_optionality(md):
                        matched.append("cheap_optionality")
                if "compounder_research_candidate" in strategies:
                    if compounder_research_candidate(md):
                        matched.append("compounder_research_candidate")
                if "stale_price" in strategies:
                    series = _price_series(conn, cid, config.DISCOVERY_STALE_WINDOW_DAYS)
                    if stale_price(md, series):
                        matched.append("stale_price")
                else:
                    series = None

                if not matched:
                    continue

                # Auto-scoring
                age_days = _market_age_days(first_seen)
                ag = attention_gap_score(md["volume"], age_days, md["liquidity"])
                if series is None:
                    series = _price_series(conn, cid, config.DISCOVERY_STALE_WINDOW_DAYS)
                sp = stale_price_score(series)
                lq = liquidity_score(md["liquidity"])
                sd = spread_score(md["spread"])
                # Strategy bonus: small constant nudge so "matched many" bubbles up
                bonus = min(0.30 * len(matched), 1.0)
                raw_score = combined_raw_discoverability(
                    attention_gap=ag, stale_price=sp,
                    liquidity=lq, spread=sd, strategy_bonus=bonus,
                )

                results[cid] = {
                    "condition_id": cid,
                    "question": md["question"],
                    "vertical": md["vertical"],
                    "theme_tags": md["theme_tags"],
                    "end_date": md["end_date"],
                    "days_to_resolution": round(md["days_to_end"], 1) if md["days_to_end"] else None,
                    "yes_price": round(md["yes_price"], 4),
                    "spread": md["spread"],
                    "liquidity": md["liquidity"],
                    "volume": md["volume"],
                    "market_age_days": round(age_days, 1) if age_days else None,
                    "strategies": matched,
                    "auto_attention_gap_score": ag,
                    "auto_stale_price_score": sp,
                    "auto_liquidity_score": lq,
                    "auto_spread_score": sd,
                    "raw_discoverability_score": raw_score,
                    "needs_backfill": series is not None and len(series) < 3,
                }
                for s in matched:
                    strategy_counts[s] = strategy_counts.get(s, 0) + 1

            conn.commit()

        # Rank and cap per strategy
        ranked = sorted(results.values(),
                        key=lambda r: r["raw_discoverability_score"], reverse=True)
        # Per-strategy cap - take top N for each, then union & dedupe
        by_strategy: dict[str, list[dict]] = {s: [] for s in strategies}
        for r in ranked:
            for s in r["strategies"]:
                if s in by_strategy and len(by_strategy[s]) < max_per_strategy:
                    by_strategy[s].append(r)
        keep_cids = {r["condition_id"] for lst in by_strategy.values() for r in lst}
        final = [r for r in ranked if r["condition_id"] in keep_cids]

        return {
            "scanned_markets": len(raw_markets),
            "persisted_markets": persisted_markets,
            "persisted_snapshots": persisted_snapshots,
            "skipped_open_positions": len(open_cids),
            "skipped_recent_reviews": len(recent_cids),
            "strategy_summary": strategy_counts,
            "candidates": final,
            "thresholds": {
                "low_vol_min_usd": config.DISCOVERY_LOW_VOL_MIN,
                "low_vol_max_usd": config.DISCOVERY_LOW_VOL_MAX,
                "stale_age_min_days": config.DISCOVERY_STALE_AGE_MIN_DAYS,
                "stale_stdev_max": config.DISCOVERY_STALE_STDEV_MAX,
                "stale_window_days": config.DISCOVERY_STALE_WINDOW_DAYS,
                "cheap_opt_low_max": config.DISCOVERY_CHEAP_OPT_LOW_MAX,
                "cheap_opt_high_min": config.DISCOVERY_CHEAP_OPT_HIGH_MIN,
            },
        }

    @mcp.tool()
    async def discovery_overlap_with_open_positions(max_pages: int = 6) -> dict:
        """
        Diagnostic: how many of the open positions would have been surfaced by
        discovery_scan (ignoring the open-position pre-filter)? High overlap =
        Claude's intuition agrees with the auto-strategies. Low overlap = the
        engine sees a different opportunity surface than current picks.
        """
        _ensure_db()
        scan_min_vol = min(config.DISCOVERY_LOW_VOL_MIN, config.MIN_VOLUME_USD)
        scan_days_min = min(config.DISCOVERY_LOW_VOL_DAYS_MIN,
                             config.DISCOVERY_CHEAP_OPT_DAYS_MIN,
                             config.MIN_DAYS_TO_RESOLUTION)
        scan_days_max = max(config.DISCOVERY_LOW_VOL_DAYS_MAX,
                             config.DISCOVERY_CHEAP_OPT_DAYS_MAX,
                             config.MAX_DAYS_TO_RESOLUTION)
        async with httpx.AsyncClient() as http:
            raw_markets = await fetch_active_markets(
                http, max_pages=max_pages, sort="none",
                min_volume_usd=scan_min_vol,
                days_min=scan_days_min, days_max=scan_days_max,
            )

        with db.connect() as conn:
            open_cids = _open_position_cids(conn)
            if not open_cids:
                return {"open_positions": 0, "matched_by_discovery": 0, "details": []}
            # Build first-seen lookup
            placeholders = ",".join("?" for _ in raw_markets) if raw_markets else "''"
            rows = conn.execute(
                f"SELECT condition_id, first_seen_at FROM markets "
                f"WHERE condition_id IN ({placeholders})",
                [m.condition_id for m in raw_markets],
            ).fetchall() if raw_markets else []
            first_seen_map = {r["condition_id"]: r["first_seen_at"] for r in rows}

            details = []
            for m in raw_markets:
                if m.condition_id not in open_cids:
                    continue
                md = _market_to_dict(m, first_seen_at=first_seen_map.get(m.condition_id))
                matched = []
                if low_volume_research_sweetspot(md):
                    matched.append("low_volume_research_sweetspot")
                if cheap_optionality(md):
                    matched.append("cheap_optionality")
                series = _price_series(conn, m.condition_id, config.DISCOVERY_STALE_WINDOW_DAYS)
                if stale_price(md, series):
                    matched.append("stale_price")
                details.append({
                    "condition_id": m.condition_id,
                    "question": m.question,
                    "matched_strategies": matched,
                    "would_have_been_found": bool(matched),
                })
        matched_n = sum(1 for d in details if d["would_have_been_found"])
        return {
            "open_positions_in_scan": len(details),
            "open_positions_total": len(open_cids),
            "matched_by_discovery": matched_n,
            "match_rate": round(matched_n / len(details), 3) if details else 0.0,
            "details": details,
        }
