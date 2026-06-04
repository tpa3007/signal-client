import run_command_m as m


def test_macro_language_only_market_is_not_b_candidate():
    candidate = {
        "question": "Will South Korea GDP growth in Q2 2026 be between 2.0% and 2.4%?",
        "yes_price": 0.21,
        "spread": 0.08,
        "days_to_end": 59,
        "local_language": "Korean (Korea Herald, Yonhap)",
        "first_queries": [
            "Will South Korea GDP growth in Q2 2026 be between 2.0% and 2.4% Korea Herald Yonhap 2026",
            "South Korea election polls 2026 official results",
        ],
        "gem_breakdown": {"lang": "+60 HIGH_LANG(korean) in 20-65% range"},
    }
    review = m.review_candidate(candidate)
    assert review["status"] != "b_candidate"
    assert any("macro bracket" in flag for flag in review["red_flags"])
    assert any("contaminated" in flag for flag in review["red_flags"])


def test_local_election_with_price_and_catalyst_can_pass():
    candidate = {
        "question": "Will Kim Kwan-young win the 2026 Jeonbuk Province Gubernatorial Election?",
        "yes_price": 0.43,
        "spread": 0.02,
        "days_to_end": 10,
        "local_language": "Korean",
        "gem_breakdown": {"lang": "+60 HIGH_LANG(korean) in 20-65% range"},
    }
    review = m.review_candidate(candidate)
    assert review["status"] == "b_candidate"
    assert review["operator_score"] >= 5


def test_build_shortlist_caps_same_cluster():
    candidates = [
        {
            "condition_id": "0x1",
            "question": "Will Kim Kwan-young win the 2026 Jeonbuk Province Gubernatorial Election?",
            "yes_price": 0.43,
            "spread": 0.02,
            "days_to_end": 10,
            "local_language": "Korean",
            "gem_score": 60,
        },
        {
            "condition_id": "0x2",
            "question": "Will Lee Won-taek win the 2026 Jeonbuk Province Gubernatorial Election?",
            "yes_price": 0.17,
            "spread": 0.02,
            "days_to_end": 10,
            "local_language": "Korean",
            "gem_score": 59,
        },
    ]
    selected, reviewed = m.build_shortlist(candidates, limit=5)
    assert len(reviewed) == 2
    assert len(selected) == 1


def test_divergence_side_overrides_formula_side():
    candidate = {
        "condition_id": "0x3",
        "question": "Will Keiko Fujimori win the 2026 Peruvian presidential election?",
        "yes_price": 0.755,
        "spread": 0.01,
        "days_to_end": 13,
        "local_language": "English",
        "suggested_side": "NO",
        "predictit_divergence": {
            "pi_price": 0.85,
            "divergence": 0.095,
            "match_score": 0.83,
        },
        "gem_score": 45,
    }
    selected, _ = m.build_shortlist([candidate], limit=1)
    assert selected[0]["suggested_side"] == "YES"
    assert any("M overrides" in flag for flag in selected[0]["manual_shortlist"]["red_flags"])


def test_watch_fallback_keeps_cycle_alive_when_no_direct_b_candidates():
    candidates = [
        {
            "condition_id": "0x4",
            "question": "Will AfD win an absolute majority of seats in Sachsen-Anhalt?",
            "yes_price": 0.4,
            "spread": 0.02,
            "days_to_end": 104,
            "local_language": "German",
            "gem_score": 35,
        }
    ]
    selected, reviewed = m.build_shortlist(candidates, limit=5)
    assert reviewed[0]["manual_shortlist"]["status"] == "watch"
    assert len(selected) == 1
    assert selected[0]["manual_shortlist"]["queue_reason"] == "watch_fallback_operator_review_required"


def test_divergence_researchable_price_promotes_candidate():
    candidate = {
        "condition_id": "0x5",
        "question": "Will Benjamin Netanyahu be the next Prime Minister of Israel?",
        "yes_price": 0.355,
        "spread": 0.01,
        "days_to_end": 220,
        "local_language": "Hebrew",
        "suggested_side": "YES",
        "predictit_divergence": {
            "pi_price": 0.68,
            "divergence": 0.325,
            "match_score": 0.625,
        },
        "gem_score": 100,
    }
    review = m.review_candidate(candidate)
    assert review["status"] == "b_candidate"
    assert review["operator_score"] >= 5


