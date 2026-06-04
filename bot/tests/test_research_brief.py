"""Catalyst calendar and daily brief tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import db
import mcp_server


def _call(name, **kwargs):
    tool = mcp_server.mcp._tool_manager._tools[name]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or getattr(tool, "callback", None)
    return fn(**kwargs)


def _seed_market(c, cid: str, *, days: int = 5):
    now = datetime.now(timezone.utc)
    end = (now + timedelta(days=days)).isoformat()
    c.execute("""
        INSERT INTO markets (condition_id, question, slug, end_date,
                             first_seen_at, last_seen_at, vertical)
        VALUES (?, 'Will test catalyst happen?', 'test', ?, ?, ?, 'us_politics')
    """, (cid, end, now.isoformat(), now.isoformat()))
    return end


def test_catalyst_calendar_includes_open_position(tmp_db):
    with db.connect() as c:
        end = _seed_market(c, "0xcat", days=5)
        c.execute("""
            INSERT INTO positions (condition_id, opened_at, intended_side,
                                   intended_entry_price, intended_stake_usd,
                                   stake_source, status, end_date)
            VALUES (?, ?, 'YES', 0.40, 10.0, 'paper', 'open', ?)
        """, ("0xcat", datetime.now(timezone.utc).isoformat(), end))
        c.commit()
    out = _call("catalyst_calendar", horizon_days=7)
    assert out["count"] == 1
    assert out["markets"][0]["condition_id"] == "0xcat"
    assert "open_position" in out["markets"][0]["reasons"]


def test_daily_research_brief_returns_portfolio_panel(tmp_db):
    with db.connect() as c:
        end = _seed_market(c, "0xbrief", days=5)
        db.set_market_tags(c, condition_id="0xbrief", tags=["us_primary_2026"])
        c.execute("""
            INSERT INTO positions (condition_id, opened_at, intended_side,
                                   intended_entry_price, intended_stake_usd,
                                   stake_source, status, end_date)
            VALUES (?, ?, 'YES', 0.40, 10.0, 'paper', 'open', ?)
        """, ("0xbrief", datetime.now(timezone.utc).isoformat(), end))
        c.commit()
    out = _call("daily_research_brief")
    assert out["portfolio"]["open_positions"] == 1
    assert out["portfolio"]["by_theme"]["us_primary_2026"] == 10.0
    assert out["catalysts"]["count"] == 1
