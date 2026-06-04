"""Narrative drift and stale source detection — Phase 10."""
from __future__ import annotations

from datetime import datetime, timezone

from forager.models import (
    Claim,
    DriftType,
    NarrativeDriftEvent,
    Source,
    StaleSourceAlert,
    WatchThread,
)


def detect_narrative_drift(
    thread_id: str,
    watch_thread: WatchThread,
    old_claims: list[Claim],
    new_claims: list[Claim],
) -> list[NarrativeDriftEvent]:
    """Compare old vs new claim sets; return drift events for significant changes."""
    events: list[NarrativeDriftEvent] = []

    old_count = len(old_claims)
    new_count = len(new_claims)
    old_contradictions = sum(1 for c in old_claims if c.stance.value == "contradicts")
    new_contradictions = sum(1 for c in new_claims if c.stance.value == "contradicts")
    contradiction_delta = new_contradictions - old_contradictions

    if old_count > 0 and abs(new_count - old_count) / old_count >= 0.25:
        drift_score = round(min(1.0, abs(new_count - old_count) / old_count), 3)
        events.append(NarrativeDriftEvent(
            thread_id=thread_id,
            watch_thread_id=watch_thread.id,
            drift_type=DriftType.NARRATIVE,
            description=(
                f"Claim volume changed: {old_count} → {new_count} "
                f"({'+'if new_count > old_count else ''}{new_count - old_count})"
            ),
            drift_score=drift_score,
            old_claim_count=old_count,
            new_claim_count=new_count,
            contradiction_delta=contradiction_delta,
        ))

    if abs(contradiction_delta) >= 1:
        drift_score = round(min(1.0, abs(contradiction_delta) / max(old_contradictions, 1)), 3)
        events.append(NarrativeDriftEvent(
            thread_id=thread_id,
            watch_thread_id=watch_thread.id,
            drift_type=DriftType.CLAIM_UPDATED,
            description=(
                f"Contradiction count changed: {old_contradictions} → {new_contradictions}"
            ),
            drift_score=drift_score,
            old_claim_count=old_count,
            new_claim_count=new_count,
            contradiction_delta=contradiction_delta,
        ))

    return events


def detect_stale_sources(
    thread_id: str,
    watch_thread: WatchThread,
    sources: list[Source],
    stale_threshold_hours: float = 24.0,
) -> list[StaleSourceAlert]:
    """Return a StaleSourceAlert for each source not refreshed within threshold."""
    now = datetime.now(timezone.utc)
    alerts: list[StaleSourceAlert] = []
    for source in sources:
        last_seen = source.last_seen_at or source.first_seen_at
        try:
            last_dt = datetime.fromisoformat(last_seen)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            last_dt = now
        stale_hours = (now - last_dt).total_seconds() / 3600.0
        if stale_hours >= stale_threshold_hours:
            alerts.append(StaleSourceAlert(
                thread_id=thread_id,
                watch_thread_id=watch_thread.id,
                source_id=source.id,
                url=source.url,
                last_fetched_at=last_seen,
                stale_hours=round(stale_hours, 1),
                description=(
                    f"Source not refreshed in {stale_hours:.1f}h "
                    f"(threshold: {stale_threshold_hours}h)"
                ),
            ))
    return alerts
