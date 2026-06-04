"""Read-only real-money portfolio audit helpers.

The audit is intentionally diagnostic. It does not create trades, signals, fills,
or research facts; it turns existing ledger state into a prioritized review queue.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lib.queries import research_completeness


OPEN_POSITION_STATUSES = {"open", "filled", "partially_filled"}
ENTRY_SIDES = {"YES", "NO", "BUY"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, "normal": 5}.get(severity, 9)


def _risk(severity: str, code: str, message: str, action: str) -> dict:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "recommended_research_action": action,
    }


def _gate_status(row: dict[str, Any], approved_prebet_count: int) -> tuple[str, bool]:
    if int(row.get("manual_trade") or 0):
        return "manual_real_trade", False
    if approved_prebet_count > 0 or row.get("gate_status") == "gated":
        return "gated", False
    if row.get("gate_status") == "manual":
        return "operator_manual_without_formal_gate", False
    return "legacy_gate_violation", True


def _latest_snapshot(conn, condition_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT yes_price, no_price, best_bid, best_ask, spread,
               yes_entry_price, no_entry_price, volume, liquidity, captured_at
        FROM snapshots
        WHERE condition_id = ?
        ORDER BY captured_at DESC LIMIT 1
        """,
        (condition_id,),
    ).fetchone()
    return dict(row) if row else None


