"""Small election-model helpers for proportional-seat prediction markets.

The goal is not to replace country-specific electoral law. This module gives
Signal a transparent first-pass model for markets where the hidden edge lives in
thresholds, wasted votes, and seat allocation rather than headline polling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Contender:
    name: str
    poll_share: float
    kind: str = "party"
    threshold: float | None = None


def _share(value: float | int | str | None) -> float:
    """Accept either 0.325 or 32.5 and return a 0..1 share."""
    if value is None:
        return 0.0
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    if out < 0:
        return 0.0
    if out > 1.0:
        out = out / 100.0
    return out


def _delta_share(value: float | int | str | None) -> float:
    """Accept delta as percentage points (5 => 0.05) or share (0.05 => 0.05)."""
    if value is None:
        return 0.0
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    if abs(out) >= 1.0:
        out = out / 100.0
    return out


def _threshold_for(contender: Contender, party_threshold: float, bloc_threshold: float) -> float:
    if contender.threshold is not None:
        return _share(contender.threshold)
    kind = contender.kind.strip().lower()
    if kind in {"bloc", "alliance", "coalition"}:
        return bloc_threshold
    return party_threshold


def parse_contenders(contenders: list[dict[str, Any]]) -> list[Contender]:
    out: list[Contender] = []
    for item in contenders:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        poll = _share(item.get("poll_share", item.get("poll", item.get("share"))))
        kind = str(item.get("kind") or "party")
        threshold = item.get("threshold")
        out.append(Contender(name=name, poll_share=poll, kind=kind, threshold=None if threshold is None else _share(threshold)))
    return out


def apply_adjustments(contenders: list[Contender], adjustments: dict[str, float | int] | None) -> list[Contender]:
    if not adjustments:
        return contenders
    lowered = {str(k).strip().lower(): _delta_share(v) for k, v in adjustments.items()}
    adjusted: list[Contender] = []
    for c in contenders:
        delta = lowered.get(c.name.lower(), 0.0)
        adjusted.append(Contender(c.name, max(0.0, c.poll_share + delta), c.kind, c.threshold))
    return adjusted


def allocate_undecided(
    contenders: list[Contender],
    undecided_share: float = 0.0,
    allocations: dict[str, float | int] | None = None,
) -> list[Contender]:
    undecided = _share(undecided_share)
    if undecided <= 0:
        return contenders
    if not contenders:
        return []

    if allocations:
        weights = {str(k).strip().lower(): max(0.0, float(v)) for k, v in allocations.items()}
    else:
        weights = {c.name.lower(): c.poll_share for c in contenders}

    total_weight = sum(weights.get(c.name.lower(), 0.0) for c in contenders)
    if total_weight <= 0:
        total_weight = float(len(contenders))
        weights = {c.name.lower(): 1.0 for c in contenders}

    out: list[Contender] = []
    for c in contenders:
        add = undecided * weights.get(c.name.lower(), 0.0) / total_weight
        out.append(Contender(c.name, c.poll_share + add, c.kind, c.threshold))
    return out


def dhondt_allocate(votes: dict[str, float], total_seats: int) -> dict[str, int]:
    """Allocate seats with the D'Hondt highest-averages method."""
    seats = {name: 0 for name in votes}
    if total_seats <= 0 or not votes:
        return seats

    quotients: list[tuple[float, float, str]] = []
    for name, vote in votes.items():
        if vote <= 0:
            continue
        for divisor in range(1, total_seats + 1):
            quotients.append((vote / divisor, vote, name))

    quotients.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    for _, _, name in quotients[:total_seats]:
        seats[name] += 1
    return seats


