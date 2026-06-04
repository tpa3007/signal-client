"""Ledger metadata helpers.

These fields make the ledger comparable across project eras. They are deliberately
simple enums/heuristics: enough structure for dashboards and learning, without
pretending to be probability estimates.
"""
from __future__ import annotations

from typing import Any


EDGE_ARCHETYPE_MAP = {
    "private_market_valuation": "provider_metric",
    "election_local_asymmetry": "local_polling",
    "geopolitical_control": "geopolitical_catalyst",
    "battlefield_control": "geopolitical_catalyst",
    "legislative_deadline": "deadline_decay_short",
    "diplomatic_visit_or_meeting": "geopolitical_catalyst",
    "resolution_wording_trap": "resolution_mechanics",
    "countable_catalyst": "resolution_mechanics",
    "cheap_optionality": "cheap_tail",
    "moonshot": "cheap_tail",
    "stale_catalyst": "deadline_decay_short",
    "repricing_watch": "deadline_decay_short",
    "anti_consensus_compounder": "primary_field_structure",
    "cross_platform_divergence": "cross_platform_divergence",
}


def edge_archetype_from_primary(primary_archetype: str | None, question: str | None = None) -> str:
    raw = (primary_archetype or "").strip().lower()
    q = (question or "").lower()
    if "npm price" in q or "valuation" in q or "nasdaq private market" in q:
        return "provider_metric"
    if any(x in q for x in ("spencer pratt", "celebrity")):
        return "celebrity_overpricing"
    if any(x in q for x in ("fed", "rba", "ecb", "cash rate", "rate")):
        return "central_bank_sequence"
    if any(x in q for x in ("gpt", "gemini", "model", "release", "ipo")):
        return "resolution_mechanics"
    if any(x in q for x in ("poll", "election", "primary", "governor", "seats")):
        return "local_polling"
    if any(x in q for x in ("iran", "israel", "russia", "ukraine", "pakistan", "netanyahu", "putin")):
        return "geopolitical_catalyst"
    if raw in EDGE_ARCHETYPE_MAP:
        return EDGE_ARCHETYPE_MAP[raw]
    if raw in {"crowd_narrative_error", "actor_incentive_mismatch", "low_attention_research"}:
        return "primary_field_structure"
    if raw == "general_research":
        return "unknown"
    return raw or "unknown"


def signal_generation_epoch(*, gate_status: str | None, manual_trade: bool = False,
                            operator_decision: str | None = None) -> str:
    if manual_trade or (operator_decision or "") == "manual_real_trade":
        return "manual_real"
    if gate_status == "gated":
        return "gated_v2_after_MR"
    if gate_status == "manual":
        return "operator_approved"
    if gate_status == "legacy_gate_violation":
        return "legacy"
    return "legacy"


def approval_strength(*, edge: float | None, confidence: float | None,
                      checklist_score: float | None = None,
                      operator_approved: bool = False) -> str:
    edge_value = abs(float(edge or 0.0))
    confidence_value = float(confidence or 0.0)
    score = float(checklist_score or 0.0)
    if operator_approved and edge_value >= 0.12 and confidence_value >= 0.65 and score >= 82:
        return "A"
    if edge_value >= 0.08 and confidence_value >= 0.55:
        return "B"
    if edge_value >= 0.04:
        return "C"
    if edge_value > 0:
        return "D"
    return "F"


def confidence_source(*, manual_trade: bool = False, operator_approved: bool = False,
                      model: str | None = None) -> str:
    model_l = (model or "").lower()
    if manual_trade:
        return "manual_human"
    if operator_approved:
        return "operator_override"
    if "ollama" in model_l:
        return "ollama_draft"
    if "aladdin" in model_l or "command" in model_l:
        return "forager_packet"
    return "automated_score"


def post_entry_review_signal(*, mtm_pnl_pct: float | None = None,
                             days_to_deadline: float | None = None,
                             gate_status: str | None = None,
                             stake_source: str | None = None,
                             edge_archetype: str | None = None) -> tuple[bool, str]:
    reasons: list[str] = []
    if mtm_pnl_pct is not None and mtm_pnl_pct <= -30.0:
        reasons.append("price_moved_against_entry_gt_30pct")
    if days_to_deadline is not None and days_to_deadline < 7:
        reasons.append("deadline_lt_7_days")
    if gate_status == "legacy_gate_violation":
        reasons.append("legacy_gate_violation")
    if stake_source in {"real", "hybrid"}:
        reasons.append("real_money_or_hybrid")
    if edge_archetype == "cheap_tail":
        reasons.append("cheap_tail_requires_active_catalyst_check")
    return bool(reasons), "; ".join(reasons)


def merge_metadata(base: dict[str, Any], **updates: Any) -> dict[str, Any]:
    out = dict(base)
    for key, value in updates.items():
        if value is not None:
            out[key] = value
    return out
