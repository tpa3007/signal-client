# Signal - ТЗ для UI/UX дашборда

Дата: 2026-05-19

Этот документ описывает не визуальный стиль, а смысловое и backend-наполнение будущего дашборда SIGNAL. Дизайнеру не нужно копировать существующий terminal dashboard. Наоборот: нужно проявить креатив и создать современный, интуитивно понятный, удобный интерфейс, который не перегружает пользователя и не выглядит примитивно или однотипно.

Главная задача дизайна: визуально превратить SIGNAL из набора исследовательских команд и SQLite-таблиц в понятный исследовательский терминал, где владелец проекта сразу видит, что система нашла, что она думает, где есть риск, где нужен ресерч, какие сигналы открыты, чему проект научился и какие действия надо сделать дальше.

## 1. Что такое SIGNAL

SIGNAL - это личная исследовательская система для Polymarket. Это не автотрейдер и не терминал для быстрой купли-продажи. Проект рассчитан на paper-money, hold-to-resolution исследование:

- находить overlooked / hidden-gem рынки;
- собирать evidence и source trail;
- строить dossier по рынку;
- оценивать вероятность и edge против рыночной цены;
- выпускать только gated paper signals;
- учитывать open positions и exposure;
- после resolution делать outcome learning review;
- накапливать материал для будущей исследовательской работы.

В интерфейсе это должно ощущаться как исследовательская лаборатория: не казино, не crypto-trading экран, не обычная таблица сделок.

## 2. Главные пользовательские сценарии

Дашборд должен помогать владельцу проекта выполнять 6 регулярных сценариев.

### 2.1. Открыть проект и понять состояние

Пользователь должен за 30-60 секунд понять:

- сколько рынков известно системе;
- сколько кандидатов сейчас в очереди;
- сколько открытых paper positions;
- какие позиции stale и требуют update;
- есть ли resolved markets без outcome review;
- есть ли incomplete dossiers;
- есть ли перегруз по vertical/theme/archetype exposure;
- что система рекомендует сделать следующим шагом.

### 2.2. Найти новые рынки для исследования

Пользователь запускает discovery или смотрит последнюю discovery-очередь.

Интерфейс должен показывать не только список рынков, а причину, почему рынок попал в фокус:

- matched strategies: `low_volume_research_sweetspot`, `stale_price`, `cheap_optionality`, `compounder_research_candidate`;
- research lane: moonshot / hidden / compounder;
- raw discoverability score;
- price, spread, volume, liquidity;
- days to resolution;
- source queries to collect;
- recommended next actions.

Важно: дашборд не должен визуально внушать, что дешевые moonshots важнее всего. Нужно показать три равноправные research lanes.

### 2.3. Провести deep research по рынку

Для выбранного рынка нужен market dossier view:

- вопрос рынка и ссылка на Polymarket;
- текущая цена YES/NO, bid/ask, spread, liquidity, volume;
- timeline цены из snapshots;
- resolution map;
- evidence list;
- actor map;
- causal factors;
- scenario tree;
- premortem;
- forecast updates;
- hidden-gem или moonshot review;
- pre-bet checklist;
- analyses и signal history.

Пользователь должен видеть, чего не хватает до качественного dossier. Не просто score, а конкретные missing blocks: нет evidence, нет scenario tree, нет premortem, нет resolution map и т.д.

### 2.4. Решить: signal, watch, reject, needs more research

Дашборд должен ясно показывать decision state рынка:

- `discovered` - рынок найден, но еще не изучен;
- `watch` / `watchlist` - интересен, но пока без сигнала;
- `deep_research_candidate` - стоит исследовать глубже;
- `needs_more_research` - уже есть материалы, но dossier неполный;
- `rejected` - причина отказа записана;
- `approved_for_signal` - pre-bet checklist разрешает сигнал;
- `signal` - создан paper signal и position;
- `open_position` - позиция открыта и требует мониторинга;
- `resolved_pending_learning` - рынок завершился, но learning review не сделан;
- `learned` - исход разобран, lessons записаны.

Эта цепочка в будущем должна лечь в `research_ledger`. Пока данные живут в разных таблицах, но UI должен мыслить именно таким жизненным циклом.

### 2.5. Следить за открытыми позициями

Для open positions нужны:

- side: YES/NO;
- intended entry price;
- current side price;
- stake;
- mark-to-market value;
- mark-to-market PnL;
- days to resolution;
- thesis snapshot;
- last forecast update;
- stale warning, если давно не было update;
- linked signal, analysis, dossier completeness;
- exposure bucket: vertical, theme, archetype, deadline week.

Важно: реальные деньги не являются фокусом интерфейса. Основной режим - paper research. Если позже появится real/hybrid fill, он должен быть отмечен отдельно и осторожно.

