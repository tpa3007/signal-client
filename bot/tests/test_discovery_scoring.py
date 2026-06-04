"""Stage 2: auto-scoring component behaviour."""
from __future__ import annotations

import pytest

from lib.discovery_scoring import (
    attention_gap_score,
    combined_raw_discoverability,
    liquidity_score,
    spread_score,
    stale_price_score,
)


# --- attention_gap -----------------------------------------------------------

def test_attention_gap_zero_when_market_brand_new():
    # 0 days old, even with low volume → no attention gap claim
    assert attention_gap_score(volume=1000, market_age_days=0, liquidity=10000) == 0.0


def test_attention_gap_high_for_old_low_volume_with_liquidity():
    # 60 day old, $5k volume, $50k liquidity → very neglected
    s = attention_gap_score(volume=5000, market_age_days=60, liquidity=50000)
    assert s > 0.85


def test_attention_gap_zero_when_volume_saturated():
    s = attention_gap_score(volume=200_000, market_age_days=60, liquidity=50000)
    assert s == 0.0


def test_attention_gap_neutral_when_metadata_missing():
    s = attention_gap_score(volume=5000, market_age_days=None, liquidity=None)
    assert 0.0 < s < 1.0


# --- stale_price -------------------------------------------------------------

def test_stale_score_neutral_without_enough_history():
    assert stale_price_score([]) == 0.5
    assert stale_price_score(None) == 0.5
    assert stale_price_score([0.5, 0.5]) == 0.5  # only 2 points


def test_stale_score_high_for_flat_series():
    s = stale_price_score([0.30, 0.31, 0.30, 0.31, 0.30])
    assert s > 0.85


def test_stale_score_low_for_volatile_series():
    s = stale_price_score([0.30, 0.50, 0.10, 0.55, 0.15])
    assert s < 0.2


# --- liquidity / spread ------------------------------------------------------

def test_liquidity_score_saturates_at_moonshot_norm():
    assert liquidity_score(0) == 0.0
    assert liquidity_score(25000) == 1.0
    assert liquidity_score(50000) == 1.0  # capped


def test_liquidity_score_neutral_when_missing():
    assert liquidity_score(None) == 0.5


def test_spread_score_inverse_to_spread():
    assert spread_score(0.0) == 1.0
    assert spread_score(0.03) == pytest.approx(0.5, abs=0.01)
    assert spread_score(0.06) == 0.0  # equals MAX_SPREAD


def test_spread_score_neutral_when_missing():
    assert spread_score(None) == 0.5


# --- combined ----------------------------------------------------------------

def test_combined_score_aligned_with_inputs():
    perfect = combined_raw_discoverability(
        attention_gap=1.0, stale_price=1.0, liquidity=1.0, spread=1.0,
        strategy_bonus=1.0,
    )
    assert perfect == 100.0
    zero = combined_raw_discoverability(
        attention_gap=0.0, stale_price=0.0, liquidity=0.0, spread=0.0,
        strategy_bonus=0.0,
    )
    assert zero == 0.0


def test_combined_score_weights():
    # 0.40*1 + 0.25*0 + 0.10*0 + 0.10*0 + 0.15*0 = 40
    s = combined_raw_discoverability(
        attention_gap=1.0, stale_price=0.0, liquidity=0.0, spread=0.0,
    )
    assert s == 40.0


def test_combined_score_demotes_liquid_pre_priced_markets():
    """A Fed-style scenario: zero attention_gap but max liquidity + tight spread
    must score LOWER than a real gem with high attention_gap and so-so liquidity."""
    fed_like = combined_raw_discoverability(
        attention_gap=0.0, stale_price=0.5,
        liquidity=1.0, spread=1.0, strategy_bonus=0.1,
    )
    gem_like = combined_raw_discoverability(
        attention_gap=0.6, stale_price=0.5,
        liquidity=0.5, spread=0.5, strategy_bonus=0.3,
    )
    assert gem_like > fed_like
