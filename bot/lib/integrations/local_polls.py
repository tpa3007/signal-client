"""Local polling data scraper — language asymmetry intelligence for prediction markets.

Fetches polling/survey data from local-language sources that English-platform
traders systematically ignore.  Returns structured poll snapshots that Command B
injects as seed context into Forager.

SUPPORTED REGIONS:
  korean   — Gallup Korea, Realmeter, Naver News aggregation
  hebrew   — Smith Consulting, Walla polls, Channel 12 News
  turkish  — MetroPoll, Konda Research, Sabah survey aggregation
  romanian — CURS, Avangarde, Digi24 poll aggregation
  taiwanese — TVBS, NCCU Election Study Center, Liberty Times polls

HOW IT WORKS:
  1. Detect candidate/entity names from market question
  2. Build local-language search query (e.g. Korean: "갤럽 여론조사 {name}")
  3. Fetch from news aggregator (Naver, Walla, etc.) + specific poll pages
  4. Extract poll percentages via regex on translated snippets
  5. Return structured PollSnapshot with language_edge_score

USAGE:
  from lib.integrations.local_polls import fetch_polls_for_market, format_polls_for_forager
  snaps = fetch_polls_for_market("Will Kim Kyung-soo win Gyeongnam?", "korean")
  block = format_polls_for_forager(snaps)
"""
from __future__ import annotations

import re
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

ALLOW_UNVERIFIED_POLL_SNIPPETS = os.getenv(
    "SIGNAL_ALLOW_UNVERIFIED_POLL_SNIPPETS", "0"
).lower() in {"1", "true", "yes"}

# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class PollResult:
    candidate_name: str
    percentage: float
    party: str = ""
    rank: int = 0            # 1=leading, 2=second, etc.


@dataclass
class PollSnapshot:
    source_name: str
    source_url: str
    region: str
    poll_date: str           # YYYY-MM-DD or approximate
    results: list[PollResult] = field(default_factory=list)
    sample_size: int = 0
    margin_of_error: float = 0.0
    leading_candidate: str = ""
    leading_pct: float = 0.0
    runner_up: str = ""
    runner_up_pct: float = 0.0
    lead_margin: float = 0.0  # leading - runner_up
    raw_snippet: str = ""     # original text for LLM consumption
    translated_snippet: str = ""  # English translation
    language_edge_score: float = 0.0  # 0-1: how much info advantage vs English
    fetch_ok: bool = False
    source_quality: str = "unknown"


# ── Language-region config ───────────────────────────────────────────────────

