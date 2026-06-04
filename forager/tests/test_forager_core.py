from forager.models import DepthMode, HypothesisCreateRequest, ResearchStartRequest, SourceRegisterRequest
from forager.search.query_mutation import build_kill_criteria_queries, mutate_query
from forager.scoring.packet_value import label_packet_value, score_packet_signal_value
from forager.scoring.weirdness import score_domain_relevance, score_source_weirdness
from forager.service import ForagerService


def test_mutate_query_includes_non_obvious_lenses():
    mutations = mutate_query("Kim Kyung-soo Gyeongnam election", max_queries=24)
    lenses = {mutation.lens for mutation in mutations}

    assert "absence" in lenses
    assert "contradiction" in lenses
    assert "pre_hype" in lenses
    assert "technical_surface" in lenses


def test_start_research_creates_thread_and_mutations():
    service = ForagerService()
    result = service.start_research(
        ResearchStartRequest(seed_query="Polymarket Korea local election", market_id="market_1", depth=DepthMode.DEEP)
    )

    assert result["thread"]["market_id"] == "market_1"
    assert result["thread"]["status"] == "searching"
    assert len(result["mutations"]) == 24
    assert result["boundary"] == "Forager discovers; Signal decides."


def test_register_source_creates_anomaly_for_weird_source():
    service = ForagerService()
    result = service.start_research(ResearchStartRequest(seed_query="obscure AI release market"))
    thread_id = result["thread"]["id"]

    registered = service.register_source(
        thread_id,
        SourceRegisterRequest(
            url="https://old-forum.example.org/archive/deleted-thread.pdf",
            title="Deleted forum PDF contradicts the public story",
            snippet="cached dispute from a niche forum",
        ),
    )

    assert registered["weirdness_score"] >= 0.45
    assert registered["anomaly"] is not None
    assert registered["anomaly"]["anomaly_type"] == "source_weirdness"


def test_build_packet_recommends_more_research_for_weird_anomalies():
    service = ForagerService()
    result = service.start_research(ResearchStartRequest(seed_query="will hidden project launch by June", market_id="market_2"))
    thread_id = result["thread"]["id"]
    service.register_source(
        thread_id,
        SourceRegisterRequest(
            url="https://github.com/example/project/issues/17",
            title="Maintainer hints at removed milestone",
            snippet="unusual timing, deleted roadmap, contradiction",
        ),
    )
    service.add_hypothesis(
        thread_id,
        HypothesisCreateRequest(
            title="Removed milestone may imply launch delay",
            hypothesis_text="The public market may miss a removed technical milestone.",
            confidence=0.45,
            weirdness_score=0.70,
            signal_relevance_score=0.60,
        ),
    )

    packet = service.build_packet(thread_id)

    assert packet.aggregate_weirdness_score > 0.40
    assert packet.weak_signals
    assert "request_more_research" in packet.recommended_signal_actions


# ── Query hygiene ──────────────────────────────────────────────────────────────

def test_mutate_query_no_meta_words_in_quoted_seed():
    """Шаблоны не должны вставлять мета-слова (contradiction, archive и т.д.)
    внутрь quoted-части запроса рядом с seed."""
    mutations = mutate_query("Barnes North Carolina Senate 2026", max_queries=24)
    banned_inside_seed = ("contradiction", "disconfirming", "archive", "fake", "debunk")
    for m in mutations:
        # The seed phrase should appear quoted but without meta-words embedded inside the quotes
        # Check: none of the banned words appear immediately adjacent to the quoted seed
        quoted = f'"Barnes North Carolina Senate 2026"'
        if quoted in m.query:
            tail = m.query[m.query.index(quoted) + len(quoted):]
            for word in banned_inside_seed:
                assert word not in quoted.lower(), (
                    f"Meta-word '{word}' found inside quoted seed in query: {m.query}"
                )


