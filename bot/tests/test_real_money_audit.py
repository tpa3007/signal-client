from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
import db
from lib.real_money_audit import build_real_money_audit


NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _seed_market(conn, cid: str = "0xreal", *, end_date: str = "2026-06-10T00:00:00Z") -> None:
    db.upsert_market(
        conn,
        condition_id=cid,
        question="Will the test event happen?",
        slug="test-event",
        end_date=end_date,
        vertical="economics_finance",
    )


def _seed_real_position(
    conn,
    cid: str = "0xreal",
    *,
    side: str = "YES",
    manual: bool = True,
    stake_source: str = "real",
) -> tuple[int, int]:
    signal_id = db.add_signal(
        conn,
        condition_id=cid,
        created_at="2026-05-30T12:00:00+00:00",
        model="pytest",
        yes_price_at_signal=0.30 if side == "YES" else 0.70,
        yes_equivalent_entry=0.30 if side == "YES" else 0.70,
        side_entry_price=0.30,
        claude_prob=0.60,
        confidence=0.55,
        side=side,
        edge=0.10,
        bet_amount=30.0,
        reasoning="pytest real position",
        sources_json="[]",
        tokens_in=None,
        tokens_out=None,
        cache_read_tokens=None,
        cost_usd=0.0,
        gate_status="manual" if manual else "legacy_gate_violation",
        gate_audit_note="pytest",
    )
    conn.execute(
        """
        UPDATE signals
        SET real_money = 1,
            manual_trade = ?,
            retrospective = ?,
            real_entry_price = 0.30,
            real_bet_usd = 30.0,
            real_shares = 100.0,
            real_filled_at = '2026-05-30T12:00:00+00:00',
            real_max_payout = 100.0
        WHERE id = ?
        """,
        (1 if manual else 0, 1 if manual else 0, signal_id),
    )
    position_id = db.add_position(
        conn,
        condition_id=cid,
        signal_id=signal_id,
        opened_at="2026-05-30T12:00:00+00:00",
        intended_side=side,
        intended_entry_price=0.30 if side == "YES" else 0.70,
        side_entry_price=0.30,
        yes_equivalent_entry=0.30 if side == "YES" else 0.70,
        intended_stake_usd=30.0,
        stake_source=stake_source,
        status="open",
        thesis_snapshot_text="pytest",
        primary_archetype="stale_price",
        end_date="2026-06-10T00:00:00Z",
    )
    return signal_id, position_id


def test_real_money_audit_tracks_partial_exit_and_residual_risk(tmp_db):
    with db.connect() as conn:
        _seed_market(conn)
        _, position_id = _seed_real_position(conn)
        db.add_fill(conn, position_id=position_id, side="YES", price=0.30, shares=100, stake_usd=30, venue="polymarket", filled_at="2026-05-30T12:00:00+00:00")
        db.add_fill(conn, position_id=position_id, side="SELL_YES", price=0.70, shares=50, stake_usd=35, venue="polymarket", filled_at="2026-05-31T12:00:00+00:00")
        conn.execute(
            """
            INSERT INTO snapshots (condition_id, captured_at, yes_price, no_price, yes_entry_price, no_entry_price, source)
            VALUES ('0xreal', ?, 0.80, 0.20, 0.80, 0.20, 'pytest')
            """,
            ((NOW - timedelta(hours=1)).isoformat(),),
        )
        conn.commit()

        out = build_real_money_audit(conn, bankroll_usd=1000, now=NOW)

    assert out["summary"]["positions_count"] == 1
    pos = out["positions"][0]
    assert pos["fills"]["residual_shares"] == 50.0
    assert pos["mark_to_market"]["current_value_usd"] == 40.0
    assert pos["mark_to_market"]["mtm_pnl_usd"] == 45.0
    assert pos["mark_to_market"]["remaining_worst_case_loss_usd"] == 0.0
    assert any(r["code"] == "partially_de_risked" for r in pos["risks"])


