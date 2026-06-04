# Signal - Developer Handoff

## What This Project Is

Signal is a personal Polymarket research system. It is not primarily an automated trading bot.

Its core value is structured forecasting, evidence logging, calibration, and hidden-gem discovery.

## Current Codebase

Main project folders:

- `bot/` - MCP server, SQLite schema, Streamlit dashboard, terminal dashboard, paper loop.
- `research/` - Phase 0 scripts and initial vertical analysis.
- `docs/Signal/` - research vision and planning notes.

The cloned `polymarket-pipeline/` folder is a reference ancestor and should not be treated as the main codebase.

## Current Architecture

Claude Desktop calls local MCP tools:

- `fetch_candidates`;
- `get_market_details`;
- `record_analysis`;
- `analysis_log`;
- `open_signals`;
- `resolve_closed`;
- `performance_report`;
- `daily_run_status`;
- `finalize_daily_run`.

SQLite is the source of truth.

Important tables:

- `markets`;
- `snapshots`;
- `analyses`;
- `signals`;
- `daily_runs`.

## Most Important Recent Change

`record_analysis` now logs every analysis, not only emitted signals.

This is the first step toward proper calibration and research science.

## Next Best Engineering Tasks

1. Add executable bid/ask/spread snapshots.
2. Split `signals` and `positions`.
3. Add calibration metrics.
4. Add source/evidence table.
5. Add duplicate/idempotency protection.
6. Build market-level research memory.
7. Add tests around PnL, edge gates, and analysis logging.

## Design Principle

Every important decision should be reconstructable later.

If a developer changes the project, they should ask:

- Does this preserve research traceability?
- Does this improve calibration?
- Does this reduce hidden bias?
- Does this make the project more useful as a research instrument?

