"""Tests for second-batch integrations: ReliefWeb, OFAC, OpenSky, Wikidata SPARQL."""
from __future__ import annotations

import asyncio


class _MockResponse:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json = json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _MockClient:
    def __init__(self, mapping):
        self.mapping = mapping

    async def get(self, url, params=None, headers=None, timeout=None, follow_redirects=False):
        for key, resp in self.mapping.items():
            if key in url:
                return resp
        raise AssertionError(f"no mock for {url}")

    async def post(self, url, params=None, json=None, data=None, headers=None, timeout=None):
        for key, resp in self.mapping.items():
            if key in url:
                return resp
        raise AssertionError(f"no mock for {url}")


# ---------- ReliefWeb ----------

def test_reliefweb_search_parses():
    from lib.integrations import reliefweb
    payload = {
        "totalCount": 5,
        "data": [{
            "id": "100",
            "fields": {
                "title": "Crisis report",
                "url_alias": "report/ukraine/example-100",
                "date": {"created": "2026-05-19T10:00:00Z"},
                "country": [{"name": "Ukraine"}],
                "source": [{"name": "OCHA"}],
                "disaster_type": [{"name": "Conflict"}],
            }
        }]
    }
    client = _MockClient({"reliefweb.int": _MockResponse(json_data=payload)})
    out = asyncio.run(reliefweb.search_reports(client, query="Donetsk", days_back=14))
    assert out["count"] == 1
    assert out["reports"][0]["country"] == ["Ukraine"]
    assert "OCHA" in (out["reports"][0]["source"] or [])
    assert out["reports"][0]["url"] == "https://reliefweb.int/report/ukraine/example-100"


def test_reliefweb_appname_pending_returns_clear_error():
    from lib.integrations import reliefweb
    client = _MockClient({"reliefweb.int": _MockResponse(text="forbidden", status_code=403)})
    out = asyncio.run(reliefweb.search_reports(client, query="Donetsk", days_back=14))
    assert out["error"] == "ReliefWeb appname not approved"
    assert "api-team@reliefweb.int" in out["hint"]


# ---------- OFAC SDN ----------

def test_ofac_sdn_parser():
    from lib.integrations import sanctions
    xml = """<?xml version="1.0"?>
<sdnList xmlns="http://tempuri.org/sdnList.xsd">
  <sdnEntry>
    <uid>123</uid>
    <firstName>Ali</firstName>
    <lastName>Khamenei</lastName>
    <sdnType>Individual</sdnType>
    <programList>
      <program>IRAN</program>
      <program>SDGT</program>
    </programList>
    <akaList>
      <aka>
        <firstName>Sayyid</firstName>
        <lastName>Ali Khamenei</lastName>
      </aka>
    </akaList>
  </sdnEntry>
</sdnList>"""
    client = _MockClient({"treas.gov": _MockResponse(text=xml)})
    sanctions._CACHE["ofac"] = None
    sanctions._CACHE_TS["ofac"] = 0
    out = asyncio.run(sanctions.ofac_sdn_search(client, "Khamenei"))
    assert out["list_size"] == 1
    assert out["matches_count"] == 1
    assert out["matches"][0]["uid"] == "123"
    assert "IRAN" in out["matches"][0]["programs"]


# ---------- OpenSky ----------

def test_opensky_states_parser():
    from lib.integrations import opensky
    payload = {
        "time": 1700000000,
        "states": [
            ["icao1", "FOO123 ", "UK", 1, 1, -0.5, 51.5, 11000, False, 250.0,
             90.0, -2.0, None, 11100, "1234", False, 0],
        ],
    }
    client = _MockClient({"opensky-network.org": _MockResponse(json_data=payload)})
    out = asyncio.run(opensky.states_in_bbox(
        client, south=50, north=52, west=-1, east=1))
    assert out["count"] == 1
    assert out["states"][0]["callsign"] == "FOO123"
    assert out["states"][0]["origin_country"] == "UK"
    assert out["states"][0]["baro_altitude_m"] == 11000


def test_opensky_flights_window_limit():
    from lib.integrations import opensky
    out = asyncio.run(opensky.flights_in_window(
        _MockClient({}), begin_unix=0, end_unix=10 * 86400))
    assert "error" in out
    assert "7 days" in out["error"]


# ---------- Wikidata SPARQL ----------

def test_sparql_office_holders_parser():
    from lib.integrations import wikidata_sparql
    payload = {
        "results": {
            "bindings": [
                {
                    "person": {"value": "http://www.wikidata.org/entity/Q12345"},
                    "personLabel": {"value": "Test Person"},
                    "start": {"value": "2024-01-01T00:00:00Z"},
                    "countryLabel": {"value": "Wonderland"},
                },
            ]
        }
    }
    client = _MockClient({"query.wikidata.org": _MockResponse(json_data=payload)})
    out = asyncio.run(wikidata_sparql.current_office_holders(
        client, position_qid="Q11696"))
    assert out["count"] == 1
    assert out["holders"][0]["qid"] == "Q12345"
    assert out["holders"][0]["name"] == "Test Person"


def test_sparql_politicians_in_country_parser():
    from lib.integrations import wikidata_sparql
    payload = {
        "results": {
            "bindings": [
                {
                    "p": {"value": "http://www.wikidata.org/entity/Q9999"},
                    "pLabel": {"value": "Politician X"},
                    "occLabel": {"value": "politician"},
                    "partyLabel": {"value": "Party Y"},
                },
            ]
        }
    }
    client = _MockClient({"query.wikidata.org": _MockResponse(json_data=payload)})
    out = asyncio.run(wikidata_sparql.politicians_in_country(client, "Q31"))
    assert out["count"] == 1
    assert out["politicians"][0]["party"] == "Party Y"