def test_real_money_audit_flags_gate_stale_snapshot_and_thin_dossier(tmp_db):
    with db.connect() as conn:
        _seed_market(conn, end_date="2026-06-02T00:00:00Z")
        _, position_id = _seed_real_position(conn, manual=False)
        db.add_fill(conn, position_id=position_id, side="YES", price=0.30, shares=100, stake_usd=30, venue="polymarket", filled_at="2026-05-30T12:00:00+00:00")
        conn.execute(
            """
            INSERT INTO snapshots (condition_id, captured_at, yes_price, no_price, yes_entry_price, no_entry_price, source)
            VALUES ('0xreal', ?, 0.20, 0.80, 0.20, 0.80, 'pytest')
            """,
            ((NOW - timedelta(hours=30)).isoformat(),),
        )
        conn.commit()

        out = build_real_money_audit(conn, bankroll_usd=1000, now=NOW, stale_snapshot_hours=12, urgent_days=7)

    pos = out["positions"][0]
    codes = {r["code"] for r in pos["risks"]}
    assert {"gate_violation", "stale_snapshot", "thin_dossier", "deadline_urgent"}.issubset(codes)
    assert pos["research_state"]["gate_violation"] is True
    assert out["priority_actions"][0]["priority"] == "high"


def test_real_money_audit_includes_legacy_real_money_stake_source(tmp_db):
    with db.connect() as conn:
        _seed_market(conn)
        signal_id, position_id = _seed_real_position(conn, stake_source="real_money")
        conn.execute("UPDATE signals SET real_money = 0 WHERE id = ?", (signal_id,))
        db.add_fill(
            conn,
            position_id=position_id,
            side="YES",
            price=0.30,
            shares=100,
            stake_usd=30,
            venue="polymarket",
            filled_at="2026-05-30T12:00:00+00:00",
        )
        conn.commit()

        out = build_real_money_audit(conn, bankroll_usd=1000, now=NOW)

    assert out["summary"]["positions_count"] == 1
    assert out["positions"][0]["stake_source"] == "real_money"


def test_real_money_audit_prefers_snapshot_no_price_for_no_positions(tmp_db):
    with db.connect() as conn:
        _seed_market(conn)
        _, position_id = _seed_real_position(conn, side="NO")
        db.add_fill(
            conn,
            position_id=position_id,
            side="NO",
            price=0.30,
            shares=100,
            stake_usd=30,
            venue="polymarket",
            filled_at="2026-05-30T12:00:00+00:00",
        )
        conn.execute(
            """
            INSERT INTO snapshots (condition_id, captured_at, yes_price, no_price, yes_entry_price, no_entry_price, source)
            VALUES ('0xreal', ?, 0.70, 0.31, 0.70, 0.31, 'pytest')
            """,
            ((NOW - timedelta(hours=1)).isoformat(),),
        )
        conn.commit()

        out = build_real_money_audit(conn, bankroll_usd=1000, now=NOW)

    pos = out["positions"][0]
    assert pos["mark_to_market"]["no_price"] == 0.31
    assert pos["mark_to_market"]["current_side_price"] == 0.31
    assert pos["mark_to_market"]["current_value_usd"] == 31.0


def test_real_money_portfolio_audit_mcp_tool_is_read_only(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "BANKROLL_USD", 1000.0)
    with db.connect() as conn:
        _seed_market(conn)
        _, position_id = _seed_real_position(conn)
        db.add_fill(conn, position_id=position_id, side="YES", price=0.30, shares=100, stake_usd=30, venue="polymarket", filled_at="2026-05-30T12:00:00+00:00")
        conn.commit()

    import mcp_server

    tool = mcp_server.mcp._tool_manager._tools["real_money_portfolio_audit"]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or getattr(tool, "callback", None)
    out = fn(stale_snapshot_hours=12, urgent_days=7)

    assert out["workflow"] == "real_money_portfolio_audit"
    assert out["rules"]["signals_created"] is False
    assert out["rules"]["positions_created"] is False
    assert out["rules"]["fills_created"] is False
    assert out["summary"]["positions_count"] == 1
