# Forager Phase 10 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 10 добавляет Monitoring and Drift — Forager теперь возвращается к unresolved threads и обнаруживает изменения нарратива.

Цель достигнута: Forager может сказать "этот тезис изменился, потому что изменилась структура источников/claims".

## Архитектура

```text
watch_thread(thread_id)
    │
    └── WatchThread(status=ACTIVE, recrawl_interval_hours)

run_watch_check(thread_id, WatchCheckRequest)
    │
    ├── snapshot old_claims
    │
    ├── Recrawl sources (limit=recrawl_limit)
    │       CrawlerAdapter.fetch(url)
    │       → new Document + update source.last_seen_at
    │
    ├── detect_narrative_drift(old_claims, new_claims)
    │       volume change ≥ 25% → DriftType.NARRATIVE
    │       contradiction delta ≥ 1 → DriftType.CLAIM_UPDATED
    │
    ├── detect_stale_sources(sources, stale_threshold_hours)
    │       source.last_seen_at > threshold → StaleSourceAlert
    │
    ├── save NarrativeDriftEvent, StaleSourceAlert
    │
    └── WatchThread(check_count++, last_checked_at)
```

## Модели

### WatchThread

```python
class WatchThread(BaseModel):
    id: str              # prefix "watch_"
    thread_id: str
    market_id: str | None
    status: WatchStatus  # ACTIVE / PAUSED / COMPLETED
    recrawl_interval_hours: int = 24
    last_checked_at: str | None
    check_count: int = 0
    created_at: str
    updated_at: str
```

### NarrativeDriftEvent

```python
class NarrativeDriftEvent(BaseModel):
    id: str              # prefix "drift_"
    thread_id: str
    watch_thread_id: str
    drift_type: DriftType  # NARRATIVE / LANGUAGE / SOURCE_STALE / CLAIM_UPDATED / CLAIM_RETRACTED
    description: str
    drift_score: float
    old_claim_count: int
    new_claim_count: int
    contradiction_delta: int
    affected_claim_ids: list[str]
    created_at: str
```

### StaleSourceAlert

```python
class StaleSourceAlert(BaseModel):
    id: str              # prefix "stale_"
    thread_id: str
    watch_thread_id: str
    source_id: str
    url: str
    last_fetched_at: str | None
    stale_hours: float
    description: str
    resolved: bool = False
    created_at: str
```

### ClaimStatusUpdate

```python
class ClaimStatusUpdate(BaseModel):
    id: str              # prefix "csupdate_"
    thread_id: str
    watch_thread_id: str
    claim_id: str
    old_stance: str | None
    new_stance: str | None
    reason: str
    created_at: str
```

## Чистые функции в monitor.py

### detect_narrative_drift

Сравнивает старый и новый set claims:
- Изменение volume ≥ 25% → `DriftType.NARRATIVE`, drift_score = delta/old
- Изменение contradiction count ≥ 1 → `DriftType.CLAIM_UPDATED`

### detect_stale_sources

Для каждого Source: если `last_seen_at` > `stale_threshold_hours` → `StaleSourceAlert`.

## API endpoints

| Method | Path | Назначение |
|--------|------|------------|
| POST | `/threads/{id}/watch` | Создать WatchThread |
| POST | `/threads/{id}/watch-check` | Запустить check: recrawl + drift |
| GET | `/threads/{id}/drift-events` | Drift events + stale alerts |

## SQLite таблицы

```sql
CREATE TABLE IF NOT EXISTS forager_watch_threads (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, status TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forager_narrative_drift_events (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
    watch_thread_id TEXT NOT NULL, drift_type TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forager_stale_source_alerts (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, watch_thread_id TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forager_claim_status_updates (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, watch_thread_id TEXT NOT NULL, json TEXT NOT NULL
);
```

## Новые файлы

```text
forager/monitor.py               — detect_narrative_drift, detect_stale_sources
tests/test_forager_phase10.py    — 16 тестов
```

## Ограничения Phase 10

- Document diffing (сравнение content_text до и после) — Phase 10+
- Language drift detector — Phase 10+
- Market-linked monitoring priorities — Phase 14
- recrawl_interval_hours не проверяется автоматически (нет cron); используется вручную через API

## Проверка

```text
pytest -q forager
124 passed
```

Phase 10 добавил 16 новых тестов.
