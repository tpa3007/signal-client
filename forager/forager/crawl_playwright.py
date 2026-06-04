"""Playwright crawler adapter for Forager Phase 6.

Requires the `playwright` package and browser binaries:
    pip install playwright
    playwright install chromium

Use for JS-heavy pages, SPAs, or pages that require interaction before
content loads. This is slower than all other adapters — only use it when
Firecrawl or SimpleHttp fail to return meaningful content.
"""
from __future__ import annotations

from forager.crawl import CrawledDocument, CrawlerAdapter
from forager.crawl_firecrawl import ConfigError


class PlaywrightCrawlerAdapter(CrawlerAdapter):
    """Crawls pages using a headless Chromium browser via Playwright."""

    source_name = "playwright"

    def __init__(self, browser: str = "chromium", headless: bool = True) -> None:
        self.browser = browser
        self.headless = headless
        try:
            from playwright.sync_api import sync_playwright as _  # noqa: F401
        except ImportError as exc:
            raise ConfigError(
                "playwright package is required: pip install playwright && playwright install chromium"
            ) from exc

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = getattr(pw, self.browser).launch(headless=self.headless)
            try:
                page = browser.new_page()
                page.goto(url, timeout=30_000)
                page.wait_for_load_state("networkidle", timeout=10_000)
                title = page.title() or None
                text = page.inner_text("body")[:max_chars]
            finally:
                browser.close()

        return CrawledDocument(url=url, title=title, content_text=text)
