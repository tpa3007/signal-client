# Signal + Forager Master Commands RU

Дата: 2026-05-20
Статус: active operating playbook

Этот файл нужен для новых чатов Claude/Codex/ChatGPT. Его можно открыть, скопировать нужную команду и дать агенту без длинного объяснения проекта.

Главная граница:

```text
Forager discovers.
Signal decides.
Learning calibrates both.
```

Forager не создает ставки, позиции, fills или финальные Signal analyses. Он ищет источники, weak signals, contradictions, anomalies, hypotheses и делает packets. Signal принимает решение через свои dossier, checklist и gate.

## Universal Bootstrap

Добавляй этот блок в начало любой команды ниже:

```text
You are operating inside Signal + Forager.

Before doing anything:
1. Read AGENT_OPERATING_CONTRACT.md.
2. Read WORKFLOW_CONTRACTS.md.
3. Read WRITE_POLICY.md.
4. Read RESEARCH_LEDGER_STATUS_RULES.md.
5. Read AGENT_STARTUP_SEQUENCE.md.
6. Read forager/OPERATING_CONTRACT.md.
7. Read docs/Signal/technical/49 - Forager Core Priorities RU.md.
8. Read docs/Signal/workflows/MASTER_AGENT_COMMANDS_RU.md.
9. Read docs/Signal/workflows/SIGNAL_FORAGER_MASTER_COMMANDS_RU.md.
10. Identify the workflow level before writes.
11. Use workflow_runs/workflow_steps for every serious workflow.
12. Use only approved Signal tools for Signal DB writes.
13. Use only Forager service/API/store paths for Forager records.
14. Do not write directly to SQLite for research facts.
15. Do not create one-off Python insert scripts for evidence, analyses, signals, positions, fills, or Forager packets.
16. Do not create signal/position/fill unless Signal L3 gate passes.
17. If a required tool is missing, stop with blocker and propose the missing tool/test instead of bypassing the workflow.
18. At the end report: workflow level, records written, reports created, blockers, next exact command.
```

Core Forager rule:

```text
Use /research/core-loop and /attention/minimal as the default Forager path.
Do not use Phase 16/17 ecology layers as core proof unless the user explicitly asks for an experimental run.
```

---

## Command A - Signal To Forager Candidate Intake

Назначение: Signal делает прагматичный первый проход по Polymarket, выбирает кандидатов и передает их в Forager. Это дешевле, чем Forager-first discovery, потому что дорогой интернет-рекурсивный поиск запускается только по отобранным рынкам.

Скопируй в новый чат:

```text
Task: Run SIGNAL_TO_FORAGER_CANDIDATE_INTAKE.

Goal:
Use Signal as the first-pass market filter. Find the best current Polymarket candidates for deeper Forager research, persist allowed discovery state, create a clean Forager handoff queue, and write an operator report.

Candidate policy:
- Do not select only huge-odds moonshots.
- Include hidden gems, moonshots with real research path, and compounders priced up to about 0.55-0.60 when confidence/source asymmetry could create edge.
- Exclude lottery markets with no source path.
- Default candidate count: 5-12, not fixed. If the market is rich, select more; if weak, select fewer.

Workflow:
1. Run Universal Bootstrap.
2. Classify as L0 -> L1 -> L2 planning. L3 is forbidden here.
3. Start workflow_runs record:
   workflow_name = signal_to_forager_candidate_intake
   workflow_level = L0 -> L1 -> L2 planning
4. Load Signal state:
   - research_ledger(limit=100)
   - portfolio_snapshot()
   - open_signals()
   - incomplete_research_queue(limit=30)
   - pending_outcome_reviews()
   - master_maintenance_audit() if available
5. Run market discovery using the best available project tool:
   - preferred: master_discovery_research_cycle(max_pages=6, max_candidates=20, enrich_top=12, write_report=true)
   - fallback: master_market_discovery + api_research_enrichment
6. Persist only legal Signal discovery writes:
   - markets
   - snapshots
   - market_tags
   - workflow_runs/workflow_steps
   - markdown report
7. Do not write Signal evidence, checklist, analysis, signal, position, or fill.
8. Create a Forager handoff queue for each selected candidate:
   - condition_id / market_id
   - Polymarket URL / slug
   - question
   - current YES/NO price and spread
   - liquidity / volume
   - end date / catalyst date
   - suspected edge archetype
   - why Signal alone may miss it
   - first-pass thesis
   - disconfirming angle to search
   - local-language needs
   - best first queries for Forager
   - priority: P0/P1/P2
9. If Forager API/store is available, create or prepare Forager research threads for the candidates through Forager paths only. If not available, put the queue in the report and mark blocker = forager_runtime_not_available.
10. Write operator report:
    docs/Signal/reports/YYYY-MM-DD - Signal To Forager Candidate Intake RU.md
11. Finish workflow_runs as completed or blocked.

Output:
- workflow_run_id
- candidate_count
- P0/P1/P2 Forager queue
- what was written to Signal DB
- what was written/prepared for Forager
- report path
- blockers
- next exact command:
  FORAGER_BATCH_DEEP_RESEARCH_TO_SIGNAL
```

