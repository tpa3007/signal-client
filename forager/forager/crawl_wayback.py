"""Wayback Machine / archive.org crawler adapter for Forager Phase 6.

Uses the CDX Search API (free, no key required) to find the latest snapshot
of a URL, then fetches the archived version via SimpleHttpCrawlerAdapter.
"""
from __future__ import annotations

import json
import urllib.parse
from urllib.request import Request, urlopen

from forager.crawl import CrawledDocument, CrawlerAdapter, SimpleHttpCrawlerAdapter

_CDX_API = "https://web.archive.org/cdx/search/cdx"
_ARCHIVE_BASE = "https://web.archive.org/web"


class WaybackCrawlerAdapter(CrawlerAdapter):
    """Fetches a URL through the Wayback Machine.

    If the URL is already a web.archive.org URL it is fetched directly.
    Otherwise the CDX API is queried for the most recent 200-status snapshot.
    """

    source_name = "wayback"

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        if "web.archive.org" in url.lower():
            return self._fetch_archive(url, max_chars)
        archive_url = self._latest_snapshot(url)
        if archive_url is None:
            raise RuntimeError(f"no Wayback snapshot found for: {url}")
        return self._fetch_archive(archive_url, max_chars)

    def latest_snapshot_url(self, url: str) -> str | None:
        """Return the archive URL of the most recent 200-status snapshot, or None."""
        return self._latest_snapshot(url)

    def _latest_snapshot(self, url: str) -> str | None:
        params = urllib.parse.urlencode(
            {
                "url": url,
                "output": "json",
                "limit": 1,
                "fl": "timestamp,original",
                "filter": "statuscode:200",
                "sort": "reverse",
            }
        )
        cdx_url = f"{_CDX_API}?{params}"
        request = Request(cdx_url, headers={"User-Agent": "SignalForager/0.6"})
        with urlopen(request, timeout=15) as resp:
            data = json.loads(resp.read())
        # CDX returns [["timestamp","original"], [val, val], ...]
        if not isinstance(data, list) or len(data) < 2:
            return None
        timestamp, original = data[1]
        return f"{_ARCHIVE_BASE}/{timestamp}/{original}"

    def _fetch_archive(self, archive_url: str, max_chars: int) -> CrawledDocument:
        inner = SimpleHttpCrawlerAdapter()
        doc = inner.crawl(archive_url, max_chars=max_chars)
        return CrawledDocument(
            url=archive_url,
            title=doc.title,
            content_text=doc.content_text,
            content_markdown=doc.content_markdown,
        )
