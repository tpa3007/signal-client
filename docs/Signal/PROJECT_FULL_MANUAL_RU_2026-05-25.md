# Signal / Forager: полный русский manual проекта

Дата: `2026-05-25`  
Рабочая папка: `C:\Signal`  
Главная БД Signal: `bot/bot.db`  
Главная БД Forager: `bot/forager.db`

Этот документ нужен, чтобы перестать держать проект в голове. Он описывает, зачем существует Signal, где заканчивается Forager и начинается Signal, какие команды запускаются, какие файлы и таблицы они трогают, как устроен поиск кандидатов, как работает ручной слой, как происходит запись сигналов, как устроено обучение, и что сейчас записано в БД по ставкам.

---

## 1. Короткая суть проекта

Signal - это локальная research OS для Polymarket. Его задача не в том, чтобы автоматически торговать, а в том, чтобы находить рынки с потенциальным edge, прогонять их через строгую исследовательскую воронку и сохранять весь след в SQLite/markdown.

Главная формула проекта:

```text
Forager discovers.
Signal decides.
Learning calibrates both.
```

По-русски:

- **Forager** ищет источники, слабые сигналы, противоречия, аномалии, claims, hypotheses и packets.
- **Signal** принимает решение: reject / watch / needs_more_research / approved_for_signal / paper signal.
- **Learning loop** потом смотрит, где мы были правы, где ошиблись, какие источники, аркетипы и формулы подвели.

Ключевая философия: меньше сигналов, но с понятной причинной моделью, источниками, resolution map, premortem и audit trail.

---

## 2. Главные директории

| Путь | Что это |
|---|---|
| `bot/` | Основной Signal: команды A/B/C/D/E/F/G/G2/H/M/P/R, SQLite schema, MCP tools, portfolio, gates. |
| `forager/` | Upstream research engine: поиск, crawl, extraction, graph, packets, SDV. |
| `docs/Signal/` | Архитектура, отчёты, manuals, technical notes. |
| `dashboard-web/` | Web-dashboard для визуализации состояния Signal из export data. |
| `research/` | Экспериментальные исследовательские скрипты/датасеты. |
| `bot/lib/` | Чистые helper-модули: scoring, gates, kelly, ledger, execution, discovery, integrations. |
| `bot/tools/` | MCP/project tools, которыми агент должен писать в БД вместо прямых insert-скриптов. |
| `bot/tests/` | Регрессионные тесты для gates, commands, portfolio, Forager handoff, discovery. |

---

## 3. Главные БД

### Signal DB: `bot/bot.db`

Signal DB хранит рынки, snapshots, research dossier, signals, positions, fills, PnL, workflow journal и learning records.

Основные таблицы:

| Таблица | Назначение |
|---|---|
| `markets` | Один ряд на рынок Polymarket: question, slug, end_date, vertical, resolved. |
| `snapshots` | Исторические цены, liquidity, spread, entry prices. |
| `market_tags` | Темы и кластеры рынков. |
| `evidence` | Source-backed evidence. |
| `resolution_maps` | Что считается YES, NO, ambiguous. |
| `actor_maps` | Участники/акторы рынка. |
| `causal_factors` | Механизмы, которые двигают outcome. |
| `scenario_trees` | YES/NO/uncertainty paths. |
| `premortems` | Почему тезис может умереть. |
| `pre_bet_checklists` | Gate перед сигналом. |
| `analyses` | Analysis record: probability, edge, decision. |
| `signals` | Формальный signal. |
| `positions` | Намерение/позиция: side, entry, stake, status. |
| `fills` | Реальные или paper fills. |
| `pnl_events` | mark/exit/resolution PnL. |
| `outcome_learning_reviews` | Разбор исходов и ошибок. |
| `workflow_runs` / `workflow_steps` | Журнал запусков. |
| `signal_quality_reviews` | Оценка качества сигналов. |

Ledger metadata для сравнения эпох:

- `signal_generation_epoch`: `legacy`, `gated_v1`, `gated_v2_after_MR`, `operator_approved`, `manual_real`;
- `edge_archetype`: `resolution_mechanics`, `provider_metric`, `local_polling`, `central_bank_sequence`, `celebrity_overpricing`, `cross_platform_divergence`, `cheap_tail`, `geopolitical_catalyst`, `deadline_decay_short`, `primary_field_structure`;
- `confidence_source`: `manual_human`, `codex_high`, `opus`, `ollama_draft`, `automated_score`, `forager_packet`, `operator_override`;
- `approval_strength`: `A/B/C/D/F`;
- `post_entry_review_required` + reason.

Цель этих полей: не смешивать legacy-плюс с gated-плюсом и видеть, кто реально был мозгом сигнала: человек/strong LLM, Forager packet, Ollama draft или старый automated score.
| `triage_scores` | История triage/discovery scores. |

### Forager DB: `bot/forager.db`

Forager DB хранит не ставки, а исследовательский след:

- threads;
- raw search items;
- promoted sources;
- crawled documents;
- claims;
- entities;
- entity mentions;
- claim relations;
- contradiction clusters;
- evidence drafts;
- packets;
- translation queue;
- translated documents.

---

## 4. Уровни workflow: L0-L5

Проект разделяет уровни работы, чтобы агент не прыгал сразу к ставке.

| Уровень | Смысл | Что разрешено |
|---|---|---|
| L0 | Discovery / intake | Найти рынки, обновить `markets`, `snapshots`, `market_tags`. |
| L1 | Triage | Отобрать кандидатов, распределить по lane/status. |
| L2 | Deep research / dossier | Evidence, resolution map, actor map, causal factors, scenarios, premortem, checklist. |
| L3 | Signal commit | Только после gate. Создать paper signal/position/fill. |
| L4 | Learning | Outcome reviews, false positives, calibration, benchmark. |
| L5 | Maintenance / repair | Чистка legacy, миграции, integrity audits. |

Главное правило: **L0-L2 не создают ставку**. Ставка появляется только в L3 через Command C / `aladdin_signal_commit` или через отдельный manual real trade path, если человек уже сделал реальную сделку руками.

---

## 5. Полный современный цикл

Текущий основной цикл:

```text
G -> G2 -> M -> R -> B -> D -> C
```

Дополнительные команды:

```text
P  - private market intelligence before/alongside G
F  - мониторинг открытых paper-позиций
E  - resolution tracker / outcome learning
H  - portfolio intelligence / Kelly / correlation
run_cycle.py - оркестратор и audit wrapper
```

Почему появились M и R:

- раньше G/G2 формульно находили кандидатов;
- B автономно копал;
- D слишком много смотрел на SDV;
- C мог создать paper signal из технически красивого, но интеллектуально слабого пути.

Теперь:

