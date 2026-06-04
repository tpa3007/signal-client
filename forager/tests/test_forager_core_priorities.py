"""Core-priority tests: pragmatic recursive loop and minimal attention."""
from __future__ import annotations

from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.models import (
    Claim,
    CoreResearchLoopRequest,
    MinimalAttentionRequest,
    ResearchStartRequest,
    SearchBurstRequest,
    Stance,
    ThreadStatus,
)
from forager.search import CompositeSearchAdapter, SearchResult, StaticSearchAdapter, create_default_search_adapter
from forager.service import ForagerService


_URL = "https://example.com/core-loop"
_TEXT = """
Aurora will launch in June according to official project messaging.
A local source contradicts the timeline and reports delay pressure.
The roadmap wording weakened from will launch to continues development.
"""


def _svc() -> ForagerService:
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(
                url=_URL,
                title="Aurora roadmap contradiction",
                snippet="local source contradicts launch timeline",
                source_name="static",
                raw={},
            )
        ]
    )
    crawler = StaticCrawlerAdapter(
        {
            _URL: CrawledDocument(
                url=_URL,
                title="Aurora local report",
                content_text=_TEXT,
                language="en",
            )
        }
    )
    return ForagerService(search_adapter=search, crawler_adapter=crawler)


def test_core_research_loop_builds_packet_and_bridge() -> None:
    svc = _svc()

    result = svc.run_core_research_loop(
        CoreResearchLoopRequest(
            seed_query="Aurora roadmap launch",
            market_id="mkt_core_loop",
            recursive_rounds=1,
            max_queries_per_round=1,
            results_per_query=1,
            max_sources_per_round=2,
            include_local_language=True,
            run_semantic_graph=True,
            build_evidence_drafts=True,
        )
    )

    assert "Forager discovers" in result.boundary
    assert result.packet_id is not None
    assert result.signal_bridge is not None
    assert result.signal_bridge.forager_packet_id == result.packet_id
    assert result.counts["documents"] >= 1
    assert result.counts["claims"] >= 1
    assert result.counts["entities"] >= 1
    assert any(step["step"] == "recursive_search" for step in result.steps)
    assert "handoff_packet_to_signal" in result.next_actions


def test_minimal_attention_prioritizes_hot_unresolved_thread() -> None:
    svc = _svc()
    hot = svc.start_research(ResearchStartRequest(seed_query="hot contradiction", market_id="hot"))["thread"]["id"]
    cold = svc.start_research(ResearchStartRequest(seed_query="cold stale", market_id="cold"))["thread"]["id"]
    hot_thread = svc.store.require_thread(hot)
    hot_thread.weirdness_score = 0.95
    hot_thread.status = ThreadStatus.INVESTIGATING
    svc.store.add_thread(hot_thread)
    svc.store.add_claim(Claim(thread_id=hot, claim_text="Local source contradicts launch timeline", stance=Stance.CONTRADICTS))

    state = svc.build_minimal_attention_state(MinimalAttentionRequest(obsession_threshold=0.50))

    assert "simple prioritization" in state.boundary
    assert state.profiles[0].thread_id == hot
    assert state.profiles[0].obsession_probability >= 0.50
    assert "allocate_more_budget" in state.profiles[0].actions
    assert set(state.attention_distribution).issuperset({hot, cold})




def test_default_search_adapter_has_no_key_fallback(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    adapter = create_default_search_adapter()
    results = adapter.search("Will Russia enter Orikhiv by July 31 ISW DeepStateMap", count=5)

    assert not any(type(child).__name__ == "NullSearchAdapter" for child in adapter.adapters)
    assert any(result.source_name == "official_seed" for result in results)
    assert any("deepstatemap" in result.url.lower() or "storymaps.arcgis.com" in result.url.lower() for result in results)


def test_composite_search_adapter_continues_after_provider_failure() -> None:
    class BrokenSearchAdapter:
        source_name = "broken"

        def search(self, query: str, *, count: int) -> list[SearchResult]:
            raise RuntimeError("provider down")

    adapter = CompositeSearchAdapter(
        [
            BrokenSearchAdapter(),
            StaticSearchAdapter(
                default_results=[
                    SearchResult(url="https://example.com/source", title="Recovered source", source_name="static")
                ]
            ),
        ]
    )

    results = adapter.search("anything", count=3)

    assert [result.url for result in results] == ["https://example.com/source"]


def test_search_burst_promotes_relevant_official_source_even_when_not_weird() -> None:
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(
                url="https://elections.wi.gov/",
                title="Wisconsin elections governor primary",
                snippet="Wisconsin governor primary elections official information",
                source_name="static",
            )
        ]
    )
    svc = ForagerService(search_adapter=search)
    thread_id = svc.start_research(
        ResearchStartRequest(seed_query="Wisconsin elections governor primary", market_id="mkt_relevance")
    )["thread"]["id"]

    burst = svc.run_search_burst(
        thread_id,
        SearchBurstRequest(max_queries=1, results_per_query=1, promote_threshold=0.75),
    )

    assert burst["raw_items_written"] == 1
    assert burst["promoted_sources"] == 1

