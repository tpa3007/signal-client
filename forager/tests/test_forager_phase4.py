from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.memory import SQLiteForagerStore
from forager.models import (
    CrawlSourceRequest,
    RecursiveSearchRequest,
    ResearchStartRequest,
    SearchBurstRequest,
    TranslationQueueRequest,
)
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService

URL = "https://local.example.kr/archive/hidden-project"
DOC_TEXT = """
Hidden Project maintainers announced that the June launch will depend on API readiness.
Hidden Project roadmap contradicts the launch claim and denied that the milestone was stable.
Kim Labs and Example Foundation discussed the release before the market noticed it.
Polymarket odds may miss the delay because the changelog was removed.
"""


def _phase4_service(store=None, language="ko"):
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(
                url=URL,
                title="Local archive contradicts launch story",
                snippet="removed milestone, local-language archive, unusual timing",
                source_name="static",
                raw={"rank": 1},
            ),
            SearchResult(
                url="https://github.com/example/hidden-project/issues/99",
                title="Graph expansion issue mentions Kim Labs",
                snippet="follow-up issue from entity graph expansion",
                source_name="static",
                raw={"rank": 2},
            ),
        ]
    )
    crawler = StaticCrawlerAdapter(
        {
            URL: CrawledDocument(
                url=URL,
                title="Hidden Project Korean archive",
                content_text=DOC_TEXT,
                language=language,
                published_at="2026-05-20",
            )
        }
    )
    return ForagerService(store=store, search_adapter=search, crawler_adapter=crawler)


def _prepared_thread(service: ForagerService) -> str:
    start = service.start_research(ResearchStartRequest(seed_query="hidden project launch market", market_id="market_phase4"))
    thread_id = start["thread"]["id"]
    service.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1))
    service.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))
    service.expand_graph(thread_id)
    return thread_id


def test_recursive_graph_search_runs_limited_expansion_queries():
    service = _phase4_service()
    thread_id = _prepared_thread(service)

    result = service.recursive_graph_search(
        thread_id,
        RecursiveSearchRequest(max_queries=3, results_per_query=2, max_entities=3, mutations_per_entity=2),
    )
    state = service.get_thread(thread_id)

    assert result.queries_attempted <= 3
    assert result.queries_attempted > 0
    assert result.raw_items_written >= 2
    assert state["raw_items"]
    assert len(state["raw_items"]) >= result.raw_items_written


def test_translation_queue_collects_non_english_documents_once():
    service = _phase4_service(language="ko")
    thread_id = _prepared_thread(service)

    first = service.build_translation_queue(thread_id, TranslationQueueRequest(target_language="en"))
    second = service.build_translation_queue(thread_id, TranslationQueueRequest(target_language="en"))
    state = service.get_thread(thread_id)

    assert len(first.queued_items) == 1
    assert len(second.queued_items) == 1
    assert first.queued_items[0].id == second.queued_items[0].id
    assert state["translation_queue"][0]["language"] == "ko"
    assert any(anomaly["anomaly_type"] == "translation_queue_open" for anomaly in state["anomalies"])


def test_translation_queue_skips_english_documents():
    service = _phase4_service(language="en")
    thread_id = _prepared_thread(service)

    result = service.build_translation_queue(thread_id, TranslationQueueRequest(target_language="en"))

    assert result.queued_items == []
    assert result.skipped_document_ids


def test_sqlite_persists_translation_queue(tmp_path):
    db_path = tmp_path / "forager_phase4.sqlite3"
    service = _phase4_service(SQLiteForagerStore(db_path), language="ko")
    thread_id = _prepared_thread(service)
    queued = service.build_translation_queue(thread_id, TranslationQueueRequest(target_language="en"))

    reopened = SQLiteForagerStore(db_path)

    assert len(reopened.thread_translation_queue(thread_id)) == 1
    assert reopened.thread_translation_queue(thread_id)[0].id == queued.queued_items[0].id
