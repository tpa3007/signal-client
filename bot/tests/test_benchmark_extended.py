"""Stage 7: extended benchmark with gate-decision check and negative cases."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import db
import mcp_server  # ensures all tools register


def _seed_market(c, cid: str, vertical: str = "us_politics"):
    now = datetime.now(timezone.utc).isoformat()
    c.execute("""INSERT INTO markets (condition_id, question, slug, end_date,
                  first_seen_at, last_seen_at, vertical)
                  VALUES (?, 'q', 's', '2026-08-01', ?, ?, ?)""",
              (cid, now, now, vertical))


def _seed_snapshot(c, cid: str, yes_price: float, spread: float = 0.02):
    now = datetime.now(timezone.utc).isoformat()
    c.execute("""INSERT INTO snapshots (condition_id, captured_at, yes_price,
                  no_price, yes_entry_price, no_entry_price, spread)
                  VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (cid, now, yes_price, 1 - yes_price, yes_price, 1 - yes_price, spread))


def _call(_tool_name, **kw):
    t = mcp_server.mcp._tool_manager._tools[_tool_name]
    fn = getattr(t, "fn", None)
    return fn(**kw)


def test_create_benchmark_case_accepts_case_kind_and_gate(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xtest1")
        _seed_snapshot(c, "0xtest1", 0.50)
        c.commit()
    res = _call("create_signal_benchmark_case",
        name="test positive case",
        condition_id="0xtest1",
        expected_primary_archetype="cheap_optionality",
        expected_min_quality_score=70.0,
        expected_min_mtm_roi=0.30,
        reference_side="YES",
        reference_entry_price=0.10,
        reference_probability_yes=0.20,
        reference_confidence=0.60,
        case_kind="positive",
        expected_gate_decision="fire",
    )
    assert res.get("ok") is True


def test_invalid_case_kind_rejected(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xtest2")
        c.commit()
    res = _call("create_signal_benchmark_case",
        name="bad",
        condition_id="0xtest2",
        expected_primary_archetype="cheap_optionality",
        expected_min_quality_score=50.0,
        expected_min_mtm_roi=0.0,
        case_kind="not_a_kind",
    )
    assert "error" in res


def test_invalid_gate_decision_rejected(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xtest3")
        c.commit()
    res = _call("create_signal_benchmark_case",
        name="bad gate",
        condition_id="0xtest3",
        expected_primary_archetype="cheap_optionality",
        expected_min_quality_score=50.0,
        expected_min_mtm_roi=0.0,
        expected_gate_decision="block_imaginary",
    )
    assert "error" in res


def test_negative_case_skips_archetype_review_check(tmp_db):
    """Negative cases shouldn't fail just because they lack signal_archetype_review."""
    with db.connect() as c:
        _seed_market(c, "0xtestneg")
        _seed_snapshot(c, "0xtestneg", 0.20, spread=0.02)
        c.commit()
    _call("create_signal_benchmark_case",
        name="negative test case",
        condition_id="0xtestneg",
        expected_primary_archetype="resolution_wording_trap",
        expected_min_quality_score=0.0,
        expected_min_mtm_roi=-0.60,
        expected_moved_toward=False,
        reference_side="NO",
        reference_entry_price=0.20,
        reference_probability_yes=0.70,
        reference_confidence=0.40,  # below MIN_CONFIDENCE=0.50
        case_kind="negative",
        expected_gate_decision="block_confidence",
    )
    res = _call("signal_regression_benchmark", active_only=True)
    # Find our case
    case = next(c for c in res["cases"] if c["name"] == "negative test case")
    # Should not have 'missing_signal_archetype_review' failure
    assert "missing_signal_archetype_review" not in case["failures"]


def test_gate_decision_matches_when_inputs_complete(tmp_db):
    """A reference signal with low confidence should produce block_confidence."""
    with db.connect() as c:
        _seed_market(c, "0xtestgate")
        _seed_snapshot(c, "0xtestgate", 0.40, spread=0.02)
        c.commit()
    _call("create_signal_benchmark_case",
        name="gate test",
        condition_id="0xtestgate",
        expected_primary_archetype="cheap_optionality",
        expected_min_quality_score=0.0,
        expected_min_mtm_roi=-0.50,
        expected_moved_toward=False,
        reference_side="YES",
        reference_entry_price=0.40,
        reference_probability_yes=0.60,
        reference_confidence=0.30,  # WAY below MIN_CONFIDENCE
        case_kind="negative",
        expected_gate_decision="block_confidence",
    )
    res = _call("signal_regression_benchmark")
    case = next(c for c in res["cases"] if c["name"] == "gate test")
    assert case["actual_gate_decision"] == "block_confidence"
    # Should not have gate_decision_mismatch failure
    assert not any("gate_decision_mismatch" in f for f in case["failures"])


def test_gate_uses_reference_spread_not_latest_snapshot(tmp_db):
    """Stored reference_spread keeps benchmarks stable as new snapshots arrive."""
    with db.connect() as c:
        _seed_market(c, "0xtestspread")
        _seed_snapshot(c, "0xtestspread", 0.40, spread=0.20)  # would block if used
        c.commit()
    _call("create_signal_benchmark_case",
        name="reference spread stability",
        condition_id="0xtestspread",
        expected_primary_archetype="cheap_optionality",
        expected_min_quality_score=0.0,
        expected_min_mtm_roi=-0.50,
        reference_side="YES",
        reference_entry_price=0.40,
        reference_probability_yes=0.50,
        reference_confidence=0.60,
        reference_spread=0.02,
        case_kind="negative",
        expected_gate_decision="fire",
    )
    res = _call("signal_regression_benchmark")
    case = next(c for c in res["cases"] if c["name"] == "reference spread stability")
    assert case["actual_gate_decision"] == "fire"
    assert case["reference_spread"] == 0.02


def test_gate_decision_can_block_stale_snapshot(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xteststale")
        _seed_snapshot(c, "0xteststale", 0.40, spread=0.02)
        c.commit()
    _call("create_signal_benchmark_case",
        name="stale snapshot gate",
        condition_id="0xteststale",
        expected_primary_archetype="cheap_optionality",
        expected_min_quality_score=0.0,
        expected_min_mtm_roi=-0.50,
        reference_side="YES",
        reference_entry_price=0.40,
        reference_probability_yes=0.50,
        reference_confidence=0.60,
        reference_spread=0.02,
        reference_snapshot_age_min=999.0,
        case_kind="negative",
        expected_gate_decision="block_snapshot_stale",
    )
    res = _call("signal_regression_benchmark")
    case = next(c for c in res["cases"] if c["name"] == "stale snapshot gate")
    assert case["actual_gate_decision"] == "block_snapshot_stale"
    assert not any("gate_decision_mismatch" in f for f in case["failures"])
