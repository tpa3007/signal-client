"""Bridge helpers that package Forager output for Signal ingestion.

This module still refuses to write Signal data. It translates Forager memory
into a structured handoff object with explicit next actions and blockers.
"""
from __future__ import annotations

from forager.models import ResearchPacket, ResearchThread, SignalBridgePacket, SourceRawItem


def build_signal_bridge_packet(
    *,
    thread: ResearchThread,
    packet: ResearchPacket | None,
    source_items: list[SourceRawItem],
    blockers: list[str] | None = None,
) -> SignalBridgePacket:
    active_blockers = list(blockers or [])
    if packet is None:
        active_blockers.append("research_packet_missing")
    if not source_items:
        active_blockers.append("source_raw_items_missing")

    if packet is None:
        summary = f"Forager thread '{thread.seed_query}' has not produced a research packet yet."
        weak_signals = []
        hypotheses = []
        anomalies = []
        actions = ["build_research_packet"]
        packet_id = None
    else:
        summary = packet.summary
        weak_signals = packet.weak_signals
        hypotheses = packet.hypotheses
        anomalies = packet.anomalies
        actions = list(packet.recommended_signal_actions)
        packet_id = packet.id

    signal_next_actions = [
        "review_forager_packet",
        "promote_sources_to_signal_evidence_only_after_manual_or_tool_validation",
        "run_signal_pre_bet_gate_if_candidate_survives",
    ]
    if active_blockers:
        signal_next_actions.insert(0, "resolve_forager_blockers")

    return SignalBridgePacket(
        thread_id=thread.id,
        market_id=thread.market_id,
        forager_packet_id=packet_id,
        summary=summary,
        weak_signals=weak_signals,
        source_items=source_items,
        hypotheses=hypotheses,
        anomalies=anomalies,
        recommended_signal_actions=actions,
        signal_next_actions=signal_next_actions,
        blockers=list(dict.fromkeys(active_blockers)),
    )
