"""Disconfirmation-hunter perspective.

Actively looks for evidence that would BREAK the suggested thesis. Owns the
kill-criteria list and grades how strongly the world has confirmed/denied
each. Its instinct is bearish-on-the-thesis: assume the thesis is wrong,
hunt for the proof.

What this perspective uniquely sees:
  - Specific kill-criterion hits across the document set
  - Asymmetry between "no evidence FOR" vs "evidence AGAINST"
  - Sources the consensus-aligned analyst would dismiss as outliers
"""
from __future__ import annotations

from typing import Any

from .base import Perspective


def _field(obj: Any, name: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class DisconfirmationPerspective(Perspective):
    name = "disconfirmation"
    persona_prompt = (
        "You are the project's red-team analyst. Your job is to KILL the "
        "suggested thesis. Assume the operator is about to bet wrong, and your "
        "task is to give them the strongest piece of disconfirming evidence "
        "you can find. You weight 'evidence the event will NOT happen' "
        "10× more than 'evidence the event will happen' — confirmation bias "
        "is the operator's problem, not yours. You operate on the kill_criteria "
        "list as your primary search agenda."
    )

    def extract_context(self, thread_data: dict[str, Any]) -> dict[str, Any]:
        base = super().extract_context(thread_data)
        cand = thread_data.get("candidate_metadata", {}) or {}
        base["suggested_side"] = cand.get("signal_side") or cand.get("suggested_side")
        base["thesis"] = cand.get("thesis", "")
        base["kill_criteria"] = cand.get("kill_criteria", []) or thread_data.get("kill_criteria", [])
        # Existing disconfirming sources Forager already gathered
        base["existing_disconf_sources"] = thread_data.get("disconfirming_sources", [])
        base["disconfirming_found"] = thread_data.get("disconfirming_found", False)
        # Claims that lean CONTRADICTS
        claims = thread_data.get("claims") or []
        base["contradict_claims_count"] = sum(
            1 for c in claims
            if str(_field(c, "stance", "")).lower() == "contradicts"
        )
        base["total_claims"] = len(claims)
        return base

    def domain_flags(self, thread_data: dict, context: dict) -> list[str]:
        flags = []
        kc = context.get("kill_criteria", [])
        if not kc:
            flags.append("NO_KILL_CRITERIA_DEFINED")  # red flag
        else:
            flags.append(f"kill_criteria_count:{len(kc)}")
        if context.get("disconfirming_found"):
            flags.append("disconfirming_evidence_already_in_packet")
        if context.get("contradict_claims_count", 0) >= 3:
            flags.append("strong_contradicting_claims")
        return flags

    def evidence_refs(self, thread_data: dict, context: dict) -> list[str]:
        return list(context.get("existing_disconf_sources") or [])[:10]

    def rule_based_hypotheses(self, thread_data: dict, context: dict) -> list[dict]:
        hyps: list[dict] = []
        suggested = context.get("suggested_side", "?")
        kill_criteria = context.get("kill_criteria", [])
        contra = context.get("contradict_claims_count", 0)
        total = context.get("total_claims", 0)

        # Hypothesis 1: kill criteria status
        if not kill_criteria:
            hyps.append({
                "direction": "UNCERTAIN",
                "title": "No kill criteria defined — thesis untestable",
                "hypothesis_text": (
                    "Without explicit kill criteria, this perspective cannot run its "
                    "primary search. Recommend that the dossier define 3 specific "
                    "criteria BEFORE entry: each must be externally verifiable, "
                    "specific to the resolution mechanism, and falsifiable before "
                    "the deadline."
                ),
                "confidence": 0.70,
                "evidence_score": 0.30,
                "perspective_specific_notes": "Block the bet until kill criteria defined.",
            })
        else:
            covered = sum(1 for s in (context.get("existing_disconf_sources") or [])
                          if s)  # rough heuristic
            opposite = "NO" if suggested == "YES" else "YES"
            hyps.append({
                "direction": opposite if context.get("disconfirming_found") else "UNCERTAIN",
                "title": f"Kill-criterion search — {len(kill_criteria)} defined",
                "hypothesis_text": (
                    f"Active kill criteria: {len(kill_criteria)}. Disconfirming sources "
                    f"already in packet: {len(context.get('existing_disconf_sources') or [])}. "
                    f"If even ONE kill criterion is confirmed, thesis collapses to "
                    f"near-zero probability. {'Some disconfirming evidence found — investigate priority.' if context.get('disconfirming_found') else 'No firm disconfirmation yet; continue actively hunting.'}"
                ),
                "confidence": 0.70 if context.get("disconfirming_found") else 0.55,
                "evidence_score": 0.55,
                "perspective_specific_notes": (
                    f"Each kill criterion needs its own targeted shallow search "
                    f"that does NOT include the thesis-supporting keywords."
                ),
            })

        # Hypothesis 2: claim balance
        if total >= 4:
            ratio = contra / total
            if ratio >= 0.40:
                opposite = "NO" if suggested == "YES" else "YES"
                hyps.append({
                    "direction": opposite,
                    "title": f"Claim balance leans against thesis ({contra}/{total})",
                    "hypothesis_text": (
                        f"Across {total} extracted claims, {contra} contradict the "
                        f"suggested {suggested} side. Ratio {ratio:.0%}. Crowd "
                        f"consensus may be wrong; consider downsizing OR taking "
                        f"the opposite side."
                    ),
                    "confidence": 0.65,
                    "evidence_score": 0.60,
                    "perspective_specific_notes": "Strong red flag — re-evaluate side.",
                })

        # Hypothesis 3: absence-of-evidence trap
        hyps.append({
            "direction": "UNCERTAIN",
            "title": "Absence of disconfirmation ≠ confirmation",
            "hypothesis_text": (
                "The most dangerous bet is one where no specific disconfirmer surfaced — "
                "either the thesis is right, OR the search just didn't reach the "
                "specific source that would kill it. Demand coverage on EACH kill "
                "criterion individually, not aggregate disconf_found=True."
            ),
            "confidence": 0.55,
            "evidence_score": 0.40,
            "perspective_specific_notes": (
                "Reject 'no news is good news'. Force per-criterion coverage."
            ),
        })
        return hyps
