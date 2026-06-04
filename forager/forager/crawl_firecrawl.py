"""Firecrawl crawler adapter for Forager Phase 6.

Requires a FIRECRAWL_API_KEY environment variable and the `requests` package.
This adapter handles JS-heavy pages, dynamic rendering, and complex scraping
cases that SimpleHttpCrawlerAdapter and PdfCrawlerAdapter cannot cover.
"""
from __future__ import annotations

import os

from forager.crawl import CrawledDocument, CrawlerAdapter


class ConfigError(RuntimeError):
    """Raised when a required API key or package is missing."""


class FirecrawlCrawlerAdapter(CrawlerAdapter):
    """Crawls via the Firecrawl API.

    Set FIRECRAWL_API_KEY in the environment before use.
    See https://firecrawl.dev for API documentation.
    """

    source_name = "firecrawl"

    def __init__(self, api_key: str | None = None, api_url: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY")
        self.api_url = api_url or os.environ.get("FIRECRAWL_API_URL", "https://api.firecrawl.dev")
        if not self.api_key:
            raise ConfigError(
                "FIRECRAWL_API_KEY is required for FirecrawlCrawlerAdapter. "
                "Set the environment variable or pass api_key= explicitly."
            )
        try:
            import requests as _  # noqa: F401
        except ImportError as exc:
            raise ConfigError("pip install requests is required for FirecrawlCrawlerAdapter") from exc

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        import requests  # guarded above

        response = requests.post(
            f"{self.api_url}/v1/scrape",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"]},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        content = (data.get("data") or {}).get("markdown") or ""
        title = (data.get("data") or {}).get("metadata", {}).get("title")
        return CrawledDocument(
            url=url,
            title=title,
            content_markdown=content[:max_chars],
            content_text=content[:max_chars],
        )
