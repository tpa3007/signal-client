"""Repair migration: backfill brier_score / market_brier_score.

The 8 existing outcome_learning_reviews were written via write_learning_reviews.py
without computing Brier scores. This backfills them for cleanly-resolved rows
(outcome_side in YES/NO) using:

  brier_score        = (our probability_yes        - outcome)^2
  market_brier_score = (market yes_price_at_signal - outcome)^2

Everything is in YES-space so it is side-agnostic. Idempotent: only fills rows
where the score is currently NULL.

Usage:
    cd C:\\Signal\\bot
    python migrations/003_backfill_brier_scores.py          # apply
    python migrations/003_backfill_brier_scores.py --dry-run # preview only
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_DIR))
from lib.calibration import compute_brier  # noqa: E402

DB_PATH = BOT_DIR / "bot.db"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT o.id, o.outcome_side, o.probability_yes,
               o.brier_score, o.market_brier_score,
               COALESCE(s.yes_price_at_signal, o.entry_price) AS market_yes
        FROM outcome_learning_reviews o
        LEFT JOIN signals s ON s.id = o.signal_id
        WHERE o.outcome_side IN ('YES', 'NO')
        """
    ).fetchall()

    updated = 0
    for r in rows:
        our_brier = compute_brier(r["probability_yes"], r["outcome_side"])
        mkt_brier = compute_brier(r["market_yes"], r["outcome_side"])
        # Only fill nulls (idempotent).
        new_our = r["brier_score"] if r["brier_score"] is not None else our_brier
        new_mkt = r["market_brier_score"] if r["market_brier_score"] is not None else mkt_brier
        if new_our == r["brier_score"] and new_mkt == r["market_brier_score"]:
            continue
        verdict = (
            "we beat market" if (new_our is not None and new_mkt is not None and new_our < new_mkt)
            else "market beat us" if (new_our is not None and new_mkt is not None and new_our > new_mkt)
            else "tie"
        )
        print(f"  review #{r['id']} [{r['outcome_side']}]: "
              f"our={new_our} market={new_mkt} -> {verdict}")
        if not args.dry_run:
            conn.execute(
                "UPDATE outcome_learning_reviews SET brier_score=?, market_brier_score=? WHERE id=?",
                (new_our, new_mkt, r["id"]),
            )
        updated += 1

    if args.dry_run:
        print(f"[dry-run] would update {updated} rows")
    else:
        conn.commit()
        print(f"updated {updated} rows")
    conn.close()


if __name__ == "__main__":
    main()
