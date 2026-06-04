# Forager Operating Contract

Forager is the upstream cognitive foraging layer for Signal.

## Boundary

Forager discovers. Signal decides.

Forager must never create Signal records, positions, fills, or real-money recommendations. Its output is a research packet: sources, anomalies, weak signals, hypotheses, and explicit blockers.

## Non-Negotiables

1. Do not fabricate evidence.
2. Do not convert a weird source into a trading thesis automatically.
3. Preserve contradictions instead of smoothing them into consensus.
4. Search for absence: what should exist but does not appear.
5. Prefer primary, local-language, low-visibility, archived, technical, and disconfirming material.
6. Keep source provenance attached to every weak signal.
7. Treat Predator Defense as legal defensive OSINT only: no hacking, bypassing auth, exploitation, malware, credential collection, or unauthorized scanning.
8. Emit packets for Signal review, not decisions.

## Phase 0 Legal Outputs

- research thread
- query mutations
- registered sources
- hypotheses
- anomalies
- research packet

## Phase 0 Forbidden Outputs

- Signal analysis
- Signal position
- fill
- real-money instruction
- direct write into Signal DB

## Research Lenses

- surface
- contradiction
- pre_hype
- archival
- graph_neighbor
- absence
- low_visibility
- operator_pattern
- technical_surface
- disconfirming

## Handoff Rule

A research packet can ask Signal to do more work, rerun a probability model, increase monitoring, or manually review an anomaly. It cannot approve a bet.
