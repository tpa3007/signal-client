"""Price / edge / gating helpers. No DB access."""
from __future__ import annotations

import config


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def float_or_none(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if 0.0 <= out <= 1.0 else None


def execution_prices(
    yes_price: float,
    no_price: float,
    best_bid: float | None,
    best_ask: float | None,
    spread: float | None,
) -> tuple[float, float, float | None]:
    """Buying YES uses YES ask; buying NO ≈ 1 − YES bid. Falls back to outcome prices."""
    computed_spread = spread
    if computed_spread is None and best_bid is not None and best_ask is not None:
        computed_spread = max(0.0, best_ask - best_bid)
    yes_entry = best_ask if best_ask is not None else yes_price
    no_entry = (1.0 - best_bid) if best_bid is not None else no_price
    return yes_entry, no_entry, computed_spread


def best_executable_edge(
    probability_yes: float,
    yes_entry_price: float,
    no_entry_price: float,
) -> tuple[str, float]:
    yes_edge = probability_yes - yes_entry_price
    no_edge = (1.0 - probability_yes) - no_entry_price
    return ("YES", yes_edge) if yes_edge >= no_edge else ("NO", no_edge)


def no_signal_reason(edge: float, confidence: float, spread: float | None) -> str | None:
    """
    Stage 0 gates (tightened 2026-05-18 audit):
      - edge >= EDGE_THRESHOLD
      - spread <= MAX_SPREAD
      - confidence >= MIN_CONFIDENCE
      - spread-adjusted edge = edge − spread/2 >= MIN_SPREAD_ADJ_EDGE
    """
    if edge < config.EDGE_THRESHOLD:
        return "edge_below_threshold"
    if spread is not None and spread > config.MAX_SPREAD:
        return "spread_too_wide"
    if confidence < config.MIN_CONFIDENCE:
        return "confidence_below_threshold"
    spread_for_adj = spread if spread is not None else 0.0
    if (edge - spread_for_adj / 2.0) < config.MIN_SPREAD_ADJ_EDGE:
        return "spread_adjusted_edge_below_threshold"
    return None
