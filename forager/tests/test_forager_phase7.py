"""Phase 7 tests: Evidence Draft Layer.

All tests are network-free. Focus on:
- Scoring utilities (reliability, freshness)
- EvidenceDraft creation from claims / documents / raw items
- Disconfirming evidence requirement
- review_evidence_draft (Signal import path)
- Boundary invariant: drafts carry the boundary string
- SQLite persistence
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forager.evidence import score_draft_freshness, score_draft_reliability, source_type_weight
from forager.models import (
    Claim,
    ClaimType,
    CrawlSourceRequest,
    Document,
    EvidenceDraftRequest,
    EvidenceDraftReviewRequest,
    EvidenceDraftStatus,
    EvidenceSourceType,
    ResearchStartRequest,
    SearchBurstRequest,
    Stance,
    SourceRawItem,
    SourceType,
)
from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService
from forager.memory.sqlite_store import SQLiteForagerStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CRAWL_URL = "https://example.com/evidence-test"
_CRAWL_TEXT = """
The project denied the milestone was stable. The audit contradicts the official claim.
Independent review supports a delay in the timeline. Evidence of misrepresentation found.
"""


def _svc() -> ForagerService:
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(url=_CRAWL_URL, title="Evidence test article", snippet="contradicts claim", source_name="static", raw={})
        ]
    )
    docs = {_CRAWL_URL: CrawledDocument(url=_CRAWL_URL, title="Evidence Article", content_text=_CRAWL_TEXT)}
    return ForagerService(search_adapter=search, crawler_adapter=StaticCrawlerAdapter(docs))


def _setup_thread(svc: ForagerService) -> str:
    start = svc.start_research(ResearchStartRequest(seed_query="milestone audit delay", market_id="mkt_p7"))
    thread_id = start["thread"]["id"]
    svc.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1, promote_threshold=0.0))
    svc.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))
    return thread_id


# ===========================================================================
# Scoring utilities
# ===========================================================================


def test_source_type_weight_claim_highest():
    assert source_type_weight("claim") > source_type_weight("document")
    assert source_type_weight("document") > source_type_weight("raw_item")


def test_reliability_score_bounded():
    score = score_draft_reliability("claim", credibility_score=1.0, claim_confidence=1.0)
    assert 0.0 <= score <= 1.0


def test_reliability_low_for_raw_item_with_low_credibility():
    score = score_draft_reliability("raw_item", credibility_score=0.1, claim_confidence=0.0)
    assert score < 0.5


def test_freshness_returns_half_for_unknown():
    assert score_draft_freshness(None) == 0.5


def test_freshness_high_for_recent():
    recent = datetime.now(timezone.utc).isoformat()
    assert score_draft_freshness(recent) == 1.0


def test_freshness_low_for_old():
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    assert score_draft_freshness(old) <= 0.10


def test_freshness_decays_linearly():
    mid = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    score = score_draft_freshness(mid)
    assert 0.40 < score < 0.65


# ===========================================================================
# build_evidence_drafts
# ===========================================================================


def test_build_evidence_drafts_creates_drafts():
    svc = _svc()
    thread_id = _setup_thread(svc)
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    assert result.drafts_created > 0


def test_build_evidence_drafts_creates_bundle():
    svc = _svc()
    thread_id = _setup_thread(svc)
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    assert result.bundle_id is not None
    bundles = svc.store.thread_evidence_draft_bundles(thread_id)
    assert len(bundles) == 1
    assert bundles[0].id == result.bundle_id


def test_build_evidence_drafts_boundary_invariant():
    svc = _svc()
    thread_id = _setup_thread(svc)
    svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    drafts = svc.store.thread_evidence_drafts(thread_id)
    for draft in drafts:
        assert "not evidence" in draft.boundary


def test_disconfirming_blocker_when_no_contradicts():
    svc = _svc()
    # Thread with no crawled documents — no claims, no contradictions
    start = svc.start_research(ResearchStartRequest(seed_query="no contradictions", market_id="mkt_p7b"))
    thread_id = start["thread"]["id"]
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=True))
    assert result.blocker == "no_disconfirming_evidence_found"


def test_no_blocker_when_require_disconfirming_false():
    svc = _svc()
    start = svc.start_research(ResearchStartRequest(seed_query="no contradictions", market_id="mkt_p7c"))
    thread_id = start["thread"]["id"]
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    assert result.blocker is None


def test_min_reliability_filters_low_quality():
    svc = _svc()
    thread_id = _setup_thread(svc)
    # Very high threshold should filter out most or all drafts
    result = svc.build_evidence_drafts(
        thread_id,
        EvidenceDraftRequest(min_reliability_score=0.99, require_disconfirming=False),
    )
    assert result.drafts_created == 0


# ===========================================================================
# review_evidence_draft
# ===========================================================================


def test_review_draft_approved():
    svc = _svc()
    thread_id = _setup_thread(svc)
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    assert result.draft_ids
    draft_id = result.draft_ids[0]
    reviewed = svc.review_evidence_draft(
        thread_id,
        draft_id,
        EvidenceDraftReviewRequest(status=EvidenceDraftStatus.APPROVED, reviewer_note="looks good"),
    )
    assert reviewed.status == EvidenceDraftStatus.APPROVED
    assert reviewed.reviewer_note == "looks good"
    assert reviewed.reviewed_at is not None


def test_review_draft_rejected():
    svc = _svc()
    thread_id = _setup_thread(svc)
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    draft_id = result.draft_ids[0]
    reviewed = svc.review_evidence_draft(
        thread_id,
        draft_id,
        EvidenceDraftReviewRequest(status=EvidenceDraftStatus.REJECTED, reviewer_note="stale source"),
    )
    assert reviewed.status == EvidenceDraftStatus.REJECTED


def test_review_draft_persisted_in_store():
    svc = _svc()
    thread_id = _setup_thread(svc)
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    draft_id = result.draft_ids[0]
    svc.review_evidence_draft(thread_id, draft_id, EvidenceDraftReviewRequest(status=EvidenceDraftStatus.APPROVED))
    stored = svc.store.get_evidence_draft(draft_id)
    assert stored is not None
    assert stored.status == EvidenceDraftStatus.APPROVED


def test_review_unknown_draft_raises():
    svc = _svc()
    thread_id = _setup_thread(svc)
    with pytest.raises(KeyError, match="evidence draft not found"):
        svc.review_evidence_draft(thread_id, "draft_nonexistent", EvidenceDraftReviewRequest(status=EvidenceDraftStatus.APPROVED))


# ===========================================================================
# SQLite persistence
# ===========================================================================


def test_sqlite_evidence_drafts_persist(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    thread_id = _setup_thread(svc)
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    assert result.drafts_created > 0

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    drafts = db2.thread_evidence_drafts(thread_id)
    assert len(drafts) == result.drafts_created


def test_sqlite_review_persists(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    thread_id = _setup_thread(svc)
    result = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    draft_id = result.draft_ids[0]
    svc.review_evidence_draft(thread_id, draft_id, EvidenceDraftReviewRequest(status=EvidenceDraftStatus.APPROVED))

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    stored = db2.get_evidence_draft(draft_id)
    assert stored is not None
    assert stored.status == EvidenceDraftStatus.APPROVED
