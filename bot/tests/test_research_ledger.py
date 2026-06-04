from __future__ import annotations

import db
from lib.ledger import research_ledger_rows, research_ledger_summary


def _market(conn, cid: str, yes_price: float = 0.45, resolved: bool = False) -> None:
    db.upsert_market(
        conn,
        condition_id=cid,
        question=f"Will market {cid} resolve YES?",
        slug=f"market-{cid}",
        end_date="2026-08-01T00:00:00Z",
        vertical="us_politics",
    )
    db.add_snapshot(
        conn,
        condition_id=cid,
        yes_price=yes_price,
        no_price=1.0 - yes_price,
        best_bid=yes_price - 0.01,
        best_ask=yes_price + 0.01,
        spread=0.02,
        yes_entry_price=yes_price + 0.01,
        no_entry_price=1.0 - yes_price + 0.01,
        volume=50_000,
        liquidity=20_000,
        source="test",
    )
    if resolved:
        conn.execute(
            "UPDATE markets SET resolved=1, resolved_yes=1.0, resolved_at=? WHERE condition_id=?",
            ("2026-07-01T00:00:00+00:00", cid),
        )


def _hidden_review(conn, cid: str, decision: str = "watchlist") -> int:
    return db.add_hidden_gem_review(
        conn,
        condition_id=cid,
        created_at=None,
        analyst="test",
        executable_edge=0.08,
        liquidity_score=0.8,
        spread_score=0.8,
        attention_gap_score=0.7,
        evidence_asymmetry_score=0.6,
        stale_price_score=0.4,
        catalyst_score=0.6,
        resolution_clarity_score=0.7,
        total_score=58.0,
        thesis="Interesting but not ready.",
        disconfirming_evidence="Needs better source trail.",
        next_check_at="2026-06-01T00:00:00+00:00",
        decision=decision,
    )


def _analysis(conn, cid: str, decision: str = "no_signal") -> int:
    return db.add_analysis(
        conn,
        run_date="2026-05-19",
        condition_id=cid,
        created_at=None,
        analyst="test",
        model="test",
        yes_price_at_analysis=0.45,
        probability_yes=0.55,
        confidence=0.5,
        edge=0.10,
        decision=decision,
        no_signal_reason="missing_pre_bet_checklist" if decision == "no_signal" else None,
        signal_id=None,
        reasoning="Test reasoning",
        sources_json="[]",
        notes="",
    )


def test_research_ledger_includes_watch_candidate(conn):
    _market(conn, "watch", yes_price=0.45)
    _hidden_review(conn, "watch", decision="watchlist_priority")
    conn.commit()

    rows = research_ledger_rows(conn, include_discovered=False)

    assert len(rows) == 1
    row = rows[0]
    assert row["condition_id"] == "watch"
    assert row["status"] == "watch"
    assert row["research_lane"] == "compounder"
    assert row["latest_decision"] == "watchlist_priority"
    assert row["next_action"] == "recheck_watch_candidate"


def test_research_ledger_filters_out_pure_discovered_by_default(conn):
    _market(conn, "new", yes_price=0.48)
    conn.commit()

    assert research_ledger_rows(conn) == []
    rows = research_ledger_rows(conn, include_discovered=True)

    assert len(rows) == 1
    assert rows[0]["status"] == "discovered"


def test_research_ledger_marks_open_position(conn):
    _market(conn, "pos", yes_price=0.40)
    signal_id = db.add_signal(
        conn,
        condition_id="pos",
        created_at=None,
        model="test",
        yes_price_at_signal=0.41,
        claude_prob=0.62,
        confidence=0.65,
        side="YES",
        edge=0.21,
        bet_amount=10.0,
        reasoning="Test signal",
        sources_json="[]",
        tokens_in=None,
        tokens_out=None,
        cache_read_tokens=None,
        cost_usd=0.0,
    )
    position_id = db.add_position(
        conn,
        condition_id="pos",
        signal_id=signal_id,
        opened_at=None,
        intended_side="YES",
        intended_entry_price=0.41,
        intended_stake_usd=10.0,
        stake_source="paper",
        status="open",
        thesis_snapshot_text="Test signal",
        primary_archetype=None,
        end_date="2026-08-01T00:00:00Z",
    )
    conn.commit()

    row = research_ledger_rows(conn)[0]

    assert row["status"] == "open_position"
    assert row["signal_id"] == signal_id
    assert row["position_id"] == position_id
    assert row["gate_violation"] is True
    assert row["approved_prebet_id"] is None
    assert row["signal_generation_epoch"] == "legacy"
    assert row["edge_archetype"] == "unknown"
    assert row["approval_strength"] in {"A", "B", "C", "D", "F"}
    assert row["priority"] == "critical"
    assert row["next_action"] == "repair_signal_gate_audit"


