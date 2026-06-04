"""Stage 2: snapshot-backfill idempotency."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import db


def _seed_market(c, cid: str = "0xa"):
    now = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT INTO markets (condition_id, question, slug, end_date,
                             first_seen_at, last_seen_at, vertical)
        VALUES (?, 'q', 's', '2026-08-01T00:00:00Z', ?, ?, 'geopolitics')
    """, (cid, now, now))


def test_add_snapshot_raw_inserts_when_no_collision(tmp_db):
    with db.connect() as c:
        _seed_market(c)
        c.commit()
        ok = db.add_snapshot_raw(
            c, condition_id="0xa",
            captured_at="2026-04-01T00:00:00+00:00",
            yes_price=0.30, source="backfill",
        )
        assert ok is True
        n = c.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        assert n == 1


def test_add_snapshot_raw_skips_within_12h_window(tmp_db):
    with db.connect() as c:
        _seed_market(c)
        c.execute("""INSERT INTO snapshots (condition_id, captured_at, yes_price, source)
                     VALUES ('0xa', '2026-04-01T12:00:00+00:00', 0.30, 'fetch')""")
        c.commit()
        # 6h later — same window → skip
        ok = db.add_snapshot_raw(
            c, condition_id="0xa",
            captured_at="2026-04-01T18:00:00+00:00",
            yes_price=0.31, source="backfill",
        )
        assert ok is False
        n = c.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        assert n == 1


def test_add_snapshot_raw_inserts_outside_12h_window(tmp_db):
    with db.connect() as c:
        _seed_market(c)
        c.execute("""INSERT INTO snapshots (condition_id, captured_at, yes_price, source)
                     VALUES ('0xa', '2026-04-01T00:00:00+00:00', 0.30, 'fetch')""")
        c.commit()
        # 18h later → outside window → insert
        ok = db.add_snapshot_raw(
            c, condition_id="0xa",
            captured_at="2026-04-01T18:00:00+00:00",
            yes_price=0.31, source="backfill",
        )
        assert ok is True
        n = c.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        assert n == 2


def test_repeated_backfill_is_idempotent(tmp_db):
    """Calling twice with the same series must not duplicate rows."""
    with db.connect() as c:
        _seed_market(c)
        c.commit()
        series = [
            ("2026-04-01T00:00:00+00:00", 0.30),
            ("2026-04-15T00:00:00+00:00", 0.32),
            ("2026-05-01T00:00:00+00:00", 0.28),
        ]
        for ts, p in series:
            db.add_snapshot_raw(c, condition_id="0xa", captured_at=ts,
                                yes_price=p, source="backfill")
        c.commit()
        first = c.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        # Re-run
        for ts, p in series:
            db.add_snapshot_raw(c, condition_id="0xa", captured_at=ts,
                                yes_price=p, source="backfill")
        c.commit()
        second = c.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        assert first == second == 3
