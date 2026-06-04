# Forager Phase 14 — Signal Integration Layer

Дата: 2026-05-20
Статус: implemented

## Назначение

Phase 14 создает безопасный мост между Forager и Signal. Это не запись в Signal DB, не сигнал и не ставка. Это read-only snapshot, который показывает, какие Forager-артефакты можно принести в Signal как контекст.

## Новый объект

`SignalIntegrationSnapshot`

Поля:

- `thread_id`
- `market_id`
- `forager_packet_id`
- `evidence_bundle_ids`
- `approved_evidence_draft_ids`
- `calibration_score_id`
- `watch_thread_ids`
- `blockers`
- `recommended_next_actions`
- `boundary`

Boundary всегда содержит смысл: snapshot не пишет Signal DB.

## Команда сервиса

```python
ForagerService.build_signal_integration_snapshot(thread_id)
```

API:

```http
POST /threads/{thread_id}/signal-integration-snapshot
```

## Логика

Snapshot автоматически запускает maintenance audit с `include_low_severity=False` и собирает hard blockers.

Если есть `high/critical` blockers, snapshot не рекомендует импорт dossier в Signal. Он возвращает следующие действия:

- `resolve_forager_audit_blockers`
- `build_research_packet`
- `review_and_approve_evidence_drafts`
- `create_watch_thread_for_active_candidate`

Если packet есть, evidence approved и hard blockers отсутствуют, появляется:

- `review_for_signal_dossier_import`

## Важное правило

Forager не создает `signal`, `position`, `fill`, `analysis` в Signal.

Он может дать:

- источники
- сырые находки
- draft evidence
- approved evidence ids
- packet id
- readiness/blockers

Финальное решение остается за Signal workflow и его gate/checklist.

## Хранение

Добавлены persistence paths:

- InMemory: `signal_integration_snapshots`
- SQLite: `forager_signal_integration_snapshots`
