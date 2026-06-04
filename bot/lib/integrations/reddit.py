"""Reddit access for local community-sentiment intelligence.

Reddit's high-volume commercial Data API is paywalled, but a personal "script"
app is still FREE (100 QPM) and is all we need. This module tries, in order:

  1. OAuth (script app: REDDIT_CLIENT_ID/SECRET + REDDIT_USERNAME/PASSWORD) —
     works from ANY IP, including cloud. The reliable path.
  2. Unauthenticated JSON with a browser UA — works from residential IPs
     (the operator's own machine), 403 from datacenter/cloud IPs.
  3. RSS + public redlib/redirect mirrors — last-ditch fallbacks.

Setup for OAuth (2 min, free):
  1. https://www.reddit.com/prefs/apps  →  "create another app"  →  type "script".
  2. name=anything, redirect uri=http://localhost:8080
  3. Put in .env:
       REDDIT_CLIENT_ID=<the id under the app name>
       REDDIT_CLIENT_SECRET=<the secret>
       REDDIT_USERNAME=<your reddit username>
       REDDIT_PASSWORD=<your reddit password>
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

_UA = ("web:signal-research:v1.0 (by /u/{user})")
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_MIRRORS = [
    "https://redlib.catsarch.com", "https://safe.reddit.farm",
    "https://red.ngn.tf", "https://libreddit.kavin.rocks",
]

_token_cache: dict[str, Any] = {"token": None, "exp": 0}


def _ua() -> str:
    return _UA.format(user=os.getenv("REDDIT_USERNAME", "signal"))


# ── OAuth (script app, password grant) ─────────────────────────────────────

def _get_token() -> str | None:
    """OAuth token. Prefers the no-password installed_client grant (read-only,
    only REDDIT_CLIENT_ID needed). Falls back to password grant if a username/
    password is configured (slightly higher rate limit)."""
    cid = os.getenv("REDDIT_CLIENT_ID", "").strip()
    if not cid:
        return None
    if _token_cache["token"] and time.time() < _token_cache["exp"] - 60:
        return _token_cache["token"]
    import base64
    secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user = os.getenv("REDDIT_USERNAME", "").strip()
    pw = os.getenv("REDDIT_PASSWORD", "").strip()

    if user and pw:
        body = {"grant_type": "password", "username": user, "password": pw}
    else:
        # installed_client: read-only, no Reddit login required
        dev = os.getenv("REDDIT_DEVICE_ID", "").strip() or ("signal-" + "0" * 30)[:30]
        body = {"grant_type": "https://oauth.reddit.com/grants/installed_client",
                "device_id": dev}
    try:
        basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        req = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=urllib.parse.urlencode(body).encode(),
            headers={"Authorization": f"Basic {basic}", "User-Agent": _ua()})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read())
        tok = d.get("access_token")
        if tok:
            _token_cache["token"] = tok
            _token_cache["exp"] = time.time() + int(d.get("expires_in", 3600))
            return tok
    except Exception:  # noqa: BLE001
        return None
    return None


def _oauth_get(path: str, params: dict) -> Any:
    tok = _get_token()
    if not tok:
        return None
    url = f"https://oauth.reddit.com{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}", "User-Agent": _ua()})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


# ── Unauthenticated / mirror fallbacks ─────────────────────────────────────

def _plain_get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA, "Accept": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def _normalize(children: list) -> list[dict]:
    out = []
    for c in children or []:
        d = c.get("data", {}) if isinstance(c, dict) else {}
        out.append({
            "title": d.get("title") or "",
            "body": (d.get("selftext") or d.get("body") or "")[:600],
            "score": d.get("score", 0),
            "num_comments": d.get("num_comments", 0),
            "created": d.get("created_utc"),
            "permalink": d.get("permalink", ""),
            "subreddit": d.get("subreddit", ""),
        })
    return out


def search(subreddit: str, query: str, *, sort: str = "new", limit: int = 15) -> list[dict]:
    """Search a subreddit. Tries OAuth → unauth JSON → mirrors."""
    params = {"q": query, "restrict_sr": "1", "sort": sort, "limit": str(limit)}
    # 1. OAuth
    try:
        d = _oauth_get(f"/r/{subreddit}/search", params)
        if d:
            return _normalize(d.get("data", {}).get("children", []))
    except Exception:  # noqa: BLE001
        pass
    # 2. Unauth JSON (residential IP)
    try:
        d = _plain_get(f"https://www.reddit.com/r/{subreddit}/search.json?{urllib.parse.urlencode(params)}")
        return _normalize(d.get("data", {}).get("children", []))
    except Exception:  # noqa: BLE001
        pass
    # 3. Mirrors
    for base in _MIRRORS:
        try:
            d = _plain_get(f"{base}/r/{subreddit}/search.json?{urllib.parse.urlencode(params)}")
            kids = d.get("data", {}).get("children", []) if isinstance(d, dict) else []
            if kids:
                return _normalize(kids)
        except Exception:  # noqa: BLE001
            continue
    return []


def hot(subreddit: str, *, limit: int = 15) -> list[dict]:
    try:
        d = _oauth_get(f"/r/{subreddit}/hot", {"limit": str(limit)})
        if d:
            return _normalize(d.get("data", {}).get("children", []))
    except Exception:  # noqa: BLE001
        pass
    try:
        d = _plain_get(f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}")
        return _normalize(d.get("data", {}).get("children", []))
    except Exception:  # noqa: BLE001
        return []


def available() -> dict:
    """Report which access path is live (for diagnostics)."""
    return {
        "oauth_configured": bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_PASSWORD")),
        "oauth_token_ok": bool(_get_token()),
    }


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("access:", available())
    sub = sys.argv[1] if len(sys.argv) > 1 else "PERU"
    q = sys.argv[2] if len(sys.argv) > 2 else "Keiko Sanchez segunda vuelta"
    res = search(sub, q, limit=10)
    print(f"r/{sub} '{q}': {len(res)} posts")
    for r in res[:10]:
        print(f"  [{r['score']}^ {r['num_comments']}c] {r['title'][:90]}")
