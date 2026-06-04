# Forager Phase 15 — Reference Readiness

Дата: 2026-05-20
Статус: implemented

## Назначение

Phase 15 отвечает на вопрос: можно ли считать этот Forager thread эталонным исследовательским dossier, которое не стыдно показать другому разработчику, агенту или использовать как reference-case для дальнейшего обучения Signal.

## Новый объект

`ReferenceReadinessReport`

Поля:

- `thread_id`
- `maturity_score`
- `reference_ready`
- `criteria`
- `blockers`
- `next_phase_actions`
- `created_at`

## Команда сервиса

```python
ForagerService.build_reference_readiness_report(thread_id)
```

API:

```http
POST /threads/{thread_id}/reference-readiness
```

## Критерии зрелости

Сейчас проверяются:

- `has_sources`
- `has_documents`
- `has_claims`
- `has_entities`
- `has_research_packet`
- `has_evidence_drafts`
- `has_approved_evidence`
- `has_semantic_graph`
- `has_swarm_trace`
- `has_watch_thread`
- `has_calibration`
- `translations_resolved`
- `signal_snapshot_created`

`maturity_score` = доля выполненных критериев.

## Reference-ready правило

Thread считается reference-ready, если:

- `maturity_score >= 0.85`
- нет `high/critical` blockers из maintenance audit

Если score ниже порога, добавляется blocker:

```text
maturity_below_reference_threshold
```

## Почему это важно

Forager должен уметь не только находить редкие источники, но и понимать качество собственной работы. Phase 15 делает исследование воспроизводимым: видно, какие слои пройдены, какие отсутствуют, что надо доделать.

## Хранение

Добавлены persistence paths:

- InMemory: `reference_readiness_reports`
- SQLite: `forager_reference_readiness_reports`

## Инвариант

Reference readiness — это не торговый сигнал. Это мета-оценка зрелости research thread.
