# Signal - Roadmap

## Phase 1 - Research Memory Foundation

Status: in progress.

Goals:

- log every market analysis;
- track no-signal decisions;
- expose research log in dashboard;
- add MCP `analysis_log`;
- make daily status include analysis count.

Why it matters:

Without this, the project only remembers signals. A real research project must remember the whole decision surface.

## Phase 2 - Spread-Aware Edge

Status: in progress.

Goals:

- store best bid, best ask, spread, and liquidity in snapshots;
- compute executable YES/NO entry prices;
- reject signals where edge disappears after spread;
- track paper entry price separately from market midpoint.

Implemented so far:

- snapshots can store bid/ask/spread and executable YES/NO entry prices;
- candidate fetch returns entry prices and spread when available;
- `record_analysis` chooses the best executable side and gates on executable edge;
- `MAX_SPREAD` rejects wide-spread signals;
- signal PnL uses a side-entry equivalent instead of raw YES midpoint.

## Phase 3 - Forecast Quality Metrics

Status: in progress.

Goals:

- Brier score;
- calibration buckets;
- log score;
- market-relative score;
- ROI by confidence and edge bucket;
- vertical-level analytics;
- false-positive and false-negative review.

Implemented so far:

- `forecast_quality_report` computes Brier/log score and market-relative quality;
- calibration and confidence buckets are exposed through MCP;
- `false_negative_review` searches no-signal analyses for missed alpha;
- `market_move_after_analysis` compares forecasts to later price snapshots;
- dashboard shows the first Learning block for resolved forecasts.

## Phase 4 - Deep Research Workflow

Status: in progress.

Goals:

- enforce resolution criteria review;
- save source evidence records;
- add YES/NO case structure;
- add skeptic pass;
- add contradiction check;
- add catalyst calendar.

Implemented so far:

- `evidence` table stores source-level claims;
- `forecast_updates` table preserves probability changes;
- `hidden_gem_reviews` stores weighted hidden-gem scores;
- MCP tools can record evidence, update forecasts, score hidden gems, show a watchlist, and return a market dossier.

## Phase 5 - Research Memory and Updates

Status: in progress.

Goals:

- market-level research history;
- "what changed since last analysis";
- stale source detection;
- thesis versioning;
- update forecasts without overwriting older forecasts.

Implemented so far:

- `market_research_memory` returns the dossier for one market;
- `record_forecast_update` stores probability deltas without overwriting prior forecasts.
- `research_completeness_score` and `incomplete_research_queue` identify thin research dossiers.

## Phase 6 - Hidden Gem Engine

Status: in progress.

Goals:

- rank candidates by hidden-gem score;
- identify undercovered but liquid markets;
- detect stale prices;
- detect attention gaps;
- find markets with asymmetric information availability;
- compare crowd movement vs source updates.

Implemented so far:

- actor maps capture who can move the outcome;
- causal factors separate mechanism from narrative;
- anomalies store weird or stale market observations;
- scenario trees store multiple paths to resolution;
- premortems force a skeptic pass;
- `contrarian_brief` summarizes the causal dossier before hidden-gem review.

## Phase 7 - Paper-to-Live Discipline

Goals:

- separate signals from positions;
- track paper fills and real fills;
- model slippage;
- enforce bankroll and exposure rules;
- make live positions auditable.

## Phase 8 - Research Paper Layer

Goals:

- export clean datasets;
- generate experiment logs;
- write methodology;
- compare LLM forecasts vs market prices;
- analyze when human-in-loop LLM research adds value.
