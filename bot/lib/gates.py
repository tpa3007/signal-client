"""Signal gate validation helpers.

This module is the hard runtime layer behind the agent contracts. It answers one
question: can a researched market legally become a formal Signal position now?
"""
from __future__ import annotations

from typing import Any

import config
import db
from lib.execution import best_executable_edge, no_signal_reason
from lib.exposure import check_exposure
from lib.queries import latest_snapshot_with_age
from lib.sizing import recommended_stake


REQUIRED_DOSSIER_COUNTS = {
    "resolution_maps": 1,
    "evidence": 2,
    "actor_maps": 1,
    "causal_factors": 2,
    "scenario_trees": 3,
    "premortems": 1,
}


def _count(conn, table: str, condition_id: str) -> int:
    return int(conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE condition_id = ?",
        (condition_id,),
    ).fetchone()["n"])


def _source_count(conn, condition_id: str) -> int:
    row = conn.execute("""
        SELECT COUNT(DISTINCT COALESCE(source_url, source_name)) AS n
        FROM evidence
        WHERE condition_id = ?
          AND COALESCE(source_url, source_name) IS NOT NULL
    """, (condition_id,)).fetchone()
    return int(row["n"] or 0)


def _latest_approved_prebet(conn, condition_id: str):
    return conn.execute("""
        SELECT *
        FROM pre_bet_checklists
        WHERE condition_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
    """, (condition_id,)).fetchone()


