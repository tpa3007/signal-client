# Signal Research Ledger Status Rules

The ledger is the authority for operational state.

Agents must not decide lifecycle status by prose. Status is derived from database facts.

## Status Model

```text
discovered
watch
deep_research
needs_more_research
approved_for_signal
no_signal
rejected
signal
open_position
resolved_pending_learning
learned
```

## Authority Rules

- If prose says `enter` but ledger says `needs_more_research`, ledger wins.
- If checklist is missing, status cannot be treated as approved.
- If a signal exists without approved pre-bet checklist before signal time, it is a `gate_violation`.
- If a market is resolved and no outcome learning review exists, status must be `resolved_pending_learning`.
- If a market is open and no recent update exists, it must appear as stale/monitoring debt.
- A watchlist item is not a signal.
- A hidden-gem review is not a signal.
- A moonshot review is not a signal.
- A markdown deep dive is not a signal.

## Gate Violation Rule

A signal/position/fill created without a prior `pre_bet_checklist.decision = approved_for_signal` must be treated as a critical maintenance issue.

The correct response is not to delete the record silently. The correct response is:

1. Preserve the historical fact.
2. Mark or surface the gate violation.
3. Create/return a repair/audit next action.
4. Add the missing checklist only if it reflects facts that existed before the signal time, and label it as a repair/audit record if supported.

## Dashboard Rule

Dashboard views must show both:

- the economic/research state, such as `open_position`;
- protocol health, such as `gate_violation=true`.

A real open position with a gate violation is still an open position, but it must be critical until audited.
