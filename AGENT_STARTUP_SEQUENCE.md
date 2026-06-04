# Signal Agent Startup Sequence

Every agent must run this sequence before doing project work.

## Step 1. Read Project Contract

Read first:

- `AGENT_OPERATING_CONTRACT.md`
- `WORKFLOW_CONTRACTS.md`
- `WRITE_POLICY.md`
- `RESEARCH_LEDGER_STATUS_RULES.md`
- `AGENT_RUNTIME_SETUP_RU.md`
- `docs/Signal/core/00 - North Star.md`
- `docs/Signal/protocols/27 - Research Ledger RU.md`
- `docs/Signal/workflows/MASTER_AGENT_COMMANDS_RU.md`
- `forager/OPERATING_CONTRACT.md`
- `docs/Signal/technical/49 - Forager Core Priorities RU.md`
- `docs/Signal/workflows/SIGNAL_FORAGER_MASTER_COMMANDS_RU.md`

## Step 2. Identify Workflow Level

Classify the user request as:

- L0 briefing;
- L1 enrichment;
- L2 deep research;
- L3 signal commit;
- L4 learning;
- L5 maintenance;
- docs/report only.

If ambiguous, default to the lower-risk workflow.

## Step 3. Load Current Project State

Use available tools or read-only queries to inspect:

- `research_ledger(limit=100)`;
- `portfolio_snapshot()`;
- `pending_outcome_reviews()`;
- `incomplete_research_queue(limit=20)`;
- `open_signals()`;
- `master_maintenance_audit()`.

## Step 4. Declare Allowed Writes Internally

Before writing, identify:

- active workflow level;
- allowed write tools;
- forbidden actions;
- stop conditions.

## Step 5. Execute Workflow

Use only approved MCP/project tools for writes.

Do not write direct SQL for research facts.
Do not create one-off insert scripts.
Do not create signal/position/fill unless L3 gates pass.

## Step 6. End With Structured Result

Report:

- workflow level;
- tools/actions used;
- records written;
- records blocked;
- signal created: yes/no;
- gate violations found;
- next action;
- remaining learning debt.
