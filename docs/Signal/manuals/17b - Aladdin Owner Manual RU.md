# Aladdin Owner Manual — RU

Практическое руководство по новой модели Signal (после Stage 0-6). Используй как «справочник за столом» во время рабочей сессии.

Парный документ для теории — [14 - Aladdin Upgrade Plan and Session Log.md](../reports/14 - Aladdin Upgrade Plan and Session Log.md). Baseline для будущих сравнений — [15 - Aladdin Smoke Run 2026-05-19.md](../reports/15 - Aladdin Smoke Run 2026-05-19.md). Источник доктрины — [00 - North Star.md](../core/00 - North Star.md).

---

## 0. Что это такое в одном абзаце

Signal — твой персональный research-терминал под Polymarket. Он сам сканирует рынок, находит кандидатов, считает риск, режет ставки под уже сидящие позиции, и помнит каждое исследование. Это **не торговый бот** — он ничего не покупает. Он показывает что смотреть, как сайзить, и заставляет тебя пройти через дисциплину дossier перед тем как взять позицию.

Главная философия (см. [00 - North Star.md](../core/00 - North Star.md)):

> imaginative intake, strict pre-bet research, hold-to-resolution learning

Идея фиксируется свободно (`record_moonshot_review` может говорить «это интересно»). Pre-bet checklist строгий. После резолюции — обязательный outcome review.

---

## 1. Утренняя сессия — за 7 шагов

Стандартный путь когда ты садишься работать. От 5 до 30 минут в зависимости от глубины.

### Шаг 1. `daily_research_brief()` — открой «панель»

Один вызов даёт всю утреннюю сводку:

```
daily_research_brief(horizon_days=14, discovery_limit=10)
```

Что вернётся, в порядке важности:
1. **portfolio** — что в позициях, по каким bucket'ам распределено, общее at-risk.
2. **catalysts** — что резолвится в горизонте N дней. Это самое важное — здесь видно concentration risk и предстоящие катализаторы.
3. **due_for_recheck** — `moonshot_next_step` маркеры (что мониторить и почему).
4. **pending_outcome_reviews** — резолвнутые позиции без post-mortem'а. Закрывай как можно быстрее, иначе learning loop ломается.
5. **incomplete_research** — досье с completeness <85%. Если рынок зашёл, dossier обязан быть полным.
6. **recent_discovery_candidates** — отголоски прошлых discovery-сканов.
7. **recommended_next_calls** — что движок думает делать дальше (пока статический список, в будущем будет state-aware).

**Что я ищу в первую очередь:** красные флаги в catalysts (>40% книги на одну неделю?) и pending_outcome_reviews (>0 = есть долг).

### Шаг 2. Если катализатор близко (≤3 дня) — иди в `market_research_memory(condition_id)`

Это вытащит весь dossier по этому рынку: analyses, evidence, actor_maps, causal_factors, scenarios, premortems, hidden_gem_reviews, текущий snapshot, signal_quality_reviews. Один вызов — полная картина «что мы знаем и где сейчас».

Если что-то поменялось (новость, цена сдвинулась) — пиши `record_forecast_update(...)` чтобы переоценить вероятность с явным `previous_probability_yes → updated_probability_yes` и причиной. **Не перетирай** старые forecast'ы — пиши новый update, история важна.

### Шаг 3. `discovery_scan()` — поищи новых кандидатов

```
discovery_scan(max_pages=10, max_per_strategy=12)
```

Возвращает ранжированный список markets с auto-scores (см. ниже). **Сильнейший сигнал — composite hit** (рынок матчит 2+ стратегии). Внимание сначала на них, потом на одиночные.

Если ничего интересного — это **нормально**. Stage 0 гейты затянуты специально чтобы 5 рынков в неделю было нормой, а не 18 за 3 дня.

### Шаг 4. Для топ-3 кандидатов — `backfill_price_history(condition_id, days=90)`

Это даёт CLOB-историю в `snapshots`, активирует `stale_price` стратегию и `auto_attention_gap_score`. Без этого scores могут быть нейтральными (0.5). 

Идемпотентно, можно вызывать повторно без вреда.

