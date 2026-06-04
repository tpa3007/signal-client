"""CrawlRouter — dispatches to the right adapter based on URL and enforces
the crawl budget and robots.txt policy.

Usage:
    from forager.crawl_router import CrawlRouter, build_default_router
    router = build_default_router()                # uses SimpleHttpCrawlerAdapter for everything
    service = ForagerService(crawler_adapter=router)

To wire in specialized adapters:
    router = CrawlRouter(
        adapters={
            "http":    SimpleHttpCrawlerAdapter(),
            "github":  GitHubCrawlerAdapter(),
            "rss":     RssCrawlerAdapter(),
            "wayback": WaybackCrawlerAdapter(),
            "pdf":     PdfCrawlerAdapter(),
        },
        policy=CrawlPolicy(max_requests_per_domain=30, min_delay_seconds=1.0),
        check_robots=True,
    )
"""
from __future__ import annotations

from forager.crawl import CrawledDocument, CrawlerAdapter, ResilientCrawlerAdapter, SimpleHttpCrawlerAdapter
from forager.crawl_budget import CrawlBudgetExhausted, CrawlBudgetLedger, CrawlPolicy, RobotsPolicyChecker


class CrawlRouter(CrawlerAdapter):
    """Routes crawl requests to the appropriate sub-adapter.

    Routing priority (first match wins):
        github.com              → "github"
        *.pdf / /pdf/ in path  → "pdf"
        web.archive.org        → "wayback"
        /rss, /feed, .rss, .xml → "rss"
        everything else         → "http"

    If the named adapter is not registered, falls back to "http" or the first
    available adapter.
    """

    source_name = "router"

    def __init__(
        self,
        adapters: dict[str, CrawlerAdapter] | None = None,
        policy: CrawlPolicy | None = None,
        budget: CrawlBudgetLedger | None = None,
        check_robots: bool = False,
    ) -> None:
        self.policy = policy or CrawlPolicy()
        self.budget = budget or CrawlBudgetLedger(self.policy)
        self.robots: RobotsPolicyChecker | None = RobotsPolicyChecker() if check_robots else None
        self.adapters: dict[str, CrawlerAdapter] = adapters or {"http": SimpleHttpCrawlerAdapter()}

    # ------------------------------------------------------------------
    # CrawlerAdapter interface
    # ------------------------------------------------------------------

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        allowed, reason = self.budget.can_crawl(url)
        if not allowed:
            raise CrawlBudgetExhausted(f"{reason}: {url}")

        if self.robots is not None and self.policy.respect_robots:
            if not self.robots.is_allowed(url):
                raise RuntimeError(f"robots.txt disallows crawl: {url}")

        adapter = self._select(url)
        doc = adapter.crawl(url, max_chars=max_chars)

        bytes_fetched = len((doc.content_text or "").encode("utf-8"))
        self.budget.record_request(url, bytes_fetched)
        return doc

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _select(self, url: str) -> CrawlerAdapter:
        lower = url.lower()
        if "github.com" in lower:
            return self._get("github")
        if lower.endswith(".pdf") or "/pdf/" in lower or "filetype:pdf" in lower:
            return self._get("pdf")
        if "web.archive.org" in lower or "wayback" in lower:
            return self._get("wayback")
        if "/rss" in lower or "/feed" in lower or lower.endswith((".rss", ".xml", ".atom")):
            return self._get("rss")
        return self._get("http")

    def _get(self, name: str) -> CrawlerAdapter:
        return self.adapters.get(name) or self.adapters.get("http") or next(iter(self.adapters.values()))

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def budget_summary(self) -> dict:
        return self.budget.summary()

    def selected_adapter_name(self, url: str) -> str:
        adapter = self._select(url)
        return getattr(adapter, "source_name", type(adapter).__name__)


def build_default_router(
    policy: CrawlPolicy | None = None,
    check_robots: bool = False,
) -> CrawlRouter:
    """Build a router with the best available http adapter.

    Uses ResilientCrawlerAdapter (trafilatura → newspaper3k → SimpleHttp chain)
    when trafilatura is installed; falls back to SimpleHttpCrawlerAdapter otherwise.
    Specialized adapters (GitHub, PDF, RSS, Wayback) remain as SimpleHttp stubs
    unless explicitly overridden by the caller.
    """
    try:
        import trafilatura  # noqa: F401, PLC0415
        http: CrawlerAdapter = ResilientCrawlerAdapter()
    except ImportError:
        http = SimpleHttpCrawlerAdapter()
    simple = SimpleHttpCrawlerAdapter()
    return CrawlRouter(
        adapters={"http": http, "github": simple, "pdf": simple, "wayback": simple, "rss": simple},
        policy=policy,
        check_robots=check_robots,
    )
