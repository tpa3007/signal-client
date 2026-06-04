"""One-off cleanup: mark 13 zombie workflow_runs as stale_abandoned.

These rows have been stuck in status='running' since 2026-05-20/21.
The process that owned them died. They will never complete.

Run once from the bot/ directory:
    python cleanup_zombies.py

Idempotent: AND status = 'running' guard means re-running is safe.
"""
import sys
import os

# Ensure we can import bot modules
sys.path.insert(0, os.path.dirname(__file__))

import db  # noqa: E402

ZOMBIE_IDS = [7, 8, 9, 10, 11, 12, 13, 14, 15, 19, 20, 33, 39]
NOTES = "Marked stale_abandoned by Phase 1 cleanup — process died 2026-05-20/21"


def main() -> None:
    db.init()
    with db.connect() as conn:
        placeholders = ",".join("?" * len(ZOMBIE_IDS))

        conn.execute(
            f"""UPDATE workflow_runs
                SET status = 'stale_abandoned',
                    completed_at = datetime('now'),
                    notes = ?
                WHERE id IN ({placeholders})
                  AND status = 'running'""",
            [NOTES] + ZOMBIE_IDS,
        )

        affected = conn.execute(
            f"""SELECT COUNT(*) FROM workflow_runs
                WHERE id IN ({placeholders})
                  AND status = 'stale_abandoned'""",
            ZOMBIE_IDS,
        ).fetchone()[0]

        conn.commit()

    print(f"Marked {affected} workflow_runs as stale_abandoned")

    if affected != len(ZOMBIE_IDS):
        print(
            f"WARNING: Expected {len(ZOMBIE_IDS)}, got {affected}. "
            "Some IDs may not exist or were already non-running."
        )
        sys.exit(1)

    # Verify no running zombies remain
    with db.connect() as conn:
        remaining = conn.execute(
            f"""SELECT COUNT(*) FROM workflow_runs
                WHERE id IN ({placeholders})
                  AND status = 'running'""",
            ZOMBIE_IDS,
        ).fetchone()[0]

    if remaining > 0:
        print(f"ERROR: {remaining} zombie IDs still have status='running'")
        sys.exit(1)

    print("Verified: zero zombie IDs remain in status='running'")


if __name__ == "__main__":
    main()