### Шаг 5. Re-run `discovery_scan` — посмотри как ranking изменился после backfill

Composite hits часто появляются именно после backfill, потому что без истории `stale_price` не матчится.

### Шаг 6. Выбери 1 кандидата для deep-research (см. раздел 4)

Не более одного нового кандидата за сессию. Pre-bet checklist строгий, его нельзя пройти за 5 минут.

### Шаг 7. После сессии — `finalize_daily_run(...)`

Это закрывает запись в таблице `daily_runs`. Идемпотентно за день. Помогает считать кост и активность.

---

## 2. Как читать `daily_research_brief` — отрывок-разбор

Пример вывода `portfolio` блока:

```
total_at_risk_usd: 260.19
total_at_risk_pct_bankroll: 22.6
by_vertical: {us_politics: 81.91, international_geopolitics: 74.15, ...}
by_archetype: {cheap_optionality: 96.21, ...}
by_theme: {iran_cluster: 28.37, us_primary_2026: 6.50}
by_deadline_week: {2026-W27: 112.90, ...}
```

**Что искать:**

- `total_at_risk_pct_bankroll > 50%` — стоп, не бери новых, разгружай.
- Любой vertical/archetype/theme >70% своего cap'а — больше не бери в этот bucket.
- **`by_deadline_week` с одной неделей >35% книги** — concentration shock risk. Если несколько резолюций в один день пойдут не по тезису, портфель уйдёт в минус сразу.
- `by_theme` — пустой не значит что нет clustering. Значит что разметки не было. Если ты видишь 3 Iran-related кандидата — пометь `set_market_tags(..., ["iran_cluster"])`, чтобы exposure cap сработал.

---

## 3. Как читать `discovery_scan` — что значат scores

Каждый кандидат:

```
score=47.8  [cheap_optionality+stale_price]  (international_geopolitics)
yes=0.895  vol=$54k  days=14.7
auto: attn=0.08  stale=0.82  liq=0.68  spr=0.83
Q: Will Woo Sang-ho win the 2026 Gangwon Province gubernatorial election?
```

### Strategies (теги в квадратных скобках)

| Стратегия | Что ловит | Когда верить |
|---|---|---|
| `low_volume_research_sweetspot` | $5-30k volume, 14-90 дней, normal spread, цена 0.10-0.90 | Где крупные desks игнорируют, а исследовать можно. **Доверять — если есть actor map.** |
| `stale_price` | Возраст >21 день, stdev цены <3% за 14 дней | Зрелый рынок «застрял» — ждёт катализатора. **Доверять — если ясен предстоящий триггер.** |
| `cheap_optionality` | yes ≤0.15 или ≥0.85, ликвидность есть, volume ≤$200k, 7-90 дней | Powell-style asymmetric payout. **Доверять — если есть mechanism, иначе lottery ticket.** |

**Composite hit (2+ стратегии)** — намного сильнее одиночного. Сегодня (см. baseline 2026-05-19) это: Gangwon, Armenia, Lebanon, Paxton.

### Auto-scores (нумерические компоненты)

| Score | Считается из | Высокий = |
|---|---|---|
| `attention_gap` | (1-volume_share)·age_share·liquidity_share | Рынок старый + ликвидный, но никто не торгует. Hidden gem candidate. |
| `stale_price` | 1 - stdev(14d)/0.05 | Цена не двигалась. Ждёт катализатора. |
| `liquidity` | liq / $25k normalizer | Можно зайти без шока цены. |
| `spread` | 1 - spread/MAX_SPREAD | Узкий спред — дешёвое исполнение. |

Веса в combined: 0.40 attn + 0.25 stale + 0.10 liq + 0.10 spread + 0.15 strategy_bonus. **Attention_gap доминирует** — это намеренно, чтобы Fed-style markets с $5M объёмом не лезли в топ.

### На что обращать внимание

- `attn=0.00` — **рынок уже на радаре у всех.** Даже если он matches cheap_optionality, скорее всего alpha нет.
- `stale=1.00` — слишком ровный. Иногда означает «никто не торговал», но иногда — «полная стагнация и rerate близок».
- `days_to_resolution` <10 — времени мало на исследование и катализатор, риск headline-bet растёт.
- `days_to_resolution` >60 — другая категория, hold-to-resolution с большим окном неопределённости.

