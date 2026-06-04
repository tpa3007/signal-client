"""Wikipedia REST + Wikidata entity APIs — keyless.

Wikipedia REST: https://en.wikipedia.org/api/rest_v1/
Wikidata: https://www.wikidata.org/w/api.php
"""
from __future__ import annotations

from urllib.parse import quote

from lib.integrations import _safe_get

WIKI_REST = "https://{lang}.wikipedia.org/api/rest_v1"
WIKIDATA = "https://www.wikidata.org/w/api.php"


async def wikipedia_summary(client, title: str, *, lang: str = "en") -> dict:
    """Page summary: extract, thumbnail, type, description, urls."""
    if not title.strip():
        return {"error": "title is required"}
    url = f"{WIKI_REST.format(lang=lang)}/page/summary/{quote(title.replace(' ', '_'))}"
    r = await _safe_get(client, url)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    return {
        "title": d.get("title"),
        "description": d.get("description"),
        "extract": d.get("extract"),
        "type": d.get("type"),
        "url": (d.get("content_urls") or {}).get("desktop", {}).get("page"),
        "lang": lang,
        "thumbnail": (d.get("thumbnail") or {}).get("source"),
        "wikibase_item": d.get("wikibase_item"),
    }


async def wikidata_search(client, query: str, *, lang: str = "en",
                           limit: int = 7) -> dict:
    """Find Wikidata entity Q-IDs by free text."""
    if not query.strip():
        return {"error": "query is required"}
    params = {
        "action": "wbsearchentities",
        "search": query,
        "language": lang,
        "format": "json",
        "limit": max(1, min(20, limit)),
    }
    r = await _safe_get(client, WIKIDATA, params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "candidates": []}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}", "candidates": []}
    cands = []
    for item in d.get("search", []):
        cands.append({
            "id": item.get("id"),
            "label": item.get("label"),
            "description": item.get("description"),
            "url": "https:" + item.get("url") if item.get("url") else None,
            "concept_uri": item.get("concepturi"),
        })
    return {"count": len(cands), "candidates": cands}


async def wikidata_entity(client, qid: str) -> dict:
    """Pull full claims/labels for a Wikidata entity (e.g. Q12345)."""
    if not qid.strip() or not qid.upper().startswith("Q"):
        return {"error": "qid must look like Q12345"}
    params = {
        "action": "wbgetentities",
        "ids": qid,
        "format": "json",
        "props": "labels|descriptions|claims|sitelinks/urls",
        "languages": "en",
    }
    r = await _safe_get(client, WIKIDATA, params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    ent = (d.get("entities") or {}).get(qid)
    if not ent:
        return {"error": "entity not found"}
    # Compact claim summary: claim_id -> first value
    claims = {}
    for prop, values in (ent.get("claims") or {}).items():
        if not values:
            continue
        mainsnak = values[0].get("mainsnak", {})
        dv = mainsnak.get("datavalue", {})
        v = dv.get("value")
        if isinstance(v, dict):
            v = v.get("id") or v.get("text") or v.get("time") or v
        claims[prop] = v
    return {
        "id": qid,
        "label_en": (ent.get("labels") or {}).get("en", {}).get("value"),
        "description_en": (ent.get("descriptions") or {}).get("en", {}).get("value"),
        "wikipedia_en": ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("url"),
        "claims": claims,
    }
