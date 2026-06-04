"""End-to-end check that record_analysis honours new Stage 0 gates:

  - snapshot must be <= MAX_SNAPSHOT_AGE_MIN minutes old;
  - signal emits only when ALL gates pass and pre-bet checklist approves;
  - the analysis row is recorded EVERY time (no-signal decisions logged too).
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import config
import db
import mcp_server  # noqa: F401  - ensures tool modules import and DB schema migrations run


def _insert_market_and_snapshot(conn, condition_id: str, *, age_minutes: float = 0.0,
                                yes_price: float = 0.40,
                                yes_entry: float = 0.42, no_entry: float = 0.58,
                                spread: float = 0.04):
    """Manually seed a market + a snapshot with controllable age."""
    now = datetime.now(timezone.utc)
    captured = (now - timedelta(minutes=age_minutes)).isoformat()
    conn.execute("""
        INSERT INTO markets (condition_id, question, slug, end_date,
                             first_seen_at, last_seen_at, vertical)
        VALUES (?, ?, ?, ?, ?, ?, 'geopolitics')
    """, (condition_id, "test question", "test-slug", "2026-09-01T00:00:00Z",
          now.isoformat(), now.isoformat()))
    conn.execute("""
        INSERT INTO snapshots (condition_id, captured_at, yes_price, no_price,
                               best_bid, best_ask, spread,
                               yes_entry_price, no_entry_price,
                               volume, liquidity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (condition_id, captured, yes_price, 1 - yes_price,
          yes_price - spread/2, yes_price + spread/2, spread,
          yes_entry, no_entry, 100000.0, 50000.0))
    conn.commit()


def _insert_pre_bet_checklist(conn, condition_id: str,
                              decision: str = "approved_for_signal"):
    conn.execute("""
        INSERT INTO pre_bet_checklists (
            condition_id, created_at, analyst, intended_side,
            intended_entry_price, estimated_probability, confidence, edge,
            has_resolution_map, has_evidence_base, has_actor_map,
            has_causal_model, has_scenario_tree, has_premortem,
            has_moonshot_review, evidence_balance_ok, spread_ok,
            liquidity_ok, sizing_ok, resolution_risk_ok, thesis,
            top_risks, disconfirming_evidence, checklist_score,
            decision, next_action
        ) VALUES (?, ?, 'test', 'YES', 0.42, 0.60, 0.70, 0.18,
                  1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1,
                  'approved test thesis', 'test risk', 'test disconfirming evidence',
                  90.0, ?, NULL)
    """, (condition_id, db.utcnow_iso(), decision))
    conn.commit()



def _insert_full_dossier(conn, condition_id: str):
    db.add_resolution_map(
        conn,
        condition_id=condition_id,
        created_at=None,
        analyst="test",
        yes_criteria="YES resolves if the tested event happens.",
        no_criteria="NO resolves otherwise.",
        primary_resolution_source="Official source",
        secondary_resolution_sources="[]",
        deadline_text="By the listed market deadline.",
        ambiguity_cases="None material for this test.",
        non_qualifying_events="Non-official rumors do not qualify.",
        required_artifact="Official result page.",
        resolution_risk_score=0.1,
        wording_trap_score=0.1,
        source_quality_score=0.9,
        deadline_clarity_score=0.9,
        completeness_score=95.0,
        parser_warnings_json="[]",
        parser_ambiguity_score=0.05,
        parser_suggestion="clear",
        summary="Test resolution map.",
    )
    for i in range(2):
        db.add_evidence(
            conn,
            condition_id=condition_id,
            created_at=None,
            source_url=f"https://example.com/source-{i}",
            source_name=f"Source {i}",
            published_at="2026-05-19T00:00:00+00:00",
            claim=f"Evidence claim {i}",
            stance="YES" if i == 0 else "MIXED",
            strength=0.7,
            reliability=0.8,
            freshness=0.8,
            notes="Test evidence.",
        )
    db.add_actor_map(
        conn,
        condition_id=condition_id,
        created_at=None,
        actor_name="Test actor",
        actor_type="institution",
        role="Can influence the outcome.",
        incentives="Wants the event to happen.",
        constraints="Faces public constraints.",
        likely_action="Continue current path.",
        influence_score=0.7,
        visibility_score=0.7,
        notes="Test actor map.",
    )
    for i in range(2):
        db.add_causal_factor(
            conn,
            condition_id=condition_id,
            created_at=None,
            factor_name=f"Factor {i}",
            mechanism="Moves probability through observable public actions.",
            direction="YES" if i == 0 else "NO",
            importance=0.7,
            uncertainty=0.3,
            observable_signal="Fresh public source.",
            current_state="Active.",
            next_check_at=None,
        )
    for i, prob in enumerate([0.45, 0.35, 0.20]):
        db.add_scenario(
            conn,
            condition_id=condition_id,
            created_at=None,
            scenario_name=f"Scenario {i}",
            path="A plausible path to this outcome.",
            probability=prob,
            outcome_side="YES" if i < 2 else "NO",
            key_assumptions="Test assumptions.",
            breakpoints="Test breakpoint.",
            early_warning_signals="Test warning.",
        )
    db.add_premortem(
        conn,
        condition_id=condition_id,
        created_at=None,
        thesis="The market is mispriced.",
        failure_mode="The public evidence was misleading.",
        disconfirming_signal="Official data turns against the thesis.",
        probability_if_wrong=0.35,
        mitigation="Cut or downgrade on disconfirmation.",
        severity=0.7,
    )
    conn.commit()

