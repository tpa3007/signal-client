"""Wayback Machine diff — silent change detector for official pages.

Official websites (election commissions, ministries, central banks) often
update quietly — well before making formal press announcements.
Comparing the current page to a week-old snapshot can surface early signals:
  - Election commission adds candidate name or result row
  - Central bank updates "statement" page before press conference
  - Ministry changes troop deployment or policy language
  - Official biography page gets quietly updated (job title change, death)

Uses the Wayback Machine CDX API and Availability API.
Free, no auth required.

Usage:
    from lib.integrations.wayback import diff_page, get_snapshot_url

    result = diff_page("https://www.cec.gov.ua", days_ago=7)
    if result and result["change_score"] > 0.2:
        print(result["summary"])
"""
from __future__ import annotations

import re
import hashlib
import requests
from datetime import datetime, timedelta, timezone

_AVAILABILITY_API = "https://archive.org/wayback/available"
_CDX_API = "https://web.archive.org/cdx/search/cdx"
_WAYBACK_PREFIX = "https://web.archive.org/web"

# Minimum change score to return a result (avoids noise from ads/timestamps)
_MIN_CHANGE_SCORE = 0.05

# Tags that carry low-value dynamic content (timestamps, ads, counters)
_NOISE_RE = re.compile(
    r'<(script|style|noscript|iframe|ins|aside|nav|footer)[^>]*>.*?</\1>|'
    r'<!--.*?-->|'
    r'\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|UTC|GMT)?|'  # timestamps
    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}',              # ISO timestamps
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def get_snapshot_url(url: str, days_ago: int = 7, timeout: int = 10) -> str | None:
    """Get Wayback Machine snapshot URL for `url` from approximately `days_ago` days ago.

    Returns the WBM replay URL (https://web.archive.org/web/{ts}/{url}) or None.
    """
    target_dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    timestamp = target_dt.strftime("%Y%m%d")

    # CDX API: find closest snapshot to target date
    try:
        r = requests.get(
            _CDX_API,
            params={
                "url": url,
                "output": "json",
                "fl": "timestamp,statuscode",
                "filter": "statuscode:200",
                "limit": "1",
                "closest": timestamp,
                "from": (target_dt - timedelta(days=3)).strftime("%Y%m%d"),
                "to": target_dt.strftime("%Y%m%d"),
            },
            timeout=timeout,
        )
        if r.status_code == 200:
            rows = r.json()
            if len(rows) >= 2:  # first row is header
                ts = rows[1][0]
                return f"{_WAYBACK_PREFIX}/{ts}/{url}"
    except Exception:
        pass

    # Fallback: availability API (less precise date matching)
    try:
        r = requests.get(
            _AVAILABILITY_API,
            params={"url": url, "timestamp": timestamp},
            timeout=timeout,
        )
        if r.status_code == 200:
            data = r.json()
            snap = data.get("archived_snapshots", {}).get("closest", {})
            if snap.get("available") and snap.get("url"):
                return snap["url"]
    except Exception:
        pass

    return None


def _fetch_text(url: str, timeout: int = 15) -> str:
    """Fetch a URL and extract plain text (strip HTML, normalise whitespace)."""
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; signal-research/1.0)"},
            allow_redirects=True,
        )
        if r.status_code != 200:
            return ""
        html = r.text
    except Exception:
        return ""

    # Strip noise (scripts, styles, nav, timestamps)
    clean = _NOISE_RE.sub(" ", html)
    # Strip remaining HTML tags
    clean = _TAG_RE.sub(" ", clean)
    # Normalise whitespace
    clean = _WS_RE.sub(" ", clean).strip()
    return clean[:50_000]  # cap at 50k chars


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def _significant_diff(old_text: str, new_text: str) -> tuple[float, list[str], list[str]]:
    """Compute change score and extract added/removed sentence fragments.

    Returns (change_score, added_sentences, removed_sentences).
    change_score = 0.0 (identical) to 1.0 (completely different).
    """
    # Split into "sentences" (roughly: split on punctuation + line breaks)
    def sentences(text: str) -> set[str]:
        parts = re.split(r'[.!?\n]+', text)
        return {s.strip()[:120] for s in parts if len(s.strip()) > 20}

    old_sents = sentences(old_text)
    new_sents = sentences(new_text)

    added = [s for s in new_sents - old_sents if len(s) > 30]
    removed = [s for s in old_sents - new_sents if len(s) > 30]

    # Change score: Jaccard distance (1 - overlap ratio)
    union = old_sents | new_sents
    intersection = old_sents & new_sents
    if not union:
        return 0.0, [], []
    change_score = 1.0 - len(intersection) / len(union)

    return round(change_score, 3), added[:5], removed[:5]


def diff_page(
    url: str,
    *,
    days_ago: int = 7,
    min_change_score: float = _MIN_CHANGE_SCORE,
) -> dict | None:
    """Diff the current version of `url` against its Wayback snapshot from N days ago.

    Returns {url, days_ago, snapshot_url, change_score, added, removed, summary}
    or None if no significant change detected.

    change_score is between 0.0 (identical) and 1.0 (completely different).
    Noise (timestamps, ad banners) is stripped before comparison.
    """
    snapshot_url = get_snapshot_url(url, days_ago=days_ago)
    if not snapshot_url:
        return None

    old_text = _fetch_text(snapshot_url)
    new_text = _fetch_text(url)

    if not old_text or not new_text:
        return None

    # Quick hash check — if identical text, skip diff
    if _text_hash(old_text) == _text_hash(new_text):
        return None

    change_score, added, removed = _significant_diff(old_text, new_text)
    if change_score < min_change_score:
        return None

    # Build summary
    summary_parts = [f"Page changed (score={change_score:.2f}) since {days_ago} days ago."]
    if added:
        summary_parts.append(f"NEW content: {added[0][:100]}")
    if removed:
        summary_parts.append(f"REMOVED: {removed[0][:100]}")

    return {
        "url": url,
        "snapshot_url": snapshot_url,
        "days_ago": days_ago,
        "change_score": change_score,
        "added": added,
        "removed": removed,
        "summary": " | ".join(summary_parts),
    }


def diff_pages_for_candidate(candidate: dict) -> list[dict]:
    """Check Wayback diffs for all official_urls in a forager candidate dict.

    Reads candidate.get("official_urls") — a list of URLs to check.
    These are typically added by Command G for election/government markets.
    Returns list of diff results (non-None only).
    """
    official_urls = candidate.get("official_urls") or []
    results = []
    for url in official_urls[:3]:  # max 3 to limit latency
        result = diff_page(url)
        if result:
            results.append(result)
    return results
