"""TGStat global Telegram post search — zero auth, zero API keys.

TGStat (https://tgstat.ru / https://tgstat.com) is a Telegram analytics
platform that indexes posts from ALL public Telegram channels.  Their web
search lets you query across the entire indexed corpus — unlike t.me/s/ which
only searches within a single channel.

How it works:
  - GET https://tgstat.ru/en/search?q={query}&type=post&sort=1
  - Returns an SSR HTML page (no JS required for the initial result set)
  - No login, API key, or registration required
  - Falls back to tgstat.com (English domain) if the .ru domain fails

Graceful degradation:
  - If TGStat switches to JS-only rendering (no post-item divs in response),
    returns [] without raising.
  - Any network / parse error also returns [].
  - Rate-limited to one request every 3 seconds via module-level state.
"""
from __future__ import annotations

import re
import time
from html import unescape

import httpx


# ── Constants ─────────────────────────────────────────────────────────────────

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_SEARCH_URLS = [
    "https://tgstat.ru/en/search",
    "https://tgstat.com/en/search",
]

_MIN_INTERVAL_SEC = 3.0   # polite delay between calls
_last_call_time: float = 0.0

# Common question words to strip when extracting key terms
_STOP_WORDS: frozenset[str] = frozenset({
    "will", "does", "the", "a", "an", "be", "in", "on", "for", "to", "by",
    "is", "are", "was", "were", "has", "have", "get", "win", "lose", "next",
    "new", "first", "last", "2025", "2026", "2027", "this", "that", "it",
    "its", "of", "or", "and", "at", "as", "do", "not", "no", "if", "who",
    "what", "when", "where", "which", "how", "can", "could", "would",
    "should", "may", "might", "from", "with", "than", "their", "there",
    "about", "between", "into", "up", "out", "before",
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _html_to_text(html: str) -> str:
    """Strip HTML tags and decode entities; preserve paragraph breaks."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _rate_limit() -> None:
    """Block until the minimum inter-call interval has elapsed."""
    global _last_call_time  # noqa: PLW0603
    elapsed = time.monotonic() - _last_call_time
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    _last_call_time = time.monotonic()


def _extract_key_terms(question: str, n: int = 3) -> str:
    """Extract key search terms from a market question string.

    Removes common question/stop words, punctuation, and short tokens;
    returns the *n* longest remaining words joined by a space.

    Args:
        question: Free-text market question, e.g. "Will Russia enter a ceasefire?"
        n:        Number of key terms to return (default 3).

    Returns:
        Space-separated string of key terms, e.g. "russia ceasefire enter".
    """
    # Lowercase and remove punctuation
    clean = re.sub(r"[^\w\s]", " ", question.lower())
    tokens = clean.split()

    # Filter stop words and very short tokens
    candidates = [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]

    if not candidates:
        # Fall back to first 3 non-trivial tokens from original question
        candidates = [t for t in tokens if len(t) > 2]

    # Sort by length (longest = most specific) and take top n
    candidates.sort(key=len, reverse=True)
    return " ".join(candidates[:n])


# ── HTML parser ───────────────────────────────────────────────────────────────

def _parse_tgstat_html(html: str, max_results: int) -> list[dict]:
    """Parse TGStat search results HTML into a list of result dicts.

    Expected structure (SSR):
        <div class="post-item card">
          <div class="post-item__channel">
            <a class="font-weight-bold" href="/channel/@channelname">Display Name</a>
            <small>@channelname</small>
          </div>
          <div class="post-item__text">...post text...</div>
          <div class="post-item__info">
            <span class="post-item__date">22.05.2026 10:30</span>
            <span>views: 12 534</span>
          </div>
          <a href="https://t.me/channelname/12345">view post</a>
        </div>

    Returns [] if no post-item divs are present (JS rendering, empty page,
    or structural change).
    """
    results: list[dict] = []

    # Locate each post-item block; greedily capture until the next post-item
    # or end of string.  TGStat nests cards inside a container so we look for
    # the opening tag and capture until the next opening or a closing wrapper.
    # Strategy: split on the card opener, process each chunk.
    chunks = re.split(r'<div[^>]+class="[^"]*post-item[^"]*card[^"]*"', html)

    if len(chunks) <= 1:
        # No post-item cards found — likely JS-rendered or empty
        return []

    for chunk in chunks[1:]:  # first chunk is content before first card
        if len(results) >= max_results:
            break

        # ── Channel display name and /channel/ href ──────────────────────────
        channel_name = ""
        channel_url = ""
        ch_m = re.search(
            r'<a[^>]+href="(/channel/[^"]+)"[^>]*>([^<]+)</a>',
            chunk,
        )
        if ch_m:
            channel_url = ch_m.group(1)   # relative: /channel/@name
            channel_name = unescape(ch_m.group(2).strip())

        # Fallback: extract handle from <small>@handle</small>
        if not channel_name:
            small_m = re.search(r"<small[^>]*>(@\w+)</small>", chunk)
            if small_m:
                channel_name = small_m.group(1)

        # ── Post text ─────────────────────────────────────────────────────────
        text = ""
        text_m = re.search(
            r'class="[^"]*post-item__text[^"]*"[^>]*>(.*?)</div>',
            chunk,
            re.DOTALL,
        )
        if text_m:
            text = _html_to_text(text_m.group(1))

        if not text:
            continue

        # ── Date ──────────────────────────────────────────────────────────────
        date = ""
        date_m = re.search(
            r'class="[^"]*post-item__date[^"]*"[^>]*>([^<]+)<',
            chunk,
        )
        if date_m:
            date = date_m.group(1).strip()
        else:
            # Some versions use datetime= attribute on an <a> or <time> tag
            dt_m = re.search(r'datetime="([^"]+)"', chunk)
            if dt_m:
                date = dt_m.group(1).strip()

        # ── Views ─────────────────────────────────────────────────────────────
        views = ""
        # "views: 12 534" pattern (space as thousands separator)
        views_m = re.search(r"views[:\s]*([0-9][0-9\s]*)", chunk, re.IGNORECASE)
        if views_m:
            views = views_m.group(1).strip().replace("\xa0", "")

        # ── Post URL (direct t.me link) ───────────────────────────────────────
        post_url = ""
        url_m = re.search(r'href="(https://t\.me/[^"]+)"', chunk)
        if url_m:
            post_url = url_m.group(1)

        results.append({
            "channel": channel_name,
            "channel_url": channel_url,
            "text": text,
            "date": date,
            "views": views,
            "post_url": post_url,
        })

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def search_tgstat(
    query: str,
    max_results: int = 20,
    timeout: int = 15,
) -> list[dict]:
    """Search TGStat for posts matching *query* across all public Telegram channels.

    Tries tgstat.ru first, falls back to tgstat.com.  Both domains share the
    same search endpoint structure.

    Args:
        query:       Search query string.
        max_results: Maximum number of result dicts to return (default 20).
        timeout:     HTTP request timeout in seconds (default 15).

    Returns:
        List of dicts, each with keys:
            channel     — channel display name or @handle
            channel_url — TGStat relative path, e.g. "/channel/@channelname"
            text        — post text (HTML tags stripped)
            date        — date string as shown on site, e.g. "22.05.2026 10:30"
            views       — view count string, e.g. "12534" (may be empty)
            post_url    — direct t.me link, e.g. "https://t.me/channelname/12345"

        Returns [] on any error or if no results are found.
    """
    if not query or not query.strip():
        return []

    _rate_limit()

    params = {
        "q": query.strip(),
        "type": "post",
        "sort": "1",  # newest first
    }
    headers = {
        "User-Agent": _UA,
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://tgstat.ru/",
    }

    for base_url in _SEARCH_URLS:
        try:
            response = httpx.get(
                base_url,
                params=params,
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            )
            if response.status_code != 200:
                continue

            results = _parse_tgstat_html(response.text, max_results)
            if results:
                return results

            # Got 200 but no post-item divs — likely JS rendering on this domain;
            # try the fallback domain before giving up.

        except Exception:  # noqa: BLE001
            continue

    return []


def search_tgstat_for_market(
    question: str,
    max_results: int = 15,
) -> list[dict]:
    """Search TGStat using key terms extracted from a prediction market question.

    Extracts 2-3 key terms from *question* by removing common stop words and
    taking the longest remaining tokens, then calls search_tgstat().

    Args:
        question:    Market question text, e.g.
                     "Will Russia and Ukraine reach a ceasefire agreement in 2026?"
        max_results: Maximum results to return (default 15).

    Returns:
        List of post dicts (same schema as search_tgstat), or [] on failure.
    """
    query = _extract_key_terms(question, n=3)
    if not query:
        return []
    return search_tgstat(query, max_results=max_results)
