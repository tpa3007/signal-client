"""Integration clients — parsing tests with mocked HTTP responses."""
from __future__ import annotations

import asyncio
import json
from xml.sax.saxutils import escape

import pytest


class _MockResponse:
    def __init__(self, *, json_data=None, text=""):
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _MockClient:
    def __init__(self, mapping):
        # mapping: url-substring -> _MockResponse
        self.mapping = mapping
        self.calls = []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        for key, resp in self.mapping.items():
            if key in url:
                return resp
        raise AssertionError(f"no mock for {url}")


# ---------- GDELT ----------

def test_gdelt_search_parses_articles():
    from lib.integrations import gdelt
    payload = {"articles": [
        {"url": "https://reuters.com/x", "title": "Headline", "domain": "reuters.com",
         "language": "English", "seendate": "20260519", "tone": -1.5,
         "socialimage": "img.png"},
    ]}
    client = _MockClient({"gdeltproject.org": _MockResponse(json_data=payload)})
    out = asyncio.run(gdelt.search_articles(client, "test query"))
    assert out["count"] == 1
    assert out["articles"][0]["domain"] == "reuters.com"
    assert out["articles"][0]["tone"] == -1.5


def test_gdelt_search_requires_query():
    from lib.integrations import gdelt
    client = _MockClient({})
    out = asyncio.run(gdelt.search_articles(client, "  "))
    assert "error" in out


# ---------- OSM ----------

def test_geocode_parses_response():
    from lib.integrations import osm
    payload = [{
        "display_name": "Rodynske, Donetsk Oblast, Ukraine",
        "lat": "48.354", "lon": "37.203",
        "boundingbox": ["48.34", "48.37", "37.19", "37.23"],
        "type": "city", "importance": 0.5,
        "address": {"country": "Ukraine"},
        "osm_id": 12345, "osm_type": "node",
    }]
    client = _MockClient({"nominatim": _MockResponse(json_data=payload)})
    out = asyncio.run(osm.geocode_place(client, "Rodynske, Ukraine"))
    assert out["count"] == 1
    assert out["results"][0]["lat"] == 48.354
    assert out["results"][0]["bbox_south_north_west_east"] == [48.34, 48.37, 37.19, 37.23]


# ---------- Wikipedia ----------

def test_wiki_summary_parses_fields():
    from lib.integrations import wikipedia
    payload = {
        "title": "Knesset",
        "description": "Parliament of Israel",
        "extract": "The Knesset is the legislature.",
        "type": "standard",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Knesset"}},
        "wikibase_item": "Q190771",
    }
    client = _MockClient({"wikipedia.org": _MockResponse(json_data=payload)})
    out = asyncio.run(wikipedia.wikipedia_summary(client, "Knesset"))
    assert out["title"] == "Knesset"
    assert out["wikibase_item"] == "Q190771"
    assert "legislature" in out["extract"]


def test_wikidata_search_parses_candidates():
    from lib.integrations import wikipedia
    payload = {"search": [
        {"id": "Q190771", "label": "Knesset",
         "description": "Parliament of Israel",
         "url": "//www.wikidata.org/wiki/Q190771",
         "concepturi": "http://www.wikidata.org/entity/Q190771"},
    ]}
    client = _MockClient({"wikidata.org/w/api.php": _MockResponse(json_data=payload)})
    out = asyncio.run(wikipedia.wikidata_search(client, "Knesset"))
    assert out["candidates"][0]["id"] == "Q190771"


# ---------- SEC EDGAR ----------

def test_sec_resolve_cik_normalises_digits():
    from lib.integrations import sec
    out = sec._normalise_cik("0000789019")
    assert out == "0000789019"
    out = sec._normalise_cik("789019")
    assert out == "0000789019"
    out = sec._normalise_cik("SNOW")
    assert out is None


