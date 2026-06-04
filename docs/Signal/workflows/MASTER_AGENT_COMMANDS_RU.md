# Signal - Master Agent Commands RU

Это файл с командами, которые можно копировать в новый чат Claude/Codex/ChatGPT. Каждая команда начинается с одного и того же operating contract, чтобы агент не импровизировал запись в БД и не создавал сигналы в обход pre-bet gate.

## Универсальный пролог для любого нового агента

Скопируй этот блок в начало любой задачи:

```text
You are operating inside Signal, a personal Polymarket research OS.

Before doing anything:
1. Read AGENT_OPERATING_CONTRACT.md.
2. Read WORKFLOW_CONTRACTS.md.
3. Read WRITE_POLICY.md.
4. Read RESEARCH_LEDGER_STATUS_RULES.md.
5. Read AGENT_STARTUP_SEQUENCE.md.
6. Read docs/Signal/README.md.
7. Read docs/Signal/workflows/MASTER_AGENT_COMMANDS_RU.md.
8. Identify the workflow level of my request: L0, L1, L2, L3, L4, L5, docs/report only, or repair.
9. Use only approved MCP/project tools for research writes.
10. Do not write directly to SQLite.
11. Do not create one-off Python insert scripts for evidence, analyses, signals, positions, or fills.
12. Do not create signal/position/fill unless aladdin_signal_commit or the approved signal path passes all gates.
13. If a required tool is missing, propose or implement the tool with tests instead of bypassing the workflow.
14. If this is a real manual trade, record it only as manual/retrospective trade evidence; do not pretend it passed a prior pre-bet checklist.
15. At the end, report: workflow level, tools called, records written, skipped writes, blockers, next_action, docs created, and whether any signal was created.
```


## Implemented MCP Tools

Эти мастер-команды уже имеют реальные tool-реализации в `bot/tools/workflows.py`:

- `master_discovery_research_cycle(max_pages=6, max_candidates=16, enrich_top=10, vertical=None, write_report=True)`
  - делает L0/L1 intake, live discovery, API enrichment, Tier A/B/C sorting;
  - пишет только `markets`, `snapshots`, `market_tags` и markdown report;
  - не создает evidence, checklist, signal, position, fill.

- `master_learning_cycle(limit=50, write_report=True)`
  - делает L4 learning audit: resolved learning debt, stale forecasts, gate violations, incomplete dossiers, archetypes, source registry;
  - пишет markdown report;
  - возвращает legal next-write tasks, но сам не фабрикует outcome/forecast reviews.

Старые tools остаются полезными как компоненты:

- `master_market_discovery`
- `api_research_enrichment`
- `research_ledger`
- `master_maintenance_audit`
- `aladdin_master_cycle`

---


---

## Integrity Core - уже реализовано

Эти инструменты теперь являются обязательной частью мастер-воркфлоу:

- `validate_signal_gate(condition_id, probability_yes, confidence, side, proposed_stake_usd, primary_archetype)`
  - read-only проверка: свежий snapshot, approved pre-bet checklist, resolution map, evidence >= 2, actor map, causal factors >= 2, scenario tree >= 3, premortem, source depth, spread/edge/confidence/exposure;
  - ничего не пишет в БД;
  - если gate не проходит, агент обязан остановиться и вернуть `blocked_reason` + `next_action`.

- `aladdin_signal_commit(condition_id, side, probability_yes, confidence, reasoning, sources, paper_only=true)`
  - единственный формальный L3 путь создать paper signal;
  - сам вызывает `validate_signal_gate`;
  - если gate прошел, пишет analysis + signal + paper position + paper fill;
  - real-money execution здесь запрещен.

- `record_real_manual_trade(...)`
  - единственный легальный путь записать сделку, которую оператор уже сделал руками на реальные деньги;
  - ставит `manual_trade=1`, `retrospective=1`, `operator_decision='manual_real_trade'`;
  - не создает фальшивый pre-bet checklist задним числом;
  - ledger не считает такую запись gate violation, но она остается видимой для learning/review.

Правило: если агент хочет создать signal/position/fill и не использует `aladdin_signal_commit` или `record_real_manual_trade`, он нарушает контракт проекта.

---

## Workflow Journal - обязательный лабораторный след

