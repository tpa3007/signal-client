"""Election modeling tools for proportional-seat markets."""
from __future__ import annotations

from lib.election_model import poll_to_seat_scenarios


def register(mcp):
    @mcp.tool()
    def poll_to_seat_model(
        target: str,
        contenders: list[dict],
        total_seats: int = 101,
        party_threshold: float = 0.04,
        bloc_threshold: float = 0.08,
        undecided_share: float = 0.0,
        undecided_allocations: dict | None = None,
        tie_breaker: str = "raw_votes",
        scenarios: list[dict] | None = None,
    ) -> dict:
        """
        Convert polling into approximate proportional seat allocation.

        Use this for markets whose hidden edge lives in election mechanics:
        thresholds, wasted votes, fragmented fields, and undecided allocation.
        Inputs accept shares as either 0.325 or 32.5. Scenario adjustments are
        percentage points when absolute value is >= 1 (5 => +5pp), or direct
        share deltas when smaller (0.05 => +5pp). Set tie_breaker='raw_votes'
        for markets where equal seats resolve by valid votes.
        """
        if not target.strip():
            return {"error": "target is required"}
        if not contenders:
            return {"error": "contenders are required"}
        return poll_to_seat_scenarios(
            contenders=contenders,
            target=target,
            total_seats=total_seats,
            party_threshold=party_threshold,
            bloc_threshold=bloc_threshold,
            undecided_share=undecided_share,
            undecided_allocations=undecided_allocations,
            tie_breaker=tie_breaker,
            scenarios=scenarios,
        )
