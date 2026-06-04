from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from signal_client.audit import audit_positions, build_run_report, render_markdown
from signal_client.integrity import verify_lock
from signal_client.polymarket import fetch_positions, post_json


def _load_rules() -> dict:
    return json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))


def _write_integrity_violation(result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"integrity_violation_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(
        "# Signal Client Integrity Violation\n\n"
        "The client runner refused to run because protected files changed.\n\n"
        f"```json\n{json.dumps(result, indent=2, sort_keys=True)}\n```\n",
        encoding="utf-8",
    )
    return path


def _load_positions(args) -> list[dict]:
    if args.positions_json:
        payload = json.loads(Path(args.positions_json).read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and isinstance(payload.get("positions"), list):
            return payload["positions"]
        if isinstance(payload, list):
            return payload
        raise ValueError("positions-json must be a list or an object with a positions list")
    if not args.wallet:
        raise SystemExit("Provide --wallet or --positions-json")
    return fetch_positions(args.wallet)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Signal client-mode portfolio audit.")
    parser.add_argument("--wallet", help="Client Polymarket wallet address")
    parser.add_argument("--positions-json", help="Local JSON list of positions, for offline runs")
    parser.add_argument("--out", default="client_audits", help="Output directory")
    parser.add_argument("--share", action="store_true", help="Force sharing audit/report to configured endpoint")
    parser.add_argument("--no-share", action="store_true", help="Disable sharing for this run when policy permits")
    parser.add_argument("--share-endpoint", default=os.getenv("SIGNAL_CLIENT_SHARE_ENDPOINT", ""))
    parser.add_argument("--client-id", default=os.getenv("SIGNAL_CLIENT_ID", "local-client"))
    parser.add_argument("--consent-wallet", action="store_true", help="Include wallet in shared run report")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    integrity = verify_lock(ROOT)
    if not integrity["ok"]:
        path = _write_integrity_violation(integrity, out_dir)
        print(f"Integrity violation. Report written to {path}")
        return 2

    rules = _load_rules()
    privacy = rules.get("privacy") or {}
    positions = _load_positions(args)
    audit = audit_positions(positions, rules=rules)
    wallet_for_report = args.wallet if args.consent_wallet else None
    run_report = build_run_report(audit, include_wallet=wallet_for_report)
    audit_md = render_markdown(audit)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"audit_{stamp}.md"
    json_path = out_dir / f"run_report_{stamp}.json"
    md_path.write_text(audit_md, encoding="utf-8")
    json_path.write_text(json.dumps(run_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    auto_share = bool(privacy.get("share_default_if_endpoint_configured")) and bool(args.share_endpoint)
    share_enabled = (args.share or auto_share) and not args.no_share

    if share_enabled:
        if not args.share_endpoint:
            raise SystemExit("--share requires --share-endpoint or SIGNAL_CLIENT_SHARE_ENDPOINT")
        secret = os.getenv("SIGNAL_CLIENT_SHARE_SECRET")
        if not secret:
            raise SystemExit("--share requires SIGNAL_CLIENT_SHARE_SECRET")
        payload = {
            "client_id": args.client_id,
            "consent": True,
            "consent_wallet": bool(args.consent_wallet),
            "audit_md": audit_md,
            "run_report_json": run_report,
        }
        response = post_json(args.share_endpoint, payload, secret=secret)
        print(f"Shared audit: {response}")
    elif auto_share and args.no_share:
        print("Sharing disabled for this run by --no-share.")

    print(f"Audit written to {md_path}")
    print(f"Run report written to {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
