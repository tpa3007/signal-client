"""Probability calibration from outcome_learning_reviews.

Builds a correction curve: bucket our historical predicted_probability values,
compute actual_win_rate per bucket, interpolate a correction function.

With < MIN_RESOLVED outcomes: returns identity (no correction — not enough data).
With >= MIN_RESOLVED: returns a step-function correction based on bucket averages.

Usage:
    from lib.calibration import load_calibration_correction
    correct = load_calibration_correction(db_path)
    adjusted_prob = correct(raw_estimated_prob)
"""
from __future__ import annotations

import sqlite3
from typing import Callable

MIN_RESOLVED = 10   # resolved trades for full-strength calibration
SOFT_MIN_RESOLVED = 5  # below this, no correction at all (too noisy)
FULL_BLEND = 0.70   # blend strength at/above MIN_RESOLVED
SOFT_BLEND = 0.30   # blend strength in the SOFT_MIN..MIN transition band
BUCKETS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def _blend_strength(n_resolved: int) -> float:
    """Ramp correction strength with sample size.

    < SOFT_MIN          -> 0.0 (identity)
    SOFT_MIN..MIN-1     -> SOFT_BLEND (damped, avoids overfitting tiny samples)
    >= MIN              -> FULL_BLEND
    """
    if n_resolved < SOFT_MIN_RESOLVED:
        return 0.0
    if n_resolved < MIN_RESOLVED:
        return SOFT_BLEND
    return FULL_BLEND


def _identity(prob: float) -> float:
    return max(0.01, min(0.99, prob))


def compute_brier(probability_yes: float | None, outcome_side: str) -> float | None:
    """Brier score in YES-space: (forecast_yes - outcome)^2, outcome in {0,1}.

    Returns None when the outcome is not a clean YES/NO resolution or the
    forecast is missing. Lower is better; 0.25 is the coin-flip baseline.
    """
    if probability_yes is None:
        return None
    outcome = outcome_side.upper() if outcome_side else ""
    if outcome not in ("YES", "NO"):
        return None
    outcome_value = 1.0 if outcome == "YES" else 0.0
    p = max(0.0, min(1.0, float(probability_yes)))
    return round((p - outcome_value) ** 2, 4)


def load_calibration_correction(db_path: str = "bot.db") -> Callable[[float], float]:
    """Return a calibration function based on resolved outcome_learning_reviews.

    Returns identity function if:
    - DB doesn't exist
    - outcome_learning_reviews table missing
    - fewer than MIN_RESOLVED resolved outcomes

    Otherwise returns a step-function interpolation over 0.1-wide buckets.
    The corrected probability is clipped to [0.01, 0.99].
    """
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute("""
            SELECT probability_yes, outcome_side
            FROM outcome_learning_reviews
            WHERE outcome_side IN ('YES', 'NO')
              AND probability_yes IS NOT NULL
              AND probability_yes > 0
              AND probability_yes < 1
        """).fetchall()
        conn.close()
    except Exception:  # noqa: BLE001
        return _identity

    blend = _blend_strength(len(rows))
    if blend == 0.0:
        return _identity

    # Build bucket → (sum_wins, count)
    bucket_stats: dict[float, list[int]] = {b: [0, 0] for b in BUCKETS}
    for prob_yes, outcome in rows:
        prob = float(prob_yes)
        bucket_idx = min(int(prob * 10) / 10, 0.9)
        bucket_idx = round(bucket_idx, 1)
        if bucket_idx not in bucket_stats:
            bucket_idx = min(BUCKETS, key=lambda b: abs(b - prob))
        bucket_stats[bucket_idx][1] += 1
        if outcome == "YES":
            bucket_stats[bucket_idx][0] += 1

    # Build correction lookup: {bucket_center → actual_win_rate}
    corrections: dict[float, float] = {}
    for bucket, (wins, count) in bucket_stats.items():
        if count >= 2:
            corrections[bucket] = wins / count
        # else: bucket has <2 samples → fall through to identity for that bucket

    if not corrections:
        return _identity

    def correct(prob: float) -> float:
        p = max(0.01, min(0.99, float(prob)))
        bucket = round(min(int(p * 10) / 10, 0.9), 1)
        if bucket in corrections:
            raw_correction = corrections[bucket] - bucket
            # Blend strength ramps with sample size (see _blend_strength).
            adjusted = p + blend * raw_correction
            return round(max(0.01, min(0.99, adjusted)), 3)
        return p

    return correct


def calibration_stats(db_path: str = "bot.db") -> dict:
    """Return a summary of the calibration dataset for reporting.

    Returns:
        {resolved: int, pending: int, buckets: {bucket: {predicted, actual, count}},
         overconfident: bool, well_calibrated: bool}
    """
    try:
        conn = sqlite3.connect(db_path)
        all_rows = conn.execute(
            "SELECT probability_yes, confidence, outcome_side FROM outcome_learning_reviews"
        ).fetchall()
        conn.close()
    except Exception:  # noqa: BLE001
        return {"error": "DB unavailable", "resolved": 0}

    resolved = [r for r in all_rows if r[2] in ("YES", "NO")]
    pending = [r for r in all_rows if r[2] == "PENDING"]

    bucket_data: dict[float, dict] = {}
    for prob_yes, _, outcome in resolved:
        prob = float(prob_yes)
        bucket = round(min(int(prob * 10) / 10, 0.9), 1)
        if bucket not in bucket_data:
            bucket_data[bucket] = {"predicted": bucket + 0.05, "wins": 0, "count": 0}
        bucket_data[bucket]["count"] += 1
        if outcome == "YES":
            bucket_data[bucket]["wins"] += 1

    buckets_out = {}
    overconfidence_deltas = []
    for b, d in sorted(bucket_data.items()):
        if d["count"] > 0:
            actual = d["wins"] / d["count"]
            buckets_out[str(b)] = {
                "predicted_center": d["predicted"],
                "actual_win_rate": round(actual, 3),
                "count": d["count"],
                "delta": round(actual - d["predicted"], 3),
            }
            overconfidence_deltas.append(actual - d["predicted"])

    avg_delta = sum(overconfidence_deltas) / len(overconfidence_deltas) if overconfidence_deltas else 0
    return {
        "resolved": len(resolved),
        "pending": len(pending),
        "total": len(all_rows),
        "min_for_calibration": MIN_RESOLVED,
        "soft_min": SOFT_MIN_RESOLVED,
        "calibration_active": len(resolved) >= SOFT_MIN_RESOLVED,
        "blend_strength": _blend_strength(len(resolved)),
        "full_strength": len(resolved) >= MIN_RESOLVED,
        "average_delta": round(avg_delta, 3),
        "overconfident": avg_delta < -0.05,
        "well_calibrated": abs(avg_delta) <= 0.05,
        "buckets": buckets_out,
    }
