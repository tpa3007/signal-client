"""Stake sizing.

Stage 0 introduced the Kelly-fraction wrapper. Stage 1 adds portfolio-aware
shrinkage: the more of a sector/archetype/deadline-week bucket we already hold,
the more we shrink new stakes in that bucket, even if the raw signal is strong.
"""
from __future__ import annotations

import config


def recommended_stake(
    edge: float,
    confidence: float,
    *,
    conn=None,
    condition_id: str | None = None,
    vertical: str | None = None,
    primary_archetype: str | None = None,
    end_date: str | None = None,
    theme_tags: list[str] | None = None,
) -> dict:
    """Return ``{recommended, base, shrinkage_factor, clamped, breaches}``.

    - ``base`` = ``BANKROLL_USD * KELLY_FRACTION * edge * confidence``.
    - ``shrinkage_factor`` = ``1 - highest_existing_share`` across exposure
      buckets. If no ``conn`` is provided, shrinkage is 1.0 (Stage 0 behaviour).
    - Final stake is clamped to ``[BET_MIN_USD, BET_MAX_USD]``.
    - ``breaches`` lists caps that the *base + shrunk* stake would still violate
      (informational; clamping comes from sizing, not from this list).
    """
    base = (
        config.BANKROLL_USD
        * config.KELLY_FRACTION
        * max(0.0, float(edge))
        * max(0.0, float(confidence))
    )

    shrinkage_factor = 1.0
    breaches: list[dict] = []
    if conn is not None and condition_id is not None and vertical is not None:
        # Import locally to avoid a circular import at module load.
        from lib.exposure import check_exposure
        chk = check_exposure(
            conn,
            condition_id=condition_id,
            vertical=vertical,
            primary_archetype=primary_archetype,
            end_date=end_date,
            proposed_stake_usd=base,
            theme_tags=theme_tags,
        )
        shrinkage_factor = max(0.0, 1.0 - chk["highest_existing_share"])
        breaches = chk["breaches"]

    raw = base * shrinkage_factor
    clamped_value = min(max(round(raw, 2), config.BET_MIN_USD), config.BET_MAX_USD)
    return {
        "recommended": clamped_value,
        "base": round(base, 2),
        "shrinkage_factor": round(shrinkage_factor, 4),
        "clamped": clamped_value != round(raw, 2),
        "breaches": breaches,
    }