---

## 4. Pipeline глубокого исследования — порядок и инструменты

Если хочешь зайти в позицию по новому кандидату, **обязательная** последовательность:

### 4a. Resolution-first: `record_resolution_map(...)`

Самый важный шаг. До любого «тезиса» — что **конкретно** считается YES, что NO, какие источники, есть ли wording trap.

```
record_resolution_map(
  condition_id=...,
  yes_criteria="конкретное условие резолюции YES",
  no_criteria="всё остальное",
  primary_resolution_source="официальный источник",
  deadline_text="точная дата UTC",
  ambiguity_cases="recount? RCV? withdrawal?",
  non_qualifying_events="что НЕ засчитается (polling leads, endorsements)",
  required_artifact="что нужно чтобы рынок резолвнулся",
  source_quality_score=0.85, deadline_clarity_score=0.95,
)
```

Если `completeness_score < 70` — тезис ещё не готов. Это **гейт**, не косметика.

### 4b. Evidence: `record_evidence(...)` минимум ×2

Каждое утверждение — отдельная запись со stance (YES/NO/MIXED/NEUTRAL), strength, reliability, freshness. Источники реальные, с url и `published_at`.

«Слабых» evidence (strength<0.3) можно записать — это нормальная база для будущей переоценки. **Что нельзя** — пропустить шаг и сделать сразу `record_analysis`.

### 4c. Actor map: `record_actor_map(...)` минимум ×1, лучше 2-3

Кто двигает исход? Их incentives, constraints, likely_action. Это вытаскивает тебя из headline-mode в incentive-mode.

### 4d. Causal factors: `record_causal_factor(...)` минимум 2

Не narratives, а механизмы. Каждый с direction (YES/NO/MIXED/UNKNOWN), importance, uncertainty, observable_signal, next_check_at.

`next_check_at` важно — он попадёт в `due_for_recheck` в следующем `daily_research_brief`.

### 4e. (Опционально) `record_scenario(...)` ×3

Несколько путей к резолюции. Сумма probabilities ≈ 1.0. Полезно когда есть >2 возможных исходов.

### 4f. `record_premortem(...)`

Скептический проход. **Если тезис ошибочный — почему?** failure_mode + disconfirming_signal + probability_if_wrong.

Можно пропустить только если уверенность <0.45 (низкая) — иначе обязательно.

### 4g. `record_hidden_gem_review(...)` — общая оценка

После сбора dossier — review с 7 scoring компонентами. Auto-scores из discovery (attention_gap, stale_price, liquidity, spread) можно использовать как defaults, остальные 3 (evidence_asymmetry, catalyst, resolution_clarity) ты ставишь сам.

### 4h. `record_pre_bet_checklist(...)`

Главный гейт. Возвращает `decision: needs_more_research | enter | skip`. Если `needs_more_research` — иди заполняй что не хватает, не игнорь.

### 4i. `exposure_check(condition_id, proposed_stake_usd, primary_archetype=...)`

Что произойдёт с буджетом если возьмёшь N$? Покажет breaches по vertical/archetype/theme/deadline_week/single_market.

### 4j. `record_analysis(probability_yes, confidence, reasoning, sources)`

Финальный шаг. Считает edge, проходит ли через все Stage 0 гейты, sizing с shrinkage. Создаёт position + paper fill автоматически.

**Между 4i и 4j**: если exposure_check показал breach по какому-то bucket — это **остановка**. Не лезь, переделай sizing или возьми другой market.

---

## 5. Sizing и exposure caps — почему движок режет ставку

### Базовая формула

```
base_stake = BANKROLL × KELLY_FRACTION × edge × confidence
           = $1150 × 0.25 × edge × confidence
```

Для edge=0.07 conf=0.60 → base = $12.08.

### Shrinkage

```
shrinkage_factor = 1 - highest_existing_share
```

