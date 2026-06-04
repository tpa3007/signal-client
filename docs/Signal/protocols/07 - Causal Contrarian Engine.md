# Signal - Causal Contrarian Engine

This note defines the next layer of Signal's thinking: moving from evidence and forecasts into causal models.

The goal is to notice what the market may not be modeling:

- who actually controls the outcome;
- which mechanism matters more than the headline;
- what looks weird or stale;
- which path to resolution is underpriced;
- how our own thesis could fail.

## Core Idea

Hidden gems are often not hidden because the information is private.

They are hidden because public information is not connected correctly.

Signal should therefore ask:

- What is the market probably watching?
- What is the market probably ignoring?
- Which actor has the power to change the outcome?
- Which procedural step is required?
- Which missing confirmation matters?
- Which scenario is weird but plausible?
- What would kill our thesis?

## New Memory Objects

### Actor Maps

Tool:

- `record_actor_map`

Stores:

- actor name;
- actor type;
- role;
- incentives;
- constraints;
- likely action;
- influence score;
- visibility score.

This helps distinguish loud actors from decisive actors.

### Causal Factors

Tool:

- `record_causal_factor`

Stores:

- factor name;
- mechanism;
- direction: `YES`, `NO`, `MIXED`, or `UNKNOWN`;
- importance;
- uncertainty;
- observable signal;
- current state;
- next check date.

This forces the research to explain how the outcome actually happens.

### Anomalies

Tool:

- `record_anomaly`

Stores:

- anomaly type;
- observation;
- why it matters;
- implied direction;
- severity;
- confidence;
- status;
- source URL.

Examples:

- price did not move after a source update;
- a key actor is silent;
- the headline implies YES but resolution rules imply NO;
- an operational step is missing;
- an old source is still anchoring the market.

### Scenario Trees

Tool:

- `record_scenario`

Stores:

- scenario name;
- path;
- probability;
- outcome side;
- key assumptions;
- breakpoints;
- early warning signals.

This prevents a single thesis from hiding alternative paths.

### Premortems

Tool:

- `record_premortem`

Stores:

- thesis;
- failure mode;
- disconfirming signal;
- probability if wrong;
- mitigation;
- severity.

This is the built-in skeptic pass.

### Contrarian Brief

Tool:

- `contrarian_brief`

Returns the causal dossier for one market:

- actors;
- causal factors;
- anomalies;
- scenarios;
- premortems.

Use it before `record_hidden_gem_review`.

## Suggested Research Ritual

For any market that looks promising:

1. Record at least 2 actors.
2. Record at least 2 causal factors.
3. Record any anomaly, including absence of expected evidence.
4. Build 3 scenarios: YES path, NO path, weird/delay path.
5. Write a premortem.
6. Generate `contrarian_brief`.
7. Only then score the hidden gem.

The point is not bureaucracy. The point is to slow the mind down at the exact places where prediction markets often misprice reality.

## What "Between The Lines" Means Here

Between the lines does not mean inventing conspiracies.

It means noticing public but under-modeled structure:

- incentives;
- constraints;
- sequencing;
- missing confirmations;
- timing;
- bureaucratic friction;
- contradiction between rhetoric and mechanism.

This is the layer where Signal should become genuinely unusual.

