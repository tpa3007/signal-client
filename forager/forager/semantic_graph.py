"""Semantic claim graph builder for Forager Phase 8.

Pure functions — no store access, no side effects.
The service calls this module and stores the results.
"""
from __future__ import annotations

import itertools

from forager.embedding import EmbeddingAdapter, cosine_similarity
from forager.models import (
    ClaimLineageEntry,
    ContradictionCluster,
    SemanticClaimRelation,
    SemanticGraphRequest,
    SemanticGraphResult,
    SemanticRelationType,
)

# Keyword sets for lightweight relation classification.
# Checked against the combined lowercased text of both claims in a pair.
_CONTRADICTS = frozenset({
    "denied", "deny", "denies", "contradict", "contradicts", "contradicted",
    "false", "wrong", "refute", "refutes", "dispute", "disputes", "against",
    "incorrect", "misleading",
})
_UPDATES = frozenset({
    "update", "updated", "updates", "revised", "revision", "changed",
    "change", "new", "latest", "recently", "corrected", "correction",
    "retracted", "retraction",
})
_WEAKENS = frozenset({
    "unclear", "uncertain", "uncertainty", "doubt", "doubts", "possibly",
    "might", "maybe", "perhaps", "probably", "alleged", "unconfirmed",
    "speculation", "rumored",
})
_SUPPORTS = frozenset({
    "confirms", "confirmed", "confirm", "supports", "support", "supports",
    "agrees", "agreed", "agree", "verified", "verify", "backed", "validates",
    "validates", "corroborates",
})


def _classify_pair(
    text_a: str,
    text_b: str,
    similarity: float,
) -> tuple[SemanticRelationType, float, str]:
    """Return (relation_type, confidence, rationale) for a claim pair."""
    words = frozenset((text_a + " " + text_b).lower().split())

    if words & _CONTRADICTS:
        return SemanticRelationType.CONTRADICTS, 0.72, "contradiction keywords in claim pair"
    if words & _UPDATES:
        return SemanticRelationType.UPDATES, 0.65, "update/revision keywords in claim pair"
    if words & _WEAKENS:
        return SemanticRelationType.WEAKENS, 0.62, "uncertainty keywords in claim pair"
    if words & _SUPPORTS:
        return SemanticRelationType.SUPPORTS, 0.68, "supporting keywords in claim pair"
    if similarity >= 0.70:
        return SemanticRelationType.REFRAMES, 0.55, "high similarity without directional keywords"
    return SemanticRelationType.UNRELATED, max(0.0, 1.0 - similarity), "low similarity, no keywords"


def build_semantic_claim_graph(
    thread_id: str,
    claims: list,
    embedding_adapter: EmbeddingAdapter,
    request: SemanticGraphRequest,
) -> SemanticGraphResult:
    """Build semantic relations between claims using embeddings + keyword classification.

    Returns SemanticGraphResult with relations, contradiction clusters, and lineage.
    All objects carry fresh IDs — the caller is responsible for storing them.
    """
    if len(claims) < 2:
        return SemanticGraphResult(total_pairs_evaluated=0)

    embeddings = {c.id: embedding_adapter.embed(c.claim_text or "") for c in claims}

    relations: list[SemanticClaimRelation] = []
    pairs_evaluated = 0

    for c_a, c_b in itertools.combinations(claims, 2):
        sim = cosine_similarity(embeddings[c_a.id], embeddings[c_b.id])
        pairs_evaluated += 1

        if sim < request.similarity_threshold:
            continue

        rel_type, confidence, rationale = _classify_pair(
            c_a.claim_text or "",
            c_b.claim_text or "",
            sim,
        )

        if rel_type == SemanticRelationType.UNRELATED:
            continue
        if confidence < request.min_classifier_confidence:
            continue

        relations.append(SemanticClaimRelation(
            thread_id=thread_id,
            source_claim_id=c_a.id,
            target_claim_id=c_b.id,
            semantic_relation_type=rel_type,
            similarity_score=round(sim, 4),
            classifier_confidence=confidence,
            rationale=rationale,
        ))

    # Group all CONTRADICTS relations into one cluster per thread.
    # Phase 8 uses a single flat cluster; Phase 8+ can split by connected components.
    contradiction_rels = [r for r in relations if r.semantic_relation_type == SemanticRelationType.CONTRADICTS]
    clusters: list[ContradictionCluster] = []
    if contradiction_rels:
        claim_ids = list(
            {r.source_claim_id for r in contradiction_rels} | {r.target_claim_id for r in contradiction_rels}
        )
        cluster_score = round(
            sum(r.classifier_confidence for r in contradiction_rels) / len(contradiction_rels), 3
        )
        clusters.append(ContradictionCluster(
            thread_id=thread_id,
            claim_ids=claim_ids,
            relation_ids=[r.id for r in contradiction_rels],
            cluster_score=cluster_score,
            summary=f"{len(contradiction_rels)} semantic contradiction(s) among {len(claim_ids)} claim(s)",
        ))

    # Claim lineage: each UPDATES relation creates a lineage entry.
    lineage: list[ClaimLineageEntry] = [
        ClaimLineageEntry(
            thread_id=thread_id,
            claim_id=r.target_claim_id,
            predecessor_claim_id=r.source_claim_id,
            relation_type=SemanticRelationType.UPDATES,
        )
        for r in relations
        if r.semantic_relation_type == SemanticRelationType.UPDATES
    ]

    return SemanticGraphResult(
        semantic_relations=relations,
        contradiction_clusters=clusters,
        claim_lineage=lineage,
        total_pairs_evaluated=pairs_evaluated,
    )
