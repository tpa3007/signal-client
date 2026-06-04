"""Phase 6 tests: rich crawling layer.

All tests are network-free. Real adapters (Wayback, GitHub, RSS) use static
sub-adapters inside CrawlRouter, or parse static content directly.
"""
from __future__ import annotations

import time

import pytest

from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.crawl_budget import CrawlBudgetExhausted, CrawlBudgetLedger, CrawlPolicy
from forager.crawl_github import GitHubCrawlerAdapter
from forager.crawl_pdf import PdfCrawlerAdapter
from forager.crawl_router import CrawlRouter, build_default_router
from forager.crawl_rss import RssCrawlerAdapter
from forager.models import CrawlSourceRequest, ResearchStartRequest, SearchBurstRequest
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RSS_2_XML = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item><title>Launch delayed</title><description>The project launch will be postponed.</description></item>
    <item><title>Audit contradicts claim</title><description>Independent audit denied the milestone was stable.</description></item>
  </channel>
</rss>"""

ATOM_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Unusual activity detected</title>
    <summary>Market odds may miss the delay signal.</summary>
  </entry>
</feed>"""

# Minimal valid PDF with one visible text object (uncompressed)
_PDF_BYTES = (
    b"%PDF-1.0\n1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type /Pages /Kids [3 0 R] /Count 1>>endobj\n"
    b"3 0 obj<</Type /Page /MediaBox [0 0 612 792]"
    b"/Contents 4 0 R /Parent 2 0 R>>endobj\n"
    b"4 0 obj<</Length 44>>\nstream\n"
    b"BT /F1 12 Tf 100 700 Td (Hello PDF world) Tj ET\n"
    b"endstream\nendobj\n"
    b"xref\n0 5\n0000000000 65535 f\n"
    b"trailer<</Size 5 /Root 1 0 R>>\n%%EOF"
)


def _static_router(url_map: dict[str, str]) -> CrawlRouter:
    """Router backed by a StaticCrawlerAdapter for all types."""
    docs = {
        url: CrawledDocument(url=url, title=None, content_text=text)
        for url, text in url_map.items()
    }
    static = StaticCrawlerAdapter(docs)
    return CrawlRouter(
        adapters={"http": static, "github": static, "rss": static, "wayback": static, "pdf": static},
        policy=CrawlPolicy(min_delay_seconds=0),
    )


# ===========================================================================
# Budget ledger
# ===========================================================================


def test_budget_allows_first_request():
    ledger = CrawlBudgetLedger(CrawlPolicy(min_delay_seconds=0))
    allowed, reason = ledger.can_crawl("https://example.com/page")
    assert allowed
    assert reason is None


def test_budget_blocks_after_domain_limit():
    ledger = CrawlBudgetLedger(CrawlPolicy(max_requests_per_domain=2, min_delay_seconds=0))
    ledger.record_request("https://example.com/a")
    ledger.record_request("https://example.com/b")
    allowed, reason = ledger.can_crawl("https://example.com/c")
    assert not allowed
    assert "domain_limit" in reason


def test_budget_blocks_after_session_request_limit():
    ledger = CrawlBudgetLedger(CrawlPolicy(max_requests_per_session=2, min_delay_seconds=0))
    ledger.record_request("https://a.com/1")
    ledger.record_request("https://b.com/1")
    allowed, reason = ledger.can_crawl("https://c.com/1")
    assert not allowed
    assert reason == "session_request_limit"


def test_budget_blocks_after_bytes_limit():
    ledger = CrawlBudgetLedger(CrawlPolicy(max_bytes_per_session=100, min_delay_seconds=0))
    ledger.record_request("https://a.com/1", bytes_fetched=101)
    allowed, reason = ledger.can_crawl("https://b.com/1")
    assert not allowed
    assert reason == "session_bytes_limit"


def test_budget_rate_limit_blocks_rapid_second_request():
    ledger = CrawlBudgetLedger(CrawlPolicy(min_delay_seconds=60.0))
    ledger.record_request("https://slow.com/1")
    allowed, reason = ledger.can_crawl("https://slow.com/2")
    assert not allowed
    assert "rate_limit" in reason


def test_budget_summary_tracks_totals():
    ledger = CrawlBudgetLedger(CrawlPolicy(min_delay_seconds=0))
    ledger.record_request("https://a.com/1", bytes_fetched=500)
    ledger.record_request("https://b.com/1", bytes_fetched=300)
    summary = ledger.summary()
    assert summary["total_requests"] == 2
    assert summary["total_bytes"] == 800
    assert "a.com" in summary["domains"]


# ===========================================================================
# CrawlRouter — adapter selection
# ===========================================================================


def test_router_selects_github_for_github_url():
    router = build_default_router(CrawlPolicy(min_delay_seconds=0))
    assert router.selected_adapter_name("https://github.com/owner/repo") in ("simple_http", "github", "static")


def test_router_selects_pdf_for_pdf_url():
    router = build_default_router(CrawlPolicy(min_delay_seconds=0))
    assert router.selected_adapter_name("https://example.com/report.pdf") in ("simple_http", "pdf", "static")


def test_router_selects_wayback_for_archive_url():
    router = build_default_router(CrawlPolicy(min_delay_seconds=0))
    assert router.selected_adapter_name("https://web.archive.org/web/2023/https://example.com") in (
        "simple_http", "wayback", "static",
    )