Для любой серьезной мастер-команды агент обязан оставить след в `workflow_runs/workflow_steps`.

Если команда уже автоматизирована, она вернет `workflow_run_id`. Если нет, агент должен вручную вызвать:

```text
start_workflow_run(...)
record_workflow_step(...) for every major step/blocker/write group
finish_workflow_run(...)
```

Минимальные шаги для deep research:

```text
1. load_project_state
2. fetch_market_details
3. resolution_check
4. source_collection
5. dossier_writes
6. pre_bet_checklist
7. final_decision
8. write_report
```

Минимальные шаги для learning:

```text
1. load_ledger
2. find_learning_debt
3. review_resolved_positions
4. stale_forecast_updates
5. source_archetype_review
6. write_report
```

Если workflow остановился, `finish_workflow_run(status="blocked")`, а blocker должен быть записан в последнем `workflow_step`.

## Signal + Forager Master Route - основной двухшаговый маршрут

Новый основной маршрут для глубокого поиска выглядит так:

```text
Signal first-pass discovery
-> Forager recursive deep research
-> Signal dossier/checklist decision
-> optional Signal commit gate
-> Learning
```

Подробные copy/paste команды находятся в:

```text
docs/Signal/workflows/SIGNAL_FORAGER_MASTER_COMMANDS_RU.md
```

Ключевые команды:

- `SIGNAL_TO_FORAGER_CANDIDATE_INTAKE` - Signal сканирует Polymarket, выбирает 5-12 кандидатов и готовит очередь для Forager. Это L0 -> L1 -> L2 planning. Сигналы, позиции и fills запрещены.
- `FORAGER_BATCH_DEEP_RESEARCH_TO_SIGNAL` - Forager прогоняет core recursive research loop по кандидатам, создает packets, затем Signal промоутит только проверенные findings в dossier/checklist records.
- `SIGNAL_COMMIT_AFTER_FORAGER` - отдельный L3 gate, единственный момент, где можно создать formal paper signal.
- `FORAGER_FIRST_DISCOVERY_EXPERIMENT` - дорогой экспериментальный режим, где Forager ищет weak signals первым и потом мапит их на Polymarket.
- `SIGNAL_FORAGER_LEARNING_LOOP` - обучение Signal и Forager по исходам, packet quality, source quality и false positives.

Правило границы:

```text
Forager discovers.
Signal decides.
Learning calibrates both.
```

Forager core path сейчас только:

```text
POST /research/core-loop
POST /attention/minimal
```

Phase 16/17 ecology layers остаются experimental/north-star и не являются стандартным доказательством alpha.

## Command 1 - Master Discovery Research Cycle

Назначение: найти новые рынки, отсортировать кандидатов, провести глубокий research лучших, записать структуру в БД и сделать отчет в docs. Это основной режим поиска hidden gems.

```text
Task: Run MASTER_DISCOVERY_RESEARCH_CYCLE.

Goal:
Find the best current Polymarket research candidates, especially hidden gems, moonshots with real logic, and medium-priced compounders with unusually strong confidence. Do not limit research only to very cheap high-odds markets; include markets up to ~0.55-0.60 when confidence, source depth, and edge justify it.

Workflow:
1. Run startup sequence and classify this as L0 -> L1 -> L2, with L3 only if explicitly approved.
2. Load current state:
   - research_ledger(limit=100) if available
   - portfolio_snapshot()
   - open_signals()
   - incomplete_research_queue(limit=30)
   - pending_outcome_reviews()
   - source_status / maintenance audit if available
3. Run broad market discovery:
   - include low-price moonshots
   - include 0.15-0.60 compounder candidates
   - include markets with stale price, language asymmetry, procedural misunderstanding, source asymmetry, or crowd narrative error
   - exclude random lottery markets with no research path
4. For each candidate, create a candidate table with:
   - market / condition_id / slug
   - current price and spread
   - liquidity and volume
   - deadline and catalyst calendar
   - likely research lane: moonshot / hidden_gem / compounder / watch
   - first-pass thesis
   - main blocker
   - next best source/API
5. Use all relevant APIs and sources already configured in the project:
   - Polymarket Gamma / CLOB / local snapshots
   - GDELT, Wikipedia/Wikidata, OpenFEC, YouTube, official sources, relevant domain sources
   - domain-specific APIs if available
   - note unavailable APIs explicitly; do not silently ignore failures
6. Rank candidates into:
   - Tier A: deep research now
   - Tier B: watchlist with exact trigger
   - Tier C: reject with reason
7. For Tier A candidates, run full L2 deep research, one market at a time:
   - resolution map
   - evidence, including disconfirming evidence
   - actor map
   - causal factors
   - scenario tree
   - premortem
   - hidden_gem/moonshot/compounder review
   - pre-bet checklist
8. Do not create signal/position/fill during this workflow. If something is approved, return `approved_for_signal_candidate` and explain what exact L3 command should be run next.
9. Write all research facts through approved MCP/project tools only.
10. Create a markdown report in docs/Signal/reports/ with date in filename:
    `YYYY-MM-DD - Master Discovery Research Report RU.md`

Output format:
- Executive summary
- Current portfolio context
- Candidate board
- Tier A deep dives
- Tier B watchlist and triggers
- Tier C rejects
- What was written to DB
- What was not written and why
- Blockers / failed APIs
- Next exact command
```