### 2.6. Учиться на исходах

Learning view должен отвечать:

- какие resolved markets ждут outcome review;
- где прогноз был лучше рынка;
- где рынок был лучше нас;
- какие archetypes работают;
- какие archetypes вредят;
- какие источники часто цитировались;
- какие no-signal решения могли быть false negatives;
- где confidence был завышен;
- какие правила надо обновить.

Это сердце исследовательского проекта. Дизайн должен помогать видеть обучение как отдельный цикл, а не как архив старых ставок.

## 3. Основные сущности backend

Источник правды сейчас: SQLite `C:\Signal\bot\bot.db`.

Ключевые таблицы:

| Сущность | Таблица | Что хранит |
|---|---|---|
| Market universe | `markets` | condition_id, question, slug, end_date, resolved, vertical |
| Price history | `snapshots` | YES/NO price, bid/ask, spread, volume, liquidity, source |
| Tags | `market_tags` | theme tags: ai_launches, us_primary_2026 и т.д. |
| Hidden-gem review | `hidden_gem_reviews` | score, thesis, disconfirming evidence, decision |
| Moonshot review | `moonshot_reviews` | side, entry, payout, anti-random score, kill criteria |
| Evidence | `evidence` | source_url, source_name, claim, stance, reliability |
| Resolution map | `resolution_maps` | YES/NO criteria, sources, ambiguity, wording risk |
| Actor map | `actor_maps` | actors, incentives, constraints, likely action |
| Causal model | `causal_factors` | factors, mechanisms, direction, uncertainty |
| Anomalies | `anomalies` | unusual observations and why they matter |
| Scenario tree | `scenario_trees` | scenarios, probabilities, assumptions, warning signals |
| Premortem | `premortems` | failure modes and disconfirming signals |
| Checklist | `pre_bet_checklists` | gate completeness and decision before signal |
| Analysis | `analyses` | probability, confidence, edge, signal/no_signal decision |
| Signal | `signals` | paper signal, side, price, probability, edge, stake |
| Position | `positions` | intended position, status, thesis snapshot, exposure metadata |
| Fill | `fills` | paper or real fill records |
| PnL event | `pnl_events` | marks, resolution, partial exits |
| Forecast update | `forecast_updates` | probability changes over time |
| Outcome learning | `outcome_learning_reviews` | post-mortem, errors, lesson, rule update |
| Quality review | `signal_quality_reviews` | mark-to-market quality, grade, verdict, lessons |
| Archetype review | `signal_archetype_reviews` | signal pattern and repeatable lesson |
| Benchmark cases | `signal_benchmark_cases` | regression examples for model behavior |
| Source registry | `sources` | source reliability, latency, bias, track record |

## 4. Состояние текущего наполнения базы

На момент аудита:

```text
markets: 201
snapshots: 1429
market_tags: 94
hidden_gem_reviews: 5
moonshot_reviews: 8
evidence: 15
resolution_maps: 5
actor_maps: 8
causal_factors: 10
anomalies: 2
scenario_trees: 15
premortems: 4
pre_bet_checklists: 4
analyses: 3
signals: 18
positions: 18
fills: 20
pnl_events: 54
forecast_updates: 1
outcome_learning_reviews: 0
signal_quality_reviews: 21
signal_archetype_reviews: 3
signal_benchmark_cases: 7
sources: 49
```

UI должен учитывать, что некоторые блоки могут быть пустыми или незрелыми. Например, `outcome_learning_reviews` пока пустой, и это должно отображаться как learning debt, а не как ошибка.

## 5. Рекомендуемая информационная архитектура

Не навязываю визуальный стиль, но backend-смысл лучше разложить на такие зоны.

### 5.1. Command Center

Главная страница. Должна отвечать: “что сейчас важно?”

Данные:

- health summary из `master_maintenance_audit`;
- discovery summary из `aladdin_master_cycle` / `master_market_discovery`;
- open exposure из `portfolio_snapshot`;
- pending outcome reviews;
- stale open positions;
- incomplete research dossiers;
- learning snapshot;
- recommended next calls.

Компоненты по смыслу:

- project health;
- today priority queue;
- latest discovery candidates;
- open risk/exposure;
- learning debt;
- recent important changes.

### 5.2. Discovery Lab

Страница поиска новых рынков.

Данные:

- `master_market_discovery` top candidates;
- `discovery_scan` strategy matches;
- `api_research_enrichment` packets;
- latest market snapshots;
- source queries.

Кандидат должен показывать:

- question;
- research lane;
- matched strategies;
- yes/no prices;
- spread;
- liquidity/volume;
- days to resolution;
- discoverability score and components;
- source queries;
- next actions;
- whether it already has reviews/evidence.