def _call_record_analysis(**kwargs):
    """The tool is registered as a closure inside tools.research.register(mcp).
    Easiest path: invoke via the FastMCP tool manager."""
    mgr = mcp_server.mcp._tool_manager
    tool = mgr._tools["record_analysis"]
    # FastMCP tools store the underlying callable on `.fn`
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or getattr(tool, "callback", None)
    assert fn is not None, f"could not locate underlying fn on {tool!r}"
    return fn(**kwargs)


def test_fresh_snapshot_passes_all_gates_and_emits_signal(tmp_db):
    cid = "0xtest_pass"
    with db.connect() as c:
        # Strong YES signal: prob=0.60, yes_entry=0.42 -> edge ~= 0.18; spread thin; conf high
        _insert_market_and_snapshot(c, cid, age_minutes=2.0,
                                    yes_price=0.42, yes_entry=0.42, no_entry=0.60, spread=0.02)
        _insert_pre_bet_checklist(c, cid)
        _insert_full_dossier(c, cid)
    out = _call_record_analysis(
        condition_id=cid,
        probability_yes=0.60,
        confidence=0.70,
        reasoning="strong evidence the market is mispricing the catalyst",
        sources=["https://example.com/source"],
    )
    assert out.get("signal_emitted") is True, out
    assert out["side"] == "YES"
    assert out["no_signal_reason"] is None
    assert out["bet_amount"] >= config.BET_MIN_USD


def test_dry_run_evaluates_signal_without_writing_rows(tmp_db):
    cid = "0xtest_dry_run"
    with db.connect() as c:
        _insert_market_and_snapshot(c, cid, age_minutes=2.0,
                                    yes_price=0.42, yes_entry=0.42, no_entry=0.60, spread=0.02)
        _insert_pre_bet_checklist(c, cid)
        _insert_full_dossier(c, cid)
    out = _call_record_analysis(
        condition_id=cid,
        probability_yes=0.60,
        confidence=0.70,
        reasoning="dry-run thesis",
        sources=[],
        dry_run=True,
    )
    assert out["signal_emitted"] is False
    assert out["would_emit_signal"] is True
    assert out["dry_run"] is True
    assert out["signal_id"] is None
    assert out["analysis_id"] is None
    assert out["sizing"] is not None
    with db.connect() as c:
        sigs = c.execute("SELECT COUNT(*) AS n FROM signals WHERE condition_id = ?", (cid,)).fetchone()["n"]
        analyses = c.execute("SELECT COUNT(*) AS n FROM analyses WHERE condition_id = ?", (cid,)).fetchone()["n"]
        positions = c.execute("SELECT COUNT(*) AS n FROM positions WHERE condition_id = ?", (cid,)).fetchone()["n"]
        assert sigs == 0
        assert analyses == 0
        assert positions == 0


