"""GDELT Cloud API v2 client.

Structured access to global conflict/political events, news story clusters,
and entity profiles — with Bearer-token authentication.

Key advantages over free GDELT 2.0 Doc API:
  - Structured event data: country, region, category, event_family
  - market_sensitivity score per event (directly relevant to Signal)
  - significance score, goldstein_scale, fatality tracking
  - Event density by date (group_by=date) → spike detection
  - Semantic search across stories and events
  - entity_refs + actor_refs cross-referencing

API Key env var: GDELT_API_KEY
Base URL: https://gdeltcloud.com/api/v2
Docs: https://docs.gdeltcloud.com/api-reference/v2

Usage (sync):
    from lib.integrations.gdelt_cloud import event_density_spike, search_events_sync
    spike = event_density_spike("Iran nuclear", days=7)
    if spike and spike["spike_ratio"] > 1.5:
        print(spike["summary"])

Usage (async):
    async with httpx.AsyncClient() as client:
        from lib.integrations.gdelt_cloud import search_events
        events = await search_events(client, "Sudan RSF", country="Sudan", limit=5)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import httpx

_BASE = "https://gdeltcloud.com/api/v2"

# Event domains (GDELT Cloud taxonomy)
DOMAIN_POLITICAL = "POLITICAL"
DOMAIN_ECONOMIC = "ECONOMIC"
DOMAIN_CORPORATE = "CORPORATE"
DOMAIN_HEALTH = "HEALTH"
DOMAIN_INFORMATION = "INFORMATION"
DOMAIN_ENVIRONMENT = "ENVIRONMENT"
DOMAIN_CRIME = "CRIME"

# Event families
FAMILY_CONFLICT = "conflict"
FAMILY_CAMEOPLUS = "cameoplus"


def _get_api_key() -> str | None:
    return os.environ.get("GDELT_API_KEY", "").strip() or None


def _auth_headers(api_key: str | None = None) -> dict:
    key = api_key or _get_api_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _date_n_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


# ── Core async methods ────────────────────────────────────────────────────────

async def search_events(
    client: httpx.AsyncClient,
    query: str | None = None,
    *,
    country: str | None = None,
    region: str | None = None,
    continent: str | None = None,
    event_family: str | None = None,       # "conflict" | "cameoplus"
    category: str | None = None,
    domain: str | None = None,             # POLITICAL | ECONOMIC | ...
    has_fatalities: bool | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    sort: str = "significance",            # "significance" | "recent"
    limit: int = 10,
    cursor: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Search GDELT Cloud events with rich filters.

    Returns {success, data: [Event], pagination} or {success: false, error: ...}.
    Each Event includes: id, title, summary, event_date, category, domain,
    geo, actors, metrics (significance, market_sensitivity, goldstein_scale,
    confidence, article_count), has_fatalities, fatalities, top_articles.
    """
    params: dict = {"limit": limit, "sort": sort, "include_images": "false"}
    if query:
        params["search"] = query
    if country:
        params["country"] = country
    if region:
        params["region"] = region
    if continent:
        params["continent"] = continent
    if event_family:
        params["event_family"] = event_family
    if category:
        params["category"] = category
    if domain:
        params["domain"] = domain
    if has_fatalities is not None:
        params["has_fatalities"] = str(has_fatalities).lower()
    if date_start:
        params["date_start"] = date_start
    if date_end:
        params["date_end"] = date_end
    if cursor:
        params["cursor"] = cursor

    try:
        r = await client.get(
            f"{_BASE}/events",
            params=params,
            headers=_auth_headers(api_key),
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        return {"success": False, "error": f"HTTP {exc.response.status_code}", "data": []}
    except Exception as exc:
        return {"success": False, "error": str(exc), "data": []}


async def event_summary_by_date(
    client: httpx.AsyncClient,
    *,
    query: str | None = None,
    country: str | None = None,
    region: str | None = None,
    continent: str | None = None,
    event_family: str | None = None,
    domain: str | None = None,
    has_fatalities: bool | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    limit: int = 30,
    api_key: str | None = None,
) -> dict:
    """Get event count grouped by date — perfect for spike detection.

    Returns {success, data: [{key (date), event_count, conflict_event_count,
    article_count, avg_significance, fatalities, ...}]}.
    """
    params: dict = {
        "group_by": "date",
        "limit": limit,
    }
    if query:
        params["search"] = query
    if country:
        params["country"] = country
    if region:
        params["region"] = region
    if continent:
        params["continent"] = continent
    if event_family:
        params["event_family"] = event_family
    if domain:
        params["domain"] = domain
    if has_fatalities is not None:
        params["has_fatalities"] = str(has_fatalities).lower()
    if date_start:
        params["date_start"] = date_start
    if date_end:
        params["date_end"] = date_end

    try:
        r = await client.get(
            f"{_BASE}/events/summary",
            params=params,
            headers=_auth_headers(api_key),
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        return {"success": False, "error": f"HTTP {exc.response.status_code}", "data": []}
    except Exception as exc:
        return {"success": False, "error": str(exc), "data": []}


async def search_stories(
    client: httpx.AsyncClient,
    query: str | None = None,
    *,
    country: str | None = None,
    region: str | None = None,
    continent: str | None = None,
    domain: str | None = None,
    has_events: bool | None = None,
    has_fatalities: bool | None = None,
    article_count_min: int | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    sort: str = "significance",
    limit: int = 10,
    api_key: str | None = None,
) -> dict:
    """Search news story clusters.

    Stories are clusters of related articles covering the same event.
    Returns {success, data: [Story]} where each Story has: id, title,
    story_date, category, geo, metrics (significance, article_count,
    linked_event_count), linked_events, entity_refs, top_articles.
    """
    params: dict = {"limit": limit, "sort": sort, "include_images": "false"}
    if query:
        params["search"] = query
    if country:
        params["country"] = country
    if region:
        params["region"] = region
    if continent:
        params["continent"] = continent
    if domain:
        params["domain"] = domain
    if has_events is not None:
        params["has_events"] = str(has_events).lower()
    if has_fatalities is not None:
        params["has_fatalities"] = str(has_fatalities).lower()
    if article_count_min:
        params["article_count_min"] = article_count_min
    if date_start:
        params["date_start"] = date_start
    if date_end:
        params["date_end"] = date_end

    try:
        r = await client.get(
            f"{_BASE}/stories",
            params=params,
            headers=_auth_headers(api_key),
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        return {"success": False, "error": f"HTTP {exc.response.status_code}", "data": []}
    except Exception as exc:
        return {"success": False, "error": str(exc), "data": []}


async def get_entity(
    client: httpx.AsyncClient,
    entity_id: str,
    api_key: str | None = None,
) -> dict:
    """Fetch full entity profile with story and event references."""
    try:
        r = await client.get(
            f"{_BASE}/entities/{entity_id}",
            headers=_auth_headers(api_key),
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Spike detection — key function for Command B pre-research ─────────────────

async def _compute_event_spike(
    client: httpx.AsyncClient,
    query: str | None = None,
    *,
    country: str | None = None,
    region: str | None = None,
    event_family: str | None = None,
    domain: str | None = None,
    days: int = 7,
    spike_threshold: float = 1.5,
    api_key: str | None = None,
) -> dict | None:
    """Compute event density spike for a query/country over the last N days.

    Compares last 2 days vs N-day average. Returns spike dict or None.
    """
    result = await event_summary_by_date(
        client,
        query=query,
        country=country,
        region=region,
        event_family=event_family,
        domain=domain,
        date_start=_date_n_days_ago(days),
        date_end=_date_n_days_ago(0),
        limit=days + 5,
        api_key=api_key,
    )
    if not result.get("success") or not result.get("data"):
        return None

    buckets = result["data"]
    if not buckets:
        return None

    # Sort chronologically
    buckets_sorted = sorted(buckets, key=lambda b: b.get("key", ""))

    # Compute daily event counts
    event_counts = [float(b.get("event_count") or 0) for b in buckets_sorted]
    sig_scores = [float(b.get("avg_significance") or 0) for b in buckets_sorted]
    article_counts = [float(b.get("article_count") or 0) for b in buckets_sorted]

    if not event_counts or max(event_counts) == 0:
        return None

    avg_count = sum(event_counts) / len(event_counts)
    recent = event_counts[-2:] if len(event_counts) >= 2 else event_counts[-1:]
    recent_avg = sum(recent) / len(recent) if recent else 0

    if avg_count == 0 or recent_avg == 0:
        return None

    spike_ratio = recent_avg / avg_count

    if spike_ratio < spike_threshold:
        return None

    # Most recent day details
    latest = buckets_sorted[-1]
    latest_date = latest.get("key", "?")
    latest_sig = float(latest.get("avg_significance") or latest.get("max_significance") or 0)
    latest_fatalities = int(latest.get("fatalities") or 0)

    # High-significance events from the spike period
    spike_top = sorted(buckets_sorted[-2:], key=lambda b: float(b.get("avg_significance") or 0), reverse=True)

    summary = (
        f"GDELT Cloud event density spike x{spike_ratio:.2f} "
        f"(recent={recent_avg:.1f} events/day vs {avg_count:.1f} avg/{days}d)"
    )
    if latest_fatalities:
        summary += f" | {latest_fatalities} fatalities on {latest_date}"

    return {
        "spike_ratio": round(spike_ratio, 2),
        "recent_avg_events": round(recent_avg, 1),
        "baseline_avg_events": round(avg_count, 1),
        "days_window": days,
        "latest_date": latest_date,
        "latest_significance": round(latest_sig, 3),
        "latest_fatalities": latest_fatalities,
        "total_events": int(sum(event_counts)),
        "total_articles": int(sum(article_counts)),
        "summary": summary,
        "query": query,
        "country": country,
    }


# ── Sync wrappers for use in non-async code (Command B) ──────────────────────

def event_density_spike(
    query: str | None = None,
    *,
    country: str | None = None,
    region: str | None = None,
    event_family: str | None = None,
    domain: str | None = None,
    days: int = 7,
    spike_threshold: float = 1.5,
    timeout: float = 15.0,
    api_key: str | None = None,
) -> dict | None:
    """Sync wrapper: detect event density spike for a topic/country.

    Returns spike dict or None (no spike / API unavailable).
    Designed for Command B pre-research injection.
    """
    if not (api_key or _get_api_key()):
        return None  # no key configured — skip silently

    import asyncio  # noqa: PLC0415

    async def _run():
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await _compute_event_spike(
                client,
                query=query,
                country=country,
                region=region,
                event_family=event_family,
                domain=domain,
                days=days,
                spike_threshold=spike_threshold,
                api_key=api_key,
            )

    # Detect whether we're already inside an event loop. Calling asyncio.run()
    # from inside one raises RuntimeError; in that case use nest_asyncio or fall
    # through to a thread-pooled run. We choose the simplest safe option:
    # if a loop is running, skip silently (caller has fallbacks).
    try:
        running_loop = asyncio.get_event_loop()
        if running_loop.is_running():
            return None
    except RuntimeError:
        pass
    try:
        return asyncio.run(_run())
    except Exception as exc:
        # Only print on actually unexpected errors, not the asyncio-in-loop case
        if "running event loop" not in str(exc):
            print(f"[GDELTCloud] event_density_spike error: {exc}")
        return None


def search_conflict_events_sync(
    query: str | None = None,
    *,
    country: str | None = None,
    continent: str | None = None,
    has_fatalities: bool | None = None,
    date_start: str | None = None,
    limit: int = 5,
    timeout: float = 15.0,
    api_key: str | None = None,
) -> list[dict]:
    """Sync wrapper: fetch top conflict events for a topic.

    Returns list of event dicts (empty on failure/no key).
    """
    if not (api_key or _get_api_key()):
        return []

    import asyncio  # noqa: PLC0415

    async def _run():
        async with httpx.AsyncClient(timeout=timeout) as client:
            result = await search_events(
                client,
                query=query,
                country=country,
                continent=continent,
                event_family=FAMILY_CONFLICT,
                has_fatalities=has_fatalities,
                date_start=date_start or _date_n_days_ago(14),
                sort="significance",
                limit=limit,
                api_key=api_key,
            )
            return result.get("data") or []

    try:
        return asyncio.run(_run())
    except Exception as exc:
        print(f"[GDELTCloud] search_conflict_events_sync error: {exc}")
        return []


def search_stories_sync(
    query: str,
    *,
    country: str | None = None,
    continent: str | None = None,
    domain: str | None = None,
    date_start: str | None = None,
    limit: int = 5,
    timeout: float = 15.0,
    api_key: str | None = None,
) -> list[dict]:
    """Sync wrapper: fetch top story clusters for a topic.

    Returns list of story dicts (empty on failure/no key).
    """
    if not (api_key or _get_api_key()):
        return []

    import asyncio  # noqa: PLC0415

    async def _run():
        async with httpx.AsyncClient(timeout=timeout) as client:
            result = await search_stories(
                client,
                query,
                country=country,
                continent=continent,
                domain=domain,
                has_events=True,
                date_start=date_start or _date_n_days_ago(14),
                sort="significance",
                limit=limit,
                api_key=api_key,
            )
            return result.get("data") or []

    try:
        return asyncio.run(_run())
    except Exception as exc:
        print(f"[GDELTCloud] search_stories_sync error: {exc}")
        return []


# ── Forager-ready formatting ──────────────────────────────────────────────────

def format_spike_for_forager(spike: dict) -> str:
    """Format a spike result as a Forager seed context block."""
    query_str = f" for '{spike['query']}'" if spike.get("query") else ""
    country_str = f" in {spike['country']}" if spike.get("country") else ""
    return (
        f"📊 GDELT CLOUD EVENT DENSITY SPIKE{query_str}{country_str}\n"
        f"  {spike['summary']}\n"
        f"  Window: {spike['days_window']} days | Total events: {spike['total_events']} "
        f"| Articles: {spike['total_articles']}\n"
        f"  Latest significance: {spike['latest_significance']:.3f} | "
        f"Fatalities: {spike['latest_fatalities']}"
    )


def format_events_for_forager(events: list[dict], max_events: int = 3) -> str:
    """Format conflict events as a Forager seed context block."""
    if not events:
        return ""
    lines = [f"=== GDELT Cloud Conflict Events (top {len(events[:max_events])}) ==="]
    for ev in events[:max_events]:
        sig = ev.get("metrics", {}).get("significance", 0)
        ms = ev.get("metrics", {}).get("market_sensitivity", 0)
        geo = ev.get("geo", {}).get("country", "?")
        date = (ev.get("event_date") or "")[:10]
        title = ev.get("title") or ev.get("summary", "")[:80]
        fatal = ev.get("fatalities") or 0
        lines.append(
            f"[{date} | {geo} | sig={sig:.2f} | mkt_sens={ms:.2f}{' | ⚠ FATALITIES: '+str(fatal) if fatal else ''}]\n"
            f"  {title}"
        )
    return "\n".join(lines)
