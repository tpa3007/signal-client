"""Phase 16 tests: Cognitive Ecology Layer.

The layer turns Forager from a linear research engine into a steering system:
gravity, heat, dream hypotheses, anti-consensus pressure, weather, and
meta-cognition. It must remain research-only and must not create evidence or
Signal records.
"""
from __future__ import annotations

from pathlib import Path

from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.memory.sqlite_store import SQLiteForagerStore
from forager.models import (
    CognitiveEcologyRequest,
    Document,
    Entity,
    EntityMention,
    EntityType,
    ResearchStartRequest,
    SearchBurstRequest,
    CrawlSourceRequest,
    ThreadLifeState,
)
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService


_URL = "https://example.com/phase16"
_TEXT = """
Project Aurora will launch in June according to official sources.
A local analyst reports delay risk and contradicts the launch consensus.
Aurora remains committed but hiring and roadmap language are changing.
"""


def _svc() -> ForagerService:
    search = StaticSearchAdapter(default_results=[SearchResult(url=_URL, title="Aurora launch shift", snippet="delay risk contradicts consensus", source_name="static", raw={})])
    crawler = StaticCrawlerAdapter({_URL: CrawledDocument(url=_URL, title="Aurora report", content_text=_TEXT, language="en")})
    return ForagerService(search_adapter=search, crawler_adapter=crawler)


def _researched_thread(svc: ForagerService, market_id: str = "mkt_phase16") -> str:
    start = svc.start_research(ResearchStartRequest(seed_query="Project Aurora launch delay", market_id=market_id))
    thread_id = start["thread"]["id"]
    svc.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1, promote_threshold=0.0))
    svc.crawl_sources(thread_id, CrawlSourceRequest(max_sources=1, extract=True))
    svc.build_packet(thread_id)
    return thread_id


def test_cognitive_ecology_snapshot_is_research_only() -> None:
    svc = _svc()
    thread_id = _researched_thread(svc)

    snapshot = svc.build_cognitive_ecology_snapshot(thread_id, CognitiveEcologyRequest())

    assert "does not create evidence" in snapshot.boundary
    assert snapshot.heat.heat_score >= 0.0
    assert len(snapshot.anti_consensus_reviews) == 5
    assert snapshot.dream_hypotheses
    assert "not evidence" in snapshot.dream_hypotheses[0].boundary
    assert snapshot.query_mutation_learning
    assert snapshot.next_actions


def test_high_weirdness_promotes_obsession_state() -> None:
    svc = _svc()
    thread_id = _researched_thread(svc)
    thread = svc.store.require_thread(thread_id)
    thread.weirdness_score = 0.91
    svc.store.add_thread(thread)

    snapshot = svc.build_cognitive_ecology_snapshot(thread_id)

    assert snapshot.thread_state.state == ThreadLifeState.OBSESSION
    assert "open_obsession_thread" in snapshot.next_actions


def test_cross_market_relation_from_shared_entity() -> None:
    svc = _svc()
    thread_a = _researched_thread(svc, "mkt_a")
    thread_b = _researched_thread(svc, "mkt_b")
    entity = Entity(name="Aurora", canonical_name="aurora", entity_type=EntityType.PROJECT)
    svc.store.add_entity(entity)
    doc_a = Document(source_id="source_manual_a", thread_id=thread_a, url="https://a.example", language="en")
    doc_b = Document(source_id="source_manual_b", thread_id=thread_b, url="https://b.example", language="en")
    svc.store.add_document(doc_a)
    svc.store.add_document(doc_b)
    svc.store.add_entity_mention(EntityMention(entity_id=entity.id, document_id=doc_a.id, thread_id=thread_a, mention_text="Aurora"))
    svc.store.add_entity_mention(EntityMention(entity_id=entity.id, document_id=doc_b.id, thread_id=thread_b, mention_text="Aurora"))

    snapshot = svc.build_cognitive_ecology_snapshot(thread_a, CognitiveEcologyRequest(include_cross_market=True))

    assert snapshot.cross_market_relations
    assert snapshot.cross_market_relations[0].market_b == "mkt_b"
    assert "aurora" in snapshot.cross_market_relations[0].shared_entities


def test_cognitive_ecology_persists_in_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "forager.db"
    db = SQLiteForagerStore(db_path)
    svc = _svc()
    svc.store = db
    thread_id = _researched_thread(svc)

    snapshot = svc.build_cognitive_ecology_snapshot(thread_id)

    db2 = SQLiteForagerStore(db_path)
    stored = db2.thread_cognitive_ecology_snapshots(thread_id)
    assert len(stored) == 1
    assert stored[0].id == snapshot.id
    assert stored[0].heat.heat_score == snapshot.heat.heat_score
