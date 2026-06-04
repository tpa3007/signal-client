"""ProPublica Nonprofit Explorer — GET-only, no auth.

Use for: 501(c) orgs, foundation funding, dark-money flow proxies in actor
maps. The deprecated Congress API has been retired — this is the
documented replacement that still works.

Docs: https://projects.propublica.org/nonprofits/api
"""
from __future__ import annotations

from lib.integrations import _safe_get

API_BASE = "https://projects.propublica.org/nonprofits/api/v2"


async def search_orgs(client, query: str, *, state: str | None = None,
                      ntee_category: int | None = None,
                      c_code: int | None = None) -> dict:
    """Search nonprofit organizations.

    Args:
        ntee_category: 1..10 (NTEE major group).
        c_code: 3, 4, 5, 6 etc. (501(c)(N) type).
    """
    if not query.strip():
        return {"error": "query is required"}
    params = {"q": query}
    if state:
        params["state[id]"] = state.upper()
    if ntee_category:
        params["ntee[id]"] = ntee_category
    if c_code:
        params["c_code[id]"] = c_code
    r = await _safe_get(client, f"{API_BASE}/search.json", params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    orgs = d.get("organizations") or []
    return {
        "count": d.get("total_results"),
        "page": d.get("cur_page"),
        "organizations": [
            {
                "ein": o.get("ein"),
                "name": o.get("name"),
                "city": o.get("city"),
                "state": o.get("state"),
                "ntee_code": o.get("ntee_code"),
                "raw_ntee_code": o.get("raw_ntee_code"),
                "subseccd": o.get("subseccd"),
            }
            for o in orgs
        ],
    }


async def organization(client, ein: int | str) -> dict:
    """Detailed view of one organization by EIN."""
    r = await _safe_get(client, f"{API_BASE}/organizations/{ein}.json")
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    org = d.get("organization") or {}
    filings = d.get("filings_with_data") or []
    return {
        "ein": org.get("ein"),
        "name": org.get("name"),
        "address": org.get("address"),
        "city": org.get("city"),
        "state": org.get("state"),
        "ntee_code": org.get("ntee_code"),
        "subseccd": org.get("subseccd"),
        "ruling_date": org.get("ruling_date"),
        "recent_filings_count": len(filings),
        "recent_filings": [
            {
                "tax_period": f.get("tax_prd"),
                "totrevenue": f.get("totrevenue"),
                "totfuncexpns": f.get("totfuncexpns"),
                "totassetsend": f.get("totassetsend"),
                "pdf_url": f.get("pdf_url"),
            }
            for f in filings[:5]
        ],
    }
