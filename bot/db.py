"""SQLite schema + helpers. One file = one source of truth for state."""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    condition_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    slug TEXT,
    end_date TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    resolved INTEGER DEFAULT 0,
    resolved_yes REAL,
    resolved_at TEXT,
    vertical TEXT DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    yes_price REAL NOT NULL,
    no_price REAL,
    best_bid REAL,
    best_ask REAL,
    spread REAL,
    yes_entry_price REAL,
    no_entry_price REAL,
    volume REAL,
    liquidity REAL,
    source TEXT DEFAULT 'fetch',
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_snap_market ON snapshots(condition_id, captured_at);

CREATE TABLE IF NOT EXISTS market_tags (
    condition_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL,
    PRIMARY KEY (condition_id, tag),
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_market_tags_tag ON market_tags(tag, condition_id);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    model TEXT NOT NULL,
    yes_price_at_signal REAL NOT NULL,
    yes_equivalent_entry REAL,
    side_entry_price REAL,
    claude_prob REAL NOT NULL,
    confidence REAL NOT NULL,
    side TEXT NOT NULL,
    edge REAL NOT NULL,
    bet_amount REAL NOT NULL,
    reasoning TEXT,
    sources_json TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cache_read_tokens INTEGER,
    cost_usd REAL,
    resolved INTEGER DEFAULT 0,
    realized_pnl REAL,
    -- Real money tracking (NULL = paper only)
    real_money INTEGER DEFAULT 0,
    real_entry_price REAL,
    real_bet_usd REAL,
    real_shares REAL,
    real_filled_at TEXT,
    real_max_payout REAL,
    real_pnl_actual REAL,
    manual_trade INTEGER DEFAULT 0,
    retrospective INTEGER DEFAULT 0,
    operator_decision TEXT,
    price_model_version TEXT DEFAULT 'legacy',
    gate_status TEXT DEFAULT 'unknown',
    gate_audit_note TEXT,
    signal_generation_epoch TEXT DEFAULT 'legacy',
    edge_archetype TEXT,
    confidence_source TEXT DEFAULT 'automated_score',
    approval_strength TEXT,
    post_entry_review_required INTEGER DEFAULT 0,
    post_entry_review_reason TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_sig_market ON signals(condition_id);
CREATE INDEX IF NOT EXISTS idx_sig_created ON signals(created_at);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    analyst TEXT NOT NULL DEFAULT 'claude-desktop',
    model TEXT NOT NULL,
    yes_price_at_analysis REAL NOT NULL,
    probability_yes REAL NOT NULL,
    confidence REAL NOT NULL,
    edge REAL NOT NULL,
    decision TEXT NOT NULL,
    no_signal_reason TEXT,
    signal_id INTEGER,
    reasoning TEXT,
    sources_json TEXT,
    notes TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id),
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);
CREATE INDEX IF NOT EXISTS idx_analysis_market ON analyses(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_run ON analyses(run_date, created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_decision ON analyses(decision);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_url TEXT,
    source_name TEXT,
    published_at TEXT,
    claim TEXT NOT NULL,
    stance TEXT NOT NULL DEFAULT 'NEUTRAL',
    strength REAL NOT NULL DEFAULT 0.5,
    reliability REAL NOT NULL DEFAULT 0.5,
    freshness REAL NOT NULL DEFAULT 0.5,
    notes TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_market ON evidence(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evidence_stance ON evidence(stance);

CREATE TABLE IF NOT EXISTS forecast_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    previous_probability_yes REAL,
    updated_probability_yes REAL NOT NULL,
    delta REAL,
    trigger TEXT,
    reason TEXT NOT NULL,
    sources_json TEXT,
    analysis_id INTEGER,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id),
    FOREIGN KEY (analysis_id) REFERENCES analyses(id)
);
CREATE INDEX IF NOT EXISTS idx_forecast_updates_market ON forecast_updates(condition_id, created_at);

CREATE TABLE IF NOT EXISTS hidden_gem_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    analyst TEXT NOT NULL DEFAULT 'claude-desktop',
    executable_edge REAL NOT NULL DEFAULT 0,
    liquidity_score REAL NOT NULL DEFAULT 0.5,
    spread_score REAL NOT NULL DEFAULT 0.5,
    attention_gap_score REAL NOT NULL DEFAULT 0.5,
    evidence_asymmetry_score REAL NOT NULL DEFAULT 0.5,
    stale_price_score REAL NOT NULL DEFAULT 0.5,
    catalyst_score REAL NOT NULL DEFAULT 0.5,
    resolution_clarity_score REAL NOT NULL DEFAULT 0.5,
    total_score REAL NOT NULL DEFAULT 0,
    thesis TEXT NOT NULL,
    disconfirming_evidence TEXT,
    next_check_at TEXT,
    decision TEXT NOT NULL DEFAULT 'watchlist',
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_hidden_gem_market ON hidden_gem_reviews(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_hidden_gem_score ON hidden_gem_reviews(total_score DESC);

CREATE TABLE IF NOT EXISTS signal_quality_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    signal_id INTEGER,
    analysis_id INTEGER,
    created_at TEXT NOT NULL,
    pick_created_at TEXT,
    evaluator TEXT NOT NULL DEFAULT 'claude-desktop',
    original_side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stake_usd REAL NOT NULL,
    shares REAL NOT NULL,
    probability_yes REAL,
    confidence REAL,
    market_price_at_pick REAL,
    current_yes_price REAL,
    current_side_price REAL,
    current_snapshot_at TEXT,
    mark_to_market_value REAL,
    mark_to_market_pnl REAL,
    mark_to_market_roi REAL,
    price_delta_yes REAL,
    moved_toward_thesis INTEGER,
    repricing_speed_hours REAL,
    forecast_edge_at_entry REAL,
    thesis_quality_score REAL NOT NULL DEFAULT 0.5,
    entry_quality_score REAL NOT NULL DEFAULT 0.5,
    catalyst_quality_score REAL NOT NULL DEFAULT 0.5,
    resolution_quality_score REAL NOT NULL DEFAULT 0.5,
    timing_quality_score REAL NOT NULL DEFAULT 0.5,
    risk_quality_score REAL NOT NULL DEFAULT 0.5,
    total_score REAL NOT NULL DEFAULT 0,
    grade TEXT,
    verdict TEXT NOT NULL,
    lessons TEXT,
    sources_json TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id),
    FOREIGN KEY (signal_id) REFERENCES signals(id),
    FOREIGN KEY (analysis_id) REFERENCES analyses(id)
);
CREATE INDEX IF NOT EXISTS idx_signal_quality_market ON signal_quality_reviews(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_signal_quality_score ON signal_quality_reviews(total_score DESC);
CREATE INDEX IF NOT EXISTS idx_signal_quality_signal ON signal_quality_reviews(signal_id);

CREATE TABLE IF NOT EXISTS signal_archetype_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    signal_quality_review_id INTEGER,
    created_at TEXT NOT NULL,
    evaluator TEXT NOT NULL DEFAULT 'claude-desktop',
    primary_archetype TEXT NOT NULL,
    secondary_archetypes_json TEXT,
    countable_catalyst_score REAL NOT NULL DEFAULT 0,
    cheap_optionality_score REAL NOT NULL DEFAULT 0,
    resolution_wording_trap_score REAL NOT NULL DEFAULT 0,
    stale_price_score REAL NOT NULL DEFAULT 0,
    actor_incentive_mismatch_score REAL NOT NULL DEFAULT 0,
    crowd_narrative_error_score REAL NOT NULL DEFAULT 0,
    repricing_watch_score REAL NOT NULL DEFAULT 0,
    evidence TEXT NOT NULL,
    anti_pattern_risk TEXT,
    repeatable_lesson TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id),
    FOREIGN KEY (signal_quality_review_id) REFERENCES signal_quality_reviews(id)
);
CREATE INDEX IF NOT EXISTS idx_archetype_reviews_market ON signal_archetype_reviews(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_archetype_reviews_primary ON signal_archetype_reviews(primary_archetype);

CREATE TABLE IF NOT EXISTS signal_benchmark_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    expected_primary_archetype TEXT NOT NULL,
    expected_min_quality_score REAL NOT NULL DEFAULT 0,
    expected_min_mtm_roi REAL NOT NULL DEFAULT 0,
    expected_moved_toward INTEGER,
    expected_min_forecast_edge REAL,
    reference_side TEXT,
    reference_entry_price REAL,
    reference_probability_yes REAL,
    reference_confidence REAL,
    reference_spread REAL,
    reference_snapshot_age_min REAL,
    failure_if TEXT,
    notes TEXT,
    -- Extended fields (added later; migration adds them to old DBs):
    case_kind TEXT DEFAULT 'positive',           -- positive | negative (anti-case)
    expected_gate_decision TEXT DEFAULT 'fire',  -- fire | block_edge | block_spread | block_confidence | block_spread_adj
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_benchmark_cases_market ON signal_benchmark_cases(condition_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_cases_active ON signal_benchmark_cases(active);

CREATE TABLE IF NOT EXISTS moonshot_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    analyst TEXT NOT NULL DEFAULT 'claude-desktop',
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    payout_multiple REAL NOT NULL,
    implied_probability REAL NOT NULL,
    estimated_probability REAL,
    probability_edge REAL,
    catalyst_score REAL NOT NULL DEFAULT 0.5,
    mechanism_score REAL NOT NULL DEFAULT 0.5,
    evidence_score REAL NOT NULL DEFAULT 0.5,
    resolution_score REAL NOT NULL DEFAULT 0.5,
    liquidity_score REAL NOT NULL DEFAULT 0.5,
    spread_score REAL NOT NULL DEFAULT 0.5,
    narrative_heat_score REAL NOT NULL DEFAULT 0.5,
    anti_random_score REAL NOT NULL DEFAULT 0.5,
    total_score REAL NOT NULL DEFAULT 0,
    risk_tier TEXT NOT NULL,
    decision TEXT NOT NULL,
    thesis TEXT NOT NULL,
    kill_criteria TEXT NOT NULL,
    next_research_step TEXT,
    sources_json TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_moonshot_reviews_market ON moonshot_reviews(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_moonshot_reviews_score ON moonshot_reviews(total_score DESC);
CREATE INDEX IF NOT EXISTS idx_moonshot_reviews_decision ON moonshot_reviews(decision);

CREATE TABLE IF NOT EXISTS resolution_maps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    analyst TEXT NOT NULL DEFAULT 'claude-desktop',
    yes_criteria TEXT NOT NULL,
    no_criteria TEXT NOT NULL,
    primary_resolution_source TEXT,
    secondary_resolution_sources TEXT,
    deadline_text TEXT,
    ambiguity_cases TEXT,
    non_qualifying_events TEXT,
    required_artifact TEXT,
    resolution_risk_score REAL NOT NULL DEFAULT 0.5,
    wording_trap_score REAL NOT NULL DEFAULT 0.5,
    source_quality_score REAL NOT NULL DEFAULT 0.5,
    deadline_clarity_score REAL NOT NULL DEFAULT 0.5,
    completeness_score REAL NOT NULL DEFAULT 0,
    parser_warnings_json TEXT,
    parser_ambiguity_score REAL,
    parser_suggestion TEXT,
    summary TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_resolution_maps_market ON resolution_maps(condition_id, created_at);

CREATE TABLE IF NOT EXISTS pre_bet_checklists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    analyst TEXT NOT NULL DEFAULT 'claude-desktop',
    intended_side TEXT NOT NULL,
    intended_entry_price REAL,
    estimated_probability REAL NOT NULL,
    confidence REAL NOT NULL,
    edge REAL,
    has_resolution_map INTEGER NOT NULL DEFAULT 0,
    has_evidence_base INTEGER NOT NULL DEFAULT 0,
    has_actor_map INTEGER NOT NULL DEFAULT 0,
    has_causal_model INTEGER NOT NULL DEFAULT 0,
    has_scenario_tree INTEGER NOT NULL DEFAULT 0,
    has_premortem INTEGER NOT NULL DEFAULT 0,
    has_moonshot_review INTEGER NOT NULL DEFAULT 0,
    evidence_balance_ok INTEGER NOT NULL DEFAULT 0,
    spread_ok INTEGER NOT NULL DEFAULT 0,
    liquidity_ok INTEGER NOT NULL DEFAULT 0,
    sizing_ok INTEGER NOT NULL DEFAULT 0,
    resolution_risk_ok INTEGER NOT NULL DEFAULT 0,
    thesis TEXT NOT NULL,
    top_risks TEXT NOT NULL,
    disconfirming_evidence TEXT NOT NULL,
    checklist_score REAL NOT NULL DEFAULT 0,
    decision TEXT NOT NULL,
    next_action TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_pre_bet_market ON pre_bet_checklists(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pre_bet_decision ON pre_bet_checklists(decision);

CREATE TABLE IF NOT EXISTS outcome_learning_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    signal_id INTEGER,
    analysis_id INTEGER,
    created_at TEXT NOT NULL,
    analyst TEXT NOT NULL DEFAULT 'claude-desktop',
    outcome_side TEXT NOT NULL,
    predicted_side TEXT,
    entry_price REAL,
    probability_yes REAL,
    confidence REAL,
    realized_pnl REAL,
    brier_score REAL,
    market_brier_score REAL,
    outcome_summary TEXT NOT NULL,
    why_right_or_wrong TEXT NOT NULL,
    resolution_error INTEGER NOT NULL DEFAULT 0,
    probability_error INTEGER NOT NULL DEFAULT 0,
    evidence_error INTEGER NOT NULL DEFAULT 0,
    timing_error INTEGER NOT NULL DEFAULT 0,
    sizing_error INTEGER NOT NULL DEFAULT 0,
    luck_factor REAL NOT NULL DEFAULT 0.5,
    repeatable_lesson TEXT NOT NULL,
    rule_update TEXT,
    error_taxonomy_json TEXT,
    primary_error_type TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id),
    FOREIGN KEY (signal_id) REFERENCES signals(id),
    FOREIGN KEY (analysis_id) REFERENCES analyses(id)
);
CREATE INDEX IF NOT EXISTS idx_outcome_learning_market ON outcome_learning_reviews(condition_id, created_at);

CREATE TABLE IF NOT EXISTS actor_maps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    actor_type TEXT,
    role TEXT NOT NULL,
    incentives TEXT NOT NULL,
    constraints TEXT,
    likely_action TEXT,
    influence_score REAL NOT NULL DEFAULT 0.5,
    visibility_score REAL NOT NULL DEFAULT 0.5,
    notes TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_actor_maps_market ON actor_maps(condition_id, created_at);

CREATE TABLE IF NOT EXISTS causal_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'UNKNOWN',
    importance REAL NOT NULL DEFAULT 0.5,
    uncertainty REAL NOT NULL DEFAULT 0.5,
    observable_signal TEXT,
    current_state TEXT,
    next_check_at TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_causal_factors_market ON causal_factors(condition_id, created_at);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    anomaly_type TEXT NOT NULL,
    observation TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    implied_direction TEXT NOT NULL DEFAULT 'UNKNOWN',
    severity REAL NOT NULL DEFAULT 0.5,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'open',
    source_url TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_anomalies_market ON anomalies(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status);

CREATE TABLE IF NOT EXISTS scenario_trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    path TEXT NOT NULL,
    probability REAL NOT NULL,
    outcome_side TEXT NOT NULL DEFAULT 'UNKNOWN',
    key_assumptions TEXT,
    breakpoints TEXT,
    early_warning_signals TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_scenario_trees_market ON scenario_trees(condition_id, created_at);

CREATE TABLE IF NOT EXISTS premortems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    thesis TEXT NOT NULL,
    failure_mode TEXT NOT NULL,
    disconfirming_signal TEXT NOT NULL,
    probability_if_wrong REAL NOT NULL DEFAULT 0.5,
    mitigation TEXT,
    severity REAL NOT NULL DEFAULT 0.5,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_premortems_market ON premortems(condition_id, created_at);

CREATE TABLE IF NOT EXISTS daily_runs (
    run_date TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    markets_seen INTEGER DEFAULT 0,
    haiku_filtered INTEGER DEFAULT 0,
    sonnet_analyzed INTEGER DEFAULT 0,
    signals_emitted INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0
);

-- Stage 1: Portfolio & risk engine ------------------------------------------
-- positions: an INTENT to take a side at a price. Replaces the implicit
-- "signal == position" coupling that lived in signals.real_money*.
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    signal_id INTEGER,
    opened_at TEXT NOT NULL,
    intended_side TEXT NOT NULL,
    intended_entry_price REAL NOT NULL,
    side_entry_price REAL,
    yes_equivalent_entry REAL,
    price_model_version TEXT DEFAULT 'legacy',
    intended_stake_usd REAL NOT NULL,
    stake_source TEXT NOT NULL DEFAULT 'paper',  -- paper | real | hybrid
    status TEXT NOT NULL DEFAULT 'open',         -- open | filled | partially_filled | cancelled | resolved
    thesis_snapshot_text TEXT,
    primary_archetype TEXT,
    edge_archetype TEXT,
    signal_generation_epoch TEXT DEFAULT 'legacy',
    confidence_source TEXT DEFAULT 'automated_score',
    approval_strength TEXT,
    post_entry_review_required INTEGER DEFAULT 0,
    post_entry_review_reason TEXT,
    end_date TEXT,
    closed_at TEXT,
    closed_reason TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id),
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);
CREATE INDEX IF NOT EXISTS idx_positions_market ON positions(condition_id);
CREATE INDEX IF NOT EXISTS idx_positions_signal ON positions(signal_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);

