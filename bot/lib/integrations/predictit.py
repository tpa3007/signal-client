"""PredictIt public API integration — no auth, no key required.

Fetches all active US political markets and matches them against Polymarket
questions by Jaccard token overlap to detect price divergence.

API docs: https://www.predictit.org/api/marketdata/all/
"""
from __future__ import annotations

import re

import httpx

PREDICTIT_API = "https://www.predictit.org/api/marketdata/all/"

# Tokens that carry no discriminative value for matching
_STOP = frozenset({
    "will", "the", "be", "a", "an", "of", "in", "on", "by", "to", "for",
    "is", "are", "was", "were", "has", "have", "had", "at", "from", "that",
    "this", "it", "its", "with", "or", "and", "not", "no", "yes",
    "next", "new", "first", "last", "win", "won", "lose", "lost",
    "get", "gets", "got", "2024", "2025", "2026", "2027",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
})

_NON_DISCRIMINATING = frozenset({
    "election", "presidential", "president", "governor", "senate", "house",
    "primary", "nominee", "nomination", "round", "republican", "democratic",
    "party", "candidate", "candidates", "market", "contract",
})


def _tokenize(text: str) -> frozenset[str]:
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return frozenset(w for w in words if w not in _STOP and len(w) > 2)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _anchor_tokens(tokens: frozenset[str]) -> frozenset[str]:
    """Tokens that are specific enough to protect against false matches.

    PredictIt has many similarly worded election contracts. Plain Jaccard can
    match "first round presidential election" while missing that the candidate
    or country differs. Anchors are longer non-generic tokens such as surnames,
    countries, states, districts, or named institutions.
    """
    return frozenset(
        t for t in tokens
        if len(t) >= 5 and t not in _NON_DISCRIMINATING
    )


def fetch_all_markets(timeout: int = 15) -> list[dict]:
    """Return list of dicts with keys: name, yes_price, url, market_id.

    For multi-contract markets (e.g. "Who will be president?") each contract
    becomes its own entry with its name appended to the market name.
    Binary single-contract markets (contract name == "Yes") are kept as-is.

    Returns [] on any error so callers can degrade gracefully.
    """
    try:
        r = httpx.get(
            PREDICTIT_API,
            timeout=timeout,
            headers={"User-Agent": "Signal/1.0 (prediction-market research)"},
            follow_redirects=True,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        markets = data.get("markets") or []
        result: list[dict] = []
        for m in markets:
            name: str = m.get("name") or ""
            url: str = m.get("url") or ""
            mid = m.get("id")
            contracts = m.get("contracts") or []

            # Determine effective YES price for each contract
            for c in contracts:
                cname: str = c.get("name") or ""
                # bestBuyYesCost is the current ask for YES shares (0–1 range)
                price = c.get("bestBuyYesCost") or c.get("lastTradePrice")
                if price is None:
                    continue
                price = float(price)
                if not (0.01 <= price <= 0.99):
                    continue  # delisted / dormant contract

                # For a binary market the single contract is named "Yes" —
                # use the market name alone; otherwise append the contract label.
                if cname.lower() in ("yes", ""):
                    full_name = name
                else:
                    full_name = f"{name} — {cname}"

                result.append({
                    "name": full_name,
                    "yes_price": round(price, 3),
                    "url": url,
                    "market_id": mid,
                    "contract_id": c.get("id"),
                })
        return result
    except Exception:  # noqa: BLE001
        return []


def find_match(
    question: str,
    markets: list[dict],
    min_jaccard: float = 0.45,
) -> dict | None:
    """Return the best PredictIt market matching *question*, or None.

    Uses Jaccard token overlap after stop-word removal.
    min_jaccard=0.45 plus anchor-token overlap keeps only reasonably confident
    matches and rejects generic election-wording overlaps.
    """
    q_tokens = _tokenize(question)
    q_anchors = _anchor_tokens(q_tokens)
    best: dict | None = None
    best_score = 0.0
    for m in markets:
        m_tokens = _tokenize(m["name"])
        shared_anchors = q_anchors & _anchor_tokens(m_tokens)
        if q_anchors and not shared_anchors:
            continue
        score = _jaccard(q_tokens, m_tokens)
        # Require at least two specific overlaps for generic election wording.
        if len(q_anchors) >= 2 and len(shared_anchors) < 2:
            score *= 0.5
        if score > best_score:
            best_score = score
            best = m
    if best is not None and best_score >= min_jaccard:
        return {**best, "match_score": round(best_score, 3)}
    return None