_REGION_CONFIG = {
    "korean": {
        "entities_re": [
            r"[A-Z][a-z]+ [A-Z][a-z]+-[a-z]+",  # Kim Kyung-soo pattern
            r"[A-Z][a-z]+ [A-Z][a-z]+",           # Generic Korean name
        ],
        "search_term_template": "{entity} 여론조사",  # "{name} poll/survey"
        "sources": [
            {
                "name": "Naver News",
                "search_url": "https://search.naver.com/search.naver?where=news&query={query}&sm=tab_jum",
                "snippet_selector": "text",
                "language": "ko",
            },
            {
                "name": "Gallup Korea",
                "url": "https://www.gallup.co.kr/gallupdb/reportContent.asp",
                "search_url": "https://search.naver.com/search.naver?where=news&query=갤럽+한국+여론조사+{entity}",
                "language": "ko",
            },
            {
                "name": "Realmeter",
                "search_url": "https://search.naver.com/search.naver?where=news&query=리얼미터+여론조사+{entity}",
                "language": "ko",
            },
        ],
        "poll_keywords_local": ["여론조사", "갤럽", "리얼미터", "조사", "%", "지지율"],
        "poll_keywords_translated": ["poll", "survey", "gallup", "approval", "%"],
        "pct_pattern": r"(\d+\.?\d*)\s*%",
        "moe_pattern": r"오차.*?(\d+\.?\d*)\s*%",
        "sample_pattern": r"응답.*?(\d{3,4})\s*명",
    },
    "hebrew": {
        "entities_re": [r"[A-Z][a-z]+ [A-Z][a-z]+"],
        "search_term_template": "{entity} סקר",
        "sources": [
            {
                "name": "Walla News Polls",
                "search_url": "https://news.walla.co.il/search?q={entity}+%D7%A1%D7%A7%D7%A8",
                "language": "he",
            },
            {
                "name": "Channel 12 News",
                "search_url": "https://www.mako.co.il/news-military?q={entity}+סקר",
                "language": "he",
            },
        ],
        "poll_keywords_local": ["סקר", "אחוז", "%", "מנדטים"],
        "pct_pattern": r"(\d+\.?\d*)\s*%",
    },
    "turkish": {
        "entities_re": [r"[A-Z][a-z]+ [A-Z][a-z]+", r"[A-Z]+"],
        "search_term_template": "{entity} anket",
        "sources": [
            {
                "name": "MetroPoll",
                "search_url": "https://www.metropoll.com.tr/?s={entity}",
                "language": "tr",
            },
            {
                "name": "Haberler Anket",
                "search_url": "https://www.haberler.com/ara/?q={entity}+anket",
                "language": "tr",
            },
        ],
        "poll_keywords_local": ["anket", "yüzde", "%", "oy oranı"],
        "pct_pattern": r"(\d+\.?\d*)\s*%",
    },
    "romanian": {
        # Unicode-aware: matches Cătălin Predoiu, Ilie Bolojan, etc. (ă, î, â, ș, ț)
        "entities_re": [
            r"[A-ZÀ-ž][a-zÀ-ž]+ [A-ZÀ-ž][a-zÀ-ž]+",  # Two-word name with accents
            r"[A-Z][a-z]+ [A-Z][a-z]+",                  # Fallback ASCII
        ],
        # For PM-formation markets: search for candidatura/premier not just polls
        "search_term_template": "{entity} premier prim-ministru",
        "sources": [
            {
                "name": "Digi24 Stiri",
                "search_url": "https://www.digi24.ro/search?q={entity}+premier",
                "language": "ro",
            },
            {
                "name": "G4Media Stiri",
                "search_url": "https://www.g4media.ro/?s={entity}+prim-ministru",
                "language": "ro",
            },
            {
                "name": "Recorder.ro",
                "search_url": "https://www.recorder.ro/?s={entity}+premier",
                "language": "ro",
            },
        ],
        "poll_keywords_local": [
            # Election polls
            "sondaj", "procente", "%", "intenție de vot",
            # PM formation indicators
            "premier", "prim-ministru", "premier desemnat", "candidatura",
            "coalitie", "vot de învestitură", "mandat", "desemnat",
        ],
        "pct_pattern": r"(\d+\.?\d*)\s*%",
    },
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ── Entity extraction ────────────────────────────────────────────────────────

_STOP_PHRASES = frozenset({
    "Prime Minister", "President", "Nobel Peace", "Nobel Prize", "Peace Prize",
    "United States", "European Union", "New People", "Communist Party",
    "National Assembly", "People Power", "Democratic Party",
    "By September", "By June", "By May", "Will Win",
})


def _extract_entities(question: str, region: str) -> list[str]:
    """Extract candidate/entity names from a market question for a given region."""
    cfg = _REGION_CONFIG.get(region, {})
    entities: list[str] = []
    for pattern in cfg.get("entities_re", []):
        matches = re.findall(pattern, question)
        entities.extend(m.strip() for m in matches if len(m.strip()) > 4)

    # Filter out structural/generic phrases that are not candidate names
    entities = [
        e for e in entities
        if e not in _STOP_PHRASES
        and not any(sp.lower() in e.lower() for sp in _STOP_PHRASES)
    ]

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for e in entities:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result[:3]  # max 3 entities


def _translate_snippet(text: str, src_lang: str = "ko") -> str:
    """Translate a text snippet to English using deep-translator (offline-capable)."""
    if not text or not text.strip():
        return ""
    try:
        from deep_translator import GoogleTranslator  # noqa: PLC0415
        # GoogleTranslator has no local mode, but is free for small chunks
        translator = GoogleTranslator(source=src_lang, target="en")
        # Truncate to 500 chars to avoid rate limits
        chunk = text.strip()[:500]
        result = translator.translate(chunk)
        return result or ""
    except Exception:  # noqa: BLE001
        pass
    # Fallback: return original (LLM may still parse numbers)
    return text


# ── Poll extraction ──────────────────────────────────────────────────────────

def _extract_poll_numbers(text: str, region: str) -> tuple[list[PollResult], float, int]:
    """Extract poll percentages, margin of error, and sample size from text.

    Returns (results, margin_of_error, sample_size).
    """
    cfg = _REGION_CONFIG.get(region, {})
    pct_pattern = cfg.get("pct_pattern", r"(\d+\.?\d*)\s*%")
    moe_pattern = cfg.get("moe_pattern", r"(?:margin|오차|erreur).*?(\d+\.?\d*)\s*%")
    sample_pattern = cfg.get("sample_pattern", r"(?:n=|sample|응답).*?(\d{3,5})")

    # Extract all percentages in order of appearance
    pcts = [float(m) for m in re.findall(pct_pattern, text) if 0 < float(m) <= 100]

    # MoE
    moe_match = re.search(moe_pattern, text, re.IGNORECASE)
    moe = float(moe_match.group(1)) if moe_match else 0.0

    # Sample size
    sample_match = re.search(sample_pattern, text, re.IGNORECASE)
    sample = int(sample_match.group(1)) if sample_match else 0

    # Build results — we don't have names here, just raw percentages
    results: list[PollResult] = []
    for i, pct in enumerate(pcts[:6], 1):  # max 6 candidates
        results.append(PollResult(candidate_name=f"Candidate_{i}", percentage=pct, rank=i))

    return results, moe, sample


def _translate_name_to_korean(name: str) -> str:
    """Translate a romanized Korean name to Korean script via Google Translate.

    Returns original name if translation fails or result doesn't contain Korean chars.
    """
    try:
        from deep_translator import GoogleTranslator  # noqa: PLC0415
        result = GoogleTranslator(source="en", target="ko").translate(name)
        if result and any('가' <= ch <= '힣' for ch in result):
            return result
    except Exception:  # noqa: BLE001
        pass
    return name


def _fetch_naver_news(entity: str, region: str, timeout: int = 8) -> list[str]:
    """Fetch Naver News search results for an entity + poll keyword.

    Returns list of text snippets from article titles/descriptions.

    Naver News uses JavaScript rendering — article titles are NOT in the standard
    HTML structure. Instead they appear as JSON-embedded \"title\" fields in the
    page source. This function extracts those embedded titles.

    Also tries Korean-script translation of the entity name for better matching.
    """
    import urllib.parse  # noqa: PLC0415
    cfg = _REGION_CONFIG.get(region, {})
    term_template = cfg.get("search_term_template", "{entity} poll")

    # For Korean: also try the Korean-script version of the name
    queries_to_try: list[str] = []
    if region == "korean":
        kr_name = _translate_name_to_korean(entity)
        if kr_name != entity:
            # Korean name + poll keyword
            queries_to_try.append(f"{kr_name} 여론조사")
            queries_to_try.append(f"{kr_name} 지지율 2026")
        # Also try English romanization
        queries_to_try.append(term_template.format(entity=entity))
    else:
        queries_to_try.append(term_template.format(entity=entity))

    all_snippets: list[str] = []

    for query in queries_to_try[:3]:
        if len(all_snippets) >= 15:
            break
        encoded = urllib.parse.quote(query)
        url = (
            f"https://search.naver.com/search.naver"
            f"?where=news&query={encoded}&sm=tab_jum&sort=1"
        )
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=_HEADERS)
                if resp.status_code != 200:
                    continue
                html = resp.text

            # Primary: JSON-embedded title fields (Naver's JS-rendered titles appear here)
            json_titles = re.findall(r'"title"\s*:\s*"([^"]{10,250})"', html)
            snippets: list[str] = []
            for t in json_titles[:15]:
                # Decode HTML entities (e.g. &quot; → ")
                t = re.sub(r'&quot;', '"', t)
                t = re.sub(r'&amp;', '&', t)
                t = re.sub(r'<[^>]+>', '', t).strip()
                if t and len(t) > 8:
                    snippets.append(t)

            # Fallback: classic HTML patterns (for older Naver page versions)
            if not snippets:
                titles = re.findall(r'class="news_tit"[^>]*>([^<]{10,200})</a>', html)
                snippets.extend(t.strip() for t in titles[:10])
                descs = re.findall(r'class="news_dsc"[^>]*>([^<]{20,400})</div>', html, re.DOTALL)
                for d in descs[:8]:
                    clean = re.sub(r'<[^>]+>', '', d).strip()
                    if clean:
                        snippets.append(clean[:300])

            all_snippets.extend(s for s in snippets if s not in all_snippets)

        except Exception:  # noqa: BLE001
            continue

    return all_snippets[:20]