def test_missing_pre_bet_checklist_blocks_signal_but_logs_analysis(tmp_db):
    cid = "0xtest_missing_checklist"
    with db.connect() as c:
        _insert_market_and_snapshot(c, cid, age_minutes=2.0,
                                    yes_price=0.42, yes_entry=0.42, no_entry=0.60, spread=0.02)
    out = _call_record_analysis(
        condition_id=cid,
        probability_yes=0.60,
        confidence=0.70,
        reasoning="strong evidence but no checklist approval yet",
        sources=[],
    )
    assert out["signal_emitted"] is False
    assert out["no_signal_reason"] == "missing_pre_bet_checklist"
    with db.connect() as c:
        sigs = c.execute("SELECT COUNT(*) AS n FROM signals WHERE condition_id = ?", (cid,)).fetchone()["n"]
        analyses = c.execute("SELECT COUNT(*) AS n FROM analyses WHERE condition_id = ?", (cid,)).fetchone()["n"]
        assert sigs == 0
        assert analyses == 1


def test_pre_bet_bypass_only_allowed_for_dry_run(tmp_db):
    cid = "0xtest_no_formal_bypass"
    with db.connect() as c:
        _insert_market_and_snapshot(c, cid, age_minutes=2.0,
                                    yes_price=0.42, yes_entry=0.42, no_entry=0.60, spread=0.02)
    out = _call_record_analysis(
        condition_id=cid,
        probability_yes=0.60,
        confidence=0.70,
        reasoning="attempted formal bypass",
        sources=[],
        require_pre_bet_approval=False,
    )
    assert out["signal_emitted"] is False
    assert out["no_signal_reason"] == "missing_pre_bet_checklist"
    with db.connect() as c:
        sigs = c.execute("SELECT COUNT(*) AS n FROM signals WHERE condition_id = ?", (cid,)).fetchone()["n"]
        assert sigs == 0


def test_stale_snapshot_is_rejected(tmp_db):
    cid = "0xtest_stale"
    with db.connect() as c:
        _insert_market_and_snapshot(c, cid, age_minutes=config.MAX_SNAPSHOT_AGE_MIN + 30)
    out = _call_record_analysis(
        condition_id=cid,
        probability_yes=0.60, confidence=0.70,
        reasoning="...", sources=[],
    )
    assert out.get("error") == "snapshot_stale_call_fetch_candidates"
    assert out["snapshot_age_min"] > config.MAX_SNAPSHOT_AGE_MIN


def test_low_confidence_logs_analysis_but_no_signal(tmp_db):
    cid = "0xtest_lowconf"
    with db.connect() as c:
        _insert_market_and_snapshot(c, cid, age_minutes=1.0,
                                    yes_price=0.42, yes_entry=0.42, no_entry=0.60, spread=0.02)
    out = _call_record_analysis(
        condition_id=cid,
        probability_yes=0.60,
        confidence=0.40,  # below MIN_CONFIDENCE=0.50
        reasoning="hunch only",
        sources=[],
    )
    assert out["signal_emitted"] is False
    assert out["no_signal_reason"] == "confidence_below_threshold"
    # ...but analysis row should still exist
    with db.connect() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM analyses WHERE condition_id = ?", (cid,)).fetchone()["n"]
        assert n == 1


def test_wide_spread_rejected_even_with_strong_thesis(tmp_db):
    cid = "0xtest_wide"
    with db.connect() as c:
        _insert_market_and_snapshot(c, cid, age_minutes=1.0,
                                    yes_price=0.42, yes_entry=0.45, no_entry=0.63,
                                    spread=0.10)  # > MAX_SPREAD=0.06
    out = _call_record_analysis(
        condition_id=cid,
        probability_yes=0.60, confidence=0.70,
        reasoning="thesis fine but illiquid",
        sources=[],
    )
    assert out["signal_emitted"] is False
    assert out["no_signal_reason"] == "spread_too_wide"


def test_missing_snapshot_returns_error(tmp_db):
    out = _call_record_analysis(
        condition_id="0xnonexistent",
        probability_yes=0.60, confidence=0.70,
        reasoning="...", sources=[],
    )
    assert "no snapshot" in out.get("error", "")
