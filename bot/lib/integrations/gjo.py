"""Good Judgment Open (GJO) — superforecaster aggregated probabilities.

GJO participants are selected by track record; their aggregate probability
is systematically more accurate than naive crowd forecasting.
When GJO = 35% vs Polymarket = 55%, that is a strong mispricing signal.

No API key required. Uses public question list endpoint.
Endpoint: https://www.gjopen.com/questions
"""
from __future__ import annotations

import re
import requests

_BASE = "https://www.gjopen.com"
_QUESTIONS_URL = f"{_BASE}/questions"

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


def _parse_html_questions(html: str) -> list[dict]:
    """Extract questions and community probabilities from GJO questions page HTML.

    GJO renders each question as:
      <h3 class="mb-0">Question title text</h3>
      ...
      <span ...>42%</span>   (community forecast)
    or as JSON in a <script type="application/json"> tag.
    """
    questions: list[dict] = []

    # Strategy 1: look for embedded JSON (Turbo/React apps often embed initial state)
    json_match = re.search(
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    if json_match:
        try:
            import json  # noqa: PLC0415
            data = json.loads(json_match.group(1))
            items = (
                data.get("questions")
                or data.get("challenges")
                or data.get("forecasts")
                or []
            )
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("name") or item.get("title") or item.get("question") or ""
                    prob = (
                        item.get("community_prediction")
                        or item.get("prediction")
                        or item.get("probability")
                    )
                    url = item.get("url") or item.get("path") or ""
                    if title and prob is not None:
                        try:
                            prob_float = float(prob)
                            if prob_float > 1.0:
                                prob_float /= 100.0
                            if 0.0 < prob_float < 1.0:
                                questions.append({
                                    "question": title,
                                    "probability": round(prob_float, 4),
                                    "url": f"{_BASE}{url}" if url.startswith("/") else url,
                                })
                        except (TypeError, ValueError):
                            pass
        except Exception:  # noqa: BLE001
            pass

    if questions:
        return questions

    # Strategy 2: parse HTML structure
    # Find question blocks: title + percentage pairs
    # GJO uses patterns like: question title in <h3>/<h4>/<a class="question-link">
    # and percentages like "Community: 42%" or just "42%" nearby
    title_re = re.compile(
        r'(?:class="[^"]*(?:question|challenge|title)[^"]*"[^>]*>|<h[34][^>]*>)'
        r'\s*<a[^>]*href="([^"]*)"[^>]*>\s*(.*?)\s*</a>',
        re.DOTALL | re.IGNORECASE,
    )
    pct_re = re.compile(r'(\d{1,3}(?:\.\d)?)\s*%')

    for m in title_re.finditer(html):
        url_path = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not title or len(title) < 10:
            continue
        # Look for a probability near this title (within next ~500 chars)
        window = html[m.end(): m.end() + 500]
        pcts = pct_re.findall(window)
        if not pcts:
            continue
        try:
            prob = float(pcts[0]) / 100.0
        except ValueError:
            continue
        if not 0.01 < prob < 0.99:
            continue
        full_url = f"{_BASE}{url_path}" if url_path.startswith("/") else url_path
        questions.append({"question": title, "probability": round(prob, 4), "url": full_url})

    return questions


def fetch_all_questions(timeout: int = 20) -> list[dict]:
    """Fetch open GJO questions with community probability.

    Tries multiple approaches in order:
      1. JSON API endpoint (if available)
      2. HTML page parsing

    Returns list of {question, probability, url} dicts.
    Returns empty list if GJO is unreachable or structure has changed.
    """
    headers = {
        "Accept": "application/json, text/html",
        "User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)",
    }

    # Try JSON API first (undocumented but often works for Rails apps)
    for api_url in [
        f"{_BASE}/api/v1/questions?is_open=true&per_page=200",
        f"{_BASE}/api/v1/challenges?status=open&per_page=200",
    ]:
        try:
            r = requests.get(api_url, headers={"Accept": "application/json"}, timeout=timeout)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                data = r.json()
                items = (
                    data if isinstance(data, list)
                    else data.get("questions") or data.get("challenges") or []
                )
                out = []
                for item in items:
                    title = item.get("name") or item.get("title") or item.get("question", "")
                    prob_raw = (
                        item.get("community_prediction")
                        or item.get("community_weighted_mean")
                        or item.get("prediction")
                    )
                    url = item.get("url") or item.get("path") or f"{_BASE}/questions/{item.get('id', '')}"
                    if not title or prob_raw is None:
                        continue
                    try:
                        prob = float(prob_raw)
                        if prob > 1.0:
                            prob /= 100.0
                        if 0.0 < prob < 1.0:
                            out.append({
                                "question": title,
                                "probability": round(prob, 4),
                                "url": url if url.startswith("http") else f"{_BASE}{url}",
                            })
                    except (TypeError, ValueError):
                        pass
                if out:
                    return out
        except Exception:  # noqa: BLE001
            pass

    # Fall back to HTML parsing of questions page
    all_questions: list[dict] = []
    for page in range(1, 6):  # up to 5 pages
        try:
            r = requests.get(
                _QUESTIONS_URL,
                params={"page": page, "is_open": "true"},
                headers=headers,
                timeout=timeout,
            )
            if r.status_code != 200:
                break
            parsed = _parse_html_questions(r.text)
            if not parsed:
                break
            all_questions.extend(parsed)
            if len(parsed) < 10:
                break  # last page
        except Exception as exc:  # noqa: BLE001
            print(f"[GJO] page {page} error: {exc}")
            break

    return all_questions


def find_match(
    question: str,
    questions: list[dict],
    min_jaccard: float = 0.38,
) -> dict | None:
    """Find best-matching GJO question for a Polymarket market question.

    Raised from 0.25→0.38 (2026-05-27) to reduce false matches.  GJO
    phrasing is verbose but the previous threshold was too permissive.
    Returns {question, probability, url, match_score} or None.
    """
    q_tokens = _tokenize(question)
    if not q_tokens:
        return None
    best: dict | None = None
    best_score = 0.0
    for q in questions:
        title = q.get("question", "")
        if not title:
            continue
        score = _jaccard(q_tokens, _tokenize(title))
        if score > best_score:
            best_score = score
            best = q
    if best is None or best_score < min_jaccard:
        return None
    return {**best, "match_score": round(best_score, 3)}