где `highest_existing_share` = максимум по всем bucket'ам (vertical/archetype/theme/deadline_week/single_market), которые затронет новая позиция.

Если в `iran_cluster` уже сидит $200 из $287 cap'а (70%), и ты хочешь добавить Iran-related рынок — `shrinkage = 0.30`. Base $12 → recommended $3.60.

Это правильно. Если ты уже глубоко в нарративе, новые ставки в этом же нарративе должны быть мельче. **Не борись с этим** — это защита.

### Clamps

```
recommended_stake = clamp(base × shrinkage, BET_MIN_USD=1, BET_MAX_USD=30)
```

`BET_MAX=$30` — не от страха, а от того, что paper-money экспериментальная. Если хочешь больше — поднимай через env, но это серьёзное решение.

### Когда caps реально срабатывают

| Cap | Текущее использование (на 2026-05-19) | Срабатывает когда |
|---|---|---|
| `vertical` (40% = $460) | us_politics 18%, intl 16% | Стоит вернуться позже, разгрузить |
| `archetype` (30% = $345) | cheap_optionality 28% | Один архетип не должен доминировать |
| `theme` (25% = $287.50) | iran_cluster 10% | Нарратив-кластер — самая важная защита |
| `deadline_week` (50% = $575) | W27 = 20% | Чтобы single-day shock не убил книгу |
| `single_market` (10% = $115) | макс ~5% | Никакой market не >10% bankroll |

---

## 6. После резолюции — outcome learning loop

Это **главная** часть. Без этого все остальные слои — украшение.

### Шаг 1. `resolve_closed()` — pull актуальные резолюции

Дёрни в начале каждой сессии. Возвращает количество замаркированных-резолвом рынков + посчитанные realized_pnl.

### Шаг 2. `pending_outcome_reviews()` — что закрыто, но без post-mortem'а

Этот вызов уже в daily_research_brief, но проверь ещё раз. Если count >0 — это долг, который нужно закрыть **до** входа в новые позиции.

### Шаг 3. Для каждого pending — `record_outcome_learning_review(...)`

```
record_outcome_learning_review(
  condition_id=...,
  outcome_side="YES"|"NO",
  predicted_side="YES"|"NO",
  why_right_or_wrong="конкретная причина: тезис верен/нет, mechanism сработал/нет",
  outcome_summary="что реально произошло",
  resolution_error=0|1,        # неправильно прочитали условия резолюции
  probability_error=0|1,       # сильно ошиблись в вероятности
  evidence_error=0|1,          # источники не учли
  timing_error=0|1,            # промахнулись по timing
  sizing_error=0|1,            # сайз был неправильный
  luck_factor=0.0-1.0,         # сколько успех/провал — удача
  repeatable_lesson="что я запомню и применю в будущем",
  rule_update="нужно ли менять config или strategy? (часто None)",
)
```

**Самый важный поле — `repeatable_lesson`.** Это то, что попадает в долгосрочную память системы.

Категории error боксов — это компас. Если у тебя за месяц 4 `evidence_error=1` — significant pattern, нужно лучше работать с источниками.

### Шаг 4. (Stage 4 когда будет) — `gate_recommendations()`

После накопления ≥10 outcome reviews — система начнёт предлагать корректировки гейтов по архетипам. Сейчас это ещё не оживлено — нужны данные.

---

## 7. Регулярное обслуживание

### Backfill price history (раз в неделю минимум)

Для каждого active candidate и каждой open position, у которой <10 snapshots:

```
backfill_price_history(condition_id, days=90)
```

Это нужно для `stale_price` стратегии и для recovery от старых рынков, у которых fetch_candidates даёт одну точку.

### Тематические теги (по мере появления кластеров)

Когда видишь что 3+ кандидата в одной теме — пометь явно:

```
set_market_tags(condition_id, tags=["iran_cluster"])
# или
set_market_tags(condition_id, tags=["us_primary_2026", "governor_race"])
```

Это даёт theme cap защиту.

### Реклассификация (когда меняешь VERTICALS keywords)

Если правишь `config.VERTICALS` — нужно прогнать reclassification по существующим рынкам, иначе старые останутся в legacy bucket'ах. Сейчас это разовый ручной шаг (SQL update + classifier), в будущем — отдельный tool.

