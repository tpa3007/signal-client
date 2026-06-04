"""Stage 1: shrinkage-aware sizing."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import config
import db
import mcp_server  # ensures db.init runs
from lib.sizing import recommended_stake


def _seed_market(c, condition_id: str, vertical: str = "geopolitics",
                 end_date: str = "2026-06-15T00:00:00Z"):
    now = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT INTO markets (condition_id, question, slug, end_date,
                             first_seen_at, last_seen_at, vertical)
        VALUES (?, 'q', 's', ?, ?, ?, ?)
    """, (condition_id, end_date, now, now, vertical))


def _seed_position(c, condition_id: str, stake: float, end_date: str | None = None):
    now = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT INTO positions (condition_id, opened_at, intended_side,
                               intended_entry_price, intended_stake_usd,
                               stake_source, status, end_date)
        VALUES (?, ?, 'YES', 0.40, ?, 'paper', 'open', ?)
    """, (condition_id, now, stake, end_date))


def test_sizing_without_connection_skips_shrinkage(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "KELLY_FRACTION", 0.25)
    monkeypatch.setattr(config, "BET_MAX_USD", 100.0)
    monkeypatch.setattr(config, "BET_MIN_USD", 1.0)
    out = recommended_stake(edge=0.10, confidence=0.60)
    # base = 1000 * 0.25 * 0.10 * 0.60 = 15.0
    assert out["base"] == pytest.approx(15.0)
    assert out["shrinkage_factor"] == 1.0
    assert out["recommended"] == 15.0


def test_sizing_clamps_to_bet_min(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "BET_MIN_USD", 5.0)
    monkeypatch.setattr(config, "BET_MAX_USD", 100.0)
    monkeypatch.setattr(config, "KELLY_FRACTION", 0.25)
    out = recommended_stake(edge=0.01, confidence=0.50)  # raw $1.25, below min
    assert out["recommended"] == 5.0
    assert out["clamped"] is True


def test_sizing_clamps_to_bet_max(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "BET_MAX_USD", 30.0)
    monkeypatch.setattr(config, "BET_MIN_USD", 1.0)
    monkeypatch.setattr(config, "KELLY_FRACTION", 0.25)
    out = recommended_stake(edge=0.50, confidence=0.80)  # raw $100
    assert out["recommended"] == 30.0


def test_sizing_shrinkage_reduces_stake_under_sector_load(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "BET_MIN_USD", 1.0)
    monkeypatch.setattr(config, "BET_MAX_USD", 100.0)
    monkeypatch.setattr(config, "KELLY_FRACTION", 0.25)
    monkeypatch.setattr(config, "EXPOSURE_VERTICAL_CAP_PCT", 0.40)  # $400 cap
    monkeypatch.setattr(config, "EXPOSURE_ARCHETYPE_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_DEADLINE_WEEK_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_SINGLE_MARKET_CAP_PCT", 0.99)

    # No existing exposure -> full stake
    with db.connect() as c:
        _seed_market(c, "0xnew", "geopolitics")
        c.commit()
        out_clean = recommended_stake(
            edge=0.10, confidence=0.60, conn=c,
            condition_id="0xnew", vertical="geopolitics",
            primary_archetype=None, end_date="2026-09-01T00:00:00Z",
        )
    assert out_clean["shrinkage_factor"] == 1.0
    assert out_clean["recommended"] == pytest.approx(15.0)

    # Add $300 of existing geopolitics exposure (75% of $400 cap)
    with db.connect() as c:
        _seed_market(c, "0xexisting", "geopolitics")
        _seed_position(c, "0xexisting", stake=300.0)
        c.commit()
        out_loaded = recommended_stake(
            edge=0.10, confidence=0.60, conn=c,
            condition_id="0xnew", vertical="geopolitics",
            primary_archetype=None, end_date="2026-09-01T00:00:00Z",
        )
    # shrinkage = 1 - 0.75 = 0.25 -> raw = 15 * 0.25 = 3.75 -> above BET_MIN
    assert out_loaded["shrinkage_factor"] == pytest.approx(0.25)
    assert out_loaded["recommended"] == pytest.approx(3.75, abs=0.05)


def test_sizing_shrinkage_reduces_stake_under_theme_load(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "BET_MIN_USD", 1.0)
    monkeypatch.setattr(config, "BET_MAX_USD", 100.0)
    monkeypatch.setattr(config, "KELLY_FRACTION", 0.25)
    monkeypatch.setattr(config, "EXPOSURE_VERTICAL_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_ARCHETYPE_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_DEADLINE_WEEK_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_SINGLE_MARKET_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_THEME_CAP_PCT", 0.20)
    with db.connect() as c:
        _seed_market(c, "0xexisting", "international_geopolitics")
        _seed_market(c, "0xnew", "international_geopolitics")
        db.set_market_tags(c, condition_id="0xexisting", tags=["iran_cluster"])
        db.set_market_tags(c, condition_id="0xnew", tags=["iran_cluster"])
        _seed_position(c, "0xexisting", stake=150.0)
        c.commit()
        out = recommended_stake(
            edge=0.10, confidence=0.60, conn=c,
            condition_id="0xnew", vertical="international_geopolitics",
            primary_archetype=None, end_date="2026-09-01T00:00:00Z",
            theme_tags=["iran_cluster"],
        )
    assert out["shrinkage_factor"] == 0.25
    assert out["recommended"] == 3.75


def test_sizing_zero_edge_returns_min_stake(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BET_MIN_USD", 1.0)
    out = recommended_stake(edge=0.0, confidence=0.7)
    assert out["base"] == 0.0
    assert out["recommended"] == 1.0  # clamped to min


def test_sizing_negative_inputs_treated_as_zero():
    out = recommended_stake(edge=-0.05, confidence=-0.5)
    assert out["base"] == 0.0