- **M** заставляет G2 пройти через ручной/strong-LLM shortlist desk;
- **R** превращает кандидата в конкретный research memo;
- **B** должен отвечать на decisive questions, а не просто “искать в интернете”;
- **D** не должен принимать SDV как инвестиционную вероятность.

---

## 6. Command G - широкий скан Polymarket

Файл: `bot/run_command_g.py`

Назначение: просканировать много рынков Polymarket, собрать universe, посчитать первичные признаки и записать широкий список кандидатов.

Главные output-файлы:

- `bot/candidates_wide.json`;
- `bot/triage_report.json`;
- `bot/g_scan_queue.py`.

Что делает G:

- читает рынки Polymarket;
- фильтрует уже открытые позиции и недавно исследованные рынки;
- считает discoverability / liquidity / volume / spread;
- классифицирует вертикали;
- ищет stale price, low-volume sweet spot, cheap optionality, compounders;
- добавляет local-language/info-asymmetry clues;
- может писать LLM handoff/vibe-check, но не должен сам решать ставку.

Главный риск G: если API/пагинация/фильтры ограничивают scan, можно просканировать меньше 10k+ рынков и пропустить edge. Поэтому cycle report всегда должен показывать `raw_rows`, `accepted_rows`, `candidate_universe_total`.

---

## 7. Command G2 - hidden gem ranker

Файл: `bot/run_command_g2.py`

Назначение: взять `candidates_wide.json` и сжать до top-25 hidden gem candidates.

Основные критерии:

1. **Language arbitrage** - локальный язык, локальные источники, неочевидные English traders.
2. **Cross-platform divergence** - Metaculus / PredictIt / Kalshi / Manifold / GJO против Polymarket.
3. **Upcoming catalyst** - близкая дата, vote, meeting, deadline.
4. **Narrative bubble short** - crowd overconfidence в high-YES рынках.

Output:

- `bot/g2_top25.json`;
- `bot/forager_queue_auto.py`.

Каждый кандидат из G2 теперь дополнительно получает `g2_review_frame`: `why_ranked`, `why_not_edge_yet`, `what_must_be_true_for_edge`. Это намеренно переименовывает смысл G2: он находит anomalies/suspicions, но не доказывает edge и не оценивает probability.

Важная свежая правка: G2 теперь не должен награждать экстремальные рынки типа 1% или 99% только за “локальный язык + близкая дата”. Если нет конкретного divergence/contradiction/bubble-short setup, score capped.

---

## 8. Command M - manual shortlist desk

Файл: `bot/run_command_m.py`

Назначение: превратить top-25 G2 в маленькую очередь для R/B. Это ручной/strong-LLM фильтр до траты Tavily/Brave.

Статусы M:

- `b_candidate` - можно тратить B;
- `watch` - интересно, но нужен человек;
- `reject` - не тратить B.

Output:

- `bot/manual_shortlist_queue.py`;
- `bot/manual_shortlist_report.md`.

Свежая правка: M больше не отправляет 0/100-ish рынки в B без конкретного edge. Также “цена researchable” и “near deadline” больше не считаются самостоятельным edge-path.

---

## 9. Command R - reasoning memo gate

Файл: `bot/run_command_r.py`

Назначение: перед B создать человеческий/LLM-readable memo.

Output:

- `bot/forager_queue_reasoned.py`;
- `bot/reasoning_memos.json`;
- `bot/reasoning_memos.md`.

Что добавляет R:

- side under consideration;
- archetype;
- `edge_thesis`: структурная гипотеза ошибки рынка;
- `market_mechanics`: отдельная карта механики резолюции до B;
- resolution read;
- why market may be wrong;
- decisive questions;
- source plan;
- avoid sources;
- required evidence;
- stop rules;
- `operator_review` placeholder.

Ключевой смысл: B не должен “искать вообще”; он должен ответить на конкретные вопросы, без которых D не имеет права approve.

`edge_thesis` фиксирует: side, current price, implied probability, edge type, почему рынок может ошибаться, что изменит мнение, какие decisive/disconfirming sources нужны, max uncertainty и anti-signal flags. Это нужно, чтобы B копал не “рынок вообще”, а конкретную гипотезу mispricing.

`market_mechanics` фиксирует до B: `yes_resolves_if`, `no_resolves_if`, `canonical_source`, `resolution_authority`, `deadline`, `deadline_timezone`, provider metric/lag для private-company markets, ambiguity risks, `can_event_happen_and_resolve_no`, `can_resolve_50_50` и `verification_status`. Это отдельный объект, потому что рынок может быть фундаментально “правильным”, но резолвиться иначе из-за правил/провайдера/часового пояса.

---

## 10. Command B - Forager deep research

Файл: `bot/run_command_b.py`

Назначение: взять очередь из R и запустить Forager core loop.

Output:

- `bot/forager_results.json`;
- записи в `bot/forager.db`;
- handoff context в `bot/llm_handoff/`.

Что делает B:

- запускает decisive research pass по research_plan из R;
- добавляет operator supporting URLs как seed sources;
- запускает Telegram/open-web/local-polls/structural pre-research;
- запускает Forager `CoreResearchLoopRequest`;
- собирает packet, SDV, blockers, claims, evidence drafts;
- не создаёт сигнал.

Свежая правка: B фильтрует нерелевантные fallback hits. Если Tavily/Brave не дают нормальных результатов, B теперь должен честно ставить `search_backend_degraded`, а не считать FRED/левый Metaculus “найденными источниками”.

---

## 11. Command D - Signal L2 dossier gate

Файл: `bot/run_command_d.py`

Назначение: мост Forager -> Signal dossier.

D берёт `forager_results.json` и очередь R, затем:

- upsert market;
- пишет resolution map;
- пишет evidence;
- пишет actor map;
- пишет causal factors;
- пишет scenario trees;
- пишет premortem;
- запускает pre-bet checklist;
- выдаёт `dossier_results.json`.

Раньше D слишком зависел от SDV. Сейчас SDV трактуется как **research quality score**, а не как probability/edge. Если оператор вручную дал probability + supporting evidence, D может пропустить low-SDV dossier, но только при явном operator approval.

Дополнительные hard gates Signal 2.0:

- `search_backend_degraded` из B блокирует approval, если нет явного operator override с источниками;
- `needs_market_mechanics` блокирует reasoned candidates, пока mechanics не заполнены или явно не verified оператором;
- `anti_signal_flags` блокируют cheap lottery / near-certain / thin-edge ловушки;
- `source_confidence` отделяет качество источников от количества найденных документов;
- `causal_confidence` проверяет, двигают ли источники вероятность resolution, а не просто подтверждают, что тема существует.

---

## 12. Command C - paper signal commit

Файл: `bot/run_command_c.py`

Назначение: единственный стандартный путь создать paper signal после D.

C:

