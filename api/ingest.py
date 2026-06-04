from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any


def _safe_client_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value or "unknown")
    return cleaned[:80] or "unknown"


def process_ingest(
    *,
    headers: dict[str, str],
    body: bytes,
    secret: str | None = None,
    storage_dir: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    expected_secret = secret if secret is not None else os.getenv("SIGNAL_CLIENT_INGEST_SECRET", "")
    provided_secret = headers.get("x-signal-client-secret") or headers.get("X-Signal-Client-Secret") or ""
    if expected_secret and provided_secret != expected_secret:
        return 401, {"ok": False, "error": "unauthorized"}

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return 400, {"ok": False, "error": "invalid_json"}

    if payload.get("consent") is not True:
        return 400, {"ok": False, "error": "missing_consent"}

    audit_md = payload.get("audit_md")
    run_report = payload.get("run_report_json")
    if not isinstance(audit_md, str) or not isinstance(run_report, dict):
        return 400, {"ok": False, "error": "missing_audit_or_report"}

    if payload.get("consent_wallet") is not True:
        run_report = dict(run_report)
        run_report["wallet"] = None

    client_id = _safe_client_id(str(payload.get("client_id") or "unknown"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = storage_dir or Path(os.getenv("SIGNAL_CLIENT_INGEST_DIR", "/tmp/signal-client-ingest"))
    client_dir = root / client_id
    client_dir.mkdir(parents=True, exist_ok=True)

    audit_path = client_dir / f"audit_{stamp}.md"
    report_path = client_dir / f"run_report_{stamp}.json"
    audit_path.write_text(audit_md, encoding="utf-8")
    report_path.write_text(json.dumps(run_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return 200, {
        "ok": True,
        "client_id": client_id,
        "audit_path": str(audit_path),
        "run_report_path": str(report_path),
        "positions_count": run_report.get("positions_count"),
        "decision_counts": run_report.get("decision_counts"),
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - Vercel expects BaseHTTPRequestHandler shape.
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        status, payload = process_ingest(headers=dict(self.headers), body=body)
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self):  # noqa: N802
        response = json.dumps({"ok": False, "error": "method_not_allowed"}).encode("utf-8")
        self.send_response(405)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)
