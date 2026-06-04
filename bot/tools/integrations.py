"""MCP tools wrapping external API integrations."""
from __future__ import annotations

import asyncio
import os

import httpx

import db
from lib.integrations import (gdelt, osm, wikipedia, sec, arxiv, github, weather,
                                acled, openfec, firms, propublica_nonprofits, youtube,
                                reliefweb, sanctions, opensky, wikidata_sparql)


def _ensure_db() -> None:
    db.init()


async def _with_client(coro_factory):
    async with httpx.AsyncClient() as client:
        return await coro_factory(client)


def register(mcp):

    # ---------- GDELT ----------
    @mcp.tool()
    async def gdelt_search(query: str, days_back: int = 7,
                            max_records: int = 25,
                            domain: str = "", country: str = "") -> dict:
        """
        Search GDELT 2.0 for recent news articles. No API key needed.

        Args:
            query: GDELT expression. Supports phrases, AND/OR, theme:..., sourcecountry:..
            days_back: 1..365.
            max_records: 1..250.
            domain: restrict to one domain ("reuters.com").
            country: 2-letter ISO source country ("UA", "RU", "US").

        Use for: actor-mention monitoring, narrative heat, freshness of evidence,
        OSINT context for geopolitical markets.
        """
        return await _with_client(lambda c: gdelt.search_articles(
            c, query, days_back=days_back, max_records=max_records,
            domain=domain or None, country=country or None,
        ))

    @mcp.tool()
    async def gdelt_volume_timeline(query: str, days_back: int = 14) -> dict:
        """
        Article-volume time series from GDELT for a query — used to spot
        narrative ignition or fade. Daily counts of matching articles.
        """
        return await _with_client(lambda c: gdelt.article_volume_timeline(
            c, query, days_back=days_back,
        ))

    # ---------- OSM ----------
    @mcp.tool()
    async def geocode_place(place: str, country: str = "", limit: int = 5) -> dict:
        """
        Geocode a place name via OpenStreetMap Nominatim. Returns lat/lon + bbox.
        Use for OSINT layer: turn "Rodynske" into coordinates before querying
        ACLED/FIRMS/Sentinel/etc.

        Args:
            place: free text ("Rodynske, Ukraine").
            country: optional 2-letter ISO filter.
            limit: 1..10 candidates.
        """
        return await _with_client(lambda c: osm.geocode_place(
            c, place, country=country or None, limit=limit,
        ))

    # ---------- Wikipedia / Wikidata ----------
    @mcp.tool()
    async def wiki_summary(title: str, lang: str = "en") -> dict:
        """
        Get Wikipedia page summary — extract, type, URL, Wikidata Q-ID.
        First call for any new actor / party / event / candidate to
        confirm identity before deeper research.
        """
        return await _with_client(lambda c: wikipedia.wikipedia_summary(
            c, title, lang=lang,
        ))

    @mcp.tool()
    async def wiki_entity_search(query: str, limit: int = 7) -> dict:
        """Find Wikidata entity candidates for a free-text query."""
        return await _with_client(lambda c: wikipedia.wikidata_search(
            c, query, limit=limit,
        ))

    @mcp.tool()
    async def wiki_entity_details(qid: str) -> dict:
        """Full claims for a Wikidata entity Q-ID (label, description, P-claims,
        Wikipedia URL)."""
        return await _with_client(lambda c: wikipedia.wikidata_entity(c, qid))

    # ---------- SEC EDGAR ----------
    @mcp.tool()
    async def sec_filings(ticker_or_cik: str, types: list[str] = None,
                           limit: int = 15) -> dict:
        """
        Recent SEC filings for a public company. Use for tech_business markets
        (Snowflake guidance, OpenAI not-IPO calibration, etc.). Default form
        types: 8-K, 10-Q, 10-K. Pass ['ALL'] for everything.
        """
        return await _with_client(lambda c: sec.company_filings(
            c, ticker_or_cik, types=types or None, limit=limit,
        ))

    @mcp.tool()
    async def sec_company_facts(ticker_or_cik: str, concept: str = "") -> dict:
        """
        Company XBRL facts. Without concept: list available metrics.
        With concept (e.g. 'Revenues', 'NetIncomeLoss'): return recent 6-quarter
        series. Use for earnings guidance / revenue forecast markets.
        """
        return await _with_client(lambda c: sec.company_facts(
            c, ticker_or_cik, concept=concept or None,
        ))

    # ---------- arXiv ----------
    @mcp.tool()
    async def arxiv_search(query: str, max_results: int = 10,
                            sort_by: str = "submittedDate") -> dict:
        """
        Search arXiv papers. Use for AI release markets (paper drops often
        precede model announcements).

        Examples: 'all:"Gemini 3"', 'cat:cs.AI AND ti:reasoning'.
        """
        return await _with_client(lambda c: arxiv.search_papers(
            c, query, max_results=max_results, sort_by=sort_by,
        ))

    # ---------- GitHub ----------
    @mcp.tool()
    async def github_repo(owner_repo: str) -> dict:
        """Repo overview: stars, forks, last push, language."""
        return await _with_client(lambda c: github.repo_overview(c, owner_repo))

    @mcp.tool()
    async def github_releases(owner_repo: str, limit: int = 5) -> dict:
        """Recent releases for a repo (tag, name, date, prerelease flag)."""
        return await _with_client(lambda c: github.recent_releases(
            c, owner_repo, limit=limit,
        ))

    @mcp.tool()
    async def github_commits(owner_repo: str, days_back: int = 7,
                              limit: int = 20) -> dict:
        """Recent commits on default branch."""
        return await _with_client(lambda c: github.recent_commits(
            c, owner_repo, days_back=days_back, limit=limit,
        ))

    # ---------- Open-Meteo ----------
    @mcp.tool()
    async def weather_forecast(lat: float, lon: float, days: int = 7) -> dict:
        """7-16 day weather forecast for a point (temp, precip, wind)."""
        return await _with_client(lambda c: weather.forecast(
            c, lat, lon, days=days,
        ))

    # ---------- ACLED ----------
    @mcp.tool()
    async def acled_events_near(lat: float, lon: float, radius_km: float = 30,
                                 days_back: int = 14, limit: int = 50) -> dict:
        """
        ACLED conflict events within radius_km of (lat, lon) in the last N days.
        Use after geocode_place. Returns event_type, sub_event_type, actors,
        fatalities, source per event.

        Requires ACLED_EMAIL + ACLED_PASSWORD in env. If account isn't yet
        API-approved, returns a structured 'account not API-enabled' message
        with the hint to enable in the developer portal.
        """
        return await _with_client(lambda c: acled.events_near(
            c, lat, lon, radius_km=radius_km, days_back=days_back, limit=limit,
        ))

    @mcp.tool()
    async def acled_events_by_country(country: str, days_back: int = 14,
                                       limit: int = 100,
                                       event_type: str = "") -> dict:
        """ACLED events in a country (e.g. 'Ukraine', 'Israel') last N days."""
        return await _with_client(lambda c: acled.events_by_country(
            c, country, days_back=days_back, limit=limit,
            event_type=event_type or None,
        ))

    @mcp.tool()
    async def acled_actor_search(actor: str, days_back: int = 30,
                                  limit: int = 50) -> dict:
        """ACLED events involving a named actor (partial match)."""
        return await _with_client(lambda c: acled.actor_search(
            c, actor, days_back=days_back, limit=limit,
        ))

    # ---------- OpenFEC ----------
    @mcp.tool()
    async def fec_candidate_search(name: str, state: str = "",
                                    cycle: int = 2026,
                                    office: str = "") -> dict:
        """
        Search US federal candidates by name. Office: H (House), S (Senate),
        P (President). FEC does NOT cover state-level governor races.
        """
        return await _with_client(lambda c: openfec.candidate_search(
            c, name, state=state or None, cycle=cycle,
            office=office or None,
        ))

    @mcp.tool()
    async def fec_candidate_totals(candidate_id: str, cycle: int = 2026) -> dict:
        """Receipts, disbursements, cash-on-hand for a candidate in a cycle."""
        return await _with_client(lambda c: openfec.candidate_totals(
            c, candidate_id, cycle=cycle,
        ))

    @mcp.tool()
    async def fec_late_spending(candidate_id: str, cycle: int = 2026,
                                 per_page: int = 20) -> dict:
        """Independent expenditures targeting a candidate (24/48-hour reports).
        Surfaces late surges in outside support/opposition."""
        return await _with_client(lambda c: openfec.late_spending(
            c, candidate_id, cycle=cycle, per_page=per_page,
        ))

    # ---------- NASA FIRMS ----------
    @mcp.tool()
    async def firms_thermal_anomalies(lat: float, lon: float,
                                       radius_km: float = 30,
                                       days_back: int = 5,
                                       source: str = "VIIRS_SNPP_NRT") -> dict:
        """
        Active-fire / thermal-anomaly detections (MODIS/VIIRS) within a
        radius. NRT area endpoint caps at 5 days.

        Use as OSINT proxy for strike activity near a frontline location.
        Pair with acled_events_near for double confirmation.
        """
        return await _with_client(lambda c: firms.thermal_anomalies(
            c, lat, lon, radius_km=radius_km, days_back=days_back, source=source,
        ))

    # ---------- ProPublica Nonprofits ----------
    @mcp.tool()
    async def propublica_search_orgs(query: str, state: str = "",
                                      ntee_category: int = 0,
                                      c_code: int = 0) -> dict:
        """Search nonprofit organizations (501(c)). Useful for actor maps
        and dark-money flow tracing."""
        return await _with_client(lambda c: propublica_nonprofits.search_orgs(
            c, query, state=state or None,
            ntee_category=ntee_category or None,
            c_code=c_code or None,
        ))

    @mcp.tool()
    async def propublica_organization(ein: str) -> dict:
        """Detailed view of one nonprofit by EIN, including recent 990 filings."""
        return await _with_client(lambda c: propublica_nonprofits.organization(c, ein))

    # ---------- YouTube ----------
    @mcp.tool()
    async def youtube_search(query: str, max_results: int = 10,
                              order: str = "relevance",
                              published_after: str = "",
                              channel_id: str = "",
                              region: str = "") -> dict:
        """
        Search YouTube. **Costs 100 quota units per call** (daily quota 10000,
        so ~100 searches/day). Use for debates, interviews, candidate
        statements, geopolitical briefings.
        """
        return await _with_client(lambda c: youtube.search(
            c, query, max_results=max_results, order=order,
            published_after=published_after or None,
            channel_id=channel_id or None,
            region=region or None,
        ))

    @mcp.tool()
    async def youtube_channel_info(channel_id: str) -> dict:
        """Channel statistics (subs, views, video count). 1 quota unit."""
        return await _with_client(lambda c: youtube.channel_info(c, channel_id))

    # ---------- ReliefWeb ----------
    @mcp.tool()
    async def reliefweb_search(query: str = "", country: str = "",
                                disaster_type: str = "",
                                days_back: int = 30,
                                limit: int = 10) -> dict:
        """Search ReliefWeb humanitarian reports. Country: ISO3 or English name."""
        return await _with_client(lambda c: reliefweb.search_reports(
            c, query=query, country=country or None,
            disaster_type=disaster_type or None,
            days_back=days_back, limit=limit,
        ))

    # ---------- Sanctions ----------
    @mcp.tool()
    async def ofac_sdn_search(name: str, max_results: int = 10) -> dict:
        """Search OFAC SDN by partial name (cached 1h). Includes aliases."""
        return await _with_client(lambda c: sanctions.ofac_sdn_search(
            c, name, max_results=max_results,
        ))

    @mcp.tool()
    async def eu_sanctions_search(name: str, max_results: int = 10) -> dict:
        """Search EU consolidated sanctions list by partial name (cached 1h)."""
        return await _with_client(lambda c: sanctions.eu_sanctions_search(
            c, name, max_results=max_results,
        ))

    @mcp.tool()
    async def uk_sanctions_search(name: str, max_results: int = 10) -> dict:
        """Search UK OFSI consolidated sanctions list by partial name (cached 1h)."""
        return await _with_client(lambda c: sanctions.uk_sanctions_search(
            c, name, max_results=max_results,
        ))

    # ---------- OpenSky ----------
    @mcp.tool()
    async def opensky_states_in_bbox(south: float, north: float,
                                      west: float, east: float) -> dict:
        """Snapshot of all aircraft positions inside a bbox. Anonymous reads
        cost ~1-4 credits/day quota."""
        return await _with_client(lambda c: opensky.states_in_bbox(
            c, south=south, north=north, west=west, east=east,
        ))

    @mcp.tool()
    async def opensky_flights_in_window(begin_unix: int, end_unix: int,
                                         airport_icao: str = "") -> dict:
        """Departures/arrivals over a time window (≤7 days). Without airport
        ICAO returns all flights (heavy)."""
        return await _with_client(lambda c: opensky.flights_in_window(
            c, begin_unix=begin_unix, end_unix=end_unix,
            airport_icao=airport_icao or None,
        ))

    # ---------- Wikidata SPARQL (politicians) ----------
    @mcp.tool()
    async def wikidata_current_office_holders(position_qid: str,
                                                limit: int = 30) -> dict:
        """Current holders of a Wikidata political office (P39).

        Examples of position QIDs:
          Q11696 — President of the US
          Q5145  — Member of US House of Representatives
          Q14211 — Member of Knesset
          Q41587 — President of Russia
        """
        return await _with_client(lambda c: wikidata_sparql.current_office_holders(
            c, position_qid=position_qid, limit=limit,
        ))

    @mcp.tool()
    async def wikidata_politicians_in_country(country_qid: str,
                                                limit: int = 30) -> dict:
        """List politicians by country (P27 citizenship, P106 occupation politician).

        Country QID examples:
          Q30 (USA), Q31 (Belgium), Q142 (France), Q183 (Germany),
          Q218 (Romania), Q399 (Armenia), Q801 (Israel), Q212 (Ukraine).
        """
        return await _with_client(lambda c: wikidata_sparql.politicians_in_country(
            c, country_qid, limit=limit,
        ))

    # ---------- Connection status ----------
    @mcp.tool()
    def integrations_status() -> dict:
        """Report which integrations are configured (env vars present)."""
        return {
            "keyless_ready": [
                "GDELT", "OpenStreetMap Nominatim", "Wikipedia/Wikidata",
                "SEC EDGAR", "arXiv", "GitHub (anonymous, 60req/h)",
                "Open-Meteo", "OFAC SDN", "EU Sanctions", "UK OFSI",
                "OpenSky Network", "Wikidata SPARQL", "ProPublica Nonprofits",
            ],
            "keyed_active": [
                "OpenFEC", "NASA FIRMS", "YouTube Data v3",
            ],
            "keyed_pending_approval": [
                "ACLED (token OK, API access pending — request via access@acleddata.com)",
                "ReliefWeb v2 (needs approved appname — request via api-team@reliefweb.int)",
            ],
            "env_keys_detected": {
                "SIGNAL_CONTACT_EMAIL": bool(os.getenv("SIGNAL_CONTACT_EMAIL")),
                "GITHUB_TOKEN": bool(os.getenv("GITHUB_TOKEN")),
                "NASA_FIRMS_MAP_KEY": bool(os.getenv("NASA_FIRMS_MAP_KEY")),
                "ACLED_API_KEY": bool(os.getenv("ACLED_API_KEY")),
                "ACLED_EMAIL": bool(os.getenv("ACLED_EMAIL")),
                "OPENFEC_API_KEY": bool(os.getenv("OPENFEC_API_KEY")),
                "PROPUBLICA_API_KEY": bool(os.getenv("PROPUBLICA_API_KEY")),
                "REDDIT_CLIENT_ID": bool(os.getenv("REDDIT_CLIENT_ID")),
                "REDDIT_CLIENT_SECRET": bool(os.getenv("REDDIT_CLIENT_SECRET")),
                "YOUTUBE_API_KEY": bool(os.getenv("YOUTUBE_API_KEY")),
                "OPENSANCTIONS_API_KEY": bool(os.getenv("OPENSANCTIONS_API_KEY")),
                "SENTINEL_HUB_CLIENT_ID": bool(os.getenv("SENTINEL_HUB_CLIENT_ID")),
                "SENTINEL_HUB_CLIENT_SECRET": bool(os.getenv("SENTINEL_HUB_CLIENT_SECRET")),
            },
            "not_yet_implemented_but_keyless": [
                "ReliefWeb (needs appname registration but free)",
                "OFAC SDN list (direct file download)",
                "EveryPolitician / Wikidata politicians (Wikidata adapter)",
            ],
            "not_yet_implemented_needs_key": [
                "ACLED (free signup -> ACLED_API_KEY + ACLED_EMAIL)",
                "NASA FIRMS (free signup -> NASA_FIRMS_MAP_KEY)",
                "OpenFEC (free signup -> OPENFEC_API_KEY)",
                "ProPublica (email request -> PROPUBLICA_API_KEY)",
                "Reddit (OAuth app -> REDDIT_CLIENT_ID/SECRET)",
                "YouTube Data (Google Cloud project -> YOUTUBE_API_KEY)",
                "OpenSanctions (signup -> OPENSANCTIONS_API_KEY)",
                "Sentinel Hub (OAuth -> SENTINEL_HUB_CLIENT_ID/SECRET)",
            ],
        }