---

## Command 2 - Single Market Full Deep Dive

Назначение: максимально подробно разобрать один рынок от resolution wording до сценариев и pre-bet checklist.

```text
Task: Run SINGLE_MARKET_FULL_DEEP_DIVE.

Market:
[paste Polymarket URL / slug / condition_id]

Goal:
Investigate this market from zero to a complete research dossier. The output must decide between reject, watch, needs_more_research, approved_for_signal_candidate, or approved_for_signal. Do not create a signal unless I explicitly add: `L3 signal commit approved`.

Workflow:
1. Run startup sequence.
2. Identify this as L2 deep research.
3. Fetch market details and latest snapshot.
4. Parse resolution wording and identify traps.
5. Find primary resolution source.
6. Build source plan by domain.
7. Use all relevant APIs and official/web sources.
8. Record via tools only:
   - record_resolution_map
   - record_evidence, including disconfirming evidence
   - record_actor_map
   - record_causal_factor
   - record_scenario
   - record_premortem
   - record_hidden_gem_review or record_moonshot_review when applicable
   - record_pre_bet_checklist
9. Separate probability, confidence, edge, and decision.
10. Cap confidence if source depth is thin.
11. Create report:
   `docs/Signal/reports/YYYY-MM-DD - Deep Dive - [short slug] RU.md`

Output:
- Decision
- Fair probability range and center
- Confidence and why
- Edge vs market
- Main thesis
- Best disconfirming evidence
- Premortem
- Triggers to update / exit / scale
- DB records written
- Missing blocks
- Next action
```

---

## Command 3 - Signal Commit Gate

Назначение: единственный разрешенный путь превратить готовый research dossier в paper signal. Для real money агент должен только подготовить decision support, а не давать автоматическое действие.

```text
Task: Run SIGNAL_COMMIT_GATE.

Market:
[paste condition_id / URL]

Side:
YES/NO

Mode:
paper_only=true

Goal:
Validate whether this researched market can become a formal Signal paper position. Do not bypass any gate.

Workflow:
1. Run startup sequence.
2. Identify this as L3 signal commit.
3. Load latest dossier and ledger state.
4. Validate signal gate:
   - fresh snapshot
   - approved pre_bet_checklist
   - resolution map
   - evidence count >= 2
   - actor map
   - causal factors >= 2
   - scenario tree
   - premortem
   - spread/liquidity ok
   - exposure ok
   - source depth ok
   - no unresolved blocker
5. If any gate fails, do not create signal. Return blocked_reason and next_action.
6. If all gates pass, create paper signal through approved tool path only.
7. Create report/update note in docs/Signal/reports/.

Output:
- gate_passed true/false
- signal_created true/false
- paper position details if created
- blocked_reason if blocked
- next_action
```

---

## Command 4 - Master Learning Cycle

Назначение: постоянное обучение машины. Этот workflow не ищет новые ставки; он изучает прошлые решения, исходы, ошибки, удачу, повторяемые паттерны и обновляет память проекта.

