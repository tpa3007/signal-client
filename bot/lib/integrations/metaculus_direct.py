"""Metaculus direct REST API client.

Replaces the old snippet-parsing approach (which depended on web-search
results returning "X% probability" text) with a structured API call that
returns community_prediction directly as a float.

API:  GET https://www.metaculus.com/api2/questions/?search={query}
Docs: https://www.metaculus.com/api2/

No API key required for public questions. Rate limit: ~60 req/min.
"""
from __future__ import annotations

import re
import requests

_API = "https://www.metaculus.com/api2/questions/"

_STOP = frozenset({
    "will", "the", "be", "a", "an", "of", "in", "on", "by", "to", "for",
    "is", "are", "was", "were", "has", "have", "had", "at", "from", "that",
    "this", "it", "its", "with", "or", "and", "not", "no", "yes",
    "next", "new", "first", "last", "win", "won", "lose", "lost",
    "before", "after", "during", "when", "who", "which", "where", "how",
    "what", "if", "then", "than", "more", "most", "any", "some", "all",
    "get", "got", "may", "might", "could", "would", "should",
    "between", "above", "below", "over", "under",
    "does", "do", "did", "end", "year", "month", "week", "day",
    "least", "many", "much", "their", "they", "about", "into",
    "other", "another", "also", "only", "just", "even", "still",
    "2024", "2025", "2026", "2027",
})


def _tokenize(text: str) -> frozenset[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return frozenset(t for t in tokens if t not in _STOP and len(t) >= 3)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_community_prob(question_data: dict) -> float | None:
    """Extract community probability from a Metaculus API question object.

    Handles multiple API versions and question types.
    Returns None if no meaningful probability is available.
    """
    # Primary field (binary questions)
    cp = question_data.get("community_prediction")
    if isinstance(cp, (int, float)) and 0.0 < cp < 1.0:
        return float(cp)

    # Nested structure: {q: {p2: 0.42}} used by some question types
    if isinstance(cp, dict):
        for key in ("p2", "q2", "median"):
            v = cp.get(key)
            if isinstance(v, (int, float)) and 0.0 < v < 1.0:
                return float(v)

    # prediction_timeseries: take last datapoint
    pts = question_data.get("prediction_timeseries") or []
    if pts:
        last = pts[-1]
        if isinstance(last, dict):
            for key in ("community_prediction", "p2", "q2"):
                v = last.get(key)
                if isinstance(v, (int, float)) and 0.0 < v < 1.0:
                    return float(v)

    return None


def search_question(
    query: str,
    *,
    timeout: int = 15,
    min_jaccard: float = 0.20,
) -> dict | None:
    """Search Metaculus for a question matching query using the direct REST API.

    Returns {metaculus_prob, title, url, question_id, num_forecasters} or None.
    Returns None if no match found or on network error.

    min_jaccard=0.20 is lower than PredictIt because Metaculus questions
    are often phrased very differently from Polymarket while covering the
    same event.  We trade some false-positive risk for recall.
    """
    # Extract 3–4 key tokens for the search query (shorter = better recall)
    tokens = _tokenize(query)
    # Take longest non-numeric tokens (more specific = better search hit)
    sorted_tokens = sorted(tokens, key=len, reverse=True)
    search_str = " ".join(sorted_tokens[:4])
    if not search_str:
        return None

    try:
        r = requests.get(
            _API,
            params={
                "search": search_str,
                "status": "open",
                "type": "forecast",
                "limit": 10,
                "format": "json",
            },
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except Exception as exc:
        print(f"[MetaculusDirect] network error: {exc}")
        return None

    if r.status_code == 429:
        print("[MetaculusDirect] rate limited")
        return None
    if r.status_code != 200:
        return None

    try:
        data = r.json()
    except Exception:
        return None

    results = data.get("results") or []
    if not results:
        return None

    q_tokens = _tokenize(query)
    best: dict | None = None
    best_score = 0.0

    for item in results:
        title = item.get("title") or item.get("question", {}).get("title", "") or ""
        if not title:
            continue
        score = _jaccard(q_tokens, _tokenize(title))
        if score > best_score:
            best_score = score
            best = item

    if best is None or best_score < min_jaccard:
        return None

    prob = _extract_community_prob(best)
    if prob is None:
        return None

    qid = best.get("id", "")
    title = best.get("title") or ""
    url = best.get("url") or f"https://www.metaculus.com/questions/{qid}"
    n_forecasters = best.get("number_of_forecasters") or best.get("forecasters_count") or 0

    return {
        "metaculus_prob": round(prob, 4),
        "title": title,
        "url": url,
        "question_id": qid,
        "num_forecasters": n_forecasters,
        "match_score": round(best_score, 3),
    }
