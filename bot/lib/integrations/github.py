"""GitHub REST API — anonymous reads (60 req/hour limit).

Set GITHUB_TOKEN env var to get 5000 req/h. Token can be a fine-grained PAT
with public_repo scope only.
Docs: https://docs.github.com/en/rest
"""
from __future__ import annotations

import os

from lib.integrations import _safe_get

GH = "https://api.github.com"


def _auth_headers() -> dict:
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        return {"Authorization": f"Bearer {tok}",
                "X-GitHub-Api-Version": "2022-11-28"}
    return {"X-GitHub-Api-Version": "2022-11-28"}


async def repo_overview(client, owner_repo: str) -> dict:
    """Basic info on a public repo: stars, forks, last update, default branch."""
    if "/" not in owner_repo:
        return {"error": "owner_repo must be 'owner/repo'"}
    r = await _safe_get(client, f"{GH}/repos/{owner_repo}", headers=_auth_headers())
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"]}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}"}
    return {
        "full_name": d.get("full_name"),
        "description": d.get("description"),
        "stars": d.get("stargazers_count"),
        "forks": d.get("forks_count"),
        "watchers": d.get("subscribers_count"),
        "open_issues": d.get("open_issues_count"),
        "default_branch": d.get("default_branch"),
        "updated_at": d.get("updated_at"),
        "pushed_at": d.get("pushed_at"),
        "language": d.get("language"),
        "topics": d.get("topics"),
    }


async def recent_releases(client, owner_repo: str, *, limit: int = 5) -> dict:
    """List recent releases (tags + names + dates)."""
    if "/" not in owner_repo:
        return {"error": "owner_repo must be 'owner/repo'"}
    r = await _safe_get(client, f"{GH}/repos/{owner_repo}/releases",
                       params={"per_page": max(1, min(30, limit))},
                       headers=_auth_headers())
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "releases": []}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}", "releases": []}
    out = []
    for rel in (d if isinstance(d, list) else []):
        out.append({
            "tag": rel.get("tag_name"),
            "name": rel.get("name"),
            "published_at": rel.get("published_at"),
            "prerelease": rel.get("prerelease"),
            "draft": rel.get("draft"),
            "url": rel.get("html_url"),
        })
    return {"count": len(out), "releases": out}


async def recent_commits(client, owner_repo: str, *, days_back: int = 7,
                          limit: int = 20) -> dict:
    """Recent commits on default branch."""
    if "/" not in owner_repo:
        return {"error": "owner_repo must be 'owner/repo'"}
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    r = await _safe_get(client, f"{GH}/repos/{owner_repo}/commits",
                       params={"per_page": max(1, min(100, limit)), "since": since},
                       headers=_auth_headers())
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "commits": []}
    try:
        d = r.json()
    except Exception as e:
        return {"error": f"parse: {e}", "commits": []}
    out = []
    for c in (d if isinstance(d, list) else []):
        commit = c.get("commit") or {}
        out.append({
            "sha": c.get("sha", "")[:8],
            "message": (commit.get("message") or "").split("\n")[0][:100],
            "author": (commit.get("author") or {}).get("name"),
            "date": (commit.get("author") or {}).get("date"),
            "url": c.get("html_url"),
        })
    return {"count": len(out), "since": since, "commits": out,
            "authenticated": bool(os.getenv("GITHUB_TOKEN"))}
