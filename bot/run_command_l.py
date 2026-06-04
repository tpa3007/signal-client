"""
Command L — Learn From Closed Positions
=========================================
Post-mortem analysis engine for Signal V1 closed positions.

Usage:
  python run_command_l.py              -- process all unreviewed closed positions
  python run_command_l.py --id 6       -- process single position by ID
  python run_command_l.py --batch      -- process all + generate aggregate snapshot
  python run_command_l.py --snapshot   -- only generate aggregate snapshot from existing postmortems
  python run_command_l.py --list       -- list all postmortems already recorded

Architecture follows the 30-block GPT framework:
  Market → Thesis → Evidence → Probability → Entry → Hold/Exit → Resolution → Post-mortem → Rule update

The key insight: Signal must not learn from outcome alone.
It learns from the delta between what it believed, why, what resolved,
which evidence was decision-useful, and which process generalizes.
"""

from __future__ import annotations
import sys, os, json, sqlite3, argparse, math
from datetime import datetime, timezone
from textwrap import dedent

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(ROOT_DIR, "bot.db")

# ── Error type taxonomy ────────────────────────────────────────────────────
ERROR_TYPES = [
    "BAD_DEADLINE_MODEL",
    "BAD_RESOLUTION_READING",
    "BAD_SOURCE_SELECTION",
    "FALSE_CONFIDENCE",
    "OVERWEIGHTED_NOISE",
    "UNDERWEIGHTED_LOCAL_SOURCE",
    "MISSED_DISCONFIRMING_EVIDENCE",
    "BAD_ENTRY_PRICE",
    "BAD_EXIT_DISCIPLINE",
    "LOW_LIQUIDITY_TRAP",
    "MARKET_ALREADY_EFFICIENT",
    "THESIS_RIGHT_TIMING_WRONG",
    "THESIS_WRONG",
    "RANDOM_OUTCOME",
]

EDGE_TYPES = [
    "SOURCE_EDGE",
    "LOCAL_LANGUAGE_EDGE",
    "POLLING_EDGE",
    "DEADLINE_MODEL_EDGE",
    "RESOLUTION_WORDING_EDGE",
    "MARKET_MISPRICING_EDGE",
    "NARRATIVE_ASYMMETRY_EDGE",
    "LIQUIDITY_EDGE",
    "TIMING_EDGE",
]

OUTCOME_LABELS = [
    "WIN", "LOSS", "BREAKEVEN",
    "PARTIAL_WIN", "PARTIAL_LOSS",
    "EARLY_EXIT_GOOD", "EARLY_EXIT_BAD",
]

PROCESS_LABELS = [
    "GOOD_PROCESS_GOOD_OUTCOME",
    "GOOD_PROCESS_BAD_OUTCOME",
    "BAD_PROCESS_GOOD_OUTCOME",
    "BAD_PROCESS_BAD_OUTCOME",
    "UNCLEAR_PROCESS",
]


