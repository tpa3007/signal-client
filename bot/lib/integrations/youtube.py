"""YouTube Data API v3 client.

Auth: api_key query param. Quota: 10 000 units/day.
search.list = 100 units; videos.list / channels.list = 1 unit per request.

Use for: campaign debates, candidate interviews, geopolitical briefings,
official channel activity.

Docs: https://developers.google.com/youtube/v3
"""
from __future__ import annotations

import os

from lib.integrations import _safe_get

API_BASE = "https://www.googleapis.com/youtube/v3"


def _key_param() -> dict:
    return {"key": os.getenv("YOUTUBE_API_KEY", "")}


async def search(client, query: str, *, max_results: int = 10,
                  order: str = "relevance",
                  published_after: str | None = None,
                  channel_id: str | None = None,
                  region: str | None = None) -> dict:
    """
    Search YouTube. **Costs 100 quota units per call** — use sparingly.

    Args:
        order: relevance | date | viewCount | rating | title.
        published_after: ISO datetime ("2026-05-01T00:00:00Z").
        region: 2-letter ISO ("US", "UA").
    """
    if not os.getenv("YOUTUBE_API_KEY"):
        return {"error": "YOUTUBE_API_KEY missing in env"}
    if not query.strip():
        return {"error": "query is required"}
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max(1, min(50, max_results)),
        "order": order,
        **_key_param(),
    }
    if published_after:
        params["publishedAfter"] = published_after
    if channel_id:
        params["channelId"] = channel_id
    if region:
        params["regionCode"] = region.upper()
    r = await _safe_get(client, f"{API_BASE}/search", params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    if "error" in d:
        return {"error": d["error"].get("message", "unknown"), "raw": d["error"]}
    items = d.get("items") or []
    return {
        "count": len(items),
        "page_info": d.get("pageInfo"),
        "videos": [
            {
                "video_id": (i.get("id") or {}).get("videoId"),
                "title": (i.get("snippet") or {}).get("title"),
                "channel": (i.get("snippet") or {}).get("channelTitle"),
                "channel_id": (i.get("snippet") or {}).get("channelId"),
                "published_at": (i.get("snippet") or {}).get("publishedAt"),
                "description": (i.get("snippet") or {}).get("description", "")[:200],
                "url": f"https://www.youtube.com/watch?v={(i.get('id') or {}).get('videoId')}",
            }
            for i in items
        ],
    }


async def channel_info(client, channel_id: str) -> dict:
    """1 quota unit. Get subscribers, view count, video count, country, branding."""
    if not os.getenv("YOUTUBE_API_KEY"):
        return {"error": "YOUTUBE_API_KEY missing in env"}
    params = {
        "part": "snippet,statistics,brandingSettings",
        "id": channel_id,
        **_key_param(),
    }
    r = await _safe_get(client, f"{API_BASE}/channels", params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    items = d.get("items") or []
    if not items:
        return {"error": "channel not found"}
    ch = items[0]
    return {
        "channel_id": ch.get("id"),
        "title": (ch.get("snippet") or {}).get("title"),
        "country": (ch.get("snippet") or {}).get("country"),
        "published_at": (ch.get("snippet") or {}).get("publishedAt"),
        "subscribers": int((ch.get("statistics") or {}).get("subscriberCount", 0)),
        "views": int((ch.get("statistics") or {}).get("viewCount", 0)),
        "video_count": int((ch.get("statistics") or {}).get("videoCount", 0)),
    }
