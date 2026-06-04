import importlib


def test_command_c_blocks_missing_operator_handoff(tmp_db):
    command_c = importlib.import_module("run_command_c")

    blockers = command_c._operator_handoff_blockers({
        "condition_id": "0x1",
        "primary_archetype": "general_research",
        "operator_approved": True,
        "operator_probability": 0.62,
        "market_mechanics_verified": True,
        "operator_reject_reasons_checked": False,
        "disconfirming_evidence_checked": True,
        "cluster_exposure_checked": True,
    })

    assert blockers == ["operator_reject_reasons_checked"]


def test_command_c_accepts_complete_operator_handoff(tmp_db):
    command_c = importlib.import_module("run_command_c")

    blockers = command_c._operator_handoff_blockers({
        "condition_id": "0x1",
        "primary_archetype": "general_research",
        "operator_approved": True,
        "operator_probability": 0.62,
        "market_mechanics_verified": True,
        "operator_reject_reasons_checked": True,
        "disconfirming_evidence_checked": True,
        "cluster_exposure_checked": True,
    })

    assert blockers == []
