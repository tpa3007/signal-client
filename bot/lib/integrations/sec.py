"""SEC EDGAR clients — filings + company facts.

Public, keyless, but SEC requires a contactable User-Agent header per
https://www.sec.gov/os/accessing-edgar-data — we send it via lib.integrations.
Rate limit: 10 req/s.
"""
from __future__ import annotations

import asyncio

from lib.integrations import _safe_get

EDGAR_DATA = "https://data.sec.gov"
EDGAR_WWW = "https://www.sec.gov"


# Cached ticker -> CIK mapping (loaded lazily)
_TICKER_CACHE: dict[str, str] | None = None


async def _load_ticker_map(client) -> dict[str, str]:
    """Lazy-load the SEC ticker -> CIK map (~10k entries, one HTTP call)."""
    global _TICKER_CACHE
    if _TICKER_CACHE is not None:
        return _TICKER_CACHE
    r = await _safe_get(client, f"{EDGAR_WWW}/files/company_tickers.json")
    if isinstance(r, dict) and "_error" in r:
        return {}
    try:
        d = r.json()
    except Exception:
        return {}
    out = {}
    # Format: {"0":{"cik_str":...,"ticker":"AAPL","title":"..."}, "1": {...}}
    for v in d.values():
        if isinstance(v, dict) and v.get("ticker"):
            out[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
    _TICKER_CACHE = out
    return out


def _normalise_cik(ticker_or_cik: str) -> str | None:
    """If input already looks like CIK, normalise to 10-digit. Else None
    (caller should use _load_ticker_map)."""
    s = ticker_or_cik.strip()
    if s.isdigit():
        return s.zfill(10)
    return None


async def resolve_cik(client, ticker_or_cik: str) -> str | None:
    cik = _normalise_cik(ticker_or_cik)
    if cik:
        return cik
    tmap = await _load_ticker_map(client)
    return tmap.get(ticker_or_cik.upper())


async def company_filings(client, ticker_or_cik: str, *,
                           types: list[str] | None = None,
                           limit: int = 15) -> dict:
    """Recent filings for a company. Defaults to 8-K + 10-Q + 10-K."""
    cik = await resolve_cik(client, ticker_or_cik)
    if not cik:
        return {"error": f"could not resolve ticker/CIK: {ticker_or_cik}"}
    types = [t.upper() for t in (types or ["8-K", "10-Q", "10-K"])]
    r = await _safe_get(client, f"{EDGAR_DATA}/submissions/CIK{cik}.json")
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    recent = (d.get("filings") or {}).get("recent") or {}
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    out = []
    for i, form in enumerate(forms):
        if form.upper() not in types and "ALL" not in types:
            continue
        acc_clean = accs[i].replace("-", "") if i < len(accs) else ""
        url = (f"{EDGAR_WWW}/Archives/edgar/data/{int(cik)}/{acc_clean}/{primary_docs[i]}"
               if i < len(primary_docs) and primary_docs[i] else None)
        out.append({
            "form": form,
            "filing_date": dates[i] if i < len(dates) else None,
            "accession": accs[i] if i < len(accs) else None,
            "description": descriptions[i] if i < len(descriptions) else None,
            "url": url,
        })
        if len(out) >= limit:
            break
    return {
        "cik": cik,
        "name": d.get("name"),
        "tickers": d.get("tickers"),
        "filings": out,
        "count": len(out),
    }


async def company_facts(client, ticker_or_cik: str, *,
                         concept: str | None = None) -> dict:
    """XBRL fundamentals. If `concept` (e.g. 'Revenues') given, returns one
    metric's series; otherwise returns the metric list."""
    cik = await resolve_cik(client, ticker_or_cik)
    if not cik:
        return {"error": f"could not resolve ticker/CIK: {ticker_or_cik}"}
    if concept:
        url = f"{EDGAR_DATA}/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
    else:
        url = f"{EDGAR_DATA}/api/xbrl/companyfacts/CIK{cik}.json"
    r = await _safe_get(client, url)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    if concept:
        units = d.get("units", {})
        # Return USD series if present
        usd_series = units.get("USD") or next(iter(units.values()), [])
        # Take last 6 entries
        series = sorted(usd_series, key=lambda x: x.get("end") or "")[-6:]
        return {
            "cik": cik,
            "concept": concept,
            "label": d.get("label"),
            "description": d.get("description"),
            "recent_series": [{"end": s.get("end"), "val": s.get("val"),
                                "fy": s.get("fy"), "fp": s.get("fp"),
                                "form": s.get("form")} for s in series],
        }
    facts = (d.get("facts") or {}).get("us-gaap") or {}
    return {
        "cik": cik,
        "name": d.get("entityName"),
        "available_concepts": sorted(facts.keys())[:60],  # cap to keep output reasonable
        "total_concepts": len(facts),
    }
