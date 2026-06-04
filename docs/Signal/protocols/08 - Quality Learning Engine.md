# Signal - Quality Learning Engine

This note defines the layer that keeps Signal honest.

The project should not only produce better-looking research. It should measure whether that research improves forecast quality and helps find missed alpha.

## Why This Layer Exists

Structured reasoning can still become storytelling.

Signal needs a statistical conscience:

- Did our forecast beat the market snapshot?
- Were our probability buckets calibrated?
- Did high confidence actually mean better accuracy?
- Which no-signal markets later moved in our direction?
- Which hidden-gem reviews were made without enough research structure?

## Forecast Quality

Tool:

- `forecast_quality_report`

Metrics:

- Brier score;
- market Brier score;
- market-relative Brier;
- log score;
- market-relative log score;
- calibration buckets;
- confidence buckets;
- best and worst relative forecasts.

Positive market-relative Brier means Signal beat the market snapshot. Negative means the market was better.

## False Negative Review

Tool:

- `false_negative_review`

This searches no-signal analyses for missed opportunities:

- the market price later moved in the forecast direction;
- or the market resolved in the implied direction.

This is one of the most important hidden-gem loops. A system that only studies emitted signals will miss the alpha it was too cautious to take.

## Research Completeness

Tools:

- `research_completeness_score`
- `incomplete_research_queue`

The completeness score checks whether a market has:

- analysis;
- evidence base;
- actor map;
- causal model;
- scenario tree;
- premortem;
- hidden-gem review.

This prevents "thin" hidden-gem calls from looking as trustworthy as deeply researched ones.

## Price Movement After Analysis

Tool:

- `market_move_after_analysis`

This compares each analysis to later price snapshots for the same market.

It helps detect:

- stale prices;
- delayed market reaction;
- whether our thesis moved before resolution;
- whether no-signal decisions were too conservative.

## Current Limitations

Quality metrics only become meaningful after resolved analyses accumulate.

For the first weeks, the most valuable use is qualitative:

- inspect false negatives;
- inspect incomplete research;
- compare price moves after analysis;
- watch whether the dashboard starts showing calibration drift.

## Next Step

Once enough data exists, Signal should export these metrics into a research dataset so the methodology can become publishable.

