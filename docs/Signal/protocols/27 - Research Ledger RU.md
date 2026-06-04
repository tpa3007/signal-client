# Signal - Research Ledger

Дата: 2026-05-19

`research_ledger` - это единая лента жизненного цикла рынков. Она нужна, чтобы владелец проекта и будущий dashboard видели не разрозненные таблицы, а понятное состояние каждой идеи: что найдено, что в watch, что отвергнуто, что стало paper signal, что уже resolved и чему система научилась.

## Зачем это нужно

До ledger память проекта уже была в базе, но была распределена по таблицам:

- `markets`
- `snapshots`
- `hidden_gem_reviews`
- `moonshot_reviews`
- `evidence`
- `resolution_maps`
- `actor_maps`
- `causal_factors`
- `scenario_trees`
- `premortems`
- `pre_bet_checklists`
- `analyses`
- `signals`
- `positions`
- `fills`
- `pnl_events`
- `outcome_learning_reviews`

Это правильно для хранения фактов, но неудобно для оператора. Ledger собирает эти факты в одну строку на рынок.

## Важный принцип

Ledger сейчас сделан как read-side слой, а не как ручная дублирующая таблица.

Это значит:

- факты остаются в нормализованных таблицах;
- статус рынка выводится из реальных записей;
- нет риска, что отдельная таблица ledger забудет обновиться;
- dashboard может читать один готовый агрегированный список.

## Tool

MCP tool:

```text
research_ledger(status="", lane="", limit=100, include_discovered=False)
```

Параметры:

- `status` - фильтр по lifecycle status;
- `lane` - фильтр по research lane;
- `limit` - максимум строк;
- `include_discovered` - показывать ли чисто найденные, но еще не затронутые рынки.

По умолчанию `include_discovered=False`, чтобы ledger показывал осмысленные рабочие элементы, а не весь сырой universe.

## Lifecycle statuses

Ledger использует такие состояния:

| Status | Значение |
|---|---|
| `discovered` | рынок найден и записан, но еще не изучался |
| `watch` | рынок интересен, но пока без сигнала |
| `deep_research` | рынок стоит глубоко исследовать |
| `needs_more_research` | уже есть checklist/research, но не хватает dossier |
| `approved_for_signal` | pre-bet checklist разрешил signal, нужно проверить свежесть snapshot |
| `no_signal` | анализ записан, но сигнал не прошел gates |
| `rejected` | рынок отвергнут, причина записана |
| `signal` | signal есть, но нет открытой active position |
| `open_position` | есть активная paper/live/hybrid position |
| `resolved_pending_learning` | рынок завершился, но outcome learning review еще не сделан |
| `learned` | исход разобран и lesson записан |

## Research lanes

Ledger пытается классифицировать рынок по линии исследования:

- `moonshot` - cheap optionality / high payout / speculative asymmetric side;
- `compounder` - mid-price 0.22-0.60, где важна высокая уверенность;
- `hidden` - hidden/neglected/source-asymmetry review;
- `unknown` - данных пока мало.

Это важно: SIGNAL не должен быть только машиной дешевых иксов. Ledger помогает dashboard держать moonshot, hidden и compounder идеи рядом, но различать их смысл.

## Поля строки ledger

Каждая строка содержит:

```text
condition_id
question
slug
vertical
theme_tags
status
priority
research_lane
current_yes_price
current_no_price
spread
liquidity
volume
snapshot_at
end_date
resolved
resolved_yes
model_probability_yes
confidence
edge
score
score_type
latest_decision
decision_reason
blocker
next_action
next_check_at
dossier_completeness
missing_dossier_blocks
dossier_counts
source_count
evidence_count
analysis_id
signal_id
position_id
latest_review_id
outcome_review_id
created_at
last_touched_at
stale_open_position
```

## Priority logic

Ledger выставляет priority не как инвестиционную рекомендацию, а как операционный приоритет:

- `critical` - resolved market без learning review;
- `high` - approved signal, deep research, stale open position;
- `medium` - watch / needs more research / active monitoring;
- `low` - rejected, learned, discovered, no_signal.

## Next action

Ledger возвращает `next_action`, чтобы dashboard мог показывать не просто статус, а следующий шаг:

- `run_api_research_enrichment`
- `collect_more_sources`
- `recheck_watch_candidate`
- `complete_dossier`
- `complete_missing_research`
- `record_analysis`
- `record_forecast_update`
- `monitor_position`
- `record_outcome_learning_review`
- `review_lessons`
- `no_action_until_new_catalyst`

## Как использовать

Обычный обзор рабочих элементов:

```text
research_ledger(limit=100)
```

Только watchlist:

```text
research_ledger(status="watch", limit=50)
```

Только compounder идеи:

```text
research_ledger(lane="compounder", limit=50)
```

Весь universe, включая нетронутые discovered markets:

```text
research_ledger(include_discovered=True, limit=300)
```

## Что это дает dashboard

Dashboard теперь может иметь одну центральную таблицу/ленту `Research Ledger`, где видно:

- какие идеи ждут внимания;
- что было отвергнуто;
- какие позиции открыты;
- где надо обновить forecast;
- где надо разобрать outcome;
- какие рынки уже имеют lessons;
- где dossier слабый;
- где следующий конкретный шаг.

Это следующий слой взросления проекта: SIGNAL начинает помнить не только “ставки”, а весь путь мысли.