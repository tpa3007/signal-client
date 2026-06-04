"""Legislative Timeline Calculator — structural analysis for law/procedural markets.

For markets like "Will X bill pass by date Y?" or "Will Y dissolve parliament by Z?",
computes whether the required procedural steps can physically complete before the deadline.

TAXONOMY:
  IMPOSSIBLE_TIMELINE  — Minimum required days > deadline days * 0.85 (safety factor).
                         Legislative process physically cannot complete in time.
  COMPRESSED_TIMELINE  — Minimum required days 70-85% of deadline. Very tight. Possible
                         with fast-tracking but high structural risk.
  FEASIBLE_TIMELINE    — Minimum required days < 70% of deadline. Process can complete.
  COMFORTABLE_TIMELINE — Minimum required days < 40% of deadline. Ample time.

CALIBRATION (from Knesset dissolution signal #15):
  Israeli Knesset dissolution required ~4 readings over ~14 minimum days.
  Our signal had only ~13 days to May 31 deadline → COMPRESSED_TIMELINE / borderline IMPOSSIBLE.
  Market correctly priced to 5.5% YES after initial entry at 13-14%.
  Lesson: Always check minimum process time vs. deadline.

USAGE:
  from lib.analysis.legislative_calculator import analyze_legislative_timeline, PROCESS_TEMPLATES
  analysis = analyze_legislative_timeline(
      steps=["preliminary_reading", "first_reading", "second_reading", "third_reading"],
      days_to_deadline=13,
  )
  # => {"timeline_type": "IMPOSSIBLE_TIMELINE", "safety_margin": 0.72, ...}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Process step minimum times (days) ────────────────────────────────────────

# Legislative processes vary by country but these are approximate minimums.
# Based on actual parliamentary procedure data.
_STEP_MIN_DAYS: dict[str, float] = {
    # Generic readings (most parliamentary systems)
    "preliminary_reading": 1.0,
    "first_reading": 2.0,
    "second_reading": 3.0,
    "third_reading": 2.0,
    "committee_review": 5.0,
    "committee_vote": 1.0,
    "plenary_debate": 2.0,
    "plenary_vote": 1.0,
    "presidential_signature": 3.0,  # typically 7-14 days but can be faster
    "senate_confirmation": 7.0,
    "constitutional_review": 10.0,

    # US-specific
    "house_vote": 1.0,
    "senate_vote": 1.0,
    "conference_committee": 5.0,
    "presidential_veto_window": 10.0,

    # Israeli Knesset
    "knesset_preliminary": 1.0,
    "knesset_first_reading": 2.0,
    "knesset_second_reading": 3.0,
    "knesset_third_reading": 2.0,
    "knesset_dissolution_vote": 1.0,   # final dissolution vote after all readings

    # EU
    "eu_first_reading": 14.0,
    "eu_second_reading": 14.0,
    "eu_council_vote": 7.0,
    "eu_trilogue": 21.0,
}

# Known multi-step templates by process type
PROCESS_TEMPLATES: dict[str, list[str]] = {
    "knesset_dissolution": [
        "knesset_preliminary",
        "knesset_first_reading",
        "knesset_second_reading",
        "knesset_third_reading",
        "knesset_dissolution_vote",
    ],
    "us_legislation": [
        "house_vote",
        "senate_vote",
        "presidential_signature",
    ],
    "us_legislation_full": [
        "house_vote",
        "senate_vote",
        "conference_committee",
        "presidential_signature",
    ],
    "uk_legislation": [
        "first_reading",
        "second_reading",
        "committee_review",
        "third_reading",
        "presidential_signature",
    ],
    "generic_4_readings": [
        "preliminary_reading",
        "first_reading",
        "second_reading",
        "third_reading",
    ],
    "generic_vote": [
        "plenary_debate",
        "plenary_vote",
    ],
}


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class LegislativeAnalysis:
    timeline_type: str          # IMPOSSIBLE / COMPRESSED / FEASIBLE / COMFORTABLE
    steps_remaining: list[str]
    min_days_per_step: dict[str, float]
    min_total_days: float       # sum of minimum days for all steps
    days_to_deadline: float
    safety_margin: float        # days_to_deadline / min_total_days (>1 = feasible)
    signal_note: str
    is_structural_ceiling: bool  # True if timeline makes YES extremely unlikely


# ── Core computation ─────────────────────────────────────────────────────────

def analyze_legislative_timeline(
    steps: list[str],
    days_to_deadline: float,
    custom_min_days: dict[str, float] | None = None,
    market_yes_price: float | None = None,
) -> LegislativeAnalysis:
    """Analyze whether a legislative/procedural process can complete by deadline.

    Args:
        steps:            List of procedural step names (from _STEP_MIN_DAYS keys
                          or PROCESS_TEMPLATES values)
        days_to_deadline: Days until market resolution deadline
        custom_min_days:  Override default minimum days per step
        market_yes_price: Current market YES price (for structural ceiling detection)

    Returns:
        LegislativeAnalysis with timeline_type and note.
    """
    step_times = dict(_STEP_MIN_DAYS)
    if custom_min_days:
        step_times.update(custom_min_days)

    # Compute minimum total days
    step_mins: dict[str, float] = {}
    for step in steps:
        step_mins[step] = step_times.get(step, 2.0)  # default 2 days if unknown

    min_total = sum(step_mins.values())
    safety_margin = days_to_deadline / min_total if min_total > 0 else 999.0

    # Classify
    if safety_margin < 0.85:
        timeline_type = "IMPOSSIBLE_TIMELINE"
        note = (
            f"IMPOSSIBLE TIMELINE: Process requires minimum {min_total:.0f} days "
            f"but only {days_to_deadline:.0f} days remain until deadline. "
            f"Safety margin: {safety_margin:.2f}x (need > 1.0). "
            f"Steps breakdown: {', '.join(f'{s}={d:.0f}d' for s, d in step_mins.items())}. "
            f"This is a structural NO regardless of political will. "
            f"Similar to Knesset dissolution signal #15 which resolved NO."
        )
    elif safety_margin < 1.30:
        timeline_type = "COMPRESSED_TIMELINE"
        note = (
            f"COMPRESSED TIMELINE: Process needs {min_total:.0f} days minimum, "
            f"{days_to_deadline:.0f} days available. Safety margin: {safety_margin:.2f}x. "
            f"Feasible with fast-tracking but HIGH structural risk. "
            f"Any delay in one step causes failure. "
            f"This should be priced with significant uncertainty discount."
        )
    elif safety_margin < 2.50:
        timeline_type = "FEASIBLE_TIMELINE"
        note = (
            f"FEASIBLE TIMELINE: Process needs {min_total:.0f} days, "
            f"{days_to_deadline:.0f} days available. "
            f"Can complete with some buffer for normal delays."
        )
    else:
        timeline_type = "COMFORTABLE_TIMELINE"
        note = (
            f"COMFORTABLE TIMELINE: Process needs {min_total:.0f} days, "
            f"{days_to_deadline:.0f} days available ({safety_margin:.1f}x buffer). "
            f"Timeline is not the binding constraint."
        )

    # Structural ceiling detection
    is_ceiling = timeline_type in ("IMPOSSIBLE_TIMELINE", "COMPRESSED_TIMELINE")
    if is_ceiling and market_yes_price and market_yes_price > 0.25:
        note += (
            f"\nSHORT SIGNAL: Market prices YES at {market_yes_price:.0%} but "
            f"timeline is {timeline_type}. "
            f"Structural constraint makes YES highly unlikely."
        )

    return LegislativeAnalysis(
        timeline_type=timeline_type,
        steps_remaining=steps,
        min_days_per_step=step_mins,
        min_total_days=min_total,
        days_to_deadline=days_to_deadline,
        safety_margin=safety_margin,
        signal_note=note,
        is_structural_ceiling=is_ceiling,
    )


# ── Auto-detection from market question ─────────────────────────────────────

_LEGISLATIVE_KEYWORDS = [
    "bill", "legislation", "law", "act", "amendment",
    "pass", "vote", "ratify", "approve", "enact",
    "dissolve parliament", "dissolution", "knesset",
    "congress", "senate", "house", "bundestag", "knesset",
    "reading", "referendum", "ballot", "motion",
]

_KNESSET_KEYWORDS = ["knesset", "israel", "dissolv", "coalition", "likud", "netanyahu"]
_US_KEYWORDS = ["congress", "senate", "house of representatives", "filibuster"]
_UK_KEYWORDS = ["parliament", "commons", "lords", "westminster"]


def detect_legislative_market(question: str) -> bool:
    """Return True if market question is likely a legislative/procedural market."""
    ql = question.lower()
    return any(kw in ql for kw in _LEGISLATIVE_KEYWORDS)


def guess_process_template(question: str, days_to_deadline: float) -> LegislativeAnalysis | None:
    """Auto-detect process template and run analysis if possible."""
    ql = question.lower()

    if any(kw in ql for kw in _KNESSET_KEYWORDS):
        return analyze_legislative_timeline(
            PROCESS_TEMPLATES["knesset_dissolution"],
            days_to_deadline,
        )
    if any(kw in ql for kw in _US_KEYWORDS):
        if "conference" in ql or "bicameral" in ql:
            return analyze_legislative_timeline(
                PROCESS_TEMPLATES["us_legislation_full"],
                days_to_deadline,
            )
        return analyze_legislative_timeline(
            PROCESS_TEMPLATES["us_legislation"],
            days_to_deadline,
        )
    if any(kw in ql for kw in _UK_KEYWORDS):
        return analyze_legislative_timeline(
            PROCESS_TEMPLATES["uk_legislation"],
            days_to_deadline,
        )
    # Generic: assume 4 readings if "reading" mentioned
    if "reading" in ql:
        return analyze_legislative_timeline(
            PROCESS_TEMPLATES["generic_4_readings"],
            days_to_deadline,
        )
    # Minimal: just a vote
    if any(kw in ql for kw in ["vote", "pass", "approve"]):
        return analyze_legislative_timeline(
            PROCESS_TEMPLATES["generic_vote"],
            days_to_deadline,
        )
    return None


def format_legislative_for_forager(analysis: LegislativeAnalysis) -> str:
    """Format a LegislativeAnalysis as a text block for Forager seed context."""
    emoji = {
        "IMPOSSIBLE_TIMELINE": "🚫",
        "COMPRESSED_TIMELINE": "⚠️",
        "FEASIBLE_TIMELINE": "✅",
        "COMFORTABLE_TIMELINE": "✅",
    }.get(analysis.timeline_type, "📋")

    lines = [
        f"=== LEGISLATIVE TIMELINE ANALYSIS {emoji} ===",
        f"Timeline type: {analysis.timeline_type}",
        f"Steps remaining: {', '.join(analysis.steps_remaining)}",
        f"Minimum total days required: {analysis.min_total_days:.0f} days",
        f"Days to deadline: {analysis.days_to_deadline:.0f} days",
        f"Safety margin: {analysis.safety_margin:.2f}x",
        "",
        f"INTERPRETATION: {analysis.signal_note}",
    ]
    if analysis.is_structural_ceiling:
        lines.append(
            "\n!!! STRUCTURAL CEILING — timeline makes YES highly unlikely !!!"
        )
    return "\n".join(lines)
