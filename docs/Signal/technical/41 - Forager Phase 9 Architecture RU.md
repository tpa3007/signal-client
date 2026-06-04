# Forager Phase 9 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 9 добавляет Recursive Swarm Orchestration — Forager теперь запускает несколько специализированных агентов в рамках одного bounded investigation и оставляет полный trace.

Цель достигнута: один master workflow с бюджетом, дисциплиной и полным trace execution.

## Архитектура

```text
run_swarm(thread_id, SwarmRequest)
    │
    ├── SwarmRun созданы (trace record)
    │
    ├── Для каждого agent_role в request.agents:
    │       AgentWorkRecord(status=RUNNING)
    │       ├── HUNTER:           run_search_burst + crawl_sources
    │       ├── SKEPTIC:          count CONTRADICTS claims → contradiction_pass_done=True
    │       ├── CARTOGRAPHER:     expand_graph (если есть entities)
    │       ├── WHISPER_LISTENER: build_local_language_profile
    │       ├── SYNTHESIZER:      build_packet
    │       └── ARCHIVIST/ENGINEER/LATERALIST: noted (Phase 9+)
    │       AgentWorkRecord(status=DONE|BLOCKED|SKIPPED)
    │
    ├── Conflict detection (SKEPTIC pass):
    │       prior_anomalies > 0 AND contradictions_found == 0
    │           → ConflictEntry("hunter_weirdness_unconfirmed")
    │
    ├── Stop condition: contradictions_found >= stop_on_enough_contradictions
    │
    └── SwarmRun(status=DONE, contradiction_pass_done, consensus_allowed)
```

## Ключевые инварианты

```text
No consensus before contradiction pass.
```

`consensus_allowed = True` только если SKEPTIC запустился.
Если `require_contradiction_pass=True` и SKEPTIC не запустился — `blocker="contradiction_pass_not_done"`.

## Модели

### SwarmRun

```python
class SwarmRun(BaseModel):
    id: str              # prefix "swarm_"
    thread_id: str
    agents_planned: list[AgentRole]
    status: SwarmAgentStatus
    contradiction_pass_done: bool
    consensus_allowed: bool
    total_queries: int
    total_crawls: int
    total_anomalies: int
    blocker: str | None
    notes: list[str]
    created_at: str
    completed_at: str | None
```

### AgentWorkRecord

Trace record для каждого агента в рамках SwarmRun.

```python
class AgentWorkRecord(BaseModel):
    id: str              # prefix "work_"
    swarm_run_id: str
    agent_role: AgentRole
    status: SwarmAgentStatus
    queries_used: int
    crawls_used: int
    raw_items_found: int
    anomalies_raised: int
    contradictions_found: int
    notes: list[str]
    started_at: str | None
    completed_at: str | None
    created_at: str
```

### ConflictEntry

Запись о disagreement между агентами.

```python
class ConflictEntry(BaseModel):
    id: str              # prefix "conflict_"
    swarm_run_id: str
    thread_id: str
    agent_a: AgentRole
    agent_b: AgentRole
    conflict_type: str   # "hunter_weirdness_unconfirmed" и др.
    description: str
    resolved: bool
    created_at: str
```

### AgentBudget

```python
class AgentBudget(BaseModel):
    max_queries: int = 3
    max_crawls: int = 2
    max_search_results: int = 5
```

## Stop conditions

| Условие | Результат |
|---------|-----------|
| `total_queries >= max_total_queries` | `blocker="max_total_queries_exhausted"`, агенты не запускаются |
| `contradictions_found >= stop_on_enough_contradictions` | Ранний выход с примечанием в `swarm_run.notes` |

## Конфликтный детектор

После запуска SKEPTIC:
- Если `prior_work_records.anomalies_raised > 0` И `skeptic.contradictions_found == 0`
  → создаётся ConflictEntry с типом "hunter_weirdness_unconfirmed"

## Агенты Phase 9

| Agent | Действие |
|-------|----------|
| HUNTER | run_search_burst + crawl_sources (в рамках budget) |
| SKEPTIC | Считает CONTRADICTS claims → contradiction_pass_done |
| CARTOGRAPHER | expand_graph (если есть entities) |
| WHISPER_LISTENER | build_local_language_profile |
| SYNTHESIZER | build_packet |
| ARCHIVIST | noted — Phase 9+ |
| ENGINEER | noted — Phase 9+ |
| LATERALIST | noted — Phase 9+ |

## API endpoints

| Method | Path | Назначение |
|--------|------|------------|
| POST | `/threads/{id}/swarm` | Запустить swarm investigation |
| GET | `/threads/{id}/swarm-runs` | Список swarm runs для thread |

## SQLite таблицы

```sql
CREATE TABLE forager_swarm_runs (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE forager_agent_work_records (
    id TEXT PRIMARY KEY,
    swarm_run_id TEXT NOT NULL,
    agent_role TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE forager_conflict_entries (
    id TEXT PRIMARY KEY,
    swarm_run_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    json TEXT NOT NULL
);
```

## Ограничения Phase 9

- ARCHIVIST, ENGINEER, LATERALIST — заглушки (noted, status=SKIPPED)
- ConflictLedger — одно правило: hunter_weirdness_unconfirmed; Phase 11 добавит больше
- Агенты работают последовательно (не параллельно); Phase 9+ — параллельный swarm
- Budget в памяти (не персистируется между запусками swarm)

## Новые файлы

```text
tests/test_forager_phase9.py — 17 тестов
```

## Проверка

```text
pytest -q forager
108 passed
```

Phase 9 добавил 17 новых тестов (swarm execution, contradiction pass, budget, conflict detection, stop conditions, SQLite persistence).
