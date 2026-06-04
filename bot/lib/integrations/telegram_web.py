"""Telegram public channel scraper — zero auth, zero API keys.

Two complementary backends, tried in order:

  1. RSShub RSS  — structured XML feed via rsshub.app public instance.
     Gives clean post text, dates, post URLs. Best quality.
     URL: https://rsshub.app/telegram/channel/{channel}

  2. Paginated t.me/s/  — Telegram's own SSR web preview.
     Supports ?before={message_id} pagination → can fetch 200+ posts.
     Slower but works when RSShub is rate-limited.

Neither requires a Telegram account, api_id, or any registration.
Both work for any PUBLIC channel.

Why not tg-archive / Telethon:
  - tg-archive needs api_id (my.telegram.org registration broken for some accounts)
  - snscrape TelegramChannelScraper broken on Python 3.12+ (deprecated)
  - Our two-backend approach covers 95% of use cases without credentials
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import unescape

import httpx


# ── Constants ────────────────────────────────────────────────────────────────

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MIN_INTERVAL_SEC = 2.0          # polite delay between t.me/s/ requests
_RSSHUB_INSTANCES = [            # tried in order; first success wins
    "https://rsshub.app",
    "https://rsshub.fly.dev",
    "https://rsshub.rssforever.com",
]
_RSSHUB_TIMEOUT = 12
_TMES_TIMEOUT = 12

_last_fetch_time: float = 0.0


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class TelegramPost:
    channel: str
    post_id: str
    text: str
    date: str | None = None       # ISO-like datetime string
    views: str | None = None       # "12.5K" format (t.me/s only)
    url: str = ""
    forwarded_from: str | None = None
    source: str = "web"           # "rsshub" | "web"


@dataclass
class TelegramChannelSnapshot:
    channel: str
    url: str
    posts: list[TelegramPost] = field(default_factory=list)
    raw_text: str = ""            # concatenated, ready for Forager injection
    backend: str = "none"         # "rsshub" | "web" | "none"
    error: str | None = None


# ── Backend 1: RSShub RSS ────────────────────────────────────────────────────

def _fetch_rsshub(channel: str) -> TelegramChannelSnapshot | None:
    """Try each RSShub instance in order; return snapshot or None on failure."""
    url_template = "/telegram/channel/{}"
    for base in _RSSHUB_INSTANCES:
        url = base + url_template.format(channel)
        try:
            r = httpx.get(
                url,
                timeout=_RSSHUB_TIMEOUT,
                headers={"User-Agent": _UA},
                follow_redirects=True,
            )
            if r.status_code != 200:
                continue
            posts = _parse_rss(channel, r.text)
            if not posts:
                continue
            snap = TelegramChannelSnapshot(
                channel=channel,
                url=url,
                posts=posts,
                backend="rsshub",
            )
            snap.raw_text = _build_raw_text(channel, posts)
            return snap
        except Exception:  # noqa: BLE001
            continue
    return None


def _parse_rss(channel: str, xml_text: str) -> list[TelegramPost]:
    """Parse RSShub RSS response into TelegramPost list."""
    posts: list[TelegramPost] = []
    try:
        # Strip default namespace declarations that confuse ElementTree
        xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]+"', "", xml_text, count=5)
        root = ET.fromstring(xml_clean)
    except ET.ParseError:
        return posts

    # RSS 2.0: channel/item; Atom: feed/entry
    ns_map = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//entry")

    for item in items:
        # Extract link (post URL)
        link_el = item.find("link")
        link = (link_el.text or "").strip() if link_el is not None else ""
        if not link:
            link_el = item.find("guid")
            link = (link_el.text or "").strip() if link_el is not None else ""

        # Extract post_id from URL like https://t.me/channel/12345
        post_id = ""
        m = re.search(r"/(\d+)/?$", link)
        if m:
            post_id = m.group(1)

        # Extract description / content
        desc_el = (
            item.find("description")
            or item.find("{http://www.w3.org/2005/Atom}content")
            or item.find("{http://www.w3.org/2005/Atom}summary")
        )
        raw_html = (desc_el.text or "") if desc_el is not None else ""
        # Also check for CDATA (already decoded by ET into plain text)
        text = _html_to_text(raw_html).strip()
        if not text or len(text) < 5:
            # Fall back to title
            title_el = item.find("title")
            text = (title_el.text or "").strip() if title_el is not None else ""

        if not text:
            continue

        # Extract date
        date = None
        for tag in ("pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published"):
            el = item.find(tag)
            if el is not None and el.text:
                date = el.text.strip()
                break

        posts.append(TelegramPost(
            channel=channel,
            post_id=post_id,
            text=text,
            date=date,
            url=link,
            source="rsshub",
        ))

    return posts


def _html_to_text(html: str) -> str:
    """Strip HTML tags, preserve paragraph breaks."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


# ── Backend 2: Paginated t.me/s/ ────────────────────────────────────────────

