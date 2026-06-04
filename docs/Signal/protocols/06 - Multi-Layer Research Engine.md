# Signal - Multi-Layer Research Engine

This note defines the next stage of Signal: moving from "one forecast per market" to a layered research memory.

The goal is not to add more market categories yet. The goal is to think more deeply about each market that already enters the lab.

## New Research Layers

### 1. Evidence Layer

Every important source should become an evidence item:

- source URL or publication;
- extracted claim;
- stance: `YES`, `NO`, `MIXED`, or `NEUTRAL`;
- strength;
- reliability;
- freshness;
- notes.

This prevents the project from remembering only conclusions. It preserves the raw claims that caused the forecast to move.

Tool:

- `record_evidence`

### 2. Forecast Update Layer

Forecasts should not overwrite older forecasts.

When new information changes the probability, the system stores:

- previous probability;
- updated probability;
- delta;
- trigger;
- reason;
- sources.

This makes belief evolution auditable. Later, Signal can study whether updates improved accuracy or only added noise.

Tool:

- `record_forecast_update`

### 3. Hidden-Gem Review Layer

A hidden gem is not just "Claude probability differs from price".

A real hidden gem should combine:

- executable edge;
- liquidity that can support a position;
- spread that does not destroy entry;
- evidence asymmetry;
- attention gap;
- stale market price;
- upcoming catalyst;
- clear resolution rules.

The system now stores a weighted `hidden_gem_score` from 0 to 100.

Tool:

- `record_hidden_gem_review`

### 4. Market Dossier Layer

Every market can now be inspected as a dossier:

- latest execution context;
- analyses;
- evidence;
- forecast updates;
- hidden-gem reviews;
- signals.

Tool:

- `market_research_memory`

### 5. Watchlist Layer

The watchlist should contain markets that deserve more thought, not necessarily immediate signals.

Tool:

- `hidden_gem_watchlist`

### 6. Causal / Contrarian Layer

Hidden gems need causal structure, not just evidence.

The project can now store:

- actor maps;
- causal factors;
- anomalies;
- scenario trees;
- premortems.

Tools:

- `record_actor_map`
- `record_causal_factor`
- `record_anomaly`
- `record_scenario`
- `record_premortem`
- `contrarian_brief`

## Suggested Daily Deep-Research Flow

For a promising candidate:

1. Call `get_market_details`.
2. Read resolution criteria.
3. Record 2-6 evidence items with `record_evidence`.
4. Estimate probability and call `record_analysis`.
5. Force a skeptic pass: write the best reason this market is not a gem.
6. Record actors, causal factors, anomalies, scenarios, and premortem when the market deserves deeper work.
7. Call `contrarian_brief`.
8. Call `record_hidden_gem_review`.
9. If new information arrives later, call `record_forecast_update`.
10. Review `hidden_gem_watchlist` before deciding what deserves more research time.

## Why This Matters

The project should learn from:

- signals;
- non-signals;
- source quality;
- thesis updates;
- markets that looked good but failed skeptic review;
- markets that were watchlisted before the price moved.

That is the difference between a signal bot and a research lab.
