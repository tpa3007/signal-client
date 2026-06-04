"""Scoring functions — pure, deterministic, no DB."""
from __future__ import annotations

import math

import pytest

from lib.scoring import (
    hidden_gem_score,
    log_score,
    moonshot_score,
    normalize_score_100,
    pre_bet_score,
    quality_grade,
    resolution_completeness,
    score_dossier_completeness,
    score_forecast_confidence,
    score_signal_readiness,
    signal_quality_score,
)


def test_hidden_gem_score_zero_inputs_returns_zero():
    s = hidden_gem_score(
        executable_edge=0.0,
        liquidity_score=0.0, spread_score=0.0, attention_gap_score=0.0,
        evidence_asymmetry_score=0.0, stale_price_score=0.0,
        catalyst_score=0.0, resolution_clarity_score=0.0,
    )
    assert s == 0.0


def test_hidden_gem_score_perfect_inputs_returns_one_hundred():
    s = hidden_gem_score(
        executable_edge=0.20,  # normalised by /0.20 → 1.0
        liquidity_score=1.0, spread_score=1.0, attention_gap_score=1.0,
        evidence_asymmetry_score=1.0, stale_price_score=1.0,
        catalyst_score=1.0, resolution_clarity_score=1.0,
    )
    assert s == 100.0


def test_hidden_gem_score_known_mix():
    # Quality dossier with only modest edge
    s = hidden_gem_score(
        executable_edge=0.10,           # edge_score = 0.5
        liquidity_score=0.8, spread_score=0.6, attention_gap_score=0.7,
        evidence_asymmetry_score=0.7, stale_price_score=0.5,
        catalyst_score=0.6, resolution_clarity_score=0.7,
    )
    # Hand-computed: 0.22*0.5 + 0.14*0.8 + 0.10*0.6 + 0.14*0.7 + 0.16*0.7 + 0.10*0.5 + 0.08*0.6 + 0.06*0.7
    expected = 100.0 * (0.11 + 0.112 + 0.06 + 0.098 + 0.112 + 0.05 + 0.048 + 0.042)
    assert s == pytest.approx(expected, abs=0.01)


def test_moonshot_score_handles_unknown_edge():
    # When probability_edge=None, the function uses a 0.35 default for edge_score
    s = moonshot_score(
        probability_edge=None, payout_multiple=10.0,
        catalyst_score=0.6, mechanism_score=0.6, evidence_score=0.5,
        resolution_score=0.5, liquidity_score=0.5, spread_score=0.5,
        narrative_heat_score=0.5, anti_random_score=0.5,
    )
    assert 0 < s < 100


def test_moonshot_score_rewards_high_payout():
    low = moonshot_score(
        probability_edge=0.05, payout_multiple=4.0,
        catalyst_score=0.5, mechanism_score=0.5, evidence_score=0.5,
        resolution_score=0.5, liquidity_score=0.5, spread_score=0.5,
        narrative_heat_score=0.5, anti_random_score=0.5,
    )
    high = moonshot_score(
        probability_edge=0.05, payout_multiple=15.0,
        catalyst_score=0.5, mechanism_score=0.5, evidence_score=0.5,
        resolution_score=0.5, liquidity_score=0.5, spread_score=0.5,
        narrative_heat_score=0.5, anti_random_score=0.5,
    )
    assert high > low


def test_resolution_completeness_full_dossier():
    s = resolution_completeness(
        yes_criteria="X", no_criteria="Y",
        primary_resolution_source="src",
        deadline_text="2026-06-01",
        ambiguity_cases="case",
        non_qualifying_events="event",
        required_artifact="artefact",
        source_quality_score=1.0,
        deadline_clarity_score=1.0,
    )
    assert s == 100.0


def test_resolution_completeness_empty_dossier():
    s = resolution_completeness(
        yes_criteria="", no_criteria="",
        primary_resolution_source="",
        deadline_text="", ambiguity_cases="",
        non_qualifying_events="", required_artifact="",
        source_quality_score=0.0,
        deadline_clarity_score=0.0,
    )
    assert s == 0.0


def test_normalize_score_100_accepts_ratio_and_percent_scales():
    assert normalize_score_100(0.70) == pytest.approx(70.0)
    assert normalize_score_100(70) == pytest.approx(70.0)
    assert normalize_score_100(None) == 0.0
    assert normalize_score_100("bad") == 0.0