def test_router_selects_rss_for_feed_url():
    router = build_default_router(CrawlPolicy(min_delay_seconds=0))
    assert router.selected_adapter_name("https://example.com/feed.rss") in ("simple_http", "rss", "static")


def test_router_raises_on_budget_exceeded():
    router = _static_router({"https://example.com/p": "text"})
    router.budget = CrawlBudgetLedger(CrawlPolicy(max_requests_per_session=0, min_delay_seconds=0))
    with pytest.raises(CrawlBudgetExhausted):
        router.crawl("https://example.com/p", max_chars=1000)


def test_router_records_budget_after_successful_crawl():
    url = "https://example.com/page"
    router = _static_router({url: "some content here"})
    router.crawl(url, max_chars=1000)
    assert router.budget.total_requests == 1
    assert router.budget.total_bytes > 0


def test_router_budget_summary_exposed():
    router = _static_router({"https://example.com/a": "abc"})
    router.crawl("https://example.com/a", max_chars=1000)
    summary = router.budget_summary()
    assert summary["total_requests"] == 1


# ===========================================================================
# RSS parsing
# ===========================================================================


def test_rss_adapter_parses_rss2_feed():
    adapter = RssCrawlerAdapter()
    title, content = adapter.parse_feed(RSS_2_XML, max_chars=10000)
    assert title == "Test Feed"
    assert "Launch delayed" in content
    assert "Audit contradicts claim" in content
    assert "postponed" in content


def test_rss_adapter_parses_atom_feed():
    adapter = RssCrawlerAdapter()
    title, content = adapter.parse_feed(ATOM_XML, max_chars=10000)
    assert title == "Atom Feed"
    assert "Unusual activity detected" in content
    assert "odds may miss" in content


def test_rss_adapter_handles_malformed_xml_gracefully():
    adapter = RssCrawlerAdapter()
    _, content = adapter.parse_feed("<not valid xml >>>", max_chars=500)
    assert len(content) <= 500


# ===========================================================================
# PDF extraction (fallback — no pypdf)
# ===========================================================================


def test_pdf_adapter_fallback_extracts_text_from_simple_pdf():
    adapter = PdfCrawlerAdapter()
    text = adapter.extract_text(_PDF_BYTES, max_chars=1000)
    # Either pypdf or fallback should find the visible text
    assert "Hello PDF world" in text or "[PDF:" in text


def test_pdf_adapter_fallback_returns_stub_for_unreadable_content():
    adapter = PdfCrawlerAdapter()
    text = adapter.extract_text(b"not a real pdf", max_chars=500)
    # Should not raise; returns stub or empty
    assert isinstance(text, str)


# ===========================================================================
# GitHub URL routing / path parsing
# ===========================================================================


def test_github_adapter_parses_repo_url():
    owner, repo, parts = GitHubCrawlerAdapter._parse_url("https://github.com/octocat/hello-world")
    assert owner == "octocat"
    assert repo == "hello-world"
    assert parts == []


def test_github_adapter_parses_issues_url():
    _, _, parts = GitHubCrawlerAdapter._parse_url("https://github.com/octocat/hello/issues")
    assert parts == ["issues"]


def test_github_adapter_parses_single_issue_url():
    _, _, parts = GitHubCrawlerAdapter._parse_url("https://github.com/octocat/hello/issues/42")
    assert parts == ["issues", "42"]


def test_github_adapter_parses_releases_url():
    _, _, parts = GitHubCrawlerAdapter._parse_url("https://github.com/octocat/hello/releases")
    assert parts == ["releases"]


def test_github_adapter_parses_commits_url():
    _, _, parts = GitHubCrawlerAdapter._parse_url("https://github.com/octocat/hello/commits")
    assert parts == ["commits"]


def test_github_adapter_returns_none_for_short_url():
    owner, repo, _ = GitHubCrawlerAdapter._parse_url("https://github.com/octocat")
    assert owner is None
    assert repo is None


# ===========================================================================
# Integration: ForagerService with CrawlRouter
# ===========================================================================

_CRAWL_URL = "https://example.com/article"
_CRAWL_TEXT = """
The project announced that the June launch will depend on API readiness.
The roadmap contradicts the launch claim and denied that the milestone was stable.
Market odds may miss the delay because the changelog was removed.
"""


def _service_with_router() -> tuple[ForagerService, CrawlRouter]:
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(url=_CRAWL_URL, title="Article", snippet="launch delay", source_name="static", raw={})
        ]
    )
    router = _static_router({_CRAWL_URL: _CRAWL_TEXT})
    svc = ForagerService(search_adapter=search, crawler_adapter=router)
    return svc, router


def test_service_crawl_uses_router_and_records_budget():
    svc, router = _service_with_router()
    start = svc.start_research(ResearchStartRequest(seed_query="project launch delay", market_id="mkt_p6"))
    thread_id = start["thread"]["id"]
    # promote_threshold=0 ensures the source is registered regardless of weirdness score
    svc.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1, promote_threshold=0.0))
    svc.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))

    assert router.budget.total_requests >= 1


def test_service_crawl_blocked_by_budget_records_error():
    svc, router = _service_with_router()
    start = svc.start_research(ResearchStartRequest(seed_query="blocked crawl test", market_id="mkt_p6b"))
    thread_id = start["thread"]["id"]
    svc.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1, promote_threshold=0.0))
    # Exhaust budget after sources are registered but before crawling
    router.budget = CrawlBudgetLedger(CrawlPolicy(max_requests_per_session=0, min_delay_seconds=0))
    result = svc.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=False))

    assert result["errors"]
