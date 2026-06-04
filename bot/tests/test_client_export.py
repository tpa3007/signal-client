from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path

from export_client_repo import export_client_repo


def test_export_client_repo_contains_contracts_and_no_private_artifacts(tmp_path):
    target = export_client_repo(tmp_path / "signal-client")

    expected = [
        "AGENTS.md",
        "CLAUDE.md",
        "INSTRUCTIONS.md",
        "INTEGRITY.lock",
        "LICENSE",
        "PUBLISHING.md",
        "TERMS.md",
        "pyproject.toml",
        "run_client_audit.py",
        "rules.json",
        "signal_client/audit.py",
        "signal_client/integrity.py",
    ]
    for rel in expected:
        assert (target / rel).exists(), rel

    exported = [p.relative_to(target).as_posix() for p in target.rglob("*")]
    assert "bot.db" not in exported
    assert not any("llm_handoff" in p for p in exported)
    assert not any(p.endswith((".db", ".sqlite", ".sqlite3")) for p in exported)


def test_exported_integrity_lock_detects_rule_changes(tmp_path):
    target = export_client_repo(tmp_path / "signal-client")
    sys.path.insert(0, str(target))
    try:
        from signal_client.integrity import verify_lock

        assert verify_lock(target)["ok"] is True
        rules = json.loads((target / "rules.json").read_text(encoding="utf-8"))
        rules["thresholds"]["near_deadline_days"] = 99
        (target / "rules.json").write_text(json.dumps(rules), encoding="utf-8")

        result = verify_lock(target)
        assert result["ok"] is False
        assert "rules.json" in result["changed"]
    finally:
        sys.path.remove(str(target))


def test_exported_runner_writes_local_audit_and_anonymized_report(tmp_path):
    target = export_client_repo(tmp_path / "signal-client")
    positions = [
        {
            "conditionId": "0x1",
            "title": "Will annual inflation be 4.3% in May?",
            "outcome": "No",
            "size": 150,
            "avgPrice": 0.56,
            "curPrice": 0.58,
            "endDate": "2026-06-10T08:00:00Z",
        },
        {
            "conditionId": "0x2",
            "title": "Will a candidate win the governor election?",
            "outcome": "Yes",
            "size": 500,
            "avgPrice": 0.20,
            "curPrice": 0.10,
            "endDate": "2026-06-03T08:00:00Z",
        },
    ]
    positions_path = tmp_path / "positions.json"
    positions_path.write_text(json.dumps(positions), encoding="utf-8")
    out_dir = tmp_path / "audits"

    result = subprocess.run(
        [
            sys.executable,
            str(target / "run_client_audit.py"),
            "--positions-json",
            str(positions_path),
            "--wallet",
            "0xSECRET",
            "--out",
            str(out_dir),
        ],
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    reports = list(out_dir.glob("run_report_*.json"))
    audits = list(out_dir.glob("audit_*.md"))
    assert len(reports) == 1
    assert len(audits) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["positions_count"] == 2
    assert report["wallet"] is None
    assert "Signal Client Portfolio Audit" in audits[0].read_text(encoding="utf-8")


def test_exported_runner_auto_shares_when_endpoint_is_configured(tmp_path, monkeypatch):
    target = export_client_repo(tmp_path / "signal-client")
    positions_path = tmp_path / "positions.json"
    positions_path.write_text(
        json.dumps([
            {
                "conditionId": "0x1",
                "title": "Will annual inflation be 4.3% in May?",
                "outcome": "No",
                "size": 150,
                "avgPrice": 0.56,
                "curPrice": 0.58,
            }
        ]),
        encoding="utf-8",
    )

    monkeypatch.setenv("SIGNAL_CLIENT_SHARE_ENDPOINT", "https://signal.example/api/ingest")
    monkeypatch.setenv("SIGNAL_CLIENT_SHARE_SECRET", "secret")

    spec = importlib.util.spec_from_file_location("exported_run_client_audit", target / "run_client_audit.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    calls = []

    def fake_post_json(url, payload, *, secret, timeout=20):
        calls.append({"url": url, "payload": payload, "secret": secret})
        return {"ok": True}

    monkeypatch.setattr(module, "post_json", fake_post_json)

    rc = module.main([
        "--positions-json",
        str(positions_path),
        "--wallet",
        "0xSECRET",
        "--out",
        str(tmp_path / "audits"),
    ])

    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["url"] == "https://signal.example/api/ingest"
    assert calls[0]["secret"] == "secret"
    assert calls[0]["payload"]["run_report_json"]["wallet"] is None
    assert "Signal Client Portfolio Audit" in calls[0]["payload"]["audit_md"]
