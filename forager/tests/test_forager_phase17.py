"""Phase 17 tests: attention ecology, obsession dynamics, pre-emergence intelligence."""
from __future__ import annotations

from pathlib import Path

from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.memory.sqlite_store import SQLiteForagerStore
from forager.models import (
    AttentionOrchestrationRequest,
    CrawlSourceRequest,
    Document,
    Entity,
    EntityMention,
    EntityType,
    ResearchStartRequest,
    SearchBurstRequest,
)
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService


_URL = "https://example.com/phase17"
_TEXT = """
Aurora will launch soon, but local sources report delay risk.
The roadmap language is changing and analysts contradict the official timeline.
Hiring patterns suggest infrastructure pressure before mainstream coverage.
"""


def _svc() -> ForagerService:
    search = StaticSearchAdapter(default_results=[SearchResult(url=_URL, title="Aurora pressure", snippet="delay risk infrastructure pressure", source_name="static", raw={})])
    crawler = StaticCrawlerAdapter({_URL: CrawledDocument(url=_URL, title="Aurora pressure report", content_text=_TEXT, language="en")})
    return ForagerService(search_adapter=search, crawler_adapter=crawler)


def _thread(svc: ForagerService, market_id: str, seed: str = "Aurora launch delay") -> str:
    start = svc.start_research(ResearchStartRequest(seed_query=seed, market_id=market_id))
    tid = start["thread"]["id"]
    svc.run_search_burst(tid, SearchBurstRequest(max_queries=1, results_per_query=1, promote_threshold=0.0))
    svc.crawl_sources(tid, CrawlSourceRequest(max_sources=1, extract=True))
    svc.build_packet(tid)
    return tid


def _attach_shared_entity(svc: ForagerService, thread_id: str, name: str = "Aurora") -> None:
    entity = Entity(name=name, canonical_name=name.lower(), entity_type=EntityType.PROJECT)
    svc.store.add_entity(entity)
    doc = Document(source_id=f"source_{thread_id}", thread_id=thread_id, url=f"https://{thread_id}.example", language="en")
    svc.store.add_document(doc)
    svc.store.add_entity_mention(EntityMention(entity_id=entity.id, document_id=doc.id, thread_id=thread_id, mention_text=name))


def test_attention_orchestration_distributes_budget() -> None:
    svc = _svc()
    _thread(svc, "mkt_a")
    _thread(svc, "mkt_b", "Aurora supply chain pressure")

    plan = svc.build_attention_orchestration_plan(AttentionOrchestrationRequest(total_attention_budget=1.0))

    assert "reallocates research attention" in plan.boundary
    assert len(plan.thread_profiles) == 2
    assert plan.attention_state.active_threads
    assert 0.99 <= sum(plan.attention_state.attention_distribution.values()) <= 1.01
    assert plan.ecology_feed.items


def test_obsession_propagates_to_related_thread() -> None:
    svc = _svc()
    source = _thread(svc, "mkt_source")
    target = _thread(svc, "mkt_target", "Aurora energy grid pressure")
    _attach_shared_entity(svc, source)
    _attach_shared_entity(svc, target)
    thread = svc.store.require_thread(source)
    thread.weirdness_score = 0.95
    svc.store.add_thread(thread)

    plan = svc.build_attention_orchestration_plan(AttentionOrchestrationRequest(obsession_threshold=0.50))

    assert plan.obsession_propagations
    assert any(p.source_thread_id == source and p.target_thread_id == target for p in plan.obsession_propagations)


def test_immune_response_cools_low_evidence_recursion() -> None:
    svc = _svc()
    _thread(svc, "mkt_immune")

    plan = svc.build_attention_orchestration_plan(AttentionOrchestrationRequest(immune_threshold=0.20))

    assert plan.immune_responses
    assert any("cap_confidence" in r.cooling_actions or "block_signal_import_until_sources_exist" in r.cooling_actions for r in plan.immune_responses)


def test_attention_orchestration_persists_in_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "forager.db"
    db = SQLiteForagerStore(db_path)
    svc = _svc()
    svc.store = db
    _thread(svc, "mkt_sqlite_attention")

    plan = svc.build_attention_orchestration_plan()

    db2 = SQLiteForagerStore(db_path)
    stored = db2.list_attention_orchestration_plans()
    assert len(stored) == 1
    assert stored[0].id == plan.id
    assert stored[0].attention_state.active_threads == plan.attention_state.active_threads
