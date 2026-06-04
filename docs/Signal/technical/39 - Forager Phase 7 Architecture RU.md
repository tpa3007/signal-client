# Forager Phase 7 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 7 добавляет Evidence Draft Layer — первый явный мост между исследованием Forager и системой принятия решений Signal.

Forager предлагает `EvidenceDraft`. Signal решает, принять или отклонить. Ни один черновик не становится доказательством без явного review.

## Главная граница (остаётся неизменной)

```text
Forager discovers. Signal decides.
```

Каждый `EvidenceDraft` несёт это поле:

```text
boundary = "EvidenceDraft: not evidence until Signal approves."
```

## Архитектура слоя

```text
Thread
    ├── Claims        ─┐
    ├── Documents     ─┤── build_evidence_drafts() ──> EvidenceDraft[]
    └── SourceRawItems─┘                                     │
                                                        EvidenceDraftBundle
                                                             │
                                              review_evidence_draft() → Signal
```

## Scoring

Два независимых скоринга в `forager/evidence.py`:

### score_draft_reliability

Комбинирует вес типа источника, credibility и claim confidence.

```text
raw = source_type_weight(source_type) * credibility + 0.30 * claim_confidence
score = min(1.0, raw)
```

Веса типов:
- claim: 0.70
- document: 0.60
- raw_item: 0.45

### score_draft_freshness

Линейный decay за 365 дней. Неизвестная дата → 0.5.

```text
days_old < 1    → 1.0
days_old >= 365 → 0.10
else            → 1.0 - days_old / 365
```

### overall_score

```text
overall_score = (reliability_score + freshness_score) / 2
```

## Модели

### EvidenceDraft

```python
class EvidenceDraft(BaseModel):
    id: str                      # prefix "draft_"
    thread_id: str
    source_type: EvidenceSourceType   # RAW_ITEM | DOCUMENT | CLAIM
    source_id: str               # id оригинального объекта
    url: str | None
    title: str | None
    excerpt: str | None          # фрагмент из документа
    claim_text: str | None       # для claim-типа
    stance: Stance               # SUPPORTS | CONTRADICTS | NEUTRAL | UNCLEAR
    reliability_score: float
    freshness_score: float
    overall_score: float
    status: EvidenceDraftStatus  # DRAFT | APPROVED | REJECTED | PENDING_REVIEW
    reviewer_note: str | None
    reviewed_at: str | None
    boundary: str                # "EvidenceDraft: not evidence until Signal approves."
    created_at: str
```

### EvidenceDraftBundle

Собирает все черновики одного thread. Обязательно проверяет наличие disconfirming evidence.

```python
class EvidenceDraftBundle(BaseModel):
    id: str                      # prefix "bundle_"
    thread_id: str
    draft_ids: list[str]
    has_disconfirming: bool
    blocker: str | None          # "no_disconfirming_evidence_found" если нет CONTRADICTS
    aggregate_score: float
    boundary: str
    created_at: str
```

## Требование disconfirming evidence

Если `require_disconfirming=True` (default) и ни один черновик не имеет `stance=CONTRADICTS`:

```text
bundle.blocker = "no_disconfirming_evidence_found"
```

Signal видит этот blocker и знает: пакет неполный. Нужно дополнительное исследование с противоречащими источниками.

## build_evidence_drafts()

Создаёт черновики в порядке убывания глубины:
1. Claims (наиболее надёжный слой)
2. Documents
3. SourceRawItems

Черновики с `reliability_score < min_reliability_score` отфильтровываются.

## review_evidence_draft()

Signal import path:

```python
draft = svc.review_evidence_draft(thread_id, draft_id,
    EvidenceDraftReviewRequest(status=EvidenceDraftStatus.APPROVED, reviewer_note="..."))
```

- Обновляет `status` и `reviewer_note`
- Ставит `reviewed_at` timestamp
- Не делает прямых записей в схему Signal
- Персистируется через store (InMemory или SQLite)

## API endpoints

| Method | Path | Назначение |
|--------|------|------------|
| POST | `/threads/{id}/evidence-drafts` | Создать черновики для thread |
| GET | `/threads/{id}/evidence-drafts` | Список черновиков + bundles |
| POST | `/threads/{id}/evidence-drafts/{draft_id}/review` | Рецензировать черновик |

Версия API: 0.6.0

## SQLite таблицы

```sql
CREATE TABLE forager_evidence_drafts (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL,
    json TEXT NOT NULL
);

CREATE TABLE forager_evidence_draft_bundles (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    json TEXT NOT NULL
);
```

## Новые файлы

```text
forager/evidence.py             — score_draft_reliability, score_draft_freshness, source_type_weight
tests/test_forager_phase7.py    — 19 тестов
```

## Изменённые файлы

```text
forager/models.py               — EvidenceDraftStatus, EvidenceSourceType, EvidenceDraft,
                                  EvidenceDraftBundle, EvidenceDraftRequest,
                                  EvidenceDraftResult, EvidenceDraftReviewRequest
forager/memory/store.py         — evidence_drafts/bundles поля + 5 методов
forager/memory/sqlite_store.py  — 2 новые таблицы + 5 методов
forager/service.py              — build_evidence_drafts(), review_evidence_draft(),
                                  get_thread() расширен
apps/api/main.py                — 3 новых endpoint, version 0.6.0
```

## Проверка

На момент записи:

```text
pytest -q forager
72 passed
```

Phase 7 добавил 19 новых тестов:
- scoring utilities (7 тестов)
- build_evidence_drafts / bundle / boundary / disconfirming / filtering (6 тестов)
- review_evidence_draft (4 теста)
- SQLite persistence (2 теста)
