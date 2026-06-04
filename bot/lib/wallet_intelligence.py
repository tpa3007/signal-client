"""Pure wallet/player intelligence helpers for Command W.

The functions here deliberately avoid network and database access. Command W can
use them to make wallet tracking less script-like: identify the side, size the
signal, grade the player, and keep convergence weighted by signal quality.
"""
from __future__ import annotations

import math
from typing import Any


DUST_POSITION_USD = 25.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_wallet_side(position: dict[str, Any]) -> str | None:
    """Return YES/NO for a Polymarket position-like dict when it is knowable."""
    outcome = str(position.get("outcome") or position.get("outcomeName") or "").lower()
    if "yes" in outcome:
        return "YES"
    if "no" in outcome:
        return "NO"

    side = str(position.get("side") or "").upper()
    if side in {"YES", "NO"}:
        return side

    return None


def position_avg_price(position: dict[str, Any]) -> float:
    for key in ("avgPrice", "averagePrice", "price", "curPrice"):
        value = _float(position.get(key))
        if value > 0:
            return value
    return 0.0


def position_value_usd(position: dict[str, Any]) -> float:
    """Best-effort current/notional USD value from data-api position fields."""
    for key in ("currentValue", "value", "usdcSize", "initialValue"):
        value = _float(position.get(key))
        if value > 0:
            return value

    size = _float(position.get("size") or position.get("shares"))
    price = position_avg_price(position)
    return max(0.0, size * price)


def classify_player_style(profile: dict[str, Any], composite_score: float) -> dict[str, Any]:
    """Classify a wallet as a usable player archetype, with risk flags."""
    resolved = int(_float(profile.get("markets_resolved")))
    total_usd = _float(profile.get("total_volume_usd"))
    win_rate = profile.get("win_rate")
    timing_alpha = profile.get("timing_alpha")
    edge = profile.get("best_category_edge")
    hhi = _float(profile.get("category_hhi"))
    bio = str(profile.get("bio") or "").lower()

    flags: list[str] = []
    if resolved < 3:
        flags.append("thin_resolved_sample")
    if total_usd >= 15_000 and composite_score < 25:
        flags.append("large_flow_without_proven_edge")
    if hhi < 0.25 and edge is None:
        flags.append("scattershot_no_category_edge")
    if any(k in bio for k in ("degen", "gambl", "ape", "yolo")):
        flags.append("self_described_degen")

    if composite_score >= 40 and timing_alpha is not None and timing_alpha >= 0.65 and hhi >= 0.45:
        style = "early_specialist_insider_candidate"
        reason = "early entries plus category concentration"
    elif composite_score >= 40:
        style = "insider_candidate"
        reason = "composite score clears insider threshold"
    elif composite_score >= 25 and edge is not None and edge > 0:
        style = "category_sharp"
        reason = "positive category brier edge"
    elif total_usd >= 15_000:
        style = "whale_flow_only"
        reason = "large notional flow without enough proven edge"
    elif win_rate is not None and resolved >= 5 and composite_score < 25:
        style = "low_trust_player"
        reason = "resolved sample exists but score is weak"
    else:
        style = "unclassified_player"
        reason = "insufficient clean evidence"

    trust_score = composite_score
    if resolved < 3:
        trust_score *= 0.75
    if "large_flow_without_proven_edge" in flags:
        trust_score *= 0.80
    trust_score = round(max(0.0, min(100.0, trust_score)), 1)

    return {
        "player_style": style,
        "trust_score": trust_score,
        "trust_reason": reason,
        "risk_flags": flags,
    }


def score_position_signal(
    position: dict[str, Any],
    *,
    label: str = "unknown",
    composite_score: float = 0.0,
    our_side: str | None = None,
) -> dict[str, Any]:
    """Score how much one wallet position should matter to Command W."""
    side = normalize_wallet_side(position)
    avg_price = position_avg_price(position)
    usd = position_value_usd(position)
    pnl = _float(position.get("cashPnl") or position.get("realizedPnl"))

    flags: list[str] = []
    if side is None:
        flags.append("unknown_side")
    if usd < DUST_POSITION_USD:
        flags.append("dust_position")
    if avg_price and avg_price <= 0.15:
        flags.append("low_price_optionality")
    if avg_price and avg_price >= 0.75:
        flags.append("high_conviction_price")

    agreement = None
    if our_side and side:
        agreement = "agree" if side == our_side else "disagree"
        flags.append("same_as_us" if agreement == "agree" else "opposes_us")

    label_bonus = {
        "insider": 24.0,
        "smart": 16.0,
        "whale": 8.0,
    }.get(label, 0.0)
    score_component = min(30.0, max(0.0, composite_score) * 0.45)
    size_component = min(30.0, math.log10(max(usd, 1.0)) * 10.0)
    price_component = 0.0
    if avg_price >= 0.75:
        price_component = 8.0
    elif avg_price >= 0.55:
        price_component = 5.0
    elif 0 < avg_price <= 0.15:
        price_component = 4.0
    pnl_component = 4.0 if pnl > 0 else 0.0

    strength = score_component + size_component + label_bonus + price_component + pnl_component
    if "dust_position" in flags:
        strength *= 0.35
    if side is None:
        strength = 0.0
    strength = round(max(0.0, min(100.0, strength)), 1)

    if side is None or usd < DUST_POSITION_USD:
        tier = "ignore"
    elif strength >= 70:
        tier = "high"
    elif strength >= 45:
        tier = "medium"
    else:
        tier = "low"

    return {
        "side": side,
        "usd": round(usd, 2),
        "avg_price": round(avg_price, 4),
        "pnl": round(pnl, 2),
        "agreement": agreement,
        "signal_strength": strength,
        "signal_tier": tier,
        "flags": flags,
    }


def convergence_vote_weight(signal: dict[str, Any]) -> float:
    """Weight one wallet vote for convergence detection."""
    if signal.get("signal_tier") == "ignore":
        return 0.0
    usd = _float(signal.get("usd"))
    strength = _float(signal.get("signal_strength"))
    return round(strength * math.sqrt(max(usd, 1.0)), 2)