### `signal_regression_benchmark` (раз в неделю)

```
signal_regression_benchmark(active_only=True)
```

Должен оставаться 2/2 (Figure F.03, Gemini reasoning flagship). Если упал — гейты сдвинулись и нужно понять почему.

### Тесты (после каждого изменения логики)

```
cd bot && python -m pytest -q
```

106 тестов сегодня. После любых правок `lib/` или `tools/` — прогон обязателен.

---

## 8. Известные ограничения — где не доверять движку

### Discovery

- **Очень новые рынки** (<24 часа на Polymarket) могут не иметь backfill истории → `stale_price` всегда False, attention_gap занижен. **Решение:** `backfill_price_history` сразу как увидишь market.
- **Узкие сектора** (sports prediction analogs, exotic resolution sources) могут не попадать ни в одну vertical → теряются. Сейчас 4 markets всё ещё в legacy `geopolitics` bucket — не реклассифицированы.
- **Volume может быть фейковым** — wash-trading на низко-ликвидных markets. Если `auto_attention_gap` высокий, но top-of-book спред резкий — что-то странное.

### Sizing

- **Shrinkage слишком агрессивный для clean buckets.** Если у тебя пустой archetype, и ты хочешь зайти на $20 — shrinkage всё равно может быть 0.85 потому что **другой** bucket нагружен. Это намеренно — но иногда хочется явно forc'ить.
- **`BET_MAX=$30` ограничивает** даже на очень сильных сигналах. Это потолок для paper-money режима.

### Calibration

- **Stage 4 ещё не активен.** `archetype_strengths_weaknesses` пуст пока не накопится ≥10 резолюций. Сейчас веса и пороги — best-effort guess.
- **`forecast_quality_report`** показывает Brier/log score только для резолвнутых markets. У нас 0 резолюций → пустой отчёт.

### Pre-bet checklist

- **`needs_more_research` иногда срабатывает на полные dossiers** если completeness <85%. Если уверен — можно override через `decision="enter"` параметр, но это явная сознательная decision.

### Vertical classifier

- Keyword-based. Никогда не будет идеальным. **Spot-check** результаты — особенно когда видишь странную классификацию (типа Armenia в us_politics, что мы недавно фиксили).

---

## 9. Аварийные процедуры

### «Что-то импортится с ошибкой»

```bash
cd bot && python -c "import mcp_server; print('OK', len(mcp_server.mcp._tool_manager._tools))"
```

Если падает — сделай `python -m py_compile <file>` на каждом изменённом файле.

### «Tests упали»

```bash
cd bot && python -m pytest -v 2>&1 | tail -30
```

Если упал `test_record_analysis::test_fresh_snapshot_passes_all_gates_and_emits_signal` — гейты сдвинулись. Если `test_pnl::*` — формула realized_pnl поломана.

### «Demo signal попал в живую БД»

Если случайно сделал record_analysis с reasoning="DEMO" — удаляй вручную:

```sql
DELETE FROM fills WHERE position_id IN (SELECT id FROM positions WHERE signal_id IN (SELECT id FROM signals WHERE reasoning LIKE '%DEMO%'));
DELETE FROM positions WHERE signal_id IN (SELECT id FROM signals WHERE reasoning LIKE '%DEMO%');
DELETE FROM analyses WHERE reasoning LIKE '%DEMO%' OR notes LIKE '%DEMO%';
DELETE FROM signals WHERE reasoning LIKE '%DEMO%';
```

Сделай VACUUM после.

### «discovery_scan возвращает 0 кандидатов»

Скорее всего гейты слишком строгие для текущего рыночного состояния. Поиграй с `max_pages=20` (больше markets на входе) и `max_per_strategy=20`. Если всё равно пусто — Polymarket в моменте действительно тихий, и это нормально.

### «exposure_check блокирует все мои попытки»

Значит book перегружен. Проверь `portfolio_snapshot.total_at_risk_pct_bankroll`. Если >40% — пора **разгружать**, не нагружать.

