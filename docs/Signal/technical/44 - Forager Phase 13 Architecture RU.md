# Forager Phase 13 — Production Hardening

Дата: 2026-05-20
Статус: implemented

## Назначение

Phase 13 превращает Forager из набора исследовательских возможностей в проверяемую лабораторную систему. Главная задача: перед тем как выводить найденный поток в Signal, машина должна сама сказать, чего не хватает, где риск, где blocker и какие шаги нужны дальше.

## Новый объект

`MaintenanceAuditReport` — отчет аудита по одному research thread.

Он содержит:

- `status`: `pass`, `warn`, `fail`
- `findings`: список `MaintenanceFinding`
- `counts`: численная карта состояния потока
- `created_at`: время аудита

`MaintenanceFinding` содержит:

- `severity`: `info`, `low`, `medium`, `high`, `critical`
- `code`: машинно-читаемый код проблемы
- `description`: человеческое описание
- `remediation`: что делать дальше

## Команда сервиса

```python
ForagerService.run_maintenance_audit(thread_id, MaintenanceAuditRequest(...))
```

API:

```http
POST /threads/{thread_id}/maintenance-audit
```

## Что проверяется

Аудит смотрит на:

- наличие crawled documents
- наличие extracted claims/entities
- наличие ResearchPacket
- evidence drafts и approved evidence
- blocked evidence bundles
- pending translations
- semantic graph
- swarm trace
- watch thread
- calibration summary
- blocked thread status

## Правило допуска

Если есть `high` или `critical` finding, отчет получает `status=fail`.

Это означает: Forager thread нельзя использовать как надежный input для Signal signal commit. Его можно читать как исследовательский черновик, но нельзя воспринимать как завершенный dossier.

## Хранение

Добавлены persistence paths:

- InMemory: `maintenance_audit_reports`
- SQLite: `forager_maintenance_audit_reports`

## Инвариант

Phase 13 ничего не решает за Signal. Он только говорит, насколько Forager-исследование готово к handoff.
