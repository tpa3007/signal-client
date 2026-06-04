"""Wikipedia edit surge detector.

A sudden spike in edits to a Wikipedia article is a strong leading indicator
that something notable just happened:
  - Death of a political figure    → article gets 30+ edits in 2h
  - Military coup / territory change → country/leader/city article surges
  - Election result announced       → candidate/country article spikes
  - Policy reversal / law passed    → topic article + related pages surge

Wikipedia usually updates within 15–30 minutes of an event while major
news agencies may take 30–90 minutes to publish.  Edit surges give us
a 15–60 minute edge before the English press catches up.

API: https://en.wikipedia.org/w/api.php  (free, no auth)

Usage:
    from lib.integrations.wikipedia_surge import detect_surge, surge_for_question
    result = detect_surge("Iran")
    if result and result["surge_score"] > 0.6:
        print(f"Surge: {result['edit_count_48h']} edits on '{result['title']}'")
"""
from __future__ import annotations

import re
import requests
from datetime import datetime, timezone, timedelta

_API = "https://en.wikipedia.org/w/api.php"

# Number of edits in the given window that constitutes a "surge"
SURGE_THRESHOLD_LOW = 6     # 6+ edits in 48h → weak surge
SURGE_THRESHOLD_HIGH = 15   # 15+ edits in 48h → strong surge
SURGE_THRESHOLD_EXTREME = 40  # 40+ edits in 48h → breaking news level

# Common stop words to strip from topic extraction
_QSTOP = frozenset({
    "will", "be", "the", "a", "an", "of", "in", "on", "by", "to", "for",
    "is", "are", "was", "were", "has", "have", "had", "at", "from",
    "this", "it", "its", "with", "or", "and", "not", "no", "yes",
    "win", "lose", "lost", "next", "new", "first", "last",
    "before", "after", "when", "who", "which", "where", "how", "what",
    "if", "does", "do", "did", "may", "might", "could", "would", "should",
    "more", "most", "any", "some", "all", "get", "got", "end",
    "year", "month", "week", "day", "least", "much", "their", "they",
    "about", "other", "also", "only", "just", "even", "still",
    "between", "over", "under", "above", "below",
    "2024", "2025", "2026", "2027",
})


def _extract_article_candidates(question: str) -> list[str]:
    """Derive 1–3 likely Wikipedia article titles from a market question.

    Strategy:
      1. Extract capitalized noun phrases (most specific → least specific)
      2. Fall back to 3-word chunks of non-stop words
    """
    # Capitalised phrase extractor: runs of Caps words (like "Donald Trump" or "North Korea")
    cap_phrases = re.findall(
        r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z]{2,}(?:\s+[A-Z][a-z]+)*)",
        question,
    )
    # Also extract individual capitalised words (≥4 chars, not sentence-start)
    # Sentence-start candidates are ambiguous; skip first word
    words = question.split()
    cap_singles = [w.rstrip("?.,:;") for w in words[1:] if w[0].isupper() and len(w) >= 4]

    candidates: list[str] = []
    seen: set[str] = set()
    for phrase in cap_phrases + cap_singles:
        phrase = phrase.strip("?.,:;()")
        if phrase and phrase not in seen and len(phrase) >= 4:
            seen.add(phrase)
            candidates.append(phrase)

    # If nothing extracted, fall back to first 3 non-stop content words
    if not candidates:
        content = [w.rstrip("?.,:;") for w in words if w.lower().rstrip("?.,:;") not in _QSTOP and len(w) >= 4]
        if content:
            candidates.append(" ".join(content[:3]).title())

    return candidates[:4]  # at most 4 candidate titles to check


def fetch_revision_timestamps(title: str, rvlimit: int = 50, timeout: int = 10) -> list[str]:
    """Return ISO timestamp strings for the most recent `rvlimit` revisions."""
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "rvlimit": str(rvlimit),
        "rvprop": "timestamp|user",
        "format": "json",
        "redirects": "1",
    }
    try:
        r = requests.get(_API, params=params, timeout=timeout,
                         headers={"User-Agent": "signal-research-bot/1.0"})
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    pages = data.get("query", {}).get("pages", {})
    for page_data in pages.values():
        if page_data.get("missing") is not None:
            return []   # article doesn't exist
        revisions = page_data.get("revisions") or []
        return [rv.get("timestamp", "") for rv in revisions if rv.get("timestamp")]

    return []


def _count_edits_in_window(timestamps: list[str], hours: int) -> tuple[int, list[str]]:
    """Count edits within the last `hours` and return (count, recent_ts_list)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for ts in timestamps:
        try:
            dt = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                recent.append(ts)
        except ValueError:
            continue
    return len(recent), recent


def detect_surge(
    topic: str,
    *,
    hours: int = 48,
    threshold: int = SURGE_THRESHOLD_LOW,
) -> dict | None:
    """Detect Wikipedia edit surge for a specific article title.

    Args:
        topic: Wikipedia article title (exact or close match)
        hours: look-back window in hours
        threshold: minimum edits in window to trigger

    Returns dict with surge details or None if no surge detected.
    {
        title, url, edit_count, hours_window, surge_score (0.0–1.0),
        surge_level ("low"/"high"/"extreme"), latest_edit
    }
    """
    timestamps = fetch_revision_timestamps(topic, rvlimit=50)
    if not timestamps:
        return None

    count, recent = _count_edits_in_window(timestamps, hours)
    if count < threshold:
        return None

    # Surge score: logarithmic scale — 6 edits = 0.40, 15 = 0.70, 40 = 1.0
    import math  # noqa: PLC0415
    surge_score = min(1.0, math.log(count + 1, 40 + 1))

    if count >= SURGE_THRESHOLD_EXTREME:
        level = "extreme"
    elif count >= SURGE_THRESHOLD_HIGH:
        level = "high"
    else:
        level = "low"

    return {
        "title": topic,
        "url": f"https://en.wikipedia.org/wiki/{topic.replace(' ', '_')}",
        "edit_count": count,
        "hours_window": hours,
        "surge_score": round(surge_score, 3),
        "surge_level": level,
        "latest_edit": recent[0] if recent else None,
    }


def surge_for_question(
    question: str,
    *,
    hours: int = 48,
    threshold: int = SURGE_THRESHOLD_LOW,
) -> dict | None:
    """Auto-detect Wikipedia edit surge from a Polymarket question string.

    Tries up to 4 candidate article titles derived from the question text.
    Returns the first (strongest) surge found, or None.

    Returns dict with {title, url, edit_count, surge_score, surge_level,
                        latest_edit, candidate_tried, hours_window}
    """
    candidates = _extract_article_candidates(question)
    if not candidates:
        return None

    best: dict | None = None
    for candidate in candidates:
        result = detect_surge(candidate, hours=hours, threshold=threshold)
        if result:
            # Pick highest surge score across candidates
            if best is None or result["surge_score"] > best["surge_score"]:
                result["candidate_tried"] = candidate
                best = result

    return best


def format_surge(result: dict) -> str:
    """Format a surge result for injection into Forager seed context."""
    level_emoji = {"low": "⚠", "high": "🔥", "extreme": "🚨"}.get(result["surge_level"], "⚠")
    return (
        f"{level_emoji} WIKIPEDIA EDIT SURGE: '{result['title']}' "
        f"— {result['edit_count']} edits in last {result['hours_window']}h "
        f"(surge_score={result['surge_score']:.2f}, level={result['surge_level']})\n"
        f"  Latest: {result.get('latest_edit', '?')[:16]}\n"
        f"  URL: {result['url']}"
    )
