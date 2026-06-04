# Signal - Spread-Aware Edge

This note describes the first execution-quality upgrade.

## Problem

The early version compared Claude probability to `yes_price`.

That is not enough.

Prediction markets have spreads. A forecast can look attractive against midpoint or displayed outcome price but disappear when buying the actual YES or NO token.

Example:

- displayed YES: 0.50;
- YES ask: 0.56;
- Claude probability: 0.54.

Naively this looks like +4% edge. Executably it is -2% edge.

## Current Implementation

Snapshots can now store:

- `no_price`;
- `best_bid`;
- `best_ask`;
- `spread`;
- `yes_entry_price`;
- `no_entry_price`.

When bid/ask exists:

- buying YES uses `best_ask`;
- buying NO is approximated as `1 - best_bid`;
- spread is `best_ask - best_bid` if not directly provided.

When orderbook fields are missing, the system falls back to outcome prices.

## Signal Logic

For every analysis:

- YES edge = `probability_yes - yes_entry_price`;
- NO edge = `(1 - probability_yes) - no_entry_price`;
- the system chooses the better executable side;
- if executable edge is below threshold, no signal;
- if spread is wider than `MAX_SPREAD`, no signal;
- if confidence is too low, no signal.

This means Signal can now say:

"The forecast is directionally different from the displayed price, but not tradable after spread."

That distinction is essential for real research.

## Next Improvements

- fetch full CLOB orderbook for high-conviction markets;
- estimate slippage for planned bet size;
- store depth at multiple levels;
- track maker vs taker execution;
- separate signal price from actual fill price;
- compute paper PnL using executable simulated fills.

