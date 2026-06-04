"""Manifold Markets public API integration — no auth, no key required.

Fetches open binary markets and matches them against Polymarket questions
by Jaccard token overlap to detect price divergence.

API docs: https://docs.manifold.markets/api#get-v0markets
"""
from __future__ import annotations

import re

import httpx

MANIFOLD_API = "https://api.manifold.markets/v0/markets"
_PAGE_LIMIT = 1000  # API max per request

_STOP = frozenset({
    "will", "the", "be", "a", "an", "of", "in", "on", "by", "to", "for",
    "is", "are", "was", "were", "has", "have", "had", "at", "from", "that",
    "this", "it", "its", "with", "or", "and", "not", "no", "yes",
    "next", "new", "first", "last", "win", "won", "lose", "lost",
    "get", "gets", "got", "2024", "2025", "2026", "2027",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
})


def _tokenize(text: str) -> frozenset[str]:
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return frozenset(w for w in words if w not in _STOP and len(w) > 2)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def fetch_all_markets(timeout: int = 25) -> list[dict]:
    """Return list of dicts with keys: question, probability, url, id.

    Fetches open, unresolved BINARY markets sorted by recent activity.
    Returns [] on any error.
    """
    try:
        r = httpx.get(
            MANIFOLD_API,
            params={
                "limit": _PAGE_LIMIT,
                "sort": "score",
                "filter": "open",
                "contractType": "BINARY",
            },
            timeout=timeout,
            headers={"User-Agent": "Signal/1.0 (prediction-market research)"},
            follow_redirects=True,
        )
        if r.status_code != 200:
            return []
        raw = r.json()
        if not isinstance(raw, list):
            return []
        result: list[dict] = []
        for m in raw:
            if m.get("isResolved"):
                continue
            prob = m.get("probability")
            if prob is None:
                continue
            prob = float(prob)
            if not (0.02 <= prob <= 0.98):
                continue  # fully-resolved or near-certain / boring
            result.append({
                "question": m.get("question") or "",
                "probability": round(prob, 3),
                "url": m.get("url") or "",
                "id": m.get("id") or "",
            })
        return result
    except Exception:  # noqa: BLE001
        return []


def find_match(
    question: str,
    markets: list[dict],
    min_jaccard: float = 0.40,
) -> dict | None:
    """Return the best Manifold market matching *question*, or None.

    Raised from 0.28→0.40 (2026-05-27) to reduce false-match divergence
    signals.  Manifold questions are verbose but 0.28 produced too many
    spurious price-gap alerts.
    """
    q_tokens = _tokenize(question)
    best: dict | None = None
    best_score = 0.0
    for m in markets:
        score = _jaccard(q_tokens, _tokenize(m["question"]))
        if score > best_score:
            best_score = score
            best = m
    if best is not None and best_score >= min_jaccard:
        return {**best, "match_score": round(best_score, 3)}
    return None
