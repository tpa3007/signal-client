"""Hosted Signal launcher for public client repositories.

The full Signal + Forager engine is not shipped to clients. This launcher sends
the user's wallet/positions and requested command sequence to the author's
hosted runner, then stores the returned receipt/report locally.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from signal_client.integrity import IntegrityError, load_rules, verify_lock  # noqa: E402


DEFAULT_COMMANDS = "G,G2,M,R,B,D,W,PORTFOLIO_AUDIT"


def _headers(secret: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "signal-client/hosted"}
    if secret:
        headers["X-Signal-Run-Secret"] = secret
    return headers


def _post_json(url: str, payload: dict[str, Any], secret: str, timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(secret), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, secret: str, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=_headers(secret), method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_positions(path: str | None) -> list[dict[str, Any]] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("positions"), list):
        return payload["positions"]
    raise ValueError("positions-json must be a list or an object with a positions list")


def _write_text_report(out_dir: Path, name: str, text: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def _receipt_md(response: dict[str, Any], endpoint: str, commands: str) -> str:
    generated = datetime.now(timezone.utc).isoformat()
    return "\n".join(
        [
            f"# Signal Hosted Run Receipt - {response.get('run_id', 'unknown')}",
            "",
            f"Generated: `{generated}`",
            f"Endpoint: `{endpoint}`",
            f"Status: `{response.get('status')}`",
            f"Commands: `{commands}`",
            "",
            "The full Signal + Forager engine runs on the author's private worker.",
            "This public repository does not contain proprietary logic or author data.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit a hosted Signal + Forager run.")
    parser.add_argument("--wallet", default=os.getenv("POLYMARKET_WALLET", ""))
    parser.add_argument("--positions-json", default="")
    parser.add_argument("--commands", default=os.getenv("SIGNAL_CLIENT_COMMANDS", DEFAULT_COMMANDS))
    parser.add_argument("--endpoint", default=os.getenv("SIGNAL_CLIENT_RUN_ENDPOINT", ""))
    parser.add_argument("--secret", default=os.getenv("SIGNAL_CLIENT_RUN_SECRET", ""))
    parser.add_argument("--client-id", default=os.getenv("SIGNAL_CLIENT_ID", "local-client"))
    parser.add_argument("--out-dir", default="client_audits")
    parser.add_argument("--poll", action="store_true", help="Poll until the hosted run finishes.")
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--max-polls", type=int, default=90)
    parser.add_argument("--consent-wallet", action="store_true")
    args = parser.parse_args()

    try:
        verify_lock(ROOT)
        rules = load_rules(ROOT)
    except IntegrityError as exc:
        out = Path(args.out_dir)
        _write_text_report(out, "integrity_violation.md", f"# Integrity violation\n\n{exc}\n")
        print(f"Integrity violation: {exc}")
        return 2

    if not args.endpoint:
        print("Set SIGNAL_CLIENT_RUN_ENDPOINT or pass --endpoint.")
        return 2
    positions = _load_positions(args.positions_json)
    if not args.wallet and positions is None:
        print("Pass --wallet or --positions-json.")
        return 2

    payload = {
        "client_id": args.client_id,
        "wallet": args.wallet or None,
        "positions": positions,
        "commands": args.commands,
        "consent_report_to_author": True,
        "consent_wallet_to_author": bool(args.consent_wallet),
        "client_rules_version": rules.get("version"),
    }
    try:
        response = _post_json(args.endpoint, payload, args.secret)
    except urllib.error.HTTPError as exc:
        print(f"Hosted run rejected: HTTP {exc.code} {exc.read().decode('utf-8', errors='replace')}")
        return 1

    out_dir = Path(args.out_dir)
    run_id = response.get("run_id", "unknown")
    receipt = _write_text_report(out_dir, f"hosted_run_{run_id}.md", _receipt_md(response, args.endpoint, args.commands))
    print(f"Hosted run queued: {run_id}")
    print(f"Receipt written to {receipt}")

    if not args.poll or not run_id:
        return 0

    status_url = args.endpoint + ("&" if "?" in args.endpoint else "?") + urllib.parse.urlencode({"run_id": run_id})
    for _ in range(max(1, args.max_polls)):
        time.sleep(max(1, args.poll_seconds))
        status = _get_json(status_url, args.secret)
        state = status.get("status")
        print(f"Run {run_id}: {state}")
        if status.get("client_report_md"):
            final_path = _write_text_report(out_dir, f"signal_report_{run_id}.md", status["client_report_md"])
            print(f"Final report written to {final_path}")
        if state in {"completed", "failed", "blocked"}:
            return 0 if state == "completed" else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
