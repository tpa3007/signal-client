"""Unified read-side research ledger.

The project stores facts in normalized tables: markets, snapshots, reviews,
analyses, signals, positions, and outcome reviews. This module turns those facts
into one lifecycle row per market for dashboards and operator queues.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import config
from lib.ledger_meta import edge_archetype_from_primary, post_entry_review_signal
from lib.queries import latest_probability, research_completeness

OPEN_POSITION_STATUSES = {"open", "filled", "partially_filled"}


def _dict(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _latest(conn, table: str, condition_id: str, order_col: str = "created_at") -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT * FROM {table} WHERE condition_id = ? ORDER BY {order_col} DESC, id DESC LIMIT 1",
        (condition_id,),
    ).fetchone()
    return _dict(row)


def _count(conn, table: str, condition_id: str) -> int:
    return int(conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE condition_id = ?",
        (condition_id,),
    ).fetchone()["n"])


def _latest_snapshot(conn, condition_id: str) -> dict[str, Any] | None:
    row = conn.execute("""
        SELECT * FROM snapshots
        WHERE condition_id = ?
        ORDER BY captured_at DESC, id DESC LIMIT 1
    """, (condition_id,)).fetchone()
    return _dict(row)


def _theme_tags(conn, condition_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT tag FROM market_tags WHERE condition_id = ? ORDER BY tag",
        (condition_id,),
    ).fetchall()
    return [r["tag"] for r in rows]


def _source_count(conn, condition_id: str) -> int:
    row = conn.execute("""
        SELECT COUNT(DISTINCT COALESCE(source_url, source_name)) AS n
        FROM evidence
        WHERE condition_id = ?
          AND COALESCE(source_url, source_name) IS NOT NULL
    """, (condition_id,)).fetchone()
    return int(row["n"] or 0)


def _latest_pnl_event(conn, position_id: int | None) -> dict[str, Any] | None:
    if not position_id:
        return None
    row = conn.execute(
        """
        SELECT * FROM pnl_events
        WHERE position_id = ?
        ORDER BY event_at DESC, id DESC LIMIT 1
        """,
        (position_id,),
    ).fetchone()
    return _dict(row)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _age_hours(value: str | None) -> float | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _days_to_deadline(value: str | None) -> float | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - datetime.now(timezone.utc)).total_seconds() / 86400.0


def _max_timestamp(*values: str | None) -> str | None:
    valid = [v for v in values if v]
    if not valid:
        return None
    return max(valid)


def _side_prices(snapshot: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not snapshot or snapshot.get("yes_price") is None:
        return None, None
    yes = float(snapshot["yes_price"])
    no = snapshot.get("no_price")
    no = float(no) if no is not None else 1.0 - yes
    return yes, no



def _approved_prebet_before_signal(conn, condition_id: str, signal_created_at: str | None) -> dict[str, Any] | None:
    if not signal_created_at:
        return None
    row = conn.execute("""
        SELECT id, decision, checklist_score, created_at
        FROM pre_bet_checklists
        WHERE condition_id = ?
          AND created_at <= ?
          AND decision = 'approved_for_signal'
        ORDER BY created_at DESC, id DESC LIMIT 1
    """, (condition_id, signal_created_at)).fetchone()
    return _dict(row)

def _research_lane(snapshot: dict[str, Any] | None,
                   hidden: dict[str, Any] | None,
                   moonshot: dict[str, Any] | None) -> str:
    yes, no = _side_prices(snapshot)
    if moonshot is not None:
        return "moonshot"
    if yes is not None and no is not None:
        if yes <= config.SPECULATIVE_PRICE_MAX or no <= config.SPECULATIVE_PRICE_MAX:
            return "moonshot"
        lo = config.DISCOVERY_COMPOUNDER_PRICE_MIN
        hi = config.DISCOVERY_COMPOUNDER_PRICE_MAX
        if (lo <= yes <= hi) or (lo <= no <= hi):
            return "compounder"
    if hidden is not None:
        return "hidden"
    return "unknown"


def _latest_review(hidden: dict[str, Any] | None,
                   moonshot: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if hidden is None and moonshot is None:
        return None, None
    if hidden is None:
        return moonshot, "moonshot"
    if moonshot is None:
        return hidden, "hidden_gem"
    h_at = hidden.get("created_at") or ""
    m_at = moonshot.get("created_at") or ""
    return (moonshot, "moonshot") if m_at >= h_at else (hidden, "hidden_gem")


def _status(market: dict[str, Any],
            hidden: dict[str, Any] | None,
            moonshot: dict[str, Any] | None,
            prebet: dict[str, Any] | None,
            analysis: dict[str, Any] | None,
            signal: dict[str, Any] | None,
            position: dict[str, Any] | None,
            outcome: dict[str, Any] | None,
            dossier_counts: dict[str, int]) -> str:
    if outcome is not None:
        return "learned"
    touched = any([hidden, moonshot, prebet, analysis, signal, position]) or any(dossier_counts.values())
    if market.get("resolved") and touched:
        return "resolved_pending_learning"
    if position is not None and position.get("status") in OPEN_POSITION_STATUSES:
        return "open_position"
    if signal is not None:
        return "signal"
    if prebet is not None:
        if prebet.get("decision") == "approved_for_signal":
            return "approved_for_signal"
        return "needs_more_research"
    if analysis is not None:
        if analysis.get("decision") == "signal":
            return "signal"
        return "no_signal"

    review, _ = _latest_review(hidden, moonshot)
    decision = (review or {}).get("decision", "")
    decision_l = decision.lower()
    if decision_l.startswith("reject"):
        return "rejected"
    if "deep" in decision_l or "promote" in decision_l:
        return "deep_research"
    if "watch" in decision_l:
        return "watch"
    if review is not None:
        return "review_recorded"
    if any(dossier_counts.values()):
        return "research_in_progress"
    return "discovered"


def _score(review: dict[str, Any] | None,
           review_type: str | None,
           prebet: dict[str, Any] | None,
           quality: dict[str, Any] | None) -> tuple[float | None, str | None]:
    if quality is not None and quality.get("total_score") is not None:
        return float(quality["total_score"]), "quality"
    if prebet is not None and prebet.get("checklist_score") is not None:
        return float(prebet["checklist_score"]), "checklist"
    if review is not None and review.get("total_score") is not None:
        return float(review["total_score"]), review_type
    return None, None


def _latest_decision(prebet: dict[str, Any] | None,
                     analysis: dict[str, Any] | None,
                     review: dict[str, Any] | None) -> str | None:
    if prebet is not None:
        return prebet.get("decision")
    if analysis is not None:
        return analysis.get("decision")
    if review is not None:
        return review.get("decision")
    return None


def _next_action(status: str, missing: list[str], next_check_at: str | None,
                 stale_open: bool) -> tuple[str | None, str | None, str]:
    if status == "resolved_pending_learning":
        return "record_outcome_learning_review", "resolved market has no learning review", "critical"
    if status == "open_position":
        if stale_open:
            return "record_forecast_update", "open position has no fresh forecast update", "high"
        return "monitor_position", None, "medium"
    if status == "approved_for_signal":
        return "record_analysis", "pre-bet checklist approved; verify fresh snapshot first", "high"
    if status == "deep_research":
        return "complete_dossier", ", ".join(missing) if missing else None, "high"
    if status == "needs_more_research":
        return "complete_missing_research", ", ".join(missing) if missing else None, "medium"
    if status == "watch":
        action = "recheck_watch_candidate" if next_check_at else "collect_more_sources"
        return action, None, "medium"
    if status == "no_signal":
        return "monitor_false_negative_risk", None, "low"
    if status == "rejected":
        return "no_action_until_new_catalyst", None, "low"
    if status == "learned":
        return "review_lessons", None, "low"
    if status == "discovered":
        return "run_api_research_enrichment", "not yet reviewed", "low"
    return "inspect_market", None, "medium"


def build_research_ledger_row(conn, market: dict[str, Any]) -> dict[str, Any]:
    cid = market["condition_id"]
    snapshot = _latest_snapshot(conn, cid)
    hidden = _latest(conn, "hidden_gem_reviews", cid)
    moonshot = _latest(conn, "moonshot_reviews", cid)
    prebet = _latest(conn, "pre_bet_checklists", cid)
    analysis = _latest(conn, "analyses", cid)
    signal = _latest(conn, "signals", cid)
    approved_prebet = _approved_prebet_before_signal(conn, cid, signal.get("created_at") if signal else None)
    manual_trade = bool(signal.get("manual_trade")) if signal else False
    gate_status = signal.get("gate_status") if signal else None
    legacy_gate_violation = gate_status == "legacy_gate_violation"
    gate_violation = (
        signal is not None
        and approved_prebet is None
        and not manual_trade
        and not legacy_gate_violation
    )
    position = _latest(conn, "positions", cid, "opened_at")
    latest_pnl = _latest_pnl_event(conn, position.get("id") if position else None)
    outcome = _latest(conn, "outcome_learning_reviews", cid)
    quality = _latest(conn, "signal_quality_reviews", cid)
    review, review_type = _latest_review(hidden, moonshot)
    completeness = research_completeness(conn, cid)
    counts = {
        "evidence": _count(conn, "evidence", cid),
        "resolution_maps": _count(conn, "resolution_maps", cid),
        "actor_maps": _count(conn, "actor_maps", cid),
        "causal_factors": _count(conn, "causal_factors", cid),
        "scenario_trees": _count(conn, "scenario_trees", cid),
        "premortems": _count(conn, "premortems", cid),
        "forecast_updates": _count(conn, "forecast_updates", cid),
    }
    status = _status(market, hidden, moonshot, prebet, analysis, signal, position, outcome, counts)
    score, score_type = _score(review, review_type, prebet, quality)
    latest_update = _latest(conn, "forecast_updates", cid)
    latest_touch = _max_timestamp(
        market.get("last_seen_at"),
        snapshot.get("captured_at") if snapshot else None,
        hidden.get("created_at") if hidden else None,
        moonshot.get("created_at") if moonshot else None,
        prebet.get("created_at") if prebet else None,
        analysis.get("created_at") if analysis else None,
        signal.get("created_at") if signal else None,
        position.get("opened_at") if position else None,
        outcome.get("created_at") if outcome else None,
    )
    last_forecast_touch = _max_timestamp(
        analysis.get("created_at") if analysis else None,
        latest_update.get("created_at") if latest_update else None,
        position.get("opened_at") if position else None,
    )
    stale_open = status == "open_position" and ((_age_hours(last_forecast_touch) or 0) >= 72)
    next_action, blocker, priority = _next_action(
        status,
        completeness["missing"],
        review.get("next_check_at") if review else None,
        stale_open,
    )
    if gate_violation:
        priority = "critical"
        blocker = "signal exists without approved pre_bet_checklist before signal time"
        next_action = "repair_signal_gate_audit"
    elif legacy_gate_violation:
        blocker = "legacy signal without approved pre_bet_checklist; quarantined from new gated signals"
        next_action = "legacy_gate_violation_review"
        priority = "medium"
    yes, no = _side_prices(snapshot)
    prob = latest_probability(conn, cid)
    edge = analysis.get("edge") if analysis else (signal.get("edge") if signal else None)
    edge_archetype = (
        (position or {}).get("edge_archetype")
        or (signal or {}).get("edge_archetype")
        or edge_archetype_from_primary((position or {}).get("primary_archetype"), market.get("question"))
    )
    edge_archetype = edge_archetype_from_primary(edge_archetype, market.get("question"))
    signal_epoch = (
        (position or {}).get("signal_generation_epoch")
        or (signal or {}).get("signal_generation_epoch")
        or ("legacy" if legacy_gate_violation else None)
    )
    confidence_src = (
        (position or {}).get("confidence_source")
        or (signal or {}).get("confidence_source")
    )
    approval = (
        (position or {}).get("approval_strength")
        or (signal or {}).get("approval_strength")
    )
    mtm_pct = None
    if latest_pnl and position and position.get("intended_stake_usd"):
        stake = float(position.get("intended_stake_usd") or 0)
        if stake > 0 and latest_pnl.get("delta_pnl_usd") is not None:
            mtm_pct = float(latest_pnl["delta_pnl_usd"]) / stake * 100.0
    if mtm_pct is None and position and snapshot:
        try:
            intended_side = str(position.get("intended_side") or "YES").upper()
            side_entry = float(position.get("side_entry_price") or position.get("intended_entry_price") or 0)
            current_side = yes if intended_side == "YES" else no
            if side_entry > 0 and current_side is not None:
                mtm_pct = (float(current_side) - side_entry) / side_entry * 100.0
        except (TypeError, ValueError):
            mtm_pct = None
    review_required, review_reason = post_entry_review_signal(
        mtm_pnl_pct=mtm_pct,
        days_to_deadline=_days_to_deadline(market.get("end_date")),
        gate_status=gate_status,
        stake_source=(position or {}).get("stake_source"),
        edge_archetype=edge_archetype,
    )
    if position and position.get("post_entry_review_required") is not None:
        review_required = bool(position.get("post_entry_review_required")) or review_required
        if position.get("post_entry_review_reason"):
            review_reason = position.get("post_entry_review_reason")

    return {
        "condition_id": cid,
        "question": market["question"],
        "slug": market.get("slug"),
        "vertical": market.get("vertical") or "unknown",
        "theme_tags": _theme_tags(conn, cid),
        "status": status,
        "priority": priority,
        "research_lane": _research_lane(snapshot, hidden, moonshot),
        "current_yes_price": yes,
        "current_no_price": no,
        "spread": snapshot.get("spread") if snapshot else None,
        "liquidity": snapshot.get("liquidity") if snapshot else None,
        "volume": snapshot.get("volume") if snapshot else None,
        "snapshot_at": snapshot.get("captured_at") if snapshot else None,
        "end_date": market.get("end_date"),
        "resolved": bool(market.get("resolved")),
        "resolved_yes": market.get("resolved_yes"),
        "model_probability_yes": prob,
        "confidence": analysis.get("confidence") if analysis else (signal.get("confidence") if signal else None),
        "edge": edge,
        "signal_generation_epoch": signal_epoch,
        "edge_archetype": edge_archetype,
        "confidence_source": confidence_src,
        "approval_strength": approval,
        "post_entry_review_required": review_required,
        "post_entry_review_reason": review_reason,
        "latest_mtm_pnl_pct": round(mtm_pct, 2) if mtm_pct is not None else None,
        "score": score,
        "score_type": score_type,
        "latest_decision": _latest_decision(prebet, analysis, review),
        "decision_reason": analysis.get("no_signal_reason") if analysis else None,
        "blocker": blocker,
        "next_action": next_action,
        "next_check_at": review.get("next_check_at") if review else None,
        "dossier_completeness": completeness["score"],
        "missing_dossier_blocks": completeness["missing"],
        "dossier_counts": completeness["counts"],
        "source_count": _source_count(conn, cid),
        "evidence_count": counts["evidence"],
        "analysis_id": analysis.get("id") if analysis else None,
        "signal_id": signal.get("id") if signal else None,
        "position_id": position.get("id") if position else None,
        "approved_prebet_id": approved_prebet.get("id") if approved_prebet else None,
        "gate_violation": gate_violation,
        "legacy_gate_violation": legacy_gate_violation,
        "gate_status": gate_status,
        "gate_audit_note": signal.get("gate_audit_note") if signal else None,
        "manual_trade": manual_trade,
        "latest_review_id": review.get("id") if review else None,
        "outcome_review_id": outcome.get("id") if outcome else None,
        "created_at": market.get("first_seen_at"),
        "last_touched_at": latest_touch,
        "stale_open_position": stale_open,
    }


def research_ledger_rows(conn, *, status: str | None = None, lane: str | None = None,
                         limit: int = 100, include_discovered: bool = False) -> list[dict[str, Any]]:
    status = status or None
    lane = lane or None
    limit = max(1, min(int(limit), 500))
    markets = conn.execute("""
        SELECT * FROM markets
        ORDER BY last_seen_at DESC, first_seen_at DESC
    """).fetchall()
    out: list[dict[str, Any]] = []
    for market_row in markets:
        row = build_research_ledger_row(conn, dict(market_row))
        if not include_discovered and row["status"] == "discovered":
            continue
        if status and row["status"] != status:
            continue
        if lane and row["research_lane"] != lane:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def research_ledger_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_epoch: dict[str, int] = {}
    by_edge_archetype: dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        by_lane[row["research_lane"]] = by_lane.get(row["research_lane"], 0) + 1
        by_priority[row["priority"]] = by_priority.get(row["priority"], 0) + 1
        epoch = row.get("signal_generation_epoch") or "none"
        edge_archetype = row.get("edge_archetype") or "unknown"
        by_epoch[epoch] = by_epoch.get(epoch, 0) + 1
        by_edge_archetype[edge_archetype] = by_edge_archetype.get(edge_archetype, 0) + 1
    return {
        "count": len(rows),
        "by_status": by_status,
        "by_lane": by_lane,
        "by_priority": by_priority,
        "by_signal_generation_epoch": by_epoch,
        "by_edge_archetype": by_edge_archetype,
        "critical_or_high": sum(1 for r in rows if r["priority"] in {"critical", "high"}),
        "gate_violations": sum(1 for r in rows if r.get("gate_violation")),
        "post_entry_review_required": sum(1 for r in rows if r.get("post_entry_review_required")),
    }