def test_research_ledger_marks_resolved_pending_learning_and_learned(conn):
    _market(conn, "done", yes_price=0.40, resolved=True)
    analysis_id = _analysis(conn, "done")
    conn.commit()

    row = research_ledger_rows(conn)[0]
    assert row["status"] == "resolved_pending_learning"
    assert row["priority"] == "critical"
    assert row["next_action"] == "record_outcome_learning_review"

    db.add_outcome_learning_review(
        conn,
        condition_id="done",
        signal_id=None,
        analysis_id=analysis_id,
        created_at=None,
        analyst="test",
        outcome_side="YES",
        predicted_side="YES",
        entry_price=0.40,
        probability_yes=0.55,
        confidence=0.5,
        realized_pnl=None,
        brier_score=0.2025,
        market_brier_score=0.36,
        outcome_summary="Resolved YES.",
        why_right_or_wrong="Test review.",
        resolution_error=0,
        probability_error=0,
        evidence_error=0,
        timing_error=0,
        sizing_error=0,
        luck_factor=0.5,
        repeatable_lesson="Keep tracking.",
        rule_update=None,
    )
    conn.commit()

    row = research_ledger_rows(conn)[0]
    assert row["status"] == "learned"
    assert row["outcome_review_id"] is not None


def test_research_ledger_summary_counts(conn):
    _market(conn, "a", yes_price=0.45)
    _hidden_review(conn, "a", decision="watchlist")
    _market(conn, "b", yes_price=0.08)
    _hidden_review(conn, "b", decision="reject_random")
    conn.commit()

    rows = research_ledger_rows(conn)
    summary = research_ledger_summary(rows)

    assert summary["count"] == 2
    assert summary["by_status"] == {"watch": 1, "rejected": 1}
    assert summary["by_lane"]["moonshot"] == 1
    assert summary["post_entry_review_required"] == 0

def test_research_ledger_does_not_flag_signal_with_prior_approved_prebet(conn):
    _market(conn, "approved", yes_price=0.40)
    prebet_id = db.add_pre_bet_checklist(
        conn,
        condition_id="approved",
        created_at="2026-05-19T00:00:00+00:00",
        analyst="test",
        intended_side="YES",
        intended_entry_price=0.41,
        estimated_probability=0.62,
        confidence=0.65,
        edge=0.21,
        has_resolution_map=1,
        has_evidence_base=1,
        has_actor_map=1,
        has_causal_model=1,
        has_scenario_tree=1,
        has_premortem=1,
        has_moonshot_review=0,
        evidence_balance_ok=1,
        spread_ok=1,
        liquidity_ok=1,
        sizing_ok=1,
        resolution_risk_ok=1,
        thesis="Approved test",
        top_risks="Test risk",
        disconfirming_evidence="Test counter",
        checklist_score=95.0,
        decision="approved_for_signal",
        next_action="record_analysis",
    )
    signal_id = db.add_signal(
        conn,
        condition_id="approved",
        created_at="2026-05-19T01:00:00+00:00",
        model="test",
        yes_price_at_signal=0.41,
        claude_prob=0.62,
        confidence=0.65,
        side="YES",
        edge=0.21,
        bet_amount=10.0,
        reasoning="Test signal",
        sources_json="[]",
        tokens_in=None,
        tokens_out=None,
        cache_read_tokens=None,
        cost_usd=0.0,
    )
    db.add_position(
        conn,
        condition_id="approved",
        signal_id=signal_id,
        opened_at="2026-05-19T01:00:00+00:00",
        intended_side="YES",
        intended_entry_price=0.41,
        intended_stake_usd=10.0,
        stake_source="paper",
        status="open",
        thesis_snapshot_text="Test signal",
        primary_archetype=None,
        end_date="2026-08-01T00:00:00Z",
    )
    conn.commit()

    row = research_ledger_rows(conn)[0]

    assert row["gate_violation"] is False
    assert row["approved_prebet_id"] == prebet_id
    assert row["status"] == "open_position"


def test_research_ledger_exposes_epoch_and_review_flags(conn):
    _market(conn, "meta", yes_price=0.40)
    signal_id = db.add_signal(
        conn,
        condition_id="meta",
        created_at="2026-05-19T01:00:00+00:00",
        model="aladdin-signal-commit",
        yes_price_at_signal=0.41,
        claude_prob=0.62,
        confidence=0.70,
        side="YES",
        edge=0.21,
        bet_amount=10.0,
        reasoning="Local election polling thesis.",
        sources_json="[]",
        tokens_in=None,
        tokens_out=None,
        cache_read_tokens=None,
        cost_usd=0.0,
        gate_status="gated",
        primary_archetype="election_local_asymmetry",
        operator_approved=True,
        post_entry_review_required=1,
        post_entry_review_reason="manual test review",
    )
    db.add_position(
        conn,
        condition_id="meta",
        signal_id=signal_id,
        opened_at="2026-05-19T01:00:00+00:00",
        intended_side="YES",
        intended_entry_price=0.41,
        intended_stake_usd=10.0,
        stake_source="paper",
        status="open",
        thesis_snapshot_text="Local election polling thesis.",
        primary_archetype="election_local_asymmetry",
        signal_generation_epoch="gated_v2_after_MR",
        confidence_source="operator_override",
        approval_strength="A",
        post_entry_review_required=1,
        post_entry_review_reason="manual test review",
        end_date="2026-08-01T00:00:00Z",
    )
    conn.commit()

    row = research_ledger_rows(conn)[0]

    assert row["signal_generation_epoch"] == "gated_v2_after_MR"
    assert row["edge_archetype"] == "local_polling"
    assert row["confidence_source"] == "operator_override"
    assert row["approval_strength"] == "A"
    assert row["post_entry_review_required"] is True
    assert row["post_entry_review_reason"] == "manual test review"
