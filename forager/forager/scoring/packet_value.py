"""Packet-to-Signal value scoring.

This answers the question Signal actually cares about:
"How much should this Forager packet move my probability estimate?"

Weirdness and signal_relevance measure what the packet *is*.
signal_decision_value measures how *useful* it is for making a bet decision.

A packet with many weird sources but no kill-criteria coverage and no confirmed
disconfirming evidence is interesting but low-value for Signal. A packet with
one high-credibility source that directly addresses the resolution criteria is
high-value even if it has low weirdness.
"""
from __future__ import annotations

from forager.scoring.weirdness import clamp01


def score_packet_signal_value(
    *,
    hypothesis_count: int,
    avg_hypothesis_confidence: float,
    source_count: int,
    high_credibility_source_count: int,
    kill_criteria_covered: int,
    kill_criteria_total: int,
    disconfirming_found: bool,
    anomaly_count: int,
    signal_relevance: float,
) -> float:
    """Score how useful this packet is for a Signal bet decision (0.0–1.0).

    Factors (weighted):
    - Hypothesis coverage (40 %): do we have hypotheses with real confidence?
    - Source quality (25 %): ratio of high-credibility to total sources
    - Kill criteria coverage (20 %): what fraction of kill criteria were searched?
    - Disconfirming evidence (10 %): was a disconfirming source actually found?
    - Signal relevance pass-through (5 %): inherited from thread relevance
    """
    # 1. Hypothesis value: count × average confidence, capped at 1.0
    hyp_value = clamp01(min(hypothesis_count, 6) / 6.0 * avg_hypothesis_confidence) if hypothesis_count else 0.0

    # 2. Source quality: fraction of sources from high-credibility domains
    source_quality = 0.0
    if source_count > 0:
        ratio = high_credibility_source_count / source_count
        # Even one credible source in 10 is meaningful; nonlinear scale
        source_quality = clamp01(ratio ** 0.5)

    # 3. Kill criteria coverage: what fraction of kill criteria were searched
    kc_coverage = 0.0
    if kill_criteria_total > 0:
        kc_coverage = clamp01(kill_criteria_covered / kill_criteria_total)
    elif disconfirming_found:
        # No formal kill criteria but disconfirming evidence was found anyway
        kc_coverage = 0.50

    # 4. Disconfirming evidence bonus
    disconfirming_bonus = 0.10 if disconfirming_found else 0.0

    # 5. Anomaly bonus (diminishing returns)
    anomaly_bonus = clamp01(min(anomaly_count, 4) / 4.0) * 0.05

    score = (
        hyp_value * 0.40
        + source_quality * 0.25
        + kc_coverage * 0.20
        + disconfirming_bonus
        + signal_relevance * 0.05
        + anomaly_bonus
    )
    return clamp01(score)


def label_packet_value(signal_decision_value: float) -> str:
    """Human-readable tier for signal_decision_value."""
    if signal_decision_value >= 0.70:
        return "high_value"
    if signal_decision_value >= 0.45:
        return "medium_value"
    if signal_decision_value >= 0.20:
        return "low_value"
    return "noise"