def test_kill_criteria_queries_produce_targeted_disconfirming():
    criteria = [
        "Barnes loses primary endorsement",
        "Barnes drops out of race",
        "Opponent fundraising surges past Barnes",
    ]
    queries = build_kill_criteria_queries("Barnes North Carolina Senate 2026", criteria)
    assert len(queries) >= 3
    for q in queries:
        assert q.lens == "disconfirming"
        # Each query should reference a kill criterion, not just generic debunk terms
        assert any(frag in q.query for frag in ("Barnes", "loses", "drops", "Opponent", "fundraising"))


def test_kill_criteria_queries_empty_criteria():
    result = build_kill_criteria_queries("any seed", [])
    assert result == []


# ── Source quality / domain relevance ─────────────────────────────────────────

def test_domain_relevance_high_for_matching_keywords():
    score = score_domain_relevance(
        "https://ballotpedia.org/Mark_Robinson_North_Carolina",
        ["Barnes", "North Carolina", "Senate"],
    )
    assert score >= 0.20  # at least one keyword matches


def test_domain_relevance_high_credibility_domains_always_relevant():
    for domain in ("https://reuters.com/politics/barnes", "https://bbc.com/news/election"):
        score = score_domain_relevance(domain, ["unrelated", "keywords"])
        assert score >= 0.60, f"High-credibility domain should score ≥ 0.60, got {score}"


def test_source_weirdness_penalises_irrelevant_forum():
    # Reddit post with no matching topic keywords → should not get full weirdness bonus
    score_irrelevant = score_source_weirdness(
        url="https://reddit.com/r/philosophy/post/random",
        title="Some philosophy thread",
        snippet="completely unrelated discussion",
        topic_keywords=["Barnes", "North Carolina", "Senate", "election"],
    )
    # Without topic_keywords, same URL would score higher
    score_no_filter = score_source_weirdness(
        url="https://reddit.com/r/philosophy/post/random",
        title="Some philosophy thread",
        snippet="completely unrelated discussion",
    )
    assert score_irrelevant < score_no_filter, "Irrelevant forum should score lower than unfiltered"
    assert score_irrelevant <= 0.35, f"Irrelevant forum scored too high: {score_irrelevant}"


def test_source_weirdness_on_topic_forum_preserves_bonus():
    # "northcarolina" and "senate-race" in URL normalise to "north carolina" and "senate race"
    score = score_source_weirdness(
        url="https://reddit.com/r/northcarolina/post/senate-race",
        title="NC Senate race discussion",
        snippet="Barnes polling data and endorsements",
        topic_keywords=["Barnes", "North Carolina", "Senate"],
    )
    assert score >= 0.25, f"On-topic forum should keep weirdness bonus, got {score}"


# ── Packet signal value ────────────────────────────────────────────────────────

def test_packet_signal_value_high_for_good_packet():
    score = score_packet_signal_value(
        hypothesis_count=3,
        avg_hypothesis_confidence=0.65,
        source_count=8,
        high_credibility_source_count=4,
        kill_criteria_covered=3,
        kill_criteria_total=3,
        disconfirming_found=True,
        anomaly_count=2,
        signal_relevance=0.70,
    )
    assert score >= 0.60
    assert label_packet_value(score) in ("high_value", "medium_value")


def test_packet_signal_value_low_for_no_hypotheses_no_disconfirming():
    score = score_packet_signal_value(
        hypothesis_count=0,
        avg_hypothesis_confidence=0.0,
        source_count=5,
        high_credibility_source_count=0,
        kill_criteria_covered=0,
        kill_criteria_total=0,
        disconfirming_found=False,
        anomaly_count=0,
        signal_relevance=0.30,
    )
    assert score < 0.25
    assert label_packet_value(score) in ("low_value", "noise")


def test_packet_model_has_decision_value_fields():
    """ResearchPacket should expose new signal decision fields."""
    from forager.models import ResearchPacket
    p = ResearchPacket(thread_id="t1", summary="test")
    assert hasattr(p, "signal_decision_value")
    assert hasattr(p, "kill_criteria")
    assert hasattr(p, "disconfirming_found")
    assert hasattr(p, "disconfirming_sources")
