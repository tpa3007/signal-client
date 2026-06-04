"""Crawler adapters for Forager.

The crawler layer converts a promoted source URL into raw document text. It is
kept behind an interface so Phase 2 can run without browser dependencies while
Phase 3 can swap in Firecrawl or Playwright.

Resilience chain (ResilientCrawlerAdapter):
  trafilatura  →  newspaper3k  →  SimpleHttp  →  snippet-only fallback

trafilatura handles boilerplate stripping, gzip, redirects, and most news sites.
newspaper3k handles structured article extraction where trafilatura struggles.
SimpleHttp is the baseline for plain HTML pages.
Snippet-only fallback extracts title + meta description when full crawl fails —
better than raising and losing the source entirely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# Domains that require JS / CAPTCHA / paywall and will never succeed with
# any HTTP-only crawler.  We skip the full crawl and use snippet fallback
# directly to avoid burning budget on known failures.
_JS_ONLY_DOMAINS = frozenset({
    "youtube.com", "youtu.be",
    "twitter.com", "x.com",
    "instagram.com", "tiktok.com",
    "facebook.com", "fb.com",
    "linkedin.com",
    "polymarket.com",
})


@dataclass(frozen=True)
class CrawledDocument:
    url: str
    title: str | None
    content_text: str
    content_markdown: str | None = None
    language: str | None = None
    published_at: str | None = None
    raw_content_hash: str | None = None


class CrawlerAdapter:
    source_name = "base"

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        raise NotImplementedError


class StaticCrawlerAdapter(CrawlerAdapter):
    source_name = "static"

    def __init__(self, documents: dict[str, CrawledDocument]) -> None:
        self.documents = documents

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        if url not in self.documents:
            raise RuntimeError(f"static crawler has no document for url: {url}")
        doc = self.documents[url]
        return CrawledDocument(
            url=doc.url,
            title=doc.title,
            content_text=doc.content_text[:max_chars],
            content_markdown=doc.content_markdown[:max_chars] if doc.content_markdown else None,
            language=doc.language,
            published_at=doc.published_at,
            raw_content_hash=doc.raw_content_hash,
        )


class SimpleHttpCrawlerAdapter(CrawlerAdapter):
    source_name = "simple_http"

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        request = Request(url, headers={"User-Agent": "SignalForager/0.2"})
        with urlopen(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(max_chars * 4)
        text = raw.decode("utf-8", errors="replace")
        title = None
        if "html" in content_type.lower() or "<html" in text.lower():
            title = _extract_title(text)
            text = _html_to_text(text)
        return CrawledDocument(url=url, title=title, content_text=text[:max_chars], content_markdown=None)


class ResilientCrawlerAdapter(CrawlerAdapter):
    """Multi-strategy crawler: trafilatura → newspaper3k → SimpleHttp → snippet fallback.

    Designed for production use.  Never raises — returns a CrawledDocument
    even for paywalled/JS-only pages (snippet-only fallback with short text).
    The caller should check len(doc.content_text) to gauge extraction quality.
    """
    source_name = "resilient"
    MIN_USEFUL_CHARS = 200  # below this, consider strategy failed

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        domain = urlparse(url).netloc.lower().removeprefix("www.")

        # Skip full crawl for JS-only domains — go straight to snippet fallback
        if any(d in domain for d in _JS_ONLY_DOMAINS):
            return self._snippet_fallback(url, max_chars, reason="js_only_domain")

        # 1. trafilatura — best general-purpose article extractor
        try:
            doc = self._crawl_trafilatura(url, max_chars)
            if doc is not None:
                return doc
        except Exception:  # noqa: BLE001
            pass

        # 2. newspaper3k — structured article extraction
        try:
            doc = self._crawl_newspaper(url, max_chars)
            if doc is not None:
                return doc
        except Exception:  # noqa: BLE001
            pass

        # 3. SimpleHttp — basic HTML stripper
        try:
            return SimpleHttpCrawlerAdapter().crawl(url, max_chars=max_chars)
        except Exception:  # noqa: BLE001
            pass

        # 4. Snippet fallback — fetch raw HTML, extract title + meta description only
        return self._snippet_fallback(url, max_chars, reason="all_strategies_failed")

    # ── private strategies ────────────────────────────────────────────────

    def _crawl_trafilatura(self, url: str, max_chars: int) -> CrawledDocument | None:
        import trafilatura  # noqa: PLC0415
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        if not text or len(text) < self.MIN_USEFUL_CHARS:
            return None
        try:
            metadata = trafilatura.extract_metadata(downloaded)
            title = metadata.title if metadata else None
            published_at = str(metadata.date) if (metadata and metadata.date) else None
        except Exception:  # noqa: BLE001
            title = None
            published_at = None
        return CrawledDocument(
            url=url,
            title=title,
            content_text=text[:max_chars],
            content_markdown=None,
            published_at=published_at,
        )

    def _crawl_newspaper(self, url: str, max_chars: int) -> CrawledDocument | None:
        """Article extraction using newspaper4k (preferred) or newspaper3k (fallback).

        newspaper4k is a maintained fork of newspaper3k with better multilingual
        support, async capabilities, and improved extraction for modern CMS sites.
        Install: pip install newspaper4k  (drop-in replacement, same API)
        Fallback: pip install newspaper3k  (legacy, still works)
        """
        article = None
        try:
            # newspaper4k: maintained fork with better multilingual + modern CMS support
            from newspaper import Article  # noqa: PLC0415
            article = Article(url, fetch_images=False, memoize_articles=False)
            article.download()
            article.parse()
        except ImportError:
            return None
        except Exception:  # noqa: BLE001
            return None

        if not article or not article.text or len(article.text) < self.MIN_USEFUL_CHARS:
            return None

        published_at: str | None = None
        if article.publish_date:
            try:
                published_at = article.publish_date.isoformat()
            except Exception:  # noqa: BLE001
                pass

        # newspaper4k exposes article.meta_lang and article.authors for enrichment
        language: str | None = getattr(article, "meta_lang", None) or None
        return CrawledDocument(
            url=url,
            title=article.title or None,
            content_text=article.text[:max_chars],
            content_markdown=None,
            language=language,
            published_at=published_at,
        )

    def _snippet_fallback(self, url: str, max_chars: int, *, reason: str = "") -> CrawledDocument:
        """Best-effort: fetch raw HTML (if possible), extract title + meta description."""
        title: str | None = None
        description: str | None = None
        try:
            req = Request(url, headers={"User-Agent": "SignalForager/0.2"})
            with urlopen(req, timeout=10) as resp:
                raw = resp.read(32_000).decode("utf-8", errors="replace")
            title = _extract_title(raw)
            description = _extract_meta_description(raw)
        except Exception:  # noqa: BLE001
            pass
        text_parts = [p for p in [title, description] if p]
        content = " | ".join(text_parts) if text_parts else f"[crawl failed: {reason}]"
        return CrawledDocument(
            url=url,
            title=title,
            content_text=content[:max_chars],
            content_markdown=None,
        )


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return _collapse_ws(unescape(re.sub(r"<[^>]+>", " ", match.group(1))))


def _extract_meta_description(html: str) -> str | None:
    match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{10,500})["\']',
        html, re.IGNORECASE,
    )
    if not match:
        # Try alternate attribute order
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']{10,500})["\'][^>]+name=["\']description["\']',
            html, re.IGNORECASE,
        )
    if match:
        return _collapse_ws(unescape(match.group(1)))
    # og:description fallback
    match = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{10,500})["\']',
        html, re.IGNORECASE,
    )
    return _collapse_ws(unescape(match.group(1))) if match else None


def _html_to_text(html: str) -> str:
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<(p|br|li|h[1-6]|div|section|article)[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    return _collapse_ws(unescape(text))


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def create_default_crawler() -> CrawlerAdapter:
    """Auto-select the best available crawler based on installed packages."""
    try:
        import trafilatura  # noqa: F401, PLC0415
        return ResilientCrawlerAdapter()
    except ImportError:
        return SimpleHttpCrawlerAdapter()
