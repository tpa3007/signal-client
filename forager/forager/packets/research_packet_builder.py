"""Research packet builder for Signal handoff."""
from __future__ import annotations

from urllib.parse import urlparse

from forager.models import Anomaly, Hypothesis, ResearchPacket, ResearchThread, WeakSignal
from forager.scoring.packet_value import label_packet_value, score_packet_signal_value
from forager.scoring.weirdness import HIGH_CREDIBILITY_DOMAINS, score_signal_relevance, score_thread_weirdness


def recommended_signal_actions(*, weirdness: float, signal_relevance: float, anomaly_count: int, hypothesis_count: int, signal_decision_value: float) -> list[str]:
    actions: list[str] = []
    if signal_decision_value >= 0.70:
        actions.append("promote_to_dossier")
    if weirdness >= 0.65:
        actions.append("request_more_research")
        actions.append("increase_monitoring")
    if signal_relevance >= 0.55 and hypothesis_count:
        actions.append("rerun_probability_model")
    if anomaly_count >= 2:
        actions.append("manual_review")
    if signal_decision_value < 0.20 and not actions:
        actions.append("do_nothing")
    if not actions:
        actions.append("do_nothing")
    return list(dict.fromkeys(actions))


def _count_high_credibility_sources(source_urls: list[str]) -> int:
    count = 0
    for url in source_urls:
        domain = urlparse(url).netloc.lower()
        if any(d in domain for d in HIGH_CREDIBILITY_DOMAINS):
            count += 1
    return count


def build_research_packet(
    *,
    thread: ResearchThread,
    source_scores: list[float],
    lenses: list[str],
    hypotheses: list[Hypothesis],
    anomalies: list[Anomaly],
    source_urls: list[str] | None = None,
    kill_criteria: list[str] | None = None,
    kill_criteria_covered: int | None = None,
    disconfirming_sources: list[str] | None = None,
) -> ResearchPacket:
    weirdness = score_thread_weirdness(source_scores, lenses)
    signal_relevance = score_signal_relevance(
        market_id=thread.market_id,
        seed_query=thread.seed_query,
        source_count=len(source_scores),
        anomaly_count=len(anomalies),
    )

    urls = source_urls or []
    kill_criteria_list = kill_criteria or []
    disconf_sources = disconfirming_sources or []
    disconfirming_found = len(disconf_sources) > 0
    high_cred_count = _count_high_credibility_sources(urls)

    avg_confidence = sum(h.confidence for h in hypotheses) / len(hypotheses) if hypotheses else 0.0

    # kc_covered: how many criteria returned relevant search results.
    # If not explicitly provided (legacy callers), assume all criteria were covered.
    kc_total = len(kill_criteria_list)
    kc_covered = (
        kill_criteria_covered
        if kill_criteria_covered is not None
        else kc_total
    )

    signal_decision_value = score_packet_signal_value(
        hypothesis_count=len(hypotheses),
        avg_hypothesis_confidence=avg_confidence,
        source_count=len(urls),
        high_credibility_source_count=high_cred_count,
        kill_criteria_covered=kc_covered,
        kill_criteria_total=kc_total,
        disconfirming_found=disconfirming_found,
        anomaly_count=len(anomalies),
        signal_relevance=signal_relevance,
    )

    weak_signals = [
        WeakSignal(
            title=a.anomaly_type.replace("_", " ").title(),
            description=a.description,
            weirdness_score=a.weirdness_score,
            evidence_ids=list(a.evidence.get("source_ids", [])),
        )
        for a in sorted(anomalies, key=lambda item: item.weirdness_score, reverse=True)[:5]
    ]

    summary = (
        f"Forager explored '{thread.seed_query}' and found {len(weak_signals)} weak signals, "
        f"{len(hypotheses)} hypotheses, and {len(anomalies)} anomalies. "
        f"Signal decision value: {label_packet_value(signal_decision_value)} ({signal_decision_value:.2f}). "
        "This packet is not a trading decision; Signal must verify and score it."
    )

    return ResearchPacket(
        market_id=thread.market_id,
        thread_id=thread.id,
        summary=summary,
        weak_signals=weak_signals,
        hypotheses=hypotheses,
        anomalies=anomalies,
        recommended_signal_actions=recommended_signal_actions(
            weirdness=weirdness,
            signal_relevance=signal_relevance,
            anomaly_count=len(anomalies),
            hypothesis_count=len(hypotheses),
            signal_decision_value=signal_decision_value,
        ),
        aggregate_weirdness_score=weirdness,
        aggregate_signal_relevance_score=signal_relevance,
        aggregate_confidence=avg_confidence,
        signal_decision_value=signal_decision_value,
        signal_decision_value_label=label_packet_value(signal_decision_value),
        kill_criteria=kill_criteria_list,
        disconfirming_found=disconfirming_found,
        disconfirming_sources=disconf_sources,
    )
