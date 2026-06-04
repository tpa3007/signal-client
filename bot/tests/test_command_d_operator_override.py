import run_command_d as command_d


def test_operator_approved_candidates_are_not_prefiltered_by_low_sdv(monkeypatch):
    candidate = {
        "condition_id": "0xoperator",
        "question": "Will a manually reviewed candidate resolve YES?",
        "priority": "P0",
        "operator_review": {"approved_for_d": True},
    }
    packet = {"signal_decision_value": command_d.MIN_SDV_FOR_DOSSIER - 0.01}

    def stop_before_db(*_args, **_kwargs):
        raise RuntimeError("reached_db")

    monkeypatch.setattr(command_d.db, "connect", stop_before_db)

    try:
        command_d.build_dossier_for_candidate(candidate, packet)
    except RuntimeError as exc:
        assert str(exc) == "reached_db"
    else:
        raise AssertionError("Expected build to continue past the SDV prefilter")


def test_non_operator_candidates_are_prefiltered_by_low_sdv():
    candidate = {
        "condition_id": "0xauto",
        "question": "Will an automatic candidate resolve YES?",
        "priority": "P0",
        "operator_review": {"approved_for_d": False},
    }
    packet = {"signal_decision_value": command_d.MIN_SDV_FOR_DOSSIER - 0.01}

    result = command_d.build_dossier_for_candidate(candidate, packet)

    assert result["skipped"] is True
    assert "below threshold" in result["reason"]


def test_reasoned_candidates_are_not_prefiltered_by_low_sdv(monkeypatch):
    candidate = {
        "condition_id": "0xreasoned",
        "question": "Will a reasoned candidate resolve YES?",
        "priority": "P0",
        "requires_operator_review": True,
        "operator_review": {"approved_for_d": False},
    }
    packet = {"signal_decision_value": command_d.MIN_SDV_FOR_DOSSIER - 0.01}

    def stop_before_db(*_args, **_kwargs):
        raise RuntimeError("reached_db")

    monkeypatch.setattr(command_d.db, "connect", stop_before_db)

    try:
        command_d.build_dossier_for_candidate(candidate, packet)
    except RuntimeError as exc:
        assert str(exc) == "reached_db"
    else:
        raise AssertionError("Expected reasoned candidate to continue past the SDV prefilter")


