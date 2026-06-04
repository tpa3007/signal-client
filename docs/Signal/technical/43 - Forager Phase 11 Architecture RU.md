# Forager Phase 11 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 11 добавляет Scoring and Calibration — Forager теперь учится, какие weirdness signals реально дают alpha, а какие — шум.

Цель достигнута: Forager знает, какие формы weird реальны, а какие — noise.

## Архитектура

```text
review_anomaly(thread_id, AnomalyReviewRequest)
    │
    └── AnomalyReview(verdict: CONFIRMED_ALPHA / FALSE_POSITIVE / NOISE, archetype)

build_source_track_records(thread_id)
    │
    ├── Per source: count claims from source_docs
    │       confirmed_claims = stance in {supports, contradicts}
    │       yield_score = confirmed / total
    │       archetype = classify_weirdness_archetype(url, source_type)
    │
    └── SourceTrackRecord[]

build_calibration_summary(thread_id, CalibrationRequest)
    │
    ├── AnomalyReviews for thread
    ├── alpha_rate = confirmed_alpha / total
    ├── archetype_yields = { archetype: alpha_rate }
    │
    └── CalibrationScore
```

## Модели

### WeirdnessArchetype

```python
class WeirdnessArchetype(StrEnum):
    FORUM_RUMOR = "forum_rumor"
    ARCHIVED_CONTRADICTION = "archived_contradiction"
    CROSS_LANGUAGE_GAP = "cross_language_gap"
    GITHUB_SIGNAL = "github_signal"
    PDF_HIDDEN = "pdf_hidden"
    TRANSLATION_SURFACE = "translation_surface"
    RECURSIVE_ENTITY = "recursive_entity"
    TEMPORAL_ANOMALY = "temporal_anomaly"
    UNKNOWN = "unknown"
```

### AnomalyReview

```python
class AnomalyReview(BaseModel):
    id: str              # prefix "review_"
    thread_id: str
    anomaly_id: str
    verdict: AnomalyVerdict  # CONFIRMED_ALPHA / FALSE_POSITIVE / NOISE
    reviewer_note: str | None
    archetype: WeirdnessArchetype
    created_at: str
```

### SourceTrackRecord

```python
class SourceTrackRecord(BaseModel):
    id: str              # prefix "track_"
    thread_id: str
    source_id: str
    url: str
    total_claims: int
    confirmed_claims: int
    yield_score: float   # confirmed / total
    archetype: WeirdnessArchetype
    created_at: str
```

### CalibrationScore

```python
class CalibrationScore(BaseModel):
    id: str              # prefix "calib_"
    thread_id: str
    total_anomalies: int
    confirmed_alpha_count: int
    false_positive_count: int
    noise_count: int
    weirdness_alpha_rate: float  # confirmed_alpha / total
    archetype_yields: dict[str, float]  # archetype -> alpha_rate
    created_at: str
```

## Archetype Classifier (archetypes.py)

Keyword/URL pattern matching:

| Archetype | Признаки |
|-----------|---------|
| ARCHIVED_CONTRADICTION | source_type=ARCHIVE или web.archive.org в URL |
| GITHUB_SIGNAL | source_type=GITHUB или github.com в URL |
| PDF_HIDDEN | source_type=PDF или .pdf в URL |
| FORUM_RUMOR | source_type=FORUM или reddit/forum/chan в URL |
| TRANSLATION_SURFACE | non-english TLD (.ru, .cn, .de, ...) или translate. в URL |
| UNKNOWN | всё остальное |

## API endpoints

| Method | Path | Назначение |
|--------|------|------------|
| POST | `/threads/{id}/anomaly-reviews` | Записать вердикт по аномалии |
| GET | `/threads/{id}/anomaly-reviews` | Список вердиктов |
| POST | `/threads/{id}/source-track-records` | Построить track records |
| POST | `/threads/{id}/calibration` | Построить CalibrationScore |

Версия API: 0.8.0

## SQLite таблицы

```sql
CREATE TABLE IF NOT EXISTS forager_anomaly_reviews (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
    anomaly_id TEXT NOT NULL, verdict TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forager_source_track_records (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, source_id TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forager_calibration_scores (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, json TEXT NOT NULL
);
```

## Новые файлы

```text
forager/archetypes.py             — classify_weirdness_archetype
tests/test_forager_phase11.py     — 17 тестов
```

## Ограничения Phase 11

- Outcome-linked learning (Signal → Forager) — Phase 14
- Expansion query yield score — Phase 11+
- Contradiction cluster yield — Phase 11+
- False positive review workflow — Phase 11+
- Классификатор — keyword/URL pattern, не LLM

## Проверка

```text
pytest -q forager
141 passed
```

Phase 11 добавил 17 новых тестов (archetype classifier, anomaly review, track records, calibration summary, SQLite persistence).