- читает `dossier_results.json`;
- берёт только approved markets;
- требует explicit operator handoff: `operator_approved`, `operator_probability`, verified market mechanics, reject-reason/disconfirming/cluster checks;
- вызывает validate gate;
- создаёт `signals`, `analyses`, `positions`, `fills`;
- всегда paper-only;
- fail closed: если нет approved, не создаёт ничего.

Real money здесь запрещён.

Новая защита: Command C больше не формализует сигнал только потому, что D написал `approved_for_signal`. D должен передать операторский handoff. Это защищает от ситуации, где automated packet выглядит аккуратно, но человек/strong LLM ещё не проверил market mechanics, disconfirming evidence и portfolio cluster risk.

---

## 13. Command F - monitor open paper positions

Файл: `bot/run_command_f.py`

Назначение: lightweight refresh по открытым позициям и рекомендация: HOLD / REVIEW / EXIT.

Семантика:

- `HOLD` - тезис пока жив, нет сильного нового противоречия.
- `REVIEW` - надо руками посмотреть: SDV упал, появились contradictions, source quality слабая, близкий expiry.
- `EXIT` - тезис сломан или позиция stale near-expiry без evidence.

F не трогает реальные деньги. Он пишет `monitor_results.json` и служит alarm layer.

---

## 14. Command E - resolution tracker / outcome learning

Файл: `bot/run_command_e.py`

Назначение: проверить закрывшиеся рынки, отметить resolution, посчитать PnL, записать learning review.

Output:

- `resolution_report.json`;
- `outcome_learning_reviews`;
- `pnl_events`.

Новая learning taxonomy записывается в `outcome_learning_reviews.error_taxonomy_json` и `primary_error_type`. Базовые классы ошибок: `wrong_resolution_read`, `stale_source`, `overtrusted_local_poll`, `narrative_overfit`, `catalyst_overweight`, `liquidity_trap`, `correlated_exposure`, `false_cross_platform_divergence`, `provider_metric_misread`, `deadline_misread`, `model_overconfidence`, `operator_override_bad`, `search_backend_degraded_but_approved`. Это нужно, чтобы Learning мог менять веса G2/M/R/D по типам ошибок, а не просто писать красивые retrospectives.

---

## 14.1. Golden Cases / Warning Cases

Подробный протокол: `docs/Signal/protocols/29 - Golden and Warning Cases RU.md`.

Эта секция фиксирует не абстрактные правила, а канонические ledger-примеры, на которых Signal должен учиться.

Golden cases:

- **Kim Kyung-soo YES** - local polling + Korean-language source asymmetry + underfollowed regional election.
- **RBA hike NO** - central-bank sequence / policy-mechanics mispricing.
- **GPT-6 before GTA VI NO** - resolution-clause / weird market-mechanics edge.
- **Spencer Pratt NO** - celebrity overpricing vs electoral reality.
- **OpenAI $950B NO** - candidate golden case only if NPM/provider mechanics are verified.

Warning cases:

- **OpenAI not IPO YES** - model/timeline overconfidence.
- **Gemini release markets** - wording/release ambiguity.
- **Sorin Grindeanu PM YES** - cheap optionality trap.
- **Israel/Iran geopolitical tails** - geopolitical plausibility is not resolution probability.

Operational rule:

```text
Every serious candidate should answer:
1. Which golden case does it resemble?
2. Which warning case could it secretly be?
3. What decisive fact separates the two?
4. Has that fact been checked with relevant and disconfirming sources?
```

G2 may only raise suspicion. M/R/D/E must use these cases as quality templates and trap detectors.

---

## 15. Command H - portfolio intelligence

Файл: `bot/run_command_h.py`

Назначение: посмотреть портфель как портфель, а не набор отдельных рынков.

H:

- грузит open positions;
- тянет live prices;
- считает Kelly/EV;
- группирует коррелированные clusters;
- пишет sizing/rebalance recommendations.

---

## 16. Command P - private market intelligence

Файл: `bot/run_command_p.py`

Назначение: отдельный workflow для новых Polymarket рынков по private-company valuation через Nasdaq Private Market.

Почему нужен P: такие рынки резолвятся не “реальной стоимостью компании”, а конкретной provider metric, например NPM Price, с cadence/lag/rules.

Output:

- `bot/private_market_candidates.json`;
- `bot/private_market_report.md`;
- `bot/private_market_forager_queue.py`;
- `bot/private_market_queue_reasoned.py`.

---

## 17. Command A - legacy/validator intake

Файл: `bot/run_command_a.py`

Исторически A был Signal -> Forager candidate intake. Сейчас Command G/G2/M/R стали основным discovery route. A используется как лёгкий validator/enricher очереди, в том числе с Ollama drafts, если поля пустые.

---

## 18. run_cycle.py - orchestration/audit wrapper

Файл: `bot/run_cycle.py`

Назначение: запускать цепочку и проверять artifacts между шагами.

Пример:

```powershell
cd C:\Signal\bot
..\.tools\python312\python.exe run_cycle.py
```

Default mode is safe/operator-first: `G -> G2 -> M -> R`. It writes reasoning memos and stops before B/D/C so a human/Codex/Opus layer can judge the candidates.

Extended modes:

```powershell
..\.tools\python312\python.exe run_cycle.py --mode scan_only
..\.tools\python312\python.exe run_cycle.py --mode research_only --from R --to D
..\.tools\python312\python.exe run_cycle.py --mode no_commit --from G --to D
..\.tools\python312\python.exe run_cycle.py --mode paper_commit_after_operator --from B --to C
```

Что делает:

- проверяет required_before/expected_after;
- пишет cycle_report `.json` и `.md`;
- считает сколько рынков реально scanned;
- показывает warnings: 0 approved, incomplete operator review, degraded B, stale F и т.п.

---

## 19. Как происходит поиск и отбор

### Stage 1: Polymarket universe

G получает рынки с Polymarket, сохраняет markets/snapshots и строит universe. Важные поля:

- `condition_id`;
- `question`;
- `slug`;
- `yes_price`, `no_price`;
- `spread`;
- `volume`, `liquidity`;
- `end_date`;
- `vertical`;
- `theme_tags`.

### Stage 2: first-pass scoring

Смотрятся:

- цена: дешёвый moonshot, mid-price compounder, high-confidence bubble;
- ликвидность и спред;
- свежесть/стабильность цены;
- close catalyst;
- language asymmetry;
- cross-platform divergence;
- existing portfolio exposure;
- был ли рынок недавно исследован.

### Stage 3: G2 hidden-gem compression

G2 должен найти не просто популярные рынки, а те, где может быть информационная асимметрия:

- корейские/румынские/арабские/персидские local-language рынки;
- рынки с misunderstood resolution;
- private company valuation mechanics;
- platform divergence;
- narrative bubbles.

### Stage 4: M ручной desk

