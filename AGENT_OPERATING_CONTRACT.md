# Signal Agent Operating Contract

This is the runtime contract for any Claude, Codex, ChatGPT, or other agent operating inside Signal.

Signal is a personal Polymarket research OS. It is not an auto-trading bot. Its lifecycle is:

```text
candidate -> research -> dossier -> checklist -> signal/no-signal -> hold/monitor -> outcome learning
```

Your job is to preserve traceability, calibration, and research discipline.

## 1. Non-Negotiable Rules

1. No invisible decisions.
2. Discovery is not a signal.
3. Moonshot review is not a signal.
4. Hidden-gem review is not a signal.
5. A good markdown deep dive is not permission to enter.
6. High dossier completeness is not permission to enter.
7. No signal without an approved pre-bet checklist.
8. No direct SQLite writes for research facts.
9. No one-off Python insert scripts for evidence, reviews, analyses, signals, positions, or fills.
10. No signal/position/fill creation outside `aladdin_signal_commit` or another explicitly approved project tool path.
11. No real-money recommendation unless the user explicitly asks and project state supports it.
12. If source depth is thin, cap confidence and record the blocker.
13. If a required tool is missing, propose or implement the tool with tests instead of bypassing the workflow.

## 2. Allowed Write Paths

Research data must be written through MCP/project tools only:

- `record_resolution_map`
- `record_evidence`
- `record_actor_map`
- `record_causal_factor`
- `record_scenario`
- `record_premortem`
- `record_anomaly`
- `record_hidden_gem_review`
- `record_moonshot_review`
- `record_pre_bet_checklist`
- `record_analysis`
- `record_forecast_update`
- `record_outcome_learning_review`
- `record_signal_quality_review`
- `record_signal_archetype`
- `validate_signal_gate` (read-only gate validation)
- `aladdin_signal_commit` (the formal L3 paper signal creation path)
- `record_real_manual_trade` (manual/retrospective operator real-money reconciliation only)
- `start_workflow_run` / `record_workflow_step` / `finish_workflow_run` for laboratory session traceability
- `record_fill`, only for actual fills or explicit paper-fill workflow

Direct SQL/Python insertion is forbidden unless this is a named migration or approved repair task with backup, tests, and an affected-row log.

## 3. Signal Creation Gate

Before creating any formal paper signal, position, or fill, call `validate_signal_gate` or use `aladdin_signal_commit`, which performs this validation:

- latest snapshot exists and is fresh;
- resolution map exists;
- evidence count is at least 2;
- actor map exists;
- causal factors count is at least 2;
- scenario tree exists;
- premortem exists;
- latest pre-bet checklist exists;
- checklist decision is exactly `approved_for_signal`;
- spread and liquidity gates pass;
- exposure check passes;
- confidence and edge clear thresholds;
- source depth is not below required threshold;
- no unresolved blocker remains.

If any required condition fails:

- do not create a signal;
- do not create a position;
- do not create a fill;
- return or record a blocked/no-signal decision;
- set `next_action` to the missing block.

## 4. Writing Behavior

When writing research:

- write source-backed claims, not vibes;
- distinguish primary, secondary, social, market, and model-derived evidence;
- record disconfirming evidence;
- record source absence when important;
- separate probability from confidence;
- separate edge from decision;
- separate paper signal from real position;
- never turn prose into database truth without the legal tool path.

## 5. Workflow Levels

Always identify the active workflow level before writing:

```text
L0 briefing
L1 enrichment
L2 deep research
L3 signal commit
L4 learning
L5 maintenance
```

Never perform a higher-level action inside a lower-level workflow.

## 6. Stop Conditions

Stop and report blockers if:

- resolution rules are unclear;
- direct resolution source is missing;
- source APIs fail in a way that affects confidence;
- evidence is one-sided;
- there is no premortem;
- checklist is missing or not approved;
- exposure cap is breached;
- user asks to skip gates;
- the only path forward would require direct DB writes.

## 7. Ledger Authority

The project ledger wins over prose.

If a markdown note says "enter" but `research_ledger` says `needs_more_research`, the ledger wins.
If a signal exists without approved pre-bet checklist, treat it as a gate violation unless `manual_trade=1` marks it as an honest operator-entered real trade. Manual trades are not formal research Signals and must not be retroactively faked into approved dossiers.
## 8. Workflow Journal

Every serious master workflow should leave an auditable lab trail.

Use `workflow_runs` for the session-level record and `workflow_steps` for each major action, blocker, allowed write set, and records-created summary. If a workflow stops early, finish it as `blocked` or `failed`, not `completed`.

A research result without a workflow journal is incomplete session hygiene.
