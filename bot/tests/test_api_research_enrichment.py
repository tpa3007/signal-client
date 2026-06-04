"""API research enrichment workflow helpers."""
from __future__ import annotations

from tools.workflows import (
    _enrichment_decision,
    _gdelt_query_for_question,
    _guess_primary_entity,
    _office_from_question,
    _state_abbr_from_question,
)


def test_guess_primary_entity_from_candidate_question():
    q = "Will Ilie Bolojan be the next Prime Minister of Romania?"
    assert _guess_primary_entity(q) == "Ilie Bolojan"


def test_state_and_office_from_us_primary_question():
    q = "Will Angie Craig be the Democratic nominee for Senate in Minnesota?"
    assert _state_abbr_from_question(q) == "MN"
    assert _office_from_question(q) == "S"


def test_lmarena_market_requires_direct_leaderboard_snapshot():
    candidate = {"question": "Will Google have the #1 AI model?"}
    api = {"polymarket_details": {"description": "Resolves by LMArena leaderboard."}}
    decision = _enrichment_decision(candidate, api)
    assert decision["decision"] == "watch_only"
    assert "LMArena" in decision["blockers"][0]


def test_korean_local_race_marks_source_asymmetry():
    candidate = {"question": "Will Kim Kyung-soo win the 2026 Gyeongsangnam Province Gubernatorial Election?"}
    api = {"polymarket_details": {"description": "Election market."}}
    decision = _enrichment_decision(candidate, api)
    assert "local-language source asymmetry" in decision["reasons"][0]


def test_gdelt_query_sanitizes_market_wording():
    q = "Will Laura Gillen be the Democratic nominee for NY-04?"
    query = _gdelt_query_for_question(q, "Laura Gillen")
    assert "NY-04" not in query
    assert "Laura Gillen" in query


def test_gdelt_query_handles_hyphenated_korean_names():
    q = "Will Kim Kyung-soo win the 2026 Gyeongsangnam Province Gubernatorial Election?"
    query = _gdelt_query_for_question(q, "Kim Kyung-soo")
    assert "Kyung-soo" not in query
    assert "Kim Kyung soo" in query





def test_gdelt_query_avoids_short_numeric_tokens():
    q = "Will Laura Gillen be the Democratic nominee for NY-04?"
    query = _gdelt_query_for_question(q, "Laura Gillen")
    assert " 4 " not in f" {query} "
    assert "fourth district" in query


def test_gdelt_query_avoids_short_ai_token():
    q = "Will Google have the #1 AI model at the end of May 2026 (Style Control On)?"
    query = _gdelt_query_for_question(q, "Google Gemini")
    assert " AI " not in f" {query} "
    assert "artificial intelligence" in query
