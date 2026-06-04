"""Wikidata SPARQL endpoint — politicians lookup.

For complex queries (current office holders, MPs by country, etc.).
For simple entity-by-name use lib.integrations.wikipedia.wikidata_search.

Endpoint: https://query.wikidata.org/sparql
No auth, but identifying User-Agent is required and queries should be cached.
"""
from __future__ import annotations

from lib.integrations import _safe_get, USER_AGENT

SPARQL = "https://query.wikidata.org/sparql"


async def _sparql(client, query: str) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    r = await _safe_get(client, SPARQL, params={"query": query, "format": "json"},
                       headers=headers, timeout=30)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}


async def current_office_holders(client, *, position_qid: str,
                                  limit: int = 30) -> dict:
    """Find who currently holds a given political office.

    Args:
        position_qid: Wikidata Q-ID of the position (e.g. Q11696 for President
            of the United States, Q5145 for member of US House).
    """
    # `position held` = P39, `start time` = P580, `end time` = P582
    # Current = has start but no end (or end > today)
    query = f"""
    SELECT DISTINCT ?person ?personLabel ?start ?countryLabel WHERE {{
      ?person p:P39 ?statement .
      ?statement ps:P39 wd:{position_qid} .
      OPTIONAL {{ ?statement pq:P580 ?start . }}
      OPTIONAL {{ ?statement pq:P582 ?end . }}
      OPTIONAL {{ ?person wdt:P27 ?country . }}
      FILTER NOT EXISTS {{ ?statement pq:P582 ?endTime . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT {max(1, min(100, limit))}
    """
    d = await _sparql(client, query)
    if "error" in d:
        return d
    rows = (d.get("results") or {}).get("bindings") or []
    out = []
    for row in rows:
        out.append({
            "qid": (row.get("person") or {}).get("value", "").rsplit("/", 1)[-1],
            "name": (row.get("personLabel") or {}).get("value"),
            "start_date": (row.get("start") or {}).get("value", "")[:10],
            "country": (row.get("countryLabel") or {}).get("value"),
        })
    return {"count": len(out), "holders": out, "position_qid": position_qid}


async def politicians_in_country(client, country_qid: str, *,
                                  limit: int = 30) -> dict:
    """List politicians by country (citizens with 'occupation = politician').

    Args:
        country_qid: e.g. Q31 (Belgium), Q399 (Armenia), Q218 (Romania).
    """
    query = f"""
    SELECT DISTINCT ?p ?pLabel ?occLabel ?partyLabel WHERE {{
      ?p wdt:P31 wd:Q5 ;
         wdt:P27 wd:{country_qid} ;
         wdt:P106 ?occ .
      ?occ wdt:P279* wd:Q82955 .
      OPTIONAL {{ ?p wdt:P102 ?party . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT {max(1, min(100, limit))}
    """
    d = await _sparql(client, query)
    if "error" in d:
        return d
    rows = (d.get("results") or {}).get("bindings") or []
    return {
        "count": len(rows),
        "politicians": [
            {
                "qid": (r.get("p") or {}).get("value", "").rsplit("/", 1)[-1],
                "name": (r.get("pLabel") or {}).get("value"),
                "occupation": (r.get("occLabel") or {}).get("value"),
                "party": (r.get("partyLabel") or {}).get("value"),
            }
            for r in rows
        ],
    }
