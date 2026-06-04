# Master Workflows RU

Дата: 2026-05-19

Этот слой добавляет не новые сигналы, а операционные режимы. Идея: вместо 10 ручных вызовов запускать одну мастер-команду, которая сама собирает состояние проекта, сканирует рынки, показывает очереди и не дает learning loop развалиться из-за забытых записей.

Важно: мастер-команды не фабрикуют evidence и не создают сигналы без dossier. Они собирают данные, записывают market/snapshot источники, ранжируют кандидатов и возвращают точный список следующих действий.

## 1. `aladdin_master_cycle`

Главная команда для начала сессии.

Что делает:

- опционально сканирует новые рынки Polymarket;
- сохраняет markets/snapshots с source=`master_discovery`;
- ранжирует hidden-gem/moonshot кандидатов;
- показывает portfolio exposure;
- показывает pending outcome reviews;
- показывает stale open positions;
- показывает incomplete research dossiers;
- показывает learning snapshot по archetypes, no-signal reasons, source registry;
- возвращает operator priorities.

Когда запускать:

```text
aladdin_master_cycle(run_discovery=True, max_pages=4, max_candidates=10)
```

Если ты просто хочешь открыть проект и понять, что делать дальше, начинай здесь.

## 2. `master_market_discovery`

Команда только для поиска новых кандидатов.

Что делает:

- сканирует Polymarket через Gamma;
- сохраняет market metadata и snapshot;
- классифицирует vertical/theme tags;
- применяет discovery strategies:
  - `low_volume_research_sweetspot`
  - `cheap_optionality`
  - `stale_price`
- ранжирует кандидатов по discoverability;
- возвращает source queries, которые надо собрать перед dossier;
- возвращает action queue: backfill, moonshot review, hidden gem review, source collection.

Пример:

```text
master_market_discovery(max_pages=6, max_candidates=15)
```

Важно: это не список ставок. Это список рынков, которые стоит исследовать.

## 3. `master_learning_cycle`

Команда для обучения проекта.

Что делает:

- ищет resolved markets без `record_outcome_learning_review`;
- ищет open positions без свежего forecast update;
- ищет incomplete dossiers;
- показывает слабые и сильные archetypes;
- показывает no-signal reasons;
- показывает состояние benchmark cases;
- показывает source registry top.

Пример:

```text
master_learning_cycle(limit=20)
```

Когда запускать:

- после резолвов;
- после сильных движений цены;
- в конце research-сессии;
- если кажется, что проект начал копить мусор.

## 4. `master_maintenance_audit`

Команда для гигиены проекта.

Что делает:

- ищет open positions без snapshots;
- ищет evidence без source_url/source_name;
- ищет resolution maps с высокой ambiguity;
- ищет duplicate doc numbers;
- показывает incomplete research и pending outcomes;
- возвращает must_fix и should_fix.

Пример:

```text
master_maintenance_audit(limit=30)
```

Когда запускать:

- перед большой сессией;
- после серии ручных правок;
- когда кажется, что база начала жить своей жизнью.

## 5. Как теперь работать

Обычная сессия:

```text
1. aladdin_master_cycle
2. backfill_price_history для лучших кандидатов
3. record_moonshot_review или record_hidden_gem_review
4. record_resolution_map
5. record_evidence минимум 2 раза
6. record_actor_map / record_causal_factor / record_scenario / record_premortem
7. record_pre_bet_checklist
8. record_analysis только если approved_for_signal
```

Сессия обучения:

```text
1. master_learning_cycle
2. record_outcome_learning_review для resolved рынков
3. record_forecast_update для stale open positions
4. signal_regression_benchmark
5. source_track_record
```

Сессия уборки:

```text
1. master_maintenance_audit
2. закрыть must_fix
3. закрыть should_fix
4. aladdin_master_cycle(run_discovery=False)
```

## 6. Что еще сюда можно добавить позже

1. Автоматический `research_packet_export`: один markdown на рынок с вопросом, ценой, sources, dossier completeness, next actions.
2. `source_collection_agent`: отдельный слой, который реально ходит по web/news/TG и записывает `record_evidence` с URL.
3. `auto_backfill_top_candidates`: безопасный backfill для топ-N кандидатов из discovery.
4. `learning_debt_score`: единый показатель, насколько проект отстал по outcome reviews / forecast updates / incomplete dossiers.
5. `weekly_research_review`: недельный отчет по тому, какие archetypes усиливать, какие резать.
6. `paper_export`: превращать learning reviews и signal cases в материал для исследовательской работы.

## 7. Главная идея

Мастер-команды должны защищать проект от человеческой забывчивости.

Если оператор забыл закрыть исход, мастер-команда найдет pending outcome review. Если оператор забыл обновить открытую позицию, она попадет в stale open positions. Если рынок выглядит интересным, но без sources/dossier, он останется candidate, а не станет signal.

Это и есть следующий уровень проекта: не просто умный анализ, а система, которая заставляет умный анализ происходить регулярно.