Expected database boundary:

```text
Signal writes: markets, snapshots, market_tags, workflow_runs, workflow_steps.
Forager writes: forager_threads only if Forager API/store is available.
Forbidden here: evidence, pre_bet_checklists, analyses, signals, positions, fills.
```

---

## Command B - Forager Batch Deep Research To Signal

Назначение: Forager берет очередь кандидатов от Signal, копает интернет глубже обычного агента, делает packets, а затем Signal превращает лучшие findings в структурированные dossiers и решения.

Скопируй в новый чат:

```text
Task: Run FORAGER_BATCH_DEEP_RESEARCH_TO_SIGNAL.

Goal:
Take the latest Signal -> Forager candidate queue, run full Forager core research on each candidate, persist Forager packets, then hand the strongest packets back to Signal for structured dossier/gate decisions. Create full markdown reports and legal DB records.

Workflow:
1. Run Universal Bootstrap.
2. Classify as:
   - Forager phase: upstream recursive research
   - Signal phase: L2 deep research
   - L3 forbidden unless I explicitly add `L3 signal commit approved`
3. Start workflow_runs record:
   workflow_name = forager_batch_deep_research_to_signal
   workflow_level = Forager research -> Signal L2
4. Load latest candidate queue from:
   - latest Signal To Forager report in docs/Signal/reports/
   - workflow_runs/workflow_steps output_json if available
   - Forager threads if already created
5. For each P0/P1 candidate run Forager core loop:
   preferred API:
   POST /research/core-loop
   with:
   - seed_query = market question + candidate thesis
   - market_id = condition_id or stable market id
   - depth = deep
   - recursive_rounds = 2 by default, 3 only for P0/high heat
   - max_queries_per_round = 5
   - results_per_query = 4
   - max_sources_per_round = 6
   - include_local_language = true
   - execute_translations = false unless translation is necessary and available
   - run_semantic_graph = true
   - build_evidence_drafts = true
   - require_disconfirming_evidence = true for final candidates
6. Build minimal attention state:
   POST /attention/minimal
   Use it only for prioritization:
   - increase_recursion_depth
   - spawn_more_queries
   - revisit_thread
   - maintain
   - archive_thread
7. Persist Forager outputs only through Forager service/API/store:
   - forager_threads
   - forager_source_raw_items
   - forager_sources
   - forager_documents
   - forager_entities
   - forager_claims
   - forager_claim_relations
   - forager_contradiction_clusters
   - forager_evidence_drafts
   - forager_packets
8. Forager packet quality requirements:
   - source provenance attached
   - contradictions preserved
   - absence signals stated separately
   - local-language layer noted
   - disconfirming evidence included or blocker recorded
   - no trading decision
9. Signal review phase:
   For each strong Forager packet, Signal must independently promote only source-backed findings through approved Signal tools:
   - record_resolution_map
   - record_evidence
   - record_actor_map
   - record_causal_factor
   - record_scenario
   - record_premortem
   - record_hidden_gem_review / record_moonshot_review / compounder review when available
   - record_pre_bet_checklist
10. Do not auto-promote every Forager evidence draft. Promote only reviewed, source-backed, decision-relevant evidence.
11. Final Signal decision per market:
   - reject
   - watch
   - needs_more_research
   - approved_for_signal_candidate
   - approved_for_signal
12. Do not create signal/position/fill. If a market reaches approved_for_signal, return the exact SIGNAL_COMMIT_GATE command for the next chat.
13. Write reports:
   - docs/Signal/reports/YYYY-MM-DD - Forager Batch Deep Research RU.md
   - docs/Signal/reports/YYYY-MM-DD - Signal Final Decisions From Forager RU.md
14. Finish workflow_runs as completed or blocked.

Output:
- workflow_run_id
- candidate_count processed
- Forager packet ids
- attention priorities
- strongest weak signals
- contradictions found
- source gaps
- Signal decisions by market
- DB records written by Forager
- DB records written by Signal
- report paths
- next exact command
```

