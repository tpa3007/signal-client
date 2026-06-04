"""Graph expansion primitives for Forager Phase 3."""
from __future__ import annotations

import itertools
import re
from collections import defaultdict

from forager.models import Claim, ClaimRelation, Entity, EntityMention, EntityRelation, RelationType
from forager.search.query_mutation import mutate_query

STOPWORDS = {
    "about", "after", "again", "because", "before", "could", "delay", "false", "from", "have",
    "into", "launch", "market", "maybe", "might", "polymarket", "price", "public", "should", "source",
    "their", "there", "these", "this", "through", "will", "with", "would",
}


def build_entity_relations(*, thread_id: str, mentions: list[EntityMention], min_strength: float = 0.20) -> list[EntityRelation]:
    by_doc: dict[str, list[EntityMention]] = defaultdict(list)
    for mention in mentions:
        by_doc[mention.document_id].append(mention)

    pair_docs: dict[tuple[str, str], set[str]] = defaultdict(set)
    pair_mentions: dict[tuple[str, str], list[str]] = defaultdict(list)
    for document_id, doc_mentions in by_doc.items():
        entity_ids = list(dict.fromkeys(mention.entity_id for mention in doc_mentions))
        for left, right in itertools.combinations(sorted(entity_ids), 2):
            pair = (left, right)
            pair_docs[pair].add(document_id)
            pair_mentions[pair].extend(mention.id for mention in doc_mentions if mention.entity_id in pair)

    relations: list[EntityRelation] = []
    for (left, right), document_ids in pair_docs.items():
        strength = min(1.0, 0.20 + len(document_ids) * 0.20)
        if strength < min_strength:
            continue
        relations.append(
            EntityRelation(
                thread_id=thread_id,
                source_entity_id=left,
                target_entity_id=right,
                relation_type=RelationType.CO_MENTIONED,
                strength=strength,
                evidence={
                    "document_ids": sorted(document_ids),
                    "mention_ids": pair_mentions[(left, right)][:20],
                },
            )
        )
    return relations


def build_claim_relations(*, thread_id: str, claims: list[Claim]) -> list[ClaimRelation]:
    relations: list[ClaimRelation] = []
    for left, right in itertools.combinations(claims, 2):
        overlap = _token_overlap(left.normalized_claim or left.claim_text, right.normalized_claim or right.claim_text)
        if overlap < 0.18:
            continue
        relation_type = RelationType.RELATED_TO
        rationale = "claims share topic language"
        if left.stance.value == "contradicts" or right.stance.value == "contradicts":
            relation_type = RelationType.CONTRADICTS
            rationale = "one claim is contradiction-oriented and claims share topic language"
        elif left.claim_type == right.claim_type:
            relation_type = RelationType.SUPPORTS
            rationale = "claims share type and topic language"
        relations.append(
            ClaimRelation(
                thread_id=thread_id,
                source_claim_id=left.id,
                target_claim_id=right.id,
                relation_type=relation_type,
                strength=min(1.0, overlap + 0.20),
                rationale=rationale,
            )
        )
    return relations


def expansion_queries_from_entities(entities: list[Entity], *, max_entities: int, mutations_per_entity: int) -> list[str]:
    queries: list[str] = []
    for entity in entities[:max_entities]:
        seed = entity.name
        for mutation in mutate_query(seed, max_queries=mutations_per_entity):
            queries.append(mutation.query)
    return list(dict.fromkeys(queries))


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]{4,}", text.lower()) if token not in STOPWORDS}
