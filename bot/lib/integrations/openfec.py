"""OpenFEC client — US federal campaign finance.

Auth: api_key query param. Free key from https://api.open.fec.gov/developers/
Limits: 1000 req/h, 7500 req/day.
"""
from __future__ import annotations

import os

from lib.integrations import _safe_get

API_BASE = "https://api.open.fec.gov/v1"


def _with_key(params: dict) -> dict:
    key = os.getenv("OPENFEC_API_KEY")
    out = dict(params)
    out["api_key"] = key or "DEMO_KEY"
    return out


async def _get(client, path: str, params: dict) -> dict:
    r = await _safe_get(client, f"{API_BASE}/{path.lstrip('/')}",
                       params=_with_key(params))
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    if not os.getenv("OPENFEC_API_KEY"):
        return {"error": "OPENFEC_API_KEY missing in env"}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}


async def candidate_search(client, name: str, *, state: str | None = None,
                            cycle: int | None = None,
                            office: str | None = None) -> dict:
    """Search candidates by name (partial OK).

    Args:
        state: 2-letter ("ME", "KS").
        cycle: election cycle, e.g. 2026.
        office: H (House) | S (Senate) | P (President).
    """
    params = {"q": name, "per_page": 20}
    if state:
        params["state"] = state.upper()
    if cycle:
        params["cycle"] = cycle
    if office:
        params["office"] = office.upper()
    data = await _get(client, "candidates/search", params)
    if "error" in data:
        return data
    results = data.get("results") or []
    return {
        "count": len(results),
        "candidates": [
            {
                "candidate_id": r.get("candidate_id"),
                "name": r.get("name"),
                "office": r.get("office"),
                "office_full": r.get("office_full"),
                "party": r.get("party"),
                "state": r.get("state"),
                "district": r.get("district"),
                "election_years": r.get("election_years"),
                "incumbent_challenge": r.get("incumbent_challenge_full"),
            }
            for r in results
        ],
    }


async def candidate_totals(client, candidate_id: str, cycle: int = 2026) -> dict:
    """Receipts + disbursements + cash on hand for a candidate."""
    params = {"cycle": cycle, "per_page": 1}
    data = await _get(client, f"candidate/{candidate_id}/totals", params)
    if "error" in data:
        return data
    results = data.get("results") or []
    if not results:
        return {"candidate_id": candidate_id, "cycle": cycle, "totals": None}
    r = results[0]
    return {
        "candidate_id": candidate_id,
        "cycle": cycle,
        "receipts": r.get("receipts"),
        "disbursements": r.get("disbursements"),
        "cash_on_hand_end_period": r.get("cash_on_hand_end_period"),
        "debts_owed_by_committee": r.get("debts_owed_by_committee"),
        "individual_contributions": r.get("individual_contributions"),
        "transfers_from_other_authorized_committee": r.get("transfers_from_other_authorized_committee"),
        "coverage_end_date": r.get("coverage_end_date"),
    }


async def late_spending(client, candidate_id: str, cycle: int = 2026,
                         per_page: int = 20) -> dict:
    """24/48-hour pre-election independent expenditures targeting a candidate.
    These flag late surges in outside support/opposition — useful gauge for
    last-week primary swings.
    """
    params = {
        "candidate_id": candidate_id,
        "cycle": cycle,
        "per_page": max(1, min(100, per_page)),
        "sort": "-expenditure_date",
    }
    data = await _get(client, "schedules/schedule_e", params)
    if "error" in data:
        return data
    results = data.get("results") or []
    return {
        "candidate_id": candidate_id,
        "cycle": cycle,
        "count": len(results),
        "expenditures": [
            {
                "date": r.get("expenditure_date"),
                "amount": r.get("expenditure_amount"),
                "support_or_oppose": r.get("support_oppose_indicator"),
                "committee_name": (r.get("committee") or {}).get("name") or r.get("committee_name"),
                "payee_name": r.get("payee_name"),
                "description": r.get("expenditure_description"),
            }
            for r in results
        ],
    }
