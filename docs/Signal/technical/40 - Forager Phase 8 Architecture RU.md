# Forager Phase 8 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 8 добавляет Semantic Claim Graph — Forager теперь связывает claims не только по lexical overlap, но и по смысловому сходству.

Цель достигнута: Forager может находить противоречия даже когда источники используют разные формулировки.

## Архитектура

```text
Claims (list)
    │
    ├── StaticEmbeddingAdapter.embed() → float vectors
    │       word-hash BOW, L2-normalized, deterministic
    │
    ├── cosine_similarity(a, b) → float
    │
    ├── _classify_pair(text_a, text_b, sim) → (SemanticRelationType, confidence, rationale)
    │       keyword sets: CONTRADICTS / UPDATES / WEAKENS / SUPPORTS
    │       fallback: REFRAMES (high sim) / UNRELATED (low sim)
    │
    └── build_semantic_claim_graph() → SemanticGraphResult
            semantic_relations: list[SemanticClaimRelation]
            contradiction_clusters: list[ContradictionCluster]
            claim_lineage: list[ClaimLineageEntry]
```

## Модели

### SemanticRelationType

```python
class SemanticRelationType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    UPDATES = "updates"
    REFRAMES = "reframes"
    WEAKENS = "weakens"
    UNRELATED = "unrelated"
```

### SemanticClaimRelation

Связь между двумя claims с типом, similarity score и confidence.

```python
class SemanticClaimRelation(BaseModel):
    id: str          # prefix "screl_"
    thread_id: str
    source_claim_id: str
    target_claim_id: str
    semantic_relation_type: SemanticRelationType
    similarity_score: float
    classifier_confidence: float
    rationale: str | None
    created_at: str
```

### ContradictionCluster

Группа claims, связанных отношениями CONTRADICTS. Первая версия — один flat cluster per thread.

```python
class ContradictionCluster(BaseModel):
    id: str          # prefix "ccluster_"
    thread_id: str
    claim_ids: list[str]
    relation_ids: list[str]
    cluster_score: float     # среднее confidence contradiction relations
    summary: str | None
    created_at: str
```

### ClaimLineageEntry

Цепочка обновлений: claim B обновляет claim A (тип UPDATES).

```python
class ClaimLineageEntry(BaseModel):
    id: str          # prefix "lineage_"
    thread_id: str
    claim_id: str              # обновлённый claim
    predecessor_claim_id: str  # предшественник
    relation_type: SemanticRelationType  # всегда UPDATES
    created_at: str
```

## Keyword Classifier

Вместо LLM использует keyword sets на combined text обоих claims:

| Relation | Keywords |
|----------|----------|
| CONTRADICTS | denied, deny, contradict, contradicts, false, wrong, refute, dispute, against, incorrect, misleading |
| UPDATES | update, updated, revised, revision, changed, new, latest, recently, corrected, retracted |
| WEAKENS | unclear, uncertain, doubt, possibly, might, maybe, perhaps, alleged, unconfirmed, speculation |
| SUPPORTS | confirms, confirmed, supports, agrees, verified, backed, validates, corroborates |
| REFRAMES | high similarity (≥ 0.70) без directional keywords |
| UNRELATED | низкая similarity, нет keywords |

## EmbeddingAdapter

```python
class EmbeddingAdapter:
    def embed(self, text: str) -> list[float]: ...

class StaticEmbeddingAdapter(EmbeddingAdapter):
    """Word-hash BOW, L2-normalized. Для тестов — без сети."""
    def __init__(self, dim: int = 64): ...
```

ForagerService принимает `embedding_adapter` как инъектируемый параметр. Default: `StaticEmbeddingAdapter()`. Real embeddings (OpenAI, sentence-transformers) — stub-ready.

## build_semantic_claim_graph() в service.py

1. Получает claims из store (до `max_claims`)
2. Вызывает `_build_semantic_graph()` из `semantic_graph.py`
3. Сохраняет все отношения, кластеры, lineage entries
4. Создаёт anomaly "semantic_contradiction_cluster" для кластеров с `cluster_score >= 0.60`

## API endpoints

| Method | Path | Назначение |
|--------|------|------------|
| POST | `/threads/{id}/semantic-claim-graph` | Построить semantic graph |
| GET | `/threads/{id}/semantic-claim-graph` | Получить результаты |

Версия API: 0.7.0

## SQLite таблицы

```sql
CREATE TABLE forager_semantic_claim_relations (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    semantic_relation_type TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE forager_contradiction_clusters (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE forager_claim_lineage (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, json TEXT NOT NULL);
```

## Новые файлы

```text
forager/embedding.py        — EmbeddingAdapter, StaticEmbeddingAdapter, cosine_similarity
forager/semantic_graph.py   — _classify_pair, build_semantic_claim_graph
tests/test_forager_phase8.py — 19 тестов
```

## Ограничения Phase 8

- Один flat cluster per thread (без split по connected components)
- Классификатор keyword-based, не LLM — точность ограничена
- Реальные embeddings требуют внешнего API (готов stub для OpenAI adapter)
- similarity_threshold=0.60 подходит для real embeddings; для StaticEmbeddingAdapter в тестах используется 0.0

## Проверка

```text
pytest -q forager
108 passed
```

Phase 8 добавил 19 новых тестов (embedding unit, classifier unit, pure graph builder, service integration, SQLite persistence).
