"""Dynamic Telegram channel discovery — finds channels we've never seen before.

The static region_sources registry only contains channels we already know about.
This module discovers UNKNOWN channels that are actively discussing a specific topic —
including small insider channels (100-5,000 subs) that often have signal before
the mainstream outlets even notice the story.

Multi-pass discovery strategy:
  1. TGStat channel search  — finds channels indexed by topic keyword
  2. TGStat post search     — extracts unique channel names from recent posts
  3. Forward chain analysis — channels frequently forwarded by others = original sources
  4. @-mention graph        — channels referenced inside other channels' posts
  5. Relevance scoring      — ranks by topic frequency, size preference, novelty

Why small channels matter:
  A 300-subscriber Telegram channel run by a local journalist, retired military
  officer, or political operative will often break a story 12-48h before the
  major outlets pick it up. These are the channels the crowd doesn't know about —
  which is exactly where our information edge lives.

No auth, no API keys. All public channel scraping via TGStat + t.me/s/.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from html import unescape

import httpx


# ── Constants ─────────────────────────────────────────────────────────────────

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_TGSTAT_BASES = [
    "https://tgstat.ru",
    "https://tgstat.com",
]

_MIN_INTERVAL_SEC = 3.0
_last_call: float = 0.0

# Subscriber ranges that suggest "insider" value
# Very large channels (>100k) are already in our registry; very small (<50) are likely
# private, inactive, or bots. Sweet spot: 200 – 80,000 subscribers.
_INSIDER_MIN_SUBS = 200
_INSIDER_MAX_SUBS = 80_000


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class DiscoveredChannel:
    """A Telegram channel found through dynamic discovery."""
    handle: str                      # channel name without @, e.g. "rybar"
    title: str = ""                  # display name
    subscribers: int = 0             # subscriber count (0 = unknown)
    description: str = ""            # channel description if available
    relevance_score: float = 0.0     # 0-1, how relevant to the query
    discovery_path: str = ""         # how we found it: "tgstat_channel", "post_author", "forward", "mention"
    is_in_registry: bool = False     # True if already in our static region_sources
    sample_posts: list[str] = field(default_factory=list)  # recent relevant posts (for context)
    post_url: str = ""               # example post URL

    @property
    def tme_url(self) -> str:
        return f"https://t.me/s/{self.handle}"

    @property
    def is_insider_size(self) -> bool:
        """True when subscriber count is in the 'unknown but potentially valuable' range."""
        if self.subscribers == 0:
            return True  # unknown size — include by default
        return _INSIDER_MIN_SUBS <= self.subscribers <= _INSIDER_MAX_SUBS


# ── Rate limiter ──────────────────────────────────────────────────────────────

def _rate_limit() -> None:
    global _last_call  # noqa: PLW0603
    elapsed = time.monotonic() - _last_call
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    _last_call = time.monotonic()


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _parse_subscriber_count(raw: str) -> int:
    """Parse TGStat subscriber strings like '12 534', '1.2K', '45.6K', '1.2M'."""
    raw = raw.strip().replace("\xa0", "").replace(" ", "")
    try:
        if raw.endswith("M") or raw.endswith("m"):
            return int(float(raw[:-1]) * 1_000_000)
        if raw.endswith("K") or raw.endswith("k"):
            return int(float(raw[:-1]) * 1_000)
        return int(re.sub(r"\D", "", raw))
    except (ValueError, AttributeError):
        return 0


# ── Pass 1: TGStat channel search ─────────────────────────────────────────────

def _tgstat_get(path: str, params: dict, timeout: int = 15) -> str | None:
    """GET a TGStat page, trying .ru then .com domains."""
    _rate_limit()
    headers = {
        "User-Agent": _UA,
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://tgstat.ru/",
    }
    for base in _TGSTAT_BASES:
        try:
            r = httpx.get(
                base + path,
                params=params,
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            )
            if r.status_code == 200 and len(r.text) > 500:
                return r.text
        except Exception:  # noqa: BLE001
            continue
    return None


def search_tgstat_channels(
    query: str,
    max_channels: int = 25,
) -> list[DiscoveredChannel]:
    """Find Telegram channels indexed on TGStat that match a topic query.

    Uses TGStat's channel search endpoint. Returns channels sorted by
    TGStat's relevance ranking (which tends to surface topically focused
    channels before mega-accounts).

    We parse two result formats TGStat has used historically:
      - card-based layout with .peer-item-channel cards
      - table layout with channel-row divs
    """
    html = _tgstat_get("/en/search", {"q": query, "type": "channel", "sort": "1"})
    if not html:
        # Fallback: try the channels-specific search path
        html = _tgstat_get("/en/channels", {"q": query})
    if not html:
        return []

    channels: list[DiscoveredChannel] = []
    seen: set[str] = set()

    # ── Format A: peer-item-channel cards ────────────────────────────────────
    # <div class="peer-item-channel ...">
    #   <a href="/channel/@handle">Title</a>
    #   <small>@handle</small>
    #   <span class="...">subscribers: 12 345</span>
    # </div>
    chunks_a = re.split(r'<div[^>]+class="[^"]*peer-item[^"]*"', html)
    for chunk in chunks_a[1:]:
        if len(channels) >= max_channels:
            break
        # Handle
        handle_m = re.search(r'href="(?:/channel/)?@?([\w]+)"', chunk)
        if not handle_m:
            continue
        handle = handle_m.group(1).lstrip("@").strip()
        if not handle or handle in seen or len(handle) < 3:
            continue
        # Title
        title_m = re.search(r'<a[^>]+>([^<]+)</a>', chunk)
        title = _strip_html(title_m.group(1)) if title_m else handle
        # Subscriber count
        subs_m = re.search(
            r'(?:subscriber|member|подписчик)[s\w]*[:\s]*([0-9][0-9\s\.\,KkMmБбмк]*)',
            chunk, re.IGNORECASE,
        )
        subs = _parse_subscriber_count(subs_m.group(1)) if subs_m else 0
        # Description snippet
        desc_m = re.search(r'<p[^>]*>([^<]{10,})</p>', chunk)
        desc = _strip_html(desc_m.group(1))[:200] if desc_m else ""

        seen.add(handle)
        channels.append(DiscoveredChannel(
            handle=handle,
            title=title,
            subscribers=subs,
            description=desc,
            discovery_path="tgstat_channel_search",
        ))

    # ── Format B: table rows ─────────────────────────────────────────────────
    if not channels:
        rows = re.findall(
            r'href="(?:/channel/)?@?([\w]+)"[^>]*>([^<]{2,60})</a>.*?'
            r'([0-9][0-9\s]{2,})',
            html,
            re.DOTALL,
        )
        for handle_raw, title_raw, subs_raw in rows[:max_channels]:
            handle = handle_raw.strip().lstrip("@")
            if not handle or handle in seen:
                continue
            seen.add(handle)
            channels.append(DiscoveredChannel(
                handle=handle,
                title=_strip_html(title_raw),
                subscribers=_parse_subscriber_count(subs_raw),
                discovery_path="tgstat_channel_search",
            ))

    return channels[:max_channels]


# ── Pass 2: Extract channel names from TGStat post results ───────────────────

def extract_channels_from_post_results(posts: list[dict]) -> list[DiscoveredChannel]:
    """Extract unique channel handles from TGStat post-search results.

    Each post result has a 'channel' field — these are the authors of recent
    posts about our topic. They may not be in our static registry at all.
    """
    seen: set[str] = set()
    channels: list[DiscoveredChannel] = []
    for post in posts:
        raw = (post.get("channel") or "").strip().lstrip("@")
        # TGStat sometimes returns display names like "Rybar" instead of handles
        # The channel_url field has the real handle: /channel/@rybar
        url = post.get("channel_url") or post.get("post_url") or ""
        handle_m = re.search(r'@?([\w]{3,32})', url.split("/channel/")[-1] if "/channel/" in url else "")
        handle = handle_m.group(1) if handle_m else re.sub(r'\s+', '', raw)
        if not handle or len(handle) < 3 or handle in seen:
            continue
        seen.add(handle)
        channels.append(DiscoveredChannel(
            handle=handle,
            title=raw,
            discovery_path="post_author",
            sample_posts=[post.get("text", "")[:200]],
            post_url=post.get("post_url", ""),
        ))
    return channels


# ── Pass 3: Forward-chain and @-mention extraction from fetched posts ─────────

def extract_channels_from_content(raw_text: str) -> list[str]:
    """Extract Telegram channel handles from post content.

    Finds:
      - Forwarded-from references: "Fwd: @handle" or "forwarded from @handle"
      - Explicit @mentions in post text
      - t.me/handle links embedded in posts

    These are leads to channels that the ones we already read consider authoritative
    or worth citing — a strong signal of relevance.
    """
    handles: list[str] = []
    seen: set[str] = set()

    # @handle mentions
    for m in re.finditer(r'@([\w]{3,32})', raw_text):
        h = m.group(1)
        if h not in seen:
            seen.add(h)
            handles.append(h)

    # t.me/handle links
    for m in re.finditer(r't\.me/([\w]{3,32})(?:/\d+)?', raw_text):
        h = m.group(1)
        if h not in seen and h.lower() not in ("joinchat", "s"):
            seen.add(h)
            handles.append(h)

    return handles


# ── Pass 4: Fetch channel to check relevance and get sample posts ─────────────

def _fetch_channel_sample(
    handle: str,
    query_keywords: list[str],
    max_posts: int = 30,
    timeout: int = 10,
) -> tuple[int, float, list[str]]:
    """Fetch recent posts from a channel and score relevance to query keywords.

    Returns (subscriber_count, relevance_0_to_1, matching_post_snippets).
    Fast, lightweight — only fetches the first page of t.me/s/.
    """
    try:
        r = httpx.get(
            f"https://t.me/s/{handle}",
            timeout=timeout,
            headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9,ru;q=0.8"},
            follow_redirects=True,
        )
        if r.status_code != 200:
            return 0, 0.0, []
        html = r.text
    except Exception:  # noqa: BLE001
        return 0, 0.0, []

    # Subscriber count from channel header
    subs = 0
    subs_m = re.search(
        r'(?:subscriber|member)[s]?[^>]*>\s*([0-9][0-9\s\.\,KkMmБбмк]*)',
        html, re.IGNORECASE,
    )
    if subs_m:
        subs = _parse_subscriber_count(subs_m.group(1))

    # Extract post texts
    texts: list[str] = []
    for text_m in re.finditer(
        r'tgme_widget_message_text[^>]*>(.*?)</div>',
        html, re.DOTALL,
    ):
        text = _strip_html(text_m.group(1))
        if len(text) > 20:
            texts.append(text[:300])

    if not texts:
        return subs, 0.0, []

    # Relevance: fraction of posts mentioning at least one keyword
    kw_lower = [kw.lower() for kw in query_keywords if len(kw) > 2]
    if not kw_lower:
        return subs, 0.5, texts[:3]

    hits = sum(
        1 for t in texts
        if any(kw in t.lower() for kw in kw_lower)
    )
    relevance = min(1.0, hits / max(len(texts), 1) * 2.0)  # scale: 50% hit rate → 1.0
    matching = [t for t in texts if any(kw in t.lower() for kw in kw_lower)][:5]

    return subs, relevance, matching


# ── Relevance scoring ─────────────────────────────────────────────────────────

def _score_channel(ch: DiscoveredChannel, query_keywords: list[str]) -> float:
    """Score a discovered channel for research value.

    Factors:
    - Relevance score from post content (primary)
    - Size preference: insider range (200-80k) > mega (>80k) > unknown
    - Discovery path: forward/mention > post_author > channel_search
    - Novelty: not in static registry gets a bonus
    """
    score = ch.relevance_score  # 0–1 base

    # Size bonus — prefer insider range
    if ch.subscribers == 0:
        score += 0.10  # unknown size: mild bonus (might be very small insider)
    elif _INSIDER_MIN_SUBS <= ch.subscribers <= _INSIDER_MAX_SUBS:
        # Peak bonus at ~5,000 subs, tailing off in both directions
        if ch.subscribers <= 5_000:
            size_bonus = 0.20 * (ch.subscribers / 5_000)
        else:
            # Logarithmic decay above 5k
            import math
            size_bonus = 0.20 * max(0.0, 1.0 - math.log10(ch.subscribers / 5_000) * 0.5)
        score += size_bonus
    elif ch.subscribers > 80_000:
        score += 0.02  # large channel, probably already known

    # Discovery path bonus
    path_bonus = {
        "forward": 0.15,        # someone trusted forwarded from here
        "mention": 0.12,        # someone cited this channel
        "post_author": 0.08,    # posted about our topic
        "tgstat_channel_search": 0.05,
    }
    score += path_bonus.get(ch.discovery_path, 0.0)

    # Novelty bonus (not in our static registry = we haven't seen it before)
    if not ch.is_in_registry:
        score += 0.10

    return min(1.0, score)


# ── Main discovery entry point ────────────────────────────────────────────────

def discover_channels_for_market(
    question: str,
    keywords: list[str] | None = None,
    *,
    max_final: int = 12,
    max_to_probe: int = 30,
    known_registry_handles: set[str] | None = None,
    verbose: bool = True,
) -> list[DiscoveredChannel]:
    """Discover unknown Telegram channels relevant to a prediction market.

    Full multi-pass discovery:
      1. TGStat channel search
      2. TGStat post search → extract posting channels
      3. Forward/mention extraction from fetched content
      4. Lightweight relevance probing for all candidates
      5. Scoring and ranking

    Args:
        question:              The market question text.
        keywords:              Optional keyword list; extracted from question if None.
        max_final:             How many channels to return after scoring.
        max_to_probe:          How many candidates to probe with live fetches.
        known_registry_handles: Set of handles already in static registry (for novelty scoring).
        verbose:               Print discovery progress.

    Returns:
        Ranked list of DiscoveredChannel, best first.
    """
    if keywords is None:
        keywords = _extract_keywords(question, n=5)

    query = " ".join(keywords[:3])
    if verbose:
        print(f"  [TG-DISCO] Discovering channels for: '{query}'")
        print(f"  [TG-DISCO] Keywords: {keywords}")

    if known_registry_handles is None:
        known_registry_handles = _load_registry_handles()

    all_candidates: dict[str, DiscoveredChannel] = {}  # handle → channel

    # ── Pass 1: TGStat channel search ─────────────────────────────────────────
    try:
        ch_results = search_tgstat_channels(query, max_channels=20)
        for ch in ch_results:
            ch.is_in_registry = ch.handle.lower() in known_registry_handles
            all_candidates[ch.handle.lower()] = ch
        if verbose:
            print(f"  [TG-DISCO] Pass 1 (channel search): {len(ch_results)} channels found")
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  [TG-DISCO] Pass 1 failed: {e}")

    # ── Pass 2: TGStat post search → extract posting channels ────────────────
    try:
        from lib.integrations.tgstat import search_tgstat  # noqa: PLC0415
        posts = search_tgstat(query, max_results=30)
        post_channels = extract_channels_from_post_results(posts)
        added = 0
        for ch in post_channels:
            k = ch.handle.lower()
            if k not in all_candidates:
                ch.is_in_registry = k in known_registry_handles
                all_candidates[k] = ch
                added += 1
        if verbose:
            print(f"  [TG-DISCO] Pass 2 (post authors): {len(posts)} posts → {added} new channels")
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  [TG-DISCO] Pass 2 failed: {e}")

    # ── Pass 3: Second-keyword variation ─────────────────────────────────────
    # If we have enough keywords, try a variation query to catch different angles
    if len(keywords) >= 4:
        alt_query = " ".join(keywords[1:4])  # shifted by one keyword
        try:
            from lib.integrations.tgstat import search_tgstat  # noqa: PLC0415
            alt_posts = search_tgstat(alt_query, max_results=20)
            alt_ch = extract_channels_from_post_results(alt_posts)
            added_alt = 0
            for ch in alt_ch:
                k = ch.handle.lower()
                if k not in all_candidates:
                    ch.is_in_registry = k in known_registry_handles
                    all_candidates[k] = ch
                    added_alt += 1
            if verbose and added_alt:
                print(f"  [TG-DISCO] Pass 3 (alt query '{alt_query}'): {added_alt} new channels")
        except Exception:  # noqa: BLE001
            pass

    if not all_candidates:
        if verbose:
            print("  [TG-DISCO] No candidates found — TGStat may be JS-only today")
        return []

    if verbose:
        print(f"  [TG-DISCO] Total candidates before probing: {len(all_candidates)}")

    # ── Pass 4: Lightweight relevance probing ─────────────────────────────────
    # Sort candidates: prioritise novel channels (not in registry) and post_authors
    # (we know they posted about this topic recently) for probing budget.
    priority_order = sorted(
        all_candidates.values(),
        key=lambda c: (
            0 if not c.is_in_registry else 1,          # novel first
            0 if c.discovery_path == "post_author" else 1,  # post authors second
            c.subscribers if c.subscribers > 0 else 5_000,  # smaller first (among same tier)
        ),
    )

    probed = 0
    for ch in priority_order[:max_to_probe]:
        if probed >= max_to_probe:
            break
        try:
            subs, rel, samples = _fetch_channel_sample(ch.handle, keywords, timeout=8)
            if subs > 0 and ch.subscribers == 0:
                ch.subscribers = subs
            if rel > 0 or ch.relevance_score == 0.0:
                ch.relevance_score = rel
            if samples:
                ch.sample_posts = samples[:3]
            # Extract @mentions from samples for forward chain enrichment
            for sample in samples[:2]:
                for mention in extract_channels_from_content(sample):
                    mk = mention.lower()
                    if mk not in all_candidates and len(all_candidates) < max_to_probe * 2:
                        all_candidates[mk] = DiscoveredChannel(
                            handle=mention,
                            discovery_path="mention",
                            is_in_registry=mk in known_registry_handles,
                        )
            probed += 1
            time.sleep(1.5)  # polite pacing on t.me/s/
        except Exception:  # noqa: BLE001
            probed += 1
            continue

    if verbose:
        print(f"  [TG-DISCO] Probed {probed} channels")

    # ── Pass 5: Score and rank ────────────────────────────────────────────────
    for ch in all_candidates.values():
        ch.relevance_score = _score_channel(ch, keywords)

    ranked = sorted(
        all_candidates.values(),
        key=lambda c: c.relevance_score,
        reverse=True,
    )

    # Filter out channels with zero content and zero relevance
    ranked = [c for c in ranked if c.relevance_score > 0.05 or c.sample_posts]

    if verbose:
        print(f"  [TG-DISCO] Top discovered channels:")
        for c in ranked[:8]:
            subs_label = f"{c.subscribers:,}" if c.subscribers else "?"
            registry_tag = " [known]" if c.is_in_registry else " [NEW]"
            print(
                f"    @{c.handle:<22} subs={subs_label:<8} "
                f"rel={c.relevance_score:.2f} via={c.discovery_path}{registry_tag}"
            )

    return ranked[:max_final]


# ── Format discovered channels for Forager injection ─────────────────────────

def format_discoveries_for_forager(
    channels: list[DiscoveredChannel],
    max_channels: int = 8,
) -> str:
    """Format discovered channels as a text block for injection into Forager seed context.

    Includes the channel name, size (as a credibility signal), how it was found,
    and sample posts so Forager can assess relevance immediately.
    """
    if not channels:
        return ""

    lines = ["=== DYNAMICALLY DISCOVERED TELEGRAM CHANNELS ===",
             "These channels were found through automated discovery (not from static registry).",
             "Small channels may have insider or local knowledge not yet in mainstream press.\n"]

    for i, ch in enumerate(channels[:max_channels], 1):
        subs_label = f"{ch.subscribers:,} subscribers" if ch.subscribers > 0 else "unknown size"
        novel_tag = "NEW — not in our usual source list" if not ch.is_in_registry else "already known"
        lines.append(f"[{i}] @{ch.handle} — {ch.title or ch.handle}")
        lines.append(f"     {subs_label} | found via: {ch.discovery_path} | {novel_tag}")
        lines.append(f"     URL: https://t.me/s/{ch.handle}")
        if ch.description:
            lines.append(f"     Description: {ch.description[:150]}")
        if ch.sample_posts:
            lines.append("     Recent posts on topic:")
            for post in ch.sample_posts[:2]:
                lines.append(f"       • {post[:200]}")
        lines.append("")

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_keywords(question: str, n: int = 5) -> list[str]:
    """Extract key terms from a market question for channel discovery queries."""
    _STOP = frozenset({
        "will", "does", "the", "a", "an", "be", "in", "on", "for", "to", "by",
        "is", "are", "was", "were", "has", "have", "get", "win", "lose", "next",
        "new", "first", "last", "2025", "2026", "2027", "this", "that", "it",
        "its", "of", "or", "and", "at", "as", "do", "not", "no", "if", "who",
        "what", "when", "where", "which", "how", "can", "could", "would",
        "should", "may", "might", "from", "with", "than", "their", "there",
        "about", "between", "into", "up", "out", "before", "after", "become",
        "becomes", "became", "next", "prime", "minister", "president", "election",
    })
    clean = re.sub(r"[^\w\s]", " ", question.lower())
    tokens = [t for t in clean.split() if t not in _STOP and len(t) > 2]
    tokens.sort(key=len, reverse=True)
    return tokens[:n]


def _load_registry_handles() -> set[str]:
    """Load all known channel handles from the static region_sources registry."""
    try:
        from lib.integrations.region_sources import get_sources_for_language  # noqa: PLC0415
        # Load a broad set — use all languages
        all_handles: set[str] = set()
        for lang in [
            "russian", "arabic", "persian", "hebrew", "chinese", "korean",
            "romanian", "turkish", "german", "french", "spanish", "english",
        ]:
            try:
                sources = get_sources_for_language(lang, max_sources=100)
                for s in sources:
                    if s.tg_channel:
                        all_handles.add(s.tg_channel.lower())
            except Exception:  # noqa: BLE001
                pass
        return all_handles
    except Exception:  # noqa: BLE001
        return set()
