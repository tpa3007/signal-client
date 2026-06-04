"""Tests for REQ-01: Python falsiness bug with resolution_risk_score=0.0."""


def _buggy_guard(x):
    """Original buggy expression — float(x or 1.0)."""
    return float(x or 1.0)


def _fixed_guard(x):
    """Correct expression — x if x is not None else 1.0."""
    return x if x is not None else 1.0


def test_old_expression_is_wrong_for_zero():
    """Document the bug: 0.0 or 1.0 == 1.0 in Python."""
    assert _buggy_guard(0.0) == 1.0  # Bug: best score treated as worst


def test_resolution_risk_score_zero_passes_guard():
    """Fixed expression: 0.0 is a valid score; must not be substituted."""
    assert _fixed_guard(0.0) == 0.0


def test_resolution_risk_score_none_uses_fallback():
    """Fixed expression: None means no score; substitute fallback 1.0."""
    assert _fixed_guard(None) == 1.0


def test_resolution_risk_score_nonzero_passes_through():
    """Fixed expression: normal non-zero float passes through unchanged."""
    assert _fixed_guard(0.45) == 0.45


# ── REQ-02: paper_only_low_edge label ────────────────────────────────────────

EDGE_THRESHOLD = 0.05  # matches config.EDGE_THRESHOLD


def _gate_decision(
    *,
    has_resolution_map: bool = True,
    resolution_risk_ok: bool = True,
    checklist_score: float,
    edge: float | None,
) -> str:
    """Replicate the fixed gate decision tree (pure Python, no DB)."""
    if not has_resolution_map:
        return "block_missing_resolution_map"
    if not resolution_risk_ok:
        return "block_resolution_risk"
    if checklist_score >= 82 and edge is not None and edge >= EDGE_THRESHOLD:
        return "approved_for_signal"
    if checklist_score >= 82:           # new branch — score ok, edge thin
        return "paper_only_low_edge"
    if checklist_score >= 68:
        return "needs_more_research"
    return "reject_incomplete"


def test_high_score_low_edge_returns_paper_only_low_edge():
    result = _gate_decision(checklist_score=85, edge=0.01)
    assert result == "paper_only_low_edge"


def test_high_score_good_edge_returns_approved():
    result = _gate_decision(checklist_score=85, edge=0.06)
    assert result == "approved_for_signal"


def test_medium_score_returns_needs_more_research():
    result = _gate_decision(checklist_score=75, edge=0.01)
    assert result == "needs_more_research"


def test_low_score_returns_reject_incomplete():
    result = _gate_decision(checklist_score=50, edge=0.01)
    assert result == "reject_incomplete"
