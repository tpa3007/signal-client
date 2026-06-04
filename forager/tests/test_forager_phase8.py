"""Phase 8 tests: Semantic Claim Graph.

All tests are network-free.
Tests cover: embedding adapter, cosine similarity, keyword classifier,
semantic graph building, contradiction clusters, claim lineage, and
service-level storage + SQLite persistence.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from forager.embedding import StaticEmbeddingAdapter, cosine_similarity
from forager.models import (
    Claim,
    ClaimType,
    CrawlSourceRequest,
    ResearchStartRequest,
    SearchBurstRequest,
    SemanticGraphRequest,
    SemanticRelationType,
    Stance,
)
from forager.crawl import CrawledDocument, StaticCrawlerAdapter
from forager.search import SearchResult, StaticSearchAdapter
from forager.semantic_graph import _classify_pair, build_semantic_claim_graph
from forager.service import ForagerService
from forager.memory.sqlite_store import SQLiteForagerStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_URL = "https://example.com/semantic-test"
_TEXT = """
The milestone was confirmed as stable by the independent audit team.
The roadmap denied that the milestone was stable and contradicts the official claim.
The latest update revised the timeline after new evidence emerged.
It is unclear whether the schedule will hold given recent developments.
"""


def _svc() -> ForagerService:
    search = StaticSearchAdapter(
        default_results=[
            SearchResult(url=_URL, title="Semantic test", snippet="audit milestone", source_name="static", raw={})
        ]
    )
    docs = {_URL: CrawledDocument(url=_URL, title="Audit Report", content_text=_TEXT)}
    return ForagerService(search_adapter=search, crawler_adapter=StaticCrawlerAdapter(docs))


def _setup_thread(svc: ForagerService) -> str:
    start = svc.start_research(ResearchStartRequest(seed_query="milestone audit contradictions", market_id="mkt_p8"))
    tid = start["thread"]["id"]
    svc.run_search_burst(tid, SearchBurstRequest(max_queries=1, results_per_query=1, promote_threshold=0.0))
    svc.crawl_sources(tid, CrawlSourceRequest(max_sources=1, extract=True))
    return tid


def _make_claim(thread_id: str, text: str, stance: Stance = Stance.NEUTRAL) -> Claim:
    return Claim(thread_id=thread_id, claim_text=text, claim_type=ClaimType.FACT, confidence=0.75, stance=stance)


# ===========================================================================
# Embedding adapter unit tests
# ===========================================================================


def test_embedding_same_text_has_similarity_one():
    adapter = StaticEmbeddingAdapter(dim=32)
    v = adapter.embed("the project milestone was stable")
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-9


def test_embedding_different_texts_have_lower_similarity():
    adapter = StaticEmbeddingAdapter(dim=32)
    v1 = adapter.embed("the project milestone was confirmed stable")
    v2 = adapter.embed("completely different words about food and cooking")
    assert cosine_similarity(v1, v2) < cosine_similarity(v1, v1)


def test_embedding_returns_normalized_vector():
    import math
    adapter = StaticEmbeddingAdapter(dim=32)
    v = adapter.embed("some test text here")
    mag = math.sqrt(sum(x * x for x in v))
    assert abs(mag - 1.0) < 1e-9


def test_cosine_similarity_empty_returns_zero():
    assert cosine_similarity([], []) == 0.0


def test_cosine_similarity_mismatched_returns_zero():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


# ===========================================================================
# Keyword classifier unit tests
# ===========================================================================


def test_classifier_detects_contradicts():
    rel_type, conf, _ = _classify_pair("the claim was denied", "it contradicts the report", 0.5)
    assert rel_type == SemanticRelationType.CONTRADICTS
    assert conf > 0.60


def test_classifier_detects_updates():
    rel_type, _, _ = _classify_pair("the latest update revised the timeline", "a new correction was issued", 0.5)
    assert rel_type == SemanticRelationType.UPDATES


def test_classifier_detects_weakens():
    rel_type, _, _ = _classify_pair("it is unclear whether this holds", "uncertainty remains", 0.5)
    assert rel_type == SemanticRelationType.WEAKENS


def test_classifier_detects_supports():
    rel_type, _, _ = _classify_pair("the audit confirmed the milestone", "verified by independent review", 0.5)
    assert rel_type == SemanticRelationType.SUPPORTS


def test_classifier_returns_unrelated_on_low_similarity():
    rel_type, _, _ = _classify_pair("milestone review", "weather forecast", 0.10)
    assert rel_type == SemanticRelationType.UNRELATED


# ===========================================================================
# build_semantic_claim_graph (pure function)
# ===========================================================================


def test_semantic_graph_empty_on_single_claim():
    adapter = StaticEmbeddingAdapter()
    tid = "thread_test"
    claims = [_make_claim(tid, "just one claim")]
    result = build_semantic_claim_graph(tid, claims, adapter, SemanticGraphRequest(similarity_threshold=0.0))
    assert result.total_pairs_evaluated == 0
    assert result.semantic_relations == []


def test_semantic_graph_finds_relations_between_similar_claims():
    adapter = StaticEmbeddingAdapter()
    tid = "thread_test"
    claims = [
        _make_claim(tid, "the milestone was denied and contradicts the report"),
        _make_claim(tid, "audit confirmed that milestone is stable"),
        _make_claim(tid, "latest update revised the timeline estimate"),
    ]
    result = build_semantic_claim_graph(tid, claims, adapter, SemanticGraphRequest(similarity_threshold=0.0))
    assert result.total_pairs_evaluated == 3  # C(3,2) = 3
    assert len(result.semantic_relations) > 0


def test_semantic_graph_creates_contradiction_cluster():
    adapter = StaticEmbeddingAdapter()
    tid = "thread_test"
    claims = [
        _make_claim(tid, "the project denied the milestone claim"),
        _make_claim(tid, "independent review contradicts the official statement"),
    ]
    result = build_semantic_claim_graph(tid, claims, adapter, SemanticGraphRequest(similarity_threshold=0.0))
    assert len(result.contradiction_clusters) == 1
    assert result.contradiction_clusters[0].cluster_score > 0


def test_semantic_graph_creates_lineage_from_updates():
    adapter = StaticEmbeddingAdapter()
    tid = "thread_test"
    claims = [
        _make_claim(tid, "the latest update revised the schedule"),
        _make_claim(tid, "a new correction was issued for the timeline"),
    ]
    result = build_semantic_claim_graph(tid, claims, adapter, SemanticGraphRequest(similarity_threshold=0.0))
    assert len(result.claim_lineage) > 0


# ===========================================================================
# Service-level build_semantic_claim_graph
# ===========================================================================


def test_service_semantic_graph_stores_relations():
    svc = _svc()
    tid = _setup_thread(svc)
    result = svc.build_semantic_claim_graph(tid, SemanticGraphRequest(similarity_threshold=0.0))
    stored = svc.store.thread_semantic_claim_relations(tid)
    assert len(stored) == len(result.semantic_relations)


def test_service_semantic_graph_stores_clusters():
    svc = _svc()
    tid = _setup_thread(svc)
    result = svc.build_semantic_claim_graph(tid, SemanticGraphRequest(similarity_threshold=0.0))
    clusters = svc.store.thread_contradiction_clusters(tid)
    assert len(clusters) == len(result.contradiction_clusters)


def test_service_semantic_graph_creates_anomaly_for_high_score_cluster():
    svc = _svc()
    tid = _setup_thread(svc)
    svc.build_semantic_claim_graph(tid, SemanticGraphRequest(similarity_threshold=0.0))
    anomalies = svc.store.thread_anomalies(tid)
    semantic_anomalies = [a for a in anomalies if a.anomaly_type == "semantic_contradiction_cluster"]
    # If there are contradiction clusters with score >= 0.60, anomalies should exist
    clusters = svc.store.thread_contradiction_clusters(tid)
    high_score = [c for c in clusters if c.cluster_score >= 0.60]
    assert len(semantic_anomalies) == len(high_score)


# ===========================================================================
# SQLite persistence
# ===========================================================================


def test_sqlite_semantic_relations_persist(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    tid = _setup_thread(svc)
    result = svc.build_semantic_claim_graph(tid, SemanticGraphRequest(similarity_threshold=0.0))
    assert result.total_pairs_evaluated >= 0

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    stored = db2.thread_semantic_claim_relations(tid)
    assert len(stored) == len(result.semantic_relations)


def test_sqlite_contradiction_clusters_persist(tmp_path: Path):
    db = SQLiteForagerStore(tmp_path / "forager.db")
    svc = _svc()
    svc.store = db
    tid = _setup_thread(svc)
    result = svc.build_semantic_claim_graph(tid, SemanticGraphRequest(similarity_threshold=0.0))

    db2 = SQLiteForagerStore(tmp_path / "forager.db")
    clusters = db2.thread_contradiction_clusters(tid)
    assert len(clusters) == len(result.contradiction_clusters)
