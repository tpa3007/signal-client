import run_command_r as r


def test_reason_candidate_private_market_requires_operator_review():
    candidate = {
        "priority": "P0",
        "condition_id": "0x1",
        "question": "Will OpenAI's valuation hit (HIGH) $950B by June 30?",
        "yes_price": 0.37,
        "private_market_mechanics": {
            "threshold": "$950B",
            "direction": ">=",
        },
    }
    out = r._reason_candidate(candidate)
    assert out["reasoning_memo"]["archetype"] == "private_market_valuation"
    assert out["requires_operator_review"] is True
    assert out["operator_review"]["approved_for_d"] is False
    assert "current_or_recent_provider_mark" in out["research_plan"]["required_evidence"]
    assert out["research_plan"]["edge_thesis"]["edge_type"] == "mechanical_provider_rule"
    assert out["reasoning_memo"]["edge_thesis"]["approval_status"] == "operator_required"
    mechanics = out["research_plan"]["market_mechanics"]
    assert mechanics["canonical_source"]
    assert mechanics["verification_status"] == "operator_required"
    assert "deadline_timezone" in mechanics["must_verify_before_b"]


def test_reason_candidate_election_local_plan_has_local_sources():
    candidate = {
        "priority": "P0",
        "condition_id": "0x2",
        "question": "Will the People Power Party win 4 seats?",
        "yes_price": 0.091,
        "local_language": "Korean",
    }
    out = r._reason_candidate(candidate)
    assert out["reasoning_memo"]["archetype"] == "election_local_asymmetry"
    assert any("Local-language" in x for x in out["reasoning_memo"]["source_plan"])
    assert out["seed_query"]
    assert out["operator_review"]["market_mechanics_verified"] is False


def test_scoring_archetype_does_not_block_election_plan():
    candidate = {
        "priority": "P0",
        "condition_id": "0x3",
        "question": "Will Keiko Fujimori win the 2026 Peruvian presidential election?",
        "yes_price": 0.755,
        "archetype": "stale_catalyst",
        "suggested_side": "YES",
    }
    out = r._reason_candidate(candidate)
    assert out["reasoning_memo"]["archetype"] == "election_local_asymmetry"
    assert "local election mechanics" in out["reasoning_memo"]["resolution_read"]


def test_prime_minister_market_gets_political_election_plan():
    candidate = {
        "priority": "P0",
        "condition_id": "0x4",
        "question": "Will Benjamin Netanyahu be the next Prime Minister of Israel?",
        "yes_price": 0.355,
        "local_language": "Hebrew",
    }
    out = r._reason_candidate(candidate)
    assert out["reasoning_memo"]["archetype"] == "election_local_asymmetry"
    assert "candidate registry" in " ".join(out["reasoning_memo"]["source_plan"]).lower()


def test_diplomatic_visit_market_gets_schedule_plan():
    candidate = {
        "priority": "P0",
        "condition_id": "0x5",
        "question": "Will Trump visit Pakistan by May 31?",
        "yes_price": 0.006,
        "local_language": "Urdu",
    }
    out = r._reason_candidate(candidate)
    assert out["reasoning_memo"]["archetype"] == "diplomatic_visit_or_meeting"
    assert "official_schedule_or_host_source_checked" in out["research_plan"]["required_evidence"]


def test_extreme_price_edge_thesis_carries_anti_signal_flag():
    candidate = {
        "priority": "P0",
        "condition_id": "0x6",
        "question": "Will a cheap lottery event happen by May 31?",
        "yes_price": 0.012,
        "suggested_side": "YES",
    }
    out = r._reason_candidate(candidate)
    flags = out["research_plan"]["edge_thesis"]["anti_signal_flags"]
    assert "cheap_lottery_risk" in flags
    assert "near_deadline_is_not_edge" in flags


def test_central_bank_market_gets_policy_sequence_plan_before_meeting_plan():
    candidate = {
        "priority": "P0",
        "condition_id": "0x7",
        "question": "No change in the Selic rate after Bank of Brazil’s June 2026 meeting?",
        "yes_price": 0.098,
        "suggested_side": "YES",
    }
    out = r._reason_candidate(candidate)
    assert out["reasoning_memo"]["archetype"] == "central_bank_sequence"
    assert "official_meeting_and_rate_action_verified" in out["research_plan"]["required_evidence"]
    assert "policy decision" in out["reasoning_memo"]["resolution_read"]
    assert not any("travel" in x.lower() for x in out["reasoning_memo"]["source_plan"])


def test_private_market_threshold_is_parsed_from_question():
    candidate = {
        "priority": "P0",
        "condition_id": "0x8",
        "question": "Will Stripe's valuation hit (HIGH) $190B by June 30?",
        "yes_price": 0.205,
    }
    out = r._reason_candidate(candidate)
    decisive = " ".join(out["reasoning_memo"]["decisive_questions"])
    assert ">= $190B" in decisive
    assert "? market threshold" not in decisive


def test_private_market_low_bucket_is_still_hit_threshold():
    candidate = {
        "priority": "P0",
        "condition_id": "0x9",
        "question": "Will Canva's valuation hit (LOW) $41B by June 30?",
        "yes_price": 0.745,
    }
    out = r._reason_candidate(candidate)
    decisive = " ".join(out["reasoning_memo"]["decisive_questions"])
    assert ">= $41B" in decisive
    assert "<= $41B" not in decisive
