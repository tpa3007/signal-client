from __future__ import annotations

import db
import mcp_server  # noqa: F401
from lib.gates import validate_signal_gate as _validate_signal_gate
from lib.ledger import research_ledger_rows


def _call_tool(name: str, **kwargs):
    tool = mcp_server.mcp._tool_manager._tools[name]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or getattr(tool, "callback", None)
    assert fn is not None, f"could not locate underlying fn on {tool!r}"
    return fn(**kwargs)


def _seed_market(conn, cid: str = "0xintegrity", yes_price: float = 0.42):
    db.upsert_market(
        conn,
        condition_id=cid,
        question=f"Will integrity market {cid} resolve YES?",
        slug=f"integrity-{cid}",
        end_date="2026-09-01T00:00:00Z",
        vertical="geopolitics",
    )
    db.add_snapshot(
        conn,
        condition_id=cid,
        yes_price=yes_price,
        no_price=1.0 - yes_price,
        best_bid=yes_price - 0.01,
        best_ask=yes_price + 0.01,
        spread=0.02,
        yes_entry_price=yes_price,
        no_entry_price=1.0 - yes_price + 0.02,
        volume=100_000,
        liquidity=50_000,
        source="test",
    )


def _seed_prebet(conn, cid: str, decision: str = "approved_for_signal"):
    db.add_pre_bet_checklist(
        conn,
        condition_id=cid,
        created_at=None,
        analyst="test",
        intended_side="YES",
        intended_entry_price=0.42,
        estimated_probability=0.62,
        confidence=0.70,
        edge=0.20,
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
        thesis="Approved test thesis.",
        top_risks="Test risks.",
        disconfirming_evidence="Test disconfirmation.",
        checklist_score=95.0,
        decision=decision,
        next_action="aladdin_signal_commit",
    )


def _seed_full_dossier(conn, cid: str):
    db.add_resolution_map(
        conn,
        condition_id=cid,
        created_at=None,
        analyst="test",
        yes_criteria="YES if official source confirms the event.",
        no_criteria="NO otherwise.",
        primary_resolution_source="Official source",
        secondary_resolution_sources="[]",
        deadline_text="By deadline.",
        ambiguity_cases="None.",
        non_qualifying_events="Rumors.",
        required_artifact="Official artifact.",
        resolution_risk_score=0.1,
        wording_trap_score=0.1,
        source_quality_score=0.9,
        deadline_clarity_score=0.9,
        completeness_score=95.0,
        parser_warnings_json="[]",
        parser_ambiguity_score=0.05,
        parser_suggestion="clear",
        summary="Resolution is clear.",
    )
    for i in range(2):
        db.add_evidence(
            conn,
            condition_id=cid,
            created_at=None,
            source_url=f"https://example.com/integrity-{i}",
            source_name=f"Source {i}",
            published_at="2026-05-19T00:00:00+00:00",
            claim=f"Evidence claim {i}",
            stance="YES" if i == 0 else "MIXED",
            strength=0.75,
            reliability=0.8,
            freshness=0.8,
            notes="Test evidence.",
        )
    db.add_actor_map(
        conn,
        condition_id=cid,
        created_at=None,
        actor_name="Actor",
        actor_type="institution",
        role="Influences outcome.",
        incentives="Has incentive.",
        constraints="Has constraints.",
        likely_action="Likely action.",
        influence_score=0.7,
        visibility_score=0.7,
        notes="Actor map.",
    )
    for i in range(2):
        db.add_causal_factor(
            conn,
            condition_id=cid,
            created_at=None,
            factor_name=f"Factor {i}",
            mechanism="Moves probability.",
            direction="YES" if i == 0 else "NO",
            importance=0.7,
            uncertainty=0.3,
            observable_signal="Observable signal.",
            current_state="Active.",
            next_check_at=None,
        )
    for i, probability in enumerate([0.45, 0.35, 0.20]):
        db.add_scenario(
            conn,
            condition_id=cid,
            created_at=None,
            scenario_name=f"Scenario {i}",
            path="Plausible path.",
            probability=probability,
            outcome_side="YES" if i < 2 else "NO",
            key_assumptions="Assumptions.",
            breakpoints="Breakpoints.",
            early_warning_signals="Warnings.",
        )
    db.add_premortem(
        conn,
        condition_id=cid,
        created_at=None,
        thesis="Mispricing thesis.",
        failure_mode="Evidence fails.",
        disconfirming_signal="Source reversal.",
        probability_if_wrong=0.35,
        mitigation="Downgrade.",
        severity=0.7,
    )


def test_validate_signal_gate_blocks_incomplete_dossier(tmp_db):
    cid = "0xgate_missing"
    with db.connect() as conn:
        _seed_market(conn, cid)
        _seed_prebet(conn, cid)
        conn.commit()
        gate = _validate_signal_gate(conn, condition_id=cid, probability_yes=0.62, confidence=0.70)

    assert gate["ok"] is False
    assert "resolution_maps_below_required_1" in gate["blockers"]
    assert "source_depth_below_required_2" in gate["blockers"]


def test_aladdin_signal_commit_creates_formal_paper_position_after_gate(tmp_db):
    cid = "0xgate_commit"
    with db.connect() as conn:
        _seed_market(conn, cid)
        _seed_prebet(conn, cid)
        _seed_full_dossier(conn, cid)
        conn.commit()

    out = _call_tool(
        "aladdin_signal_commit",
        condition_id=cid,
        side="YES",
        probability_yes=0.62,
        confidence=0.70,
        reasoning="Formal commit from approved test dossier.",
        sources=["https://example.com/integrity-0"],
    )

    assert out["signal_created"] is True, out
    assert out["gate_passed"] is True
    assert out["paper_only"] is True
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM signals WHERE condition_id=?", (cid,)).fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM positions WHERE condition_id=?", (cid,)).fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM fills").fetchone()["n"] == 1


def test_record_real_manual_trade_is_legal_retrospective_path(tmp_db):
    cid = "0xmanual_trade"
    out = _call_tool(
        "record_real_manual_trade",
        condition_id=cid,
        question="Will manual trade resolve YES?",
        slug="manual-trade",
        end_date="2026-09-01T00:00:00Z",
        side="YES",
        entry_price=0.29,
        stake_usd=35.0,
        thesis="Operator entered this real-money position manually.",
        sources=["https://example.com/manual"],
        probability_yes=0.54,
        confidence=0.56,
    )

    assert out["recorded"] is True, out
    assert out["manual_trade"] is True
    with db.connect() as conn:
        signal = conn.execute("SELECT manual_trade, retrospective, operator_decision FROM signals WHERE id=?", (out["signal_id"],)).fetchone()
        assert signal["manual_trade"] == 1
        assert signal["retrospective"] == 1
        assert signal["operator_decision"] == "manual_real_trade"
        row = research_ledger_rows(conn, include_discovered=False)[0]
        assert row["manual_trade"] is True
        assert row["gate_violation"] is False
        assert row["status"] == "open_position"
