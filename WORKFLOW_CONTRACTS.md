# Signal Workflow Contracts

This document defines what each workflow level is allowed to do.

## Cross-Cutting - Signal + Forager Boundary

Forager is the upstream discovery layer. Signal is the decision and position layer.

Allowed Forager outputs:

- research threads;
- raw source items;
- sources/documents/entities/claims;
- contradiction clusters;
- evidence drafts;
- research packets;
- Signal bridge packets.

Forbidden Forager outputs:

- Signal analyses;
- Signal pre-bet approvals;
- signals;
- positions;
- fills;
- real-money instructions.

Default Forager path:

```text
POST /research/core-loop
POST /attention/minimal
```

Phase 16/17 ecology layers are experimental/north-star only unless the operator explicitly requests an experimental run.

## Cross-Cutting - Workflow Journal

Every master workflow should create a `workflow_runs` row and one or more `workflow_steps` rows.

Required step fields:

- `step_name`;
- `status`;
- `allowed_writes`;
- `writes_count`;
- `blocker` when blocked;
- `output_ref` for report paths;
- `output_json` for record IDs, candidate counts, or gate summaries.

Status rules:

- `running` while the workflow is active;
- `completed` only after the expected workflow output exists;
- `blocked` when a gate, source gap, missing tool, or operator constraint stops progress;
- `failed` for unexpected runtime errors.
## L0 - Briefing / Master Cycle

Tools: `aladdin_master_cycle`, `master_market_discovery`, `daily_research_brief`.

Purpose: open the project and understand current state.

Allowed writes:

- markets;
- snapshots;
- market tags;
- discovery artifacts.

Forbidden writes:

- final analyses;
- signals;
- positions;
- fills;
- outcome conclusions.

Expected output:

- portfolio exposure;
- pending outcome reviews;
- stale positions;
- incomplete dossiers;
- top candidates;
- operator priorities;
- recommended next calls.

L0 returns next actions. It does not complete research or create signals.

## L1 - API / Source Enrichment

Tools: `api_research_enrichment`, integration tools, source search tools.

Purpose: collect context and source candidates.

Allowed writes:

- market/snapshot refreshes when the tool is designed to do so;
- source status or raw source items when implemented;
- draft evidence only if explicitly supported by the tool.

Forbidden writes:

- `record_analysis`;
- signals;
- positions;
- fills.

Expected output:

- source summary;
- primary sources found;
- missing direct sources;
- source errors;
- confidence cap;
- recommended next action.

## L2 - Deep Research

Purpose: build one market dossier.

Mandatory chain:

1. get market details and latest snapshot;
2. parse/check resolution rules;
3. record resolution map;
4. collect sources;
5. record evidence;
6. record actor map;
7. record causal factors;
8. record scenario tree;
9. record premortem;
10. record hidden-gem/moonshot/compounder review;
11. compute dossier completeness;
12. record pre-bet checklist.

Allowed writes:

- resolution maps;
- evidence;
- actor maps;
- causal factors;
- scenarios;
- premortems;
- hidden-gem reviews;
- moonshot reviews;
- pre-bet checklists;
- forecast updates only when updating an existing thesis.

Forbidden writes:

- signals;
- positions;
- fills.

Expected decision:

```text
reject | watch | needs_more_research | approved_for_signal
```

## L3 - Signal Commit

Purpose: the only workflow level that may convert approved research into a signal.

Input:

```text
condition_id
side
probability_yes
confidence
paper_only=true by default
```

Mandatory checks:

- fresh snapshot;
- approved pre-bet checklist;
- resolution map exists;
- evidence count >= 2;
- actor map exists;
- causal factors >= 2;
- scenario tree exists;
- premortem exists;
- spread/liquidity OK;
- exposure OK;
- confidence threshold OK;
- edge threshold OK;
- source depth OK.

If all checks pass:

- call `aladdin_signal_commit` as the formal L3 paper signal path;
- `aladdin_signal_commit` writes the analysis, signal, paper position, and paper fill;
- report IDs written.

If any check fails:

- no signal;
- no position;
- no fill;
- return blocked reason and next action.

## L4 - Learning

Tools: `master_learning_cycle`, `record_outcome_learning_review`, `record_forecast_update`, `record_signal_quality_review`, benchmark/source tools.

Purpose: keep the system improving.

Allowed writes:

- outcome learning reviews;
- forecast updates;
- signal quality reviews;
- signal archetype reviews;
- source track-record updates where supported.

Expected output:

- resolved markets without learning;
- stale open positions;
- false negatives;
- archetype performance;
- source track record;
- rule updates.

## L5 - Maintenance

Tools: `master_maintenance_audit`, repair tools when explicitly approved.

Purpose: detect and repair state hygiene problems.

Checks:

- signals without approved pre-bet checklist;
- signals without analysis;
- positions without snapshots;
- evidence without source;
- invalid enum values;
- resolved markets without learning;
- duplicate docs or legacy artifacts;
- source failures.

Allowed writes:

- maintenance tasks if implemented;
- source status if implemented;
- approved repair scripts only after backup.

Forbidden writes:

- inventing research facts;
- changing conclusions without a recorded audit trail.
## L3b - Manual Real Trade Reconciliation

Tool: `record_real_manual_trade`.

Purpose: honestly record operator-entered real-money trades that already happened or were entered manually outside the formal Signal commit path.

Allowed writes:

- manual/retrospective signal row with `manual_trade=1` and `retrospective=1`;
- real position;
- real entry/exit fills;
- manual analysis row explaining that this did not pass prior pre-bet approval.

Forbidden writes:

- fake historical pre-bet checklists;
- fake evidence timestamps;
- pretending a manual real trade was a formal approved Signal.

Ledger rule: manual trades are excluded from `gate_violation`, but they remain visible as real open/closed positions and should receive retrospective learning/research notes later.
