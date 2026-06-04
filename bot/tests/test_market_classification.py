"""Vertical and thematic tag classification."""
from __future__ import annotations

from markets import _classify_vertical, classify_theme_tags


def test_maine_governor_primary_is_us_politics():
    q = "Will Nirav Shah win the 2026 Maine Governor Democratic primary election?"
    assert _classify_vertical(q) == "us_politics"
    assert "us_primary_2026" in classify_theme_tags(q)


def test_iran_markets_are_international_and_tagged():
    q = "Will Marco Rubio meet Iran by May 31?"
    assert _classify_vertical(q) == "international_geopolitics"
    assert "iran_cluster" in classify_theme_tags(q)


def test_gemini_reasoning_market_is_ai_launches():
    q = "Will Google announce a Gemini reasoning flagship model by May 22?"
    assert _classify_vertical(q) == "tech_business"
    assert "ai_launches" in classify_theme_tags(q)


def test_romanian_dissolution_is_not_science_space():
    q = "Romanian parliament dissolved by July 31?"
    assert _classify_vertical(q) == "international_geopolitics"


def test_iss_still_classifies_as_science_space():
    q = "Will NASA deorbit the ISS by 2030?"
    assert _classify_vertical(q) == "science_space"

def test_gubernatorial_does_not_trigger_ukraine_russia_tag():
    q = "Will Kim Kyung-soo win the 2026 Gyeongsangnam Province Gubernatorial Election?"
    tags = classify_theme_tags(q)
    assert "ukraine_russia" not in tags


def test_french_open_is_excluded_as_sports_market():
    q = "Will Elina Svitolina win the 2026 Women's French Open?"
    assert _classify_vertical(q) is None
