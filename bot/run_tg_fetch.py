"""Standalone Telegram channel fetcher — for manual testing and one-off research.

Usage:
    cd C:\Signal\bot
    python run_tg_fetch.py meduza_io
    python run_tg_fetch.py rybar --max-posts 50 --backend web
    python run_tg_fetch.py iranintl nexta_tv flash_ua

No API keys. No auth. Works for any public channel.
Backend order: RSShub (structured RSS) -> paginated t.me/s/ (fallback).
"""
from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from lib.integrations.telegram_web import fetch_channel, fetch_channels


def _print_snapshot(snap) -> None:
    print(f"\n{'='*60}")
    print(f"Channel : @{snap.channel}")
    print(f"Backend : {snap.backend}")
    print(f"Posts   : {len(snap.posts)}")
    if snap.error:
        print(f"Error   : {snap.error}")
    print(f"{'='*60}")
    for i, p in enumerate(snap.posts, 1):
        date_str = (p.date or "")[:16].replace("T", " ")
        views_str = f"  views:{p.views}" if p.views else ""
        print(f"\n[{i:3d}] {date_str}{views_str}  {p.url}")
        print(p.text[:400])
        if len(p.text) > 400:
            print("  [... truncated]")


def main():
    parser = argparse.ArgumentParser(description="Fetch Telegram channel posts (no auth)")
    parser.add_argument("channels", nargs="+", help="Channel names without @")
    parser.add_argument("--max-posts", type=int, default=60, help="Max posts per channel")
    parser.add_argument("--backend", choices=["auto", "rsshub", "web"], default="auto",
                        help="auto=RSShub->web fallback, rsshub=RSS only, web=t.me/s/ only")
    parser.add_argument("--raw", action="store_true", help="Print raw_text block (Forager format)")
    args = parser.parse_args()

    prefer_rsshub = args.backend in ("auto", "rsshub")

    if len(args.channels) == 1:
        snap = fetch_channel(args.channels[0], max_posts=args.max_posts, prefer_rsshub=prefer_rsshub)
        if args.raw:
            print(snap.raw_text)
        else:
            _print_snapshot(snap)
    else:
        snaps = fetch_channels(args.channels, max_channels=len(args.channels),
                               max_posts_per_channel=args.max_posts, prefer_rsshub=prefer_rsshub)
        for snap in snaps:
            if args.raw:
                print(snap.raw_text)
            else:
                _print_snapshot(snap)

    print("\nDone.")


if __name__ == "__main__":
    main()
