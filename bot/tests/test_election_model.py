"""Election model tests."""
from __future__ import annotations

from lib.election_model import dhondt_allocate, parse_contenders, poll_to_seat_scenarios, model_seats


def test_dhondt_allocates_simple_plurality():
    seats = dhondt_allocate({"A": 100, "B": 60, "C": 40}, total_seats=10)
    assert sum(seats.values()) == 10
    assert seats["A"] > seats["B"] > seats["C"]


def test_threshold_excludes_bloc_below_threshold():
    contenders = parse_contenders([
        {"name": "Civil Contract", "poll": 32.5, "kind": "party"},
        {"name": "Armenia Alliance", "poll": 4.4, "kind": "bloc"},
    ])
    out = model_seats(contenders, target="Civil Contract", total_seats=101, party_threshold=4, bloc_threshold=8)
    excluded = {r["name"] for r in out["excluded"]}
    assert "Armenia Alliance" in excluded
    assert out["target_most_seats"] is True


def test_scenarios_compute_weighted_target_probability():
    out = poll_to_seat_scenarios(
        contenders=[
            {"name": "A", "poll": 40, "kind": "party"},
            {"name": "B", "poll": 35, "kind": "party"},
            {"name": "C", "poll": 10, "kind": "party"},
        ],
        target="A",
        total_seats=20,
        scenarios=[
            {"name": "base", "probability": 0.7},
            {"name": "challenger break", "probability": 0.3, "adjustments": {"A": -10, "B": 10}},
        ],
    )
    assert out["weighted_summary"]["probability_sum"] == 1.0
    assert out["weighted_summary"]["target_most_seats_probability"] == 0.7
    assert out["weighted_summary"]["target_not_most_seats_probability"] == 0.3


def test_adjustments_are_percentage_points_not_full_shares():
    out = poll_to_seat_scenarios(
        contenders=[
            {"name": "A", "poll": 30, "kind": "party"},
            {"name": "B", "poll": 20, "kind": "party"},
        ],
        target="A",
        total_seats=10,
        scenarios=[{"name": "one point", "probability": 1, "adjustments": {"B": 1}}],
    )
    b = out["scenarios"][0]["top_seat_rows"][1]
    assert b["poll_pct"] == 21.0


def test_raw_vote_tie_breaker_counts_target_as_winner():
    out = poll_to_seat_scenarios(
        contenders=[
            {"name": "Civil Contract", "poll": 24.5, "kind": "party"},
            {"name": "Strong Armenia", "poll": 24.1, "kind": "party"},
        ],
        target="Civil Contract",
        total_seats=2,
        tie_breaker="raw_votes",
    )
    assert out["base"]["target_tied_for_most"] is True
    assert out["base"]["target_wins_tie_break"] is True
    assert out["base"]["target_most_seats"] is True


def test_mcp_tool_is_registered(tmp_db):
    import mcp_server

    assert "poll_to_seat_model" in mcp_server.mcp._tool_manager._tools
