"""Pace Calculator — structural ceiling analysis for production/count-based markets.

For markets of the form "Will X reach/exceed N units by date Y?", computes whether
the observed production pace makes YES achievable, uncertain, or structurally impossible.

TAXONOMY:
  HARD_CEILING       — Even best-case projection < 70% of target. YES is structurally
                       impossible. Market pricing YES > 20% is a potential SHORT signal.
  SOFT_CEILING       — Best-case projection 70-90% of target. Needs 1.5-2x acceleration.
                       Possible but requires major effort change.
  TIGHT_THRESHOLD    — Baseline projects 85-115% of target. Genuine uncertainty.
                       Both YES and NO are plausible depending on variance.
  PACE_SUPPORTS_YES  — Baseline projects > 115% of target. On pace. Risk is downtime/failure.

CALIBRATION (from F03 resolved trade):
  F03 was TIGHT_THRESHOLD at baseline_ratio=0.97 (projected 242k/250k).
  Robots accelerated (market hit 0.98 = 98% YES), but resolved NO.
  Lesson: tight_threshold means genuine uncertainty, NOT impossibility.

USAGE:
  from lib.analysis.pace_calculator import analyze_production_market, detect_pace_market
  analysis = analyze_production_market(
      current_count=100000,
      elapsed_hours=81,
      target_count=250000,
      deadline_hours_remaining=115,
  )
  # => {"ceiling_type": "TIGHT_THRESHOLD", "baseline_ratio": 0.97, ...}
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class PaceAnalysis:
    ceiling_type: str          # HARD_CEILING / SOFT_CEILING / TIGHT_THRESHOLD / PACE_SUPPORTS_YES
    baseline_rate: float       # units per hour at observed pace
    projected_baseline: float  # projected final count at baseline rate
    projected_best_case: float # projected final count at best-case acceleration
    baseline_ratio: float      # projected_baseline / target (1.0 = exactly on pace)
    best_case_ratio: float     # projected_best_case / target
    target_count: float
    current_count: float
    hours_remaining: float
    shortfall_baseline: float  # max(0, target - projected_baseline)
    required_rate_multiplier: float  # how much rate must increase to hit target
    signal_note: str           # human-readable interpretation
    is_short_candidate: bool   # True if market price likely far above fair value


# ── Core computation ─────────────────────────────────────────────────────────

def analyze_production_market(
    current_count: float,
    elapsed_hours: float,
    target_count: float,
    deadline_hours_remaining: float,
    best_case_multiplier: float = 1.8,   # max plausible acceleration (e.g. adding robots)
    market_yes_price: float | None = None,
) -> PaceAnalysis:
    """Analyze whether a production target is achievable given observed pace.

    Args:
        current_count:              Units produced/sorted/completed so far
        elapsed_hours:              Hours elapsed since production started
        target_count:               Target units to reach for YES resolution
        deadline_hours_remaining:   Hours until market resolution deadline
        best_case_multiplier:       Max plausible rate increase (1.8 = 80% acceleration)
        market_yes_price:           Current Polymarket YES price (for short signal detection)

    Returns:
        PaceAnalysis with ceiling_type and interpretive note.
    """
    if elapsed_hours <= 0 or target_count <= 0:
        return PaceAnalysis(
            ceiling_type="UNKNOWN",
            baseline_rate=0, projected_baseline=0, projected_best_case=0,
            baseline_ratio=0, best_case_ratio=0,
            target_count=target_count, current_count=current_count,
            hours_remaining=deadline_hours_remaining, shortfall_baseline=target_count,
            required_rate_multiplier=999, signal_note="Insufficient data for pace analysis",
            is_short_candidate=False,
        )

    baseline_rate = current_count / elapsed_hours
    projected_baseline = current_count + baseline_rate * deadline_hours_remaining
    projected_best_case = current_count + (baseline_rate * best_case_multiplier) * deadline_hours_remaining

    baseline_ratio = projected_baseline / target_count
    best_case_ratio = projected_best_case / target_count
    shortfall = max(0.0, target_count - projected_baseline)

    # How much rate increase needed to hit target at deadline?
    remaining_needed = target_count - current_count
    if deadline_hours_remaining > 0 and remaining_needed > 0:
        required_rate = remaining_needed / deadline_hours_remaining
        required_rate_multiplier = required_rate / baseline_rate if baseline_rate > 0 else 999.0
    else:
        required_rate_multiplier = 0.0

    # Classify
    if best_case_ratio < 0.70:
        ceiling_type = "HARD_CEILING"
        note = (
            f"HARD CEILING: Even at {best_case_multiplier:.1f}x acceleration, "
            f"projected {projected_best_case:,.0f} < {target_count * 0.70:,.0f} (70% of target). "
            f"YES is structurally very unlikely. Current baseline projects "
            f"{projected_baseline:,.0f} ({baseline_ratio:.0%} of target)."
        )
    elif best_case_ratio < 0.90:
        ceiling_type = "SOFT_CEILING"
        note = (
            f"SOFT CEILING: Needs {required_rate_multiplier:.1f}x rate increase to hit target. "
            f"Best-case projects {projected_best_case:,.0f} ({best_case_ratio:.0%} of target). "
            f"Possible but requires significant acceleration beyond current pace."
        )
    elif baseline_ratio < 0.85:
        ceiling_type = "TIGHT_THRESHOLD"
        note = (
            f"TIGHT THRESHOLD (needs acceleration): Baseline projects {projected_baseline:,.0f} "
            f"({baseline_ratio:.0%} of target {target_count:,.0f}). "
            f"Needs {required_rate_multiplier:.1f}x rate to hit target. "
            f"Outcome depends on whether operators can accelerate."
        )
    elif baseline_ratio <= 1.15:
        ceiling_type = "TIGHT_THRESHOLD"
        note = (
            f"TIGHT THRESHOLD (on pace with variance): Baseline projects {projected_baseline:,.0f} "
            f"({baseline_ratio:.0%} of target). "
            f"Genuine uncertainty — small variance swings outcome. "
            f"Similar to F03 resolved trade: 97% projected but resolved NO due to slowdown."
        )
    else:
        ceiling_type = "PACE_SUPPORTS_YES"
        note = (
            f"PACE SUPPORTS YES: Baseline projects {projected_baseline:,.0f} "
            f"({baseline_ratio:.0%} of target). "
            f"On pace at {baseline_rate:,.0f} units/hr. "
            f"Risk is downtime/interruption, not pace insufficiency."
        )

    # Short signal: market pricing YES much higher than warranted by pace
    is_short_candidate = False
    if market_yes_price is not None:
        if ceiling_type in ("HARD_CEILING", "SOFT_CEILING") and market_yes_price > 0.35:
            is_short_candidate = True
            note += (
                f"\nSHORT SIGNAL: Market prices YES at {market_yes_price:.0%} but "
                f"pace math suggests {ceiling_type}. "
                f"Contrarian NO may be high edge."
            )
        elif ceiling_type == "TIGHT_THRESHOLD" and market_yes_price > 0.80:
            is_short_candidate = True
            note += (
                f"\nNARRATIVE BUBBLE ALERT: Market at {market_yes_price:.0%} on a "
                f"TIGHT_THRESHOLD market. Crowd is overconfident. "
                f"Short opportunity if you can sell NO before resolution."
            )

    return PaceAnalysis(
        ceiling_type=ceiling_type,
        baseline_rate=baseline_rate,
        projected_baseline=projected_baseline,
        projected_best_case=projected_best_case,
        baseline_ratio=baseline_ratio,
        best_case_ratio=best_case_ratio,
        target_count=target_count,
        current_count=current_count,
        hours_remaining=deadline_hours_remaining,
        shortfall_baseline=shortfall,
        required_rate_multiplier=required_rate_multiplier,
        signal_note=note,
        is_short_candidate=is_short_candidate,
    )


# ── Market question detector ─────────────────────────────────────────────────

_PRODUCTION_PATTERNS = [
    # "Will X reach/exceed/hit N [units] by [date]"
    r"(?:reach|exceed|hit|push|sort|produce|manufacture|deliver|ship|sell)\s+"
    r"(?:at least\s+)?(\d[\d,]*(?:\.\d+)?)\s*(?:k\b|m\b|million|thousand|units?|packages?|robots?|cars?|vehicles?|doses?)?",
    # "Will X be [at/above] N [units]"
    r"(?:be|surpass|cross)\s+(?:at least\s+)?(\d[\d,]*(?:\.\d+)?)\s*(?:k\b|m\b)?",
]

_RATE_KEYWORDS = [
    "packages", "units", "doses", "cars", "vehicles", "robots", "ships",
    "sorted", "produced", "manufactured", "delivered", "assembled",
    "per day", "per hour", "per week", "rate", "pace", "production",
]


def detect_pace_market(question: str) -> bool:
    """Return True if a market question is likely a production/count-based market."""
    ql = question.lower()
    # Valuation/price-threshold markets often use words like "hit" plus a
    # number, but they are oracle/provider mark questions, not production pace.
    if any(term in ql for term in (
        "valuation", "market cap", "price", "xauusd", "bitcoin", "btc",
        "ethereum", "stock", "shares", "npm price",
    )):
        return False
    has_rate_kw = any(kw in ql for kw in _RATE_KEYWORDS)
    has_number = bool(re.search(r'\b\d[\d,]*(?:k|m)?\b', ql))
    has_reach_kw = any(kw in ql for kw in [
        "reach", "exceed", "hit", "push", "at least", "more than",
        "250,000", "250k", "100,000", "1 million", "million units",
    ])
    return (has_rate_kw or has_reach_kw) and has_number


def extract_pace_params_from_text(evidence_text: str) -> dict | None:
    """Best-effort extraction of pace parameters from free text evidence.

    Tries to find:
      - Current count: "X packages/units sorted/produced"
      - Elapsed time: "in Y hours/days"
      - Target: "target of Z"

    Returns dict with extracted values, or None if can't extract.
    """
    if not evidence_text:
        return None

    text = evidence_text.lower()

    # Current count patterns
    count_patterns = [
        r'(\d[\d,]*)\s*(?:packages?|units?|cars?|doses?)\s+(?:sorted|pushed|produced|delivered)',
        r'(?:sorted|produced|delivered|pushed)\s+(\d[\d,]*)\s*(?:packages?|units?)',
        r'(\d[\d,]*)\s*(?:packages?|units?)\s+in\s+\d+\s*hours?',
    ]
    current_count: float | None = None
    for pat in count_patterns:
        m = re.search(pat, text)
        if m:
            try:
                current_count = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass

    # Elapsed time patterns
    time_patterns = [
        r'in\s+(\d+(?:\.\d+)?)\s*hours?',
        r'over\s+(\d+(?:\.\d+)?)\s*hours?',
        r'(\d+(?:\.\d+)?)\s*(?:-hour|hour)\s+(?:period|window|operation)',
    ]
    elapsed_hours: float | None = None
    for pat in time_patterns:
        m = re.search(pat, text)
        if m:
            try:
                elapsed_hours = float(m.group(1))
                break
            except ValueError:
                pass
    # Also check for days
    if elapsed_hours is None:
        day_m = re.search(r'(?:in|over)\s+(\d+(?:\.\d+)?)\s*days?', text)
        if day_m:
            try:
                elapsed_hours = float(day_m.group(1)) * 24
            except ValueError:
                pass

    # Target patterns
    target_patterns = [
        r'(\d[\d,]*)\s*(?:packages?|units?|k)\s+(?:target|goal|milestone)',
        r'(?:target|goal|milestone)\s+(?:of\s+)?(\d[\d,]*)',
        r'(?:at least|more than|exceed)\s+(\d[\d,]*)',
    ]
    target: float | None = None
    for pat in target_patterns:
        m = re.search(pat, text)
        if m:
            try:
                val_str = m.group(1).replace(",", "")
                target = float(val_str)
                break
            except ValueError:
                pass

    if current_count is None or elapsed_hours is None:
        return None

    result = {
        "current_count": current_count,
        "elapsed_hours": elapsed_hours,
    }
    if target is not None:
        result["target_count"] = target
    return result


def format_pace_for_forager(analysis: PaceAnalysis) -> str:
    """Format a PaceAnalysis as a text block for Forager seed context."""
    emoji = {
        "HARD_CEILING": "🚫",
        "SOFT_CEILING": "⚠️",
        "TIGHT_THRESHOLD": "⚡",
        "PACE_SUPPORTS_YES": "✅",
    }.get(analysis.ceiling_type, "📊")

    lines = [
        f"=== PACE ANALYSIS {emoji} ===",
        f"Ceiling type: {analysis.ceiling_type}",
        f"Current count: {analysis.current_count:,.0f} units",
        f"Baseline rate: {analysis.baseline_rate:,.1f} units/hour",
        f"Projected (baseline): {analysis.projected_baseline:,.0f} ({analysis.baseline_ratio:.0%} of target)",
        f"Projected (best-case {analysis.baseline_rate * 1.8:,.0f}/hr): {analysis.projected_best_case:,.0f} ({analysis.best_case_ratio:.0%} of target)",
        f"Hours remaining: {analysis.hours_remaining:.0f}h",
        f"Required rate multiplier: {analysis.required_rate_multiplier:.1f}x",
        "",
        f"INTERPRETATION: {analysis.signal_note}",
    ]
    if analysis.is_short_candidate:
        lines.append("\n!!! SHORT SIGNAL DETECTED — see above !!!")
    return "\n".join(lines)
