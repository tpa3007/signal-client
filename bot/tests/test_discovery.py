"""Stage 2: discovery strategies — filter correctness on synthetic candidates."""
from __future__ import annotations

import pytest

import config
from lib.discovery import (
    cheap_optionality,
    compounder_research_candidate,
    low_volume_research_sweetspot,
    stale_price,
)


def _md(**overrides) -> dict:
    base = {
        "condition_id": "0xa", "question": "q", "vertical": "geopolitics",
        "yes_price": 0.45, "volume": 15000, "liquidity": 30000,
        "spread": 0.03, "days_to_end": 30, "end_date": "2026-08-01T00:00:00Z",
        "first_seen_at": "2026-03-01T00:00:00Z",
    }
    base.update(overrides)
    return base


# --- low_volume_research_sweetspot -------------------------------------------

def test_sweetspot_matches_canonical_case():
    assert low_volume_research_sweetspot(_md(volume=15000, days_to_end=30, spread=0.03)) is True


def test_sweetspot_rejects_too_high_volume():
    assert low_volume_research_sweetspot(_md(volume=50_000)) is False  # > 30k


def test_sweetspot_rejects_too_low_volume():
    assert low_volume_research_sweetspot(_md(volume=2000)) is False  # < 5k


def test_sweetspot_rejects_short_timeline():
    assert low_volume_research_sweetspot(_md(days_to_end=7)) is False


def test_sweetspot_rejects_long_timeline():
    assert low_volume_research_sweetspot(_md(days_to_end=120)) is False


def test_sweetspot_rejects_wide_spread():
    assert low_volume_research_sweetspot(_md(spread=0.10)) is False


def test_sweetspot_rejects_extreme_prices():
    assert low_volume_research_sweetspot(_md(yes_price=0.05)) is False
    assert low_volume_research_sweetspot(_md(yes_price=0.95)) is False


# --- stale_price -------------------------------------------------------------

def test_stale_matches_flat_series():
    series = [0.30, 0.31, 0.30, 0.31, 0.30, 0.30]  # stdev ≈ 0.005
    assert stale_price(_md(volume=20000), series) is True


def test_stale_rejects_volatile_series():
    series = [0.30, 0.45, 0.20, 0.50, 0.25, 0.40]  # high stdev
    assert stale_price(_md(volume=20000), series) is False


def test_stale_rejects_young_market():
    series = [0.30, 0.30, 0.30, 0.30]
    young = _md(volume=20000, first_seen_at="2026-05-10T00:00:00Z")  # < 30 days old
    assert stale_price(young, series) is False


def test_stale_rejects_low_volume_market():
    series = [0.30, 0.30, 0.30, 0.30]
    assert stale_price(_md(volume=2000), series) is False


def test_stale_returns_false_without_enough_history():
    assert stale_price(_md(volume=20000), []) is False
    assert stale_price(_md(volume=20000), [0.30, 0.30]) is False  # only 2 points
    assert stale_price(_md(volume=20000), None) is False


# --- cheap_optionality -------------------------------------------------------

def test_cheap_opt_matches_powell_style():
    m = _md(yes_price=0.08, liquidity=15000, days_to_end=14)
    assert cheap_optionality(m) is True


def test_cheap_opt_matches_high_side():
    m = _md(yes_price=0.92, liquidity=15000, days_to_end=14)
    assert cheap_optionality(m) is True


def test_cheap_opt_rejects_mid_prices():
    assert cheap_optionality(_md(yes_price=0.40, liquidity=15000, days_to_end=14)) is False
    assert cheap_optionality(_md(yes_price=0.60, liquidity=15000, days_to_end=14)) is False


def test_cheap_opt_rejects_illiquid():
    m = _md(yes_price=0.08, liquidity=2000, days_to_end=14)
    assert cheap_optionality(m) is False


def test_cheap_opt_rejects_too_short_window():
    m = _md(yes_price=0.08, liquidity=15000, days_to_end=3)
    assert cheap_optionality(m) is False


def test_cheap_opt_rejects_heavily_traded_pre_priced_market():
    """The Fed-rate false-positive case: extreme price but $5M+ volume = consensus,
    not a gem. Volume ceiling kicks in."""
    m = _md(yes_price=0.98, volume=5_800_000, liquidity=500_000, days_to_end=29)
    assert cheap_optionality(m) is False


def test_cheap_opt_accepts_known_gems_under_volume_ceiling():
    """Khamenei / Paxton / Rubio-Iran style: $50-100k volume is fine."""
    khamenei_like = _md(yes_price=0.027, volume=85_000, liquidity=16_000, days_to_end=42)
    paxton_like = _md(yes_price=0.033, volume=75_000, liquidity=18_000, days_to_end=42)
    assert cheap_optionality(khamenei_like) is True
    assert cheap_optionality(paxton_like) is True

# --- compounder_research_candidate -----------------------------------------

def test_compounder_matches_mid_priced_yes_with_good_market_quality():
    m = _md(yes_price=0.55, volume=80_000, liquidity=20_000, spread=0.02, days_to_end=45)
    assert compounder_research_candidate(m) is True


def test_compounder_matches_mid_priced_no_side():
    m = _md(yes_price=0.72, volume=80_000, liquidity=20_000, spread=0.02, days_to_end=45)
    assert compounder_research_candidate(m) is True


def test_compounder_rejects_cheap_optionality_lane():
    m = _md(yes_price=0.08, volume=80_000, liquidity=20_000, spread=0.02, days_to_end=45)
    assert compounder_research_candidate(m) is False


def test_compounder_rejects_heavily_traded_consensus_market():
    m = _md(yes_price=0.48, volume=1_000_000, liquidity=120_000, spread=0.02, days_to_end=45)
    assert compounder_research_candidate(m) is False


def test_compounder_rejects_wide_spread():
    m = _md(yes_price=0.48, volume=80_000, liquidity=20_000, spread=0.10, days_to_end=45)
    assert compounder_research_candidate(m) is False
