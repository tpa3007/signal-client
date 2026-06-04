"""Stage 1: portfolio exposure aggregation, caps, MCP tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import config
import db
import mcp_server  # ensures all tools register
from lib.exposure import open_exposure, check_exposure


def _seed_market(c, condition_id: str, vertical: str = "geopolitics",
                 end_date: str = "2026-06-15T00:00:00Z"):
    now = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT INTO markets (condition_id, question, slug, end_date,
                             first_seen_at, last_seen_at, vertical)
        VALUES (?, 'q', 's', ?, ?, ?, ?)
    """, (condition_id, end_date, now, now, vertical))


def _seed_position(c, condition_id: str, *, stake: float, side: str = "YES",
                   archetype: str | None = None, end_date: str | None = None,
                   status: str = "open"):
    now = datetime.now(timezone.utc).isoformat()
    cur = c.execute("""
        INSERT INTO positions (condition_id, signal_id, opened_at, intended_side,
                               intended_entry_price, intended_stake_usd,
                               stake_source, status, primary_archetype, end_date)
        VALUES (?, NULL, ?, ?, 0.40, ?, 'paper', ?, ?, ?)
    """, (condition_id, now, side, stake, status, archetype, end_date))
    return cur.lastrowid


def test_open_exposure_aggregates_by_vertical(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xa", "geopolitics")
        _seed_market(c, "0xb", "tech_business")
        _seed_position(c, "0xa", stake=100.0)
        _seed_position(c, "0xb", stake=50.0)
        c.commit()
        snap = open_exposure(c)
    assert snap["total_at_risk_usd"] == 150.0
    assert snap["by_vertical"]["geopolitics"] == 100.0
    assert snap["by_vertical"]["tech_business"] == 50.0
    assert snap["open_positions"] == 2


def test_open_exposure_aggregates_by_theme(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xa", "international_geopolitics")
        db.set_market_tags(c, condition_id="0xa", tags=["iran_cluster"])
        _seed_position(c, "0xa", stake=100.0)
        c.commit()
        snap = open_exposure(c)
    assert snap["by_theme"]["iran_cluster"] == 100.0


def test_open_exposure_ignores_closed_positions(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xa", "geopolitics")
        _seed_position(c, "0xa", stake=100.0, status="open")
        _seed_position(c, "0xa", stake=999.0, status="resolved")
        c.commit()
        snap = open_exposure(c)
    assert snap["total_at_risk_usd"] == 100.0


def test_check_exposure_blocks_when_vertical_cap_breached(tmp_db, monkeypatch):
    # tighten cap to make the test deterministic
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "EXPOSURE_VERTICAL_CAP_PCT", 0.20)  # $200 cap
    with db.connect() as c:
        _seed_market(c, "0xa", "geopolitics")
        _seed_market(c, "0xb", "geopolitics")
        _seed_position(c, "0xa", stake=180.0)
        c.commit()
        chk = check_exposure(
            c, condition_id="0xb", vertical="geopolitics",
            primary_archetype=None, end_date="2026-08-01T00:00:00Z",
            proposed_stake_usd=30.0,
        )
    # 180 + 30 = 210 > 200 cap -> blocked on vertical
    assert chk["allowed"] is False
    buckets = {b["bucket"] for b in chk["breaches"]}
    assert "vertical" in buckets


def test_check_exposure_blocks_when_theme_cap_breached(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "EXPOSURE_VERTICAL_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_ARCHETYPE_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_DEADLINE_WEEK_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_SINGLE_MARKET_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_THEME_CAP_PCT", 0.20)
    with db.connect() as c:
        _seed_market(c, "0xa", "international_geopolitics")
        _seed_market(c, "0xb", "international_geopolitics")
        db.set_market_tags(c, condition_id="0xa", tags=["iran_cluster"])
        db.set_market_tags(c, condition_id="0xb", tags=["iran_cluster"])
        _seed_position(c, "0xa", stake=190.0)
        c.commit()
        chk = check_exposure(
            c, condition_id="0xb", vertical="international_geopolitics",
            primary_archetype=None, end_date="2026-08-01T00:00:00Z",
            proposed_stake_usd=20.0,
            theme_tags=["iran_cluster"],
        )
    assert chk["allowed"] is False
    assert any(b["bucket"] == "theme" and b["key"] == "iran_cluster" for b in chk["breaches"])


def test_check_exposure_allows_when_caps_fit(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "EXPOSURE_VERTICAL_CAP_PCT", 0.40)
    monkeypatch.setattr(config, "EXPOSURE_ARCHETYPE_CAP_PCT", 0.30)
    monkeypatch.setattr(config, "EXPOSURE_DEADLINE_WEEK_CAP_PCT", 0.50)
    monkeypatch.setattr(config, "EXPOSURE_SINGLE_MARKET_CAP_PCT", 0.10)
    with db.connect() as c:
        _seed_market(c, "0xa", "geopolitics")
        _seed_position(c, "0xa", stake=50.0)
        c.commit()
        chk = check_exposure(
            c, condition_id="0xnew", vertical="geopolitics",
            primary_archetype=None, end_date="2026-09-01T00:00:00Z",
            proposed_stake_usd=30.0,
        )
    assert chk["allowed"] is True
    assert chk["breaches"] == []


def test_check_exposure_single_market_cap(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "EXPOSURE_SINGLE_MARKET_CAP_PCT", 0.10)  # $100
    monkeypatch.setattr(config, "EXPOSURE_VERTICAL_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_ARCHETYPE_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_DEADLINE_WEEK_CAP_PCT", 0.99)
    with db.connect() as c:
        _seed_market(c, "0xa")
        _seed_position(c, "0xa", stake=80.0)
        c.commit()
        chk = check_exposure(
            c, condition_id="0xa", vertical="geopolitics",
            primary_archetype=None, end_date="2026-09-01T00:00:00Z",
            proposed_stake_usd=30.0,
        )
    assert chk["allowed"] is False
    assert any(b["bucket"] == "single_market" for b in chk["breaches"])


def test_check_exposure_deadline_week_bucket(tmp_db, monkeypatch):
    """Two markets resolving in the same ISO-week share the deadline_week bucket."""
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "EXPOSURE_DEADLINE_WEEK_CAP_PCT", 0.10)  # $100
    monkeypatch.setattr(config, "EXPOSURE_VERTICAL_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_ARCHETYPE_CAP_PCT", 0.99)
    monkeypatch.setattr(config, "EXPOSURE_SINGLE_MARKET_CAP_PCT", 0.99)
    same_week = "2026-06-15T00:00:00Z"
    with db.connect() as c:
        _seed_market(c, "0xa", end_date=same_week)
        _seed_market(c, "0xb", end_date=same_week)
        _seed_position(c, "0xa", stake=80.0, end_date=same_week)
        c.commit()
        chk = check_exposure(
            c, condition_id="0xb", vertical="geopolitics",
            primary_archetype=None, end_date=same_week, proposed_stake_usd=30.0,
        )
    assert chk["allowed"] is False
    assert any(b["bucket"] == "deadline_week" for b in chk["breaches"])


# --- MCP tool integration ---------------------------------------------------

def _call(name, **kwargs):
    tool = mcp_server.mcp._tool_manager._tools[name]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or getattr(tool, "callback", None)
    return fn(**kwargs)


def test_portfolio_snapshot_empty_db_returns_zero(tmp_db):
    out = _call("portfolio_snapshot")
    assert out["total_at_risk_usd"] == 0.0
    assert out["open_positions"] == []


def test_portfolio_snapshot_shows_seeded_positions(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xa", "geopolitics")
        _seed_position(c, "0xa", stake=100.0)
        c.commit()
    out = _call("portfolio_snapshot")
    assert out["total_at_risk_usd"] == 100.0
    assert len(out["open_positions"]) == 1
    assert "post_entry_review_required_count" in out
    assert "signal_generation_epoch" in out["open_positions"][0]


def test_record_fill_attaches_real_money_and_promotes_status(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xa", "geopolitics")
        pid = _seed_position(c, "0xa", stake=20.0)
        c.commit()
    out = _call("record_fill", position_id=pid, side="YES",
                price=0.42, shares=47.6, stake_usd=20.0, venue="polymarket")
    assert out["ok"] is True
    assert out["slippage_vs_intent"] == pytest.approx(0.02)
    with db.connect() as c:
        row = c.execute("SELECT stake_source, status FROM positions WHERE id=?", (pid,)).fetchone()
    assert row["stake_source"] == "hybrid"
    assert row["status"] == "filled"


def test_exposure_check_via_mcp_blocks_geo_concentration(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    monkeypatch.setattr(config, "EXPOSURE_VERTICAL_CAP_PCT", 0.20)
    with db.connect() as c:
        _seed_market(c, "0xa", "geopolitics")
        _seed_market(c, "0xb", "geopolitics")
        _seed_position(c, "0xa", stake=190.0)
        c.commit()
    out = _call("exposure_check", condition_id="0xb", proposed_stake_usd=30.0)
    assert out["allowed"] is False
    assert any(b["bucket"] == "vertical" for b in out["breaches"])


def test_mark_to_market_handles_yes_and_no_sides_correctly(tmp_db):
    """NO positions store entry as YES-equivalent (1 - actual NO entry). The MTM
    formula must invert that to get the right side-entry, otherwise NO PnL is
    badly wrong (the bug that produced +$75 instead of +$3 vs audit baseline)."""
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as c:
        _seed_market(c, "0xyes_market", "geopolitics")
        _seed_market(c, "0xno_market", "geopolitics")
        # YES bought at YES=0.40 with $10: shares=25, side_entry=0.40
        c.execute("""INSERT INTO positions (condition_id, opened_at, intended_side,
                     intended_entry_price, intended_stake_usd, stake_source, status)
                     VALUES (?, ?, 'YES', 0.40, 10.0, 'paper', 'open')""",
                  ("0xyes_market", now))
        # NO bought at actual NO=0.25 (YES-equiv stored = 0.75). $10 stake.
        # Actual NO shares = 10/0.25 = 40. If YES resolves to 0.20, NO=0.80,
        # value = 40*0.80 = $32, PnL = +$22.
        c.execute("""INSERT INTO positions (condition_id, opened_at, intended_side,
                     intended_entry_price, intended_stake_usd, stake_source, status)
                     VALUES (?, ?, 'NO', 0.75, 10.0, 'paper', 'open')""",
                  ("0xno_market", now))
        # Snapshots: YES market currently at 0.50, NO market underlying YES at 0.20
        for cid, yes in (("0xyes_market", 0.50), ("0xno_market", 0.20)):
            c.execute("""INSERT INTO snapshots (condition_id, captured_at, yes_price,
                         no_price, yes_entry_price, no_entry_price)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (cid, now, yes, 1-yes, yes, 1-yes))
        c.commit()
    res = _call("mark_to_market_all")
    yes_row = next(d for d in res["details"] if d["side"] == "YES")
    no_row = next(d for d in res["details"] if d["side"] == "NO")
    # YES bought 0.40 -> now 0.50: value = 25 * 0.50 = $12.50, delta = +$2.50
    assert yes_row["value_usd"] == pytest.approx(12.50)
    assert yes_row["delta_pnl_usd"] == pytest.approx(2.50)
    # NO bought (yes-equiv) 0.75 = actual 0.25 -> YES now 0.20 = NO now 0.80
    # value = (10/0.25)*0.80 = $32, delta = +$22
    assert no_row["value_usd"] == pytest.approx(32.0)
    assert no_row["delta_pnl_usd"] == pytest.approx(22.0)


def test_pending_outcome_reviews_finds_resolved_without_review(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xa", "geopolitics")
        c.execute(
            "UPDATE markets SET resolved=1, resolved_yes=1.0, resolved_at=? WHERE condition_id='0xa'",
            (datetime.now(timezone.utc).isoformat(),),
        )
        _seed_position(c, "0xa", stake=20.0, status="resolved")
        c.commit()
    out = _call("pending_outcome_reviews")
    assert out["count"] == 1