Expected database boundary:

```text
Forager writes its own research artifacts.
Signal writes only reviewed dossier/checklist records through approved tools.
Signal does not create signals in this workflow.
```

---

## Command C - Signal Commit After Forager

Назначение: только после Command B, если какой-то рынок дошел до `approved_for_signal`.

Скопируй в новый чат:

```text
Task: Run SIGNAL_COMMIT_AFTER_FORAGER.

Market:
[condition_id / URL / slug]

Side:
YES/NO

Mode:
paper_only=true

Goal:
Convert a fully researched Signal dossier, enriched by Forager packet(s), into a formal paper Signal only if every gate passes.

Workflow:
1. Run Universal Bootstrap.
2. Classify as L3 signal commit.
3. Load:
   - latest Signal dossier
   - latest pre_bet_checklist
   - latest Forager packet / signal bridge packet
   - latest snapshot
   - current exposure
4. Run validate_signal_gate.
5. If gate fails:
   - do not create signal
   - write blocker to workflow_steps
   - return exact missing blocks
6. If gate passes:
   - use aladdin_signal_commit only
   - paper_only=true unless operator explicitly asks otherwise
7. Write/update report:
   docs/Signal/reports/YYYY-MM-DD - Signal Commit After Forager RU.md

Output:
- gate_passed
- signal_created
- signal_id / analysis_id / position_id if created
- paper entry details
- blockers
- next monitoring action
```

---

## Command D - Forager-First Discovery Experiment

Назначение: дорогой future workflow. Forager сам начинает с внешнего мира, ищет pre-market weak signals и только потом мапит их на Polymarket. Запускать редко и только с явным бюджетом.

Скопируй в новый чат:

```text
Task: Run FORAGER_FIRST_DISCOVERY_EXPERIMENT.

Budget:
[time/API/search budget]

Goal:
Use Forager as the first discovery engine, not just a deep-research engine for Signal-selected markets. This is expensive and experimental.

Rules:
1. Ask for or respect explicit budget.
2. Run Universal Bootstrap.
3. Classify as experimental Forager upstream discovery, not Signal L3.
4. Use Forager core loop and minimal attention only.
5. Do not use Phase 16/17 ecology layers unless I explicitly request experimental ecology.
6. Search for weak signals first:
   - local-language anomalies
   - source absence
   - contradiction clusters
   - technical/hiring/repo/procedural drift
   - low-visibility official sources
7. Then map findings to possible Polymarket markets.
8. Send mapped candidates to Signal as a candidate queue, not as decisions.
9. Write report:
   docs/Signal/reports/YYYY-MM-DD - Forager First Discovery Experiment RU.md

Output:
- weak signals found
- possible market mappings
- Forager packet ids
- Signal candidate queue
- blockers
- recommendation whether this expensive mode was worth it
```

---

## Command E - Signal + Forager Learning Loop

Назначение: обучение не только Signal, но и Forager: какие packets были полезны, где рекурсия дала мусор, где local-language слой реально создал edge.

Скопируй в новый чат:

```text
Task: Run SIGNAL_FORAGER_LEARNING_LOOP.

Goal:
Review resolved/open outcomes and Forager packets to improve both systems. Signal learns calibration; Forager learns which weak-signal patterns actually helped.

Workflow:
1. Run Universal Bootstrap.
2. Classify as L4 learning.
3. Load:
   - research_ledger(limit=200)
   - open_signals()
   - pending_outcome_reviews()
   - resolved markets without learning review
   - latest Forager packets for markets with Signal decisions
   - packet ids referenced by reports/workflow_steps
4. For each market with outcome or material update:
   - compare Signal thesis vs outcome
   - compare Forager packet vs outcome
   - identify whether Forager found something Signal would have missed
   - mark useful vs noisy weak signals
   - identify hallucination/over-recursion patterns
5. Write Signal learning records through approved Signal tools:
   - record_outcome_learning_review
   - record_forecast_update
   - record_signal_quality_review
6. Write Forager learning/calibration only through Forager paths if available:
   - source track record
   - calibration scores
   - anomaly reviews
7. Do not create new signals.
8. Write report:
   docs/Signal/reports/YYYY-MM-DD - Signal Forager Learning Loop RU.md

Output:
- what Signal learned
- what Forager learned
- useful Forager archetypes
- noisy Forager patterns
- source reliability changes
- calibration changes
- remaining learning debt
- next exact command
```

---

## Command F - Paper Signal Monitoring Loop

