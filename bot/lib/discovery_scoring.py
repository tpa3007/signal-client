"""Deterministic auto-scores for hidden-gem components. No LLM calls.

These fill the parts of `record_hidden_gem_review` that don't require reading
the market: attention_gap, stale_price, liquidity, spread. Claude still owns
evidence_asymmetry / catalyst / resolution_clarity (require interpretation).
"""
from __future__ import annotations

import statistics

import config
from lib.execution import clamp01

# Normalisation constants — tuneable but kept stable for now so calibration
# accumulates against fixed denominators.
VOLUME_SATURATION_USD = 100_000.0
AGE_SATURATION_DAYS = 60.0
LIQUIDITY_SATURATION_USD = 50_000.0
STALE_STDEV_SATURATION = 0.05


def attention_gap_score(volume: float, market_age_days: float | None,
                        liquidity: float | None) -> float:
    """Low volume despite long age and adequate liquidity = attention gap.

    Score = (1 − volume_share) × age_share × liquidity_share. Each component
    saturates at the constants above. Missing age or liquidity → mid-value
    contribution (0.5) for that factor.
    """
    vol_share = clamp01(float(volume or 0.0) / VOLUME_SATURATION_USD)
    if market_age_days is None:
        age_share = 0.5
    else:
        age_share = clamp01(float(market_age_days) / AGE_SATURATION_DAYS)
    if liquidity is None:
        liq_share = 0.5
    else:
        liq_share = clamp01(float(liquidity) / LIQUIDITY_SATURATION_USD)
    return round((1.0 - vol_share) * age_share * liq_share, 4)


def stale_price_score(price_series: list[float] | None) -> float:
    """Higher score = lower variance = staler price. Needs >= 3 points.

    Returns 0.5 (neutral) when we don't have enough history to judge.
    """
    if not price_series or len(price_series) < 3:
        return 0.5
    try:
        stdev = statistics.pstdev(price_series)
    except statistics.StatisticsError:
        return 0.5
    return round(1.0 - clamp01(stdev / STALE_STDEV_SATURATION), 4)


def liquidity_score(liquidity: float | None) -> float:
    if liquidity is None:
        return 0.5
    return round(clamp01(float(liquidity) / config.MOONSHOT_LIQUIDITY_NORM), 4)


def spread_score(spread: float | None) -> float:
    if spread is None or config.MAX_SPREAD <= 0:
        return 0.5
    return round(clamp01(1.0 - (float(spread) / config.MAX_SPREAD)), 4)


def combined_raw_discoverability(*, attention_gap: float, stale_price: float,
                                 liquidity: float, spread: float,
                                 strategy_bonus: float = 0.0) -> float:
    """0..100 ranking score.

    Weights bias toward "hidden": attention_gap (40%) is the strongest signal,
    stale_price (25%) the second. Liquidity and spread (10% each) only nudge
    the ranking among matched gems — strategies already gate on them, so the
    score shouldn't double-count execution-friendliness over neglected-ness.
    A market matching multiple strategies gets a 15% bonus contribution.
    """
    weighted = (
        0.40 * attention_gap
        + 0.25 * stale_price
        + 0.10 * liquidity
        + 0.10 * spread
        + 0.15 * clamp01(strategy_bonus)
    )
    return round(100.0 * weighted, 2)
