from __future__ import annotations

import json

import db
import mcp_server  # noqa: F401


def _call_tool(name: str, **kwargs):
    tool = mcp_server.mcp._tool_manager._tools[name]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or getattr(tool, "callback", None)
    assert fn is not None, f"could not locate underlying fn on {tool!r}"
    return fn(**kwargs)


def test_workflow_run_helpers_round_trip(tmp_db):
    with db.connect() as conn:
        run_id = db.start_workflow_run(
            conn,
            workflow_name="test_workflow",
            workflow_level="L9 test",
            agent_name="pytest-agent",
            input_json={"goal": "round-trip"},
        )
        step_id = db.add_workflow_step(
            conn,
            workflow_run_id=run_id,
            step_name="load_state",
            status="completed",
            allowed_writes=["workflow_steps"],
            writes_count=1,
            output_json={"ok": True},
        )
        db.finish_workflow_run(conn, run_id, status="completed", output_json={"done": True})
        conn.commit()

        detail = db.workflow_run_detail(conn, run_id)
        assert detail is not None
        assert detail["run"]["workflow_name"] == "test_workflow"
        assert detail["run"]["agent_name"] == "pytest-agent"
        assert detail["run"]["status"] == "completed"
        assert json.loads(detail["run"]["input_json"])["goal"] == "round-trip"
        assert json.loads(detail["run"]["output_json"])["done"] is True
        assert detail["steps"][0]["id"] == step_id
        assert detail["steps"][0]["step_name"] == "load_state"
        assert json.loads(detail["steps"][0]["allowed_writes"]) == ["workflow_steps"]


def test_workflow_mcp_tools_round_trip(tmp_db):
    started = _call_tool(
        "start_workflow_run",
        workflow_name="manual_lab_run",
        workflow_level="L2 deep research",
        agent_name="pytest-agent",
        input_payload={"condition_id": "0xabc"},
    )
    run_id = started["workflow_run_id"]
    step = _call_tool(
        "record_workflow_step",
        workflow_run_id=run_id,
        step_name="source_check",
        status="blocked",
        condition_id="0xabc",
        allowed_writes=[],
        blocker="primary_source_missing",
        output_payload={"next_action": "find_primary_source"},
    )
    finished = _call_tool(
        "finish_workflow_run",
        workflow_run_id=run_id,
        status="blocked",
        output_payload={"blocked_reason": "primary_source_missing"},
    )
    detail = _call_tool("workflow_run_detail", workflow_run_id=run_id)

    assert step["workflow_step_id"]
    assert finished["status"] == "blocked"
    assert detail["run"]["status"] == "blocked"
    assert detail["steps"][0]["blocker"] == "primary_source_missing"


def test_aladdin_signal_commit_logs_blocked_gate(tmp_db):
    out = _call_tool(
        "aladdin_signal_commit",
        condition_id="0xmissing_market",
        probability_yes=0.60,
        confidence=0.70,
        side="YES",
        dry_run=True,
    )

    assert out["signal_created"] is False
    assert out["gate_passed"] is False
    assert out["workflow_run_id"]
    detail = _call_tool("workflow_run_detail", workflow_run_id=out["workflow_run_id"])
    assert detail["run"]["workflow_name"] == "aladdin_signal_commit"
    assert detail["run"]["status"] == "blocked"
    assert detail["steps"][0]["step_name"] == "validate_signal_gate"
    assert detail["steps"][0]["status"] == "blocked"
    assert "market_not_found" in detail["steps"][0]["blocker"]
