import run_command_g as g
import run_command_g2 as g2


def test_us_gdp_is_not_georgian_language_arbitrage():
    lang, score = g._detect_info_asymmetry(
        "Will US GDP growth in Q2 2026 be between 2.0% and 2.5%?"
    )
    assert lang is None
    assert score == 0.0


def test_b_queue_caps_near_deadline_battlefield_cluster():
    candidates = [
        {
            "condition_id": f"0x{i}",
            "question": q,
            "vertical": "international_geopolitics",
            "archetype": "general_research",
            "days_to_end": 6,
        }
        for i, q in enumerate(
            [
                "Will Russia enter Novooleksandrivka by May 31, 2026?",
                "Will Russia capture Huliaipilske by May 31?",
                "Iran closes its airspace by June 15?",
                "Will Oh Se-hoon win the 2026 Seoul Mayoral Election?",
                "Will Kim Kwan-young win the 2026 Jeonbuk Province Gubernatorial Election?",
            ]
        )
    ]
    selected = g2._select_b_queue_candidates(candidates, 4)
    questions = [c["question"] for c in selected]
    assert "Will Russia enter Novooleksandrivka by May 31, 2026?" in questions
    assert "Will Russia capture Huliaipilske by May 31?" not in questions
    assert len(selected) == 4


def test_tactical_battlefield_market_gets_penalty_without_primary_source():
    candidate = {
        "question": "Will Russia enter Novooleksandrivka by May 31, 2026?",
        "yes_price": 0.28,
        "days_to_end": 6,
    }
    score, breakdown = g2._hidden_gem_score(candidate, {})
    assert "battlefield_penalty" in breakdown
    assert score < 85


def test_extreme_language_catalyst_market_is_capped_without_specific_edge():
    candidate = {
        "question": "Will Min Hyung-bae win the 2026 Jeonnam-Gwangju mayoral election?",
        "yes_price": 0.992,
        "days_to_end": 8,
    }
    score, breakdown = g2._hidden_gem_score(candidate, {})
    assert "extreme_price_cap" in breakdown
    assert score <= g2.EXTREME_PRICE_EDGE_CAP


def test_percent_bracket_divergence_requires_matching_scope():
    divergence = {
        "name": "Who will win the 2026 Brazilian presidential election?",
        "pi_price": 0.70,
        "match_score": 0.9,
    }
    assert not g2._divergence_scope_matches(
        "Will Luiz Inácio Lula da Silva win the first round by 5-10%?",
        divergence,
    )
    assert g2._divergence_scope_matches(
        "Will Luiz Inácio Lula da Silva win the first round by 5-10%?",
        {"name": "Lula first round margin 5-10%", "match_score": 0.9},
    )


def test_divergence_scope_rejects_first_round_and_primary_general_winner_matches():
    assert not g2._divergence_scope_matches(
        "Will Iván Cepeda Castro win the 1st round of the 2026 Colombian presidential election?",
        {"name": "Who will win the 2026 Colombian presidential election? — Iván Cepeda"},
    )
    assert not g2._divergence_scope_matches(
        "Will Steve Hilton finish first in the 2026 California Governor primary election?",
        {"name": "Who will win the 2026 election for governor of California? — Steve Hilton"},
    )
    assert g2._divergence_scope_matches(
        "Will Keiko Fujimori win the 2026 Peruvian presidential election?",
        {"name": "Who will win the 2026 Peruvian presidential election? — Keiko Fujimori"},
    )


def test_divergence_scope_rejects_country_mismatch():
    assert not g2._divergence_scope_matches(
        "Will Trump visit Pakistan by May 31?",
        {"name": "Will Trump visit Greenland in 2026?", "match_score": 0.8},
    )


def test_correlated_event_key_groups_same_korean_race_not_all_governors():
    kim = g2._correlated_event_key(
        "Will Kim Kwan-young win the 2026 Jeonbuk Province Gubernatorial Election?"
    )
    lee = g2._correlated_event_key(
        "Will Lee Won-taek win the 2026 Jeonbuk Province Gubernatorial Election?"
    )
    jeju = g2._correlated_event_key(
        "Will Wi Seong-gon win the 2026 Jeju Province Gubernatorial Election?"
    )
    assert kim == lee
    assert kim != jeju


