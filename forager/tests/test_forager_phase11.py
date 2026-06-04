"""Phase 11 tests: Scoring and Calibration.

All tests are network-free.
Tests cover: archetype classification, anomaly review, source track records,
calibration summary, alpha rate calculation, and SQLite persistence.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from forager.models import (
    AnomalyReviewRequest,
    AnomalyVerdict,
    CalibrationRequest,
    ResearchStartRequest,
    SourceType,
    WeirdnessArchetype,
)
from forager.archetypes import classify_weirdness_archetype
from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService
from forager.memory.sqlite_store import SQLiteForagerStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_URL = "https://example.com/calibration-test"
_TEXT = "The team confirmed stability. The audit supports the roadmap."


def _svc(crawl_text: str = _TEXT) -> ForagerService:
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(url=_URL, title="Calib test", snippet="audit stability calibration", source_name="static", raw={})
        ]
    )
    docs = {_URL: CrawledDocument(url=_URL, title="Calibration Report", content_text=crawl_text)}
    return ForagerService(search_adapter=search, crawler_adapter=StaticCrawlerAdapter(docs))


def _setup_thread(svc: ForagerService) -> str:
    result = svc.start_research(ResearchStartRequest(seed_query="calibration test", market_id="mkt_p11"))
    return result["thread"]["id"]


# ===========================================================================
# Archetype classifier
# ===========================================================================


def test_archetype_github():
    assert classify_weirdness_archetype("https://github.com/org/repo", SourceType.GITHUB) == WeirdnessArchetype.GITHUB_SIGNAL


def test_archetype_github_url_only():
    assert classify_weirdness_archetype("https://github.com/project/issues", "unknown") == WeirdnessArchetype.GITHUB_SIGNAL


def test_archetype_archive():
    assert classify_weirdness_archetype("https://web.archive.org/web/2023/...", SourceType.ARCHIVE) == WeirdnessArchetype.ARCHIVED_CONTRADICTION


def test_archetype_pdf():
    assert classify_weirdness_archetype("https://example.com/report.pdf", SourceType.PDF) == WeirdnessArchetype.PDF_HIDDEN


def test_archetype_forum():
    assert classify_weirdness_archetype("https://reddit.com/r/crypto", SourceType.FORUM) == WeirdnessArchetype.FORUM_RUMOR


def test_archetype_translation_surface():
    assert classify_weirdness_archetype("https://example.ru/article", SourceType.UNKNOWN) == WeirdnessArchetype.TRANSLATION_SURFACE


def test_archetype_unknown():
    assert classify_weirdness_archetype("https://example.com/news", SourceType.UNKNOWN) == WeirdnessArchetype.UNKNOWN


# ===========================================================================
# AnomalyReview
# ===========================================================================


def test_review_anomaly_creates_record():
    svc = _svc()
    tid = _setup_thread(svc)
    from forager.models import Anomaly
    anomaly = svc.store.add_anomaly(Anomaly(
        thread_id=tid,
        anomaly_type="source_weirdness",
        description="test anomaly",
        weirdness_score=0.75,
        evidence={},
    ))
    review = svc.review_anomaly(tid, AnomalyReviewRequest(
        anomaly_id=anomaly.id,
        verdict=AnomalyVerdict.CONFIRMED_ALPHA,
        archetype=WeirdnessArchetype.GITHUB_SIGNAL,
    ))
    assert review.id.startswith("review_")
    assert review.verdict == AnomalyVerdict.CONFIRMED_ALPHA
    assert review.archetype == WeirdnessArchetype.GITHUB_SIGNAL


def test_review_anomaly_stored():
    svc = _svc()
    tid = _setup_thread(svc)
    from forager.models import Anomaly
    anomaly = svc.store.add_anomaly(Anomaly(thread_id=tid, anomaly_type="test", description="x", weirdness_score=0.5, evidence={}))
    svc.review_anomaly(tid, AnomalyReviewRequest(anomaly_id=anomaly.id, verdict=AnomalyVerdict.FALSE_POSITIVE))
    reviews = svc.store.thread_anomaly_reviews(tid)
    assert len(reviews) == 1


def test_review_anomaly_unknown_thread_raises():
    svc = _svc()
    with pytest.raises(KeyError):
        svc.review_anomaly("thread_none", AnomalyReviewRequest(anomaly_id="x", verdict=AnomalyVerdict.NOISE))


# ===========================================================================
# SourceTrackRecord
# ===========================================================================


def test_build_source_track_records_returns_records():
    svc = _svc()
    tid = _setup_thread(svc)
    svc.run_search_burst(tid)
    svc.crawl_sources(tid)
    records = svc.build_source_track_records(tid)
    assert isinstance(records, list)


def test_source_track_record_has_correct_fields():
    svc = _svc()
    tid = _setup_thread(svc)
    svc.run_search_burst(tid)
    svc.crawl_sources(tid)
    records = svc.build_source_track_records(tid)
    if records:
        rec = records[0]
        assert rec.id.startswith("track_")
        assert rec.thread_id == tid
        assert rec.yield_score >= 0.0


# ===========================================================================
# Calibration summary
# ===========================================================================


def test_calibration_summary_empty_returns_zero_rate():
    svc = _svc()
    tid = _setup_thread(svc)
    score = svc.build_calibration_summary(tid)
    assert score.id.startswith("calib_")
    assert score.weirdness_alpha_rate == 0.0
    assert score.total_anomalies == 0


def test_calibration_summary_with_reviews():
    svc = _svc()
    tid = _setup_thread(svc)
    from forager.models import Anomaly
    for i in range(3):
        a = svc.store.add_anomaly(Anomaly(thread_id=tid, anomaly_type="t", description=f"a{i}", weirdness_score=0.5, evidence={}))
        verdict = AnomalyVerdict.CONFIRMED_ALPHA if i < 2 else AnomalyVerdict.FALSE_POSITIVE
        svc.review_anomaly(tid, AnomalyReviewRequest(anomaly_id=a.id, verdict=verdict))
    score = svc.build_calibration_summary(tid)
    assert score.total_anomalies == 3
    assert score.confirmed_alpha_count == 2
    assert score.false_positive_count == 1
    assert abs(score.weirdness_alpha_rate - 2/3) < 0.01


def test_calibration_archetype_yields():
    svc = _svc()
    tid = _setup_thread(svc)
    from forager.models import Anomaly
    a1 = svc.store.add_anomaly(Anomaly(thread_id=tid, anomaly_type="t", description="x", weirdness_score=0.5, evidence={}))
    a2 = svc.store.add_anomaly(Anomaly(thread_id=tid, anomaly_type="t", description="y", weirdness_score=0.5, evidence={}))
    svc.review_anomaly(tid, AnomalyReviewRequest(anomaly_id=a1.id, verdict=AnomalyVerdict.CONFIRMED_ALPHA, archetype=WeirdnessArchetype.GITHUB_SIGNAL))
    svc.review_anomaly(tid, AnomalyReviewRequest(anomaly_id=a2.id, verdict=AnomalyVerdict.FALSE_POSITIVE, archetype=WeirdnessArchetype.FORUM_RUMOR))
    score = svc.build_calibration_summary(tid)
    assert score.archetype_yields.get("github_signal") == 1.0
    assert score.archetype_yields.get("forum_rumor") == 0.0


# ===========================================================================
# SQLite persistence
# ===========================================================================


def test_sqlite_anomaly_review_persists(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    tid = _setup_thread(svc)
    from forager.models import Anomaly
    a = svc.store.add_anomaly(Anomaly(thread_id=tid, anomaly_type="t", description="x", weirdness_score=0.5, evidence={}))
    svc.review_anomaly(tid, AnomalyReviewRequest(anomaly_id=a.id, verdict=AnomalyVerdict.CONFIRMED_ALPHA))

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    reviews = db2.thread_anomaly_reviews(tid)
    assert len(reviews) == 1
    assert reviews[0].verdict == AnomalyVerdict.CONFIRMED_ALPHA


def test_sqlite_calibration_score_persists(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    tid = _setup_thread(svc)
    score = svc.build_calibration_summary(tid)

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    scores = db2.thread_calibration_scores(tid)
    assert len(scores) == 1
    assert scores[0].id == score.id