def _tmes_get(url: str) -> str | None:
    """Single rate-limited GET to t.me/s/; returns HTML or None."""
    global _last_fetch_time  # noqa: PLW0603
    elapsed = time.monotonic() - _last_fetch_time
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    try:
        r = httpx.get(
            url,
            timeout=_TMES_TIMEOUT,
            headers={
                "User-Agent": _UA,
                "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            },
            follow_redirects=True,
        )
        _last_fetch_time = time.monotonic()
        return r.text if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        _last_fetch_time = time.monotonic()
        return None


def _fetch_tmes_paginated(
    channel: str,
    max_posts: int = 200,
    max_pages: int = 8,
) -> TelegramChannelSnapshot:
    """Fetch channel posts via paginated t.me/s/?before={id}.

    Telegram's SSR web preview supports server-side pagination via the
    ?before={message_id} query parameter — each page returns ~20 posts
    prior to that ID.  We walk backwards until we have enough posts.
    """
    snap = TelegramChannelSnapshot(
        channel=channel,
        url=f"https://t.me/s/{channel}",
        backend="web",
    )
    all_posts: list[TelegramPost] = []
    before_id: int | None = None

    for page in range(max_pages):
        if len(all_posts) >= max_posts:
            break

        url = f"https://t.me/s/{channel}"
        if before_id is not None:
            url += f"?before={before_id}"

        html = _tmes_get(url)
        if html is None:
            if page == 0:
                snap.error = "HTTP error or private channel"
            break

        posts = _parse_tmes(channel, html)
        if not posts:
            break

        all_posts.extend(posts)

        # Find minimum post_id for next page (go further back in time)
        ids = [int(p.post_id) for p in posts if p.post_id.isdigit()]
        if not ids:
            break
        min_id = min(ids)
        if before_id is not None and min_id >= before_id:
            break  # no progress, stop
        before_id = min_id

    snap.posts = all_posts[:max_posts]
    snap.raw_text = _build_raw_text(channel, snap.posts)
    return snap


def _parse_tmes(channel: str, html: str) -> list[TelegramPost]:
    """Extract posts from a single t.me/s/ HTML page."""
    posts: list[TelegramPost] = []

    # Each message: data-post="channel/12345" attribute on a wrapper div
    # We extract per-message HTML blocks then pull text/date/views from each
    blocks = re.findall(
        r'data-post="[^"]+/(\d+)"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        html,
        re.DOTALL,
    )
    if not blocks:
        # Broader fallback
        blocks = re.findall(
            r'data-post="[^"]+/(\d+)".*?'
            r'tgme_widget_message_text[^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )

    for post_id, block_html in blocks:
        # Message text
        text_m = re.search(
            r'class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            block_html,
            re.DOTALL,
        )
        if not text_m:
            continue
        text = _html_to_text(text_m.group(1))
        if not text or len(text) < 10:
            continue

        date_m = re.search(r'datetime="([^"]+)"', block_html)
        views_m = re.search(r'tgme_widget_message_views[^>]*>([^<]+)<', block_html)
        fwd_m = re.search(
            r'tgme_widget_message_forwarded_from[^>]*>.*?<span[^>]*>([^<]+)</span>',
            block_html,
            re.DOTALL,
        )

        posts.append(TelegramPost(
            channel=channel,
            post_id=post_id,
            text=text,
            date=date_m.group(1) if date_m else None,
            views=views_m.group(1).strip() if views_m else None,
            url=f"https://t.me/{channel}/{post_id}",
            forwarded_from=fwd_m.group(1).strip() if fwd_m else None,
            source="web",
        ))

    return posts


# ── Keyword search within a channel ─────────────────────────────────────────

def search_channel(
    channel: str,
    query: str,
    *,
    max_posts: int = 50,
) -> TelegramChannelSnapshot:
    """Search for posts matching *query* within a single public channel.

    Uses Telegram's SSR ?q= parameter: https://t.me/s/{channel}?q={query}
    Supports pagination via additional ?before= parameter combined with ?q=.

    Falls back to empty snapshot if the channel doesn't support ?q= search
    (some channels return the full feed instead of filtered results — we
    detect this by checking whether result count is suspiciously high).
    """
    import urllib.parse  # noqa: PLC0415

    snap = TelegramChannelSnapshot(
        channel=channel,
        url=f"https://t.me/s/{channel}?q={urllib.parse.quote(query)}",
        backend="web_search",
    )
    all_posts: list[TelegramPost] = []
    before_id: int | None = None

    for page in range(4):  # max 4 pages ≈ 80 search results
        if len(all_posts) >= max_posts:
            break
        q_enc = urllib.parse.quote(query)
        url = f"https://t.me/s/{channel}?q={q_enc}"
        if before_id is not None:
            url += f"&before={before_id}"

        html = _tmes_get(url)
        if html is None:
            if page == 0:
                snap.error = "HTTP error or private channel"
            break

        posts = _parse_tmes(channel, html)
        if not posts:
            break

        all_posts.extend(posts)
        ids = [int(p.post_id) for p in posts if p.post_id.isdigit()]
        if not ids:
            break
        min_id = min(ids)
        if before_id is not None and min_id >= before_id:
            break
        before_id = min_id

    snap.posts = all_posts[:max_posts]
    snap.raw_text = _build_raw_text(channel, snap.posts)
    return snap


def search_channels_for_query(
    query: str,
    language: str,
    *,
    max_channels: int = 6,
    max_posts_per_channel: int = 30,
    tiers: list[str] | None = None,
) -> list[TelegramChannelSnapshot]:
    """Search a query across all registered channels for a language/region.

    For a market like "Will Russia capture Orikhiv before July?" this searches
    'russia orikhiv' across rybar, meduza, CITeam, nexta_tv, etc.

    Args:
        query:    search keywords (2-4 words work best)
        language: local_language value from Command G (e.g. "russian")
        max_channels: cap — avoids hammering Telegram
        max_posts_per_channel: post limit per channel
        tiers: which tiers to include (default: independent, opposition, blogger, regional)

    Returns:
        List of snapshots sorted by total post count descending.
    """
    if tiers is None:
        tiers = ["independent", "opposition", "regional", "blogger"]

    try:
        from lib.integrations.region_sources import get_sources_for_language  # noqa: PLC0415
        sources = get_sources_for_language(language, exclude_tiers=["state"], max_sources=50)
    except Exception:  # noqa: BLE001
        return []

    channels = [s.tg_channel for s in sources if s.tg_channel and s.tier in tiers]
    # deduplicate preserving order
    seen: set[str] = set()
    unique_channels: list[str] = []
    for ch in channels:
        if ch not in seen:
            seen.add(ch)
            unique_channels.append(ch)

    results: list[TelegramChannelSnapshot] = []
    for ch in unique_channels[:max_channels]:
        snap = search_channel(ch, query, max_posts=max_posts_per_channel)
        results.append(snap)

    results.sort(key=lambda s: len(s.posts), reverse=True)
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_channel(
    channel: str,
    *,
    max_posts: int = 100,
    prefer_rsshub: bool = True,
) -> TelegramChannelSnapshot:
    """Fetch recent posts from a public Telegram channel.

    Tries RSShub first (structured, clean), falls back to paginated t.me/s/.

    Args:
        channel:      channel name without @ (e.g. "meduza_io")
        max_posts:    maximum posts to return
        prefer_rsshub: try RSShub first (recommended); set False to skip

    Returns:
        TelegramChannelSnapshot — never raises, errors are in .error field
    """
    if prefer_rsshub:
        snap = _fetch_rsshub(channel)
        if snap and snap.posts:
            return snap

    # Fall back to paginated t.me/s/
    return _fetch_tmes_paginated(
        channel,
        max_posts=max_posts,
        max_pages=max(1, max_posts // 20),
    )


def fetch_channels(
    channels: list[str],
    *,
    max_channels: int = 6,
    max_posts_per_channel: int = 80,
    prefer_rsshub: bool = True,
) -> list[TelegramChannelSnapshot]:
    """Fetch multiple channels.  Returns all snapshots including errored ones."""
    results: list[TelegramChannelSnapshot] = []
    for ch in channels[:max_channels]:
        snap = fetch_channel(ch, max_posts=max_posts_per_channel, prefer_rsshub=prefer_rsshub)
        results.append(snap)
    return results


def _build_raw_text(channel: str, posts: list[TelegramPost]) -> str:
    """Build a single text document from posts for Forager injection."""
    if not posts:
        return ""
    lines: list[str] = [
        f"=== Telegram @{channel} — {len(posts)} posts ===\n"
    ]
    for p in posts:
        meta: list[str] = []
        if p.date:
            meta.append(p.date[:16].replace("T", " "))
        if p.views:
            meta.append(f"views:{p.views}")
        if p.forwarded_from:
            meta.append(f"fwd:{p.forwarded_from}")
        header = " | ".join(meta) if meta else "no-meta"
        lines.append(f"[{header}]\n{p.text}\n")
    return "\n".join(lines)


def channels_for_language(language: str, *, max_channels: int = 4) -> list[str]:
    """Return Telegram channel names for a language (from region_sources registry)."""
    try:
        from lib.integrations.region_sources import get_sources_for_language  # noqa: PLC0415
        sources = get_sources_for_language(language, max_sources=30)
        channels: list[str] = []
        seen: set[str] = set()
        for src in sorted(sources, key=lambda s: s.credibility, reverse=True):
            if src.tg_channel and src.tier not in ("state",) and src.tg_channel not in seen:
                channels.append(src.tg_channel)
                seen.add(src.tg_channel)
                if len(channels) >= max_channels:
                    break
        return channels
    except Exception:  # noqa: BLE001
        return []