def model_seats(
    contenders: list[Contender],
    target: str,
    total_seats: int = 101,
    party_threshold: float = 0.04,
    bloc_threshold: float = 0.08,
    undecided_share: float = 0.0,
    undecided_allocations: dict[str, float | int] | None = None,
    tie_breaker: str = "raw_votes",
) -> dict[str, Any]:
    target_l = target.strip().lower()
    party_threshold = _share(party_threshold)
    bloc_threshold = _share(bloc_threshold)
    contenders = allocate_undecided(contenders, undecided_share, undecided_allocations)

    total_modeled_vote = sum(c.poll_share for c in contenders)
    qualifying: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    votes: dict[str, float] = {}

    for c in contenders:
        threshold = _threshold_for(c, party_threshold, bloc_threshold)
        row = {
            "name": c.name,
            "kind": c.kind,
            "poll_share": round(c.poll_share, 4),
            "poll_pct": round(c.poll_share * 100, 2),
            "threshold": round(threshold, 4),
            "threshold_pct": round(threshold * 100, 2),
        }
        if c.poll_share + 1e-12 >= threshold:
            qualifying.append(row)
            votes[c.name] = c.poll_share
        else:
            excluded.append(row)

    seats = dhondt_allocate(votes, int(total_seats))
    qualifying_vote = sum(votes.values())
    rows = []
    for q in qualifying:
        name = q["name"]
        normalized = votes[name] / qualifying_vote if qualifying_vote else 0.0
        rows.append({
            **q,
            "normalized_qualifying_share": round(normalized, 4),
            "normalized_qualifying_pct": round(normalized * 100, 2),
            "seats": seats.get(name, 0),
            "seat_share": round(seats.get(name, 0) / total_seats, 4) if total_seats else 0.0,
        })
    rows.sort(key=lambda r: (r["seats"], r["poll_share"], r["name"]), reverse=True)

    winner = rows[0]["name"] if rows else None
    target_row = next((r for r in rows if r["name"].lower() == target_l), None)
    target_excluded = next((r for r in excluded if r["name"].lower() == target_l), None)
    target_seats = int(target_row["seats"]) if target_row else 0
    max_other_seats = max((int(r["seats"]) for r in rows if r["name"].lower() != target_l), default=0)
    tied_rows = [r for r in rows if target_row and int(r["seats"]) == target_seats]
    target_tied = bool(target_row and target_seats == max_other_seats)
    target_wins_tie_break = False
    if target_tied and tie_breaker == "raw_votes":
        target_poll = float(target_row["poll_share"]) if target_row else 0.0
        target_wins_tie_break = all(target_poll >= float(r["poll_share"]) for r in tied_rows)
    target_most = bool(target_row and (target_seats > max_other_seats or target_wins_tie_break))

    return {
        "target": target,
        "total_seats": int(total_seats),
        "party_threshold": round(party_threshold, 4),
        "bloc_threshold": round(bloc_threshold, 4),
        "tie_breaker": tie_breaker,
        "total_modeled_vote_share": round(total_modeled_vote, 4),
        "qualifying_vote_share": round(qualifying_vote, 4),
        "wasted_vote_share": round(max(0.0, total_modeled_vote - qualifying_vote), 4),
        "winner": winner,
        "target_qualified": target_row is not None,
        "target_seats": target_seats,
        "target_rank": next((idx + 1 for idx, r in enumerate(rows) if r["name"].lower() == target_l), None),
        "target_most_seats": target_most,
        "target_tied_for_most": target_tied,
        "target_wins_tie_break": target_wins_tie_break,
        "seat_rows": rows,
        "excluded": excluded,
        "target_excluded": target_excluded,
        "limitations": [
            "This is a first-pass proportional-seat model, not a certified country-specific legal simulator.",
            "D'Hondt tie-breaks, reserved seats, stable-majority bonuses, second rounds, alliances, and post-election coalitions may require a country-specific layer.",
            "Poll error and undecided allocation dominate the uncertainty; use scenario probabilities, not the base output alone.",
        ],
    }


def poll_to_seat_scenarios(
    contenders: list[dict[str, Any]],
    target: str,
    total_seats: int = 101,
    party_threshold: float = 0.04,
    bloc_threshold: float = 0.08,
    undecided_share: float = 0.0,
    undecided_allocations: dict[str, float | int] | None = None,
    tie_breaker: str = "raw_votes",
    scenarios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parsed = parse_contenders(contenders)
    base = model_seats(
        parsed,
        target=target,
        total_seats=total_seats,
        party_threshold=party_threshold,
        bloc_threshold=bloc_threshold,
        undecided_share=undecided_share,
        undecided_allocations=undecided_allocations,
        tie_breaker=tie_breaker,
    )

    scenario_rows: list[dict[str, Any]] = []
    if scenarios:
        probability_sum = 0.0
        target_most_prob = 0.0
        target_tie_prob = 0.0
        for raw in scenarios:
            prob = _share(raw.get("probability", 0.0))
            probability_sum += prob
            adjusted = apply_adjustments(parsed, raw.get("adjustments") or {})
            scenario_undecided = raw.get("undecided_share", undecided_share)
            scenario_alloc = raw.get("undecided_allocations", undecided_allocations)
            result = model_seats(
                adjusted,
                target=target,
                total_seats=total_seats,
                party_threshold=party_threshold,
                bloc_threshold=bloc_threshold,
                undecided_share=scenario_undecided,
                undecided_allocations=scenario_alloc,
                tie_breaker=tie_breaker,
            )
            if result["target_most_seats"]:
                target_most_prob += prob
            elif result["target_tied_for_most"]:
                target_tie_prob += prob
            scenario_rows.append({
                "name": raw.get("name") or f"scenario_{len(scenario_rows) + 1}",
                "probability": round(prob, 4),
                "target_most_seats": result["target_most_seats"],
                "target_tied_for_most": result["target_tied_for_most"],
                "target_wins_tie_break": result["target_wins_tie_break"],
                "winner": result["winner"],
                "target_seats": result["target_seats"],
                "target_rank": result["target_rank"],
                "top_seat_rows": result["seat_rows"][:5],
            })
        weighted = {
            "probability_sum": round(probability_sum, 4),
            "target_most_seats_probability": round(target_most_prob, 4),
            "target_not_most_seats_probability": round(max(0.0, probability_sum - target_most_prob - target_tie_prob), 4),
            "target_tied_for_most_probability": round(target_tie_prob, 4),
            "probability_sum_warning": abs(probability_sum - 1.0) > 0.02,
        }
    else:
        weighted = {
            "probability_sum": None,
            "target_most_seats_probability": 1.0 if base["target_most_seats"] else 0.0,
            "target_not_most_seats_probability": 0.0 if base["target_most_seats"] else 1.0,
            "target_tied_for_most_probability": 1.0 if base["target_tied_for_most"] and not base["target_most_seats"] else 0.0,
            "probability_sum_warning": False,
        }

    return {
        "target": target,
        "base": base,
        "scenarios": scenario_rows,
        "weighted_summary": weighted,
    }
