from __future__ import annotations

import json

from api.ingest import process_ingest


def test_ingest_requires_shared_secret(tmp_path):
    status, payload = process_ingest(
        headers={"x-signal-client-secret": "bad"},
        body=b"{}",
        secret="good",
        storage_dir=tmp_path,
    )

    assert status == 401
    assert payload["error"] == "unauthorized"


def test_ingest_stores_audit_and_redacts_wallet_without_explicit_consent(tmp_path):
    body = {
        "client_id": "client/one",
        "consent": True,
        "audit_md": "# Audit\n",
        "run_report_json": {
            "positions_count": 2,
            "decision_counts": {"review": 1},
            "wallet": "0xSECRET",
        },
    }

    status, payload = process_ingest(
        headers={"x-signal-client-secret": "good"},
        body=json.dumps(body).encode("utf-8"),
        secret="good",
        storage_dir=tmp_path,
    )

    assert status == 200
    assert payload["ok"] is True
    report_path = tmp_path / "client_one" / payload["run_report_path"].split("client_one\\")[-1]
    if not report_path.exists():
        report_path = next((tmp_path / "client_one").glob("run_report_*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["wallet"] is None
    assert next((tmp_path / "client_one").glob("audit_*.md")).read_text(encoding="utf-8") == "# Audit\n"
