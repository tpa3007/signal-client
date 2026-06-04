"""Catalyst-tracker perspective.

Owns the timeline. Watches scheduled events (votes, central-bank meetings,
hearings, deadlines, summits), translates question wording into concrete
catalyst dates, and grades how close the market is to a forced reprice.

What this perspective uniquely sees:
  - Days until catalyst event vs days until market resolution
  - Whether the catalyst is HARD-scheduled or soft-deadlined
  - Gap between catalyst date and resolution date (mispricing window)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .base import Perspective


class CatalystPerspective(Perspective):
    name = "catalyst"
    persona_prompt = (
        "You are a timeline / catalyst analyst for prediction markets. You "
        "convert market questions into a list of concrete dates: when will "
        "this market be FORCED to reprice? Election day, FOMC meeting, court "
        "hearing, vote, deadline. You distinguish HARD catalysts (calendared, "
        "non-negotiable) from SOFT (vague 'by year-end'). You flag when the "
        "catalyst happens BEFORE the market end_date (the mispricing window "
        "is the gap between catalyst and resolution)."
    )

    # Keywords mapping to expected catalyst classes
    _CATALYST_PATTERNS = [
        (r"election|vote|ballot|primary|runoff", "election"),
        (r"fomc|fed rate|federal reserve|ecb|rba|boe meeting", "central_bank"),
        (r"trial|hearing|verdict|sentenc", "judicial"),
        (r"summit|inauguration|sworn in|confirmation hearing", "political_event"),
        (r"deadline|by (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", "deadline"),
        (r"announce|release|launch|ipo", "announcement"),
    ]

    def extract_context(self, thread_data: dict[str, Any]) -> dict[str, Any]:
        base = super().extract_context(thread_data)
        cand = thread_data.get("candidate_metadata", {}) or {}
        question = (thread_data.get("question") or thread_data.get("seed_query", "")).lower()
        # Detect catalyst class
        catalyst_class = None
        for pattern, label in self._CATALYST_PATTERNS:
            if re.search(pattern, question):
                catalyst_class = label
                break
        base["catalyst_class"] = catalyst_class
        # Days to end
        end_date_str = cand.get("end_date", "")
        days_to_end = None
        if end_date_str:
            try:
                if "T" in end_date_str:
                    dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days_to_end = (dt - datetime.now(timezone.utc)).total_seconds() / 86400
            except Exception:
                pass
        base["days_to_end"] = round(days_to_end, 1) if days_to_end is not None else None
        # Known catalyst dates (placeholder — populate from external calendar in production)
        base["known_catalyst_date"] = None
        return base

    def domain_flags(self, thread_data: dict, context: dict) -> list[str]:
        flags = []
        if context.get("catalyst_class"):
            flags.append(f"catalyst:{context['catalyst_class']}")
        dte = context.get("days_to_end")
        if dte is not None:
            if dte < 3:
                flags.append("catalyst_imminent_lt_3d")
            elif dte < 14:
                flags.append("catalyst_near_lt_14d")
            elif dte < 60:
                flags.append("catalyst_medium_lt_60d")
            else:
                flags.append("catalyst_far_gte_60d")
        return flags

    def rule_based_hypotheses(self, thread_data: dict, context: dict) -> list[dict]:
        hyps: list[dict] = []
        cls = context.get("catalyst_class")
        dte = context.get("days_to_end")

        if not cls:
            hyps.append({
                "direction": "UNCERTAIN",
                "title": "No specific catalyst detected — passive market",
                "hypothesis_text": (
                    "Question wording contains no scheduled catalyst keyword. Market "
                    "likely resolves via gradual probability adjustment, not single "
                    "event reprice. Time-decay dominates; avoid sizing as if a hard "
                    "catalyst exists."
                ),
                "confidence": 0.55,
                "evidence_score": 0.30,
                "perspective_specific_notes": "Passive market — no catalyst-based edge.",
            })
            return hyps

        # Catalyst exists
        urgency = "imminent" if (dte is not None and dte < 7) else (
            "near" if (dte is not None and dte < 30) else (
                "medium" if (dte is not None and dte < 60) else "far"
            )
        )
        hyps.append({
            "direction": "UNCERTAIN",
            "title": f"{cls.title()} catalyst — {urgency} ({dte}d to end)",
            "hypothesis_text": (
                f"Detected catalyst class: {cls}. Time to resolution: {dte} days. "
                f"For {cls} markets, expect 50-80% of total price movement in the "
                f"final 48-72 hours pre-catalyst. SIZING IMPLICATION: enter early "
                f"if you have an edge thesis; the late move is hard to capture."
            ),
            "confidence": 0.65,
            "evidence_score": 0.55,
            "perspective_specific_notes": (
                f"Catalyst-class={cls}; urgency={urgency}. "
                "Recommend setting a fixed timer (e.g. T-72h re-check) on this position."
            ),
        })

        # Election-specific
        if cls == "election" and dte is not None and dte < 14:
            hyps.append({
                "direction": "UNCERTAIN",
                "title": "Election quiet period likely active",
                "hypothesis_text": (
                    "Most jurisdictions enforce a polling 'quiet period' 3-7 days "
                    "before election day. No fresh poll data inside that window. "
                    "Existing market price reflects last-pre-quiet info; surprises "
                    "discovered through Telegram / local press get fast premium."
                ),
                "confidence": 0.60,
                "evidence_score": 0.50,
                "perspective_specific_notes": (
                    "Set re-check just before quiet period begins."
                ),
            })

        # Central bank
        if cls == "central_bank":
            hyps.append({
                "direction": "UNCERTAIN",
                "title": "Central bank pricing — anchor to futures",
                "hypothesis_text": (
                    "Central-bank-decision markets must be anchored to futures-implied "
                    "probability (CME FedWatch, ASX rate futures, etc.), not press "
                    "commentary. Polymarket often lags futures by 1-2 days."
                ),
                "confidence": 0.70,
                "evidence_score": 0.55,
                "perspective_specific_notes": "Pull futures-implied prob and compare.",
            })

        return hyps