M - это место, где умная модель/человек должны сказать: “да, это выглядит как реальный edge-path” или “нет, формула обманулась”.

Хороший кандидат для B:

- есть конкретный вопрос, который можно доказать источниками;
- есть вероятная причина, почему Polymarket ошибается;
- цена не полностью забита рынком;
- есть source path;
- есть disconfirming path.

Плохой кандидат:

- просто 1% near-deadline lottery;
- просто 99% локальный фаворит без контртезиса;
- generic geopolitics “risk elevated”;
- нет источников;
- API/search даёт мусор.

---

## 20. Как работает Forager

Forager строит цепочку:

```text
search result
-> source_raw_item
-> promoted source
-> crawled document
-> claims/entities/mentions
-> graph relations
-> recursive search
-> translation queue / translated docs
-> evidence drafts
-> contradiction clusters
-> packet
-> Signal validation
```

Главные модули:

| Модуль | Смысл |
|---|---|
| `forager/search/adapters.py` | Composite search: Tavily, Brave, fallback sources, Wikipedia, GDELT. |
| `forager/crawl*.py` | Crawl router: HTTP, Playwright, PDF, RSS, GitHub, Wayback, Firecrawl. |
| `forager/extraction.py` | Claims/entities/entity mentions. |
| `forager/graph.py` | Entity/claim relations and expansion queries. |
| `forager/semantic_graph.py` | Semantic relation/contradiction graph. |
| `forager/evidence.py` | Evidence draft scoring. |
| `forager/signal_bridge.py` | Packet для Signal. |
| `forager/service.py` | Core Forager service and core-loop. |
| `forager/translation_adapters.py` | Translation layer. |
| `forager/llm_adapters.py` | Ollama adapters for hypotheses/evidence relevance. |

### SDV

SDV = signal decision value. Важный вывод последнего аудита: SDV нельзя считать “вероятностью сигнала” или единственным gate.

Правильная роль:

```text
SDV = качество/полезность research packet для решения.
```

Если SDV низкий, это может значить:

- Forager не нашёл источников;
- search backend degraded;
- documents not crawled;
- нет disconfirming evidence;
- candidate плохой;
- или B был плохо направлен.

---

## 21. Ollama в проекте

Ollama есть, но сейчас не должен быть “мозгом принятия решений”.

Правильная роль:

- дешёвые drafts;
- handoff notes;
- preliminary candidate research draft;
- monitoring draft;
- learning review draft;
- гипотезы в Forager, если модель доступна.

Файлы:

- `bot/lib/ollama.py`;
- `forager/forager/llm_adapters.py`;
- `bot/llm_handoff/`.

Если мы используем Codex high / Opus как оператора, Ollama не нужен как главный reasoning layer. Он может экономить токены на черновиках, но сложный отбор кандидатов лучше делать человеком/сильной моделью через M/R/operator_review.

---

## 22. Price model: side_entry_price vs yes_equivalent_entry

У каждого сигнала/позиции теперь надо различать:

- `side_entry_price` - цена именно той стороны, которую мы купили. Если купили NO по 20c, это `0.20`.
- `yes_equivalent_entry` - эквивалент YES price. Для NO по 20c это `0.80`.

Правильная логика:

```text
YES position:
  side_entry_price = YES price
  yes_equivalent_entry = YES price

NO position:
  side_entry_price = NO price
  yes_equivalent_entry = 1 - NO price
```

---

## 23. Dashboard

Папка: `dashboard-web/`

Dashboard читает export data:

- `bot/export_dashboard_data.py`;
- `dashboard-web/public/data/signal-dashboard.json`.

Он нужен, чтобы видеть:

- открытые позиции;
- PnL;
- candidate/research health;
- signals;
- статусы gates;
- portfolio exposure;
- learning/quality metrics.

---

## 24. Где сейчас слабые места

1. **G может просканировать меньше рынков, чем хотелось бы.** Нужно следить за `market_fetch_audit` и реально добираться до 10k+ active markets.
2. **G2 исторически переоценивал local-language near-deadline extreme prices.** Это уже частично исправлено.
3. **B зависит от Tavily/Brave.** Если API исчерпаны, B может перейти в degraded mode. Теперь это хотя бы явно видно.
4. **Forager хорош как crawler/extractor, но слаб как самостоятельный мыслитель.** Ему нужен R/operator reasoning.
5. **SDV не должен быть главным арбитром.** Он quality signal, не инвестиционная вероятность.
6. **Legacy rows ещё есть.** В БД часть старых signals имеет `legacy_gate_violation`; это не “новые нарушения”, а исторический слой до hard gate.
7. **Ручной слой обязателен.** Лучшие сигналы пока появляются, когда Codex/Opus/человек руками проверяет market mechanics.
8. **Signal 2.0 должен лучше говорить “нет”.** Больше autonomy не нужно, пока anti-signal/source/causal gates не стали надёжными.

---

## 25. Как выглядит правильный запуск полного цикла сейчас

```powershell
cd C:\Signal\bot
..\.tools\python312\python.exe run_command_g.py
..\.tools\python312\python.exe run_command_g2.py
..\.tools\python312\python.exe run_command_m.py
$env:FORAGER_QUEUE_PATH='manual_shortlist_queue.py'; ..\.tools\python312\python.exe run_command_r.py
# Потом вручную/через Codex/Opus заполнить operator_review в forager_queue_reasoned.py,
# если нужно, добавить supporting_source_urls.
$env:FORAGER_QUEUE_PATH='forager_queue_reasoned.py'; ..\.tools\python312\python.exe run_command_b.py
$env:FORAGER_QUEUE_PATH='forager_queue_reasoned.py'; ..\.tools\python312\python.exe run_command_d.py
..\.tools\python312\python.exe run_command_c.py
```

Или через wrapper:

```powershell
cd C:\Signal\bot
..\.tools\python312\python.exe run_cycle.py
```

Это безопасный default: он доходит до R и останавливается на reasoning/operator workbench. Для полного research без записи signal:

```powershell
..\.tools\python312\python.exe run_cycle.py --mode no_commit --from G --to D
```

Запуск до C допустим только после заполненного `operator_review`:

```powershell
..\.tools\python312\python.exe run_cycle.py --mode paper_commit_after_operator --from B --to C
```

Если задача именно найти сильный сигнал, лучше не слепо ждать C, а после M/R руками проверить top candidates.

---

## 26. Как читать gate_status в ставках

- `gated` - сигнал прошёл текущий formal gate / Command C path.
- `manual` - ручная real-money сделка, записанная ретроспективно как manual trade.
- `legacy_gate_violation` - старый сигнал, созданный до текущих hard-gate правил или без pre-bet checklist до времени сигнала. Это не обязательно “плохой сигнал”, но ledger должен отделять его от новых gated signals.
- `null/no_signal` у cancelled rows - обычно след repair/cancel операции или позиция без связанного полноценного signal row.