### «MTM PnL выглядит подозрительно (слишком плюс или минус)**

Возможно `mark_to_market_all` использует stale snapshots. Сначала прогон `backfill_price_history` для каждой open position, потом снова `mark_to_market_all`.

---

## 10. Шпаргалка — все 51 инструмент сгруппировано

### Открыть сессию
- `daily_research_brief(horizon_days, discovery_limit)`
- `daily_run_status(date=None)`
- `portfolio_snapshot()`
- `resolve_closed()`
- `pending_outcome_reviews()`

### Найти кандидатов
- `discovery_scan(strategies, max_per_strategy, vertical, max_pages)`
- `discovery_overlap_with_open_positions()`
- `fetch_candidates(max_markets, vertical)` — старый способ через volume desc; **избегай** для discovery
- `get_market_details(condition_id)`
- `moonshot_watchlist()` / `hidden_gem_watchlist()`

### Подготовить рынок к исследованию
- `backfill_price_history(condition_id, days)`
- `set_market_tags(condition_id, tags, source="manual")`
- `market_research_memory(condition_id)`

### Записать dossier (порядок важен)
1. `record_resolution_map(...)`
2. `record_evidence(...)` ≥2
3. `record_actor_map(...)` ≥1
4. `record_causal_factor(...)` ≥2
5. `record_scenario(...)` опционально ×3
6. `record_premortem(...)`
7. `record_anomaly(...)` если есть
8. `record_hidden_gem_review(...)` или `record_moonshot_review(...)`

### Войти в позицию
- `exposure_check(condition_id, proposed_stake_usd, primary_archetype)`
- `record_pre_bet_checklist(...)`
- `record_analysis(condition_id, probability_yes, confidence, reasoning, sources)` ← создаёт signal + position + fill
- `record_fill(position_id, side, price, shares, stake_usd, venue)` ← когда вошёл реально

### Мониторить позиции
- `mark_to_market_all()`
- `catalyst_calendar(horizon_days)`
- `due_for_recheck()`
- `repricing_alerts(min_abs_move, hours)` (если работает в твоей версии)
- `anomaly_inbox()`
- `live_positions_summary()`
- `open_signals()`

### Обновить тезис
- `record_forecast_update(condition_id, updated_probability_yes, trigger, reason, sources)`
- `contrarian_brief(condition_id)` — резюме causal dossier

### Закрытие и обучение
- `record_outcome_learning_review(...)` ← главное
- `record_signal_quality_review(...)` — early-repricing ретро (open positions)
- `record_signal_archetype(...)` — классификация архетипа
- `false_negative_review(min_move, limit)`

### Отчёты и калибровка
- `forecast_quality_report()` — Brier, log score, calibration buckets
- `signal_quality_report()`
- `performance_report()`
- `vertical_breakdown()`
- `analysis_log(limit, decision)`
- `incomplete_research_queue(limit)`
- `research_completeness_score(condition_id)`
- `market_move_after_analysis(condition_id, limit)`

### Регрессия / health-check
- `signal_regression_benchmark(active_only)` ← 2/2 должно держаться
- `create_signal_benchmark_case(...)` — добавить новый regression case
- `resolution_first_queue()` — open markets без resolution_map

### Закрытие сессии
- `finalize_daily_run(markets_seen, deep_analyzed, signals_emitted)`

---

## 11. Один параграф напоследок

Aladdin не делает тебя умнее. Он делает невозможным забыть пройти через дисциплину. Если ты захочешь взять «cheap optionality на $15» без actor map'а — pre_bet_checklist скажет `needs_more_research`. Если ты возбудился на 4-й Iran-сигнал — `exposure_check` срежет ставку до $3. Если ты забудешь записать outcome learning после резолюции — `pending_outcome_reviews` появится в утренней панели и не уйдёт пока не закроешь.

Это и есть «no invisible decisions» из North Star. Не для красоты — для калибровки. Через 30/60/90 дней у тебя будет первый честный взгляд на то, что Claude (и ты) реально умеешь, а где systematic blindspots.

Удачи, и **не торопись войти в позицию** — Polymarket будет работать и завтра.
