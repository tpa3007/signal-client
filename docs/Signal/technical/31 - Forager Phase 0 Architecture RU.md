# Forager Phase 0 Architecture RU

Дата: 2026-05-20

## Суть

Forager - это новый слой перед Signal. Signal остается строгой системой принятия решений: чеклисты, гейты, sizing, paper/real positions, learning. Forager занимается другим: он ищет странности, слабые сигналы, противоречия, исчезнувшие следы, локальные источники, технические артефакты и гипотезы, которые обычный ресерч даже не сформулировал бы.

Главная граница:

```text
Forager discovers.
Signal decides.
```

Forager не создает ставки и не пишет в Signal DB. Он готовит research packet, который Signal потом проверяет через свои правила.

## Что реализовано сейчас

Создан отдельный модуль `forager/`, независимый от `bot/` и Signal-гейтов.

Файлы ядра:

- `forager/forager/models.py` - доменные модели: thread, source, hypothesis, anomaly, weak signal, packet.
- `forager/forager/search/query_mutation.py` - генератор неочевидных поисковых мутаций.
- `forager/forager/scoring/weirdness.py` - первичный скоринг информационной странности.
- `forager/forager/memory/store.py` - in-memory store для Phase 0.
- `forager/forager/packets/research_packet_builder.py` - сборка research packet для Signal.
- `forager/forager/service.py` - сервисный workflow: start research -> register source -> add hypothesis -> build packet.
- `forager/apps/api/main.py` - FastAPI skeleton.
- `forager/tests/test_forager_core.py` - тесты Phase 0.

## Чем Forager отличается от обычного поиска

Обычный поиск отвечает на вопрос. Forager сначала ломает сам вопрос.

Он генерирует линзы:

- `surface` - публичный нарратив.
- `contradiction` - что спорит с публичным нарративом.
- `pre_hype` - следы до того, как тема стала популярной.
- `archival` - PDF, архивы, удаленные/старые страницы.
- `graph_neighbor` - соседние люди, репозитории, домены, алиасы.
- `absence` - что должно быть, но почему-то отсутствует.
- `low_visibility` - форумы, issue threads, нишевые обсуждения.
- `operator_pattern` - тайминг, стимулы, координация.
- `technical_surface` - changelog, GitHub, API docs, инфраструктура.
- `disconfirming` - что убивает гипотезу.

## Новые идеи, которые стоит развить

### 1. Absence Map

Не просто искать найденное, а фиксировать отсутствующее. Пример: у сильного политического кандидата должны быть локальные endorsements, но их нет; у AI-релиза должны быть коммиты, changelog, docs, job postings, но один слой молчит. Отсутствие становится сигналом.

### 2. Pre-Hype Fossils

Искать следы до хайпа: старые issue, архивные PDF, комментарии инженеров, вакансии, закупки, локальные новости. Часто рынок видит новость, но не видит историю накопления.

### 3. Contradiction Ledger

Не заставлять агента прийти к консенсусу слишком рано. Противоречия должны жить отдельно: кто говорит A, кто говорит not-A, какой источник старше, ближе, первичнее.

### 4. Signal Shadow

Для каждого Polymarket market строить тень: какие события вне Polymarket должны происходить, если рынок действительно близок к YES. Если тень не двигается, рынок может быть mispriced.

### 5. Narrative Drift

Сравнивать старый язык и новый язык. Если участники внезапно меняют формулировки, убирают сроки, заменяют “will launch” на “working toward”, это может быть ранним предупреждением.

### 6. Weirdness Ledger

Хранить не только источники, но и “почему это странно”. Это даст обучение: какие типы странности реально приводят к edge, а какие просто шум.

### 7. Dream Recombination

Периодически брать нерешенные threads и скрещивать их: общие акторы, одинаковые домены, похожий тайминг, одна и та же PR-машина, один паттерн задержек. Это не должно создавать сигнал, но должно создавать новые гипотезы.

### 8. Disagreement Budget

В swarm-версии каждому агенту назначать обязанность не соглашаться до определенного этапа. Hunter ищет, Skeptic ломает, Archivist уносит в прошлое, Cartographer строит граф, Whisper Listener ищет низковидимые источники, Synthesizer собирает packet.

## Почему Phase 0 сделан без live search

Это сознательно. Сначала нужен контракт памяти и формы результата. Иначе Forager быстро превратится в набор одноразовых скриптов, которые красиво ищут, но не оставляют структуры для обучения.

Текущий Phase 0 уже позволяет тестировать workflow на вручную зарегистрированных источниках и гарантирует, что output будет packet, а не “красивая ставка”.

## Следующий шаг

Phase 1 должен добавить real search adapter и persistence:

1. `source_raw_items` как отдельный слой до evidence.
2. Search API adapter: Brave/Tavily/SerpAPI или иной доступный провайдер.
3. Crawl adapter: Firecrawl/Playwright/simple HTTP.
4. SQLite persistence для локального режима.
5. Export/import bridge: Forager packet -> Signal candidate enrichment.
6. MCP/high-level commands: `forager_start_research`, `forager_register_source`, `forager_build_packet`.

## Проверка

На момент записи:

```text
pytest -q forager
4 passed
```
