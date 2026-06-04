"""Market-structure analyst perspective.

Reads order-book signals (CLOB OFI, whale flow), cross-platform divergence
(PredictIt, Kalshi, Manifold, GJO, Metaculus), and spread/liquidity health.
Cares about WHAT THE MARKET IS DOING, not what the world is doing.

What this perspective uniquely sees:
  - Order flow imbalance — institutional positioning before consensus moves
  - Resting whale orders — informed money's price floor/ceiling
  - Cross-platform divergence — different audience mispricing the same event
  - Spread/liquidity health — execution feasibility
"""
from __future__ import annotations

from typing import Any

from .base import Perspective


class MarketStructurePerspective(Perspective):
    name = "market_structure"
    persona_prompt = (
        "You are a market-microstructure analyst for prediction markets. You "
        "read order books, whale flows, and cross-platform price divergences. "
        "You do NOT care about world events directly — you care about WHO is "
        "betting and HOW MUCH. Your edge is identifying when smart-money "
        "positioning contradicts the displayed mid-price, or when one platform "
        "(PredictIt, Kalshi, Manifold, GJO, Metaculus) prices something very "
        "differently than Polymarket."
    )

    def extract_context(self, thread_data: dict[str, Any]) -> dict[str, Any]:
        base = super().extract_context(thread_data)
        cand = thread_data.get("candidate_metadata", {}) or {}
        base["yes_price"] = cand.get("yes_price")
        base["spread"] = cand.get("spread")
        base["whale_alert"] = cand.get("whale_alert") or thread_data.get("whale_alert")
        base["whale_dominant"] = cand.get("whale_dominant")
        base["whale_max_usd"] = cand.get("whale_max_usd")
        base["ofi"] = cand.get("order_flow_imbalance")
        base["divergences"] = cand.get("divergences", {})
        base["metaculus_divergence"] = cand.get("metaculus_divergence")
        return base

    def domain_flags(self, thread_data: dict, context: dict) -> list[str]:
        flags = []
        if context.get("whale_alert"):
            dom = context.get("whale_dominant", "?")
            size = context.get("whale_max_usd", 0)
            flags.append(f"whale_dominant_{dom}_${size:,.0f}")
        ofi = context.get("ofi") or {}
        if abs(ofi.get("ofi", 0)) > 0.5:
            flags.append(f"strong_ofi_{ofi.get('ofi'):+.2f}")
        if context.get("divergences"):
            platforms = list(context["divergences"].keys())
            flags.append(f"cross_platform_divergence:{','.join(platforms)}")
        return flags

    def rule_based_hypotheses(self, thread_data: dict, context: dict) -> list[dict]:
        hyps: list[dict] = []
        # Whale-driven hypothesis
        if context.get("whale_alert") and context.get("whale_dominant"):
            dom = context["whale_dominant"]
            size = context.get("whale_max_usd", 0)
            hyps.append({
                "direction": dom if dom in ("YES", "NO") else "UNCERTAIN",
                "title": f"Whale flow dominant {dom} (${size:,.0f})",
                "hypothesis_text": (
                    f"Order book shows institutional positioning toward {dom} "
                    f"side with max single order ${size:,.0f}. This is INFORMATIONAL "
                    f"only — many large Polymarket positions are degens — but at this "
                    f"scale (>$50k) implies informed conviction. Weight modestly in "
                    f"calibration."
                ),
                "confidence": 0.50,
                "evidence_score": 0.55,
                "perspective_specific_notes": (
                    f"Whale dominant={dom}, max=${size:,.0f}. Disclaimer: not a "
                    f"signal weight, context only."
                ),
            })
        # Divergence hypothesis
        divs = context.get("divergences", {})
        for platform, d in divs.items():
            div = d.get("divergence", 0)
            if div >= 0.10:
                hyps.append({
                    "direction": "UNCERTAIN",
                    "title": f"{platform.upper()} divergence Δ{div:.0%}",
                    "hypothesis_text": (
                        f"{platform} prices this differently from Polymarket by {div:.0%}. "
                        f"VERIFY MATCH QUALITY: PredictIt/Manifold matchers use Jaccard "
                        f"overlap which can false-match on shared words (e.g. 'primary' "
                        f"+ candidate name). Before trusting divergence, confirm the "
                        f"matched contract is the same EVENT, not just similar text."
                    ),
                    "confidence": 0.40,
                    "evidence_score": 0.45,
                    "perspective_specific_notes": (
                        f"Platform={platform}, match_score={d.get('match_score', 'n/a')}. "
                        f"False-match risk especially high for PredictIt on primaries."
                    ),
                })
        # OFI
        ofi = context.get("ofi") or {}
        if abs(ofi.get("ofi", 0)) > 0.3:
            direction = "YES" if ofi["ofi"] > 0 else "NO"
            hyps.append({
                "direction": direction,
                "title": f"OFI {ofi['ofi']:+.2f} — {direction} buy pressure",
                "hypothesis_text": (
                    f"Top-10 CLOB depth shows {abs(ofi['ofi']):.0%} imbalance toward "
                    f"{direction}. Bid ${ofi.get('bid_depth',0):,.0f} vs ask "
                    f"${ofi.get('ask_depth',0):,.0f}. Short-term price pressure favours "
                    f"{direction}."
                ),
                "confidence": 0.45,
                "evidence_score": 0.50,
                "perspective_specific_notes": (
                    "OFI is short-horizon; degrades over hours."
                ),
            })
        if not hyps:
            hyps.append({
                "direction": "UNCERTAIN",
                "title": "No microstructure edge detected",
                "hypothesis_text": (
                    "No whale, OFI, or cross-platform divergence signals visible. "
                    "Market microstructure perspective contributes no edge here."
                ),
                "confidence": 0.50,
                "evidence_score": 0.15,
                "perspective_specific_notes": "Perspective inactive — no structural signals.",
            })
        return hyps