-- fills: an actual entry/exit transaction. One position can accumulate
-- multiple fills (partial entries, scaling out, etc.).
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    filled_at TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    shares REAL NOT NULL,
    stake_usd REAL NOT NULL,
    slippage_vs_intent REAL,
    venue TEXT NOT NULL DEFAULT 'paper',  -- paper | polymarket
    tx_hash TEXT,
    FOREIGN KEY (position_id) REFERENCES positions(id)
);
CREATE INDEX IF NOT EXISTS idx_fills_position ON fills(position_id);
CREATE INDEX IF NOT EXISTS idx_fills_venue ON fills(venue);

-- pnl_events: granular P&L log. Marks, partial exits, resolutions.
CREATE TABLE IF NOT EXISTS pnl_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    event_at TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- mark | partial_exit | resolution
    yes_price REAL,
    side_price REAL,
    value_usd REAL,
    delta_pnl_usd REAL,
    note TEXT,
    FOREIGN KEY (position_id) REFERENCES positions(id)
);
CREATE INDEX IF NOT EXISTS idx_pnl_events_position ON pnl_events(position_id, event_at);
CREATE INDEX IF NOT EXISTS idx_pnl_events_type ON pnl_events(event_type);

-- Source Registry --------------------------------------------------------
-- Catalogue of sources used in record_evidence. Lets us auto-resolve a
-- source from a URL, track reliability/latency/bias once, and accumulate
-- per-source track records as resolutions come in.
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    url_pattern TEXT,                       -- "reuters.com" / "x.com/@user"
    source_type TEXT NOT NULL DEFAULT 'unknown',  -- official | news_agency | newspaper | think_tank | regional | political | social | blog | wiki | gov | tech | other
    reliability_score REAL NOT NULL DEFAULT 0.5,
    latency_score REAL NOT NULL DEFAULT 0.5,     -- 0 = slow / academic, 1 = real-time
    bias TEXT NOT NULL DEFAULT 'unknown',         -- left | right | center | unknown | mixed
    notes TEXT,
    created_at TEXT NOT NULL,
    times_cited INTEGER NOT NULL DEFAULT 0,
    times_correct INTEGER NOT NULL DEFAULT 0,
    times_wrong INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sources_name ON sources(name);
