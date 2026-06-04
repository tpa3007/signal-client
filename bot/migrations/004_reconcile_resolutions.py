"""Repair: purge bogus daemon snapshots + reconcile closed positions.

Two defects this fixes:
  1. sync_daemon.py queried Gamma with the wrong param (?condition_id= instead
     of ?condition_ids=). Gamma ignored it and returned a default market list,
     so every "daemon" snapshot got a placeholder price (~0.51). All daemon
     snapshots are therefore garbage and are deleted.
  2. Some positions were closed (operator exit / market expiry) but the parent
     signal still had resolved=0, so the dashboard showed them as open with
     fake unrealized PnL. We sync signals.resolved + realized_pnl from the
     closed position (using real_pnl_actual, else the latest learning review).

Idempotent. Usage:
    python migrations/004_reconcile_resolutions.py --dry-run
    python migrations/004_reconcile_resolutions.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BOT_DIR / "bot.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # 1. Purge bogus daemon snapshots
    n_daemon = conn.execute("SELECT COUNT(*) FROM snapshots WHERE source='daemon'").fetchone()[0]
    print(f"daemon snapshots to delete: {n_daemon}")
    if not args.dry_run:
        conn.execute("DELETE FROM snapshots WHERE source='daemon'")

    # 2. Reconcile closed-position signals that are still resolved=0
    rows = conn.execute(
        """
        SELECT s.id, s.resolved, s.real_pnl_actual, s.realized_pnl, s.real_money,
               p.status AS pstatus, p.closed_reason
        FROM signals s
        JOIN positions p ON p.signal_id = s.id
        WHERE p.status = 'closed' AND s.resolved = 0
        """
    ).fetchall()
    reconciled = 0
    for r in rows:
        # Best available realized pnl: real_pnl_actual > realized_pnl > learning review
        pnl = r["real_pnl_actual"]
        if pnl is None:
            pnl = r["realized_pnl"]
        if pnl is None:
            lr = conn.execute(
                "SELECT realized_pnl FROM outcome_learning_reviews "
                "WHERE signal_id=? AND realized_pnl IS NOT NULL ORDER BY id DESC LIMIT 1",
                (r["id"],),
            ).fetchone()
            if lr:
                pnl = lr["realized_pnl"]
        print(f"  sig{r['id']}: resolved 0->1, realized_pnl={pnl}  ({(r['closed_reason'] or '')[:50]})")
        if not args.dry_run:
            conn.execute(
                "UPDATE signals SET resolved=1, realized_pnl=COALESCE(?, realized_pnl), "
                "real_pnl_actual=COALESCE(real_pnl_actual, ?) WHERE id=?",
                (pnl, pnl, r["id"]),
            )
        reconciled += 1

    if args.dry_run:
        print(f"[dry-run] would delete {n_daemon} snapshots, reconcile {reconciled} signals")
    else:
        conn.commit()
        print(f"deleted {n_daemon} daemon snapshots, reconciled {reconciled} signals")
    conn.close()


if __name__ == "__main__":
    main()
