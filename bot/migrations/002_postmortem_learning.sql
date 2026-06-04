-- ============================================================
-- Signal Post-Mortem Learning System — Migration 002
-- Implements the full learning layer as designed by GPT/user.
-- Run once: python -c "import db; db.run_migration('002')"
-- ============================================================

-- ── Core post-mortem table ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS position_postmortems (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    market_question             TEXT,
    market_slug                 TEXT,
    condition_id                TEXT,

    -- Financial outcome
    outcome_label               TEXT,   -- WIN/LOSS/BREAKEVEN/PARTIAL_WIN/PARTIAL_LOSS/EARLY_EXIT_GOOD/EARLY_EXIT_BAD
    entry_price                 REAL,
    exit_price                  REAL,
    stake_usd                   REAL,
    pnl_usd                     REAL,
    pnl_pct                     REAL,
    resolution_result           TEXT,   -- YES/NO/CANCELLED/EXPIRED

    -- Process quality
    process_label               TEXT,   -- GOOD_PROCESS_GOOD_OUTCOME / GOOD_PROCESS_BAD_OUTCOME / BAD_PROCESS_GOOD_OUTCOME / BAD_PROCESS_BAD_OUTCOME / UNCLEAR_PROCESS

    -- Original thesis
    original_thesis             TEXT,
    market_implied_probability  REAL,
    signal_estimated_probability REAL,
    estimated_edge              REAL,
    edge_types                  TEXT,   -- JSON array: ["LOCAL_LANGUAGE_EDGE","POLLING_EDGE",...]
    core_reason                 TEXT,

    -- What happened
    final_outcome_description   TEXT,
    thesis_correct              INTEGER, -- 1/0/null
    timing_correct              INTEGER,
    wording_correct             INTEGER,

    -- Root cause (pick primary)
    primary_success_reason      TEXT,
    primary_failure_reason      TEXT,
    error_types                 TEXT,   -- JSON array from taxonomy

    -- Market understanding quality (0-5)
    market_understanding_score  REAL,
    source_quality_score        REAL,
    evidence_weighting_score    REAL,
    deadline_model_score        REAL,
    resolution_wording_score    REAL,
    entry_quality_score         REAL,
    exit_quality_score          REAL,
    sizing_quality_score        REAL,
    calibration_quality_score   REAL,
    overall_process_score       REAL,

    -- Reusability
    reusable_edge               TEXT,   -- what generalizes
    non_reusable_luck           TEXT,   -- what was just luck
    false_confidence_source     TEXT,   -- what created fake certainty
    missed_disconfirmation      TEXT,   -- what was ignored against position
    system_patch_required       TEXT,   -- concrete system fix

    should_trade_similar_again  INTEGER, -- 1/0
    summary                     TEXT,

    created_at                  TEXT DEFAULT (datetime('now')),
    updated_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Evidence yield ledger ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence_yield_ledger (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),
    condition_id                TEXT,

    source_url                  TEXT,
    source_title                TEXT,
    source_type                 TEXT,   -- primary/secondary/market_chatter/interpretation/social
    language                    TEXT,
    published_at                TEXT,
    discovered_by_module        TEXT,   -- CommandB/Forager/Manual/CommandG/etc

    extracted_claim             TEXT,
    stance_vs_yes               TEXT,   -- SUPPORTS_YES/SUPPORTS_NO/NEUTRAL
    stance_vs_selected_side     TEXT,   -- CONFIRMS/CONTRADICTS/NEUTRAL

    changed_probability         INTEGER,        -- 1/0
    probability_delta           REAL,           -- how much it moved signal estimate

    found_disconfirming_evidence INTEGER,
    prevented_bad_trade         INTEGER,
    caused_false_confidence     INTEGER,
    was_overweighted            INTEGER,
    was_underweighted           INTEGER,

    post_resolution_value       TEXT,   -- DECISIVE/HELPFUL/NOISE/MISLEADING/HARMFUL
    contribution_score          REAL,   -- -3 to +3

    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Probability calibration ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS probability_calibration (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),
    condition_id                TEXT,
    selected_side               TEXT,

    market_price_entry          REAL,
    market_implied_probability  REAL,
    signal_probability          REAL,
    edge_estimate               REAL,

    market_price_exit           REAL,
    final_resolution            TEXT,

    brier_score                 REAL,
    log_score                   REAL,
    calibration_bucket          TEXT,   -- "0.50-0.60" etc

    was_overconfident           INTEGER,
    was_underconfident          INTEGER,
    probability_error_type      TEXT,   -- OVERCONFIDENT/UNDERCONFIDENT/DIRECTION_WRONG/CALIBRATED

    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Deadline audit ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS deadline_audit (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),
    condition_id                TEXT,

    deadline_date               TEXT,
    deadline_type               TEXT,   -- CALENDAR/PROCEDURAL/EVENT_TRIGGERED/HARD/SOFT
    deadline_clearly_modeled    INTEGER,

    event_probable_overall      INTEGER,   -- would it happen eventually?
    event_probable_in_window    INTEGER,   -- but in THIS window?
    thesis_right_timing_wrong   INTEGER,

    procedural_bottlenecks      TEXT,   -- what could block/delay
    holiday_risk                INTEGER,
    bureaucracy_risk            INTEGER,
    delayed_resolution_risk     INTEGER,

    deadline_was_edge           INTEGER,   -- did we find edge in deadline?
    deadline_was_error_source   INTEGER,

    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Resolution wording audit ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS resolution_wording_audit (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),
    condition_id                TEXT,

    wording_text                TEXT,
    resolution_source           TEXT,
    required_artifact           TEXT,   -- "official announcement"/"signed bill"/"court ruling"/etc
    artifact_type               TEXT,

    wording_clarity_score       REAL,   -- 1-5
    ambiguity_flags             TEXT,   -- JSON array of issues found
    misunderstood_wording       INTEGER,
    wording_trap_detected       INTEGER,

    signal_traded_event         TEXT,   -- what Signal thought it was trading
    market_actually_resolved_on TEXT,   -- what it actually resolved on
    gap_description             TEXT,

    final_resolution_reason     TEXT,
    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Module attribution ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS module_attribution (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),
    condition_id                TEXT,

    module_name                 TEXT,   -- CommandG/CommandA/CommandB/CommandC/CommandD/Forager/Manual/etc
    module_role                 TEXT,

    discovered_market           INTEGER,
    found_key_evidence          INTEGER,
    found_disconfirming_evidence INTEGER,
    changed_probability         INTEGER,
    caused_false_confidence     INTEGER,
    missed_critical_issue       INTEGER,

    contribution_score          REAL,   -- -3 to +3
    required_fix                TEXT,

    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Market type learning ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_type_learning (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),
    condition_id                TEXT,

    domain                      TEXT,   -- geopolitics/elections/ai_tech/macro_econ/etc
    subdomain                   TEXT,
    geography                   TEXT,
    language_edge_available     INTEGER,

    market_type                 TEXT,   -- election/diplomatic_meeting/war_event/product_release/etc
    event_type                  TEXT,
    resolution_type             TEXT,   -- binary/multi_outcome/continuous
    deadline_type               TEXT,   -- calendar/event/procedural

    efficiency_estimate         TEXT,   -- VERY_EFFICIENT/MODERATELY_EFFICIENT/INEFFICIENT/UNDERFOLLOWED/NOISY/TRAP
    beatability_score           REAL,   -- 0-10

    should_signal_trade_again   INTEGER,
    preferred_research_strategy TEXT,
    avoid_reason                TEXT,

    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Disconfirming evidence review ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS disconfirming_evidence_review (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),
    condition_id                TEXT,

    counterclaim                TEXT,
    source_url                  TEXT,
    source_type                 TEXT,
    strength_score              REAL,   -- 1-5

    found_before_entry          INTEGER,
    considered_in_decision      INTEGER,
    correctly_weighted          INTEGER,

    should_have_changed_probability INTEGER,
    probability_delta_suggested REAL,

    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Human vs model contribution ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS human_model_delta (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER NOT NULL REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),
    condition_id                TEXT,

    signal_recommendation       TEXT,
    user_action                 TEXT,

    manual_override             INTEGER,
    override_reason             TEXT,

    signal_was_right            INTEGER,
    user_was_right              INTEGER,
    override_helped             INTEGER,
    override_hurt               INTEGER,

    emotional_risk_flag         INTEGER,
    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Learning lessons ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS learning_lessons (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id                 INTEGER REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),

    lesson_type                 TEXT,   -- SOURCE_WEIGHT/DEADLINE_MODEL/RESOLUTION_WORDING/ENTRY_PRICE/SIZING/MARKET_SELECTION/etc
    lesson_text                 TEXT,   -- concrete, specific, actionable

    applies_to_market_types     TEXT,   -- JSON array
    applies_to_modules          TEXT,   -- JSON array

    severity                    TEXT,   -- LOW/MEDIUM/HIGH/CRITICAL
    confidence                  TEXT,   -- LOW/MEDIUM/HIGH

    should_become_gate          INTEGER,
    should_update_prompt        INTEGER,
    should_update_weight        INTEGER,
    should_update_db_schema     INTEGER,

    implemented                 INTEGER DEFAULT 0,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Gate updates ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gate_updates (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_position_id          INTEGER REFERENCES positions(id),
    source_postmortem_id        INTEGER REFERENCES position_postmortems(id),

    gate_name                   TEXT,
    gate_description            TEXT,
    trigger_condition           TEXT,
    action                      TEXT,   -- BLOCK/REQUIRE_HUMAN/REDUCE_SIZE/ADD_CHECKLIST_ITEM

    severity                    TEXT,   -- LOW/MEDIUM/HIGH/CRITICAL
    applies_to_market_types     TEXT,   -- JSON array

    active                      INTEGER DEFAULT 0,
    implemented_at              TEXT,
    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Prompt update candidates ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prompt_update_candidates (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_position_id          INTEGER REFERENCES positions(id),
    postmortem_id               INTEGER REFERENCES position_postmortems(id),

    command_name                TEXT,   -- CommandA/CommandB/CommandD/etc
    current_prompt_issue        TEXT,
    proposed_prompt_patch       TEXT,

    reason                      TEXT,
    priority                    TEXT,   -- LOW/MEDIUM/HIGH/CRITICAL
    approved                    INTEGER DEFAULT 0,

    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ── Aggregate learning snapshot (run after each batch) ────────────────────
CREATE TABLE IF NOT EXISTS learning_snapshots (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date               TEXT,
    total_closed_positions      INTEGER,
    good_process_count          INTEGER,
    bad_process_count           INTEGER,
    unclear_process_count       INTEGER,
    profitable_count            INTEGER,
    unprofitable_count          INTEGER,
    avg_process_score           REAL,
    avg_calibration_error       REAL,
    best_edge_type              TEXT,
    worst_error_type            TEXT,
    most_useful_source_type     TEXT,
    most_dangerous_source_type  TEXT,
    top_system_fixes            TEXT,   -- JSON array
    notes                       TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
);