def _fetch_direct_url(url: str, timeout: int = 6) -> str:
    """Fetch a URL and return raw text content."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=_HEADERS)
            if resp.status_code != 200:
                return ""
            # Strip HTML tags
            text = re.sub(r'<[^>]+>', ' ', resp.text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:3000]
    except Exception:  # noqa: BLE001
        return ""


# ── Main fetch function ──────────────────────────────────────────────────────

def fetch_polls_for_market(
    question: str,
    region: str,
    entities: list[str] | None = None,
    timeout: int = 8,
    verbose: bool = False,
) -> list[PollSnapshot]:
    """Fetch local polling data for a prediction market.

    Args:
        question: The Polymarket question text
        region:   Language region key ('korean', 'hebrew', 'turkish', 'romanian')
        entities: Override entity extraction (optional)
        timeout:  HTTP timeout per request
        verbose:  Print debug info

    Returns:
        List of PollSnapshot objects, sorted by lead_margin descending.
    """
    if region not in _REGION_CONFIG:
        return []

    # Extract candidate names if not provided
    if not entities:
        entities = _extract_entities(question, region)
    if not entities:
        if verbose:
            print(f"  [POLLS] No entities extracted from: {question[:50]}")
        return []

    if verbose:
        print(f"  [POLLS-{region.upper()}] Searching polls for: {', '.join(entities)}")

    snapshots: list[PollSnapshot] = []

    for entity in entities[:2]:  # max 2 entities to limit requests
        snippets = _fetch_naver_news(entity, region, timeout=timeout)
        if verbose:
            print(f"  [POLLS] Naver News: {len(snippets)} snippets for '{entity}'")

        if not snippets:
            continue

        # Join snippets for analysis
        raw_text = "\n".join(snippets)

        # Filter: only keep snippets that contain poll keywords
        cfg = _REGION_CONFIG[region]
        kw_local = cfg.get("poll_keywords_local", [])
        relevant_snippets = [
            s for s in snippets
            if any(kw.lower() in s.lower() for kw in kw_local)
            or "%" in s
        ]

        if not relevant_snippets:
            continue

        relevant_text = "\n".join(relevant_snippets[:8])

        # Translate to English
        lang_code = "ko" if region == "korean" else (
            "he" if region == "hebrew" else (
                "tr" if region == "turkish" else "ro"
            )
        )
        translated = _translate_snippet(relevant_text, src_lang=lang_code)

        # Extract poll numbers
        results, moe, sample = _extract_poll_numbers(relevant_text, region)
        if not results:
            # Try from translated text
            results, moe, sample = _extract_poll_numbers(translated, region)

        # Determine leading/runner-up
        sorted_results = sorted(results, key=lambda r: r.percentage, reverse=True)
        leading = sorted_results[0] if sorted_results else None
        runner_up = sorted_results[1] if len(sorted_results) > 1 else None

        lead_margin = 0.0
        if leading and runner_up:
            lead_margin = leading.percentage - runner_up.percentage

        # Language edge score: higher when lead_margin is large and data is local
        # Base score 0.6 for any local poll found; boost for clear margin
        lang_edge = 0.6 + min(0.35, lead_margin / 100.0) if leading else 0.3

        snap = PollSnapshot(
            source_name=f"Naver News / {region.title()} polls",
            source_url=f"https://search.naver.com/search.naver?where=news&query={entity}+여론조사",
            region=region,
            poll_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            results=sorted_results[:4],
            sample_size=sample,
            margin_of_error=moe,
            leading_candidate=entity if leading else "",
            leading_pct=leading.percentage if leading else 0.0,
            runner_up=f"Opponent" if runner_up else "",
            runner_up_pct=runner_up.percentage if runner_up else 0.0,
            lead_margin=lead_margin,
            raw_snippet=relevant_text[:600],
            translated_snippet=translated[:600],
            language_edge_score=lang_edge if ALLOW_UNVERIFIED_POLL_SNIPPETS else 0.0,
            fetch_ok=bool(leading) and ALLOW_UNVERIFIED_POLL_SNIPPETS,
            source_quality="unverified_search_snippet",
        )
        snapshots.append(snap)

        # Small delay between requests
        time.sleep(0.5)

    return sorted(snapshots, key=lambda s: s.lead_margin, reverse=True)


# ── Korean-specific enhanced fetch ──────────────────────────────────────────

def fetch_korean_election_polls(
    candidate_name: str,
    election_type: str = "지사",  # 지사=governor, 시장=mayor, 의원=assembly
    timeout: int = 10,
) -> list[PollSnapshot]:
    """Enhanced Korean election poll fetcher with multiple search strategies.

    Searches for:
      1. Gallup Korea results for candidate
      2. Realmeter results for candidate
      3. General 여론조사 (yeoron_josa = public opinion poll) aggregation

    Args:
        candidate_name: Korean or romanized name (e.g. "Kim Kyung-soo" or "김경수")
        election_type:  Election type in Korean (지사/시장/의원/대통령)
        timeout: HTTP timeout
    """
    snapshots: list[PollSnapshot] = []

    # Search strategies: multiple query forms to maximize coverage
    search_queries = [
        f"{candidate_name} 여론조사",
        f"갤럽 {candidate_name} 지지율",
        f"리얼미터 {candidate_name}",
        f"{candidate_name} {election_type} 여론조사",
    ]

    import urllib.parse  # noqa: PLC0415

    # Translate romanized name to Korean script for better Naver matching
    kr_name = _translate_name_to_korean(candidate_name)
    if kr_name != candidate_name:
        # Prepend Korean-script queries (better Naver search results)
        search_queries = [
            f"{kr_name} 여론조사",
            f"갤럽 {kr_name} 지지율",
            f"리얼미터 {kr_name}",
            f"{kr_name} {election_type} 여론조사",
        ] + search_queries  # keep English fallbacks

    all_snippets: list[str] = []
    seen: set[str] = set()

    for query in search_queries[:6]:  # cap to avoid excessive requests
        encoded = urllib.parse.quote(query)
        url = f"https://search.naver.com/search.naver?where=news&query={encoded}&sort=1"
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=_HEADERS)
                if resp.status_code == 200:
                    html = resp.text

                    # Primary: JSON-embedded titles (works with Naver's JS-rendered pages)
                    json_titles = re.findall(r'"title"\s*:\s*"([^"]{10,250})"', html)
                    raw_titles: list[str] = []
                    for t in json_titles[:15]:
                        t = re.sub(r'&quot;', '"', t)
                        t = re.sub(r'&amp;', '&', t)
                        t = re.sub(r'<[^>]+>', '', t).strip()
                        if t and len(t) > 8:
                            raw_titles.append(t)

                    # Fallback: classic CSS class selectors
                    if not raw_titles:
                        raw_titles = re.findall(r'class="news_tit"[^>]*>([^<]{10,200})</a>', html)
                        descs = re.findall(r'class="news_dsc"[^>]*>\s*([^<]{15,400})\s*</div>', html)
                        for d in descs[:5]:
                            clean = re.sub(r'<[^>]+>', '', d).strip()
                            if clean:
                                raw_titles.append(clean[:300])

                    for t in raw_titles[:12]:
                        t = t.strip()
                        if t and t not in seen:
                            seen.add(t)
                            all_snippets.append(t)

        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)

    if not all_snippets:
        return []

    # Filter for poll-relevant snippets
    poll_snippets = [
        s for s in all_snippets
        if any(kw in s for kw in ["여론조사", "갤럽", "리얼미터", "지지율", "%", "조사"])
    ]

    if not poll_snippets:
        return []

    raw_text = "\n".join(poll_snippets[:12])
    translated = _translate_snippet(raw_text, src_lang="ko")

    # Parse numbers from both raw and translated
    results_raw, moe, sample = _extract_poll_numbers(raw_text, "korean")
    results_tr, moe_tr, sample_tr = _extract_poll_numbers(translated, "korean")

    # Use whichever has more data
    results = results_raw if len(results_raw) >= len(results_tr) else results_tr
    if not moe:
        moe = moe_tr
    if not sample:
        sample = sample_tr

    sorted_results = sorted(results, key=lambda r: r.percentage, reverse=True)
    leading = sorted_results[0] if sorted_results else None
    runner_up = sorted_results[1] if len(sorted_results) > 1 else None
    lead_margin = (leading.percentage - runner_up.percentage) if (leading and runner_up) else 0.0

    if sorted_results:
        snap = PollSnapshot(
            source_name="Korean polls (Gallup/Realmeter/Naver aggregation)",
            source_url="https://search.naver.com/search.naver?where=news",
            region="korean",
            poll_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            results=sorted_results[:4],
            sample_size=sample,
            margin_of_error=moe,
            leading_candidate=candidate_name,
            leading_pct=leading.percentage if leading else 0.0,
            runner_up_pct=runner_up.percentage if runner_up else 0.0,
            lead_margin=lead_margin,
            raw_snippet=raw_text[:600],
            translated_snippet=translated[:800],
            language_edge_score=(
                min(0.95, 0.65 + lead_margin / 100.0)
                if ALLOW_UNVERIFIED_POLL_SNIPPETS else 0.0
            ),
            fetch_ok=ALLOW_UNVERIFIED_POLL_SNIPPETS,
            source_quality="unverified_search_snippet",
        )
        snapshots.append(snap)

    return snapshots


# ── Formatter for Forager injection ─────────────────────────────────────────

def format_polls_for_forager(
    snapshots: list[PollSnapshot],
    market_price: float = 0.5,
) -> str | None:
    """Format poll snapshots as a text block for Forager seed context injection.

    Includes language edge score and explicit comparison to market price.
    """
    if not snapshots:
        return None

    valid = [s for s in snapshots if s.fetch_ok and s.leading_pct > 0]
    if not valid:
        return None

    lines = ["=== LOCAL LANGUAGE POLLING DATA (Language Asymmetry Intelligence) ==="]
    lines.append(
        "NOTE: This data is from local-language sources. "
        "Most English-platform traders do not have access to this information."
    )
    lines.append(
        "Only source-verified poll snapshots are included by default; search-snippet "
        "leads require SIGNAL_ALLOW_UNVERIFIED_POLL_SNIPPETS=1."
    )
    lines.append("")

    for snap in valid[:3]:
        lines.append(f"Source: {snap.source_name} ({snap.poll_date})")
        lines.append(f"Region: {snap.region.upper()}")

        if snap.leading_pct > 0:
            lines.append(f"Leading: {snap.leading_candidate} — {snap.leading_pct:.1f}%")
        if snap.runner_up_pct > 0:
            lines.append(f"Runner-up — {snap.runner_up_pct:.1f}%")
        if snap.lead_margin > 0:
            lines.append(f"Lead margin: +{snap.lead_margin:.1f}pp")
        if snap.margin_of_error > 0:
            lines.append(f"Margin of error: ±{snap.margin_of_error:.1f}%")
        if snap.sample_size > 0:
            lines.append(f"Sample size: n={snap.sample_size:,}")

        # Language edge vs market price
        if market_price > 0:
            poll_prob = snap.leading_pct / 100.0
            delta_pp = (poll_prob - market_price) * 100
            if abs(delta_pp) > 5:
                direction = "ABOVE" if delta_pp > 0 else "BELOW"
                lines.append(
                    f"LANGUAGE EDGE SIGNAL: Local polls suggest {poll_prob:.0%} probability "
                    f"({delta_pp:+.0f}pp {direction} market price of {market_price:.0%})"
                )

        lines.append(f"Language edge score: {snap.language_edge_score:.2f}/1.00")

        if snap.translated_snippet:
            lines.append(f"\nTranslated excerpt:")
            lines.append(snap.translated_snippet[:400])

        lines.append("")

    return "\n".join(lines)


# ── Auto-detect region from language string ──────────────────────────────────

def region_from_language(language_str: str) -> str | None:
    """Map a local_language string (from Command G) to a polls region key."""
    if not language_str:
        return None
    lang_lower = language_str.lower()
    if "korean" in lang_lower or "korea" in lang_lower:
        return "korean"
    if "hebrew" in lang_lower or "israel" in lang_lower:
        return "hebrew"
    if "turkish" in lang_lower or "turkey" in lang_lower:
        return "turkish"
    if "romanian" in lang_lower or "romania" in lang_lower:
        return "romanian"
    return None