def _approved_prebet_count(conn, condition_id: str, created_at: str | None) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM pre_bet_checklists
        WHERE condition_id = ?
          AND decision = 'approved_for_signal'
          AND (? IS NULL OR created_at <= ?)
        """,
        (condition_id, created_at, created_at),
    ).fetchone()
    return int(row["n"] if row else 0)


def _fills(conn, position_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, filled_at, side, price, shares, stake_usd, venue
        FROM fills
        WHERE position_id = ?
        ORDER BY filled_at, id
        """,
        (position_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _audit_rows(conn, include_closed: bool) -> list[dict[str, Any]]:
    status_filter = "" if include_closed else "AND p.status IN ('open','filled','partially_filled')"
    return [
        dict(r)
        for r in conn.execute(
            f"""
            SELECT p.id AS position_id, p.condition_id, p.signal_id,
                   p.opened_at, p.intended_side, p.intended_entry_price,
                   p.side_entry_price, p.yes_equivalent_entry, p.intended_stake_usd,
                   p.stake_source, p.status, p.end_date AS position_end_date,
                   p.primary_archetype, p.edge_archetype, p.signal_generation_epoch,
                   p.confidence_source, p.approval_strength,
                   p.post_entry_review_required, p.post_entry_review_reason,
                   m.question, m.slug, m.end_date AS market_end_date,
                   COALESCE(m.vertical, 'unknown') AS vertical,
                   m.resolved AS market_resolved, m.resolved_yes, m.resolved_at,
                   s.created_at AS signal_created_at, s.real_money, s.manual_trade,
                   s.retrospective, s.gate_status, s.gate_audit_note,
                   s.claude_prob, s.confidence, s.edge, s.reasoning
            FROM positions p
            LEFT JOIN markets m ON m.condition_id = p.condition_id
            LEFT JOIN signals s ON s.id = p.signal_id
            WHERE (p.stake_source IN ('real', 'hybrid', 'real_money') OR COALESCE(s.real_money, 0) = 1)
              {status_filter}
            ORDER BY p.opened_at DESC, p.id DESC
            """
        ).fetchall()
    ]


def build_real_money_audit(
    conn,
    *,
    bankroll_usd: float,
    now: datetime | None = None,
    stale_snapshot_hours: float = 12.0,
    urgent_days: float = 7.0,
    include_closed: bool = False,
) -> dict:
    """Return a structured, read-only audit of real-money positions."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    positions: list[dict[str, Any]] = []
    totals = {
        "buy_stake_usd": 0.0,
        "sell_proceeds_usd": 0.0,
        "residual_shares": 0.0,
        "current_value_usd": 0.0,
        "mtm_pnl_usd": 0.0,
        "remaining_worst_case_loss_usd": 0.0,
        "best_case_total_pnl_usd": 0.0,
    }

    for row in _audit_rows(conn, include_closed):
        fills = _fills(conn, row["position_id"])
        buy_fills = [f for f in fills if str(f["side"]).upper() in ENTRY_SIDES]
        sell_fills = [f for f in fills if str(f["side"]).upper().startswith("SELL")]
        buy_stake = sum(float(f["stake_usd"] or 0.0) for f in buy_fills)
        buy_shares = sum(float(f["shares"] or 0.0) for f in buy_fills)
        sell_proceeds = sum(float(f["stake_usd"] or 0.0) for f in sell_fills)
        sell_shares = sum(float(f["shares"] or 0.0) for f in sell_fills)
        residual_shares = max(0.0, buy_shares - sell_shares)
        avg_entry = buy_stake / buy_shares if buy_shares > 0 else None
        remaining_worst_loss = max(0.0, buy_stake - sell_proceeds)

        snapshot = _latest_snapshot(conn, row["condition_id"])
        snapshot_at = snapshot.get("captured_at") if snapshot else None
        snapshot_dt = _parse_dt(snapshot_at)
        snapshot_age_hours = None
        if snapshot_dt is not None:
            snapshot_age_hours = max(0.0, (now - snapshot_dt).total_seconds() / 3600.0)
        yes_price = float(snapshot["yes_price"]) if snapshot and snapshot.get("yes_price") is not None else None
        no_price = float(snapshot["no_price"]) if snapshot and snapshot.get("no_price") is not None else None
        side = str(row.get("intended_side") or "").upper()
        current_side_price = None
        if side == "YES":
            current_side_price = yes_price
        elif side == "NO":
            if no_price is not None:
                current_side_price = no_price
            elif yes_price is not None:
                current_side_price = 1.0 - yes_price
        current_value = residual_shares * current_side_price if current_side_price is not None else None
        mtm_pnl = sell_proceeds + current_value - buy_stake if current_value is not None else None
        best_case_total_pnl = sell_proceeds + residual_shares - buy_stake

        end_at = _parse_dt(row.get("market_end_date") or row.get("position_end_date"))
        days_to_end = (end_at - now).total_seconds() / 86400.0 if end_at else None
        completeness = research_completeness(conn, row["condition_id"])
        approved_prebets = _approved_prebet_count(conn, row["condition_id"], row.get("signal_created_at"))
        gate_label, gate_violation = _gate_status(row, approved_prebets)

        risks: list[dict] = []
        if int(row.get("market_resolved") or 0):
            risks.append(_risk(
                "critical",
                "resolved_position_still_open",
                "Market is marked resolved while this real-money position is still in the open audit set.",
                "Run resolve/learning workflow and reconcile final real-money PnL.",
            ))
        if days_to_end is not None and days_to_end < 0 and row.get("status") in OPEN_POSITION_STATUSES:
            risks.append(_risk(
                "critical",
                "deadline_passed_open_position",
                "Deadline has passed but the position remains open in the ledger.",
                "Check Polymarket resolution state and record outcome/exit before relying on MTM.",
            ))
        elif days_to_end is not None and days_to_end <= urgent_days:
            severity = "high" if days_to_end <= 3 else "medium"
            risks.append(_risk(
                severity,
                "deadline_urgent",
                f"Resolution window is close: {days_to_end:.1f} days remaining.",
                "Run a focused source refresh and resolution-rule check.",
            ))
        if snapshot is None:
            risks.append(_risk(
                "high",
                "missing_snapshot",
                "No market snapshot is available for mark-to-market.",
                "Refresh Gamma/CLOB snapshot before assessing position economics.",
            ))
        elif snapshot_age_hours is not None and snapshot_age_hours > stale_snapshot_hours:
            risks.append(_risk(
                "high",
                "stale_snapshot",
                f"Latest snapshot is {snapshot_age_hours:.1f} hours old.",
                "Refresh market snapshot before making any portfolio decision.",
            ))
        if gate_violation:
            risks.append(_risk(
                "high",
                "gate_violation",
                "Real position is tied to a signal without a prior approved pre-bet checklist.",
                "Treat as post-entry review debt; do not retrofit fake approval.",
            ))
        elif gate_label.startswith("manual"):
            risks.append(_risk(
                "medium",
                "manual_trade_review",
                "Position was recorded as manual/operator real trade rather than formal gated signal.",
                "Complete a retrospective post-entry review and explicit kill criteria.",
            ))
        if completeness["score"] < 60:
            risks.append(_risk(
                "high",
                "thin_dossier",
                f"Research completeness is only {completeness['score']:.1f}/100.",
                "Complete missing dossier blocks before increasing confidence.",
            ))
        elif completeness["score"] < 85:
            risks.append(_risk(
                "medium",
                "incomplete_dossier",
                f"Research completeness is {completeness['score']:.1f}/100.",
                "Fill remaining dossier gaps or explicitly cap confidence.",
            ))
        if remaining_worst_loss > bankroll_usd * 0.10:
            risks.append(_risk(
                "high",
                "large_remaining_loss",
                "Single position remaining worst-case loss exceeds 10% of bankroll.",
                "Run exposure review and avoid adding correlated risk.",
            ))
        if sell_shares > 0 and residual_shares > 0:
            risks.append(_risk(
                "info",
                "partially_de_risked",
                "Position has partial exits and residual shares still open.",
                "Track this as residual optionality; separate realized recovery from open risk.",
            ))

        risks.sort(key=lambda r: (_severity_rank(r["severity"]), r["code"]))
        severity_counts = {
            "critical": sum(1 for r in risks if r["severity"] == "critical"),
            "high": sum(1 for r in risks if r["severity"] == "high"),
            "medium": sum(1 for r in risks if r["severity"] == "medium"),
        }
        if severity_counts["critical"]:
            priority = "critical"
        elif severity_counts["high"]:
            priority = "high"
        elif severity_counts["medium"]:
            priority = "medium"
        else:
            priority = "normal"

        item = {
            "position_id": row["position_id"],
            "signal_id": row.get("signal_id"),
            "condition_id": row["condition_id"],
            "question": row.get("question"),
            "slug": row.get("slug"),
            "side": side,
            "status": row.get("status"),
            "stake_source": row.get("stake_source"),
            "vertical": row.get("vertical"),
            "end_date": row.get("market_end_date") or row.get("position_end_date"),
            "days_to_end": _round(days_to_end, 2),
            "fills": {
                "buy_count": len(buy_fills),
                "sell_count": len(sell_fills),
                "buy_stake_usd": _round(buy_stake),
                "buy_shares": _round(buy_shares, 4),
                "sell_proceeds_usd": _round(sell_proceeds),
                "sell_shares": _round(sell_shares, 4),
                "residual_shares": _round(residual_shares, 4),
                "avg_entry_price": _round(avg_entry, 4),
            },
            "mark_to_market": {
                "snapshot_at": snapshot_at,
                "snapshot_age_hours": _round(snapshot_age_hours, 2),
                "yes_price": _round(yes_price, 4),
                "no_price": _round(no_price, 4),
                "current_side_price": _round(current_side_price, 4),
                "current_value_usd": _round(current_value),
                "mtm_pnl_usd": _round(mtm_pnl),
                "remaining_worst_case_loss_usd": _round(remaining_worst_loss),
                "best_case_total_pnl_usd": _round(best_case_total_pnl),
            },
            "research_state": {
                "gate_status": gate_label,
                "gate_violation": gate_violation,
                "approved_prebet_count": approved_prebets,
                "dossier_score": completeness["score"],
                "missing_dossier_blocks": completeness["missing"],
                "manual_trade": bool(row.get("manual_trade")),
                "post_entry_review_required": bool(row.get("post_entry_review_required")),
                "post_entry_review_reason": row.get("post_entry_review_reason"),
            },
            "risks": risks,
            "priority": priority,
        }
        positions.append(item)

        totals["buy_stake_usd"] += buy_stake
        totals["sell_proceeds_usd"] += sell_proceeds
        totals["residual_shares"] += residual_shares
        totals["remaining_worst_case_loss_usd"] += remaining_worst_loss
        totals["best_case_total_pnl_usd"] += best_case_total_pnl
        if current_value is not None:
            totals["current_value_usd"] += current_value
        if mtm_pnl is not None:
            totals["mtm_pnl_usd"] += mtm_pnl

    positions.sort(key=lambda p: (_severity_rank(p["priority"]), p["days_to_end"] if p["days_to_end"] is not None else 9999))
    priority_actions = []
    seen_actions: set[tuple[str, str]] = set()
    for p in positions:
        for risk in p["risks"]:
            key = (p["condition_id"], risk["code"])
            if key in seen_actions:
                continue
            seen_actions.add(key)
            priority_actions.append({
                "priority": risk["severity"],
                "condition_id": p["condition_id"],
                "position_id": p["position_id"],
                "question": p["question"],
                "risk_code": risk["code"],
                "action": risk["recommended_research_action"],
            })
    priority_actions.sort(key=lambda a: _severity_rank(a["priority"]))

    totals = {k: _round(v) for k, v in totals.items()}
    totals["remaining_worst_case_loss_pct_bankroll"] = _round(
        (totals["remaining_worst_case_loss_usd"] or 0.0) / bankroll_usd * 100 if bankroll_usd else 0.0,
        2,
    )
    totals["buy_stake_pct_bankroll"] = _round(
        (totals["buy_stake_usd"] or 0.0) / bankroll_usd * 100 if bankroll_usd else 0.0,
        2,
    )

    return {
        "workflow": "real_money_portfolio_audit",
        "workflow_level": "L2/L4 read-only portfolio research",
        "generated_at": now.isoformat(),
        "rules": {
            "signals_created": False,
            "positions_created": False,
            "fills_created": False,
            "allowed_writes": [],
            "boundary": "Diagnostic research queue only; not financial advice and not a trade instruction.",
        },
        "settings": {
            "bankroll_usd": bankroll_usd,
            "stale_snapshot_hours": stale_snapshot_hours,
            "urgent_days": urgent_days,
            "include_closed": include_closed,
        },
        "summary": {
            "positions_count": len(positions),
            "critical_count": sum(1 for p in positions if p["priority"] == "critical"),
            "high_count": sum(1 for p in positions if p["priority"] == "high"),
            "medium_count": sum(1 for p in positions if p["priority"] == "medium"),
            "normal_count": sum(1 for p in positions if p["priority"] == "normal"),
            **totals,
        },
        "positions": positions,
        "priority_actions": priority_actions[:50],
    }