---

## 27. Самая короткая карта проекта

```text
Polymarket universe
  -> G: broad scan
  -> G2: hidden-gem formula ranker
  -> M: manual shortlist desk
  -> R: reasoning memo / decisive questions
  -> B: Forager research packet
  -> D: Signal dossier + gate
  -> C: paper signal commit only if approved
  -> F/H/E: monitor, portfolio, resolution learning
  -> Learning: outcome reviews, quality reviews, calibration, benchmark
```

Главное: **проект должен помогать думать, а не имитировать автоматическое мышление.**

---

# 28. Фактический ledger из БД

Ниже идут таблицы, сгенерированные из `bot/bot.db`: counts, открытые позиции, закрытые позиции, cancelled/прочие позиции и fills.


## 28.1 Signal DB counts

| Table | Count |
|---|---:|
| `markets` | 6184 |
| `snapshots` | 16976 |
| `signals` | 38 |
| `positions` | 40 |
| `fills` | 48 |
| `pnl_events` | 82 |
| `analyses` | 26 |
| `evidence` | 833 |
| `pre_bet_checklists` | 235 |
| `resolution_maps` | 94 |
| `actor_maps` | 155 |
| `causal_factors` | 371 |
| `scenario_trees` | 286 |
| `premortems` | 323 |
| `hidden_gem_reviews` | 8 |
| `moonshot_reviews` | 8 |
| `outcome_learning_reviews` | 5 |
| `workflow_runs` | 233 |
| `workflow_steps` | 813 |
| `triage_scores` | 254 |

## 28.2 Forager DB counts

| Table | Count |
|---|---:|
| `forager_threads` | 272 |
| `forager_packets` | 269 |
| `forager_source_raw_items` | 13894 |
| `forager_sources` | 4818 |
| `forager_documents` | 2543 |
| `forager_claims` | 3187 |
| `forager_entities` | 8978 |
| `forager_entity_mentions` | 46973 |
| `forager_evidence_drafts` | 3412 |
| `forager_evidence_draft_bundles` | 134 |
| `forager_contradiction_clusters` | 59 |
| `forager_hypotheses` | 1232 |
| `forager_anomalies` | 3794 |
| `forager_translated_documents` | 10 |
| `forager_translation_queue` | 10 |

## 28.3 Open positions from DB

