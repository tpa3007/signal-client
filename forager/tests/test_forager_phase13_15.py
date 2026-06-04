"""Phase 13-15 tests: hardening, Signal handoff snapshots, readiness.

These tests keep Forager's core contract explicit:
- incomplete threads must surface blockers,
- Signal integration is a read-only snapshot, not a Signal DB write,
- reference readiness reports persist locally.
"""
from __future__ import annotations

from pathlib import Path

from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.memory.sqlite_store import SQLiteForagerStore
from forager.models import (
    CalibrationRequest,
    CrawlSourceRequest,
    EvidenceDraftRequest,
    EvidenceDraftReviewRequest,
    EvidenceDraftStatus,
    MaintenanceAuditRequest,
    ResearchStartRequest,
    SearchBurstRequest,
    WatchCheckRequest,
)
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService


_CRAWL_URL = "https://example.com/phase13-15"
_CRAWL_TEXT = """
The local audit supports that the candidate gained momentum after a new poll.
A second analyst contradicts the old consensus and reports turnout pressure.
Independent observers confirm the race is still volatile but source-backed.
"""


def _svc() -> ForagerService:
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(
                url=_CRAWL_URL,
                title="Forager readiness test",
                snippet="local audit contradicts old consensus",
                source_name="static",
                raw={},
            )
        ]
    )
    crawler = StaticCrawlerAdapter(
        {
            _CRAWL_URL: CrawledDocument(
                url=_CRAWL_URL,
                title="Forager readiness article",
                content_text=_CRAWL_TEXT,
            )
        }
    )
    return ForagerService(search_adapter=search, crawler_adapter=crawler)


def _setup_researched_thread(svc: ForagerService) -> str:
    start = svc.start_research(ResearchStartRequest(seed_query="readiness local poll", market_id="mkt_phase13_15"))
    thread_id = start["thread"]["id"]
    svc.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1, promote_threshold=0.0))
    svc.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))
    svc.build_packet(thread_id)
    return thread_id


def test_maintenance_audit_blocks_empty_thread() -> None:
    svc = _svc()
    start = svc.start_research(ResearchStartRequest(seed_query="empty thread"))
    thread_id = start["thread"]["id"]

    report = svc.run_maintenance_audit(thread_id, MaintenanceAuditRequest(include_low_severity=False))

    codes = {finding.code for finding in report.findings}
    assert report.status == "fail"
    assert "packet_missing" in codes
    assert "documents_missing" in codes
    assert report.counts["documents"] == 0


def test_signal_integration_snapshot_is_context_only() -> None:
    svc = _svc()
    thread_id = _setup_researched_thread(svc)
    drafts = svc.build_evidence_drafts(thread_id, EvidenceDraftRequest(require_disconfirming=False))
    assert drafts.draft_ids
    reviewed = svc.review_evidence_draft(
        thread_id,
        drafts.draft_ids[0],
        EvidenceDraftReviewRequest(status=EvidenceDraftStatus.APPROVED, reviewer_note="source-backed"),
    )
    svc.watch_thread(thread_id, WatchCheckRequest())
    svc.build_calibration_summary(thread_id, CalibrationRequest())

    snapshot = svc.build_signal_integration_snapshot(thread_id)

    assert "does not write Signal DB" in snapshot.boundary
    assert snapshot.forager_packet_id is not None
    assert reviewed.id in snapshot.approved_evidence_draft_ids
    assert snapshot.evidence_bundle_ids
    assert "review_for_signal_dossier_import" in snapshot.recommended_next_actions


def test_reference_readiness_report_persists_in_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "forager.db"
    db = SQLiteForagerStore(db_path)
    svc = _svc()
    svc.store = db
    start = svc.start_research(ResearchStartRequest(seed_query="sqlite readiness", market_id="mkt_sqlite_ready"))
    thread_id = start["thread"]["id"]

    report = svc.build_reference_readiness_report(thread_id)

    db2 = SQLiteForagerStore(db_path)
    stored = db2.thread_reference_readiness_reports(thread_id)
    assert len(stored) == 1
    assert stored[0].id == report.id
    assert stored[0].reference_ready is False
    assert "maturity_below_reference_threshold" in stored[0].blockers
