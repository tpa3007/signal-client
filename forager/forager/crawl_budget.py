"""Crawl budget ledger and rate-limit policy for Forager Phase 6.

The ledger tracks per-domain request counts, byte totals, and last-request
timestamps so the router can enforce rate limits and hard caps before any
external HTTP call is made.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse


class CrawlBudgetExhausted(RuntimeError):
    """Raised when the router blocks a crawl due to budget or rate limits."""


@dataclass
class CrawlPolicy:
    max_requests_per_domain: int = 20
    min_delay_seconds: float = 0.5
    respect_robots: bool = True
    max_bytes_per_session: int = 10_000_000   # 10 MB
    max_requests_per_session: int = 200


@dataclass
class DomainRecord:
    domain: str
    request_count: int = 0
    bytes_fetched: int = 0
    last_request_at: float = 0.0


class CrawlBudgetLedger:
    """Tracks crawl resource consumption and enforces CrawlPolicy limits."""

    def __init__(self, policy: CrawlPolicy | None = None) -> None:
        self.policy = policy or CrawlPolicy()
        self._domains: dict[str, DomainRecord] = {}
        self._total_requests: int = 0
        self._total_bytes: int = 0

    def can_crawl(self, url: str) -> tuple[bool, str | None]:
        """Return (allowed, reason) — reason is None when allowed."""
        domain = _domain(url)
        record = self._domains.get(domain)

        if self._total_requests >= self.policy.max_requests_per_session:
            return False, "session_request_limit"
        if self._total_bytes >= self.policy.max_bytes_per_session:
            return False, "session_bytes_limit"
        if record and record.request_count >= self.policy.max_requests_per_domain:
            return False, f"domain_limit:{domain}"
        if record and record.last_request_at > 0 and self.policy.min_delay_seconds > 0:
            elapsed = time.monotonic() - record.last_request_at
            if elapsed < self.policy.min_delay_seconds:
                return False, f"rate_limit:{domain}"
        return True, None

    def record_request(self, url: str, bytes_fetched: int = 0) -> None:
        domain = _domain(url)
        if domain not in self._domains:
            self._domains[domain] = DomainRecord(domain=domain)
        rec = self._domains[domain]
        rec.request_count += 1
        rec.bytes_fetched += bytes_fetched
        rec.last_request_at = time.monotonic()
        self._total_requests += 1
        self._total_bytes += bytes_fetched

    def domain_record(self, url: str) -> DomainRecord | None:
        return self._domains.get(_domain(url))

    @property
    def total_requests(self) -> int:
        return self._total_requests

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def summary(self) -> dict:
        return {
            "total_requests": self._total_requests,
            "total_bytes": self._total_bytes,
            "domains": {
                k: {"requests": v.request_count, "bytes": v.bytes_fetched}
                for k, v in self._domains.items()
            },
        }


class RobotsPolicyChecker:
    """Checks robots.txt for a URL. Fetches and caches per domain.

    Fails open: if robots.txt is unreachable the URL is allowed.
    """

    def __init__(self, user_agent: str = "SignalForager") -> None:
        self.user_agent = user_agent
        self._cache: dict[str, object] = {}

    def is_allowed(self, url: str) -> bool:
        from urllib.robotparser import RobotFileParser

        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        if robots_url not in self._cache:
            try:
                parser = RobotFileParser(robots_url)
                parser.read()
                self._cache[robots_url] = parser
            except Exception:
                self._cache[robots_url] = True  # fail-open
        cached = self._cache[robots_url]
        if cached is True:
            return True
        return cached.can_fetch(self.user_agent, url)  # type: ignore[union-attr]


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower() or url