def test_sec_filings_filters_by_form():
    from lib.integrations import sec
    sec._TICKER_CACHE = {"SNOW": "0001640147"}
    payload = {
        "name": "Snowflake Inc.",
        "tickers": ["SNOW"],
        "filings": {"recent": {
            "form": ["10-Q", "8-K", "10-K", "4"],
            "filingDate": ["2026-03", "2026-02", "2026-01", "2025-12"],
            "accessionNumber": ["a-1", "a-2", "a-3", "a-4"],
            "primaryDocument": ["d1.htm", "d2.htm", "d3.htm", "d4.htm"],
            "primaryDocDescription": ["Q1", "8K filing", "Annual", "Insider"],
        }},
    }
    client = _MockClient({"submissions/CIK": _MockResponse(json_data=payload)})
    out = asyncio.run(sec.company_filings(client, "SNOW", types=["10-Q", "8-K"]))
    assert out["name"] == "Snowflake Inc."
    assert len(out["filings"]) == 2  # 10-Q and 8-K only
    forms = {f["form"] for f in out["filings"]}
    assert forms == {"10-Q", "8-K"}


# ---------- arXiv ----------

def test_arxiv_search_parses_atom():
    from lib.integrations import arxiv
    atom = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>A new model</title>
    <summary>We propose a new reasoning model</summary>
    <published>2026-05-01T00:00:00Z</published>
    <updated>2026-05-02T00:00:00Z</updated>
    <link rel="alternate" href="https://arxiv.org/abs/2605.00001"/>
    <author><name>Jane Doe</name></author>
  </entry>
</feed>"""
    client = _MockClient({"export.arxiv.org": _MockResponse(text=atom)})
    out = asyncio.run(arxiv.search_papers(client, "ti:reasoning"))
    assert out["count"] == 1
    assert out["papers"][0]["title"] == "A new model"
    assert out["papers"][0]["authors"] == ["Jane Doe"]


# ---------- GitHub ----------

def test_github_repo_parses_response():
    from lib.integrations import github
    payload = {
        "full_name": "google/gemma",
        "stargazers_count": 100,
        "forks_count": 10,
        "subscribers_count": 5,
        "open_issues_count": 3,
        "default_branch": "main",
        "pushed_at": "2026-05-19T00:00:00Z",
        "updated_at": "2026-05-19T00:00:00Z",
        "language": "Python",
        "topics": ["llm"],
    }
    client = _MockClient({"api.github.com/repos": _MockResponse(json_data=payload)})
    out = asyncio.run(github.repo_overview(client, "google/gemma"))
    assert out["stars"] == 100
    assert out["language"] == "Python"


def test_github_owner_repo_validation():
    from lib.integrations import github
    out = asyncio.run(github.repo_overview(_MockClient({}), "no-slash"))
    assert "error" in out


# ---------- Weather ----------

def test_weather_forecast_parses():
    from lib.integrations import weather
    payload = {"daily": {
        "time": ["2026-05-19", "2026-05-20"],
        "temperature_2m_max": [25.1, 26.3],
        "temperature_2m_min": [12.4, 13.8],
        "precipitation_sum": [0.0, 2.5],
        "windspeed_10m_max": [10.0, 12.5],
    }}
    client = _MockClient({"open-meteo.com": _MockResponse(json_data=payload)})
    out = asyncio.run(weather.forecast(client, 48.35, 37.20, days=2))
    assert out["count"] == 2
    assert out["days"][0]["temp_max"] == 25.1
    assert out["days"][1]["precip_mm"] == 2.5


# ---------- HTTP error handling ----------

def test_safe_get_swallows_exception():
    from lib.integrations import _safe_get

    class FailingClient:
        async def get(self, *a, **kw):
            raise RuntimeError("network down")

    out = asyncio.run(_safe_get(FailingClient(), "https://example.com"))
    assert "_error" in out
    assert "RuntimeError" in out["_error"]


# ---------- Status tool ----------

def test_integrations_status_lists_keyless_ready():
    import mcp_server
    fn = getattr(mcp_server.mcp._tool_manager._tools["integrations_status"], "fn")
    out = fn()
    assert "GDELT" in out["keyless_ready"]
    assert "SEC EDGAR" in out["keyless_ready"]
    assert "env_keys_detected" in out