```text
Task: Run MASTER_LEARNING_CYCLE.

Goal:
Make Signal smarter by reviewing all open/closed/resolved positions, old candidates, missed opportunities, false positives, false negatives, calibration drift, source quality, and archetype performance.

Workflow:
1. Run startup sequence.
2. Identify this as L4 learning.
3. Load:
   - research_ledger(limit=200)
   - portfolio_snapshot()
   - pending_outcome_reviews()
   - open_signals()
   - all resolved markets without outcome_learning_review
   - signal_quality_review gaps
   - source track record if available
4. For each resolved or materially updated market:
   - compare original thesis vs outcome
   - separate skill from luck
   - identify missed evidence
   - identify whether market moved before resolution
   - update calibration notes
   - record outcome learning through approved tools only
5. For open positions:
   - check stale forecast updates
   - record forecast_update when thesis probability changed
   - do not create new trades
6. Review rejected/watch candidates:
   - identify false negatives and whether they should become benchmark cases
7. Update archetype lessons:
   - language asymmetry
   - procedural politics
   - countable catalyst
   - cheap optionality
   - crowd narrative error
   - liquidity trap
8. Create report:
   `docs/Signal/reports/YYYY-MM-DD - Master Learning Cycle RU.md`

Output:
- Learning summary
- What improved
- Calibration changes
- Source reliability changes
- Archetype changes
- Outcome reviews recorded
- Forecast updates recorded
- Remaining learning debt
- Rule changes proposed
```

---

## Command 5 - Real Manual Trade Reconciliation

Назначение: честно записать реальные сделки, которые оператор уже сделал руками, без притворства, что они прошли pre-bet checklist заранее.

```text
Task: Run REAL_MANUAL_TRADE_RECONCILIATION.

Trades:
[paste real entries/exits]

Goal:
Reconcile my real Polymarket trades into Signal as manual/retrospective records without corrupting the research workflow.

Rules:
1. Do not pretend the trade had an approved pre_bet_checklist if it did not.
2. Do not create fake prior evidence timestamps.
3. Mark the trade as real manual / retrospective / operator-entered.
4. If a proper tool does not exist, propose or implement one with tests. Do not use direct SQL inserts.
5. Preserve real facts: entry price, exit price, stake, shares, timestamps if known, realized/unrealized PnL.
6. Then create retrospective research notes separately.

Output:
- trades reconciled
- records written
- records not written because tool missing
- proposed repair/tool migration if needed
- report file in docs/Signal/reports/
```

---

## Command 6 - Master Maintenance Audit

Назначение: техническая и исследовательская гигиена. Не делает ставки, не создает новые thesis, не чинит БД без approval.

```text
Task: Run MASTER_MAINTENANCE_AUDIT.

Goal:
Find everything that can silently rot the project memory.

Workflow:
1. Run startup sequence.
2. Identify this as L5 maintenance.
3. Run/read maintenance audit.
4. Check:
   - signals without approved pre_bet_checklist
   - positions without snapshots
   - evidence without source
   - invalid enum values
   - stale open positions
   - resolved markets without learning
   - duplicate docs / broken docs index
   - one-off scripts that should be archived or deleted after review
   - API credentials/source failures
5. Do not mutate DB unless I explicitly approve repair.
6. Create report:
   `docs/Signal/reports/YYYY-MM-DD - Maintenance Audit RU.md`

Output:
- must_fix
- should_fix
- can_ignore
- repair plan
- exact commands/tools needed
```

---

## Command 7 - Daily Operator Brief

Назначение: коротко открыть день: что держим, что протухло, какие события сегодня, где надо срочно думать.

```text
Task: Run DAILY_OPERATOR_BRIEF.

Goal:
Give me a practical daily Signal briefing.

Workflow:
1. Run startup sequence.
2. Identify this as L0 briefing, optionally L4 forecast update if open thesis changed.
3. Load current portfolio, research ledger, stale positions, catalysts for next 72h, and pending reviews.
4. Do not create new signals.
5. If an open position needs thesis update, record forecast_update only through approved tool.
6. Create optional short report:
   `docs/Signal/reports/YYYY-MM-DD - Daily Operator Brief RU.md`

Output:
- open positions
- today/tomorrow catalysts
- urgent checks
- stale thesis updates
- candidates worth deeper research
- exact next command
```