def validate_signal_gate(
    conn,
    *,
    condition_id: str,
    probability_yes: float | None = None,
    confidence: float | None = None,
    intended_side: str | None = None,
    proposed_stake_usd: float | None = None,
    primary_archetype: str | None = None,
) -> dict[str, Any]:
    """Return a complete pass/block decision for formal Signal creation."""
    blockers: list[str] = []
    missing_blocks: list[str] = []

    market = conn.execute(
        "SELECT condition_id, question, slug, vertical, end_date FROM markets WHERE condition_id = ?",
        (condition_id,),
    ).fetchone()
    if not market:
        return {
            "ok": False,
            "condition_id": condition_id,
            "blockers": ["market_not_found"],
            "missing_blocks": ["market"],
            "next_action": "fetch_or_upsert_market_first",
        }

    snapshot, snapshot_age_min, snapshot_stale = latest_snapshot_with_age(
        conn, condition_id, config.MAX_SNAPSHOT_AGE_MIN
    )
    if snapshot is None:
        blockers.append("missing_fresh_snapshot")
        missing_blocks.append("snapshot")
    elif snapshot_stale:
        blockers.append("snapshot_stale")

    open_position = conn.execute("""
        SELECT id, status
        FROM positions
        WHERE condition_id = ? AND status IN ('open', 'filled', 'partially_filled')
        ORDER BY opened_at DESC, id DESC LIMIT 1
    """, (condition_id,)).fetchone()
    if open_position is not None:
        blockers.append("open_position_exists")

    latest_prebet = _latest_approved_prebet(conn, condition_id)
    if latest_prebet is None:
        blockers.append("missing_pre_bet_checklist")
        missing_blocks.append("pre_bet_checklist")
    elif latest_prebet["decision"] != "approved_for_signal":
        blockers.append(f"pre_bet_{latest_prebet['decision']}")

    if probability_yes is None and latest_prebet is not None:
        probability_yes = float(latest_prebet["estimated_probability"])
    if confidence is None and latest_prebet is not None:
        confidence = float(latest_prebet["confidence"])
    if intended_side is None and latest_prebet is not None:
        intended_side = latest_prebet["intended_side"]

    if probability_yes is None:
        blockers.append("missing_probability_yes")
    else:
        probability_yes = max(0.0, min(1.0, float(probability_yes)))
    if confidence is None:
        blockers.append("missing_confidence")
    else:
        confidence = max(0.0, min(1.0, float(confidence)))

    counts = {table: _count(conn, table, condition_id) for table in REQUIRED_DOSSIER_COUNTS}
    for table, required in REQUIRED_DOSSIER_COUNTS.items():
        if counts[table] < required:
            missing_blocks.append(table)
            blockers.append(f"{table}_below_required_{required}")

    source_count = _source_count(conn, condition_id)
    if source_count < 2:
        blockers.append("source_depth_below_required_2")
        missing_blocks.append("source_depth")

    signal_side = None
    executable_edge = None
    yes_equivalent_entry = None
    side_entry_price = None
    numeric_gate_reason = None
    sizing_info = None
    exposure = None

    if snapshot is not None and probability_yes is not None and confidence is not None:
        yes_price = float(snapshot["yes_price"])
        no_price = float(snapshot["no_price"]) if snapshot["no_price"] is not None else 1.0 - yes_price
        yes_entry = float(snapshot["yes_entry_price"]) if snapshot["yes_entry_price"] is not None else yes_price
        no_entry = float(snapshot["no_entry_price"]) if snapshot["no_entry_price"] is not None else no_price
        spread = float(snapshot["spread"]) if snapshot["spread"] is not None else None
        best_side, best_edge = best_executable_edge(probability_yes, yes_entry, no_entry)
        signal_side = (intended_side or best_side or "").upper()
        if signal_side not in {"YES", "NO"}:
            blockers.append("invalid_intended_side")
            signal_side = best_side
        executable_edge = probability_yes - yes_entry if signal_side == "YES" else (1.0 - probability_yes) - no_entry
        yes_equivalent_entry = yes_entry if signal_side == "YES" else 1.0 - no_entry
        side_entry_price = yes_entry if signal_side == "YES" else no_entry
        numeric_gate_reason = no_signal_reason(executable_edge, confidence, spread)
        if numeric_gate_reason is not None:
            blockers.append(numeric_gate_reason)

        if proposed_stake_usd is None:
            sizing_info = recommended_stake(
                edge=executable_edge,
                confidence=confidence,
                conn=conn,
                condition_id=condition_id,
                vertical=market["vertical"] or "unknown",
                primary_archetype=primary_archetype,
                end_date=market["end_date"],
                theme_tags=db.get_market_tags(conn, condition_id),
            )
            proposed_stake_usd = sizing_info["recommended"]
        exposure = check_exposure(
            conn,
            condition_id=condition_id,
            vertical=market["vertical"] or "unknown",
            primary_archetype=primary_archetype,
            end_date=market["end_date"],
            proposed_stake_usd=float(proposed_stake_usd or 0.0),
            theme_tags=db.get_market_tags(conn, condition_id),
        )
        if not exposure.get("allowed"):
            blockers.append("exposure_cap_breached")

    # De-duplicate while preserving order.
    blockers = list(dict.fromkeys(blockers))
    missing_blocks = list(dict.fromkeys(missing_blocks))
    ok = not blockers
    return {
        "ok": ok,
        "condition_id": condition_id,
        "question": market["question"],
        "blockers": blockers,
        "missing_blocks": missing_blocks,
        "next_action": "aladdin_signal_commit" if ok else "complete_missing_gate_blocks",
        "snapshot": dict(snapshot) if snapshot else None,
        "snapshot_age_min": round(snapshot_age_min, 2) if snapshot_age_min is not None else None,
        "latest_pre_bet_checklist": dict(latest_prebet) if latest_prebet else None,
        "open_position": dict(open_position) if open_position else None,
        "dossier_counts": counts,
        "source_count": source_count,
        "probability_yes": probability_yes,
        "confidence": confidence,
        "side": signal_side,
        "yes_equivalent_entry": yes_equivalent_entry,
        "side_entry_price": side_entry_price,
        "executable_edge": executable_edge,
        "numeric_gate_reason": numeric_gate_reason,
        "proposed_stake_usd": proposed_stake_usd,
        "sizing": sizing_info,
        "exposure": exposure,
        "thresholds": {
            "edge_threshold": config.EDGE_THRESHOLD,
            "min_confidence": config.MIN_CONFIDENCE,
            "max_spread": config.MAX_SPREAD,
            "min_spread_adjusted_edge": config.MIN_SPREAD_ADJ_EDGE,
            "max_snapshot_age_min": config.MAX_SNAPSHOT_AGE_MIN,
        },
    }
