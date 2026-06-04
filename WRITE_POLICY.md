# Signal Write Policy

This policy controls how agents may mutate project state.

## Allowed

### MCP / Project Tools

Research writes are allowed only through approved tools such as:

- `record_resolution_map`
- `record_evidence`
- `record_actor_map`
- `record_causal_factor`
- `record_scenario`
- `record_premortem`
- `record_hidden_gem_review`
- `record_moonshot_review`
- `record_pre_bet_checklist`
- `record_analysis`
- `record_forecast_update`
- `record_outcome_learning_review`
- `record_signal_quality_review`
- `validate_signal_gate` (read-only)
- `aladdin_signal_commit` (formal paper signal path)
- `record_real_manual_trade` (manual/retrospective real trade reconciliation)
- `record_fill`

### Read-Only Scripts

Allowed for:

- inspection;
- reports;
- schema discovery;
- diagnostics;
- exports.

They must not mutate the database.

### Migrations

Allowed only when:

- changing schema;
- idempotent;
- named clearly;
- tests are added;
- backup is recommended or created.

### Repair Scripts

Allowed only when:

- operator explicitly requests repair;
- backup exists or is explicitly waived;
- script is idempotent;
- script logs every affected row;
- script does not invent research facts.

## Forbidden

- one-off script to insert evidence;
- one-off script to insert actor maps;
- one-off script to insert scenarios;
- one-off script to insert signal;
- one-off script to create position/fill;
- direct SQL updates to research conclusions;
- bypassing pre-bet checklist;
- creating formal paper signals outside `aladdin_signal_commit`;
- creating position from markdown conclusion;
- normalizing invalid records silently without an audit trail.

## Missing Tool Rule

If a needed write tool does not exist:

1. Do not write direct SQL.
2. Propose the missing tool.
3. Implement the tool with tests if authorized by the task.
4. Use the tool.

The correct answer to missing workflow support is better tooling, not database improvisation.