def test_low_match_divergence_does_not_promote_candidate():
    candidate = {
        "condition_id": "0x8",
        "question": "Will Trump visit Pakistan by May 31?",
        "yes_price": 0.006,
        "spread": 0.01,
        "days_to_end": 6,
        "predictit_divergence": {
            "pi_price": 0.25,
            "divergence": 0.24,
            "match_score": 0.5,
        },
        "gem_score": 45,
    }
    review = m.review_candidate(candidate)
    assert review["status"] == "reject"
    assert not any("divergence-implied" in flag for flag in review["green_flags"])


def test_researchable_price_alone_is_not_concrete_edge_path():
    candidate = {
        "condition_id": "0xb",
        "question": "China x Philippines military clash before 2027?",
        "yes_price": 0.215,
        "spread": 0.01,
        "days_to_end": 220,
        "gem_score": 60,
    }
    review = m.review_candidate(candidate)
    assert review["status"] == "reject"
    assert any("no concrete edge path" in flag for flag in review["red_flags"])


def test_watch_fallback_prefers_researchable_price_over_extreme_price():
    candidates = [
        {
            "condition_id": "0x6",
            "question": "Will Candidate A win a local mayoral election?",
            "yes_price": 0.99,
            "spread": 0.01,
            "days_to_end": 8,
            "local_language": "Korean",
            "gem_score": 45,
        },
        {
            "condition_id": "0x7",
            "question": "Will AfD win an absolute majority of seats in Sachsen-Anhalt?",
            "yes_price": 0.4,
            "spread": 0.02,
            "days_to_end": 104,
            "local_language": "German",
            "gem_score": 35,
        },
    ]
    selected, _ = m.build_shortlist(candidates, limit=1)
    assert selected[0]["condition_id"] == "0x7"


def test_extreme_local_language_market_without_specific_edge_is_rejected():
    candidate = {
        "condition_id": "0x9",
        "question": "Will Min Hyung-bae win the 2026 Jeonnam-Gwangju mayoral election?",
        "yes_price": 0.992,
        "spread": 0.01,
        "days_to_end": 8,
        "local_language": "Korean",
        "gem_score": 45,
    }
    review = m.review_candidate(candidate)
    assert review["status"] == "reject"
    assert any("extreme price" in flag for flag in review["red_flags"])


def test_golden_archetype_candidates_can_pass_to_b():
    central_bank = {
        "condition_id": "0xc",
        "question": "Bank of England increases interest rates by 25 bps after June 2026 meeting?",
        "yes_price": 0.035,
        "spread": 0.01,
        "days_to_end": 23,
        "gem_score": 65,
    }
    review = m.review_candidate(central_bank)
    assert review["status"] in {"b_candidate", "watch"}
    assert any("central-bank" in flag for flag in review["green_flags"])

    private_market = {
        "condition_id": "0xd",
        "question": "Will OpenAI's valuation hit (LOW) $800B by December 31?",
        "yes_price": 0.505,
        "spread": 0.01,
        "days_to_end": 221,
        "gem_score": 45,
    }
    review = m.review_candidate(private_market)
    assert review["status"] == "b_candidate"
    assert any("private-market" in flag for flag in review["green_flags"])


def test_watch_fallback_does_not_select_extreme_without_specific_edge():
    candidates = [
        {
            "condition_id": "0xa",
            "question": "Will Hezbollah win the most seats in the 2026 Lebanese parliamentary election?",
            "yes_price": 0.014,
            "spread": 0.01,
            "days_to_end": 8,
            "local_language": "Arabic",
            "gem_score": 45,
        }
    ]
    selected, reviewed = m.build_shortlist(candidates, limit=5)
    assert reviewed[0]["manual_shortlist"]["status"] == "reject"
    assert selected == []