Фильтры:

- vertical;
- research lane;
- strategy;
- price range;
- liquidity/volume;
- days to resolution;
- has / missing dossier blocks;
- status in lifecycle.

### 5.3. Research Queue / Ledger

Это будущий главный список всех идей. Он должен объединять рынки, watchlist, rejected, signals, resolved и learning.

Пока backend не имеет отдельной таблицы `research_ledger`, но UI должен быть спроектирован под нее.

Колонки/поля:

- lifecycle status;
- priority;
- condition_id;
- market question;
- vertical/theme;
- research lane;
- current price;
- model probability;
- edge;
- confidence;
- dossier completeness;
- latest decision;
- blocker / next action;
- next_check_at;
- owner / analyst;
- created_at / last_touched_at;
- linked signal / position / outcome review.

### 5.4. Market Dossier

Детальная страница одного рынка.

Секции данных:

- market header: question, slug/url, vertical, tags, end date, resolved status;
- price module: latest snapshot, bid/ask, spread, liquidity, volume, chart;
- current forecast: latest probability, confidence, edge, side;
- decision history: analyses, reviews, checklist, signal/no_signal;
- resolution map: criteria, ambiguity, parser warnings;
- evidence board: claims grouped by YES/NO/MIXED/NEUTRAL;
- actor map;
- causal factors;
- scenario tree;
- premortems;
- forecast update timeline;
- source trail;
- next actions;
- linked position if signal exists;
- learning review after resolution.

Критически важно: market dossier должен быстро показывать, почему система думает именно так. Не только score, но и reasoning trail.

### 5.5. Signals & Positions

Страница учета paper signals и positions.

Данные:

- `signals`;
- `positions`;
- `fills`;
- `pnl_events`;
- latest snapshots;
- portfolio exposure.

Нужны режимы:

- open;
- stale;
- resolved;
- paper only;
- hybrid/real marked separately;
- by vertical;
- by deadline week;
- by archetype/theme.

Каждая позиция должна показывать:

- original thesis;
- entry;
- current price/value;
- PnL;
- exposure contribution;
- last forecast update;
- next required action.

### 5.6. Learning Lab

Страница качества модели.

Данные:

- `forecast_quality_report`;
- `signal_quality_report`;
- `false_negative_review`;
- `signal_regression_benchmark`;
- `outcome_learning_reviews`;
- `signal_archetype_reviews`;
- `sources` track record.

Блоки:

- calibration buckets;
- Brier/log score vs market;
- confidence bucket performance;
- best/worst relative forecasts;
- no-signal false negative candidates;
- archetype performance;
- source reliability and citation history;
- lessons / rule updates.

Дизайн должен делать обучение видимым. Это не второстепенный отчет, а причина существования проекта.

### 5.7. Source & Evidence Library

Страница источников.

Данные:

- `sources`;
- `evidence`;
- source reliability/latency/bias;
- citation counts;
- correctness counters when outcomes are known.

Нужны:

- поиск по source name / domain;
- фильтр по source type;
- список evidence items, где источник использовался;
- предупреждения: source без URL, overused source, low reliability source.

### 5.8. Maintenance / Hygiene

Страница, которая предотвращает деградацию проекта.

Данные:

- `master_maintenance_audit`;
- evidence without source;
- open positions without snapshots;
- high ambiguity resolution maps;
- duplicate documentation numbers;
- incomplete dossiers;
- pending outcome reviews.

Это должна быть не “страница ошибок”, а список задач, которые сохраняют исследовательскую чистоту.

## 6. Основные метрики dashboard

### 6.1. Research Health

- total markets known;
- candidates discovered today / last run;
- incomplete dossiers count;
- avg dossier completeness;
- evidence without source count;
- pending outcome reviews count;
- stale open positions count;
- source registry coverage.

### 6.2. Discovery Quality

- candidates by research lane: moonshot / hidden / compounder;
- candidates by strategy;
- avg discoverability score;
- watchlist promotion rate;
- rejection reasons;
- deep research candidates count.

### 6.3. Forecast Quality

- total analyses;
- signal vs no_signal count;
- avg edge;
- avg confidence;
- Brier score;
- market-relative Brier;
- calibration by probability bucket;
- false negatives.

### 6.4. Position / Risk

- open positions;
- total at risk;
- max payout;
- exposure by vertical;
- exposure by theme;
- exposure by deadline week;
- correlated open pairs;
- mark-to-market PnL.

### 6.5. Learning

- outcome reviews completed / missing;
- repeatable lessons count;
- rule updates count;
- strong/weak archetypes;
- sources with good/bad track record;
- benchmark pass/fail.

