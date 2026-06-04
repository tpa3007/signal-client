from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.memory import SQLiteForagerStore
from forager.models import CrawlSourceRequest, ResearchStartRequest, SearchBurstRequest
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService

URL = "https://github.com/example/hidden-project/issues/17"
DOC_TEXT = """
Hidden Project maintainers announced that the June launch will depend on API readiness.
The deleted roadmap contradicts the public story and denied that the milestone was stable.
Kim Labs and Example Foundation discussed the release in a GitHub issue before the market noticed it.
Polymarket odds may miss the delay because the changelog was removed.
"""


def _phase2_service(store=None):
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(
                url=URL,
                title="Deleted GitHub roadmap contradicts launch story",
                snippet="maintainer removed milestone after unusual timing",
                source_name="static",
                raw={"rank": 1},
            )
        ]
    )
    crawler = StaticCrawlerAdapter(
        {
            URL: CrawledDocument(
                url=URL,
                title="Hidden Project issue 17",
                content_text=DOC_TEXT,
                language="en",
                published_at="2026-05-20",
            )
        }
    )
    return ForagerService(store=store, search_adapter=search, crawler_adapter=crawler)


def test_crawl_sources_extracts_documents_claims_entities_and_anomalies():
    service = _phase2_service()
    start = service.start_research(ResearchStartRequest(seed_query="hidden project launch market", market_id="market_phase2"))
    thread_id = start["thread"]["id"]
    service.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1))

    crawl = service.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))
    state = service.get_thread(thread_id)

    assert crawl["documents_written"] == 1
    assert crawl["claims_written"] >= 2
    assert crawl["entities_written"] >= 3
    assert state["documents"][0]["summary"]
    assert any(claim["stance"] == "contradicts" for claim in state["claims"])
    assert any(anomaly["anomaly_type"] == "document_contradiction_claims" for anomaly in state["anomalies"])


def test_sqlite_store_persists_extracted_documents_claims_and_entities(tmp_path):
    db_path = tmp_path / "forager_phase2.sqlite3"
    service = _phase2_service(SQLiteForagerStore(db_path))
    start = service.start_research(ResearchStartRequest(seed_query="hidden project launch market", market_id="market_phase2_sqlite"))
    thread_id = start["thread"]["id"]
    service.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1))
    service.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))

    reopened = SQLiteForagerStore(db_path)

    assert len(reopened.thread_documents(thread_id)) == 1
    assert len(reopened.thread_claims(thread_id)) >= 2
    assert len(reopened.thread_entities(thread_id)) >= 3
    assert len(reopened.thread_entity_mentions(thread_id)) >= 3


def test_signal_bridge_blocks_when_documents_not_crawled_then_clears_after_crawl():
    service = _phase2_service()
    start = service.start_research(ResearchStartRequest(seed_query="hidden project launch market", market_id="market_phase2_bridge"))
    thread_id = start["thread"]["id"]
    service.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1))
    service.build_packet(thread_id)

    before = service.export_signal_bridge_packet(thread_id)
    assert "documents_not_crawled" in before.blockers

    service.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))
    service.build_packet(thread_id)
    after = service.export_signal_bridge_packet(thread_id)

    assert "documents_not_crawled" not in after.blockers
    assert after.source_items
