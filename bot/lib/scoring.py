"""Pure scoring functions. No I/O, no DB. Easy to unit-test."""
from __future__ import annotations

import math
from datetime import datetime

from lib.execution import clamp01


def hidden_gem_score(
    executable_edge: float,
    liquidity_score: float,
    spread_score: float,
    attention_gap_score: float,
    evidence_asymmetry_score: float,
    stale_price_score: float,
    catalyst_score: float,
    resolution_clarity_score: float,
) -> float:
    """Weighted 0-100 score rewarding neglected, researchable markets — not just edge."""
    edge_score = clamp01(executable_edge / 0.20)
    weighted = (
        0.22 * edge_score
        + 0.14 * liquidity_score
        + 0.10 * spread_score
        + 0.14 * attention_gap_score
        + 0.16 * evidence_asymmetry_score
        + 0.10 * stale_price_score
        + 0.08 * catalyst_score
        + 0.06 * resolution_clarity_score
    )
    return round(100.0 * weighted, 2)


def moonshot_score(
    *,
    probability_edge: float | None,
    payout_multiple: float,
    catalyst_score: float,
    mechanism_score: float,
    evidence_score: float,
    resolution_score: float,
    liquidity_score: float,
    spread_score: float,
    narrative_heat_score: float,
    anti_random_score: float,
) -> float:
    edge_score = 0.35 if probability_edge is None else clamp01(probability_edge / 0.18)
    payout_score = clamp01((payout_multiple - 3.0) / 17.0)
    weighted = (
        0.18 * edge_score
        + 0.12 * payout_score
        + 0.14 * catalyst_score
        + 0.15 * mechanism_score
        + 0.11 * evidence_score
        + 0.10 * resolution_score
        + 0.07 * liquidity_score
        + 0.05 * spread_score
        + 0.04 * narrative_heat_score
        + 0.04 * anti_random_score
    )
    return round(100.0 * weighted, 2)


def resolution_completeness(
    *,
    yes_criteria: str,
    no_criteria: str,
    primary_resolution_source: str,
    deadline_text: str,
    ambiguity_cases: str,
    non_qualifying_events: str,
    required_artifact: str,
    source_quality_score: float,
    deadline_clarity_score: float,
) -> float:
    checks = [
        bool(yes_criteria.strip()),
        bool(no_criteria.strip()),
        bool(primary_resolution_source.strip()),
        bool(deadline_text.strip()),
        bool(ambiguity_cases.strip()),
        bool(non_qualifying_events.strip()),
        bool(required_artifact.strip()),
    ]
    base = sum(checks) / len(checks)
    quality = (source_quality_score + deadline_clarity_score) / 2.0
    return round((0.75 * base + 0.25 * quality) * 100, 2)


def normalize_score_100(value: float | int | str | None) -> float:
    """Normalize scores stored either as 0..1 ratios or 0..100 percentages."""
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= numeric <= 1.0:
        return numeric * 100.0
    return numeric


def score_dossier_completeness(flags: dict[str, bool]) -> float:
    """0-100: how complete is the research dossier.

    Measures structural coverage only — whether the required sections exist.
    Does NOT reflect quality of evidence or confidence in the forecast.
    """
    dossier_flags = {
        "has_resolution_map": 0.24,
        "has_evidence_base": 0.20,
        "has_actor_map": 0.16,
        "has_causal_model": 0.18,
        "has_scenario_tree": 0.14,
        "has_premortem": 0.08,
    }
    score = sum(w for k, w in dossier_flags.items() if flags.get(k, False))
    return round(clamp01(score) * 100, 2)


def score_source_quality(source_quality_raw: float) -> float:
    """0-100: how credible/relevant are the sources backing the dossier.

    Accepts a pre-computed source_quality score (0.0-1.0) from Signal's
    resolution map or evidence review.
    """
    return round(clamp01(source_quality_raw) * 100, 2)


def score_forecast_confidence(
    confidence: float,
    edge: float | None,
    *,
    disconfirming_checked: bool = False,
    contradictions_resolved: bool = False,
) -> float:
    """0-100: epistemic confidence in the thesis.

    This is distinct from dossier completeness — a full dossier can have
    low forecast confidence if evidence is thin or contradictions are unresolved.

    disconfirming_checked: was an active search for kill criteria done?
    contradictions_resolved: were major contradictions addressed?
    """
    base = clamp01(confidence)
    edge_bonus = 0.0 if edge is None else 0.08 * clamp01(max(0.0, edge) / 0.12)
    disconf_bonus = 0.06 if disconfirming_checked else 0.0
    contradiction_bonus = 0.06 if contradictions_resolved else 0.0
    return round(clamp01(base * 0.80 + edge_bonus + disconf_bonus + contradiction_bonus) * 100, 2)


def score_signal_readiness(flags: dict[str, bool]) -> float:
    """0-100: market mechanics readiness for a bet.

    Covers spread, liquidity, sizing, and resolution risk — the execution
    preconditions. A high score here does not mean the thesis is right.
    """
    readiness_flags = {
        "evidence_balance_ok": 0.25,
        "spread_ok": 0.25,
        "liquidity_ok": 0.25,
        "sizing_ok": 0.15,
        "resolution_risk_ok": 0.10,
    }
    score = sum(w for k, w in readiness_flags.items() if flags.get(k, False))
    return round(clamp01(score) * 100, 2)


def pre_bet_score(flags: dict[str, bool], confidence: float, edge: float | None) -> float:
    """Composite 0-100 pre-bet score.

    Weighted combination of the four sub-scores. Prefer reading the sub-scores
    directly to understand *why* a market is or isn't ready — the composite
    can look high even when forecast_confidence is low (full dossier, thin evidence).
    """
    dossier = score_dossier_completeness(flags) / 100.0
    readiness = score_signal_readiness(flags) / 100.0
    confidence_score = score_forecast_confidence(confidence, edge) / 100.0
    # source_quality not available here without raw score; use confidence as proxy
    composite = dossier * 0.35 + readiness * 0.30 + confidence_score * 0.35
    return round(clamp01(composite) * 100, 2)


def signal_quality_score(
    *,
    thesis_quality_score: float,
    entry_quality_score: float,
    catalyst_quality_score: float,
    resolution_quality_score: float,
    timing_quality_score: float,
    risk_quality_score: float,
    moved_toward_thesis: bool,
    mark_to_market_roi: float | None,
) -> float:
    weighted = (
        thesis_quality_score * 0.22
        + entry_quality_score * 0.24
        + catalyst_quality_score * 0.17
        + resolution_quality_score * 0.13
        + timing_quality_score * 0.16
        + risk_quality_score * 0.08
    )
    if moved_toward_thesis:
        weighted += 0.05
    elif mark_to_market_roi is not None and mark_to_market_roi < -0.2:
        weighted -= 0.05
    return round(clamp01(weighted) * 100, 2)


def log_score(probability: float, outcome: float) -> float:
    p = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    y = float(outcome)
    return -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))


def quality_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 75:
        return "A-"
    if score >= 67:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
