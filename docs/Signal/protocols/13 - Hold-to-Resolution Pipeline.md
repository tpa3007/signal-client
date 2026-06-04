# Signal - Hold-to-Resolution Pipeline

This is the serious research spine of Signal.

For now, Signal should not optimize for buying and selling around repricing. The default research mode is:

> find market -> research deeply -> decide entry/no-entry -> hold to resolution -> learn.

That requires three layers.

## 1. Resolution-First Engine

Tool:

- `record_resolution_map`

Purpose:

Before any serious signal, define the actual contract.

The map stores:

- what counts as YES;
- what counts as NO;
- primary resolution source;
- secondary sources;
- deadline;
- ambiguity cases;
- non-qualifying events;
- required artifact;
- resolution risk;
- wording trap risk;
- source/deadline clarity.

This prevents headline betting.

Examples:

- Gemini: "Google announced Gemini" is not enough; the market requires a public qualifying reasoning flagship.
- Knesset: bill submission is not enough; the market requires actual dissolution before the deadline.
- Figure: the official counter must reach the threshold before the exact deadline.

## 2. Pre-Bet Research Checklist

Tool:

- `record_pre_bet_checklist`

Purpose:

This is the gate before treating an idea as a hold-to-resolution candidate.

It checks:

- resolution map exists;
- evidence base exists;
- actor map exists;
- causal model exists;
- scenario tree exists;
- premortem exists;
- optional Moonshot review exists;
- evidence balance is acceptable;
- spread/liquidity are acceptable;
- sizing is acceptable;
- resolution risk is acceptable.

The checklist can block an idea even when edge looks attractive.

That is intentional. A hold-to-resolution signal must survive the full research path.

## 3. Outcome Learning Engine

Tool:

- `record_outcome_learning_review`

Purpose:

After resolution, Signal should learn why a signal worked or failed.

The review stores:

- outcome side;
- predicted side;
- probability and confidence;
- Brier score;
- market Brier score when available;
- realized PnL;
- why the thesis was right or wrong;
- resolution error;
- probability error;
- evidence error;
- timing error;
- sizing error;
- luck factor;
- repeatable lesson;
- rule update.

This turns every resolved market into training data.

## Supporting Tool

- `resolution_first_queue`

This lists analyzed/signal markets that still do not have a resolution map.

It is a cleanup queue. If a market is in this queue, it should not be trusted as a serious hold-to-resolution candidate yet.

## Current Seeded Maps

Resolution maps now exist for:

- Gemini reasoning flagship;
- Israeli parliament dissolved by May 31;
- Figure F.03 250k packages.

Pre-bet checklists now exist for:

- Gemini reasoning flagship: high structure, blocked by resolution risk.
- Israeli parliament dissolved by May 31: live edge, but needs deeper dossier before serious hold-to-resolution confidence.

## Core Principle

Signal should be imaginative at intake and strict before entry.

Moonshot Scout may say:

> "This is interesting."

Resolution-first and pre-bet checklist ask:

> "Is it true enough, clear enough, and researched enough to hold to resolution?"

Outcome learning later asks:

> "What did this teach us?"