def test_g2_rejects_language_points_for_macro_brackets_and_generic_diplomacy():
    macro = {
        "question": "Will China GDP growth in Q2 2026 be between 4.9% and 5.2%?",
        "yes_price": 0.32,
        "days_to_end": 52,
    }
    score, breakdown = g2._hidden_gem_score(macro, {})
    assert "lang" not in breakdown
    assert "lang_rejected" in breakdown
    assert score < 60

    generic_meeting = {
        "question": "Israel x Lebanon diplomatic meeting by May 31?",
        "yes_price": 0.64,
        "days_to_end": 5,
    }
    score, breakdown = g2._hidden_gem_score(generic_meeting, {})
    assert "lang" not in breakdown
    assert "lang_rejected" in breakdown
    assert "geopolitical_tail_cap" in breakdown
    assert score <= g2.GEOPOLITICAL_TAIL_EDGE_CAP


def test_geopolitical_tail_cap_blocks_plausibility_as_edge():
    candidate = {
        "question": "Iran x Oman Strait of Hormuz agreement by June 15?",
        "yes_price": 0.285,
        "days_to_end": 20,
    }
    score, breakdown = g2._hidden_gem_score(candidate, {})
    assert "geopolitical_tail_cap" in breakdown
    assert score <= g2.GEOPOLITICAL_TAIL_EDGE_CAP


def test_g2_promotes_golden_archetype_suspicions():
    private_market = {
        "question": "Will OpenAI's valuation hit (LOW) $800B by December 31?",
        "yes_price": 0.505,
        "days_to_end": 220,
    }
    score, breakdown = g2._hidden_gem_score(private_market, {})
    assert "provider_mechanics" in breakdown
    assert score >= g2.PRIVATE_PROVIDER_MECHANICS

    central_bank = {
        "question": "Bank of England increases interest rates by 25 bps after June 2026 meeting?",
        "yes_price": 0.035,
        "days_to_end": 23,
    }
    score, breakdown = g2._hidden_gem_score(central_bank, {})
    assert "central_bank" in breakdown
    assert score >= g2.CENTRAL_BANK_SEQUENCE

    clause = {
        "question": "Trump out as President before GTA VI?",
        "yes_price": 0.505,
        "days_to_end": 67,
    }
    score, breakdown = g2._hidden_gem_score(clause, {})
    assert "resolution_clause" in breakdown
    assert score >= g2.RESOLUTION_CLAUSE_MECHANICS

    diplomacy = {
        "question": "Will Trump speak to Vladimir Putin in May?",
        "yes_price": 0.24,
        "days_to_end": 6,
    }
    score, breakdown = g2._hidden_gem_score(diplomacy, {})
    assert "lang" not in breakdown
    assert "lang_rejected" in breakdown
    assert score < 60


def test_non_research_weather_market_is_rejected():
    candidate = {"question": "Will the highest temperature in Busan be 23°C on May 26?"}
    assert g2._non_research_market_reason(candidate) == "weather_or_sensor_market"


def test_b_queue_caps_russia_ukraine_peace_cluster():
    candidates = [
        {
            "condition_id": "0x1",
            "question": "Will Zelenskyy talk to Putin by December 31?",
            "vertical": "international_geopolitics",
            "archetype": "open_world_event",
        },
        {
            "condition_id": "0x2",
            "question": "Russia x Ukraine ceasefire by December 31, 2026?",
            "vertical": "international_geopolitics",
            "archetype": "open_world_event",
        },
        {
            "condition_id": "0x3",
            "question": "China x Philippines military clash before 2027?",
            "vertical": "international_geopolitics",
            "archetype": "open_world_event",
        },
    ]
    selected = g2._select_b_queue_candidates(candidates, 3)
    questions = [c["question"] for c in selected]
    assert len([q for q in questions if "Russia" in q or "Zelenskyy" in q]) == 1


def test_rank_context_marks_g2_as_anomaly_not_edge():
    candidate = {
        "question": "Will OpenAI's valuation hit (HIGH) $950B by June 30?",
        "yes_price": 0.37,
        "archetype": "private_market_valuation",
        "gem_breakdown": {"metaculus": "+40 METACULUS(Δ20%)"},
        "private_market_mechanics": {"metric": "NPM Price"},
    }
    frame = g2._rank_context(candidate)
    assert any("cross-platform" in reason for reason in frame["why_ranked"])
    assert any("not an operator probability" in reason for reason in frame["why_not_edge_yet"])
    assert any("Provider metric" in reason for reason in frame["what_must_be_true_for_edge"])
