"""ReliefWeb API - humanitarian crisis reports & disasters.

Auth: no key, but since 2025-11-01 a pre-approved `appname` query
parameter is required. Docs: https://apidoc.reliefweb.int/index.html
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os as _os

from lib.integrations import _safe_post

API = "https://api.reliefweb.int/v2"
APPNAME = _os.getenv("SIGNAL_RELIEFWEB_APPNAME", "signal-research-bot")


def _report_url(fields: dict, item_id: str | int | None) -> str | None:
    url = fields.get("url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    alias = fields.get("url_alias")
    if alias:
        alias = str(alias).lstrip("/")
        return f"https://reliefweb.int/{alias}" if alias.startswith("report/") else f"https://reliefweb.int/report/{alias}"
    return f"https://reliefweb.int/report/{item_id}" if item_id else None


async def search_reports(client, query: str = "", *,
                          country: str | None = None,
                          disaster_type: str | None = None,
                          limit: int = 10,
                          days_back: int = 30) -> dict:
    """Search recent humanitarian reports.

    Uses POST JSON because ReliefWeb's nested GET filter syntax is easy to get
    subtly wrong. Country accepts ISO3 or English name (e.g. UKR / Ukraine).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days_back))).strftime("%Y-%m-%dT00:00:00+00:00")
    conditions = [{"field": "date.created", "value": {"from": since}}]
    if country:
        conditions.append({"field": "country", "value": country})
    if disaster_type:
        conditions.append({"field": "disaster_type", "value": disaster_type})

    payload = {
        "limit": max(1, min(50, limit)),
        "profile": "list",
        "preset": "latest",
        "sort": ["date.created:desc"],
        "fields": {"include": [
            "title", "source.name", "date.created", "country.name",
            "disaster_type.name", "language.name", "url", "url_alias",
            "primary_country.name",
        ]},
        "filter": {"operator": "AND", "conditions": conditions},
    }
    if query:
        payload["query"] = {"value": query}

    r = await _safe_post(client, f"{API}/reports", params={"appname": APPNAME}, json=payload, timeout=30)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "reports": []}
    if getattr(r, "status_code", 200) == 403:
        return {
            "error": "ReliefWeb appname not approved",
            "detail": getattr(r, "text", "")[:240],
            "hint": "Request pre-approval for SIGNAL_RELIEFWEB_APPNAME via api-team@reliefweb.int; v2 requires approved appname.",
            "reports": [],
        }
    if getattr(r, "status_code", 200) != 200:
        return {"error": f"ReliefWeb status {r.status_code}: {getattr(r, 'text', '')[:240]}", "reports": []}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}", "reports": []}
    items = d.get("data") or []
    out = []
    for it in items:
        f = it.get("fields") or {}
        sources = f.get("source") or []
        countries = f.get("country") or []
        out.append({
            "title": f.get("title"),
            "url": _report_url(f, it.get("id")),
            "date_created": (f.get("date") or {}).get("created"),
            "country": [c.get("name") for c in countries[:3]],
            "source": [s.get("name") for s in sources[:2]],
            "disaster_type": [(dt or {}).get("name") for dt in (f.get("disaster_type") or [])][:3],
        })
    return {
        "total": d.get("totalCount"),
        "count": len(out),
        "since": since,
        "reports": out,
    }
