from pathlib import Path
import os
import time

import run_cycle


def test_slice_steps_validates_order():
    steps = run_cycle._slice_steps("G2", "D")
    assert [s.key for s in steps] == ["G2", "M", "R", "B", "D"]


def test_run_step_blocks_on_missing_required_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cycle, "ROOT", tmp_path)
    step = run_cycle.StepSpec(
        key="X",
        label="needs input",
        command=["python", "noop.py"],
        required_before=("missing.json",),
    )
    result = run_cycle._run_step(step, dry_run=False)
    assert result["status"] == "blocked"
    assert "missing.json" in result["reason"]


def test_run_step_fails_when_expected_artifact_is_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cycle, "ROOT", tmp_path)
    stale = tmp_path / "out.json"
    stale.write_text("old", encoding="utf-8")
    old_time = time.time() - 60
    os.utime(stale, (old_time, old_time))
    step = run_cycle.StepSpec(
        key="X",
        label="stale output",
        command=["python", "-c", "pass"],
        expected_after=("out.json",),
    )
    result = run_cycle._run_step(step, dry_run=False)
    assert result["status"] == "failed"
    assert result["stale_after"] == ["out.json"]


def test_audit_warns_on_thin_cycle(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cycle, "ROOT", tmp_path)
    (tmp_path / "candidates_wide.json").write_text(
        '{"market_fetch_audit":[{"filter_stats":{"raw":1900,"accepted":120}}],"candidates":[{"condition_id":"0x1"}]}',
        encoding="utf-8",
    )
    (tmp_path / "g2_top25.json").write_text('{"candidates":[{"condition_id":"0x1"}]}', encoding="utf-8")
    (tmp_path / "reasoning_memos.json").write_text('[{"condition_id":"0x1"}]', encoding="utf-8")
    (tmp_path / "forager_results.json").write_text('[]', encoding="utf-8")
    (tmp_path / "dossier_results.json").write_text('{"approved":[],"results":[]}', encoding="utf-8")
    (tmp_path / "monitor_results.json").write_text(
        '[{"recommendation":"HOLD","blockers":["documents_not_crawled"]}]',
        encoding="utf-8",
    )
    (tmp_path / "forager_queue_reasoned.py").write_text(
        "forager_queue = [{'condition_id':'0x1','operator_review':{'approved_for_d':False,'operator_probability':None}}]\n",
        encoding="utf-8",
    )

    audit = run_cycle.audit_artifacts()

    assert audit["market_scope_raw_sum"] == 1900
    assert audit["market_scope_accepted_sum"] == 120
    assert audit["wide_candidates"] == 1
    assert audit["monitor_stale_holds"] == 1
    assert audit["reasoned_queue"] == 1
    assert audit["operator_review_complete"] == 0
    assert audit["operator_ready_for_d"] == 0
    assert any("raw API coverage looks low" in warning for warning in audit["warnings"])
    assert any("HOLD rows with hard blockers" in warning for warning in audit["warnings"])
    assert any("Operator review incomplete" in warning for warning in audit["warnings"])


def test_audit_does_not_count_requested_rows_as_scanned(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cycle, "ROOT", tmp_path)
    (tmp_path / "candidates_wide.json").write_text(
        '{"market_fetch_audit":[{"requested_rows":9800,"filter_stats":{"raw":0,"accepted":0}}],"candidates":[]}',
        encoding="utf-8",
    )

    audit = run_cycle.audit_artifacts()

    assert audit["market_scope_raw_sum"] == 0


def test_audit_warns_when_c_requested_without_operator_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cycle, "ROOT", tmp_path)
    (tmp_path / "candidates_wide.json").write_text('{"candidates":[{}]}', encoding="utf-8")
    (tmp_path / "g2_top25.json").write_text('{"candidates":[{}, {}, {}, {}, {}, {}, {}, {}, {}, {}]}', encoding="utf-8")
    (tmp_path / "forager_queue_reasoned.py").write_text(
        "forager_queue = [{'condition_id':'0x1','operator_review':{'approved_for_d':False,'operator_probability':None}}]\n",
        encoding="utf-8",
    )

    audit = run_cycle.audit_artifacts(active_steps={"G", "G2", "M", "R", "B", "D", "C"})

    assert any("0 reasoned candidates are operator-ready" in warning for warning in audit["warnings"])


def test_write_cycle_report_creates_json_and_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cycle, "ROOT", tmp_path)
    audit = {
        "market_scope_raw_sum": 0,
        "market_scope_accepted_sum": 0,
        "candidate_universe_total": 0,
        "wide_candidates": 0,
        "g2_shortlist": 0,
        "reasoning_memos": 0,
        "forager_results": 0,
        "approved_for_c": 0,
        "monitor_results": 0,
        "reasoned_queue": 0,
        "operator_review_complete": 0,
        "operator_ready_for_d": 0,
        "dossier_gate_counts": {"needs_operator_probability": 2},
        "warnings": ["example warning"],
    }
    json_path, md_path = run_cycle.write_cycle_report(
        "testcycle",
        [{"step": "G", "label": "Universe scan", "status": "dry_run"}],
        audit,
    )

    assert Path(json_path).exists()
    assert Path(md_path).exists()
    assert "example warning" in md_path.read_text(encoding="utf-8")


def test_liquidity_volume_filter_is_not_warning_when_pass_adds_enough_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cycle, "ROOT", tmp_path)
    (tmp_path / "candidates_wide.json").write_text(
        """
        {
          "candidate_universe_total": 4500,
          "market_fetch_audit": [
            {
              "pass": "liquidity_asc",
              "accepted_rows": 1208,
              "new_unique_rows": 676,
              "filter_stats": {"raw": 6000, "volume": 2322, "accepted": 1208}
            }
          ],
          "candidates": [{}, {}, {}]
        }
        """,
        encoding="utf-8",
    )
    (tmp_path / "g2_top25.json").write_text('{"candidates":[{}, {}, {}, {}, {}, {}, {}, {}, {}, {}]}', encoding="utf-8")
    (tmp_path / "monitor_results.json").write_text("[]", encoding="utf-8")

    audit = run_cycle.audit_artifacts()

    assert not any("liquidity_asc filter is heavy" in warning for warning in audit["warnings"])


def test_audit_does_not_warn_about_f_when_f_not_active(monkeypatch, tmp_path):
    monkeypatch.setattr(run_cycle, "ROOT", tmp_path)
    (tmp_path / "candidates_wide.json").write_text('{"candidates":[{}]}', encoding="utf-8")
    (tmp_path / "g2_top25.json").write_text('{"candidates":[{}, {}, {}, {}, {}, {}, {}, {}, {}, {}]}', encoding="utf-8")
    (tmp_path / "reasoning_memos.json").write_text('{"total_candidates": 4, "memos": [{}, {}, {}, {}]}', encoding="utf-8")
    (tmp_path / "monitor_results.json").write_text(
        '[{"recommendation":"REVIEW_STALE_DATA","blockers":["documents_not_crawled"]}]',
        encoding="utf-8",
    )

    audit = run_cycle.audit_artifacts(active_steps={"G", "G2", "M", "R", "B", "D", "C"})

    assert audit["reasoning_memos"] == 4
    assert not any("Command F attention required" in warning for warning in audit["warnings"])