CREATE INDEX IF NOT EXISTS idx_sources_url ON sources(url_pattern);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
CREATE TABLE IF NOT EXISTS workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_name TEXT NOT NULL,
    workflow_level TEXT NOT NULL,
    agent_name TEXT NOT NULL DEFAULT 'unknown',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    input_json TEXT,
    output_json TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_name ON workflow_runs(workflow_name, started_at);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status, started_at);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_run_id INTEGER NOT NULL,
    condition_id TEXT,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL,
    allowed_writes TEXT,
    writes_count INTEGER NOT NULL DEFAULT 0,
    blocker TEXT,
    output_ref TEXT,
    output_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_run ON workflow_steps(workflow_run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_condition ON workflow_steps(condition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_status ON workflow_steps(status, created_at);

CREATE TABLE IF NOT EXISTS triage_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    run_id INTEGER,
    captured_at TEXT NOT NULL,
    discoverability_score REAL NOT NULL,
    rank INTEGER,
    metaculus_boost REAL,
    ofi_boost REAL,
    ofi REAL,
    yes_price REAL,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);
CREATE INDEX IF NOT EXISTS idx_triage_scores_condition ON triage_scores(condition_id, captured_at);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    with connect() as c:
        c.executescript(SCHEMA)
        # Lightweight migration: add vertical column to old DBs that predate it
        cols = {r["name"] for r in c.execute("PRAGMA table_info(markets)").fetchall()}
        if "vertical" not in cols:
            c.execute("ALTER TABLE markets ADD COLUMN vertical TEXT DEFAULT 'unknown'")
            c.execute("UPDATE markets SET vertical='geopolitics' WHERE vertical IS NULL OR vertical='unknown'")
        # Migrate signals table to add real_money columns
        sig_cols = {r["name"] for r in c.execute("PRAGMA table_info(signals)").fetchall()}
        new_cols = [
            ("real_money", "INTEGER DEFAULT 0"),
            ("real_entry_price", "REAL"),
            ("real_bet_usd", "REAL"),
            ("real_shares", "REAL"),
            ("real_filled_at", "TEXT"),
            ("real_max_payout", "REAL"),
            ("real_pnl_actual", "REAL"),
            ("manual_trade", "INTEGER DEFAULT 0"),
            ("retrospective", "INTEGER DEFAULT 0"),
            ("operator_decision", "TEXT"),
        ]
        for col, spec in new_cols:
            if col not in sig_cols:
                c.execute(f"ALTER TABLE signals ADD COLUMN {col} {spec}")
        snap_cols = {r["name"] for r in c.execute("PRAGMA table_info(snapshots)").fetchall()}
        snap_new_cols = [
            ("no_price", "REAL"),
            ("best_bid", "REAL"),
            ("best_ask", "REAL"),
            ("spread", "REAL"),
            ("yes_entry_price", "REAL"),
            ("no_entry_price", "REAL"),
            ("source", "TEXT DEFAULT 'fetch'"),  # Stage 2: fetch | backfill | monitor
        ]
        for col, spec in snap_new_cols:
            if col not in snap_cols:
                c.execute(f"ALTER TABLE snapshots ADD COLUMN {col} {spec}")
        c.execute("""
            UPDATE snapshots
            SET no_price = COALESCE(no_price, 1.0 - yes_price),
                yes_entry_price = COALESCE(yes_entry_price, yes_price),
                no_entry_price = COALESCE(no_entry_price, 1.0 - yes_price)
            WHERE no_price IS NULL
               OR yes_entry_price IS NULL
               OR no_entry_price IS NULL
        """)
        signal_cols = {r["name"] for r in c.execute("PRAGMA table_info(signals)").fetchall()}
        signal_new_cols = [
            ("yes_equivalent_entry", "REAL"),
            ("side_entry_price", "REAL"),
            ("price_model_version", "TEXT DEFAULT 'legacy'"),
            ("gate_status", "TEXT DEFAULT 'unknown'"),
            ("gate_audit_note", "TEXT"),
            ("signal_generation_epoch", "TEXT DEFAULT 'legacy'"),
            ("edge_archetype", "TEXT"),
            ("confidence_source", "TEXT DEFAULT 'automated_score'"),
            ("approval_strength", "TEXT"),
            ("post_entry_review_required", "INTEGER DEFAULT 0"),
            ("post_entry_review_reason", "TEXT"),
        ]
        for col, spec in signal_new_cols:
            if col not in signal_cols:
                c.execute(f"ALTER TABLE signals ADD COLUMN {col} {spec}")
        c.execute("""
            UPDATE signals
            SET yes_equivalent_entry = COALESCE(yes_equivalent_entry, yes_price_at_signal),
                side_entry_price = COALESCE(
                    side_entry_price,
                    CASE WHEN side = 'NO' THEN 1.0 - yes_price_at_signal ELSE yes_price_at_signal END
                ),
                price_model_version = COALESCE(price_model_version, 'legacy')
            WHERE yes_equivalent_entry IS NULL
               OR side_entry_price IS NULL
               OR price_model_version IS NULL
        """)
        c.execute("""
            UPDATE signals
            SET signal_generation_epoch = CASE
                    WHEN manual_trade = 1 THEN 'manual_real'
                    WHEN gate_status = 'gated' THEN 'gated_v1'
                    WHEN gate_status = 'manual' THEN 'operator_approved'
                    ELSE 'legacy'
                END,
                confidence_source = CASE
                    WHEN manual_trade = 1 THEN 'manual_human'
                    WHEN gate_status = 'gated' THEN 'forager_packet'
                    WHEN gate_status = 'manual' THEN 'operator_override'
                    ELSE COALESCE(confidence_source, 'automated_score')
                END,
                approval_strength = COALESCE(
                    approval_strength,
                    CASE
                        WHEN ABS(edge) >= 0.12 AND confidence >= 0.65 THEN 'A'
                        WHEN ABS(edge) >= 0.08 AND confidence >= 0.55 THEN 'B'
                        WHEN ABS(edge) >= 0.04 THEN 'C'
                        WHEN ABS(edge) > 0 THEN 'D'
                        ELSE 'F'
                    END
                )
            WHERE signal_generation_epoch IS NULL
               OR signal_generation_epoch = 'legacy'
               OR confidence_source IS NULL
               OR approval_strength IS NULL
        """)

        position_cols = {r["name"] for r in c.execute("PRAGMA table_info(positions)").fetchall()}
        position_new_cols = [
            ("side_entry_price", "REAL"),
            ("yes_equivalent_entry", "REAL"),
            ("price_model_version", "TEXT DEFAULT 'legacy'"),
            ("edge_archetype", "TEXT"),
            ("signal_generation_epoch", "TEXT DEFAULT 'legacy'"),
            ("confidence_source", "TEXT DEFAULT 'automated_score'"),
            ("approval_strength", "TEXT"),
            ("post_entry_review_required", "INTEGER DEFAULT 0"),
            ("post_entry_review_reason", "TEXT"),
        ]
        for col, spec in position_new_cols:
            if col not in position_cols:
                c.execute(f"ALTER TABLE positions ADD COLUMN {col} {spec}")
        c.execute("""
            UPDATE positions
            SET yes_equivalent_entry = COALESCE(
                    yes_equivalent_entry,
                    intended_entry_price
                ),
                side_entry_price = COALESCE(
                    side_entry_price,
                    CASE WHEN intended_side = 'NO' THEN 1.0 - intended_entry_price ELSE intended_entry_price END
                ),
                price_model_version = COALESCE(price_model_version, 'legacy')
            WHERE yes_equivalent_entry IS NULL
               OR side_entry_price IS NULL
               OR price_model_version IS NULL
        """)
        c.execute("""
            UPDATE positions
            SET signal_generation_epoch = COALESCE(
                    (SELECT s.signal_generation_epoch FROM signals s WHERE s.id = positions.signal_id),
                    signal_generation_epoch,
                    'legacy'
                ),
                confidence_source = COALESCE(
                    (SELECT s.confidence_source FROM signals s WHERE s.id = positions.signal_id),
                    confidence_source,
                    'automated_score'
                ),
                approval_strength = COALESCE(
                    approval_strength,
                    (SELECT s.approval_strength FROM signals s WHERE s.id = positions.signal_id)
                ),
                edge_archetype = COALESCE(edge_archetype, primary_archetype)
            WHERE edge_archetype IS NULL
               OR signal_generation_epoch IS NULL
               OR signal_generation_epoch = 'legacy'
               OR confidence_source IS NULL
               OR approval_strength IS NULL
        """)
        c.execute("""
            UPDATE positions
            SET yes_equivalent_entry = intended_entry_price,
                side_entry_price = 1.0 - intended_entry_price
            WHERE intended_side = 'NO'
              AND price_model_version = 'legacy'
              AND intended_entry_price > 0.5
        """)
        c.execute("""
            UPDATE signals
            SET gate_status = CASE
                    WHEN manual_trade = 1 THEN 'manual'
                    WHEN EXISTS (
                        SELECT 1 FROM pre_bet_checklists pc
                        WHERE pc.condition_id = signals.condition_id
                          AND pc.created_at <= signals.created_at
                          AND pc.decision = 'approved_for_signal'
                    ) THEN 'gated'
                    ELSE 'legacy_gate_violation'
                END,
                gate_audit_note = CASE
                    WHEN manual_trade = 1 THEN 'manual/operator trade, not formal gate path'
                    WHEN EXISTS (
                        SELECT 1 FROM pre_bet_checklists pc
                        WHERE pc.condition_id = signals.condition_id
                          AND pc.created_at <= signals.created_at
                          AND pc.decision = 'approved_for_signal'
                    ) THEN 'approved pre-bet checklist found before signal'
                    ELSE 'legacy signal without approved pre-bet checklist before signal time'
                END
            WHERE gate_status IS NULL OR gate_status = 'unknown'
        """)
        # Stage 1: backfill positions/fills/pnl_events from legacy signals rows
        _backfill_positions_from_signals(c)
        # Source registry seed (idempotent — upserts by name)
        seed_default_sources(c)
        # Benchmark suite migration: extended columns on signal_benchmark_cases
        bench_cols = {r["name"] for r in c.execute("PRAGMA table_info(signal_benchmark_cases)").fetchall()}
        if "case_kind" not in bench_cols:
            c.execute("ALTER TABLE signal_benchmark_cases ADD COLUMN case_kind TEXT DEFAULT 'positive'")
        if "expected_gate_decision" not in bench_cols:
            c.execute("ALTER TABLE signal_benchmark_cases ADD COLUMN expected_gate_decision TEXT DEFAULT 'fire'")
        if "reference_spread" not in bench_cols:
            c.execute("ALTER TABLE signal_benchmark_cases ADD COLUMN reference_spread REAL")
        if "reference_snapshot_age_min" not in bench_cols:
            c.execute("ALTER TABLE signal_benchmark_cases ADD COLUMN reference_snapshot_age_min REAL")

        resolution_cols = {r["name"] for r in c.execute("PRAGMA table_info(resolution_maps)").fetchall()}
        if "parser_warnings_json" not in resolution_cols:
            c.execute("ALTER TABLE resolution_maps ADD COLUMN parser_warnings_json TEXT")
        if "parser_ambiguity_score" not in resolution_cols:
            c.execute("ALTER TABLE resolution_maps ADD COLUMN parser_ambiguity_score REAL")
        if "parser_suggestion" not in resolution_cols:
            c.execute("ALTER TABLE resolution_maps ADD COLUMN parser_suggestion TEXT")
        # Checklist v2: split single checklist_score into four sub-scores
        checklist_cols = {r["name"] for r in c.execute("PRAGMA table_info(pre_bet_checklists)").fetchall()}
        if "dossier_completeness_score" not in checklist_cols:
            c.execute("ALTER TABLE pre_bet_checklists ADD COLUMN dossier_completeness_score REAL DEFAULT 0")
        if "forecast_confidence_score" not in checklist_cols:
            c.execute("ALTER TABLE pre_bet_checklists ADD COLUMN forecast_confidence_score REAL DEFAULT 0")
        if "signal_readiness_score" not in checklist_cols:
            c.execute("ALTER TABLE pre_bet_checklists ADD COLUMN signal_readiness_score REAL DEFAULT 0")
        if "disconfirming_checked" not in checklist_cols:
            c.execute("ALTER TABLE pre_bet_checklists ADD COLUMN disconfirming_checked INTEGER DEFAULT 0")
        if "contradictions_resolved" not in checklist_cols:
            c.execute("ALTER TABLE pre_bet_checklists ADD COLUMN contradictions_resolved INTEGER DEFAULT 0")
        learning_cols = {r["name"] for r in c.execute("PRAGMA table_info(outcome_learning_reviews)").fetchall()}
        if "error_taxonomy_json" not in learning_cols:
            c.execute("ALTER TABLE outcome_learning_reviews ADD COLUMN error_taxonomy_json TEXT")
        if "primary_error_type" not in learning_cols:
            c.execute("ALTER TABLE outcome_learning_reviews ADD COLUMN primary_error_type TEXT")
        c.commit()


def _backfill_positions_from_signals(c: sqlite3.Connection) -> None:
    """One-shot migration: every signals row that doesn't already have a
    position gets a position + a paper fill, plus a real fill when the legacy
    real_money columns are populated, plus a resolution pnl_event when the
    signal is already resolved. Idempotent - skips signals already mapped.
    """
    existing = {r["signal_id"] for r in c.execute(
        "SELECT signal_id FROM positions WHERE signal_id IS NOT NULL"
    ).fetchall()}
    sigs = c.execute("""
        SELECT s.id, s.condition_id, s.created_at, s.side,
               s.yes_price_at_signal, s.yes_equivalent_entry, s.side_entry_price,
               s.bet_amount, s.reasoning,
               s.resolved, s.realized_pnl,
               s.real_money, s.real_entry_price, s.real_bet_usd,
               s.real_shares, s.real_filled_at, s.real_pnl_actual,
               m.end_date
        FROM signals s JOIN markets m ON m.condition_id = s.condition_id
    """).fetchall()
    for s in sigs:
        if s["id"] in existing:
            continue
        stake_source = "hybrid" if s["real_money"] else "paper"
        status = "resolved" if s["resolved"] else "open"
        closed_at = s["real_filled_at"] if s["resolved"] else None
        cur = c.execute("""
            INSERT INTO positions (
                condition_id, signal_id, opened_at, intended_side,
                intended_entry_price, side_entry_price, yes_equivalent_entry,
                price_model_version, intended_stake_usd, stake_source,
                status, thesis_snapshot_text, primary_archetype, end_date,
                closed_at, closed_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s["condition_id"], s["id"], s["created_at"], s["side"],
            s["side_entry_price"], s["side_entry_price"], s["yes_equivalent_entry"],
            "v2_explicit", s["bet_amount"], stake_source,
            status, s["reasoning"], None, s["end_date"],
            closed_at, "resolution" if s["resolved"] else None,
        ))
        position_id = cur.lastrowid
        # Paper fill always exists
        paper_shares = s["bet_amount"] / s["side_entry_price"] if s["side_entry_price"] else 0.0
        c.execute("""
            INSERT INTO fills (position_id, filled_at, side, price, shares,
                               stake_usd, slippage_vs_intent, venue)
            VALUES (?, ?, ?, ?, ?, ?, 0.0, 'paper')
        """, (position_id, s["created_at"], s["side"],
              s["side_entry_price"], paper_shares, s["bet_amount"]))
        # Real fill (if logged)
        if s["real_money"]:
            slippage = None
            if s["real_entry_price"] is not None and s["side_entry_price"]:
                slippage = float(s["real_entry_price"]) - float(s["side_entry_price"])
            c.execute("""
                INSERT INTO fills (position_id, filled_at, side, price, shares,
                                   stake_usd, slippage_vs_intent, venue)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'polymarket')
            """, (position_id, s["real_filled_at"] or s["created_at"],
                  s["side"], s["real_entry_price"] or s["side_entry_price"],
                  s["real_shares"] or 0.0, s["real_bet_usd"] or 0.0, slippage))
        # Resolution event (if signal already resolved)
        if s["resolved"] and s["realized_pnl"] is not None:
            c.execute("""
                INSERT INTO pnl_events (position_id, event_at, event_type,
                                        value_usd, delta_pnl_usd, note)
                VALUES (?, ?, 'resolution', ?, ?, 'migrated_from_signals')
            """, (position_id, closed_at or s["created_at"],
                  None, float(s["realized_pnl"])))


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()




def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def start_workflow_run(
    conn: sqlite3.Connection,
    *,
    workflow_name: str,
    workflow_level: str,
    agent_name: str = "codex",
    input_json: Any = None,
    status: str = "running",
    notes: str | None = None,
) -> int:
    cur = conn.execute("""
        INSERT INTO workflow_runs (
            workflow_name, workflow_level, agent_name, started_at,
            status, input_json, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        workflow_name,
        workflow_level,
        agent_name or "unknown",
        utcnow_iso(),
        status,
        _json_or_none(input_json),
        notes,
    ))
    return cur.lastrowid or 0