## 7. Важные состояния и предупреждения

UI должен явно подсвечивать смысловые состояния:

- snapshot stale;
- spread too wide;
- liquidity too low;
- resolution ambiguity high;
- evidence missing source;
- only one-sided evidence;
- no disconfirming evidence;
- dossier completeness below threshold;
- pre-bet checklist not approved;
- open position without recent update;
- resolved market without outcome learning;
- exposure cap nearly breached;
- candidate was already recently reviewed;
- market is open position and should not be duplicated.

## 8. Backend endpoints / агрегаты, которые желательно иметь

Будущему backend/frontend слою нужны агрегированные read endpoints. Их можно строить как Python functions, MCP tools или API routes.

Минимальный набор:

1. `dashboard_overview()`
   - health summary;
   - counts;
   - priority tasks;
   - top candidates;
   - open exposure;
   - learning debt.

2. `research_ledger_list(filters)`
   - unified rows for discovered/watch/rejected/signal/resolved/learned.

3. `market_dossier(condition_id)`
   - full joined view across market, snapshots, reviews, evidence, scenarios, position and learning.

4. `discovery_candidates(filters)`
   - latest candidates and source actions.

5. `position_book(filters)`
   - positions + fills + PnL + latest snapshot.

6. `learning_lab()`
   - calibration, false negatives, archetypes, source track record.

7. `maintenance_tasks()`
   - hygiene issues and next actions.

8. `source_library(filters)`
   - sources + evidence usage.

## 9. Поля для будущего `research_ledger`

Рекомендуемая таблица или view должна объединять жизненный цикл идей.

Предлагаемые поля:

```text
id
condition_id
created_at
last_touched_at
question
slug
vertical
research_lane                  -- moonshot | hidden | compounder | unknown
status                         -- discovered | watch | deep_research | rejected | approved_for_signal | signal | open_position | resolved_pending_learning | learned
priority                       -- low | medium | high | critical
current_yes_price
current_no_price
intended_side
model_probability_yes
confidence
edge
score                          -- latest relevant review score
score_type                     -- discoverability | hidden_gem | moonshot | checklist | quality
latest_decision
decision_reason
blocker
next_action
next_check_at
dossier_completeness
missing_dossier_blocks_json
signal_id
position_id
analysis_id
latest_review_id
resolved
resolved_yes
outcome_review_id
source_count
evidence_count
updated_by
notes
```

UI не обязан показывать все поля сразу. Но backend должен уметь отдавать их, чтобы дизайнер мог строить разные плотности представления: compact list, detail drawer, dossier page.

## 10. Дизайнерская свобода

Не нужно копировать Bloomberg, Notion, Linear, crypto-terminal или старый terminal dashboard. Это должен быть свой интерфейс: современный, быстрый для чтения, уверенный, но не перегруженный.

Ограничения по стилю намеренно минимальны:

- не делать примитивную таблицу на всю страницу как единственный интерфейс;
- не превращать проект в визуально шумный trading terminal;
- не делать однотипные карточки без иерархии;
- не прятать uncertainty и missing data;
- не изображать watchlist как рекомендацию к ставке;
- не смешивать paper research и real money без явной маркировки.

Дизайнер может самостоятельно предложить композицию, навигацию, визуальный язык, графики, cards, drawers, timelines, command palette, swimlanes, heatmaps, glyphs, density modes и другие решения.

## 11. Что пользователь должен чувствовать

После открытия дашборда пользователь должен думать:

- “Я понимаю, что происходит с проектом.”
- “Я вижу, какие рынки стоит изучить.”
- “Я понимаю, почему машина считает рынок интересным.”
- “Я вижу, где система сомневается.”
- “Я вижу, что забыто и что надо доделать.”
- “Я вижу, чему проект научился.”
- “Это не игрушка со ставками, а настоящая исследовательская система.”

## 12. MVP dashboard

Для первой версии достаточно 5 экранов:

1. Command Center
2. Research Ledger
3. Market Dossier
4. Positions & Risk
5. Learning Lab

Source Library и Maintenance можно встроить в Command Center как панели, а позже вынести отдельно.

## 13. Необходимые данные для макета

Для дизайнера желательно подготовить mock data из реальной базы:

- 3-5 discovery candidates разных lanes;
- 2 watchlist candidates;
- 2 rejected candidates with reasons;
- 2 open positions;
- 1 incomplete dossier;
- 1 resolved_pending_learning example;
- 1 full market dossier example;
- source library sample;
- learning lab empty/early-state sample.

Важно показать не только идеальные записи, но и “грязные” состояния: нет source_url, нет scenario tree, stale position, no outcome review. Именно эти состояния делают dashboard полезным.