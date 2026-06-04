"""GDELT 2.0 DocAPI client - keyless news/event search.

Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""
from __future__ import annotations

from lib.integrations import _safe_get

DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _status_error(r, *, payload_key: str) -> dict | None:
    status = getattr(r, "status_code", 200)
    empty = [] if payload_key in {"articles", "timeline"} else None
    if status == 429:
        return {"error": "GDELT rate limited (429); retry after a short cooldown", payload_key: empty}
    if status != 200:
        return {"error": f"GDELT status {status}: {getattr(r, 'text', '')[:160]}", payload_key: empty}
    return None


async def search_articles(client, query: str, *, days_back: int = 7,
                          max_records: int = 25,
                          domain: str | None = None,
                          country: str | None = None,
                          sort: str = "datedesc") -> dict:
    """
    Search GDELT for news articles. Returns parsed JSON.

    Args:
        query: GDELT search expression. Supports phrases, AND/OR, themes.
        days_back: window (1-365), GDELT defaults to past day.
        max_records: 1-250.
        domain: restrict to news domain ("reuters.com").
        country: 2-letter ISO ("UA", "RU", "US").
        sort: datedesc | dateasc | tonedesc | toneasc.
    """
    if not query.strip():
        return {"error": "query is required"}
    timespan = f"{max(1, min(365, days_back))}d"
    q = query
    if domain:
        q += f" domain:{domain}"
    if country:
        q += f" sourcecountry:{country}"
    params = {
        "query": q,
        "mode": "artlist",
        "format": "json",
        "maxrecords": max(1, min(250, max_records)),
        "timespan": timespan,
        "sort": sort,
    }
    r = await _safe_get(client, DOC_API, params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "articles": []}
    if err := _status_error(r, payload_key="articles"):
        return err
    try:
        data = r.json()
    except Exception as e:
        return {"error": f"parse: {e}; status={getattr(r, 'status_code', None)}; content_type={getattr(r, 'headers', {}).get('content-type', '')}; preview={getattr(r, 'text', '')[:120]}", "articles": []}
    arts = data.get("articles") or []
    out = []
    for a in arts:
        out.append({
            "url": a.get("url"),
            "title": a.get("title"),
            "domain": a.get("domain"),
            "language": a.get("language"),
            "seendate": a.get("seendate"),
            "tone": a.get("tone"),
            "social_image": a.get("socialimage"),
        })
    return {"count": len(out), "articles": out, "query_used": q, "timespan": timespan}


async def article_volume_timeline(client, query: str, *, days_back: int = 14) -> dict:
    """Return article-volume time series for a query."""
    if not query.strip():
        return {"error": "query is required"}
    params = {
        "query": query,
        "mode": "timelinevol",
        "format": "json",
        "timespan": f"{max(1, min(365, days_back))}d",
    }
    r = await _safe_get(client, DOC_API, params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "timeline": []}
    if err := _status_error(r, payload_key="timeline"):
        return err
    try:
        data = r.json()
    except Exception as e:
        return {"error": f"parse: {e}; status={getattr(r, 'status_code', None)}; content_type={getattr(r, 'headers', {}).get('content-type', '')}; preview={getattr(r, 'text', '')[:120]}", "timeline": []}
    timeline = []
    for series in data.get("timeline", []):
        for pt in series.get("data", []):
            timeline.append({"date": pt.get("date"), "value": pt.get("value")})
    return {"points": len(timeline), "timeline": timeline}
