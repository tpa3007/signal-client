"""Phase 10 tests: Monitoring and Drift.

All tests are network-free.
Tests cover: watch_thread creation, watch_check execution, narrative drift
detection, stale source detection, claim_updates, and SQLite persistence.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from forager.models import (
    Anomaly,
    DriftType,
    ResearchStartRequest,
    WatchCheckRequest,
    WatchStatus,
)
from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService
from forager.memory.sqlite_store import SQLiteForagerStore
from forager.monitor import detect_narrative_drift, detect_stale_sources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_URL = "https://example.com/monitor-test"
_TEXT = "The team denied the claim. The audit contradicts the official report."


def _svc(crawl_text: str = _TEXT) -> ForagerService:
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(url=_URL, title="Monitor test", snippet="audit claim drift", source_name="static", raw={})
        ]
    )
    docs = {_URL: CrawledDocument(url=_URL, title="Monitor Report", content_text=crawl_text)}
    return ForagerService(search_adapter=search, crawler_adapter=StaticCrawlerAdapter(docs))


def _setup_thread(svc: ForagerService) -> str:
    result = svc.start_research(ResearchStartRequest(seed_query="monitoring test", market_id="mkt_p10"))
    return result["thread"]["id"]


# ===========================================================================
# WatchThread creation
# ===========================================================================


def test_watch_thread_created():
    svc = _svc()
    tid = _setup_thread(svc)
    wt = svc.watch_thread(tid)
    assert wt.id.startswith("watch_")
    assert wt.thread_id == tid
    assert wt.status == WatchStatus.ACTIVE


def test_watch_thread_idempotent():
    svc = _svc()
    tid = _setup_thread(svc)
    wt1 = svc.watch_thread(tid)
    wt2 = svc.watch_thread(tid)
    assert wt1.id == wt2.id


def test_watch_thread_stored():
    svc = _svc()
    tid = _setup_thread(svc)
    wt = svc.watch_thread(tid)
    stored = svc.store.thread_watch_threads(tid)
    assert len(stored) == 1
    assert stored[0].id == wt.id


def test_watch_thread_unknown_thread_raises():
    svc = _svc()
    with pytest.raises(KeyError):
        svc.watch_thread("thread_nonexistent")


# ===========================================================================
# WatchCheckResult
# ===========================================================================


def test_watch_check_returns_result():
    svc = _svc()
    tid = _setup_thread(svc)
    result = svc.run_watch_check(tid)
    assert result.watch_thread_id.startswith("watch_")


def test_watch_check_increments_check_count():
    svc = _svc()
    tid = _setup_thread(svc)
    svc.run_watch_check(tid)
    svc.run_watch_check(tid)
    wt = svc.store.thread_watch_threads(tid)[0]
    assert wt.check_count == 2


def test_watch_check_updates_last_checked_at():
    svc = _svc()
    tid = _setup_thread(svc)
    result = svc.run_watch_check(tid)
    wt = svc.store.get_watch_thread(result.watch_thread_id)
    assert wt.last_checked_at is not None


def test_watch_check_no_drift_when_no_drift_detect():
    svc = _svc()
    tid = _setup_thread(svc)
    result = svc.run_watch_check(tid, WatchCheckRequest(detect_drift=False))
    assert result.drift_events_found == 0
    assert result.stale_alerts_found == 0


# ===========================================================================
# Narrative drift detection (pure function)
# ===========================================================================


def test_detect_narrative_drift_no_change():
    from forager.models import Claim, Stance, WatchThread
    wt = WatchThread(thread_id="t1")
    claims = [Claim(thread_id="t1", claim_text="X", stance=Stance.NEUTRAL)]
    events = detect_narrative_drift("t1", wt, claims, claims)
    assert events == []


def test_detect_narrative_drift_volume_increase():
    from forager.models import Claim, Stance, WatchThread
    wt = WatchThread(thread_id="t1")
    old = [Claim(thread_id="t1", claim_text=f"claim {i}", stance=Stance.NEUTRAL) for i in range(4)]
    new = old + [Claim(thread_id="t1", claim_text=f"new {i}", stance=Stance.NEUTRAL) for i in range(4)]
    events = detect_narrative_drift("t1", wt, old, new)
    assert any(e.drift_type == DriftType.NARRATIVE for e in events)


def test_detect_narrative_drift_contradiction_increase():
    from forager.models import Claim, Stance, WatchThread
    wt = WatchThread(thread_id="t1")
    old = [Claim(thread_id="t1", claim_text="A", stance=Stance.NEUTRAL)]
    new = old + [Claim(thread_id="t1", claim_text="B", stance=Stance.CONTRADICTS)]
    events = detect_narrative_drift("t1", wt, old, new)
    assert any(e.drift_type == DriftType.CLAIM_UPDATED for e in events)


# ===========================================================================
# Stale source detection (pure function)
# ===========================================================================


def test_detect_stale_sources_no_stale():
    from forager.models import Source, WatchThread
    from forager.models import now_iso
    wt = WatchThread(thread_id="t1")
    sources = [Source(thread_id="t1", url="https://example.com", last_seen_at=now_iso())]
    alerts = detect_stale_sources("t1", wt, sources, stale_threshold_hours=24.0)
    assert alerts == []


def test_detect_stale_sources_stale():
    from forager.models import Source, WatchThread
    wt = WatchThread(thread_id="t1")
    # Set last_seen_at to 2000-01-01 (definitely stale)
    sources = [Source(thread_id="t1", url="https://old.example.com", last_seen_at="2000-01-01T00:00:00+00:00")]
    alerts = detect_stale_sources("t1", wt, sources, stale_threshold_hours=1.0)
    assert len(alerts) == 1
    assert alerts[0].url == "https://old.example.com"
    assert alerts[0].stale_hours > 1.0


# ===========================================================================
# SQLite persistence
# ===========================================================================


def test_sqlite_watch_thread_persists(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    tid = _setup_thread(svc)
    wt = svc.watch_thread(tid)

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    stored = db2.thread_watch_threads(tid)
    assert len(stored) == 1
    assert stored[0].id == wt.id


def test_sqlite_drift_events_persist(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    tid = _setup_thread(svc)

    from forager.models import NarrativeDriftEvent, DriftType, WatchThread
    wt = svc.watch_thread(tid)
    event = NarrativeDriftEvent(
        thread_id=tid,
        watch_thread_id=wt.id,
        drift_type=DriftType.NARRATIVE,
        description="test drift",
        drift_score=0.5,
    )
    svc.store.add_narrative_drift_event(event)

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    events = db2.thread_narrative_drift_events(tid)
    assert len(events) == 1
    assert events[0].drift_type == DriftType.NARRATIVE


def test_sqlite_stale_alerts_persist(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    tid = _setup_thread(svc)

    from forager.models import StaleSourceAlert, WatchThread
    wt = svc.watch_thread(tid)
    alert = StaleSourceAlert(
        thread_id=tid,
        watch_thread_id=wt.id,
        source_id="source_test",
        url="https://stale.example.com",
        stale_hours=72.0,
        description="72h stale",
    )
    svc.store.add_stale_source_alert(alert)

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    alerts = db2.thread_stale_source_alerts(tid)
    assert len(alerts) == 1
    assert alerts[0].stale_hours == 72.0