def test_operator_manual_evidence_satisfies_research_plan_evidence_gate(conn):
    conn.execute(
        """
        INSERT INTO markets (condition_id, question, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        ("0xmanualevidence", "Will a manually reviewed candidate resolve YES?", "2026-05-25", "2026-05-25"),
    )
    candidate = {
        "condition_id": "0xmanualevidence",
        "question": "Will a manually reviewed candidate resolve YES?",
        "priority": "P0",
        "yes_price": 0.81,
        "requires_operator_review": True,
        "operator_review": {
            "approved_for_d": True,
            "decisive_fact_status": "confirmed_edge",
            "market_mechanics_verified": True,
            "operator_probability": 0.58,
            "supporting_source_urls": ["https://example.com/a", "https://example.com/b"],
        },
        "research_plan_results": {
            "missing_required_evidence": ["local_poll_or_official_filing"],
        },
    }
    counts = {
        "resolution_maps": 1,
        "evidence": 2,
        "actor_maps": 1,
        "causal_factors": 2,
        "scenario_trees": 3,
        "premortems": 1,
    }

    gate = command_d._run_gate_check(conn, candidate["condition_id"], candidate, None, counts, sdv=0.34)

    assert gate["decision"] != "needs_decisive_fact"


def test_operator_manual_evidence_can_override_low_sdv_gate(conn):
    conn.execute(
        """
        INSERT INTO markets (condition_id, question, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        ("0xmanualsdv", "Will a manually reviewed candidate resolve YES?", "2026-05-25", "2026-05-25"),
    )
    conn.execute(
        """
        INSERT INTO resolution_maps (
            condition_id, created_at, yes_criteria, no_criteria,
            resolution_risk_score, completeness_score
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("0xmanualsdv", "2026-05-25", "YES criteria", "NO criteria", 0.2, 80),
    )
    candidate = {
        "condition_id": "0xmanualsdv",
        "question": "Will a manually reviewed candidate resolve YES?",
        "priority": "P0",
        "yes_price": 0.81,
        "requires_operator_review": True,
        "operator_review": {
            "approved_for_d": True,
            "decisive_fact_status": "confirmed_edge",
            "market_mechanics_verified": True,
            "operator_probability": 0.58,
            "supporting_source_urls": ["https://example.com/a", "https://example.com/b"],
        },
    }
    counts = {
        "resolution_maps": 1,
        "evidence": 2,
        "actor_maps": 1,
        "causal_factors": 2,
        "scenario_trees": 3,
        "premortems": 1,
    }

    gate = command_d._run_gate_check(
        conn,
        candidate["condition_id"],
        candidate,
        {"aggregate_confidence": 0.667, "disconfirming_found": False},
        counts,
        sdv=command_d.MIN_SDV_FOR_GATE - 0.01,
    )

    assert gate["decision"] == "approved_for_signal"
    assert gate["research_quality_warning"] == "forager_research_quality_low_operator_override"
    assert gate["operator_manual_evidence_ok"] is True


def test_operator_manual_evidence_sets_confidence_floor_without_packet(conn):
    conn.execute(
        """
        INSERT INTO markets (condition_id, question, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        ("0xmanualnopacket", "Will a manually reviewed candidate resolve YES?", "2026-05-25", "2026-05-25"),
    )
    conn.execute(
        """
        INSERT INTO resolution_maps (
            condition_id, created_at, yes_criteria, no_criteria,
            resolution_risk_score, completeness_score
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("0xmanualnopacket", "2026-05-25", "YES criteria", "NO criteria", 0.2, 80),
    )
    candidate = {
        "condition_id": "0xmanualnopacket",
        "question": "Will a manually reviewed candidate resolve YES?",
        "priority": "P0",
        "yes_price": 0.12,
        "signal_side": "NO",
        "requires_operator_review": True,
        "operator_review": {
            "approved_for_d": True,
            "decisive_fact_status": "confirmed_for_side",
            "market_mechanics_verified": True,
            "operator_probability": 0.04,
            "supporting_source_urls": ["https://example.com/a", "https://example.com/b"],
        },
    }
    counts = {
        "resolution_maps": 1,
        "evidence": 2,
        "actor_maps": 1,
        "causal_factors": 2,
        "scenario_trees": 3,
        "premortems": 1,
    }

    gate = command_d._run_gate_check(conn, candidate["condition_id"], candidate, None, counts, sdv=0.0)

    assert gate["confidence"] >= 0.62
    assert gate["decision"] == "approved_for_signal"


def test_sdv_still_blocks_automatic_low_quality_gate(conn):
    conn.execute(
        """
        INSERT INTO markets (condition_id, question, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        ("0xautosdv", "Will an automatic candidate resolve YES?", "2026-05-25", "2026-05-25"),
    )
    conn.execute(
        """
        INSERT INTO resolution_maps (
            condition_id, created_at, yes_criteria, no_criteria,
            resolution_risk_score, completeness_score
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("0xautosdv", "2026-05-25", "YES criteria", "NO criteria", 0.2, 80),
    )
    candidate = {
        "condition_id": "0xautosdv",
        "question": "Will an automatic candidate resolve YES?",
        "priority": "P0",
        "yes_price": 0.81,
    }
    counts = {
        "resolution_maps": 1,
        "evidence": 2,
        "actor_maps": 1,
        "causal_factors": 2,
        "scenario_trees": 3,
        "premortems": 1,
    }

    gate = command_d._run_gate_check(
        conn,
        candidate["condition_id"],
        candidate,
        {"aggregate_confidence": 0.667, "disconfirming_found": False},
        counts,
        sdv=command_d.MIN_SDV_FOR_GATE - 0.01,
    )

    assert gate["decision"] in {"needs_source_confidence", "needs_causal_confidence", "paper_only_low_edge", "needs_more_research"}
    assert gate["research_quality_warning"] == "forager_research_quality_low"


def test_degraded_b_blocks_d_without_operator_manual_evidence(conn):
    conn.execute(
        """
        INSERT INTO markets (condition_id, question, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        ("0xdegraded", "Will a degraded research candidate resolve YES?", "2026-05-25", "2026-05-25"),
    )
    conn.execute(
        """
        INSERT INTO resolution_maps (
            condition_id, created_at, yes_criteria, no_criteria,
            resolution_risk_score, completeness_score
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("0xdegraded", "2026-05-25", "YES criteria", "NO criteria", 0.2, 80),
    )
    candidate = {
        "condition_id": "0xdegraded",
        "question": "Will a degraded research candidate resolve YES?",
        "priority": "P0",
        "yes_price": 0.4,
        "requires_operator_review": True,
        "operator_review": {
            "approved_for_d": True,
            "decisive_fact_status": "confirmed_edge",
            "market_mechanics_verified": True,
            "operator_probability": 0.62,
            "supporting_source_urls": [],
        },
        "research_plan_results": {
            "decisive_fact_status": "search_backend_degraded",
            "search_backend_degraded": True,
            "required_evidence_total": 3,
            "required_evidence_found": 0,
            "missing_required_evidence": ["primary_source_found"],
        },
    }
    counts = {
        "resolution_maps": 1,
        "evidence": 2,
        "actor_maps": 1,
        "causal_factors": 2,
        "scenario_trees": 3,
        "premortems": 1,
    }

    gate = command_d._run_gate_check(
        conn,
        candidate["condition_id"],
        candidate,
        {"aggregate_confidence": 0.8, "disconfirming_found": False},
        counts,
        sdv=0.7,
    )

    assert gate["decision"] == "needs_operator_source_urls"
    assert gate["search_backend_degraded"] is True


def test_degraded_b_can_be_overridden_only_with_operator_sources(conn):
    conn.execute(
        """
        INSERT INTO markets (condition_id, question, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        ("0xdegradedok", "Will a manually rescued degraded candidate resolve YES?", "2026-05-25", "2026-05-25"),
    )
    conn.execute(
        """
        INSERT INTO resolution_maps (
            condition_id, created_at, yes_criteria, no_criteria,
            resolution_risk_score, completeness_score
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("0xdegradedok", "2026-05-25", "YES criteria", "NO criteria", 0.2, 80),
    )
    candidate = {
        "condition_id": "0xdegradedok",
        "question": "Will a manually rescued degraded candidate resolve YES?",
        "priority": "P0",
        "yes_price": 0.4,
        "requires_operator_review": True,
        "operator_review": {
            "approved_for_d": True,
            "decisive_fact_status": "confirmed_edge",
            "market_mechanics_verified": True,
            "operator_probability": 0.62,
            "supporting_source_urls": ["https://example.com/a", "https://example.com/b"],
        },
        "research_plan_results": {
            "decisive_fact_status": "search_backend_degraded",
            "search_backend_degraded": True,
            "required_evidence_total": 3,
            "required_evidence_found": 0,
            "missing_required_evidence": ["primary_source_found"],
        },
        "research_plan": {
            "market_mechanics": {
                "yes_resolves_if": "YES criteria",
                "no_resolves_if": "NO criteria",
                "canonical_source": "official source",
                "resolution_authority": "Polymarket",
                "deadline": "2026-05-31",
                "deadline_timezone": "ET",
                "ambiguity_risks": ["none"],
            },
            "edge_thesis": {
                "edge_type": "local_info_asymmetry",
                "what_would_change_my_mind": ["bad source"],
            }
        },
    }
    counts = {
        "resolution_maps": 1,
        "evidence": 2,
        "actor_maps": 1,
        "causal_factors": 2,
        "scenario_trees": 3,
        "premortems": 1,
    }

    gate = command_d._run_gate_check(
        conn,
        candidate["condition_id"],
        candidate,
        {"aggregate_confidence": 0.8, "disconfirming_found": False},
        counts,
        sdv=0.7,
    )

    assert gate["decision"] == "approved_for_signal"
    assert gate["search_backend_degraded"] is True
    assert gate["operator_manual_evidence_ok"] is True


def test_anti_signal_gate_blocks_extreme_lottery_without_manual_evidence(conn):
    conn.execute(
        """
        INSERT INTO markets (condition_id, question, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        ("0xantisignal", "Will a cheap lottery event resolve YES?", "2026-05-25", "2026-05-25"),
    )
    conn.execute(
        """
        INSERT INTO resolution_maps (
            condition_id, created_at, yes_criteria, no_criteria,
            resolution_risk_score, completeness_score
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("0xantisignal", "2026-05-25", "YES criteria", "NO criteria", 0.2, 80),
    )
    candidate = {
        "condition_id": "0xantisignal",
        "question": "Will a cheap lottery event resolve YES?",
        "priority": "P0",
        "yes_price": 0.012,
        "signal_side": "YES",
        "signal_prob": 0.09,
        "research_plan": {
            "edge_thesis": {
                "anti_signal_flags": ["cheap_lottery_risk", "near_deadline_is_not_edge"],
                "edge_type": "catalyst_underpriced",
                "what_would_change_my_mind": ["primary source missing"],
            }
        },
    }
    counts = {
        "resolution_maps": 1,
        "evidence": 2,
        "actor_maps": 1,
        "causal_factors": 2,
        "scenario_trees": 3,
        "premortems": 1,
    }

    gate = command_d._run_gate_check(
        conn,
        candidate["condition_id"],
        candidate,
        {"aggregate_confidence": 0.8, "disconfirming_found": False},
        counts,
        sdv=0.8,
    )

    assert gate["decision"] == "block_anti_signal_gate"
    assert "cheap_lottery_risk" in gate["anti_signal_blockers"]


def test_reasoned_candidate_requires_market_mechanics_before_gate(conn):
    conn.execute(
        """
        INSERT INTO markets (condition_id, question, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        ("0xmechanics", "Will a reasoned candidate resolve YES?", "2026-05-25", "2026-05-25"),
    )
    conn.execute(
        """
        INSERT INTO resolution_maps (
            condition_id, created_at, yes_criteria, no_criteria,
            resolution_risk_score, completeness_score
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("0xmechanics", "2026-05-25", "YES criteria", "NO criteria", 0.2, 80),
    )
    candidate = {
        "condition_id": "0xmechanics",
        "question": "Will a reasoned candidate resolve YES?",
        "priority": "P0",
        "yes_price": 0.4,
        "requires_operator_review": True,
        "operator_review": {
            "approved_for_d": True,
            "decisive_fact_status": "confirmed_edge",
            "operator_probability": 0.62,
            "supporting_source_urls": ["https://example.com/a", "https://example.com/b"],
        },
        "research_plan": {
            "edge_thesis": {
                "edge_type": "local_info_asymmetry",
                "what_would_change_my_mind": ["bad source"],
            }
        },
    }
    counts = {
        "resolution_maps": 1,
        "evidence": 2,
        "actor_maps": 1,
        "causal_factors": 2,
        "scenario_trees": 3,
        "premortems": 1,
    }

    gate = command_d._run_gate_check(
        conn,
        candidate["condition_id"],
        candidate,
        {"aggregate_confidence": 0.8, "disconfirming_found": False},
        counts,
        sdv=0.7,
    )

    assert gate["decision"] == "needs_market_mechanics"
    assert "market_mechanics_missing" in gate["market_mechanics_gaps"]
