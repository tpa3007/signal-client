from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.memory import SQLiteForagerStore
from forager.models import CrawlSourceRequest, GraphExpansionRequest, LocalLanguageRequest, ResearchStartRequest, SearchBurstRequest
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService

URL = "https://github.com/example/hidden-project/issues/42"
DOC_TEXT = """
Hidden Project maintainers announced that the June launch will depend on API readiness.
Hidden Project roadmap contradicts the Hidden Project launch claim and denied that the milestone was stable.
Kim Labs and Example Foundation discussed the release in a GitHub issue before the market noticed it.
Polymarket odds may miss the delay because the changelog was removed.
"""


def _phase3_service(store=None, language="ko"):
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
                title="Hidden Project issue 42",
                content_text=DOC_TEXT,
                language=language,
                published_at="2026-05-20",
            )
        }
    )
    return ForagerService(store=store, search_adapter=search, crawler_adapter=crawler)


def _prepared_thread(service: ForagerService) -> str:
    start = service.start_research(ResearchStartRequest(seed_query="hidden project launch market", market_id="market_phase3"))
    thread_id = start["thread"]["id"]
    service.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1))
    service.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))
    return thread_id


def test_expand_graph_builds_entity_and_claim_relations():
    service = _phase3_service()
    thread_id = _prepared_thread(service)

    graph = service.expand_graph(thread_id, GraphExpansionRequest(max_entities=4, mutations_per_entity=2))
    state = service.get_thread(thread_id)

    assert graph.entity_relations
    assert graph.claim_relations
    assert graph.expansion_queries
    assert state["entity_relations"]
    assert state["claim_relations"]
    assert any(relation.relation_type == "contradicts" for relation in graph.claim_relations)
    assert any(anomaly["anomaly_type"] == "claim_contradiction_graph" for anomaly in state["anomalies"])


def test_local_language_profile_flags_non_english_research_layer():
    service = _phase3_service(language="ko")
    thread_id = _prepared_thread(service)

    profile = service.build_local_language_profile(thread_id, LocalLanguageRequest(target_languages=["ko"]))
    state = service.get_thread(thread_id)

    assert profile.needs_translation is True
    assert "ko" in profile.detected_languages
    assert profile.suggested_queries
    assert state["local_language_profile"]["id"] == profile.id
    assert any(anomaly["anomaly_type"] == "local_language_research_required" for anomaly in state["anomalies"])


def test_sqlite_persists_graph_and_language_profile(tmp_path):
    db_path = tmp_path / "forager_phase3.sqlite3"
    service = _phase3_service(SQLiteForagerStore(db_path), language="ko")
    thread_id = _prepared_thread(service)
    graph = service.expand_graph(thread_id, GraphExpansionRequest(max_entities=4, mutations_per_entity=2))
    profile = service.build_local_language_profile(thread_id, LocalLanguageRequest(target_languages=["ko"]))

    reopened = SQLiteForagerStore(db_path)

    assert len(reopened.thread_entity_relations(thread_id)) == len(graph.entity_relations)
    assert len(reopened.thread_claim_relations(thread_id)) == len(graph.claim_relations)
    assert reopened.latest_local_language_profile(thread_id).id == profile.id