def test_pre_bet_score_all_flags_true_with_high_confidence():
    flags = {
        "has_resolution_map": True, "has_evidence_base": True, "has_actor_map": True,
        "has_causal_model": True, "has_scenario_tree": True, "has_premortem": True,
        "evidence_balance_ok": True, "spread_ok": True, "liquidity_ok": True,
        "sizing_ok": True, "resolution_risk_ok": True,
    }
    s = pre_bet_score(flags, confidence=1.0, edge=0.12)
    # Composite deliberately does not reach 100 without disconfirming_checked=True,
    # reflecting that a full dossier ≠ full epistemic confidence.
    assert s >= 90.0
    assert s < 100.0


def test_checklist_v2_sub_scores():
    all_flags = {
        "has_resolution_map": True, "has_evidence_base": True, "has_actor_map": True,
        "has_causal_model": True, "has_scenario_tree": True, "has_premortem": True,
        "evidence_balance_ok": True, "spread_ok": True, "liquidity_ok": True,
        "sizing_ok": True, "resolution_risk_ok": True,
    }
    # Full dossier → 100 completeness
    assert score_dossier_completeness(all_flags) == 100.0
    # No dossier flags → 0 completeness
    assert score_dossier_completeness({k: False for k in all_flags}) == 0.0
    # Full readiness flags → 100 readiness
    assert score_signal_readiness(all_flags) == 100.0
    # Confidence + edge but no disconfirming → high but not 100
    fc = score_forecast_confidence(1.0, 0.12)
    assert fc < 100.0
    # With disconfirming checked → higher
    fc_with_dc = score_forecast_confidence(1.0, 0.12, disconfirming_checked=True, contradictions_resolved=True)
    assert fc_with_dc > fc
    # Separation: completeness and readiness are independent
    partial_dossier = {k: (k in ("has_resolution_map", "has_evidence_base")) for k in all_flags}
    assert score_dossier_completeness(partial_dossier) < 50.0
    assert score_signal_readiness(partial_dossier) == 0.0  # no readiness flags set


def test_pre_bet_score_no_flags_no_bonus():
    flags = {k: False for k in (
        "has_resolution_map", "has_evidence_base", "has_actor_map",
        "has_causal_model", "has_scenario_tree", "has_premortem",
        "evidence_balance_ok", "spread_ok", "liquidity_ok",
        "sizing_ok", "resolution_risk_ok",
    )}
    assert pre_bet_score(flags, confidence=0.0, edge=None) == 0.0


def test_signal_quality_score_thesis_moved_bonus():
    base = dict(
        thesis_quality_score=0.7, entry_quality_score=0.7,
        catalyst_quality_score=0.7, resolution_quality_score=0.7,
        timing_quality_score=0.7, risk_quality_score=0.7,
        mark_to_market_roi=0.10,
    )
    no_move = signal_quality_score(moved_toward_thesis=False, **base)
    moved = signal_quality_score(moved_toward_thesis=True, **base)
    assert moved == pytest.approx(no_move + 5.0, abs=0.01)


def test_signal_quality_score_heavy_loss_penalty():
    base = dict(
        thesis_quality_score=0.7, entry_quality_score=0.7,
        catalyst_quality_score=0.7, resolution_quality_score=0.7,
        timing_quality_score=0.7, risk_quality_score=0.7,
    )
    flat = signal_quality_score(moved_toward_thesis=False, mark_to_market_roi=0.0, **base)
    crash = signal_quality_score(moved_toward_thesis=False, mark_to_market_roi=-0.5, **base)
    assert crash == pytest.approx(flat - 5.0, abs=0.01)


def test_log_score_calibrated_forecast():
    # log score with perfect calibration on YES outcome
    assert log_score(0.9, 1.0) < log_score(0.5, 1.0) < log_score(0.1, 1.0)


def test_log_score_clipped_at_extremes():
    # log_score(0, 1) must not blow up — clipped to 1e-6
    val = log_score(0.0, 1.0)
    assert math.isfinite(val) and val > 10


def test_quality_grade_boundaries():
    assert quality_grade(90) == "A"
    assert quality_grade(85) == "A"
    assert quality_grade(80) == "A-"
    assert quality_grade(70) == "B+"
    assert quality_grade(60) == "B"
    assert quality_grade(50) == "C"
    assert quality_grade(40) == "D"
