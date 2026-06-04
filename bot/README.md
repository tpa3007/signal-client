# Signal - personal Polymarket research terminal

Signal is a local, human-in-the-loop research system for Polymarket. It is built for paper-money, hold-to-resolution research: discover overlooked markets, build an auditable dossier, emit only gated paper signals, and learn from outcomes.

Auto-execution is out of scope. The project should help decide what deserves deep research, not trade by itself.

## Agent contract

Before any agent writes research data, it must read the root-level contract files:

- `AGENT_OPERATING_CONTRACT.md`
- `WORKFLOW_CONTRACTS.md`
- `WRITE_POLICY.md`
- `RESEARCH_LEDGER_STATUS_RULES.md`
- `AGENT_STARTUP_SEQUENCE.md`

Research writes must go through approved MCP/project tools. Direct SQLite insert scripts for evidence, analyses, signals, positions, or fills are forbidden outside named migrations or approved repair tasks.

## Current Architecture

1. **Discovery**
   - `discovery_scan` searches beyond obvious high-volume markets.
   - Strategies: `low_volume_research_sweetspot`, `stale_price`, `cheap_optionality`, `compounder_research_candidate`.
   - Discovery persists scanned markets and snapshots with `source='discovery'`, so candidates become part of project memory.
   - Markets are classified into `us_politics`, `international_geopolitics`, `tech_business`, and `science_space`.
   - Thematic tags such as `iran_cluster`, `us_primary_2026`, and `ai_launches` are saved in `market_tags`.

1b. **Account Intelligence**
   - `run_command_w.py` profiles Polymarket wallets, tracks smart/insider/whale positions, and watches whether tracked players agree or oppose our open positions.
   - Player analysis now separates player style/trust from raw size: early specialist, category sharp, whale-flow-only, low-trust player, or unclassified.
   - Market metadata lookups must validate exact `conditionId`; a slug or API fallback that returns another market is rejected.
   - Wallet-position alerts include signal strength and dust/noise filtering so a large or early trade is not automatically treated as insight.

1c. **Client Access Artifact**
   - `export_client_repo.py` builds a public `signal-client` artifact from `client_src/`.
   - The artifact contains client-mode contracts, a read-only `run_client_audit.py`, `rules.json`, and `INTEGRITY.lock`.
   - It excludes private runtime data (`bot.db`, ledgers, handoff files, reports, local secrets) and refuses to run when protected client logic is changed.
   - `/api/ingest` accepts explicitly shared client audits with a shared secret and redacts wallet identity unless consent is explicit.

2. **Research Dossier**
   - `record_evidence`
   - `record_resolution_map`
   - `record_actor_map`
   - `record_causal_factor`
   - `record_scenario`
   - `record_premortem`
   - `market_research_memory`

3. **Pre-Bet Gate**
   - `record_pre_bet_checklist` is the required gate before a serious paper signal.
   - A market must have latest checklist decision `approved_for_signal` before `record_analysis` can create a signal/position/fill.
   - If the checklist says `needs_more_research`, `record_analysis` records a no-signal analysis instead.

4. **Signal + Paper Position**
   - `record_analysis` computes executable edge, spread-aware gates, snapshot freshness, confidence gates, and portfolio-aware sizing.
   - Use `dry_run=True` for demos, experiments, and sanity checks. Dry runs do not write analysis, signal, position, or fill rows.

5. **Portfolio Risk**
   - `portfolio_snapshot`
   - `real_money_portfolio_audit`
   - `exposure_check`
   - `record_fill`
   - `mark_to_market_all`
   - `pending_outcome_reviews`
   - Exposure is capped by vertical, archetype, deadline week, single market, and thematic tag.
   - `real_money_portfolio_audit` is read-only: it aggregates real/hybrid fills, partial exits, residual shares, stale snapshots, gate/manual status, dossier completeness, and deadline risk into a prioritized review queue.

6. **Research Ledger / Monitoring**
   - `research_ledger` - unified lifecycle list for discovered/watch/rejected/signal/resolved/learned markets.
   - `catalyst_calendar`
   - `due_for_recheck`
   - `daily_research_brief`

7. **Learning Loop**
   - `record_outcome_learning_review`
   - `forecast_quality_report`
   - `false_negative_review`
   - `signal_quality_report`
   - `signal_regression_benchmark`

## Safe Daily Workflow

1. Start with `daily_research_brief`.
2. Inspect `portfolio_snapshot`, `catalyst_calendar`, and `due_for_recheck` if the brief flags risk.
3. If real money is on the book, run `real_money_portfolio_audit` before looking for fresh risk.
4. Run `discovery_scan` to find fresh candidates.
5. For promising candidates, call `backfill_price_history` when stale-price context matters.
6. Build the dossier: resolution map, evidence, actors, causal factors, scenarios, premortem.
7. Call `record_pre_bet_checklist`.
8. Call `record_analysis` only after the checklist returns `approved_for_signal`.
9. Use `dry_run=True` for demonstrations or incomplete research.
10. Record outcome reviews after resolution.

## Important Safety Rule

Do not run one-off demo scripts against `bot.db` unless they use `dry_run=True` or an isolated scratch database. A demo that creates signals/positions contaminates portfolio reports and calibration.

The Maine demo from 2026-05-18 was removed from live `bot.db`; the database backup is ignored by git and kept locally.

## Key Files

- `bot/mcp_server.py` - thin MCP entry point.
- `bot/tools/` - MCP tool groups.
- `bot/lib/` - pure helpers for execution, scoring, discovery, sizing, exposure, and PnL.
- `bot/db.py` - SQLite schema and persistence helpers.
- `bot/config.py` - thresholds, bankroll, gates, and discovery settings.
- `bot/tests/` - pytest regression suite.
- `docs/Signal/` - research architecture, roadmap, audits, and session logs.

## Local Setup

```powershell
cd C:\Signal\bot
py -3.12 -m pip install -r requirements.txt
py -3.12 -m pytest -q
```

Configure Claude Desktop MCP to point at:

```text
C:\Signal\bot\mcp_server.py
```

## Doctrine

Signal should prefer fewer, better-researched hold-to-resolution signals over a stream of exciting but weak ideas. Hidden gems are not random longshots; they are markets where structure, source asymmetry, resolution clarity, high-conviction mid-price mispricing, and crowd neglect combine into a repeatable research edge.

