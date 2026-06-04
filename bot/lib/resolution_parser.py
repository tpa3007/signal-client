"""Detect ambiguous terms in market resolution text.

Returns a dict of (warnings, ambiguity_score, suggestion). The point isn't to
forbid markets — it's to surface things that bit us in the past so the
operator must address them in record_resolution_map.

Severity is per-warning (low/medium/high). Score is normalised 0..1 where
higher = more ambiguous = more dangerous to enter without explicit
resolution_map.
"""
from __future__ import annotations

import re
from typing import Iterable


# Per-warning weight contribution to ambiguity score.
SEVERITY_WEIGHTS = {"low": 0.10, "medium": 0.25, "high": 0.40}


# Each rule: (regex pattern, severity, code, message)
# All patterns are case-insensitive; multi-word patterns use \b boundaries.
RULES: list[tuple[str, str, str, str]] = [
    # --- Quantitative ambiguity ---
    (r"\bapproximately\b", "high", "approximately",
     "'approximately' is fatally vague — resolution will hinge on judgment."),
    (r"\b(around|roughly|near|circa)\b", "medium", "loose_quantity",
     "Loose quantifier ({m}) — usually means resolver has discretion."),
    (r"\b(about|some|several|many|few)\b", "low", "imprecise_count",
     "Imprecise quantifier ({m}) — could matter at margins."),

    # --- Subjective rankings ---
    (r"\b(best|leading|top|primary|flagship|major)\s+(ai|model|product|company|release)\b",
     "high", "subjective_rank",
     "Subjective ranking ({m}) — needs explicit metric or this is judgment-based."),
    (r"\b(best|leading|top)\b(?!\s*(of|3|5|10))", "medium", "general_superlative",
     "General superlative ({m}) — by what metric?"),

    # --- Modifier traps ---
    (r"\b(officially|publicly|formally)\s+(announce\w*|recogni[sz]e\w*|declare\w*)\b",
     "medium", "official_modifier",
     "Modifier '{m}' — what counts as 'official'? Tweet? Press release? Filed document?"),
    (r"\bqualifying\b", "medium", "qualifying_modifier",
     "'qualifying' implies a definition somewhere — find it or the bet has wording risk."),
    (r"\b(certified|verified|confirmed)\s+(winner|result|outcome)\b",
     "low", "verification_layer",
     "Resolution requires certification step ({m}) — adds delay and possible reversal risk."),

    # --- Deadline traps ---
    (r"\b(by|before|no later than)\s+(end\s+of|the\s+end\s+of)\s+(\w+)\b",
     "low", "end_of_period",
     "Deadline references end-of-period ({m}) — confirm exact UTC cutoff in resolution_map."),
    (r"\b(by|before)\s+\w+\b.*\b(at|by)\s+(\d{1,2}):(\d{2})\b",
     "low", "specific_hour_deadline",
     "Specific hour in deadline — verify timezone."),

    # --- Compound conditions ---
    (r"\band\b.{0,80}\band\b", "medium", "multiple_and_clauses",
     "Multiple 'and' clauses — all must hold. Each is a separate resolution risk."),
    (r"\bor\b.{0,80}\bor\b", "medium", "multiple_or_clauses",
     "Multiple 'or' clauses — any can trigger. Verify which one Polymarket uses."),

    # --- Undefined quorum / consensus ---
    (r"\b(most|majority|plurality)\b", "medium", "undefined_quorum",
     "Quorum-style word ({m}) — by what count, denominator, threshold?"),
    (r"\bconsensus\b", "high", "consensus",
     "'consensus' is almost always undefined. High wording risk."),

    # --- Forward-looking conditional ---
    (r"\b(if|provided|assuming|in the event)\b.{0,80}\b(then|will|would)\b",
     "low", "conditional_resolution",
     "Conditional resolution clause — sub-condition can change outcome."),

    # --- Polymarket-specific gotchas observed in audit ---
    (r"\b(qualifying|publicly\s+available|widely\s+available)\b",
     "high", "availability_test",
     "Resolution tied to availability test — Polymarket has resolved these strictly in the past (e.g. Gemini reasoning flagship)."),
    (r"\b(releas|launch|ship|deploy)\w*\b.{0,80}\bby\b\s+\w+\s+\d", "medium",
     "release_deadline", "Release-by-date markets are wording traps when 'release' is ambiguous (beta? GA? API access?)."),
    (r"\bdissol(v|ut)\w*\b", "medium", "dissolution_event",
     "Parliamentary/corporate dissolution events require official act ≠ intent. Bill submission ≠ dissolution."),
]


def _find_matches(text: str, pattern: str) -> list[str]:
    """Return list of matched substrings (lowercased), de-duplicated."""
    if not text:
        return []
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    out: list[str] = []
    seen = set()
    for m in matches:
        s = m if isinstance(m, str) else " ".join(x for x in m if x)
        s = s.strip().lower()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def parse_resolution_clarity(text: str) -> dict:
    """Return ambiguity report for resolution text.

    {
      "warnings": [{"code", "severity", "match", "message"}, ...],
      "ambiguity_score": float 0..1,   # higher = more dangerous
      "clarity_score": float 0..1,     # 1 - ambiguity_score
      "n_high": int, "n_medium": int, "n_low": int,
      "suggestion": str | None,
    }
    """
    if not text:
        return {
            "warnings": [],
            "ambiguity_score": 0.5,
            "clarity_score": 0.5,
            "n_high": 0, "n_medium": 0, "n_low": 0,
            "suggestion": "Resolution text is empty — request full description from Polymarket Gamma.",
        }

    warnings = []
    score = 0.0
    by_code: set[str] = set()  # dedupe by code so the same rule firing twice doesn't double-count

    for pattern, severity, code, msg_tmpl in RULES:
        matches = _find_matches(text, pattern)
        if not matches:
            continue
        if code in by_code:
            continue
        by_code.add(code)
        warnings.append({
            "code": code,
            "severity": severity,
            "match": matches[0],
            "message": msg_tmpl.format(m=matches[0]),
        })
        score += SEVERITY_WEIGHTS[severity]

    # Cap at 1.0
    score = min(1.0, score)

    counts = {
        "n_high": sum(1 for w in warnings if w["severity"] == "high"),
        "n_medium": sum(1 for w in warnings if w["severity"] == "medium"),
        "n_low": sum(1 for w in warnings if w["severity"] == "low"),
    }

    suggestion = None
    if counts["n_high"] >= 1:
        suggestion = ("High-severity ambiguity found — do not enter without explicit "
                      "record_resolution_map covering each flagged term. Consider skipping.")
    elif counts["n_medium"] >= 2:
        suggestion = ("Multiple medium-severity ambiguities — write resolution_map "
                      "with explicit ambiguity_cases for each.")
    elif counts["n_medium"] >= 1 or counts["n_low"] >= 2:
        suggestion = "Some ambiguity flagged — note in resolution_map.ambiguity_cases."

    return {
        "warnings": warnings,
        "ambiguity_score": round(score, 3),
        "clarity_score": round(1.0 - score, 3),
        **counts,
        "suggestion": suggestion,
    }
