"""Evidence Draft scoring utilities for Forager Phase 7.

These functions score reliability and freshness of evidence candidates.
They are pure functions — no store access, no side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone


def source_type_weight(source_type: str) -> float:
    """Base reliability weight by source type. Claim > Document > RawItem."""
    weights = {
        "claim": 0.70,
        "document": 0.60,
        "raw_item": 0.45,
    }
    return weights.get(source_type, 0.45)


def score_draft_reliability(
    source_type: str,
    credibility_score: float = 0.5,
    claim_confidence: float = 0.5,
) -> float:
    """Combine source-type weight with credibility and claim confidence."""
    weight = source_type_weight(source_type)
    raw = weight * credibility_score + 0.30 * claim_confidence
    return round(min(1.0, raw), 3)


def score_draft_freshness(published_at: str | None) -> float:
    """Return 0.0–1.0 freshness. Decays linearly over 365 days. Unknown → 0.5."""
    if not published_at:
        return 0.5
    try:
        pub = datetime.fromisoformat(published_at)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_old = max(0, (now - pub).days)
        if days_old < 1:
            return 1.0
        if days_old >= 365:
            return 0.10
        return round(max(0.10, 1.0 - days_old / 365), 3)
    except Exception:
        return 0.5
