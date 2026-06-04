"""Client run queue API for hosted Signal execution.

This API is intentionally a queue adapter, not the Signal engine. Public
`signal-client` callers submit a job here; a private worker with the full
Signal + Forager checkout consumes the queued job, runs the commands in an
isolated workspace, writes the client report, and stores the author copy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any


ALLOWED_COMMANDS = {"G", "G2", "M", "R", "B", "D", "F", "W", "PORTFOLIO_AUDIT"}
DEFAULT_COMMANDS = ["G", "G2", "M", "R", "B", "D", "W", "PORTFOLIO_AUDIT"]


def _storage_root(storage_dir: str | os.PathLike[str] | None = None) -> Path:
    root = storage_dir or os.getenv("SIGNAL_CLIENT_RUN_QUEUE_DIR") or "/tmp/signal-client-runs"
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_response(status: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json"}, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _secret_ok(headers: dict[str, str], secret: str | None = None) -> bool:
    expected = secret if secret is not None else os.getenv("SIGNAL_CLIENT_RUN_SECRET", "")
    if not expected:
        return True
    supplied = headers.get("X-Signal-Run-Secret") or headers.get("x-signal-run-secret") or ""
    return hashlib.sha256(supplied.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()


def _safe_client_id(value: str | None) -> str:
    raw = (value or "anonymous").strip().lower()
    safe = re.sub(r"[^a-z0-9_.-]+", "_", raw)[:80].strip("._-")
    return safe or "anonymous"


def _normalise_commands(value: Any) -> list[str]:
    if value is None:
        return list(DEFAULT_COMMANDS)
    if isinstance(value, str):
        raw = [part.strip().upper() for part in value.split(",")]
    elif isinstance(value, list):
        raw = [str(part).strip().upper() for part in value]
    else:
        raise ValueError("commands must be a comma string or list")
    commands = [part for part in raw if part]
    unknown = [part for part in commands if part not in ALLOWED_COMMANDS]
    if unknown:
        raise ValueError(f"unsupported command(s): {', '.join(unknown)}")
    return commands or list(DEFAULT_COMMANDS)


def _load_body(body: bytes | str) -> dict[str, Any]:
    if isinstance(body, str):
        body = body.encode("utf-8")
    payload = json.loads(body.decode("utf-8-sig") or "{}")
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _job_dir(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9-]{36}", run_id):
        raise ValueError("invalid run_id")
    return root / run_id


def create_client_run(
    headers: dict[str, str],
    body: bytes | str,
    *,
    secret: str | None = None,
    storage_dir: str | os.PathLike[str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    if not _secret_ok(headers, secret):
        return _json_response(401, {"error": "unauthorized"})
    try:
        payload = _load_body(body)
        commands = _normalise_commands(payload.get("commands"))
    except (json.JSONDecodeError, ValueError) as exc:
        return _json_response(400, {"error": str(exc)})

    wallet = str(payload.get("wallet") or "").strip()
    positions = payload.get("positions")
    if not wallet and not positions:
        return _json_response(400, {"error": "wallet or positions is required"})

    run_id = str(uuid.uuid4())
    root = _storage_root(storage_dir)
    path = _job_dir(root, run_id)
    path.mkdir(parents=True, exist_ok=False)

    job = {
        "run_id": run_id,
        "client_id": _safe_client_id(str(payload.get("client_id") or "")),
        "created_at_unix": time.time(),
        "status": "queued",
        "commands": commands,
        "wallet": wallet or None,
        "positions": positions if isinstance(positions, list) else None,
        "consent_report_to_author": bool(payload.get("consent_report_to_author", True)),
        "consent_wallet_to_author": bool(payload.get("consent_wallet_to_author", False)),
        "requested_outputs": ["client_report_md", "run_report_json", "author_copy"],
    }
    (path / "job.json").write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
    (path / "status.json").write_text(
        json.dumps({"run_id": run_id, "status": "queued", "commands": commands}, ensure_ascii=False),
        encoding="utf-8",
    )
    return _json_response(202, {"run_id": run_id, "status": "queued", "commands": commands})


def get_client_run(
    headers: dict[str, str],
    run_id: str,
    *,
    secret: str | None = None,
    storage_dir: str | os.PathLike[str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    if not _secret_ok(headers, secret):
        return _json_response(401, {"error": "unauthorized"})
    try:
        path = _job_dir(_storage_root(storage_dir), run_id)
    except ValueError as exc:
        return _json_response(400, {"error": str(exc)})
    status_path = path / "status.json"
    if not status_path.exists():
        return _json_response(404, {"error": "run not found"})
    status = json.loads(status_path.read_text(encoding="utf-8"))
    report_path = path / "client_report.md"
    if report_path.exists():
        status["client_report_md"] = report_path.read_text(encoding="utf-8")
    run_report_path = path / "run_report.json"
    if run_report_path.exists():
        status["run_report_json"] = json.loads(run_report_path.read_text(encoding="utf-8"))
    return _json_response(200, status)


def handler(request):
    """Vercel-style BaseHTTPRequestHandler entry point."""
    headers = dict(getattr(request, "headers", {}) or {})
    method = getattr(request, "command", "GET").upper()
    if method == "POST":
        length = int(headers.get("Content-Length") or headers.get("content-length") or 0)
        body = request.rfile.read(length) if length else b"{}"
        status, out_headers, payload = create_client_run(headers, body)
    else:
        import urllib.parse

        parsed = urllib.parse.urlparse(getattr(request, "path", ""))
        params = urllib.parse.parse_qs(parsed.query)
        run_id = (params.get("run_id") or [""])[0]
        status, out_headers, payload = get_client_run(headers, run_id)
    request.send_response(status)
    for key, value in out_headers.items():
        request.send_header(key, value)
    request.end_headers()
    request.wfile.write(payload)
