import json

from api.client_runs import create_client_run, get_client_run


def _decode(response):
    status, headers, body = response
    return status, headers, json.loads(body.decode("utf-8"))


def test_create_client_run_queues_job(tmp_path):
    status, _, payload = _decode(
        create_client_run(
            {"X-Signal-Run-Secret": "ok"},
            json.dumps({"client_id": "Client One", "wallet": "0xabc", "commands": "G,G2,W"}),
            secret="ok",
            storage_dir=tmp_path,
        )
    )

    assert status == 202
    assert payload["status"] == "queued"
    assert payload["commands"] == ["G", "G2", "W"]
    job_path = tmp_path / payload["run_id"] / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["client_id"] == "client_one"
    assert job["wallet"] == "0xabc"


def test_create_client_run_rejects_unsupported_command(tmp_path):
    status, _, payload = _decode(
        create_client_run(
            {"X-Signal-Run-Secret": "ok"},
            json.dumps({"wallet": "0xabc", "commands": "G,ROOT"}),
            secret="ok",
            storage_dir=tmp_path,
        )
    )

    assert status == 400
    assert "unsupported command" in payload["error"]


def test_get_client_run_returns_report_when_ready(tmp_path):
    status, _, payload = _decode(
        create_client_run(
            {},
            json.dumps({"positions": [{"title": "A", "side": "YES"}]}),
            storage_dir=tmp_path,
        )
    )
    run_dir = tmp_path / payload["run_id"]
    (run_dir / "status.json").write_text(
        json.dumps({"run_id": payload["run_id"], "status": "completed"}),
        encoding="utf-8",
    )
    (run_dir / "client_report.md").write_text("# Report\n", encoding="utf-8")
    (run_dir / "run_report.json").write_text('{"ok":true}', encoding="utf-8")

    status, _, result = _decode(get_client_run({}, payload["run_id"], storage_dir=tmp_path))

    assert status == 200
    assert result["status"] == "completed"
    assert result["client_report_md"] == "# Report\n"
    assert result["run_report_json"] == {"ok": True}
