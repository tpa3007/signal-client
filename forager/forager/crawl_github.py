"""GitHub crawler adapter for Forager Phase 6.

Fetches repository READMEs, issues, releases, and commits via the GitHub
REST API. No authentication is required for public repositories, but a
GITHUB_TOKEN env var will raise the rate limit from 60 to 5000 req/h.
"""
from __future__ import annotations

import base64
import json
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from forager.crawl import CrawledDocument, CrawlerAdapter

_API_BASE = "https://api.github.com"


class GitHubCrawlerAdapter(CrawlerAdapter):
    """Routes github.com URLs to the appropriate GitHub API endpoint."""

    source_name = "github"

    def __init__(self, api_token: str | None = None) -> None:
        self.api_token = api_token or os.environ.get("GITHUB_TOKEN")

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        owner, repo, path_parts = self._parse_url(url)
        if owner is None or repo is None:
            raise RuntimeError(f"GitHub URL must include owner/repo: {url}")

        if path_parts and path_parts[0] == "issues":
            if len(path_parts) >= 2 and path_parts[1].isdigit():
                return self._issue(owner, repo, int(path_parts[1]), url, max_chars)
            return self._issues_list(owner, repo, url, max_chars)
        if path_parts and path_parts[0] == "releases":
            return self._releases(owner, repo, url, max_chars)
        if path_parts and path_parts[0] == "commits":
            return self._commits(owner, repo, url, max_chars)
        return self._readme(owner, repo, url, max_chars)

    # ------------------------------------------------------------------
    # URL parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_url(url: str) -> tuple[str | None, str | None, list[str]]:
        parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
        if len(parts) < 2:
            return None, None, []
        return parts[0], parts[1], parts[2:]

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _api_get(self, path: str) -> object:
        full_url = f"{_API_BASE}{path}"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "SignalForager/0.6"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        request = Request(full_url, headers=headers)
        with urlopen(request, timeout=15) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    # Endpoint implementations
    # ------------------------------------------------------------------

    def _readme(self, owner: str, repo: str, url: str, max_chars: int) -> CrawledDocument:
        try:
            data = self._api_get(f"/repos/{owner}/{repo}/readme")
            assert isinstance(data, dict)
            text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")[:max_chars]
        except Exception as exc:
            text = f"[GitHub README fetch error: {exc}]"
        return CrawledDocument(url=url, title=f"{owner}/{repo} README", content_text=text)

    def _issues_list(self, owner: str, repo: str, url: str, max_chars: int) -> CrawledDocument:
        try:
            data = self._api_get(f"/repos/{owner}/{repo}/issues?state=open&per_page=30")
            assert isinstance(data, list)
            lines = [
                f"#{i['number']}: {i['title']} — {(i.get('body') or '')[:200]}"
                for i in data
                if isinstance(i, dict)
            ]
            text = "\n".join(lines)[:max_chars]
        except Exception as exc:
            text = f"[GitHub issues fetch error: {exc}]"
        return CrawledDocument(url=url, title=f"{owner}/{repo} issues", content_text=text)

    def _issue(self, owner: str, repo: str, number: int, url: str, max_chars: int) -> CrawledDocument:
        try:
            data = self._api_get(f"/repos/{owner}/{repo}/issues/{number}")
            assert isinstance(data, dict)
            text = f"#{data['number']}: {data['title']}\n\n{data.get('body', '')}"[:max_chars]
            title = f"{owner}/{repo}#{number}: {data['title']}"
        except Exception as exc:
            text = f"[GitHub issue fetch error: {exc}]"
            title = f"{owner}/{repo}#{number}"
        return CrawledDocument(url=url, title=title, content_text=text)

    def _releases(self, owner: str, repo: str, url: str, max_chars: int) -> CrawledDocument:
        try:
            data = self._api_get(f"/repos/{owner}/{repo}/releases?per_page=10")
            assert isinstance(data, list)
            lines = [
                f"{r['tag_name']}: {r['name']} — {(r.get('body') or '')[:200]}"
                for r in data
                if isinstance(r, dict)
            ]
            text = "\n".join(lines)[:max_chars]
        except Exception as exc:
            text = f"[GitHub releases fetch error: {exc}]"
        return CrawledDocument(url=url, title=f"{owner}/{repo} releases", content_text=text)

    def _commits(self, owner: str, repo: str, url: str, max_chars: int) -> CrawledDocument:
        try:
            data = self._api_get(f"/repos/{owner}/{repo}/commits?per_page=20")
            assert isinstance(data, list)
            lines = [
                f"{c['sha'][:7]}: {c['commit']['message'][:150]}"
                for c in data
                if isinstance(c, dict)
            ]
            text = "\n".join(lines)[:max_chars]
        except Exception as exc:
            text = f"[GitHub commits fetch error: {exc}]"
        return CrawledDocument(url=url, title=f"{owner}/{repo} commits", content_text=text)