Назначение: отслеживать открытые paper signals. После того как Signal создал paper signal (напр. Barnes NO), нужно периодически проверять: не появились ли новые факты, которые меняют тезис. Forager запускает короткий re-search по kill criteria; Signal обновляет forecast.

Запускать: после каждого Command C, плюс при появлении значимых новостей по открытому paper signal.

Скопируй в новый чат:

```text
Task: Run PAPER_SIGNAL_MONITORING_LOOP.

Markets to monitor:
[list of condition_ids / market URLs with paper signals]

Goal:
Check each open paper signal for material updates. Run a targeted Forager
re-search on kill criteria, then update Signal's forecast if evidence warrants.
Do not create new signals or positions. Update existing paper signal records only.

Workflow:
1. Run Universal Bootstrap.
2. Classify as L2 monitoring re-research (not L3 — no new signal creation).
3. Start workflow_runs record:
   workflow_name = paper_signal_monitoring_loop
   workflow_level = L2 monitoring
4. For each open paper signal:
   a. Load current dossier, checklist, and latest Forager packet.
   b. Extract kill criteria from dossier premortem / disconfirming_evidence field.
      If kill criteria are missing, derive them from the thesis:
      "What specific event, announcement, or data would make this thesis wrong?"
   c. Run Forager kill criteria re-search (short, targeted):
      POST /research/core-loop
      - seed_query = original market question
      - depth = shallow
      - recursive_rounds = 1
      - max_queries_per_round = 3
      - use build_kill_criteria_queries() from forager.search.query_mutation
      - results_per_query = 4
      - require_disconfirming_evidence = true
   d. Evaluate re-search packet:
      - signal_decision_value >= 0.50 → material update found, proceed to (e)
      - signal_decision_value < 0.50 → no material update, log and move on
   e. If material update found:
      - Use record_forecast_update to adjust estimated_probability
      - Record why the thesis is stronger or weaker
      - If thesis is now reversed (e.g. YES thesis found kill criterion met):
        mark signal as needs_review and escalate to operator
      - Do NOT auto-close or auto-create a new signal
5. Write report:
   docs/Signal/reports/YYYY-MM-DD - Paper Signal Monitoring Loop RU.md
6. Finish workflow_runs as completed or needs_operator_review.

Output:
- markets checked
- kill criteria used per market
- Forager packet signal_decision_value per market
- forecast updates made (old → new probability)
- markets needing operator review
- report path
- next monitoring schedule recommendation (days until next run)
```

Expected database boundary:

```text
Forager writes: forager_threads, forager_packets (re-search artifacts).
Signal writes: forecast_updates, workflow_runs, workflow_steps.
Signal does NOT create signals, positions, or fills.
```

---

## Command E - Signal + Forager Learning Loop

Назначение: обучение не только Signal, но и Forager: какие packets были полезны, где рекурсия дала мусор, где local-language слой реально создал edge.

Скопируй в новый чат:

```text
Task: Run SIGNAL_FORAGER_LEARNING_LOOP.

Goal:
Review resolved/open outcomes and Forager packets to improve both systems. Signal learns calibration; Forager learns which weak-signal patterns actually helped.

Workflow:
1. Run Universal Bootstrap.
2. Classify as L4 learning.
3. Load:
   - research_ledger(limit=200)
   - open_signals()
   - pending_outcome_reviews()
   - resolved markets without learning review
   - latest Forager packets for markets with Signal decisions
   - packet ids referenced by reports/workflow_steps
4. For each market with outcome or material update:
   - compare Signal thesis vs outcome
   - compare Forager packet vs outcome
   - identify whether Forager found something Signal would have missed
   - mark useful vs noisy weak signals
   - identify hallucination/over-recursion patterns
5. Write Signal learning records through approved Signal tools:
   - record_outcome_learning_review
   - record_forecast_update
   - record_signal_quality_review
6. Write Forager learning/calibration only through Forager paths if available:
   - source track record
   - calibration scores
   - anomaly reviews
7. Do not create new signals.
8. Write report:
   docs/Signal/reports/YYYY-MM-DD - Signal Forager Learning Loop RU.md

Output:
- what Signal learned
- what Forager learned
- useful Forager archetypes
- noisy Forager patterns
- source reliability changes
- calibration changes
- remaining learning debt
- next exact command
```

## Final Rule

Если агент сомневается, он должен выбрать более безопасный уровень:

```text
candidate > packet > dossier > checklist > approved candidate > signal gate
```

Нельзя прыгать сразу из красивого Forager packet в Signal position.
