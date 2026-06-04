# Signal - Research Architecture

Signal should evolve into a layered research system.

## Layer 1 - Market Intake

Purpose: build the universe of markets worth looking at.

Inputs:

- Polymarket Gamma markets;
- CLOB prices/orderbook data;
- volume, liquidity, spread;
- time to resolution;
- category and vertical tags;
- exclusion filters for sports/esports/noise.

Output:

- candidate market list;
- daily snapshots;
- market metadata;
- resolution criteria.

Next improvements:

- expand use of spread and best bid/ask throughout candidate ranking;
- classify market type more carefully;
- store resolution source and market description;
- flag ambiguous markets before research.

## Layer 2 - Research Log

Purpose: preserve every forecast attempt.

The `analyses` table is the backbone. It should store both signals and no-signal decisions.

Fields that matter:

- run date;
- market id;
- market price at analysis;
- probability estimate;
- confidence;
- reasoning;
- sources;
- decision;
- no-signal reason;
- linked signal id if one exists.

This enables calibration, false-negative analysis, and proper research review.

## Layer 3 - Forecasting Protocol

Each serious analysis should follow a structured protocol:

- exact resolution criteria;
- current market price and executable price;
- base rate;
- YES case;
- NO case;
- source quality;
- catalysts before resolution;
- uncertainty and missing information;
- final probability;
- confidence;
- decision.

The forecast should be a calibrated probability, not a story.

## Layer 4 - Signal Generation

A signal is a forecast that survives trading constraints.

Requirements:

- edge above threshold;
- confidence above threshold;
- spread-adjusted/executable edge still positive;
- liquidity sufficient;
- resolution rules understood;
- thesis written clearly enough to audit later.

## Layer 5 - Position Journal

Signals and positions are different things.

A signal says: "we believe probability differs from market price."

A position says: "we entered or simulated an entry at this executable price."

Future schema should split:

- `signals`;
- `positions`;
- `fills`;
- `resolutions`;
- `pnl_events`.

## Layer 6 - Calibration Lab

Signal should eventually report:

- Brier score;
- log score;
- calibration curve;
- market-relative calibration;
- ROI by edge bucket;
- ROI by confidence bucket;
- ROI by vertical;
- ROI by time-to-resolution;
- spread-adjusted ROI;
- paper/live execution gap.
