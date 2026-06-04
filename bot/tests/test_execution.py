"""Gating and edge-side selection — the heart of record_analysis."""
from __future__ import annotations

import pytest

import config
from lib.execution import (
    best_executable_edge,
    clamp01,
    execution_prices,
    float_or_none,
    no_signal_reason,
)


# --- best_executable_edge: picks the better side ----------------------------

def test_edge_picks_yes_when_yes_is_better():
    side, edge = best_executable_edge(probability_yes=0.70, yes_entry_price=0.55, no_entry_price=0.40)
    assert side == "YES"
    assert edge == pytest.approx(0.15)


def test_edge_picks_no_when_no_is_better():
    side, edge = best_executable_edge(probability_yes=0.30, yes_entry_price=0.40, no_entry_price=0.55)
    assert side == "NO"
    assert edge == pytest.approx(0.15)


def test_edge_tie_breaks_yes():
    side, _ = best_executable_edge(probability_yes=0.50, yes_entry_price=0.45, no_entry_price=0.45)
    assert side == "YES"


# --- execution_prices: yes_entry uses ask, no_entry uses 1 - bid ------------

def test_execution_prices_uses_orderbook_when_present():
    yes, no, spread = execution_prices(
        yes_price=0.60, no_price=0.40, best_bid=0.58, best_ask=0.62, spread=None,
    )
    assert yes == 0.62  # buy YES at ask
    assert no == pytest.approx(0.42)  # buy NO ≈ 1 - YES bid
    assert spread == pytest.approx(0.04)


def test_execution_prices_falls_back_to_outcome_prices():
    yes, no, spread = execution_prices(0.60, 0.40, None, None, None)
    assert yes == 0.60
    assert no == 0.40
    assert spread is None


# --- no_signal_reason: gate ordering and Stage 0 tightened thresholds -------

def test_gates_pass_when_everything_is_solid():
    # edge=0.08, spread=0.04 (adj=0.06), conf=0.6 — all pass under Stage 0 gates
    assert no_signal_reason(edge=0.08, confidence=0.60, spread=0.04) is None


def test_gates_reject_edge_below_threshold():
    # default EDGE_THRESHOLD=0.06
    assert no_signal_reason(edge=0.05, confidence=0.60, spread=0.02) == "edge_below_threshold"


def test_gates_reject_wide_spread():
    # default MAX_SPREAD=0.06
    assert no_signal_reason(edge=0.10, confidence=0.60, spread=0.09) == "spread_too_wide"


def test_gates_reject_low_confidence():
    # default MIN_CONFIDENCE=0.50; old gate was 0.35 — this case used to pass
    assert no_signal_reason(edge=0.10, confidence=0.40, spread=0.02) == "confidence_below_threshold"


def test_gates_reject_negative_spread_adjusted_edge():
    # edge - spread/2 = 0.06 - 0.05 = 0.01 < MIN_SPREAD_ADJ_EDGE (0.04)
    assert no_signal_reason(edge=0.06, confidence=0.60, spread=0.10) == "spread_too_wide"


def test_gates_reject_thin_spread_adjusted_edge_with_acceptable_raw_spread():
    # raw spread inside MAX_SPREAD; but spread-adj edge fails
    # edge=0.06, spread=0.05, adj = 0.06 - 0.025 = 0.035 < 0.04
    assert no_signal_reason(edge=0.06, confidence=0.60, spread=0.05) == "spread_adjusted_edge_below_threshold"


def test_gates_handle_unknown_spread_as_zero_for_adjustment():
    # If spread is None we don't penalise; raw gates still apply
    assert no_signal_reason(edge=0.08, confidence=0.60, spread=None) is None


# --- helpers -----------------------------------------------------------------

def test_clamp01_bounds():
    assert clamp01(-0.5) == 0.0
    assert clamp01(1.5) == 1.0
    assert clamp01(0.3) == 0.3


def test_float_or_none_filters_invalid():
    assert float_or_none(None) is None
    assert float_or_none("") is None
    assert float_or_none("not_a_number") is None
    assert float_or_none(1.5) is None  # outside [0,1]
    assert float_or_none(-0.1) is None
    assert float_or_none(0.5) == 0.5


def test_stage0_thresholds_match_doctrine():
    """If anyone loosens Stage 0 gates accidentally, this test screams."""
    assert config.EDGE_THRESHOLD >= 0.05, "Stage 0 hardened gate; do not loosen below 0.05"
    assert config.MIN_CONFIDENCE >= 0.50, "Stage 0 hardened gate; do not loosen below 0.50"
    assert config.MIN_SPREAD_ADJ_EDGE >= 0.03
    assert config.MAX_SPREAD <= 0.08