| ID | Status | Source | Market | Side | Entry side / YES-eq | Latest YES/NO | Stake | Opened / Closed | Gate | DB note |
|---:|---|---|---|---|---:|---:|---:|---|---|---|
| 41 | open | paper | Will Chun Jae-soo win the 2026 Busan Mayoral Election... | NO | 20.0% / 80.0% | 81.0% / 19.0% | $30.00 | 2026-05-25 / - | gated | Will Chun Jae-soo win the 2026 Busan Mayoral Election... |
| 40 | open | paper | Will OpenAI's valuation hit (HIGH) $950B by June 30... | NO | 63.0% / 37.0% | 37.5% / 62.5% | $21.19 | 2026-05-24 / - | gated | PRIVATE_MARKET_VALUATION: OpenAI resolves to NPM Price via Nasdaq Private Market (NPM). Threshold=$950B, lag=once daily at 1:00 PM ET on following calendar day... |
| 39 | open | paper | Will Kim Kwan-young win the 2026 Jeonbuk Province Gubernatorial Election... | YES | 43.0% / 43.0% | 48.0% / 52.0% | $5.60 | 2026-05-24 / - | gated | Suggested side: YES. Strategies: . Vertical: international_geopolitics. |
| 38 | open | paper | Will Cho Sangho win the 2026 Sejong mayoral election... | NO | 5.9% / 94.1% | 95.3% / 4.7% | $14.65 | 2026-05-23 / - | gated | Manual pick: Korean local-election high-YES market; investigate whether 95% is overconfident or actually locked. |
| 37 | open | paper | Will JD Vance visit Pakistan by May 31... | YES | 11.3% / 11.3% | 7.3% / 92.7% | $10.65 | 2026-05-23 / - | gated | JD Vance covers South Asia / Middle East portfolio. Pakistan-US relationship active around India tension + Afghanistan + counterterror. Pakistani press (Dawn, ... |
| 36 | open | paper | Iran agrees to surrender enriched uranium stockpile by May 31, 2026... | YES | 6.3% / 6.3% | 6.3% / 93.7% | $10.73 | 2026-05-23 / - | gated | $1.8M volume — biggest market in queue. Active Oman-mediated US-Iran nuclear negotiations. Iran's 20%-enriched stockpile is central negotiating asset. Persian ... |
| 35 | open | paper | Mojtaba Khamenei seen in public by May 31... | YES | 3.2% / 3.2% | 3.2% / 96.8% | $20.49 | 2026-05-23 / - | gated | Mojtaba Khamenei is a politically significant figure (Khamenei's son, rumored as quiet successor). Public appearance = discrete observable. $371k market volume... |
| 34 | open | paper | Will Trump meet with Benjamin Netanyahu in May 2026... | YES | 3.4% / 3.4% | 5.0% / 95.0% | $10.24 | 2026-05-23 / - | gated | PredictIt 70% vs Polymarket 3% (67pp gap). Suggested side: YES. Strategies: . Vertical: international_geopolitics. |
| 33 | open | paper | Will Flávio Bolsonaro win the 2026 Brazilian presidential election... | YES | 27.9% / 27.9% | 26.2% / 73.9% | $11.05 | 2026-05-23 / - | gated | PredictIt 55% vs Polymarket 28% (27pp gap). Suggested side: YES. Strategies: stale_price. Vertical: international_geopolitics. |
| 32 | open | paper | US x Iran permanent peace deal by May 31, 2026... | YES | 25.5% / 25.5% | 24.5% / 75.5% | $10.69 | 2026-05-22 / - | gated | Suggested side: YES. Strategies: . Vertical: international_geopolitics. |
| 29 | open | paper | Will Sorin Grindeanu be the next Prime Minister of Romania... | YES | 12.5% / 12.5% | 6.6% / 93.5% | $6.58 | 2026-05-21 / - | gated | Suggested side: YES. Strategies: cheap_optionality. Discovery score: 55.0. Vertical: international_geopolitics. |
| 28 | open | paper | Will any presidential candidate win outright in the first round of the Brazil e... | YES | 14.5% / 14.5% | 16.5% / 83.5% | $7.87 | 2026-05-21 / - | gated | Suggested side: YES. Strategies: stale_price. Discovery score: 57.4. Vertical: international_geopolitics. |
| 27 | open | paper | Iran agrees to end enrichment of uranium by May 31... | YES | 9.4% / 9.4% | 7.6% / 92.4% | $9.56 | 2026-05-21 / - | gated | Suggested side: YES. Strategies: stale_price. Discovery score: 64.5. Vertical: international_geopolitics. |
| 26 | open | paper | Will Trump and Putin not meet... | NO | 8.0% / 92.0% | 92.7% / 7.3% | $30.00 | 2026-05-21 / - | gated | Suggested side: NO. Strategies: stale_price. Discovery score: 53.4. Vertical: international_geopolitics. |
| 24 | open | paper | Will Megan Degenfelder win the 2026 Wyoming Governor Republican primary electio... | NO | 29.9% / 70.1% | 82.0% / 18.1% | $30.00 | 2026-05-21 / - | gated | Suggested side: NO. Strategies: compounder_research_candidate, low_volume_research_sweetspot. Discovery score: 57.7. Vertical: us_politics. |
| 23 | open | paper | Will the Reserve Bank of Australia increase the cash rate after the June Meetin... | NO | 19.7% / 80.3% | 10.5% / 89.5% | $9.75 | 2026-05-20 / - | gated | RBA easing cycle: May 2026 cut confirmed via Forager weak signals. Central bank cut→hike in 6 weeks requires a supply shock; none observed. ABS CPI benign. Mar... |
| 22 | open | paper | Will Mandela Barnes win the 2026 Wisconsin Governor Democratic primary election... | NO | 46.0% / 54.0% | 50.5% / 49.5% | $17.20 | 2026-05-20 / - | gated | Paper Signal: Barnes NO. Market implies Barnes YES around 54.5%, but reviewed local evidence supports a wide-open primary with Hong 14 / Barnes 11 and 65% unde... |
| 20 | open | real_money | Will Kim Kyung-soo win the 2026 Gyeongsangnam Province Gubernatorial Election... | YES | 29.0% / 29.0% | 46.5% / 53.5% | $99.80 | 2026-05-19 / - | legacy_gate_violation | Deep dive 2026-05-19. Korean Gallup·News1 May 11-12 Kim +7 outside MOE. 여론조사꽃 May 12-13 Kim +1.6 within MOE. Aggregated 5 of 7 polls show Kim ahead. National D... |
| 17 | open | paper | Iran closes its airspace by May 31... | NO | 41.5% / 58.5% | 22.3% / 77.7% | $10.92 | 2026-05-18 / - | legacy_gate_violation | Trend is OPENING not closing. Imam Khomeini Intl resumed commercial flights May 9. Tehran FIR partly reopened — east open for overflights, west still closed. F... |
| 16 | open | paper | Will OpenAI not IPO by December 31, 2026... | YES | 69.5% / 69.5% | 26.5% / 73.5% | $30.00 | 2026-05-18 / - | legacy_gate_violation | OpenAI has NOT filed S-1 publicly. Standard IPO timeline post-S-1 is 4-6+ months (SEC review, road show, pricing). For IPO by Dec 31 they'd need filing in next... |
| 14 | open | paper | Will Google have the best AI model at the end of June 2026... | NO | 25.5% / 74.5% | 19.5% / 80.5% | $5.53 | 2026-05-17 / - | legacy_gate_violation | Claude Opus 4.6 currently #1 on LMArena Text Overall at Elo ~1504 (style control OFF, which is the resolution criterion). Google I/O May 19 likely brings Gemin... |
| 13 | open | paper | Gemini 3.5 released by May 31... | NO | 21.5% / 78.5% | 90.0% / 10.1% | $9.83 | 2026-05-17 / - | legacy_gate_violation | Google I/O keynote is May 19 (NOT May 14 as I initially assumed). Multiple sources confirm Gemini 3.5 Pro expected to be announced — focused on "advanced reaso... |
| 12 | open | paper | Will GPT-6 be released before GTA VI... | NO | 34.5% / 65.5% | 65.5% / 34.5% | $22.93 | 2026-05-17 / - | legacy_gate_violation | HIDDEN GEM via resolution criteria. The market resolves 50/50 if neither GPT-6 nor GTA VI releases by July 31, 2026 — this clause is decisive. GTA VI officiall... |
| 11 | open | paper | Will Renan Santos finish in third place in the first round of the 2026 Brazilia... | NO | 31.0% / 69.0% | 36.0% / 64.0% | $25.00 | 2026-05-17 / - | legacy_gate_violation | Renan Santos polls 2-3% in May 2026 surveys (Quaest, Futura). Race is dominated by Lula 45% and Flávio Bolsonaro 33%. For 3rd place Santos must beat Ronaldo Ca... |
| 10 | open | paper | Will Lisa Demuth win the 2026 Minnesota Governor Republican primary election... | NO | 33.5% / 66.5% | 63.5% / 36.5% | $6.50 | 2026-05-17 / - | legacy_gate_violation | Demuth has institutional advantages (MN House Speaker), won party straw poll with 32%, leaning hard into MAGA branding, picked running mate already. But the GO... |
| 9 | open | paper | Will Donald Trump not announce a next United States Attorney General by June 30... | YES | 39.8% / 39.8% | 55.6% / 44.4% | $22.72 | 2026-05-17 / - | legacy_gate_violation | Trump fired Bondi early April, installed Todd Blanche as acting AG. Per Bloomberg: "Trump is in no hurry to tap a permanent attorney general" — wants Blanche t... |
| 8 | open | paper | Will Trump endorse John Cornyn for TX-Sen by Nov 2 2026 ET... | NO | 29.8% / 70.2% | 2.6% / 97.4% | $5.75 | 2026-05-17 / - | legacy_gate_violation | Trump has NOT endorsed either Cornyn or Paxton despite multiple "soon" announcements over months. Original lean was toward Cornyn after March 3 primary, but MA... |
| 5 | open | paper | Will there be no change in Fed interest rates after the July 2026 meeting... | NO | 6.5% / 93.5% | 92.5% / 7.5% | $7.44 | 2026-05-17 / - | legacy_gate_violation | Fed held steady in April (3.5-3.75% range) — Powell's last meeting before staying on under Trump pressure. Dot plot forecasts 1 rate cut in 2026. Next meetings... |
| 4 | open | paper | Israel strike on Yemen by June 30, 2026... | YES | 22.0% / 22.0% | 15.0% / 85.0% | $11.37 | 2026-05-17 / - | legacy_gate_violation | Israel struck Yemen multiple times in May 2026 (Sanaa airport, Houthi PM killed, ports). US-Houthi deal in May 2026 paused US airstrikes but explicitly does NO... |
| 3 | open | paper | Will J.D. Vance attend the next US x Iran diplomatic meeting... | YES | 31.6% / 31.6% | 32.5% / 67.5% | $8.45 | 2026-05-17 / - | legacy_gate_violation | Vance is the established diplomatic lead — he led the April 11-12 Islamabad talks (21 hours), met Qatari mediator May 8, is the public face of negotiations ("U... |
| 2 | open | paper | Will Israel launch a ground operation in Iran by May 31, 2026... | YES | 7.0% / 7.0% | 3.6% / 96.4% | $9.00 | 2026-05-17 / - | legacy_gate_violation | NYT (May 15) reports Israel and US intensifying prep for potential operations "possibly starting next week"; US considering deploying commandos to retrieve nuc... |
| 1 | open | paper | Will Spencer Pratt win the 2026 Los Angeles mayoral election... | NO | 22.5% / 77.5% | 22.0% / 78.0% | $14.50 | 2026-05-17 / - | legacy_gate_violation | LA mayoral primary is June 2 (16 days). Recent polling shows Bass 25%, Raman 17%, Pratt 14% among 14 candidates in a nonpartisan primary. Pratt needs >50% to w... |

## 28.4 Closed positions from DB

| ID | Status | Source | Market | Side | Entry side / YES-eq | Latest YES/NO | Stake | Opened / Closed | Gate | DB note |
|---:|---|---|---|---|---:|---:|---:|---|---|---|
| 25 | closed | real | Will the People Power Party win 4 seats in South Korea’s June 3, 2026 parliamen... | YES | 9.1% / 9.1% | 9.8% / 90.2% | $13.00 | 2026-05-21 / 2026-05-22 | gated | manual_exit_proceeds_6.00usd |
| 21 | closed | real_money | Will Figure's F.03 robots push at least 250,000 packages by 10:00 PM on May 21... | YES | 30.0% / 30.0% | 69.5% / 30.5% | $51.00 | 2026-05-19 / 2026-05-19 | legacy_gate_violation | Sold at market 0.72 for $36, locking +$21 profit ahead of last 50h variance. Will continue monitoring resolution as learning case (not for re-entry). |
| 18 | closed | hybrid | Will a new Gemini flagship be released by May 22, 2026... | YES | 8.0% / 8.0% | 0.8% / 99.2% | $10.84 | 2026-05-18 / 2026-05-22 | legacy_gate_violation | resolved_no_market_expired |
| 15 | closed | hybrid | Israeli parliament dissolved by May 31... | YES | 13.0% / 13.0% | 4.0% / 96.0% | $26.99 | 2026-05-18 / 2026-05-21 | legacy_gate_violation | Operator exited Israeli parliament YES around $7 after deadline-model deterioration; proceeds rotated to PPP YES. |
| 7 | closed | paper | Will Russia enter Huliaipilske by May 31... | YES | 43.0% / 43.0% | 66.0% / 34.0% | $49.33 | 2026-05-17 / 2026-05-23 | legacy_gate_violation | take_profit_at_0.984_proceeds_34.33usd_pnl_+19.33 |
| 6 | closed | paper | Will Jerome Powell depart as Fed Chair between May 15 and May 22... | YES | 56.8% / 56.8% | 98.2% / 1.7% | $25.00 | 2026-05-17 / 2026-05-23 | legacy_gate_violation | resolved_yes_payout_44.01usd_pnl_+19.01 |

## 28.5 Cancelled / other positions from DB

| ID | Status | Source | Market | Side | Entry side / YES-eq | Latest YES/NO | Stake | Opened / Closed | Gate | DB note |
|---:|---|---|---|---|---:|---:|---:|---|---|---|
| 31 | cancelled | paper | Israel closes its airspace by May 31... | YES | 21.5% / 21.5% | 21.5% / 78.5% | $5.88 | 2026-05-22 / 2026-05-22 | no_signal_or_null | cancelled_fake_edge_d_bug_fix |
| 30 | cancelled | paper | Will the People Power Party win 2 seats in South Korea’s June 3, 2026 parliamen... | YES | 29.0% / 29.0% | 34.0% / 66.0% | $6.04 | 2026-05-22 / 2026-05-22 | no_signal_or_null | cancelled_fake_edge_d_bug_fix |

## 28.6 All fills from DB

| Fill ID | Position | Date | Venue | Side | Price | Shares | Stake | Market |
|---:|---:|---|---|---|---:|---:|---:|---|
| 51 | 41 | 2026-05-25T09:25:53 | paper | NO | 20.0% | 150.0000 | $30.00 | Will Chun Jae-soo win the 2026 Busan Mayoral Election... |
| 50 | 40 | 2026-05-24T17:30:32 | paper | NO | 63.0% | 33.6349 | $21.19 | Will OpenAI's valuation hit (HIGH) $950B by June 30... |
| 49 | 39 | 2026-05-24T12:51:40 | paper | YES | 43.0% | 13.0233 | $5.60 | Will Kim Kwan-young win the 2026 Jeonbuk Province Gubernatorial Election... |
| 48 | 38 | 2026-05-23T16:45:40 | paper | NO | 5.9% | 248.3051 | $14.65 | Will Cho Sangho win the 2026 Sejong mayoral election... |
| 47 | 37 | 2026-05-23T12:19:34 | paper | YES | 11.3% | 94.2478 | $10.65 | Will JD Vance visit Pakistan by May 31... |
| 46 | 36 | 2026-05-23T12:19:34 | paper | YES | 6.3% | 168.9764 | $10.73 | Iran agrees to surrender enriched uranium stockpile by May 31, 2026... |
| 45 | 35 | 2026-05-23T12:19:34 | paper | YES | 3.2% | 630.4615 | $20.49 | Mojtaba Khamenei seen in public by May 31... |
| 44 | 7 | 2026-05-23T10:52:01 | paper | SELL_YES | 98.4% | 34.8837 | $34.33 | Will Russia enter Huliaipilske by May 31... |
| 43 | 6 | 2026-05-23T10:44:42 | polymarket_resolution | RESOLVE_YES | 100.0% | 44.0141 | $44.01 | Will Jerome Powell depart as Fed Chair between May 15 and May 22... |
| 42 | 34 | 2026-05-23T10:44:05 | paper | YES | 3.4% | 301.1765 | $10.24 | Will Trump meet with Benjamin Netanyahu in May 2026... |
| 41 | 33 | 2026-05-23T10:44:05 | paper | YES | 27.9% | 39.6768 | $11.05 | Will Flávio Bolsonaro win the 2026 Brazilian presidential election... |
| 37 | 18 | 2026-05-22T23:59:00 | polymarket | SELL_YES | 0.0% | 127.5294 | $-10.84 | Will a new Gemini flagship be released by May 22, 2026... |
| 40 | 32 | 2026-05-22T18:18:03 | paper | YES | 25.5% | 41.9216 | $10.69 | US x Iran permanent peace deal by May 31, 2026... |
| 36 | 20 | 2026-05-22T14:19:21 | polymarket | YES | 33.0% | 196.1400 | $64.80 | Will Kim Kyung-soo win the 2026 Gyeongsangnam Province Gubernatorial Elect... |
| 35 | 25 | 2026-05-22T14:19:21 | polymarket | SELL_YES | 7.8% | 76.9231 | $6.00 | Will the People Power Party win 4 seats in South Korea’s June 3, 2026 parl... |
| 34 | 29 | 2026-05-21T20:35:32 | paper | YES | 12.5% | 52.6400 | $6.58 | Will Sorin Grindeanu be the next Prime Minister of Romania... |
| 33 | 28 | 2026-05-21T20:35:32 | paper | YES | 14.5% | 54.2759 | $7.87 | Will any presidential candidate win outright in the first round of the Bra... |
| 32 | 27 | 2026-05-21T20:35:32 | paper | YES | 9.4% | 101.7021 | $9.56 | Iran agrees to end enrichment of uranium by May 31... |
| 31 | 15 | 2026-05-21T20:00:28 | polymarket | SELL_YES | 4.9% | 142.7857 | $7.00 | Israeli parliament dissolved by May 31... |
| 30 | 25 | 2026-05-21T20:00:28 | polymarket | YES | 9.1% | 76.9231 | $7.00 | Will the People Power Party win 4 seats in South Korea’s June 3, 2026 parl... |
| 29 | 26 | 2026-05-21T13:57:20 | paper | NO | 8.0% | 375.0000 | $30.00 | Will Trump and Putin not meet... |
| 28 | 25 | 2026-05-21T13:57:20 | paper | YES | 7.6% | 106.3158 | $8.08 | Will the People Power Party win 4 seats in South Korea’s June 3, 2026 parl... |
| 27 | 24 | 2026-05-21T13:57:19 | paper | NO | 29.9% | 100.3344 | $30.00 | Will Megan Degenfelder win the 2026 Wyoming Governor Republican primary el... |
| 26 | 23 | 2026-05-20T20:09:08 | paper | NO | 80.3% | 12.1420 | $9.75 | Will the Reserve Bank of Australia increase the cash rate after the June M... |
| 25 | 22 | 2026-05-20T18:01:26 | paper | NO | 46.0% | 37.3913 | $17.20 | Will Mandela Barnes win the 2026 Wisconsin Governor Democratic primary ele... |
| 24 | 21 | 2026-05-19T17:15:57 | polymarket | SELL_YES | 72.0% | 50.0000 | $36.00 | Will Figure's F.03 robots push at least 250,000 packages by 10:00 PM on Ma... |
| 23 | 21 | 2026-05-19T17:15:57 | polymarket | YES | 30.0% | 50.0000 | $15.00 | Will Figure's F.03 robots push at least 250,000 packages by 10:00 PM on Ma... |
| 22 | 20 | 2026-05-19T17:15:57 | polymarket | YES | 29.0% | 120.6897 | $35.00 | Will Kim Kyung-soo win the 2026 Gyeongsangnam Province Gubernatorial Elect... |
| 20 | 18 | 2026-05-18T12:54:44 | polymarket | YES | 8.5% | 127.5294 | $10.84 | Will a new Gemini flagship be released by May 22, 2026... |
| 19 | 18 | 2026-05-18T12:54:44 | paper | YES | 8.0% | 135.5000 | $10.84 | Will a new Gemini flagship be released by May 22, 2026... |
| 16 | 15 | 2026-05-18T12:54:04 | polymarket | YES | 14.0% | 142.7857 | $19.99 | Israeli parliament dissolved by May 31... |
| 18 | 17 | 2026-05-18T11:51:07 | paper | NO | 58.5% | 18.6667 | $10.92 | Iran closes its airspace by May 31... |
| 17 | 16 | 2026-05-18T11:50:58 | paper | YES | 69.5% | 43.1655 | $30.00 | Will OpenAI not IPO by December 31, 2026... |
| 15 | 15 | 2026-05-18T11:50:48 | paper | YES | 13.0% | 149.3077 | $19.41 | Israeli parliament dissolved by May 31... |
| 14 | 14 | 2026-05-17T16:44:56 | paper | NO | 74.5% | 7.4228 | $5.53 | Will Google have the best AI model at the end of June 2026... |
| 13 | 13 | 2026-05-17T16:44:47 | paper | NO | 21.5% | 45.8275 | $9.83 | Gemini 3.5 released by May 31... |
| 12 | 12 | 2026-05-17T16:44:38 | paper | NO | 34.5% | 66.4638 | $22.93 | Will GPT-6 be released before GTA VI... |
| 11 | 11 | 2026-05-17T14:46:38 | paper | NO | 69.0% | 36.2319 | $25.00 | Will Renan Santos finish in third place in the first round of the 2026 Bra... |
| 10 | 10 | 2026-05-17T14:45:41 | paper | NO | 33.5% | 19.4030 | $6.50 | Will Lisa Demuth win the 2026 Minnesota Governor Republican primary electi... |
| 9 | 9 | 2026-05-17T14:45:23 | paper | YES | 39.8% | 57.0854 | $22.72 | Will Donald Trump not announce a next United States Attorney General by Ju... |
| 8 | 8 | 2026-05-17T14:44:08 | paper | NO | 70.2% | 8.1851 | $5.75 | Will Trump endorse John Cornyn for TX-Sen by Nov 2 2026 ET... |
| 7 | 7 | 2026-05-17T14:43:58 | paper | YES | 43.0% | 34.8837 | $15.00 | Will Russia enter Huliaipilske by May 31... |
| 6 | 6 | 2026-05-17T14:43:39 | paper | YES | 56.8% | 44.0141 | $25.00 | Will Jerome Powell depart as Fed Chair between May 15 and May 22... |
| 5 | 5 | 2026-05-17T08:16:09 | paper | NO | 6.5% | 114.4615 | $7.44 | Will there be no change in Fed interest rates after the July 2026 meeting... |
| 4 | 4 | 2026-05-17T08:14:47 | paper | YES | 22.0% | 51.6818 | $11.37 | Israel strike on Yemen by June 30, 2026... |
| 3 | 3 | 2026-05-17T08:14:38 | paper | YES | 31.6% | 26.7829 | $8.45 | Will J.D. Vance attend the next US x Iran diplomatic meeting... |
| 2 | 2 | 2026-05-17T08:13:34 | paper | YES | 7.0% | 128.5714 | $9.00 | Will Israel launch a ground operation in Iran by May 31, 2026... |
| 1 | 1 | 2026-05-17T08:13:17 | paper | NO | 77.5% | 18.7097 | $14.50 | Will Spencer Pratt win the 2026 Los Angeles mayoral election... |

---

............... ............................ ..................... ............ ....................................... ........................ ...... SQLite, ..................... ......... ........................... ...... ............ .................. ............... ..................................
