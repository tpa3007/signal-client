"""Sanctions lists - keyless direct downloads.

  - OFAC SDN (US Treasury) - XML
  - EU consolidated - CSV
  - UK OFSI consolidated - CSV

All lists are cached locally per session and refreshed on demand.
"""
from __future__ import annotations

import csv
import io
import re
import time
from xml.etree import ElementTree as ET

from lib.integrations import _safe_get, USER_AGENT

OFAC_SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/sdn.xml"
# EU & UK URLs change occasionally - keep them external-configurable later
EU_CSV_URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content"
UK_CSV_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"


# In-memory caches with TTL (1 hour)
_CACHE: dict = {"ofac": None, "eu": None, "uk": None}
_CACHE_TS: dict = {"ofac": 0.0, "eu": 0.0, "uk": 0.0}
_TTL = 3600


async def _fetch_text(client, url: str) -> str | None:
    # Sanctions lists are 5-30MB; OFAC SDN.XML alone is ~10MB. Need a long timeout
    # AND follow_redirects (some endpoints 302 to a CDN).
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT},
                              follow_redirects=True, timeout=60)
        if r.status_code != 200:
            return None
        return r.text
    except Exception:
        return None


# ---------- OFAC SDN -------------------------------------------------------

async def _load_ofac(client) -> list[dict] | None:
    now = time.time()
    if _CACHE["ofac"] and now - _CACHE_TS["ofac"] < _TTL:
        return _CACHE["ofac"]
    txt = await _fetch_text(client, OFAC_SDN_URL)
    if not txt:
        return None
    try:
        # SDN XML namespace
        ns = {"s": "http://tempuri.org/sdnList.xsd"}
        root = ET.fromstring(txt)
    except Exception:
        return None
    entries = []
    for entry in root.findall("s:sdnEntry", ns):
        # Last/first name OR org name
        last = (entry.findtext("s:lastName", default="", namespaces=ns) or "").strip()
        first = (entry.findtext("s:firstName", default="", namespaces=ns) or "").strip()
        sdn_type = (entry.findtext("s:sdnType", default="", namespaces=ns) or "").strip()
        programs = []
        for p in entry.findall("s:programList/s:program", ns):
            if p.text:
                programs.append(p.text.strip())
        # akaList for aliases
        akas = []
        for a in entry.findall("s:akaList/s:aka", ns):
            full = " ".join(filter(None, [
                a.findtext("s:firstName", default="", namespaces=ns),
                a.findtext("s:lastName", default="", namespaces=ns),
            ])).strip()
            if full:
                akas.append(full)
        uid = entry.findtext("s:uid", default="", namespaces=ns)
        entries.append({
            "uid": uid,
            "name": f"{first} {last}".strip() if last or first else "",
            "type": sdn_type,
            "programs": programs,
            "aliases": akas,
        })
    _CACHE["ofac"] = entries
    _CACHE_TS["ofac"] = now
    return entries


async def ofac_sdn_search(client, name: str, *, max_results: int = 10) -> dict:
    """Search OFAC SDN by partial name (case-insensitive). Includes aliases."""
    if not name.strip():
        return {"error": "name is required"}
    entries = await _load_ofac(client)
    if entries is None:
        return {"error": "OFAC SDN download failed"}
    q = name.lower()
    matches = []
    for e in entries:
        haystack = " ".join([e["name"]] + e["aliases"]).lower()
        if q in haystack:
            matches.append(e)
            if len(matches) >= max_results:
                break
    return {"query": name, "list_size": len(entries), "matches_count": len(matches),
            "matches": matches}


# ---------- Generic sanctioned-list search ---------------------------------

async def _load_csv(client, url: str, cache_key: str) -> list[dict] | None:
    now = time.time()
    if _CACHE[cache_key] and now - _CACHE_TS[cache_key] < _TTL:
        return _CACHE[cache_key]
    txt = await _fetch_text(client, url)
    if not txt:
        return None
    reader = csv.DictReader(io.StringIO(txt))
    rows = list(reader)
    _CACHE[cache_key] = rows
    _CACHE_TS[cache_key] = now
    return rows


async def eu_sanctions_search(client, name: str, *, max_results: int = 10) -> dict:
    """Search EU consolidated sanctions list by partial name."""
    if not name.strip():
        return {"error": "name is required"}
    rows = await _load_csv(client, EU_CSV_URL, "eu")
    if rows is None:
        return {"error": "EU sanctions list download failed"}
    q = name.lower()
    matches = []
    for r in rows:
        # EU CSV column names vary by version; check the most informative ones
        hay = " ".join(str(v) for v in r.values() if v).lower()
        if q in hay:
            # Trim to a digestible subset of fields
            matches.append({k: (v[:80] if isinstance(v, str) else v)
                            for k, v in r.items() if v})
            if len(matches) >= max_results:
                break
    return {"query": name, "list_size": len(rows), "matches_count": len(matches),
            "matches": matches}


async def uk_sanctions_search(client, name: str, *, max_results: int = 10) -> dict:
    """Search UK OFSI consolidated list by partial name."""
    if not name.strip():
        return {"error": "name is required"}
    rows = await _load_csv(client, UK_CSV_URL, "uk")
    if rows is None:
        return {"error": "UK sanctions list download failed"}
    q = name.lower()
    matches = []
    for r in rows:
        hay = " ".join(str(v) for v in r.values() if v).lower()
        if q in hay:
            matches.append({k: (v[:80] if isinstance(v, str) else v)
                            for k, v in r.items() if v})
            if len(matches) >= max_results:
                break
    return {"query": name, "list_size": len(rows), "matches_count": len(matches),
            "matches": matches}