# ── Pre-filled post-mortems for Signal V1 closed positions ────────────────
# These are the analyst-completed assessments for each closed position.
# Format: position_id → full postmortem dict
POSTMORTEMS_V1: dict[int, dict] = {

    # ══════════════════════════════════════════════════════════════════════
    # ID=6: Jerome Powell departure YES @ 0.568 → RESOLVED YES → +$19
    # ══════════════════════════════════════════════════════════════════════
    6: {
        "outcome_label": "WIN",
        "process_label": "GOOD_PROCESS_GOOD_OUTCOME",
        "entry_price": 0.568,
        "exit_price": 1.0,
        "pnl_usd": 19.01,
        "resolution_result": "YES",
        "original_thesis": "Powell's 4-year term expired May 15, 2026 — exactly within the market window. Kevin Warsh named as successor, Senate confirmation expected. Market at 56.8¢ for an event with calendar-certain date.",
        "market_implied_probability": 0.568,
        "signal_estimated_probability": 0.92,
        "estimated_edge": 0.352,
        "edge_types": json.dumps(["DEADLINE_MODEL_EDGE", "RESOLUTION_WORDING_EDGE"]),
        "core_reason": "Calendar-locked event (term expiry) mis-priced by market due to procedural uncertainty noise.",
        "final_outcome_description": "Powell departed as Fed Chair on schedule. Term expiry was the hard trigger. Resolved YES, full payout.",
        "thesis_correct": 1,
        "timing_correct": 1,
        "wording_correct": 1,
        "primary_success_reason": "DEADLINE_MODEL_EDGE",
        "primary_failure_reason": None,
        "error_types": json.dumps([]),
        "market_understanding_score": 5,
        "source_quality_score": 4,
        "evidence_weighting_score": 4,
        "deadline_model_score": 5,
        "resolution_wording_score": 5,
        "entry_quality_score": 4,
        "exit_quality_score": 5,
        "sizing_quality_score": 3,
        "calibration_quality_score": 4,
        "overall_process_score": 4.3,
        "reusable_edge": "Calendar-locked events (term expiries, scheduled dates) are systematically mispriced when the market conflates 'departure' with 'resignation' uncertainty. The key insight: if the deadline IS the event, price should reflect 1.0 minus small procedural risk.",
        "non_reusable_luck": "Minimal luck component — event was structurally certain.",
        "false_confidence_source": "None identified.",
        "missed_disconfirmation": "Could have held on (some uncertainty about exact exit date framing).",
        "system_patch_required": "Add DEADLINE_IS_EVENT gate: when market deadline coincides with scheduled event (expiry, election, meeting), apply calendar certainty premium.",
        "should_trade_similar_again": 1,
        "summary": "Golden case. Calendar-locked departure priced too cheaply due to procedural noise. Signal correctly identified the deadline structure.",

        # Sub-tables
        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 1,
            "event_probable_overall": 1,
            "event_probable_in_window": 1,
            "thesis_right_timing_wrong": 0,
            "deadline_was_edge": 1,
            "deadline_was_error_source": 0,
            "notes": "Term expiry date was public record. Market was pricing in 'what if Trump keeps him?' uncertainty, which was the mispricing."
        },
        "wording": {
            "wording_clarity_score": 4.5,
            "misunderstood_wording": 0,
            "required_artifact": "Official announcement of departure/new chair appointment",
            "artifact_type": "government_announcement",
            "notes": "Market resolved on official Fed departure. Signal correctly understood what was needed."
        },
        "market_type": {
            "domain": "macro_econ",
            "subdomain": "central_bank",
            "geography": "USA",
            "market_type": "appointment",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "MODERATELY_EFFICIENT",
            "beatability_score": 7.5,
            "should_signal_trade_again": 1,
            "preferred_research_strategy": "Calendar-lock verification + procedural path modeling"
        },
        "lessons": [
            {
                "lesson_type": "DEADLINE_MODEL",
                "lesson_text": "When a market window CONTAINS the scheduled expiry/end of a term, price the event near certainty unless there is specific evidence of an extension mechanism. Do not import general 'will X happen' uncertainty onto calendar-locked events.",
                "severity": "HIGH",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "RESOLUTION_WORDING",
                "lesson_text": "Verify what artifact triggers resolution — for 'departure' markets, confirmation is often just the official successor announcement, which removes last-minute uncertainty.",
                "severity": "MEDIUM",
                "should_become_gate": 0,
            },
            {
                "lesson_type": "SIZING",
                "lesson_text": "For calendar-locked events with edge > 30pp, sizing was conservative. Should have deployed 2x stake.",
                "severity": "LOW",
                "should_become_gate": 0,
            },
        ],
        "evidence": [
            {"source_title": "Fed term expiry date (public record)", "source_type": "primary", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": 3, "caused_false_confidence": 0, "post_resolution_value": "DECISIVE"},
            {"source_title": "Kevin Warsh nomination reporting", "source_type": "secondary", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": 2, "caused_false_confidence": 0, "post_resolution_value": "HELPFUL"},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 1, "contribution_score": 3, "missed_critical_issue": 0},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=7: Russia enters Huliaipilske by May 31 YES @ 0.430 → EXIT @ 0.984 → +$19.33
    # ══════════════════════════════════════════════════════════════════════
    7: {
        "outcome_label": "EARLY_EXIT_GOOD",
        "process_label": "GOOD_PROCESS_GOOD_OUTCOME",
        "entry_price": 0.430,
        "exit_price": 0.984,
        "pnl_usd": 19.33,
        "resolution_result": "YES",
        "original_thesis": "Russian forces actively encircling Huliaipilske. ISW/Critical Threats: 'gradual advance northeast and southwest.' Entry made early while market at 43¢.",
        "market_implied_probability": 0.430,
        "signal_estimated_probability": 0.72,
        "estimated_edge": 0.290,
        "edge_types": json.dumps(["SOURCE_EDGE", "LOCAL_LANGUAGE_EDGE", "TIMING_EDGE"]),
        "core_reason": "ISW/Critical Threats front-line maps showed encirclement pattern at 43¢. Operational military logic + source edge.",
        "final_outcome_description": "Russia captured Huliaipilske. Signal exited at 98.4¢ (take profit), capturing ~95% of the move.",
        "thesis_correct": 1,
        "timing_correct": 1,
        "wording_correct": 1,
        "primary_success_reason": "SOURCE_EDGE",
        "primary_failure_reason": None,
        "error_types": json.dumps([]),
        "market_understanding_score": 4,
        "source_quality_score": 5,
        "evidence_weighting_score": 4,
        "deadline_model_score": 4,
        "resolution_wording_score": 4,
        "entry_quality_score": 5,
        "exit_quality_score": 5,
        "sizing_quality_score": 3,
        "calibration_quality_score": 4,
        "overall_process_score": 4.2,
        "reusable_edge": "ISW/Critical Threats operational maps provide genuine tactical edge on Polymarket Ukraine front-line markets, especially when showing encirclement patterns. The market systematically lags these maps by 24-48h.",
        "non_reusable_luck": "Exit timing at 98.4¢ was opportunistic — the final resolution could have been delayed.",
        "false_confidence_source": "None identified.",
        "missed_disconfirmation": "Counter-offensive potential was not fully modeled — Ukrainian forces could have pushed back.",
        "system_patch_required": "Create 'operational_map_edge' source type in evidence ledger. Weight ISW encirclement signals at +2 contribution when within 30-day window.",
        "should_trade_similar_again": 1,
        "summary": "Strong process. ISW encirclement pattern = systematic Polymarket lag. Early exit at 98.4¢ was disciplined.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 1,
            "event_probable_overall": 1,
            "event_probable_in_window": 1,
            "thesis_right_timing_wrong": 0,
            "deadline_was_edge": 0,
            "deadline_was_error_source": 0,
            "notes": "May 31 deadline gave ~2 weeks window. Signal correctly modeled this as sufficient time given the pace of advance."
        },
        "wording": {
            "wording_clarity_score": 4.0,
            "misunderstood_wording": 0,
            "required_artifact": "Geolocation confirmation of Russian forces in settlement",
            "artifact_type": "geolocation_evidence",
            "notes": "Polymarket Ukraine markets resolve on geolocation. Signal understood this."
        },
        "market_type": {
            "domain": "geopolitics",
            "subdomain": "ukraine_war",
            "geography": "Ukraine",
            "market_type": "war_event",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "INEFFICIENT",
            "beatability_score": 8.0,
            "should_signal_trade_again": 1,
            "preferred_research_strategy": "ISW operational maps + front-line encirclement pattern detection"
        },
        "lessons": [
            {
                "lesson_type": "SOURCE_WEIGHT",
                "lesson_text": "ISW operational maps with encirclement patterns on Polymarket front-line markets have consistently high predictive value. These should have contribution_score +3 by default.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
            {
                "lesson_type": "SIZING",
                "lesson_text": "War front-line markets with clear ISW signal deserve larger sizing than $15. Consider $25-40 when encirclement pattern is confirmed.",
                "severity": "MEDIUM",
                "should_become_gate": 0,
            },
        ],
        "evidence": [
            {"source_title": "ISW/Critical Threats front-line map (encirclement pattern)", "source_type": "primary", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": 3, "caused_false_confidence": 0, "post_resolution_value": "DECISIVE"},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 1, "contribution_score": 3, "missed_critical_issue": 0},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=13: Gemini 3.5 released by May 31 NO @ 0.785 → stop_loss → LOSS
    # ══════════════════════════════════════════════════════════════════════
    13: {
        "outcome_label": "LOSS",
        "process_label": "BAD_PROCESS_BAD_OUTCOME",
        "entry_price": 0.785,
        "exit_price": 0.0,
        "pnl_usd": -12.0,   # approximate from stop_loss trigger
        "resolution_result": "YES",  # Gemini 3.5 DID release (Google I/O)
        "original_thesis": "Google I/O was May 19. Multiple sources confirmed Gemini 3.5 expected at I/O. Signal thought this was NOT likely before May 31, entered NO at 78.5¢.",
        "market_implied_probability": 0.215,  # market said 21.5% YES
        "signal_estimated_probability": 0.15,
        "estimated_edge": 0.065,
        "edge_types": json.dumps([]),
        "core_reason": "Signal believed Google I/O would NOT produce Gemini 3.5 flagship. Incorrect assessment.",
        "final_outcome_description": "Google released Gemini 3.5/2.0 Flash at Google I/O May 19. Signal's NO thesis was WRONG. Stop-loss triggered.",
        "thesis_correct": 0,
        "timing_correct": 0,
        "wording_correct": 0,
        "primary_success_reason": None,
        "primary_failure_reason": "THESIS_WRONG",
        "error_types": json.dumps(["THESIS_WRONG", "BAD_SOURCE_SELECTION", "FALSE_CONFIDENCE"]),
        "market_understanding_score": 2,
        "source_quality_score": 2,
        "evidence_weighting_score": 2,
        "deadline_model_score": 3,
        "resolution_wording_score": 2,
        "entry_quality_score": 2,
        "exit_quality_score": 3,
        "sizing_quality_score": 3,
        "calibration_quality_score": 2,
        "overall_process_score": 2.3,
        "reusable_edge": "None — this was a directional error.",
        "non_reusable_luck": "N/A (we lost).",
        "false_confidence_source": "Overconfidence that Google would NOT release Gemini 3.5 at I/O based on insufficient evidence. The wording 'new Gemini flagship' was broad enough to include Flash-tier updates.",
        "missed_disconfirmation": "Multiple leaks and signals about Gemini 3.5 pre-I/O were available but not adequately weighted. Google I/O is ALWAYS a major AI release event.",
        "system_patch_required": "GATE: No AI product release NO positions within 10 days of major tech conference (Google I/O, OpenAI Dev Day, etc.) without explicit confirmed cancellation from primary source.",
        "should_trade_similar_again": 0,
        "summary": "Bad process, bad outcome. Signal incorrectly bet against a Google I/O product release. The market (78.5¢ for NO) was actually pricing in real uncertainty, but Signal mis-assessed the release probability. Key lesson: Major tech conferences are HIGH probability release events.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 1,
            "event_probable_overall": 1,
            "event_probable_in_window": 1,
            "thesis_right_timing_wrong": 0,
            "deadline_was_edge": 0,
            "deadline_was_error_source": 0,
            "notes": "Deadline was fine. The core error was thesis direction."
        },
        "wording": {
            "wording_clarity_score": 3.0,
            "misunderstood_wording": 1,
            "required_artifact": "official_product_release",
            "artifact_type": "product_announcement",
            "notes": "Signal may have used narrow definition of 'flagship' when market wording was broader. The release of Gemini 2.0 Flash/3.5 variants satisfied the market resolution criteria."
        },
        "market_type": {
            "domain": "ai_tech",
            "subdomain": "product_release",
            "geography": "USA",
            "market_type": "product_release",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "MODERATELY_EFFICIENT",
            "beatability_score": 4.0,
            "should_signal_trade_again": 0,
            "avoid_reason": "AI product release markets near major conferences are TRAP — the conference creates systematic release pressure.",
            "preferred_research_strategy": "Only trade these with confirmed internal source or post-conference no-announcement confirmation."
        },
        "lessons": [
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "HARD GATE: Do not take NO positions on AI product release markets within 14 days of a major tech conference (Google I/O, OpenAI Dev Day, Apple WWDC, Microsoft Build). These events are explicitly release-oriented.",
                "severity": "CRITICAL",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "RESOLUTION_WORDING",
                "lesson_text": "For product release markets, verify exact wording: 'new Gemini flagship' may resolve on ANY new Gemini model, not just the top-tier. Always check historical Polymarket resolution for similar markets.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
        ],
        "evidence": [
            {"source_title": "Google I/O announcement schedule (public)", "source_type": "primary", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": -2, "caused_false_confidence": 1, "post_resolution_value": "MISLEADING", "notes": "Signal knew I/O was May 19 but incorrectly dismissed release probability."},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 0, "contribution_score": -2, "missed_critical_issue": 1, "required_fix": "Add conference proximity check to AI product release analysis."},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=15: Israeli Knesset dissolution YES @ 0.130 → manual exit ~$7 → PARTIAL_LOSS
    # ══════════════════════════════════════════════════════════════════════
    15: {
        "outcome_label": "EARLY_EXIT_BAD",
        "process_label": "BAD_PROCESS_BAD_OUTCOME",
        "entry_price": 0.130,
        "exit_price": 0.07,  # approximate
        "pnl_usd": -3.0,   # approximate small loss
        "resolution_result": "NO",
        "original_thesis": "HIDDEN GEM: Coalition submitted dissolution bill May 13-14 (Likud + UTJ + Shas + Religious Zionism). Constitutional path clear. Signal estimated 45% YES at 13¢.",
        "market_implied_probability": 0.130,
        "signal_estimated_probability": 0.45,
        "estimated_edge": 0.320,
        "edge_types": json.dumps(["RESOLUTION_WORDING_EDGE", "DEADLINE_MODEL_EDGE"]),
        "core_reason": "Saw dissolution bill submitted as strong evidence. Market at 13¢ seemed too cheap for active bill passage.",
        "final_outcome_description": "Knesset was NOT dissolved by May 31. The bill did not pass in time. Coalition dynamics stalled passage. Manual exit as deadline-model deteriorated.",
        "thesis_correct": 0,
        "timing_correct": 0,
        "wording_correct": 1,
        "primary_success_reason": None,
        "primary_failure_reason": "BAD_DEADLINE_MODEL",
        "error_types": json.dumps(["BAD_DEADLINE_MODEL", "THESIS_RIGHT_TIMING_WRONG", "FALSE_CONFIDENCE"]),
        "market_understanding_score": 3,
        "source_quality_score": 3,
        "evidence_weighting_score": 2,
        "deadline_model_score": 2,
        "resolution_wording_score": 4,
        "entry_quality_score": 3,
        "exit_quality_score": 3,
        "sizing_quality_score": 4,
        "calibration_quality_score": 2,
        "overall_process_score": 2.8,
        "reusable_edge": "Bill submission is a leading indicator, but parliamentary dissolution requires full vote and procedural steps that take weeks. The 13-day window (May 14 → May 31) was too tight for multi-step parliamentary process.",
        "non_reusable_luck": "The exit timing caught a reasonable price before full decline.",
        "false_confidence_source": "Conflated 'bill submitted' with 'bill will pass in 13 days.' Israeli coalition politics routinely delays, extends, renegotiates. 13 days for dissolution = extremely tight procedural timeline.",
        "missed_disconfirmation": "Israeli coalition parties were explicitly hedging on dissolution timing. Opposition resistance and Netanyahu's incentives to delay were underweighted.",
        "system_patch_required": "GATE: For parliamentary/legislative markets, model full procedural path. 'Bill submitted' → first reading → committee → second reading → third reading requires minimum 3-4 weeks in most parliaments. Apply 50% penalty if deadline < 3 weeks from bill submission.",
        "should_trade_similar_again": 0,
        "summary": "THESIS_RIGHT_TIMING_WRONG. Dissolution was eventually possible but not within the window. Key learning: parliamentary procedural timelines are longer than intuition suggests. 13 days from bill submission to full dissolution is essentially impossible in practice.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 0,
            "event_probable_overall": 1,
            "event_probable_in_window": 0,
            "thesis_right_timing_wrong": 1,
            "procedural_bottlenecks": "Multiple readings required, coalition negotiations, legal challenges, Netanyahu incentives to delay",
            "deadline_was_error_source": 1,
            "notes": "13 days was not sufficient for full dissolution process. Signal did not model minimum procedural timeline."
        },
        "wording": {
            "wording_clarity_score": 4.0,
            "misunderstood_wording": 0,
            "required_artifact": "official_knesset_dissolution_vote",
            "artifact_type": "parliamentary_vote",
            "notes": "Wording was clear. The error was timing not wording."
        },
        "market_type": {
            "domain": "geopolitics",
            "subdomain": "parliamentary_politics",
            "geography": "Israel",
            "market_type": "legal_resolution",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "MODERATELY_EFFICIENT",
            "beatability_score": 5.0,
            "should_signal_trade_again": 0,
            "avoid_reason": "Parliamentary dissolution markets with tight deadlines are procedural traps. 13¢ was a trap price.",
            "preferred_research_strategy": "Only trade if procedural path can be fully modeled within deadline"
        },
        "lessons": [
            {
                "lesson_type": "DEADLINE_MODEL",
                "lesson_text": "For parliamentary/legislative multi-step processes (bill → readings → vote), minimum realistic timeline is 21-28 days. If market deadline < 21 days from bill submission, apply DEADLINE_BOTTLENECK penalty (-40% to probability estimate) unless expedited process is confirmed.",
                "severity": "CRITICAL",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "Israeli coalition politics has systematic 'perpetual negotiation' dynamic. Statements of intent ≠ near-term action. Discount Israeli political announcements by 30% when < 21 days to deadline.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
        ],
        "evidence": [
            {"source_title": "Knesset dissolution bill submission (May 13-14)", "source_type": "primary", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": 1, "caused_false_confidence": 1, "post_resolution_value": "MISLEADING", "notes": "Bill submission ≠ bill passage. Overweighted this as strong evidence."},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 0, "contribution_score": -1, "missed_critical_issue": 1, "required_fix": "Add parliamentary procedural timeline modeling to geopolitics research."},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=18: New Gemini flagship by May 22 YES @ 0.080 → resolved_no_market_expired → LOSS
    # ══════════════════════════════════════════════════════════════════════
    18: {
        "outcome_label": "LOSS",
        "process_label": "UNCLEAR_PROCESS",
        "entry_price": 0.080,
        "exit_price": 0.0,
        "pnl_usd": -7.0,  # ~$7 lost on small position
        "resolution_result": "NO",  # Gemini 3.5 released but AFTER May 22
        "original_thesis": "Google I/O May 19 — Gemini 3.5/Spark/Omni expected. Multi-bracket umbrella event. Low price at 8¢ for what seemed like near-certain Google I/O release.",
        "market_implied_probability": 0.080,
        "signal_estimated_probability": 0.55,
        "estimated_edge": 0.470,
        "edge_types": json.dumps(["MARKET_MISPRICING_EDGE"]),
        "core_reason": "Google I/O May 19 was within the market window (deadline May 22). 8¢ seemed drastically underpriced for a near-certain conference release.",
        "final_outcome_description": "Gemini release happened but market resolved NO. Likely resolved on specific 'flagship' criterion not met by May 22, or the specific model tier didn't qualify. Resolution was technically NO despite releases happening.",
        "thesis_correct": 0,
        "timing_correct": 0,
        "wording_correct": 0,
        "primary_success_reason": None,
        "primary_failure_reason": "BAD_RESOLUTION_READING",
        "error_types": json.dumps(["BAD_RESOLUTION_READING", "RESOLUTION_WORDING_EDGE"]),
        "market_understanding_score": 2,
        "source_quality_score": 3,
        "evidence_weighting_score": 3,
        "deadline_model_score": 3,
        "resolution_wording_score": 1,
        "entry_quality_score": 3,
        "exit_quality_score": 2,
        "sizing_quality_score": 3,
        "calibration_quality_score": 2,
        "overall_process_score": 2.4,
        "reusable_edge": "None — the resolution wording was misread.",
        "non_reusable_luck": "N/A (loss).",
        "false_confidence_source": "Assumed any Gemini model at I/O would qualify as 'flagship.' The specific market wording may have required a specific tier. Also: this was a different position from ID=13 on the same underlying event — double exposure created confusion.",
        "missed_disconfirmation": "The market at 8¢ was pricing in that this SPECIFIC market's wording was a harder bar to clear. The low price was informative signal that was ignored.",
        "system_patch_required": "GATE: If we hold an open position on market X, do not enter a second similar market with overlapping resolution criteria without explicit distinction analysis. Prevent double exposure with different resolution bars.",
        "should_trade_similar_again": 0,
        "summary": "Bad resolution wording analysis. Signal held two related Gemini markets (ID=13 and ID=18) simultaneously. The lower-priced one (8¢) was encoding harder resolution criteria. The market price was providing information about resolution difficulty that Signal ignored.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 1,
            "event_probable_overall": 1,
            "event_probable_in_window": 1,  # thought so
            "thesis_right_timing_wrong": 0,
            "deadline_was_error_source": 0,
            "notes": "Deadline was fine; the error was resolution wording."
        },
        "wording": {
            "wording_clarity_score": 1.5,
            "misunderstood_wording": 1,
            "required_artifact": "specific_gemini_flagship_release",
            "artifact_type": "product_announcement",
            "notes": "Critical error. 'New Gemini flagship' likely required a specific tier that wasn't released. Signal did not investigate the exact resolution criteria before entering."
        },
        "market_type": {
            "domain": "ai_tech",
            "subdomain": "product_release",
            "geography": "USA",
            "market_type": "product_release",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "MODERATELY_EFFICIENT",
            "beatability_score": 3.0,
            "should_signal_trade_again": 0,
            "avoid_reason": "AI product release markets with tight wording are TRAP. 8¢ was encoding resolution difficulty."
        },
        "lessons": [
            {
                "lesson_type": "RESOLUTION_WORDING",
                "lesson_text": "A very low market price (< 10¢) on an apparently likely event is almost always encoding resolution wording difficulty or deadline risk. Do NOT dismiss cheap prices as 'obvious mispricing' — investigate WHY the market is pricing it low before entering.",
                "severity": "CRITICAL",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "Do not hold two positions on overlapping resolution criteria simultaneously (ID=13 and ID=18 both on Gemini release with different wording bars). This creates confusion and double exposure to the same underlying uncertainty.",
                "severity": "HIGH",
                "should_become_gate": 1,
            },
        ],
        "evidence": [
            {"source_title": "Google I/O schedule confirming May 19 keynote", "source_type": "primary", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": -1, "caused_false_confidence": 1, "post_resolution_value": "MISLEADING", "notes": "I/O did happen and Gemini was released but this specific market's wording required more."},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 0, "contribution_score": -2, "missed_critical_issue": 1, "required_fix": "Add wording audit as mandatory step BEFORE entry on any AI product release market."},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=21: Figure F.03 packages > 250k by May 21 YES @ 0.300 → exit @ 0.72 → +$21
    # ══════════════════════════════════════════════════════════════════════
    21: {
        "outcome_label": "EARLY_EXIT_GOOD",
        "process_label": "GOOD_PROCESS_GOOD_OUTCOME",
        "entry_price": 0.300,
        "exit_price": 0.720,
        "pnl_usd": 21.0,
        "resolution_result": "YES",
        "original_thesis": "Figure F.03 livestream counter pace trending toward 250k milestone by May 21 22:00 ET. Real-time data available on livestream — pure execution play on observable rate.",
        "market_implied_probability": 0.300,
        "signal_estimated_probability": 0.72,
        "estimated_edge": 0.420,
        "edge_types": json.dumps(["TIMING_EDGE", "SOURCE_EDGE"]),
        "core_reason": "Live observable data (package counter rate on stream) gave near-real-time edge. Market hadn't caught up to the pace trajectory.",
        "final_outcome_description": "250k packages achieved. Signal exited at 72¢ (+$21) ahead of resolution — disciplined take-profit before remaining variance.",
        "thesis_correct": 1,
        "timing_correct": 1,
        "wording_correct": 1,
        "primary_success_reason": "TIMING_EDGE",
        "primary_failure_reason": None,
        "error_types": json.dumps([]),
        "market_understanding_score": 5,
        "source_quality_score": 5,
        "evidence_weighting_score": 5,
        "deadline_model_score": 5,
        "resolution_wording_score": 5,
        "entry_quality_score": 5,
        "exit_quality_score": 5,
        "sizing_quality_score": 3,
        "calibration_quality_score": 5,
        "overall_process_score": 4.8,
        "reusable_edge": "Real-time observable data (livestreams, package counters, download metrics) creates systematic information asymmetry when Polymarket hasn't updated pricing based on the live feed. This is a highly reusable edge type.",
        "non_reusable_luck": "The decision to exit at 72¢ rather than hold to resolution was disciplined, not lucky.",
        "false_confidence_source": "None.",
        "missed_disconfirmation": "Counter could have slowed — this was not fully modeled.",
        "system_patch_required": "Add 'LIVE_OBSERVABLE_DATA' edge type to taxonomy. These should be priority targets when available.",
        "should_trade_similar_again": 1,
        "summary": "Near-perfect execution. Live data on observable metric created clear, actionable edge. Disciplined exit locked +$21. This is a template for a whole class of real-time information asymmetry plays.",

        "deadline": {
            "deadline_type": "CALENDAR",
            "deadline_clearly_modeled": 1,
            "event_probable_overall": 1,
            "event_probable_in_window": 1,
            "thesis_right_timing_wrong": 0,
            "deadline_was_edge": 1,
            "deadline_was_error_source": 0,
            "notes": "Deadline was clear (22:00 ET May 21). Signal correctly tracked pace vs deadline."
        },
        "wording": {
            "wording_clarity_score": 5.0,
            "misunderstood_wording": 0,
            "required_artifact": "package_count_milestone_observable",
            "artifact_type": "observable_metric",
            "notes": "Perfectly clear wording. Observable on the livestream."
        },
        "market_type": {
            "domain": "ai_tech",
            "subdomain": "robotics_milestone",
            "geography": "USA",
            "market_type": "observable_metric",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "INEFFICIENT",
            "beatability_score": 9.5,
            "should_signal_trade_again": 1,
            "preferred_research_strategy": "Monitor live streams/APIs for real-time metric tracking vs market price"
        },
        "lessons": [
            {
                "lesson_type": "SOURCE_WEIGHT",
                "lesson_text": "Real-time observable data (live streams, API endpoints, public dashboards) creates the highest-quality, most reliable edge. Whenever such data is available, it should be the PRIMARY source. Polymarket systematically lags real-time observables by 30-120 minutes.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
            {
                "lesson_type": "SIZING",
                "lesson_text": "For real-time observable-data trades, sizing was too conservative. When live data gives >40pp edge with observable confirmation, deploy 2-3x normal sizing.",
                "severity": "MEDIUM",
                "should_become_gate": 0,
            },
        ],
        "evidence": [
            {"source_title": "Figure F.03 livestream package counter (live)", "source_type": "primary", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": 3, "caused_false_confidence": 0, "post_resolution_value": "DECISIVE"},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 1, "contribution_score": 3, "missed_critical_issue": 0},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=25: PPP wins 4 seats South Korea June 3 YES @ 0.091 → manual exit $6 → PARTIAL_LOSS
    # ══════════════════════════════════════════════════════════════════════
    25: {
        "outcome_label": "EARLY_EXIT_BAD",
        "process_label": "BAD_PROCESS_BAD_OUTCOME",
        "entry_price": 0.091,
        "exit_price": 0.038,  # exited at loss
        "pnl_usd": -2.0,  # approximate
        "resolution_result": "UNKNOWN",  # Korea election June 3
        "original_thesis": "cheap_optionality strategy. PPP winning 4 seats seemed plausible at 9.1¢. No deep research.",
        "market_implied_probability": 0.091,
        "signal_estimated_probability": 0.15,
        "estimated_edge": 0.059,
        "edge_types": json.dumps(["MARKET_MISPRICING_EDGE"]),
        "core_reason": "cheap_optionality algorithmic signal. Very thin edge estimate (5.9pp). No meaningful research.",
        "final_outcome_description": "Manual exit at $6 proceeds. Position was speculative with no strong thesis. Exit was correct.",
        "thesis_correct": None,
        "timing_correct": None,
        "wording_correct": 0,
        "primary_success_reason": None,
        "primary_failure_reason": "BAD_SOURCE_SELECTION",
        "error_types": json.dumps(["FALSE_CONFIDENCE", "BAD_ENTRY_PRICE", "MARKET_ALREADY_EFFICIENT"]),
        "market_understanding_score": 1,
        "source_quality_score": 1,
        "evidence_weighting_score": 1,
        "deadline_model_score": 3,
        "resolution_wording_score": 2,
        "entry_quality_score": 2,
        "exit_quality_score": 4,
        "sizing_quality_score": 4,
        "calibration_quality_score": 1,
        "overall_process_score": 1.8,
        "reusable_edge": "None — this was an algorithmic cheap_optionality position with no research backing.",
        "non_reusable_luck": "N/A.",
        "false_confidence_source": "The algorithm flagged it as 'cheap_optionality' but for complex Korean election seat counts, the market was likely correctly pricing 9.1¢. The algorithm doesn't understand multi-seat Korean electoral dynamics.",
        "missed_disconfirmation": "PPP won only 2-3 seats in equivalent elections. 4 seats was a stretch. Korean electoral structure understanding was absent.",
        "system_patch_required": "GATE: cheap_optionality positions on Korean multi-seat election markets require local-language polling research before approval. Algorithm cannot assess these without domain knowledge.",
        "should_trade_similar_again": 0,
        "summary": "BAD_PROCESS. Algorithm-generated position with no meaningful research on complex Korean electoral mechanics. The exit was correct. Position should have been flagged for deeper analysis before entry.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 1,
            "event_probable_overall": 1,
            "event_probable_in_window": 1,
            "thesis_right_timing_wrong": 0,
            "deadline_was_edge": 0,
            "deadline_was_error_source": 0,
            "notes": "Deadline was clear (June 3). Issue was the thesis itself."
        },
        "wording": {
            "wording_clarity_score": 2.0,
            "misunderstood_wording": 1,
            "required_artifact": "official_election_result",
            "artifact_type": "election_result",
            "notes": "Specific seat count '4 seats' requires understanding Korean at-large vs proportional vs district seats in context of total PPP seats nationally."
        },
        "market_type": {
            "domain": "elections",
            "subdomain": "korean_local_election",
            "geography": "South Korea",
            "market_type": "election",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "UNDERFOLLOWED",
            "beatability_score": 6.0,
            "should_signal_trade_again": 1,
            "preferred_research_strategy": "Korean-language polling + electoral structure research + local language edge mandatory before entry"
        },
        "lessons": [
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "cheap_optionality algorithmic signal is NOT sufficient for complex multi-seat election markets in non-English languages. These require: (1) understanding of electoral structure, (2) local-language polling data, (3) historical base rates for the specific seat target.",
                "severity": "HIGH",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "SOURCE_WEIGHT",
                "lesson_text": "Korean election markets have LOCAL_LANGUAGE_EDGE available (Korean-language polls, local media). Always search Korean sources before trading Korean election markets.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
        ],
        "evidence": [
            {"source_title": "Algorithm: cheap_optionality signal", "source_type": "interpretation", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": -1, "caused_false_confidence": 1, "post_resolution_value": "NOISE", "notes": "Algorithm cannot assess Korean electoral dynamics."},
        ],
        "modules": [
            {"module_name": "CommandG", "found_key_evidence": 0, "caused_false_confidence": 1, "contribution_score": -1, "required_fix": "Add domain-knowledge gate for non-English multi-seat election markets."},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=2: Israel ground operation in Iran by May 31 YES @ 0.070 → NO → LOSS
    # ══════════════════════════════════════════════════════════════════════
    2: {
        "outcome_label": "LOSS",
        "process_label": "BAD_PROCESS_BAD_OUTCOME",
        "entry_price": 0.070,
        "exit_price": 0.011,
        "pnl_usd": -8.3,
        "resolution_result": "NO",
        "original_thesis": "NYT (May 15): Israel and US intensifying prep for potential operations 'possibly starting next week'. Active military posturing, evacuation orders Houthi-adjacent. 7¢ seemed cheap for 'intensifying preparations'.",
        "market_implied_probability": 0.070,
        "signal_estimated_probability": 0.25,
        "estimated_edge": 0.180,
        "edge_types": json.dumps(["NARRATIVE_ASYMMETRY_EDGE"]),
        "core_reason": "News narrative about military preparations interpreted as high probability of imminent action within 16-day window.",
        "final_outcome_description": "No Israeli ground operation in Iran by May 31. Military prep language did not translate into action within the deadline.",
        "thesis_correct": 0,
        "timing_correct": 0,
        "wording_correct": 1,
        "primary_success_reason": None,
        "primary_failure_reason": "BAD_DEADLINE_MODEL",
        "error_types": json.dumps(["BAD_DEADLINE_MODEL", "THESIS_RIGHT_TIMING_WRONG", "FALSE_CONFIDENCE", "OVERWEIGHTED_NOISE"]),
        "market_understanding_score": 3,
        "source_quality_score": 3,
        "evidence_weighting_score": 2,
        "deadline_model_score": 1,
        "resolution_wording_score": 4,
        "entry_quality_score": 3,
        "exit_quality_score": 2,
        "sizing_quality_score": 4,
        "calibration_quality_score": 2,
        "overall_process_score": 2.4,
        "reusable_edge": "None. 'Intensifying preparations' language in military context is standard narrative posturing — it does not predict specific-date action.",
        "non_reusable_luck": "N/A (loss).",
        "false_confidence_source": "NYT framing of 'possibly starting next week' created urgency that Signal treated as near-certain. Media phrasing of military contingency planning is routinely more dramatic than the underlying probability of action.",
        "missed_disconfirmation": "US-Iran diplomatic track was active simultaneously (Oman talks). Military prep and diplomatic track coexist without either dominating. The 'deterrence via prep' scenario (escalate to negotiate) was not modeled.",
        "system_patch_required": "GATE: Military 'preparation' or 'intensification' language does NOT constitute high-probability signal for action within 30 days unless: (a) explicit ultimatum with date, OR (b) verified troop movement in attack position. Apply -40% penalty to any military-action thesis based primarily on media 'intensification' language.",
        "should_trade_similar_again": 0,
        "summary": "Classic THESIS_RIGHT_TIMING_WRONG in the military domain. Israel may eventually strike Iran, but 16-day window + active diplomacy = low conversion probability. Media narrative 'intensification' language is inherently ambiguous about timing. The 7¢ price was the market correctly pricing in this ambiguity — not a mispricing.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 0,
            "event_probable_overall": 1,
            "event_probable_in_window": 0,
            "thesis_right_timing_wrong": 1,
            "procedural_bottlenecks": "US approval needed, diplomatic track active, deterrence logic delays action, internal Israeli coalition tensions",
            "deadline_was_edge": 0,
            "deadline_was_error_source": 1,
            "notes": "16-day window is short for a major military operation requiring US coordination. Signal did not model: (1) how long military 'prep' typically takes from signal to execution, (2) the deterrence/negotiation dynamic that delays action."
        },
        "wording": {
            "wording_clarity_score": 4.0,
            "misunderstood_wording": 0,
            "required_artifact": "confirmed_ground_operation_geolocation",
            "artifact_type": "military_action",
            "notes": "Wording was clear. The error was probability estimation."
        },
        "market_type": {
            "domain": "geopolitics",
            "subdomain": "iran_israel_conflict",
            "geography": "Iran/Israel",
            "market_type": "war_event",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "MODERATELY_EFFICIENT",
            "beatability_score": 4.0,
            "should_signal_trade_again": 0,
            "avoid_reason": "Military action markets with < 30-day windows based only on 'preparation' language. The market (7¢) was correctly pricing the low conversion rate from prep to action.",
            "preferred_research_strategy": "Only trade military action markets if: explicit ultimatum date exists, OR verified attack formation is confirmed by ISW/OSINT, OR US official explicitly confirms authorization."
        },
        "lessons": [
            {
                "lesson_type": "DEADLINE_MODEL",
                "lesson_text": "Military 'preparation' and 'intensification' language does NOT imply imminent action within 30 days. Standard military prep cycles (coordination, authorization chains, weather windows, diplomatic coordination) take 30-90 days minimum. Apply a PREP_TO_ACTION_PENALTY: if market window < 30 days and best evidence is 'preparations ongoing', cap probability at 15% regardless of media framing.",
                "severity": "CRITICAL",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "SOURCE_WEIGHT",
                "lesson_text": "NYT 'possibly next week' military framing is NOT a high-confidence signal. US media routinely publishes conditional military preparedness stories that are primarily about political signaling, not operational timelines. Assign contribution_score <= 0 to 'preparations ongoing' military news unless explicit date/authorization is confirmed.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "When a military action market AND a diplomatic resolution market for the SAME actors (US-Iran) are both open, the existence of active diplomacy should substantially reduce the military action probability. Signal held Iran ground op YES and Iran deal YES simultaneously — these are partially mutually exclusive and both were mis-priced.",
                "severity": "HIGH",
                "should_become_gate": 1,
            },
        ],
        "evidence": [
            {"source_title": "NYT: 'Israel/US intensifying prep, possibly next week'", "source_type": "secondary", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": -2, "caused_false_confidence": 1, "post_resolution_value": "MISLEADING", "notes": "Media framing created false urgency. 'Possibly' = low probability. 'Next week' = journalist speculation."},
            {"source_title": "Oman diplomatic track (US-Iran)", "source_type": "primary", "stance_vs_yes": "SUPPORTS_NO", "contribution_score": 0, "was_underweighted": 1, "post_resolution_value": "DECISIVE", "notes": "Active diplomacy track was underweighted. Military action is unlikely while diplomatic engagement is active."},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 0, "caused_false_confidence": 1, "missed_critical_issue": 1, "contribution_score": -1, "required_fix": "Add mutual-exclusivity check: military action markets + diplomatic resolution markets for same actors."},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=17: Iran closes airspace by May 31 NO @ 0.415 → NO resolved → WIN
    # ══════════════════════════════════════════════════════════════════════
    17: {
        "outcome_label": "WIN",
        "process_label": "GOOD_PROCESS_GOOD_OUTCOME",
        "entry_price": 0.415,
        "exit_price": 0.957,
        "pnl_usd": 14.6,
        "resolution_result": "NO",
        "original_thesis": "Trend is OPENING not closing. Imam Khomeini Intl resumed commercial flights May 9. Tehran FIR partially active. No political or military trigger for closure visible. Market at 41.5¢ for NO seemed underpriced for an observable, trackable event.",
        "market_implied_probability": 0.585,  # market said YES=58.5%
        "signal_estimated_probability": 0.20,  # Signal said YES only 20% likely
        "estimated_edge": 0.385,
        "edge_types": json.dumps(["SOURCE_EDGE", "NARRATIVE_ASYMMETRY_EDGE", "TIMING_EDGE"]),
        "core_reason": "Observable trend data (flight resumption, NOTAM data) directly contradicted the market's high YES price. Market was pricing on fear narrative; Signal priced on observable facts.",
        "final_outcome_description": "Iran airspace remained open. NO resolved at 100%. Signal entered at 41.5¢ for NO (YES was at 58.5¢) and correctly identified the market was mis-pricing based on conflict narrative rather than actual airspace data.",
        "thesis_correct": 1,
        "timing_correct": 1,
        "wording_correct": 1,
        "primary_success_reason": "SOURCE_EDGE",
        "primary_failure_reason": None,
        "error_types": json.dumps([]),
        "market_understanding_score": 5,
        "source_quality_score": 5,
        "evidence_weighting_score": 5,
        "deadline_model_score": 4,
        "resolution_wording_score": 4,
        "entry_quality_score": 4,
        "exit_quality_score": 4,
        "sizing_quality_score": 3,
        "calibration_quality_score": 4,
        "overall_process_score": 4.2,
        "reusable_edge": "Aviation data (NOTAM, flight tracker, airport status) is an objective, real-time source that systematically beats market pricing driven by conflict narrative. When observable data shows OPPOSITE trend to market narrative, this is high-quality edge.",
        "non_reusable_luck": "The absence of an Israeli strike on Iran during this window helped — a strike could have triggered airspace closure. This tail risk was not fully priced in.",
        "false_confidence_source": "Minor: the conflict environment created a real (if low) risk of sudden closure that was somewhat discounted.",
        "missed_disconfirmation": "A successful Israeli strike could have forced closure. This scenario was underweighted but was genuinely low probability given the active diplomatic track.",
        "system_patch_required": "Add 'AVIATION_DATA' as a distinct source type in evidence taxonomy. NOTAM/FlightRadar24 data for airspace status markets should have contribution_score +3 by default.",
        "should_trade_similar_again": 1,
        "summary": "Excellent process. Market was pricing based on conflict-fear narrative; Signal used observable aviation data to identify the mispricing. The key insight: when a market prices a concrete, observable, trackable event based on fear narrative rather than actual data, the data has edge. This generalizes well.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 1,
            "event_probable_overall": 0,
            "event_probable_in_window": 0,
            "thesis_right_timing_wrong": 0,
            "deadline_was_edge": 0,
            "deadline_was_error_source": 0,
            "notes": "Deadline was fine. The edge was information-based, not deadline-based."
        },
        "wording": {
            "wording_clarity_score": 4.5,
            "misunderstood_wording": 0,
            "required_artifact": "official_airspace_closure_NOTAM",
            "artifact_type": "regulatory_notice",
            "notes": "Airspace closure requires an official NOTAM — verifiable and observable. Good wording clarity."
        },
        "market_type": {
            "domain": "geopolitics",
            "subdomain": "iran_conflict",
            "geography": "Iran",
            "market_type": "observable_metric",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "INEFFICIENT",
            "beatability_score": 8.0,
            "should_signal_trade_again": 1,
            "preferred_research_strategy": "Check NOTAM/FlightRadar24 for current status + ICAO notices + airline reports. Observable aviation data beats narrative pricing."
        },
        "lessons": [
            {
                "lesson_type": "SOURCE_WEIGHT",
                "lesson_text": "For infrastructure/airspace/border status markets (airports open/closed, ports active, borders crossing), real-time observable data (FlightRadar24, NOTAM databases, MarineTraffic, border crossing reports) has contribution_score +3 and should override narrative-based market pricing. If observable data and market narrative contradict, bet the data.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "Markets about observable binary infrastructure status (airspace open/closed, port active/blocked, border crossing open/closed) are systematically BEATABLE when conflict narrative inflates YES prices. These are one of Signal's highest-edge market categories.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
        ],
        "evidence": [
            {"source_title": "Imam Khomeini Airport commercial resumption (May 9)", "source_type": "primary", "stance_vs_yes": "SUPPORTS_NO", "contribution_score": 3, "caused_false_confidence": 0, "post_resolution_value": "DECISIVE"},
            {"source_title": "FlightRadar24 / Tehran FIR status", "source_type": "primary", "stance_vs_yes": "SUPPORTS_NO", "contribution_score": 3, "caused_false_confidence": 0, "post_resolution_value": "DECISIVE"},
            {"source_title": "Conflict narrative (market pricing driver)", "source_type": "market_chatter", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": -1, "was_overweighted": 0, "post_resolution_value": "NOISE"},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 1, "contribution_score": 3, "missed_critical_issue": 0},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=27: Iran agrees to end enrichment by May 31 YES @ 0.094 → NO → LOSS
    # ══════════════════════════════════════════════════════════════════════
    27: {
        "outcome_label": "LOSS",
        "process_label": "BAD_PROCESS_BAD_OUTCOME",
        "entry_price": 0.094,
        "exit_price": 0.010,
        "pnl_usd": -8.9,
        "resolution_result": "NO",
        "original_thesis": "stale_price algorithm signal. Discovery score 64.5. Active Oman-mediated talks. No substantive analysis beyond algorithm flag.",
        "market_implied_probability": 0.094,
        "signal_estimated_probability": 0.18,
        "estimated_edge": 0.086,
        "edge_types": json.dumps([]),
        "core_reason": "Algorithmic stale_price flag with no research backing. Iran enrichment agreements require full nuclear deal — months-long process.",
        "final_outcome_description": "Iran did not agree to end enrichment by May 31. Nuclear talks continued but no agreement reached. Outcome was obvious in retrospect.",
        "thesis_correct": 0,
        "timing_correct": 0,
        "wording_correct": 1,
        "primary_success_reason": None,
        "primary_failure_reason": "BAD_DEADLINE_MODEL",
        "error_types": json.dumps(["BAD_DEADLINE_MODEL", "BAD_SOURCE_SELECTION", "FALSE_CONFIDENCE", "THESIS_WRONG"]),
        "market_understanding_score": 1,
        "source_quality_score": 1,
        "evidence_weighting_score": 1,
        "deadline_model_score": 1,
        "resolution_wording_score": 3,
        "entry_quality_score": 2,
        "exit_quality_score": 2,
        "sizing_quality_score": 3,
        "calibration_quality_score": 1,
        "overall_process_score": 1.6,
        "reusable_edge": "None.",
        "non_reusable_luck": "N/A (loss).",
        "false_confidence_source": "The stale_price algorithm flagged this market as underpriced — but 9.4¢ for 'Iran agrees to END enrichment' within 10 days was not a mispricing. Iran has never agreed to end enrichment. The algorithm cannot assess geopolitical feasibility.",
        "missed_disconfirmation": "Iran's entire nuclear doctrine is built around enrichment as a sovereign right. 'Agreeing to end enrichment' = capitulation on their core position. This has never happened and requires full JCPOA-scale deal (6-12 months of negotiation minimum). 9.4¢ in 10 days was actually OVERPRICED by the market, not underpriced.",
        "system_patch_required": "HARD GATE: stale_price and cheap_optionality signals on geopolitical negotiation markets (nuclear deals, peace agreements, sanctions removal) MUST be blocked without a specific, confirmed breakthrough signal. 'Active talks' does NOT constitute a breakthrough signal for 10-30 day windows.",
        "should_trade_similar_again": 0,
        "summary": "Worst process in the V1 batch. The algorithm flagged a 'stale price' on a market where the price was actually CORRECT. Iran agreeing to end enrichment by a specific date in 10 days is essentially impossible without a pre-announced deal. This is part of the IRAN CLUSTER failure — see cluster analysis.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 0,
            "event_probable_overall": 0,
            "event_probable_in_window": 0,
            "thesis_right_timing_wrong": 0,  # thesis itself was wrong, not just timing
            "procedural_bottlenecks": "Full nuclear agreement requires: final text, legal review, Supreme Leader approval, US Congressional notification, EU coordination — minimum 3-6 months from framework",
            "deadline_was_edge": 0,
            "deadline_was_error_source": 1,
            "notes": "Signal misunderstood what was required. 'Agrees to end enrichment' is a foundational diplomatic concession, not a routine announcement."
        },
        "wording": {
            "wording_clarity_score": 3.5,
            "misunderstood_wording": 1,
            "required_artifact": "official_iranian_government_statement_ending_enrichment",
            "artifact_type": "government_statement",
            "notes": "Signal may not have fully parsed what 'agrees to end enrichment' actually requires. This is a near-maximal concession in Iranian nuclear diplomacy, not a routine announcement."
        },
        "market_type": {
            "domain": "geopolitics",
            "subdomain": "iran_nuclear",
            "geography": "Iran",
            "market_type": "diplomatic_meeting",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "VERY_EFFICIENT",
            "beatability_score": 2.0,
            "should_signal_trade_again": 0,
            "avoid_reason": "Iran nuclear concession markets with < 30-day deadlines are TRAP. These price correctly at low probabilities. The market was RIGHT. Algorithm was wrong.",
            "preferred_research_strategy": "Only trade if: specific deal text leaked/confirmed, or Iranian officials explicitly state timeline"
        },
        "lessons": [
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "HARD GATE: Do not trade YES on Iranian nuclear concession markets (end enrichment, surrender stockpile, agree to inspections) with deadlines < 60 days unless a SPECIFIC, CONFIRMED deal text or framework agreement exists. 'Active talks' is insufficient. Iran nuclear deals require: framework → legal text → domestic approval → formal signing. Minimum 3-6 months.",
                "severity": "CRITICAL",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "SOURCE_WEIGHT",
                "lesson_text": "The stale_price algorithm assigns value to markets where price hasn't moved. For geopolitical negotiation markets, PRICE STABILITY IS OFTEN CORRECT PRICING, not market inefficiency. The algorithm cannot distinguish between 'market hasn't updated on new info' and 'nothing has changed and nothing will'.",
                "severity": "HIGH",
                "should_become_gate": 1,
            },
        ],
        "evidence": [
            {"source_title": "stale_price algorithm signal (Discovery score 64.5)", "source_type": "interpretation", "stance_vs_yes": "SUPPORTS_YES", "contribution_score": -3, "caused_false_confidence": 1, "post_resolution_value": "HARMFUL", "notes": "Algorithm cannot assess whether stable price reflects market efficiency or genuine uncertainty. For Iran nuclear markets, stability = correct pricing."},
            {"source_title": "Oman-mediated talks ongoing", "source_type": "secondary", "stance_vs_yes": "NEUTRAL", "contribution_score": -1, "was_overweighted": 1, "post_resolution_value": "NOISE", "notes": "Active talks ≠ imminent resolution. Conflated 'talks happening' with 'deal possible by May 31'."},
        ],
        "modules": [
            {"module_name": "CommandG", "found_key_evidence": 0, "caused_false_confidence": 1, "missed_critical_issue": 1, "contribution_score": -3, "required_fix": "Block stale_price/cheap_optionality on Iran nuclear concession markets entirely. Add domain-specific block list."},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=35: Mojtaba Khamenei seen in public by May 31 YES @ 0.033 → NO → LOSS
    # ══════════════════════════════════════════════════════════════════════
    35: {
        "outcome_label": "LOSS",
        "process_label": "BAD_PROCESS_BAD_OUTCOME",
        "entry_price": 0.033,
        "exit_price": 0.007,
        "pnl_usd": -18.6,  # largest absolute loss: $20 stake
        "resolution_result": "NO",
        "original_thesis": "Mojtaba Khamenei is politically significant (Khamenei's son, potential successor). 3.3¢ seemed cheap. PredictIt-style speculation on public appearance of reclusive figure.",
        "market_implied_probability": 0.033,
        "signal_estimated_probability": 0.10,
        "estimated_edge": 0.067,
        "edge_types": json.dumps([]),
        "core_reason": "Low-price speculation on appearance of a historically reclusive figure. No specific intelligence about planned appearance.",
        "final_outcome_description": "Mojtaba Khamenei was NOT seen in public by May 31. No appearance. Outcome was consistent with his historical pattern of deliberate invisibility.",
        "thesis_correct": 0,
        "timing_correct": 0,
        "wording_correct": 1,
        "primary_success_reason": None,
        "primary_failure_reason": "FALSE_CONFIDENCE",
        "error_types": json.dumps(["FALSE_CONFIDENCE", "BAD_SOURCE_SELECTION", "LOW_LIQUIDITY_TRAP", "THESIS_WRONG"]),
        "market_understanding_score": 1,
        "source_quality_score": 1,
        "evidence_weighting_score": 1,
        "deadline_model_score": 3,
        "resolution_wording_score": 3,
        "entry_quality_score": 1,
        "exit_quality_score": 2,
        "sizing_quality_score": 1,
        "calibration_quality_score": 1,
        "overall_process_score": 1.4,
        "reusable_edge": "None.",
        "non_reusable_luck": "N/A (loss). Also: this was Signal's LARGEST ABSOLUTE LOSS ($18.6) despite being a 3.3¢ entry — because of oversizing on a speculative position.",
        "false_confidence_source": "The 'political significance' of Mojtaba Khamenei created narrative interest without providing any actual predictive signal about whether he would appear publicly. Signal confused 'interesting figure' with 'likely to appear.' His historical pattern is explicit: he avoids all public appearances as a deliberate political strategy.",
        "missed_disconfirmation": "Mojtaba Khamenei has not made a confirmed public appearance in years. His invisibility is a feature, not a bug — it's a deliberate political/security strategy. The 3.3¢ market price was actually GENEROUS given his historical appearance rate.",
        "system_patch_required": "HARD GATE: Do not trade 'public appearance' markets on individuals who are DELIBERATELY reclusive as a political/security strategy (e.g., potential successors, intelligence figures, individuals in witness protection, exiled leaders). Their appearance rate is near-zero by design. $20 stake on this was a sizing catastrophe.",
        "should_trade_similar_again": 0,
        "summary": "WORST PROCESS SCORE of all V1 positions (1.4/5). Three-layer error: (1) thesis had no basis — Mojtaba is deliberately invisible, (2) entry was speculative without any positive signal, (3) $20 sizing on a 3.3¢ position was the largest absolute loss of the batch. The worst outcome is that this was paper money, but the mental model it represents (narrative interest → actionable signal) is dangerous.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 1,
            "event_probable_overall": 0,
            "event_probable_in_window": 0,
            "thesis_right_timing_wrong": 0,
            "deadline_was_edge": 0,
            "deadline_was_error_source": 0,
            "notes": "Deadline was fine. Thesis was fundamentally wrong."
        },
        "wording": {
            "wording_clarity_score": 3.5,
            "misunderstood_wording": 0,
            "required_artifact": "confirmed_photo_or_video_of_public_appearance",
            "artifact_type": "media_evidence",
            "notes": "Wording was clear but what constitutes 'public appearance' vs private visit needed clarification."
        },
        "market_type": {
            "domain": "geopolitics",
            "subdomain": "iran_politics",
            "geography": "Iran",
            "market_type": "observable_metric",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "VERY_EFFICIENT",
            "beatability_score": 1.5,
            "should_signal_trade_again": 0,
            "avoid_reason": "Appearance markets on deliberately reclusive figures are near-zero probability. Price is CORRECT at 3¢. Do not trade.",
            "preferred_research_strategy": "Only trade if: specific confirmed event scheduled where target must appear"
        },
        "lessons": [
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "HARD GATE: Do not trade 'public appearance' markets on individuals who are deliberately reclusive by design (political successors, intelligence figures, exiled figures, security-sensitive individuals). Their historical appearance rate = their market probability. 3¢ on Mojtaba Khamenei = correct pricing.",
                "severity": "CRITICAL",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "SIZING",
                "lesson_text": "Signal's LARGEST ABSOLUTE LOSS came from OVERSIZING a speculative position. $20 on a 3.3¢ market = $20 at risk for $60 potential payout. This is not edge-proportional sizing. For markets where Signal has no specific intelligence, size should be $5-10 maximum regardless of perceived cheapness.",
                "severity": "CRITICAL",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "SOURCE_WEIGHT",
                "lesson_text": "'Political significance' of a target is NOT evidence they will appear publicly. Signal confused narrative interest (Mojtaba IS important) with operational signal (Mojtaba WILL appear). These are entirely different claims. Always require a specific positive trigger before entering appearance markets.",
                "severity": "HIGH",
                "should_become_gate": 0,
            },
        ],
        "evidence": [
            {"source_title": "Mojtaba Khamenei political significance narrative", "source_type": "interpretation", "stance_vs_yes": "NEUTRAL", "contribution_score": -2, "caused_false_confidence": 1, "post_resolution_value": "NOISE", "notes": "Political significance ≠ likelihood of public appearance. These are uncorrelated."},
        ],
        "modules": [
            {"module_name": "Manual", "found_key_evidence": 0, "caused_false_confidence": 1, "missed_critical_issue": 1, "contribution_score": -3, "required_fix": "Add hard block on appearance markets for deliberately reclusive figures. Add max-size rule for speculative positions."},
        ],
    },

    # ══════════════════════════════════════════════════════════════════════
    # ID=36: Iran agrees to surrender uranium stockpile by May 31 YES @ 0.064 → NO → LOSS
    # ══════════════════════════════════════════════════════════════════════
    36: {
        "outcome_label": "LOSS",
        "process_label": "BAD_PROCESS_BAD_OUTCOME",
        "entry_price": 0.064,
        "exit_price": 0.011,
        "pnl_usd": -9.1,
        "resolution_result": "NO",
        "original_thesis": "$1.8M volume market — biggest in the queue. Active Oman-mediated US-Iran nuclear negotiations. Iran's 20% enriched uranium stockpile. Signal estimated edge from narrative momentum.",
        "market_implied_probability": 0.064,
        "signal_estimated_probability": 0.18,
        "estimated_edge": 0.116,
        "edge_types": json.dumps(["NARRATIVE_ASYMMETRY_EDGE"]),
        "core_reason": "Large market + active negotiations interpreted as signal of underpriced probability. No specific deal-breaking evidence.",
        "final_outcome_description": "Iran did NOT surrender uranium stockpile by May 31. No deal reached. Stockpile continues to grow. Outcome matches all historical base rates.",
        "thesis_correct": 0,
        "timing_correct": 0,
        "wording_correct": 1,
        "primary_success_reason": None,
        "primary_failure_reason": "BAD_DEADLINE_MODEL",
        "error_types": json.dumps(["BAD_DEADLINE_MODEL", "THESIS_WRONG", "FALSE_CONFIDENCE", "OVERWEIGHTED_NOISE"]),
        "market_understanding_score": 2,
        "source_quality_score": 2,
        "evidence_weighting_score": 1,
        "deadline_model_score": 1,
        "resolution_wording_score": 4,
        "entry_quality_score": 2,
        "exit_quality_score": 2,
        "sizing_quality_score": 3,
        "calibration_quality_score": 1,
        "overall_process_score": 1.9,
        "reusable_edge": "None. This is structurally identical to ID=27 (Iran ends enrichment). Both are Iran nuclear concession markets with 10-day windows.",
        "non_reusable_luck": "N/A (loss).",
        "false_confidence_source": "Large volume ($1.8M) was interpreted as evidence of market interest → Signal confused 'high trading volume' with 'legitimate probability of outcome.' High volume on an Iran nuclear market reflects UNCERTAINTY and NARRATIVE INTEREST, not underlying probability of concession.",
        "missed_disconfirmation": "Iran surrendering its enriched uranium stockpile is even MORE extreme than ending enrichment (ID=27). The stockpile is a strategic asset and bargaining chip. Iran surrendered it once under JCPOA (2015) but that required: 18 months of negotiations, P5+1 framework, sanctions relief package, IAEA verification protocol. None of these existed in May 2026.",
        "system_patch_required": "PART OF IRAN NUCLEAR CLUSTER — same gate as ID=27. Additionally: High market volume does NOT indicate edge. A $1.8M market on Iran uranium surrender is large because it's newsworthy, not because it's likely. Volume ≠ probability signal.",
        "should_trade_similar_again": 0,
        "summary": "Structurally identical error to ID=27. The IRAN NUCLEAR CLUSTER (IDs 27, 36, and partially 2) represents Signal's biggest systematic failure pattern in V1: conflating 'active diplomacy + narrative momentum' with 'near-term resolution probability.' Iran nuclear diplomacy operates on 6-18 month cycles, not 10-day windows. Market volume was not an edge signal.",

        "deadline": {
            "deadline_type": "HARD",
            "deadline_clearly_modeled": 0,
            "event_probable_overall": 0,
            "event_probable_in_window": 0,
            "thesis_right_timing_wrong": 0,
            "procedural_bottlenecks": "Full JCPOA-style agreement required: P5+1/US framework, sanctions relief package, IAEA verification, Iranian domestic politics, Supreme Leader approval",
            "deadline_was_edge": 0,
            "deadline_was_error_source": 1,
            "notes": "Signal did not model what 'surrendering uranium stockpile' actually requires. This is not a routine announcement — it requires full deal infrastructure that takes months."
        },
        "wording": {
            "wording_clarity_score": 4.0,
            "misunderstood_wording": 0,
            "required_artifact": "official_IAEA_verified_transfer_or_dilution",
            "artifact_type": "international_treaty_compliance",
            "notes": "Wording was clear. 'Surrender' requires verified physical transfer or dilution, not just announcement."
        },
        "market_type": {
            "domain": "geopolitics",
            "subdomain": "iran_nuclear",
            "geography": "Iran",
            "market_type": "diplomatic_meeting",
            "deadline_type": "CALENDAR",
            "efficiency_estimate": "VERY_EFFICIENT",
            "beatability_score": 2.0,
            "should_signal_trade_again": 0,
            "avoid_reason": "Iran nuclear physical compliance markets (uranium transfer, enrichment halt, inspection access) with < 60-day windows. Price at 6¢ was CORRECT — this belongs to the same blocked category as ID=27.",
            "preferred_research_strategy": "Only trade if confirmed deal framework signed AND specific IAEA transfer schedule announced"
        },
        "lessons": [
            {
                "lesson_type": "SOURCE_WEIGHT",
                "lesson_text": "High trading volume on a market is NOT a signal of legitimate probability. A $1.8M volume Iran nuclear market reflects: newsworthiness + retail speculation + narrative momentum. None of these are predictive of actual outcome. Do not use 'large market' as a reason to enter — use it as a reason to INCREASE scrutiny.",
                "severity": "HIGH",
                "should_become_gate": 1,
            },
            {
                "lesson_type": "MARKET_SELECTION",
                "lesson_text": "CLUSTER GATE: ID=27 and ID=36 are the same error type. When Signal has already entered one Iran nuclear concession market, it should NOT enter a second one with the same directional thesis unless the first position was predicated on differentiated evidence. Cluster exposure amplifies losses on correlated failures.",
                "severity": "CRITICAL",
                "should_become_gate": 1,
            },
        ],
        "evidence": [
            {"source_title": "Market volume: $1.8M", "source_type": "market_chatter", "stance_vs_yes": "NEUTRAL", "contribution_score": -1, "caused_false_confidence": 1, "post_resolution_value": "NOISE", "notes": "Volume = narrative interest, not probability signal."},
            {"source_title": "Oman-mediated talks ongoing", "source_type": "secondary", "stance_vs_yes": "NEUTRAL", "contribution_score": -1, "was_overweighted": 1, "post_resolution_value": "NOISE"},
        ],
        "modules": [
            {"module_name": "CommandG", "found_key_evidence": 0, "caused_false_confidence": 1, "missed_critical_issue": 1, "contribution_score": -2, "required_fix": "Block ALL Iran nuclear concession markets without specific deal framework. Add correlated position check."},
        ],
    },
}

# ── IRAN CLUSTER META-ANALYSIS ─────────────────────────────────────────────
# IDs 2, 27, 36 share a common failure mode: "active diplomacy/military prep
# + narrative momentum" interpreted as near-term resolution signal.
# This cluster analysis is stored via generate_cluster_analysis().
IRAN_CLUSTER_META = {
    "cluster_name": "IRAN_NARRATIVE_TRAP",
    "position_ids": [2, 27, 36],
    "total_loss": -26.3,
    "common_failure": "All three positions entered on 'active [military/diplomatic] engagement' without modeling the required procedural steps for resolution. Each event (ground op, end enrichment, surrender stockpile) requires 30-90+ days of confirmed process that Signal did not verify existed.",
    "root_cause": "Signal conflated 'situation is active' with 'resolution is near.' In geopolitics, active engagement is the NORMAL STATE — it does not predict specific near-term resolution.",
    "generalizable_rule": "GATE: For geopolitical action markets (military strikes, diplomatic agreements, treaty compliance), Signal must identify the SPECIFIC CONFIRMED PROCEDURAL PATH to resolution before entry. 'Active talks/prep' is NOT a procedural path — it is background noise. The question is not 'is this being discussed?' but 'what specific event must occur and is that event confirmed to be in motion?'",
}

# ── Additional resolved positions placeholder ──────────────────────────────


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    db.row_factory = sqlite3.Row
    _run_migration(db)
    return db


def _run_migration(db: sqlite3.Connection) -> None:
    """Apply learning tables migration if not already applied."""
    migration_path = os.path.join(ROOT_DIR, "migrations", "002_postmortem_learning.sql")
    if not os.path.exists(migration_path):
        print("[L] Warning: migration file not found at", migration_path)
        return
    # Check if already applied
    existing = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "position_postmortems" in existing:
        return  # Already applied
    print("[L] Applying migration 002_postmortem_learning.sql...")
    with open(migration_path, "r", encoding="utf-8") as f:
        sql = f.read()
    db.executescript(sql)
    db.commit()
    print("[L] Migration applied.")


def process_position(position_id: int, db: sqlite3.Connection, force: bool = False) -> bool:
    """
    Process a single position through the full post-mortem framework.
    Returns True if processed, False if skipped.
    """
    # Check if already processed
    existing = db.execute(
        "SELECT id FROM position_postmortems WHERE position_id=?", (position_id,)
    ).fetchone()
    if existing and not force:
        print(f"[L] Position {position_id} already processed (id={existing['id']}). Use --force to reprocess.")
        return False

    # Get position data
    pos = db.execute("""
        SELECT p.*, m.question, m.slug
        FROM positions p
        LEFT JOIN markets m ON m.condition_id = p.condition_id
        WHERE p.id = ?
    """, (position_id,)).fetchone()

    if not pos:
        print(f"[L] Position {position_id} not found.")
        return False

    pos = dict(pos)
    question = pos.get('question') or pos.get('condition_id','?')[:60]
    print(f"\n{'='*70}")
    print(f"[L] Processing post-mortem for Position {position_id}")
    print(f"    {question[:65]}")
    print(f"    {pos.get('intended_side')} @ {pos.get('intended_entry_price')} | status={pos.get('status')}")
    print(f"{'='*70}")

    # Get pre-filled data if available
    pm_data = POSTMORTEMS_V1.get(position_id)
    if not pm_data:
        print(f"[L] No pre-filled postmortem for position {position_id}. Creating skeleton...")
        pm_data = _create_skeleton(pos)

    now_iso = datetime.now(timezone.utc).isoformat()

    # ── Insert main postmortem ─────────────────────────────────────────────
    if existing and force:
        db.execute("DELETE FROM position_postmortems WHERE position_id=?", (position_id,))

    cursor = db.execute("""
        INSERT INTO position_postmortems (
            position_id, market_question, market_slug, condition_id,
            outcome_label, entry_price, exit_price, pnl_usd, resolution_result,
            process_label, original_thesis, market_implied_probability,
            signal_estimated_probability, estimated_edge, edge_types, core_reason,
            final_outcome_description, thesis_correct, timing_correct, wording_correct,
            primary_success_reason, primary_failure_reason, error_types,
            market_understanding_score, source_quality_score, evidence_weighting_score,
            deadline_model_score, resolution_wording_score, entry_quality_score,
            exit_quality_score, sizing_quality_score, calibration_quality_score,
            overall_process_score,
            reusable_edge, non_reusable_luck, false_confidence_source,
            missed_disconfirmation, system_patch_required,
            should_trade_similar_again, summary, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        position_id,
        question[:200],
        pos.get('slug',''),
        pos.get('condition_id',''),
        pm_data.get('outcome_label'),
        pm_data.get('entry_price', pos.get('intended_entry_price')),
        pm_data.get('exit_price'),
        pm_data.get('pnl_usd'),
        pm_data.get('resolution_result'),
        pm_data.get('process_label'),
        pm_data.get('original_thesis'),
        pm_data.get('market_implied_probability'),
        pm_data.get('signal_estimated_probability'),
        pm_data.get('estimated_edge'),
        pm_data.get('edge_types'),
        pm_data.get('core_reason'),
        pm_data.get('final_outcome_description'),
        pm_data.get('thesis_correct'),
        pm_data.get('timing_correct'),
        pm_data.get('wording_correct'),
        pm_data.get('primary_success_reason'),
        pm_data.get('primary_failure_reason'),
        pm_data.get('error_types'),
        pm_data.get('market_understanding_score'),
        pm_data.get('source_quality_score'),
        pm_data.get('evidence_weighting_score'),
        pm_data.get('deadline_model_score'),
        pm_data.get('resolution_wording_score'),
        pm_data.get('entry_quality_score'),
        pm_data.get('exit_quality_score'),
        pm_data.get('sizing_quality_score'),
        pm_data.get('calibration_quality_score'),
        pm_data.get('overall_process_score'),
        pm_data.get('reusable_edge'),
        pm_data.get('non_reusable_luck'),
        pm_data.get('false_confidence_source'),
        pm_data.get('missed_disconfirmation'),
        pm_data.get('system_patch_required'),
        pm_data.get('should_trade_similar_again'),
        pm_data.get('summary'),
        now_iso, now_iso,
    ))
    pm_id = cursor.lastrowid
    db.commit()

    # ── Insert probability calibration ─────────────────────────────────────
    res = pm_data.get('resolution_result', '')
    final_p = 1.0 if res == 'YES' else 0.0 if res == 'NO' else None
    signal_p = pm_data.get('signal_estimated_probability')
    entry_p  = pm_data.get('entry_price', pos.get('intended_entry_price'))
    brier = (signal_p - final_p) ** 2 if (signal_p is not None and final_p is not None) else None

    db.execute("""
        INSERT INTO probability_calibration
        (position_id, postmortem_id, condition_id, selected_side,
         market_price_entry, market_implied_probability, signal_probability, edge_estimate,
         final_resolution, brier_score, calibration_bucket,
         was_overconfident, was_underconfident, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        position_id, pm_id, pos.get('condition_id'),
        pos.get('intended_side'),
        entry_p,
        pm_data.get('market_implied_probability'),
        signal_p,
        pm_data.get('estimated_edge'),
        res,
        brier,
        _calibration_bucket(signal_p) if signal_p else None,
        1 if pm_data.get('was_overconfident') else (
            1 if signal_p and final_p is not None and signal_p > 0.7 and final_p == 0.0 else 0),
        0,
        pm_data.get('summary','')[:200],
        now_iso,
    ))

    # ── Insert deadline audit ──────────────────────────────────────────────
    if 'deadline' in pm_data:
        d = pm_data['deadline']
        db.execute("""
            INSERT INTO deadline_audit
            (position_id, postmortem_id, condition_id, deadline_date,
             deadline_type, deadline_clearly_modeled,
             event_probable_overall, event_probable_in_window,
             thesis_right_timing_wrong, procedural_bottlenecks,
             deadline_was_edge, deadline_was_error_source, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (position_id, pm_id, pos.get('condition_id'),
              pos.get('end_date'),
              d.get('deadline_type'), d.get('deadline_clearly_modeled'),
              d.get('event_probable_overall'), d.get('event_probable_in_window'),
              d.get('thesis_right_timing_wrong'), d.get('procedural_bottlenecks'),
              d.get('deadline_was_edge'), d.get('deadline_was_error_source'),
              d.get('notes'), now_iso))

    # ── Insert wording audit ───────────────────────────────────────────────
    if 'wording' in pm_data:
        w = pm_data['wording']
        db.execute("""
            INSERT INTO resolution_wording_audit
            (position_id, postmortem_id, condition_id, wording_text,
             required_artifact, artifact_type, wording_clarity_score,
             misunderstood_wording, final_resolution_reason, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (position_id, pm_id, pos.get('condition_id'),
              question[:300],
              w.get('required_artifact'), w.get('artifact_type'),
              w.get('wording_clarity_score'), w.get('misunderstood_wording'),
              pm_data.get('final_outcome_description','')[:300],
              w.get('notes'), now_iso))

    # ── Insert market type learning ────────────────────────────────────────
    if 'market_type' in pm_data:
        mt = pm_data['market_type']
        db.execute("""
            INSERT INTO market_type_learning
            (position_id, postmortem_id, condition_id, domain, subdomain,
             geography, market_type, deadline_type, efficiency_estimate,
             beatability_score, should_signal_trade_again,
             preferred_research_strategy, avoid_reason, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (position_id, pm_id, pos.get('condition_id'),
              mt.get('domain'), mt.get('subdomain'), mt.get('geography'),
              mt.get('market_type'), mt.get('deadline_type'),
              mt.get('efficiency_estimate'), mt.get('beatability_score'),
              mt.get('should_signal_trade_again'),
              mt.get('preferred_research_strategy'),
              mt.get('avoid_reason'), mt.get('notes',''), now_iso))

    # ── Insert lessons ─────────────────────────────────────────────────────
    for lesson in pm_data.get('lessons', []):
        db.execute("""
            INSERT INTO learning_lessons
            (position_id, postmortem_id, lesson_type, lesson_text,
             severity, should_become_gate, should_update_prompt, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (position_id, pm_id,
              lesson.get('lesson_type'), lesson.get('lesson_text'),
              lesson.get('severity'), lesson.get('should_become_gate', 0),
              lesson.get('should_update_prompt', 0), now_iso))

    # ── Insert gate updates from lessons ──────────────────────────────────
    for lesson in pm_data.get('lessons', []):
        if lesson.get('should_become_gate'):
            db.execute("""
                INSERT INTO gate_updates
                (source_position_id, source_postmortem_id, gate_name,
                 gate_description, severity, active, created_at)
                VALUES (?,?,?,?,?,0,?)
            """, (position_id, pm_id,
                  f"GATE_FROM_POS{position_id}_{lesson.get('lesson_type','')}",
                  lesson.get('lesson_text','')[:500],
                  lesson.get('severity','MEDIUM'), now_iso))

    # ── Insert evidence ────────────────────────────────────────────────────
    for ev in pm_data.get('evidence', []):
        db.execute("""
            INSERT INTO evidence_yield_ledger
            (position_id, postmortem_id, condition_id, source_title, source_type,
             stance_vs_yes, contribution_score, caused_false_confidence,
             post_resolution_value, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (position_id, pm_id, pos.get('condition_id'),
              ev.get('source_title'), ev.get('source_type'),
              ev.get('stance_vs_yes'), ev.get('contribution_score', 0),
              ev.get('caused_false_confidence', 0),
              ev.get('post_resolution_value'), ev.get('notes',''), now_iso))

    # ── Insert module attribution ──────────────────────────────────────────
    for mod in pm_data.get('modules', []):
        db.execute("""
            INSERT INTO module_attribution
            (position_id, postmortem_id, condition_id, module_name,
             found_key_evidence, caused_false_confidence, missed_critical_issue,
             contribution_score, required_fix, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (position_id, pm_id, pos.get('condition_id'),
              mod.get('module_name'), mod.get('found_key_evidence', 0),
              mod.get('caused_false_confidence', 0), mod.get('missed_critical_issue', 0),
              mod.get('contribution_score', 0), mod.get('required_fix',''), now_iso))

    db.commit()

    # Print summary
    _print_postmortem_summary(position_id, pm_data, pm_id)
    return True


def _calibration_bucket(p: float) -> str:
    if p is None: return "unknown"
    for lo, hi in [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]:
        if lo <= p < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return f"{p:.2f}"


def _create_skeleton(pos: dict) -> dict:
    """Create a minimal skeleton postmortem for positions without pre-filled data."""
    return {
        "outcome_label": "UNKNOWN",
        "process_label": "UNCLEAR_PROCESS",
        "entry_price": pos.get('intended_entry_price') or pos.get('yes_equivalent_entry'),
        "exit_price": None,
        "pnl_usd": None,
        "resolution_result": "UNKNOWN",
        "original_thesis": pos.get('thesis_snapshot_text', '')[:500] if pos.get('thesis_snapshot_text') else "Thesis not recorded",
        "market_implied_probability": pos.get('intended_entry_price'),
        "signal_estimated_probability": None,
        "estimated_edge": None,
        "edge_types": json.dumps([]),
        "core_reason": "To be filled",
        "final_outcome_description": "Awaiting resolution",
        "summary": f"Skeleton postmortem for position {pos.get('id')}. Needs manual completion.",
        "should_trade_similar_again": None,
        "lessons": [],
        "evidence": [],
        "modules": [],
    }


def _print_postmortem_summary(position_id: int, pm: dict, pm_id: int):
    emoji = "✅" if pm.get('outcome_label') in ('WIN','EARLY_EXIT_GOOD','PARTIAL_WIN') else "❌"
    print(f"\n  {emoji} Post-mortem recorded (id={pm_id})")
    print(f"  Outcome: {pm.get('outcome_label')} | Process: {pm.get('process_label')}")
    print(f"  PnL: ${pm.get('pnl_usd',0) or 0:+.2f} | Process score: {pm.get('overall_process_score') or '?'}/5")
    print(f"  Primary reason: {pm.get('primary_success_reason') or pm.get('primary_failure_reason') or '?'}")
    print(f"  Lessons: {len(pm.get('lessons',[]))} | Gates: {sum(1 for l in pm.get('lessons',[]) if l.get('should_become_gate'))}")


def generate_aggregate_snapshot(db: sqlite3.Connection) -> None:
    """Generate aggregate learning snapshot from all postmortems."""
    print(f"\n{'='*70}")
    print(" SIGNAL V1 — AGGREGATE LEARNING SNAPSHOT")
    print(f"{'='*70}")

    pms = db.execute("""
        SELECT pm.*, p.intended_side, p.opened_at
        FROM position_postmortems pm
        JOIN positions p ON p.id = pm.position_id
    """).fetchall()

    if not pms:
        print("No postmortems found.")
        return

    total = len(pms)
    wins = sum(1 for p in pms if p['outcome_label'] in ('WIN','EARLY_EXIT_GOOD','PARTIAL_WIN'))
    losses = sum(1 for p in pms if p['outcome_label'] in ('LOSS','EARLY_EXIT_BAD','PARTIAL_LOSS'))
    good_process = sum(1 for p in pms if p['process_label'] and 'GOOD_PROCESS' in p['process_label'])
    bad_process = sum(1 for p in pms if p['process_label'] and 'BAD_PROCESS' in p['process_label'])
    total_pnl = sum(p['pnl_usd'] or 0 for p in pms)
    avg_score = sum(p['overall_process_score'] or 0 for p in pms) / total if total else 0

    print(f"\n  Closed positions reviewed: {total}")
    print(f"  ✅ Wins: {wins} | ❌ Losses: {losses}")
    print(f"  GOOD process: {good_process} | BAD process: {bad_process}")
    print(f"  Total PnL: ${total_pnl:+.2f}")
    print(f"  Avg process score: {avg_score:.2f}/5.0")

    # Process label breakdown
    print(f"\n  PROCESS BREAKDOWN:")
    for label in PROCESS_LABELS:
        n = sum(1 for p in pms if p['process_label'] == label)
        if n > 0:
            bar = "█" * n
            print(f"    {label:35s}: {bar} ({n})")

    # Calibration
    calib = db.execute("""
        SELECT AVG(brier_score) as avg_brier, COUNT(*) as n
        FROM probability_calibration WHERE brier_score IS NOT NULL
    """).fetchone()
    if calib and calib['avg_brier']:
        print(f"\n  CALIBRATION:")
        print(f"    Average Brier score: {calib['avg_brier']:.4f} (lower=better, random=0.25)")
        skill = 0.25 - calib['avg_brier']
        print(f"    Skill score vs random: {skill:+.4f} ({'better' if skill > 0 else 'worse'} than random)")

    # Error types
    all_errors = []
    for pm in pms:
        if pm['error_types']:
            try: all_errors.extend(json.loads(pm['error_types']))
            except: pass
    if all_errors:
        from collections import Counter
        ec = Counter(all_errors)
        print(f"\n  TOP ERROR TYPES:")
        for err, cnt in ec.most_common(5):
            print(f"    {err}: {cnt}")

    # Lessons
    lessons = db.execute("SELECT lesson_type, severity, should_become_gate FROM learning_lessons").fetchall()
    gates = [l for l in lessons if l['should_become_gate']]
    critical = [l for l in lessons if l['severity'] == 'CRITICAL']

    print(f"\n  LESSONS: {len(lessons)} total | {len(gates)} new gates | {len(critical)} critical")

    # Market type performance
    mt = db.execute("""
        SELECT domain, COUNT(*) as n,
               SUM(CASE WHEN pm.outcome_label IN ('WIN','EARLY_EXIT_GOOD','PARTIAL_WIN') THEN 1 ELSE 0 END) as wins
        FROM market_type_learning mtl
        JOIN position_postmortems pm ON pm.id = mtl.postmortem_id
        GROUP BY domain ORDER BY n DESC
    """).fetchall()
    if mt:
        print(f"\n  MARKET DOMAIN PERFORMANCE:")
        for r in mt:
            wr = r['wins'] / r['n'] if r['n'] else 0
            print(f"    {r['domain']:20s}: {r['wins']}/{r['n']} wins ({wr*100:.0f}%)")

    # Key gates to implement
    print(f"\n  🚨 CRITICAL GATES TO IMPLEMENT:")
    gate_lessons = db.execute("""
        SELECT lesson_text, severity, lesson_type
        FROM learning_lessons
        WHERE should_become_gate=1 AND severity IN ('CRITICAL','HIGH')
        ORDER BY severity DESC
    """).fetchall()
    for i, gl in enumerate(gate_lessons[:5], 1):
        print(f"\n  Gate {i} [{gl['severity']}] ({gl['lesson_type']}):")
        print(f"    {gl['lesson_text'][:150]}")

    # Store snapshot
    top_fixes = json.dumps([gl['lesson_text'][:100] for gl in gate_lessons[:5]])
    best_error = Counter(all_errors).most_common(1)[0][0] if all_errors else None

    db.execute("""
        INSERT INTO learning_snapshots
        (snapshot_date, total_closed_positions, good_process_count, bad_process_count,
         profitable_count, unprofitable_count, avg_process_score,
         worst_error_type, top_system_fixes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now(timezone.utc).date().isoformat(),
        total, good_process, bad_process, wins, losses,
        round(avg_score, 2), best_error, top_fixes,
        datetime.now(timezone.utc).isoformat()
    ))
    db.commit()
    print(f"\n  Snapshot saved to learning_snapshots.")


def list_postmortems(db: sqlite3.Connection) -> None:
    """List all recorded postmortems."""
    pms = db.execute("""
        SELECT pm.id, pm.position_id, pm.market_question, pm.outcome_label,
               pm.process_label, pm.overall_process_score, pm.pnl_usd, pm.created_at
        FROM position_postmortems pm ORDER BY pm.position_id
    """).fetchall()

    print(f"\n{'='*70}")
    print(f" POST-MORTEMS ({len(pms)} recorded)")
    print(f"{'='*70}")
    for pm in pms:
        emoji = "✅" if pm['outcome_label'] in ('WIN','EARLY_EXIT_GOOD') else "❌" if pm['outcome_label'] in ('LOSS','EARLY_EXIT_BAD') else "⚠️"
        print(f"\n  {emoji} PM#{pm['id']} → Pos#{pm['position_id']} | {pm['outcome_label']} | score={pm['overall_process_score'] or '?'}/5")
        print(f"     {(pm['market_question'] or '')[:65]}")
        print(f"     {pm['process_label']} | pnl=${pm['pnl_usd'] or 0:+.2f} | {pm['created_at'][:10]}")


def main():
    parser = argparse.ArgumentParser(description="Command L — Signal Post-Mortem Learning")
    parser.add_argument("--id",       type=int, help="Process single position ID")
    parser.add_argument("--batch",    action="store_true", help="Process all V1 closed positions + snapshot")
    parser.add_argument("--snapshot", action="store_true", help="Generate aggregate snapshot only")
    parser.add_argument("--list",     action="store_true", help="List all postmortems")
    parser.add_argument("--force",    action="store_true", help="Reprocess even if already done")
    args = parser.parse_args()

    db = get_db()

    if args.list:
        list_postmortems(db)

    elif args.id:
        process_position(args.id, db, force=args.force)
        generate_aggregate_snapshot(db)

    elif args.snapshot:
        generate_aggregate_snapshot(db)

    elif args.batch:
        # Process all V1 closed positions
        positions_to_process = sorted(POSTMORTEMS_V1.keys())
        print(f"\n[L] Processing {len(positions_to_process)} Signal V1 positions...")
        processed = 0
        for pid in positions_to_process:
            if process_position(pid, db, force=args.force):
                processed += 1
        print(f"\n[L] Processed {processed}/{len(positions_to_process)} positions.")
        generate_aggregate_snapshot(db)

    else:
        # Default: process all that haven't been done yet
        processed = 0
        for pid in sorted(POSTMORTEMS_V1.keys()):
            if process_position(pid, db, force=False):
                processed += 1
        if processed:
            generate_aggregate_snapshot(db)
        else:
            print("[L] All pre-filled postmortems already processed. Use --force to reprocess.")
            list_postmortems(db)

    db.close()


if __name__ == "__main__":
    main()