def add_workflow_step(
    conn: sqlite3.Connection,
    *,
    workflow_run_id: int,
    step_name: str,
    status: str = "completed",
    condition_id: str | None = None,
    allowed_writes: Any = None,
    writes_count: int = 0,
    blocker: str | None = None,
    output_ref: str | None = None,
    output_json: Any = None,
) -> int:
    cur = conn.execute("""
        INSERT INTO workflow_steps (
            workflow_run_id, condition_id, step_name, status, allowed_writes,
            writes_count, blocker, output_ref, output_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        workflow_run_id,
        condition_id or None,
        step_name,
        status,
        _json_or_none(allowed_writes),
        int(writes_count or 0),
        blocker or None,
        output_ref or None,
        _json_or_none(output_json),
        utcnow_iso(),
    ))
    return cur.lastrowid or 0


def finish_workflow_run(
    conn: sqlite3.Connection,
    workflow_run_id: int,
    *,
    status: str = "completed",
    output_json: Any = None,
) -> None:
    conn.execute("""
        UPDATE workflow_runs
        SET completed_at = ?, status = ?, output_json = ?
        WHERE id = ?
    """, (utcnow_iso(), status, _json_or_none(output_json), workflow_run_id))


def list_workflow_runs(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    status: str | None = None,
    workflow_name: str | None = None,
) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if workflow_name:
        where.append("workflow_name = ?")
        params.append(workflow_name)
    sql = "SELECT * FROM workflow_runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def workflow_run_detail(conn: sqlite3.Connection, workflow_run_id: int) -> dict[str, Any] | None:
    run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (workflow_run_id,)).fetchone()
    if run is None:
        return None
    steps = conn.execute("""
        SELECT * FROM workflow_steps
        WHERE workflow_run_id = ?
        ORDER BY created_at, id
    """, (workflow_run_id,)).fetchall()
    return {"run": dict(run), "steps": [dict(s) for s in steps]}



def upsert_market(conn: sqlite3.Connection, *, condition_id: str, question: str,
                  slug: str | None, end_date: str | None,
                  vertical: str = "unknown") -> None:
    now = utcnow_iso()
    conn.execute("""
        INSERT INTO markets (condition_id, question, slug, end_date, first_seen_at, last_seen_at, vertical)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(condition_id) DO UPDATE SET
            question = excluded.question,
            slug = excluded.slug,
            end_date = excluded.end_date,
            last_seen_at = excluded.last_seen_at,
            vertical = CASE WHEN excluded.vertical != 'unknown' THEN excluded.vertical ELSE markets.vertical END
    """, (condition_id, question, slug, end_date, now, now, vertical))


def set_market_tags(conn: sqlite3.Connection, *, condition_id: str,
                    tags: list[str] | tuple[str, ...] | set[str],
                    source: str = "auto") -> None:
    clean_tags = sorted({str(t).strip() for t in tags if str(t).strip()})
    conn.execute(
        "DELETE FROM market_tags WHERE condition_id = ? AND source = ?",
        (condition_id, source),
    )
    for tag in clean_tags:
        conn.execute("""
            INSERT INTO market_tags (condition_id, tag, source, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(condition_id, tag) DO UPDATE SET
                source = excluded.source,
                created_at = excluded.created_at
        """, (condition_id, tag, source, utcnow_iso()))


def get_market_tags(conn: sqlite3.Connection, condition_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT tag FROM market_tags WHERE condition_id = ? ORDER BY tag",
        (condition_id,),
    ).fetchall()
    return [r["tag"] for r in rows]


def add_snapshot(conn: sqlite3.Connection, *, condition_id: str, yes_price: float,
                 volume: float | None, liquidity: float | None,
                 no_price: float | None = None,
                 best_bid: float | None = None,
                 best_ask: float | None = None,
                 spread: float | None = None,
                 yes_entry_price: float | None = None,
                 no_entry_price: float | None = None,
                 source: str = "fetch") -> None:
    no_price = no_price if no_price is not None else 1.0 - yes_price
    yes_entry_price = yes_entry_price if yes_entry_price is not None else yes_price
    no_entry_price = no_entry_price if no_entry_price is not None else no_price
    conn.execute("""
        INSERT INTO snapshots (
            condition_id, captured_at, yes_price, no_price, best_bid, best_ask,
            spread, yes_entry_price, no_entry_price, volume, liquidity, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        condition_id, utcnow_iso(), yes_price, no_price, best_bid, best_ask,
        spread, yes_entry_price, no_entry_price, volume, liquidity, source,
    ))


def add_signal(conn: sqlite3.Connection, **kwargs: Any) -> int:
    from lib.ledger_meta import (
        approval_strength as _approval_strength,
        confidence_source as _confidence_source,
        edge_archetype_from_primary,
        signal_generation_epoch as _signal_generation_epoch,
    )

    operator_approved = bool(kwargs.pop("operator_approved", False))
    primary_archetype = kwargs.pop("primary_archetype", None)
    kwargs.setdefault("signal_generation_epoch", _signal_generation_epoch(
        gate_status=kwargs.get("gate_status"),
        manual_trade=bool(kwargs.get("manual_trade")),
        operator_decision=kwargs.get("operator_decision"),
    ))
    kwargs.setdefault("edge_archetype", edge_archetype_from_primary(primary_archetype, kwargs.get("reasoning")))
    kwargs.setdefault("confidence_source", _confidence_source(
        manual_trade=bool(kwargs.get("manual_trade")),
        operator_approved=operator_approved,
        model=kwargs.get("model"),
    ))
    kwargs.setdefault("approval_strength", _approval_strength(
        edge=kwargs.get("edge"),
        confidence=kwargs.get("confidence"),
        operator_approved=operator_approved,
    ))
    cols = ["condition_id", "created_at", "model", "yes_price_at_signal",
            "yes_equivalent_entry", "side_entry_price",
            "claude_prob", "confidence", "side", "edge", "bet_amount",
            "reasoning", "sources_json", "tokens_in", "tokens_out",
            "cache_read_tokens", "cost_usd", "price_model_version",
            "gate_status", "gate_audit_note",
            "signal_generation_epoch", "edge_archetype", "confidence_source",
            "approval_strength", "post_entry_review_required", "post_entry_review_reason"]
    if kwargs.get("yes_equivalent_entry") is None:
        kwargs["yes_equivalent_entry"] = kwargs.get("yes_price_at_signal")
    if kwargs.get("side_entry_price") is None:
        side = str(kwargs.get("side") or "").upper()
        yes_equiv = kwargs.get("yes_equivalent_entry")
        kwargs["side_entry_price"] = (1.0 - float(yes_equiv)) if side == "NO" and yes_equiv is not None else yes_equiv
    kwargs.setdefault("price_model_version", "v2_explicit")
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO signals ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_analysis(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "run_date", "condition_id", "created_at", "analyst", "model",
        "yes_price_at_analysis", "probability_yes", "confidence", "edge",
        "decision", "no_signal_reason", "signal_id", "reasoning",
        "sources_json", "notes",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO analyses ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_evidence(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "source_url", "source_name",
        "published_at", "claim", "stance", "strength", "reliability",
        "freshness", "notes",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO evidence ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_forecast_update(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "previous_probability_yes",
        "updated_probability_yes", "delta", "trigger", "reason",
        "sources_json", "analysis_id",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO forecast_updates ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_hidden_gem_review(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "analyst", "executable_edge",
        "liquidity_score", "spread_score", "attention_gap_score",
        "evidence_asymmetry_score", "stale_price_score", "catalyst_score",
        "resolution_clarity_score", "total_score", "thesis",
        "disconfirming_evidence", "next_check_at", "decision",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO hidden_gem_reviews ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_signal_quality_review(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "signal_id", "analysis_id", "created_at", "pick_created_at",
        "evaluator", "original_side", "entry_price", "stake_usd", "shares",
        "probability_yes", "confidence", "market_price_at_pick", "current_yes_price",
        "current_side_price", "current_snapshot_at", "mark_to_market_value",
        "mark_to_market_pnl", "mark_to_market_roi", "price_delta_yes",
        "moved_toward_thesis", "repricing_speed_hours", "forecast_edge_at_entry",
        "thesis_quality_score", "entry_quality_score", "catalyst_quality_score",
        "resolution_quality_score", "timing_quality_score", "risk_quality_score",
        "total_score", "grade", "verdict", "lessons", "sources_json",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO signal_quality_reviews ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_signal_archetype_review(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "signal_quality_review_id", "created_at", "evaluator",
        "primary_archetype", "secondary_archetypes_json", "countable_catalyst_score",
        "cheap_optionality_score", "resolution_wording_trap_score", "stale_price_score",
        "actor_incentive_mismatch_score", "crowd_narrative_error_score",
        "repricing_watch_score", "evidence", "anti_pattern_risk", "repeatable_lesson",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO signal_archetype_reviews ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_signal_benchmark_case(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "name", "condition_id", "created_at", "active", "expected_primary_archetype",
        "expected_min_quality_score", "expected_min_mtm_roi", "expected_moved_toward",
        "expected_min_forecast_edge", "reference_side", "reference_entry_price",
        "reference_probability_yes", "reference_confidence", "reference_spread",
        "reference_snapshot_age_min", "failure_if", "notes",
        "case_kind", "expected_gate_decision",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO signal_benchmark_cases ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_moonshot_review(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "analyst", "side", "entry_price",
        "payout_multiple", "implied_probability", "estimated_probability",
        "probability_edge", "catalyst_score", "mechanism_score",
        "evidence_score", "resolution_score", "liquidity_score",
        "spread_score", "narrative_heat_score", "anti_random_score",
        "total_score", "risk_tier", "decision", "thesis", "kill_criteria",
        "next_research_step", "sources_json",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO moonshot_reviews ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_resolution_map(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "analyst", "yes_criteria", "no_criteria",
        "primary_resolution_source", "secondary_resolution_sources", "deadline_text",
        "ambiguity_cases", "non_qualifying_events", "required_artifact",
        "resolution_risk_score", "wording_trap_score", "source_quality_score",
        "deadline_clarity_score", "completeness_score", "parser_warnings_json",
        "parser_ambiguity_score", "parser_suggestion", "summary",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO resolution_maps ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_pre_bet_checklist(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "analyst", "intended_side",
        "intended_entry_price", "estimated_probability", "confidence", "edge",
        "has_resolution_map", "has_evidence_base", "has_actor_map",
        "has_causal_model", "has_scenario_tree", "has_premortem",
        "has_moonshot_review", "evidence_balance_ok", "spread_ok",
        "liquidity_ok", "sizing_ok", "resolution_risk_ok", "thesis",
        "top_risks", "disconfirming_evidence", "checklist_score",
        "dossier_completeness_score", "forecast_confidence_score",
        "signal_readiness_score", "disconfirming_checked", "contradictions_resolved",
        "decision", "next_action",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO pre_bet_checklists ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_outcome_learning_review(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "signal_id", "analysis_id", "created_at", "analyst",
        "outcome_side", "predicted_side", "entry_price", "probability_yes",
        "confidence", "realized_pnl", "brier_score", "market_brier_score",
        "outcome_summary", "why_right_or_wrong", "resolution_error",
        "probability_error", "evidence_error", "timing_error", "sizing_error",
        "luck_factor", "repeatable_lesson", "rule_update",
        "error_taxonomy_json", "primary_error_type",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO outcome_learning_reviews ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_actor_map(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "actor_name", "actor_type", "role",
        "incentives", "constraints", "likely_action", "influence_score",
        "visibility_score", "notes",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO actor_maps ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_causal_factor(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "factor_name", "mechanism",
        "direction", "importance", "uncertainty", "observable_signal",
        "current_state", "next_check_at",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO causal_factors ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_anomaly(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "anomaly_type", "observation",
        "why_it_matters", "implied_direction", "severity", "confidence",
        "status", "source_url",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO anomalies ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_scenario(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "scenario_name", "path",
        "probability", "outcome_side", "key_assumptions", "breakpoints",
        "early_warning_signals",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO scenario_trees ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_premortem(conn: sqlite3.Connection, **kwargs: Any) -> int:
    cols = [
        "condition_id", "created_at", "thesis", "failure_mode",
        "disconfirming_signal", "probability_if_wrong", "mitigation",
        "severity",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "created_at" in kwargs and kwargs["created_at"] is None:
        vals[cols.index("created_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO premortems ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def start_run(conn: sqlite3.Connection, run_date: str) -> None:
    conn.execute("""
        INSERT INTO daily_runs (run_date, started_at) VALUES (?, ?)
        ON CONFLICT(run_date) DO UPDATE SET started_at = excluded.started_at
    """, (run_date, utcnow_iso()))


def finish_run(conn: sqlite3.Connection, run_date: str, **stats: Any) -> None:
    sets = ", ".join(f"{k} = ?" for k in stats) + ", finished_at = ?"
    params = list(stats.values()) + [utcnow_iso(), run_date]
    conn.execute(f"UPDATE daily_runs SET {sets} WHERE run_date = ?", params)


# --- Stage 1: positions / fills / pnl_events helpers --------------------------

def add_position(conn: sqlite3.Connection, **kwargs: Any) -> int:
    from lib.ledger_meta import edge_archetype_from_primary

    if kwargs.get("side_entry_price") is None:
        kwargs["side_entry_price"] = kwargs.get("intended_entry_price")
    if kwargs.get("yes_equivalent_entry") is None:
        side = str(kwargs.get("intended_side") or "").upper()
        side_entry = kwargs.get("side_entry_price")
        kwargs["yes_equivalent_entry"] = (1.0 - float(side_entry)) if side == "NO" and side_entry is not None else side_entry
    kwargs.setdefault("price_model_version", "v2_explicit")
    kwargs.setdefault("edge_archetype", edge_archetype_from_primary(
        kwargs.get("primary_archetype"),
        kwargs.get("thesis_snapshot_text"),
    ))
    cols = [
        "condition_id", "signal_id", "opened_at", "intended_side",
        "intended_entry_price", "side_entry_price", "yes_equivalent_entry",
        "price_model_version", "intended_stake_usd", "stake_source",
        "status", "thesis_snapshot_text", "primary_archetype", "edge_archetype",
        "signal_generation_epoch", "confidence_source", "approval_strength",
        "post_entry_review_required", "post_entry_review_reason", "end_date",
    ]
    vals = [kwargs.get(c) for c in cols]
    if "opened_at" in kwargs and kwargs["opened_at"] is None:
        vals[cols.index("opened_at")] = utcnow_iso()
    cur = conn.execute(
        f"INSERT INTO positions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    return cur.lastrowid or 0


def add_fill(conn: sqlite3.Connection, *, position_id: int, side: str,
             price: float, shares: float, stake_usd: float,
             venue: str = "paper", slippage_vs_intent: float | None = None,
             tx_hash: str | None = None, filled_at: str | None = None) -> int:
    cur = conn.execute("""
        INSERT INTO fills (position_id, filled_at, side, price, shares,
                           stake_usd, slippage_vs_intent, venue, tx_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (position_id, filled_at or utcnow_iso(), side, price, shares,
          stake_usd, slippage_vs_intent, venue, tx_hash))
    return cur.lastrowid or 0


def add_pnl_event(conn: sqlite3.Connection, *, position_id: int,
                  event_type: str, value_usd: float | None = None,
                  delta_pnl_usd: float | None = None,
                  yes_price: float | None = None,
                  side_price: float | None = None,
                  note: str | None = None,
                  event_at: str | None = None) -> int:
    cur = conn.execute("""
        INSERT INTO pnl_events (position_id, event_at, event_type, yes_price,
                                side_price, value_usd, delta_pnl_usd, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (position_id, event_at or utcnow_iso(), event_type, yes_price,
          side_price, value_usd, delta_pnl_usd, note))
    return cur.lastrowid or 0


def add_snapshot_raw(conn: sqlite3.Connection, *, condition_id: str,
                     captured_at: str, yes_price: float,
                     source: str = "backfill") -> bool:
    """Insert a snapshot row for backfill or monitor sources. Idempotent: skips
    when a snapshot for the same condition_id already exists within 12 hours of
    captured_at (avoids duplicate rows when re-running backfills). Returns True
    if inserted."""
    existing = conn.execute("""
        SELECT 1 FROM snapshots
        WHERE condition_id = ?
          AND ABS((julianday(captured_at) - julianday(?)) * 24.0) < 12.0
        LIMIT 1
    """, (condition_id, captured_at)).fetchone()
    if existing:
        return False
    conn.execute("""
        INSERT INTO snapshots (
            condition_id, captured_at, yes_price, no_price,
            yes_entry_price, no_entry_price, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (condition_id, captured_at, yes_price,
          1.0 - yes_price, yes_price, 1.0 - yes_price, source))
    return True


# --- Source Registry helpers -------------------------------------------------

def upsert_source(conn: sqlite3.Connection, *, name: str,
                  url_pattern: str | None = None,
                  source_type: str = "unknown",
                  reliability_score: float = 0.5,
                  latency_score: float = 0.5,
                  bias: str = "unknown",
                  notes: str | None = None) -> int:
    """Insert or update a source by name. Returns row id."""
    row = conn.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute("""
            UPDATE sources
            SET url_pattern = COALESCE(?, url_pattern),
                source_type = ?, reliability_score = ?, latency_score = ?,
                bias = ?, notes = COALESCE(?, notes)
            WHERE id = ?
        """, (url_pattern, source_type, reliability_score, latency_score,
              bias, notes, row["id"]))
        return row["id"]
    cur = conn.execute("""
        INSERT INTO sources (name, url_pattern, source_type, reliability_score,
                             latency_score, bias, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, url_pattern, source_type, reliability_score, latency_score,
          bias, notes, utcnow_iso()))
    return cur.lastrowid or 0


def lookup_source_by_url(conn: sqlite3.Connection, url: str) -> dict | None:
    """Match a URL against url_pattern fields. Returns dict of source row or None.
    Matching is substring — pattern 'reuters.com' matches 'https://www.reuters.com/...'."""
    if not url:
        return None
    rows = conn.execute("""
        SELECT id, name, url_pattern, source_type, reliability_score,
               latency_score, bias, times_cited, times_correct, times_wrong
        FROM sources
        WHERE url_pattern IS NOT NULL AND url_pattern != ''
    """).fetchall()
    url_lower = url.lower()
    # Find longest matching pattern (so x.com/@specific_user wins over x.com)
    best = None
    best_len = 0
    for r in rows:
        pat = (r["url_pattern"] or "").lower()
        if pat and pat in url_lower and len(pat) > best_len:
            best = dict(r)
            best_len = len(pat)
    return best


def increment_source_citation(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("UPDATE sources SET times_cited = times_cited + 1 WHERE id = ?",
                 (source_id,))


def increment_source_outcome(conn: sqlite3.Connection, source_id: int,
                             correct: bool) -> None:
    field = "times_correct" if correct else "times_wrong"
    conn.execute(f"UPDATE sources SET {field} = {field} + 1 WHERE id = ?",
                 (source_id,))


# Seed list — populated on first DB init. Idempotent (upsert).
DEFAULT_SOURCES = [
    # News agencies — very fast, highly reliable
    ("Reuters", "reuters.com", "news_agency", 0.92, 0.95, "center"),
    ("AP", "apnews.com", "news_agency", 0.92, 0.95, "center"),
    ("Bloomberg", "bloomberg.com", "news_agency", 0.88, 0.90, "center"),
    ("AFP", "afp.com", "news_agency", 0.90, 0.92, "center"),
    # Major newspapers — slower, well-sourced
    ("NYT", "nytimes.com", "newspaper", 0.85, 0.75, "left"),
    ("WSJ", "wsj.com", "newspaper", 0.87, 0.78, "right"),
    ("FT", "ft.com", "newspaper", 0.88, 0.78, "center"),
    ("Washington Post", "washingtonpost.com", "newspaper", 0.82, 0.75, "left"),
    ("Guardian", "theguardian.com", "newspaper", 0.78, 0.75, "left"),
    # Political beats
    ("Politico", "politico.com", "political", 0.78, 0.85, "center"),
    ("The Hill", "thehill.com", "political", 0.72, 0.85, "center"),
    ("Axios", "axios.com", "political", 0.75, 0.88, "center"),
    # Regional — geo-political markets
    ("JNS", "jns.org", "regional", 0.65, 0.85, "right"),
    ("Times of Israel", "timesofisrael.com", "regional", 0.75, 0.85, "center"),
    ("Haaretz", "haaretz.com", "regional", 0.75, 0.80, "left"),
    ("Al Jazeera", "aljazeera.com", "regional", 0.65, 0.80, "mixed"),
    ("Kyiv Independent", "kyivindependent.com", "regional", 0.72, 0.85, "center"),
    # Official / government
    ("WhiteHouse", "whitehouse.gov", "gov", 0.95, 0.50, "center"),
    ("US State Dept", "state.gov", "gov", 0.92, 0.40, "center"),
    ("Knesset", "knesset.gov.il", "gov", 0.95, 0.50, "center"),
    ("Federal Reserve", "federalreserve.gov", "gov", 0.98, 0.60, "center"),
    ("Polymarket Gamma", "gamma-api.polymarket.com", "official", 1.00, 1.00, "center"),
    ("Polymarket CLOB", "clob.polymarket.com", "official", 1.00, 1.00, "center"),
    # Tech-specific
    ("ArXiv", "arxiv.org", "tech", 0.78, 0.50, "center"),
    ("Google AI Blog", "blog.google", "tech", 0.85, 0.70, "center"),
    ("OpenAI Blog", "openai.com/blog", "tech", 0.85, 0.70, "center"),
    # Background / reference
    ("Wikipedia", "wikipedia.org", "wiki", 0.55, 0.40, "unknown"),
    ("Ballotpedia", "ballotpedia.org", "wiki", 0.72, 0.55, "center"),
    # Social — fast but noisy
    ("X (Twitter)", "x.com", "social", 0.30, 1.00, "mixed"),
    ("Truth Social", "truthsocial.com", "social", 0.25, 1.00, "right"),
    ("Reddit", "reddit.com", "social", 0.25, 0.90, "mixed"),
    # External integrations as canonical sources (Tier 1 keyless connectors)
    ("GDELT", "gdeltproject.org", "news_agency", 0.65, 0.95, "mixed"),
    ("OpenStreetMap", "openstreetmap.org", "official", 0.85, 0.50, "center"),
    ("Nominatim", "nominatim.openstreetmap.org", "official", 0.85, 0.50, "center"),
    ("Open-Meteo", "open-meteo.com", "official", 0.85, 0.95, "center"),
    ("SEC EDGAR", "sec.gov", "gov", 0.98, 0.70, "center"),
    ("GitHub API", "api.github.com", "tech", 0.85, 0.95, "center"),
    ("Wikidata", "wikidata.org", "wiki", 0.70, 0.40, "unknown"),
    # Tier 2 keyed integrations (registered + active where account permits)
    ("ACLED", "acleddata.com", "official", 0.90, 0.80, "center"),
    ("OpenFEC", "api.open.fec.gov", "gov", 0.98, 0.75, "center"),
    ("NASA FIRMS", "firms.modaps.eosdis.nasa.gov", "official", 0.95, 0.85, "center"),
    ("ProPublica Nonprofits", "projects.propublica.org", "news_agency", 0.85, 0.50, "left"),
    ("YouTube", "youtube.com", "social", 0.55, 0.95, "mixed"),
    # Tier 3 keyless additions
    ("ReliefWeb", "reliefweb.int", "official", 0.85, 0.80, "center"),
    ("OFAC Treasury", "treasury.gov", "gov", 0.98, 0.60, "center"),
    ("EU Sanctions", "europa.eu", "gov", 0.95, 0.60, "center"),
    ("UK OFSI", "publishing.service.gov.uk", "gov", 0.95, 0.60, "center"),
    ("OpenSky Network", "opensky-network.org", "official", 0.85, 0.95, "center"),
    ("Wikidata Query", "query.wikidata.org", "wiki", 0.70, 0.40, "unknown"),
]


def seed_default_sources(conn: sqlite3.Connection) -> int:
    """Insert default source list. Idempotent via upsert. Returns count touched."""
    n = 0
    for tup in DEFAULT_SOURCES:
        name, url, stype, rel, lat, bias = tup
        upsert_source(conn, name=name, url_pattern=url, source_type=stype,
                      reliability_score=rel, latency_score=lat, bias=bias)
        n += 1
    return n
