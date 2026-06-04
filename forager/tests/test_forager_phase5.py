from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.memory import SQLiteForagerStore
from forager.models import (
    CrawlSourceRequest,
    ResearchStartRequest,
    SearchBurstRequest,
    TranslationExecutionRequest,
    TranslationQueueRequest,
)
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService
from forager.translation_adapters import FailingTranslationAdapter, StaticTranslationAdapter

URL = "https://local.example.kr/archive/hidden-project"
DOC_TEXT = """
Hidden Project maintainers announced that the June launch will depend on API readiness.
Hidden Project roadmap contradicts the launch claim and denied that the milestone was stable.
Kim Labs and Example Foundation discussed the release before the market noticed it.
Polymarket odds may miss the delay because the changelog was removed.
"""


def _phase5_service(store=None, language="ko", translation_adapter=None):
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(
                url=URL,
                title="Local archive contradicts launch story",
                snippet="removed milestone, local-language archive, unusual timing",
                source_name="static",
                raw={"rank": 1},
            )
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
    return ForagerService(
        store=store,
        search_adapter=search,
        crawler_adapter=crawler,
        translation_adapter=translation_adapter or StaticTranslationAdapter(),
    )


def _prepared_thread(service: ForagerService) -> str:
    start = service.start_research(
        ResearchStartRequest(seed_query="hidden project launch market", market_id="market_phase5")
    )
    thread_id = start["thread"]["id"]
    service.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1))
    service.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))
    service.build_translation_queue(thread_id, TranslationQueueRequest(target_language="en"))
    return thread_id


def test_execute_translations_creates_translated_document():
    service = _phase5_service()
    thread_id = _prepared_thread(service)

    result = service.execute_translations(thread_id, TranslationExecutionRequest())
    state = service.get_thread(thread_id)

    assert result.translated == 1
    assert result.failed == 0
    assert len(result.translated_document_ids) == 1
    assert state["translated_documents"]
    assert state["translated_documents"][0]["source_language"] == "ko"
    assert state["translated_documents"][0]["translation_quality"] == 0.85
    assert state["translated_documents"][0]["translated_by"] == "static"
    assert state["translated_documents"][0]["original_document_id"]


def test_execute_translations_extracts_claims_and_entities_from_translated_text():
    service = _phase5_service()
    thread_id = _prepared_thread(service)

    result = service.execute_translations(thread_id, TranslationExecutionRequest())

    assert result.claims_extracted > 0
    assert result.entities_extracted > 0


def test_execute_translations_creates_claim_translation_links():
    service = _phase5_service()
    thread_id = _prepared_thread(service)

    result = service.execute_translations(thread_id, TranslationExecutionRequest())
    state = service.get_thread(thread_id)

    assert result.claims_extracted > 0
    assert state["claim_translation_links"]
    link = state["claim_translation_links"][0]
    assert link["original_document_id"]
    assert link["translated_document_id"] == result.translated_document_ids[0]
    assert link["source_language"] == "ko"
    assert link["translation_quality"] == 0.85
    assert len(state["claim_translation_links"]) == result.claims_extracted


def test_execute_translations_marks_queue_item_done():
    service = _phase5_service()
    thread_id = _prepared_thread(service)

    service.execute_translations(thread_id, TranslationExecutionRequest())
    state = service.get_thread(thread_id)

    assert state["translation_queue"][0]["status"] == "done"


def test_execute_translations_is_idempotent():
    service = _phase5_service()
    thread_id = _prepared_thread(service)

    first = service.execute_translations(thread_id, TranslationExecutionRequest())
    second = service.execute_translations(thread_id, TranslationExecutionRequest())

    assert first.translated == 1
    assert second.translated == 0


def test_execute_translations_creates_blocker_on_failure():
    service = _phase5_service(translation_adapter=FailingTranslationAdapter())
    thread_id = _prepared_thread(service)

    result = service.execute_translations(thread_id, TranslationExecutionRequest())
    state = service.get_thread(thread_id)

    assert result.failed == 1
    assert result.translated == 0
    assert result.errors
    assert any(a["anomaly_type"] == "translation_failed" for a in state["anomalies"])
    assert state["translation_queue"][0]["status"] == "blocked"


def test_execute_translations_skips_low_quality():
    service = _phase5_service(translation_adapter=StaticTranslationAdapter(quality=0.10))
    thread_id = _prepared_thread(service)

    result = service.execute_translations(thread_id, TranslationExecutionRequest(min_quality_threshold=0.40))
    state = service.get_thread(thread_id)

    assert result.low_quality == 1
    assert result.translated == 0
    assert not state["translated_documents"]
    assert any(a["anomaly_type"] == "translation_low_quality" for a in state["anomalies"])
    assert state["translation_queue"][0]["status"] == "blocked"


def test_sqlite_persists_translated_documents(tmp_path):
    db_path = tmp_path / "forager_phase5.sqlite3"
    service = _phase5_service(SQLiteForagerStore(db_path))
    thread_id = _prepared_thread(service)

    result = service.execute_translations(thread_id, TranslationExecutionRequest())
    reopened = SQLiteForagerStore(db_path)

    assert len(reopened.thread_translated_documents(thread_id)) == 1
    assert reopened.thread_translated_documents(thread_id)[0].id == result.translated_document_ids[0]
    assert reopened.thread_translated_documents(thread_id)[0].source_language == "ko"


def test_sqlite_persists_claim_translation_links(tmp_path):
    db_path = tmp_path / "forager_phase5b.sqlite3"
    service = _phase5_service(SQLiteForagerStore(db_path))
    thread_id = _prepared_thread(service)

    result = service.execute_translations(thread_id, TranslationExecutionRequest())
    reopened = SQLiteForagerStore(db_path)

    links = reopened.thread_claim_translation_links(thread_id)
    assert len(links) == result.claims_extracted
    assert links[0].translated_document_id == result.translated_document_ids[0]


def test_sqlite_persists_updated_queue_status(tmp_path):
    db_path = tmp_path / "forager_phase5c.sqlite3"
    service = _phase5_service(SQLiteForagerStore(db_path))
    thread_id = _prepared_thread(service)

    service.execute_translations(thread_id, TranslationExecutionRequest())
    reopened = SQLiteForagerStore(db_path)

    queue = reopened.thread_translation_queue(thread_id)
    assert queue[0].status.value == "done"
