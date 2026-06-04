"""Signal dashboard sync daemon.

Keeps the static dashboard JSON fresh without an operator in the loop:

  1. Pull live YES/NO prices for OPEN positions from the Polymarket Gamma API.
  2. Write them as fresh snapshots (source='daemon') so the DB + export reflect
     current marks even when no browser is open.
  3. Re-run export_dashboard_data.py to regenerate signal-dashboard.json.
  4. (Optional) git add/commit/push the JSON so Vercel auto-deploys.

Usage:
    cd C:\\Signal\\bot
    python sync_daemon.py --once               # single pass, no git
    python sync_daemon.py --interval 900       # loop every 15 min
    python sync_daemon.py --interval 900 --push # loop + git push for Vercel

The daemon is read-mostly: it only inserts price snapshots (the same kind the
normal fetch path writes). It never creates signals, positions, or fills.
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows so non-ASCII log chars never crash the daemon
# (Windows console defaults to cp1251/cp866 under Task Scheduler).
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BOT_DIR = Path(__file__).resolve().parent
ROOT = BOT_DIR.parent
sys.path.insert(0, str(BOT_DIR))

import db  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com/markets"
DASHBOARD_JSON = ROOT / "dashboard-web" / "public" / "data" / "signal-dashboard.json"


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def _open_condition_ids() -> list[str]:
    """Genuinely-open markets only: open/pending position, signal not resolved,
    and the market deadline has not passed. Past-deadline markets are excluded
    so we never overwrite a resolved market with a live (placeholder) price."""
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT s.condition_id
            FROM signals s
            JOIN positions p ON p.signal_id = s.id
            LEFT JOIN markets m ON m.condition_id = s.condition_id
            WHERE s.resolved = 0
              AND p.status IN ('open', 'pending')
              AND (m.end_date IS NULL OR m.end_date > ?)
            """,
            (now,),
        ).fetchall()
    return [r[0] for r in rows if r[0]]


def _fetch_price(condition_id: str) -> dict | None:
    # Correct Gamma param is `condition_ids` (plural). Singular is ignored and
    # returns a default market list → placeholder prices. See migration 004.
    url = f"{GAMMA}?condition_ids={condition_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Signal-SyncDaemon/1.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as exc:  # noqa: BLE001
        _log(f"  fetch failed {condition_id[:14]}...: {exc}")
        return None
    if not data:
        return None
    m = data[0]
    # Reject wrong market or closed market — never trust a mismatched response.
    returned_id = (m.get("conditionId") or m.get("condition_id") or "").lower()
    if returned_id and returned_id != condition_id.lower():
        _log(f"  id mismatch {condition_id[:14]}... skip")
        return None
    if m.get("closed") is True:
        return None
    op = m.get("outcomePrices")
    yes = None
    if op:
        try:
            prices = json.loads(op) if isinstance(op, str) else op
            yes = float(prices[0])
        except Exception:  # noqa: BLE001
            yes = None
    if yes is None:
        try:
            yes = float(m.get("bestBid") or 0) or None
        except (TypeError, ValueError):
            yes = None
    if yes is None or yes <= 0:
        return None
    return {
        "yes": yes,
        "volume": m.get("volumeNum"),
        "liquidity": m.get("liquidityNum"),
        "spread": m.get("spread"),
    }


def refresh_prices() -> int:
    cids = _open_condition_ids()
    if not cids:
        _log("no open positions to refresh")
        return 0
    written = 0
    with db.connect() as conn:
        for cid in cids:
            info = _fetch_price(cid)
            if not info:
                continue
            db.add_snapshot(
                conn,
                condition_id=cid,
                yes_price=info["yes"],
                no_price=1.0 - info["yes"],
                volume=info.get("volume"),
                liquidity=info.get("liquidity"),
                spread=info.get("spread"),
                source="daemon",
            )
            written += 1
        conn.commit()
    _log(f"refreshed {written}/{len(cids)} open markets")
    return written


def run_export() -> None:
    result = subprocess.run(
        [sys.executable, "export_dashboard_data.py"],
        cwd=str(BOT_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _log(f"export failed: {result.stderr.strip()[:200]}")
    else:
        _log(result.stdout.strip() or "export ok")


def git_push() -> None:
    rel = DASHBOARD_JSON.relative_to(ROOT)
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", str(rel)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        if not status.stdout.strip():
            _log("no JSON change — skip push")
            return
        subprocess.run(["git", "add", str(rel)], cwd=str(ROOT), check=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        subprocess.run(
            ["git", "commit", "-m", f"chore(dashboard): sync snapshot {stamp}"],
            cwd=str(ROOT), check=True, capture_output=True, text=True,
        )
        subprocess.run(["git", "push"], cwd=str(ROOT), check=True, capture_output=True, text=True)
        _log("pushed dashboard JSON -> Vercel will redeploy")
    except subprocess.CalledProcessError as exc:  # noqa: BLE001
        _log(f"git push failed: {(exc.stderr or str(exc))[:200]}")


def sync_wallet() -> None:
    """Refresh the operator's live Polymarket portfolio (live-portfolio.json)."""
    try:
        import wallet_sync  # noqa: PLC0415
        w = wallet_sync.load_wallet()
        if w:
            p = wallet_sync.sync(w)
            _log(f"wallet synced: ${p['portfolioValue']} value, {p['positionCount']} positions, "
                 f"unrealized ${p['openUnrealizedPnl']:+.2f}")
    except Exception as exc:  # noqa: BLE001
        _log(f"wallet sync failed: {exc}")


def one_pass(push: bool) -> None:
    refresh_prices()
    sync_wallet()
    run_export()
    if push:
        git_push()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="single pass then exit")
    parser.add_argument("--interval", type=int, default=900, help="loop interval seconds")
    parser.add_argument("--push", action="store_true", help="git push JSON for Vercel autodeploy")
    args = parser.parse_args()

    db.init()
    if args.once:
        one_pass(args.push)
        return

    _log(f"sync daemon started — every {args.interval}s, push={args.push}")
    try:
        while True:
            one_pass(args.push)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        _log("stopped")


if __name__ == "__main__":
    main()
