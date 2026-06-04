"""Stage 1: Portfolio & Risk Engine MCP tools.

Exposes: portfolio_snapshot, exposure_check, record_fill,
mark_to_market_all, pending_outcome_reviews.
"""
from __future__ import annotations

from datetime import datetime, timezone

import config
import db
from lib.exposure import check_exposure, open_exposure
from lib.queries import latest_execution_context as _latest_execution_context
from lib.pnl import realized_pnl as _realized_pnl
from lib.real_money_audit import build_real_money_audit


def _ensure_db() -> None:
    db.init()


def _bankroll_pct(usd: float) -> float:
    return round(100.0 * usd / config.BANKROLL_USD, 1) if config.BANKROLL_USD else 0.0


def register(mcp):
    @mcp.tool()
    def portfolio_snapshot() -> dict:
        """
        Open-positions panel for the Aladdin terminal. Returns total at-risk,
        max payout, and exposure broken down by vertical / archetype /
        deadline-week / single-market, plus a list of correlated open pairs
        (same vertical + overlapping resolution window).

        Use at session start to know what's already on the books before
        adding a new signal.
        """
        _ensure_db()
        with db.connect() as conn:
            snap = open_exposure(conn)
            rows = conn.execute("""
                SELECT p.id AS position_id, p.condition_id, p.signal_id,
                       p.intended_side, p.intended_entry_price, p.intended_stake_usd,
                       p.side_entry_price, p.yes_equivalent_entry, p.price_model_version,
                       p.stake_source, p.status, p.end_date, p.primary_archetype,
                       p.edge_archetype, p.signal_generation_epoch, p.confidence_source,
                       p.approval_strength, p.post_entry_review_required,
                       p.post_entry_review_reason,
                       p.opened_at,
                       COALESCE(m.vertical, 'unknown') AS vertical,
                       m.question
                FROM positions p
                LEFT JOIN markets m ON m.condition_id = p.condition_id
                WHERE p.status IN ('open', 'filled', 'partially_filled')
                ORDER BY p.opened_at DESC
            """).fetchall()
            positions = [dict(r) for r in rows]
            for p in positions:
                p["theme_tags"] = db.get_market_tags(conn, p["condition_id"])
                p["post_entry_review_required"] = bool(p.get("post_entry_review_required"))
            # Max payout: stake / side_entry_price per position.
            max_payout = 0.0
            for r in positions:
                ep = r.get("side_entry_price")
                if not ep:
                    intended = r["intended_entry_price"] or 0
                    ep = (1.0 - intended) if r["intended_side"] == "NO" and intended > 0.5 else intended
                stake = r["intended_stake_usd"] or 0
                if ep > 0:
                    max_payout += stake / ep
            # Correlated pairs (same vertical + overlapping deadline windows)
            corr_pairs = []
            for i, a in enumerate(positions):
                for b in positions[i + 1:]:
                    shared_tags = sorted(set(a.get("theme_tags", [])) & set(b.get("theme_tags", [])))
                    if a["vertical"] != b["vertical"] and not shared_tags:
                        continue
                    if not (a["end_date"] and b["end_date"]):
                        continue
                    # very rough: same ISO year-week or within 14 days
                    try:
                        da = datetime.fromisoformat(a["end_date"].replace("Z", "+00:00"))
                        db_ = datetime.fromisoformat(b["end_date"].replace("Z", "+00:00"))
                        delta_days = abs((da - db_).total_seconds()) / 86400
                    except Exception:
                        continue
                    if delta_days <= 14:
                        corr_pairs.append({
                            "a_position_id": a["position_id"],
                            "b_position_id": b["position_id"],
                            "vertical": a["vertical"],
                            "shared_theme_tags": shared_tags,
                            "deadline_delta_days": round(delta_days, 1),
                        })
            corr_pairs.sort(key=lambda x: x["deadline_delta_days"])
        return {
            "total_at_risk_usd": snap["total_at_risk_usd"],
            "total_at_risk_pct_bankroll": _bankroll_pct(snap["total_at_risk_usd"]),
            "max_payout_usd": round(max_payout, 2),
            "bankroll_usd": config.BANKROLL_USD,
            "by_vertical": snap["by_vertical"],
            "by_archetype": snap["by_archetype"],
            "by_deadline_week": snap["by_deadline_week"],
            "by_theme": snap["by_theme"],
            "by_market": snap["by_market"],
            "open_positions": positions,
            "post_entry_review_required_count": sum(
                1 for p in positions if p.get("post_entry_review_required")
            ),
            "correlated_pairs": corr_pairs[:10],
            "caps": {
                "vertical_pct": config.EXPOSURE_VERTICAL_CAP_PCT,
                "archetype_pct": config.EXPOSURE_ARCHETYPE_CAP_PCT,
                "deadline_week_pct": config.EXPOSURE_DEADLINE_WEEK_CAP_PCT,
                "theme_pct": config.EXPOSURE_THEME_CAP_PCT,
                "single_market_pct": config.EXPOSURE_SINGLE_MARKET_CAP_PCT,
            },
        }

    @mcp.tool()
    def real_money_portfolio_audit(
        stale_snapshot_hours: float = 12.0,
        urgent_days: float = 7.0,
        include_closed: bool = False,
    ) -> dict:
        """
        Read-only audit of real-money positions.

        Aggregates real/hybrid fills, partial exits, residual shares, latest
        snapshot MTM, deadline urgency, gate/manual status, and dossier
        completeness into a prioritized research queue. This tool never writes
        signals, positions, fills, or research facts.
        """
        _ensure_db()
        stale_snapshot_hours = max(0.1, min(float(stale_snapshot_hours), 168.0))
        urgent_days = max(0.0, min(float(urgent_days), 60.0))
        with db.connect() as conn:
            return build_real_money_audit(
                conn,
                bankroll_usd=config.BANKROLL_USD,
                stale_snapshot_hours=stale_snapshot_hours,
                urgent_days=urgent_days,
                include_closed=bool(include_closed),
            )

    @mcp.tool()
    def exposure_check(condition_id: str, proposed_stake_usd: float,
                       primary_archetype: str | None = None) -> dict:
        """
        Would taking ``proposed_stake_usd`` on this market breach any cap?

        Call before ``record_analysis`` (or at least before assuming the
        proposed stake is allowed). Returns ``allowed``, a list of breaches
        (bucket/key/current/cap), the current exposure snapshot, and the
        ``highest_existing_share`` used by sizing shrinkage.
        """
        _ensure_db()
        with db.connect() as conn:
            row = conn.execute("""
                SELECT COALESCE(vertical, 'unknown') AS vertical, end_date
                FROM markets WHERE condition_id = ?
            """, (condition_id,)).fetchone()
            if not row:
                return {"error": f"market {condition_id} not found; call fetch_candidates first"}
            return check_exposure(
                conn,
                condition_id=condition_id,
                vertical=row["vertical"],
                primary_archetype=primary_archetype,
                end_date=row["end_date"],
                proposed_stake_usd=float(proposed_stake_usd),
                theme_tags=db.get_market_tags(conn, condition_id),
            )

    @mcp.tool()
    def record_fill(position_id: int, side: str, price: float, shares: float,
                    stake_usd: float, venue: str = "polymarket",
                    tx_hash: str = "") -> dict:
        """
        Record an actual fill against an existing position. Computes slippage
        against the position's intended_entry_price. Use ``venue='paper'`` for
        simulated entries (record_analysis already does this automatically);
        use ``venue='polymarket'`` when reporting a real fill.
        """
        _ensure_db()
        if side.upper() not in {"YES", "NO"}:
            return {"error": "side must be YES or NO"}
        with db.connect() as conn:
            pos = conn.execute(
                "SELECT intended_side, intended_entry_price, side_entry_price, stake_source, status "
                "FROM positions WHERE id = ?", (position_id,),
            ).fetchone()
            if not pos:
                return {"error": f"position {position_id} not found"}
            intended = float(pos["intended_entry_price"] or price)
            intended_side_entry = pos["side_entry_price"]
            if intended_side_entry is None:
                intended_side_entry = (1.0 - intended) if pos["intended_side"] == "NO" and intended > 0.5 else intended
            intended_side_entry = float(intended_side_entry)
            slippage = float(price) - intended_side_entry
            fill_id = db.add_fill(
                conn, position_id=position_id, side=side.upper(),
                price=float(price), shares=float(shares), stake_usd=float(stake_usd),
                slippage_vs_intent=slippage, venue=venue,
                tx_hash=tx_hash or None,
            )
            # Promote stake_source if we now have a real fill on a paper position
            if venue == "polymarket" and pos["stake_source"] == "paper":
                conn.execute(
                    "UPDATE positions SET stake_source = 'hybrid', status = 'filled' WHERE id = ?",
                    (position_id,),
                )
            conn.commit()
        return {
            "ok": True,
            "fill_id": fill_id,
            "position_id": position_id,
            "slippage_vs_intent": round(slippage, 4),
            "venue": venue,
        }

    @mcp.tool()
    def mark_to_market_all() -> dict:
        """
        Walk every open position and write a fresh ``pnl_events`` row of type
        ``mark`` using the latest snapshot. Skips positions whose market has
        no snapshot yet. Returns a summary of what was marked.
        """
        _ensure_db()
        marked = 0
        total_value = 0.0
        total_pnl = 0.0
        details = []
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT p.id AS position_id, p.condition_id, p.intended_side,
                       p.intended_entry_price, p.side_entry_price,
                       p.yes_equivalent_entry, p.intended_stake_usd
                FROM positions p
                WHERE p.status IN ('open', 'filled', 'partially_filled')
            """).fetchall()
            for r in rows:
                ctx = _latest_execution_context(conn, r["condition_id"])
                if not ctx:
                    continue
                yes_price = ctx["market_price"]
                intended = float(r["intended_entry_price"])
                entry_yes_equiv = float(r["yes_equivalent_entry"] or intended)
                if r["side_entry_price"] is not None:
                    side_entry = float(r["side_entry_price"])
                else:
                    side_entry = (1.0 - intended) if r["intended_side"] == "NO" and intended > 0.5 else intended
                stake = float(r["intended_stake_usd"])
                if r["intended_side"] == "YES":
                    side_price = yes_price
                else:
                    side_price = 1.0 - yes_price
                shares = stake / side_entry if side_entry > 0 else 0.0
                value = shares * side_price
                delta_pnl = value - stake
                db.add_pnl_event(
                    conn, position_id=r["position_id"], event_type="mark",
                    yes_price=yes_price, side_price=side_price,
                    value_usd=round(value, 2), delta_pnl_usd=round(delta_pnl, 2),
                    note="mark_to_market_all",
                )
                marked += 1
                total_value += value
                total_pnl += delta_pnl
                details.append({
                    "position_id": r["position_id"],
                    "condition_id": r["condition_id"],
                    "side": r["intended_side"],
                    "side_entry": round(side_entry, 4),
                    "side_price": round(side_price, 4),
                    "value_usd": round(value, 2),
                    "delta_pnl_usd": round(delta_pnl, 2),
                })
            conn.commit()
        return {
            "positions_marked": marked,
            "total_value_usd": round(total_value, 2),
            "total_mark_to_market_pnl_usd": round(total_pnl, 2),
            "details": details,
        }

    @mcp.tool()
    def pending_outcome_reviews(limit: int = 20) -> dict:
        """
        Positions that have RESOLVED but still have no ``outcome_learning_review``
        row. This is the queue that keeps the learning loop honest: without it,
        resolved trades quietly skip ``record_outcome_learning_review`` and the
        post-mortem signal is lost.
        """
        _ensure_db()
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT p.id AS position_id, p.condition_id, p.signal_id,
                       p.intended_side, p.intended_entry_price, p.intended_stake_usd,
                       p.opened_at, p.closed_at, m.question, m.resolved_yes,
                       m.resolved_at, s.realized_pnl
                FROM positions p
                JOIN markets m ON m.condition_id = p.condition_id
                LEFT JOIN signals s ON s.id = p.signal_id
                LEFT JOIN outcome_learning_reviews olr ON olr.condition_id = p.condition_id
                WHERE m.resolved = 1 AND olr.id IS NULL
                ORDER BY m.resolved_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return {
            "count": len(rows),
            "pending": [dict(r) for r in rows],
        }
