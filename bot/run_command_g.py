"""Command G v2 — Market Triage: Discover & Rank Research Candidates.

WHAT'S NEW vs v1:
  - discovery_mode=True: scans ALL Polymarket markets, not just politics/tech
  - Dual scan: sorted by volume (popular) + liquidity ascending (neglected)
  - economics_finance + health_pharma verticals now recognized
  - stale_price strategy uses real DB history when available
  - Ollama-powered thesis + kill criteria generation (falls back to templates)
  - Metaculus cross-calibration: flags markets where Metaculus diverges from Polymarket
  - Scoring fixes: young markets no longer penalized, information_asymmetry bonus
  - MAX_PAGES doubled to 16 (8000 markets)
  - Command A auto-populated: no more manual copy-paste

Pipeline:
    **Command G** → triage_report.json → **run_command_a.py (auto)** → Command B → D → C

Output:
  - triage_report.json     — full ranked list
  - forager_queue_auto.py  — ready-to-run Command A queue (no editing needed)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

import httpx

sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")

# Force UTF-8 stdout/stderr on Windows (avoids UnicodeEncodeError for non-ASCII
# characters in market questions, e.g. Romanian ă, Turkish ğ, Arabic letters).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import db; db.init()
import markets as markets_mod
from markets import fetch_active_markets, classify_theme_tags, _market_age_days
from lib.discovery import (
    cheap_optionality,
    compounder_research_candidate,
    low_volume_research_sweetspot,
    stale_price,
)
from lib.discovery_scoring import (
    attention_gap_score,
    liquidity_score,
    spread_score,
    stale_price_score,
    combined_raw_discoverability,
)
from lib.ollama import candidate_research_draft
from tools.workflows import _start_workflow_log, _record_workflow_step, _finish_workflow_log
import config

# ── Configuration ──────────────────────────────────────────────────────────────

TOP_N = int(os.getenv("SIGNAL_COMMAND_G_TOP_N", "15"))  # legacy: candidates in forager_queue_auto.py
# Wide scan output — how many candidates to write to candidates_wide.json for G_rank to read.
# G_rank (run_command_g2.py) reads this file and picks the best 20-25 hidden gems.
CANDIDATES_WIDE_N = int(os.getenv("SIGNAL_COMMAND_G_WIDE_N", "300"))
G_WIDE_STRATIFIED = os.getenv("SIGNAL_COMMAND_G_STRATIFIED_WIDE", "1").lower() not in ("0", "false", "no")
# Gamma API caps at 100 markets per page AND rejects offsets above 10000 (422 at page 101).
# Maximum reachable: 100 pages × 100 items = 10000 per pass, but 422 fires at page 101+.
# We use 98 pages to stay safely within the 9800-item limit per pass.
MAX_PAGES_POPULAR = 98        # pages sorted by volume DESC   (~9800 popular markets)
MAX_PAGES_NEGLECTED = 60      # pages sorted by liquidity ASC (~6000 neglected markets)
SKIP_OPEN_POSITIONS = True
SKIP_RECENTLY_REVIEWED_DAYS = 14   # increased from 7: avoid re-scanning recently touched markets
SKIP_B_RESEARCHED_DAYS = 30        # skip markets B already researched in last 30 days
MIN_SCORE = 5.0               # very low — G_scan is broad; G_rank does the real filtering
MIN_DAYS_TO_RESOLUTION = int(os.getenv("SIGNAL_COMMAND_G_MIN_DAYS", "1"))
MAX_DAYS_TO_RESOLUTION = int(os.getenv("SIGNAL_COMMAND_G_MAX_DAYS", "365"))
MIN_VOLUME_DISCOVERY = float(os.getenv("SIGNAL_COMMAND_G_MIN_VOLUME", "100"))
MIN_VOLUME_NEGLECTED_DISCOVERY = float(os.getenv("SIGNAL_COMMAND_G_NEGLECTED_MIN_VOLUME", "25"))
MIN_YES_PRICE_DISCOVERY = float(os.getenv("SIGNAL_COMMAND_G_MIN_YES_PRICE", "0.005"))
MAX_YES_PRICE_DISCOVERY = float(os.getenv("SIGNAL_COMMAND_G_MAX_YES_PRICE", "0.995"))

FETCH_AUDIT: list[dict] = []

# Information asymmetry bonus — markets where non-English sources give us edge
_INFO_ASYMMETRY_LANGUAGES = {
    # ── HIGH ASYMMETRY (24-72h edge over English press) ────────────────────
    "persian": ["iran", "tehran", "irna", "khamenei", "nuclear", "irgc", "rouhani"],
    "arabic": [
        "saudi", "riyadh", "hamas", "hezbollah", "houthi", "al jazeera", "egypt",
        "sudan", "rsf", "saf", "juba", "khartoum", "darfur",
        "gaza", "rafah", "west bank", "jenin", "ramallah",
        "yemen", "sanaa", "aden", "hodeida",
        "syria", "damascus", "idlib", "aleppo", "hts",
        "libya", "tripoli", "benghazi", "haftar",
        "iraq", "baghdad", "erbil", "pmu",
        "lebanon", "beirut",
    ],
    "russian": ["russia", "ukraine", "putin", "kremlin", "moscow", "nato", "zelenskyy",
                "donbas", "kharkiv", "zaporizhzhia", "crimea", "mariupol"],
    "hebrew": ["israel", "idf", "netanyahu", "knesset", "gaza", "west bank"],
    "chinese": ["china", "beijing", "xi jinping", "taiwan", "pla", "ccp", "hong kong"],
    "korean": [
        # International / North Korea
        "korea", "dprk", "kim jong", "pyongyang", "sanctions",
        # South Korea national geography (city/province names are unambiguously Korean)
        "seoul", "busan", "daegu", "incheon", "gwangju", "daejeon", "ulsan",
        "gyeonggi", "gangwon", "gyeongnam", "gyeongbuk", "jeonnam", "jeonbuk",
        "chungnam", "chungbuk", "jeju", "sejong",
        # South Korean politics
        "people power party", "democratic party of korea",
        "lee jae-myung", "han dong-hun", "yoon suk", "yoon suk-yeol",
        "national assembly", "korean election", "south korean",
    ],
    # ── HIGH ASYMMETRY — new global regions (Telegram is top-1 source) ─────
    "burmese": ["myanmar", "burma", "tatmadaw", "junta", "nug", "sac", "pdf",
                "yangon", "naypyidaw", "shan", "kachin", "karenni"],
    "urdu":    ["pakistan", "islamabad", "imran", "pti", "army", "isi", "karachi",
                "lahore", "nawaz", "sharif", "pml", "judiciary"],
    "dari":    ["afghanistan", "kabul", "taliban", "iec", "helmand", "kandahar",
                "panjshir", "nrf", "isis", "daesh", "isil"],
    "amharic": ["ethiopia", "addis ababa", "tigray", "tplf", "amhara", "oromia",
                "abiy", "fano", "olf", "eritrea", "somalia"],
    "armenian":   ["armenia", "yerevan", "pashinyan", "karabakh", "artsakh",
                   "azerbaijan", "aliyev", "nagorno"],
    "azerbaijani":["azerbaijan", "baku", "aliyev", "karabakh", "zangezur",
                   "armenia", "pashinyan"],
    # Keep this cluster strict. Broad tokens like "gdp", "nato", "eu", or
    # "russian" create false language-arbitrage matches on generic macro/NATO
    # markets that have no Georgia-specific local-source edge.
    "georgian":   ["georgia", "tbilisi", "saakashvili", "ivanishvili",
                   "abkhazia", "ossetia"],
    # ── MODERATE ASYMMETRY — Sahel/Africa francophone (30-48h edge) ─────────
    "french (africa)": ["mali", "burkina", "niger", "junta", "wagner", "sahel",
                        "senegal", "dakar", "abidjan", "bamako", "ouagadougou",
                        "niamey", "drc", "congo", "kinshasa", "m23"],
    "french (sahel)":  ["mali", "burkina", "niger", "sahel", "junta", "wagner"],
    # ── MODERATE ASYMMETRY — European languages (local news faster) ─────────
    "romanian": ["romania", "bucharest", "iohannis", "ciuca"],
    "dutch": ["netherlands", "amsterdam", "wilders", "pvv", "vvd", "dutch", "hague",
              "tweede kamer", "new people nl"],
    "turkish": ["turkey", "erdogan", "ankara", "istanbul", "akp", "turkish"],
    "german": ["germany", "berlin", "bundestag", "scholz", "cdu", "spd", "afd"],
    "french": ["france", "paris", "macron", "elysee", "assemblee", "french election"],
    "spanish": ["spain", "madrid", "psoe", "sanchez", "vox", "catalonia"],
    "portuguese": ["brazil", "brasilia", "lula", "bolsonaro", "stf", "portuguese"],
}


# ── Topic clustering — prevents one country/event dominating the top-N ─────────

_TOPIC_STOP = frozenset({
    "will", "the", "be", "a", "an", "of", "in", "on", "by", "to", "for",
    "is", "are", "was", "were", "has", "have", "had", "at", "from", "that",
    "this", "it", "its", "with", "or", "and", "not", "no", "yes",
    "next", "new", "first", "last", "win", "won", "lose", "lost",
    "get", "gets", "got", "take", "takes",
    "2025", "2026", "2027", "june", "july", "august", "september", "october",
    "november", "december", "january", "february", "march", "april", "may",
    "30", "31", "15", "1",
})
_MAX_PER_CLUSTER = 2   # at most 2 candidates from the same topic cluster in top-N


def _topic_cluster_key(question: str) -> str:
    """Extract a 3-word cluster key that identifies the UNDERLYING EVENT, not the actor.

    The key is built from the last 3 non-stop tokens, which captures the
    position/country/event rather than the person's name:

    "Will Cătălin Predoiu be the next Prime Minister of Romania?" → "prime minister romania"
    "Will Sorin Grindeanu be the next Prime Minister of Romania?" → "prime minister romania"
    "Will Russia enter Orikhiv by July 31?"                      → "russia enter orikhiv"
    "Will OpenAI have the highest private market valuation?"      → "private market valuation"

    We try last-3 tokens first; if they're too generic (all 2-char tokens), fall
    back to first-3 tokens so event-at-start questions still cluster.
    """
    # Normalise: lowercase, strip punctuation except hyphens
    ql = re.sub(r"[^\w\s-]", " ", question.lower())
    tokens = [t for t in ql.split() if t not in _TOPIC_STOP and len(t) > 2]

    if not tokens:
        return question[:40].lower()

    # --- Strategy: last-3 tokens (captures position + country) ---
    seen: set[str] = set()
    last_key: list[str] = []
    for t in reversed(tokens):
        if t not in seen:
            seen.add(t)
            last_key.insert(0, t)
        if len(last_key) == 3:
            break

    # If last-3 looks specific enough (longest token >= 5 chars), use it
    if last_key and max(len(t) for t in last_key) >= 5:
        return " ".join(last_key)

    # --- Fallback: first-3 tokens (for "Russia enters Orikhiv"-style questions) ---
    seen2: set[str] = set()
    first_key: list[str] = []
    for t in tokens:
        if t not in seen2:
            seen2.add(t)
            first_key.append(t)
        if len(first_key) == 3:
            break
    return " ".join(first_key)


def _select_diverse_top_n(candidates: list[dict], n: int, max_per_cluster: int = _MAX_PER_CLUSTER) -> list[dict]:
    """Pick top-N from a scored list, capping each topic cluster at max_per_cluster.

    Candidates must already be sorted by score descending.
    Clusters are keyed by _topic_cluster_key(); overflows are appended at the end
    from the next-best cluster so we always return exactly min(n, len) candidates.
    """
    cluster_counts: dict[str, int] = {}
    selected: list[dict] = []
    overflow: list[dict] = []

    for c in candidates:
        key = _topic_cluster_key(c["question"])
        count = cluster_counts.get(key, 0)
        if count < max_per_cluster:
            cluster_counts[key] = count + 1
            selected.append(c)
        else:
            overflow.append(c)
        if len(selected) >= n:
            break

    # If we ran out of non-overflowing candidates, fill remaining slots from overflow
    if len(selected) < n:
        for c in overflow:
            selected.append(c)
            if len(selected) >= n:
                break

    return selected


def _select_stratified_wide_pool(candidates: list[dict], n: int) -> tuple[list[dict], dict]:
    """Build a wide G2 pool from multiple lenses, not only formula rank.

    The old candidates_wide.json was simply top-N by discoverability_score. That
    over-selected stale/cheap/liquid markets and buried exactly the markets a
    human operator would want to inspect: language asymmetry, near-term
    geopolitics, private-company valuation, fresh markets, and long-tail samples.
    """
    selected: list[dict] = []
    seen: set[str] = set()
    bucket_counts: dict[str, int] = {}

    def add_bucket(label: str, pool: list[dict], quota: int) -> None:
        added = 0
        for c in pool:
            cid = c.get("condition_id")
            if not cid or cid in seen:
                continue
            c.setdefault("wide_selection_buckets", []).append(label)
            selected.append(c)
            seen.add(cid)
            added += 1
            if added >= quota or len(selected) >= n:
                break
        bucket_counts[label] = added

    by_score = list(candidates)
    by_score.sort(key=lambda x: x.get("discoverability_score", 0), reverse=True)

    add_bucket("top_discoverability", by_score, min(70, n))
    add_bucket(
        "language_asymmetry",
        [c for c in by_score if float(c.get("information_asymmetry") or 0) >= 0.40],
        min(55, n),
    )
    add_bucket(
        "local_elections",
        [
            c for c in by_score
            if any(w in (c.get("question", "").lower()) for w in ("election", "primary", "mayor", "governor", "seat"))
            and float(c.get("information_asymmetry") or 0) >= 0.25
        ],
        min(35, n),
    )
    add_bucket(
        "geopolitics_near_deadline",
        [
            c for c in by_score
            if c.get("vertical") == "international_geopolitics"
            and float(c.get("days_to_end") or 999) <= 60
        ],
        min(45, n),
    )
    add_bucket(
        "private_market_valuation",
        [
            c for c in by_score
            if "valuation hit" in c.get("question", "").lower()
            or "npm price" in c.get("question", "").lower()
        ],
        min(35, n),
    )
    add_bucket(
        "mid_price_compounders",
        [c for c in by_score if 0.18 <= float(c.get("yes_price") or 0) <= 0.82],
        min(45, n),
    )
    add_bucket(
        "fresh_or_underwatched",
        [
            c for c in by_score
            if "low_volume_research_sweetspot" in (c.get("matched_strategies") or [])
            or float(c.get("volume") or 0) < 5_000
        ],
        min(35, n),
    )
    # ── NEW: Macro data events — ЦБ, CPI, NFP, GDP ─────────────────────────
    _MACRO_KW = (
        "rate decision", "interest rate", "rate cut", "rate hike", "rate hold",
        "federal reserve", "fomc", "fed funds",
        "ecb", "european central bank",
        "rba", "reserve bank", "cash rate",
        "boe", "bank of england", "bank of japan", "boj",
        "cpi", "inflation", "consumer price",
        "nonfarm payroll", "nfp", "unemployment rate", "jobs report",
        "gdp", "gross domestic product",
        "pce", "core pce",
        "tariff", "trade war", "trade deal", "trade deficit",
        "recession", "soft landing",
    )
    add_bucket(
        "macro_data_events",
        [
            c for c in by_score
            if any(kw in c.get("question", "").lower() for kw in _MACRO_KW)
            and float(c.get("days_to_end") or 999) <= 90
        ],
        min(40, n),
    )
    # ── NEW: Regulatory & science events — FDA, launches, drug approvals ────
    _SCIENCE_KW = (
        "fda", "pdufa", "drug approval", "approval",
        "clinical trial", "phase 3", "phase iii",
        "spacex", "starship", "falcon", "launch", "orbit",
        "nasa", "artemis", "iss",
        "ipo", "direct listing",
    )
    add_bucket(
        "regulatory_science_events",
        [
            c for c in by_score
            if any(kw in c.get("question", "").lower() for kw in _SCIENCE_KW)
            and float(c.get("volume") or 0) >= 500
        ],
        min(25, n),
    )
    # Deterministic long-tail: sample across the whole scored candidate list so
    # G2 can occasionally see markets below the formula top cluster.
    if len(selected) < n and candidates:
        stride = max(1, len(candidates) // max(1, n - len(selected)))
        long_tail = candidates[::stride]
        add_bucket("long_tail_sample", long_tail, n - len(selected))

    if len(selected) < n:
        add_bucket("fill_by_discoverability", by_score, n - len(selected))

    return selected[:n], {
        "stratified": True,
        "target_n": n,
        "selected_n": len(selected[:n]),
        "bucket_counts": bucket_counts,
    }


# ── Vertical + language detection ─────────────────────────────────────────────

def _kw_match(keyword: str, ql: str) -> bool:
    """Word-boundary match for single-word alphanumeric keywords (e.g. 'nato', 'iran').
    Multi-word or non-alnum keywords use substring matching."""
    kw = keyword.lower()
    if kw.strip() != kw:
        return kw in ql
    if " " not in kw and kw.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", ql) is not None
    return kw in ql


def _detect_info_asymmetry(question: str) -> tuple[str | None, float]:
    """Detect if this market has non-English information edge.

    Returns (language, bonus_score 0.0-1.0).
    Higher score = more likely that local language sources have info advantage.

    Uses word-boundary matching so 'nato' doesn't fire inside 'gubernatorial',
    and language clusters are checked in priority order (strong country names
    before generic keywords like 'nuclear').
    """
    ql = question.lower()
    # Priority order: check strong country/entity clusters first.
    # This prevents 'nuclear' (in Persian cluster) from stealing a market
    # that mentions 'russia' or 'china' more prominently.
    # High-asymmetry languages: local sources run 24-72h ahead of Western press
    _HIGH_ASYMMETRY = [
        "russian", "chinese", "hebrew", "persian", "arabic", "romanian", "korean",
        # Global expansion: Telegram is top-1 realtime source for these regions
        "burmese",       # Myanmar military/resistance — almost no English realtime coverage
        "urdu",          # Pakistan politics/military — local media breaks first
        "dari",          # Afghanistan Taliban/resistance — BBC has 24h+ lag
        "amharic",       # Ethiopia Tigray/Amhara — Addis Standard only EN source
        "armenian",      # Caucasus — ceasefire/territory changes break on TG first
        "azerbaijani",   # Azerbaijan — Karabakh, Zangezur corridor news
        "georgian",      # Georgia — EU/NATO politics, Russian pressure
    ]
    # Moderate-asymmetry: news cycle similar to Western press but local-language edge
    _MOD_ASYMMETRY = [
        "dutch", "turkish", "german", "french", "spanish", "portuguese",
        "french (africa)", "french (sahel)",  # Sahel juntas: TG-first, French press lags
    ]
    _PRIORITY_ORDER = _HIGH_ASYMMETRY + _MOD_ASYMMETRY

    # Pass 1: Strong signals (explicit country/entity) — high-asymmetry first
    for lang in _HIGH_ASYMMETRY:
        keywords = _INFO_ASYMMETRY_LANGUAGES.get(lang, [])
        strong = [kw for kw in keywords if " " not in kw and len(kw) >= 4]
        if any(_kw_match(kw, ql) for kw in strong):
            return lang, 0.80
    for lang in _MOD_ASYMMETRY:
        keywords = _INFO_ASYMMETRY_LANGUAGES.get(lang, [])
        strong = [kw for kw in keywords if " " not in kw and len(kw) >= 4]
        if any(_kw_match(kw, ql) for kw in strong):
            return lang, 0.50  # moderate edge — English coverage comparable

    # Pass 2: Weaker keyword matches
    for lang in _HIGH_ASYMMETRY:
        keywords = _INFO_ASYMMETRY_LANGUAGES.get(lang, [])
        if any(_kw_match(kw, ql) for kw in keywords):
            return lang, 0.60
    for lang in _MOD_ASYMMETRY:
        keywords = _INFO_ASYMMETRY_LANGUAGES.get(lang, [])
        if any(_kw_match(kw, ql) for kw in keywords):
            return lang, 0.40

    return None, 0.0


def _classify_archetype(m: dict, matched_strategies: set[str]) -> str:
    yes = m.get("yes_price", 0.5)
    vertical = m.get("vertical", "other")
    if yes <= 0.10 or (1 - yes) <= 0.10:
        return "moonshot"
    if yes <= 0.15 or (1 - yes) <= 0.15:
        return "cheap_optionality"
    if any(k in m.get("question", "").lower()
           for k in ("fda", "pdufa", "drug approval", "nda", "bla", "phase 3")):
        return "fda_regulatory"
    if any(k in m.get("question", "").lower()
           for k in ("spacex", "launch", "orbit", "starship", "nasa", "rocket")):
        return "science_event"
    if any(k in m.get("question", "").lower()
           for k in ("nonfarm", "nfp", "unemployment rate", "gdp", "tariff", "trade deal", "trade war")):
        return "macro_data_release"
    if vertical in ("economics_finance",):
        return "monetary_policy_catalyst" if any(
            k in m.get("question", "").lower()
            for k in ("rate", "rba", "fed", "ecb", "boe", "boj", "cpi", "inflation")
        ) else "economic_indicator"
    if "low_volume_research_sweetspot" in matched_strategies:
        return "low_attention_research"
    if "compounder_research_candidate" in matched_strategies:
        return "compounder"
    if "stale_price" in matched_strategies:
        return "stale_catalyst"
    return "general_research"


def _suggest_side(m: dict) -> str:
    """Suggest research side — the side with more potential information asymmetry."""
    yes = m.get("yes_price", 0.5)
    # Research the more uncertain side (closer to 0.5)
    # But for extreme prices: research the expensive side (that's the consensus to verify)
    if yes < 0.15:
        return "YES"   # moonshot — research if event could actually happen
    if yes > 0.85:
        return "NO"    # compounder — research if dominant side is really that safe
    if yes < 0.5:
        return "YES"   # below fair value — research upside case
    return "NO"


def _local_language(question: str) -> str:
    lang, _ = _detect_info_asymmetry(question)
    lang_map = {
        "persian": "Persian (IRNA, PressTV, Tasnim News)",
        "arabic": "Arabic (Al Jazeera, Arab News, Saudi Press Agency)",
        "russian": "Russian (TASS, Interfax, Kommersant)",
        "hebrew": "Hebrew (Haaretz, Ynet, Times of Israel)",
        "chinese": "Chinese (Xinhua, CGTN, Global Times)",
        "romanian": "Romanian (Digi24, ProTV, Mediafax)",
        "korean": "Korean (Korea Herald, Yonhap)",
        "dutch": "Dutch (NOS, RTL Nieuws, Nu.nl)",
        "turkish": "Turkish (Sabah, Hurriyet, TRT World)",
        "german": "German (Spiegel, FAZ, DW, ARD)",
        "french": "French (Le Monde, Le Figaro, France 24)",
        "spanish": "Spanish (El País, El Mundo, Univision)",
        "portuguese": "Portuguese (Folha, Globo, G1)",
    }
    return lang_map.get(lang or "", "English")


# ── Kill criteria generation ───────────────────────────────────────────────────

def _kill_criteria_ollama(question: str, side: str, end_date: str = "") -> list[str] | None:
    """Use Ollama qwen2.5:7b to generate market-specific kill criteria.

    Returns None if Ollama unavailable (caller uses template fallback).
    Pass end_date to avoid year hallucinations (Ollama confuses resolution deadline).
    """
    try:
        sys.path.insert(0, "../forager")
        from forager.llm_adapters import OllamaAdapter  # noqa: PLC0415
        if not OllamaAdapter.is_available():
            return None
        adapter = OllamaAdapter()
        # Pick best model
        installed = adapter.list_models()
        if installed:
            adapter.model = adapter.best_available_model()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        deadline_note = f"Market resolves by: {end_date}. " if end_date else ""
        prompt = f"""You are a prediction market research analyst. Today is {today}. {deadline_note}

Market question: "{question}"
Research side: {side} (we are researching whether this side is correct)

Generate exactly 3 specific kill criteria — concrete factual statements that would DISPROVE
our {side} thesis if found to be true before the market resolution date. Each criterion should be:
- Specific to THIS market and resolvable BEFORE {end_date or "the deadline"}
- Verifiable via public sources within 48 hours
- A direct disconfirmer of the {side} outcome happening before {end_date or "resolution"}
- Do NOT reference dates after {end_date or today}

Respond with ONLY a JSON array of 3 strings. No preamble, no explanation:
["criterion 1", "criterion 2", "criterion 3"]"""

        response = adapter.chat(prompt)
        # Extract JSON array
        match = re.search(r'\[.*?\]', response, re.DOTALL)
        if match:
            criteria = json.loads(match.group(0))
            if isinstance(criteria, list) and len(criteria) >= 2:
                return [str(c).strip() for c in criteria[:3]]
    except Exception:  # noqa: BLE001
        pass
    return None


def _kill_criteria_template(m: dict) -> list[str]:
    """Fast fallback kill criteria generated from market metadata."""
    q = m.get("question", "")
    ql = q.lower()
    side = _suggest_side(m)

    # Economic/monetary policy markets
    if any(k in ql for k in ["rate", "rba", "fed ", "ecb", "boe", "boj", "cpi", "inflation"]):
        if side == "NO":
            return [
                f"Official central bank statement confirms rate change at next meeting",
                f"CPI/inflation print comes in significantly above/below target triggering policy action",
                f"Emergency rate decision announced outside regular meeting schedule",
            ]
        else:
            return [
                f"Central bank governor explicitly signals hold at next meeting",
                f"Inflation data within target range, removing urgency for rate action",
                f"Market pricing (futures) implies <5% probability of rate change",
            ]

    # FDA / regulatory approval markets
    if any(k in ql for k in ["fda", "pdufa", "drug approval", "nda", "bla", "phase 3"]):
        if side == "YES":
            return [
                "FDA issues Complete Response Letter (CRL) rejecting the application",
                "FDA advisory committee votes against approval recommendation",
                "Company withdraws NDA/BLA due to safety or efficacy concerns",
            ]
        else:
            return [
                "FDA approves drug on or before PDUFA date with full approval",
                "FDA advisory committee votes in favor with no additional data required",
                "FDA grants accelerated/breakthrough therapy approval ahead of schedule",
            ]

    # Space launch markets
    if any(k in ql for k in ["spacex", "launch", "orbit", "starship", "rocket"]):
        if side == "YES":
            return [
                "FAA issues launch license suspension or indefinite delay",
                "Significant vehicle anomaly during test requiring full investigation",
                "Range closure or weather window forces multi-month delay",
            ]
        else:
            return [
                "SpaceX confirms launch window and webcast schedule",
                "FAA grants launch license with no conditions",
                "Vehicle clears static fire test with no anomalies",
            ]

    # Election / political nomination markets
    if any(k in ql for k in ["nominee", "primary", "election", "candidate", "senator", "governor"]):
        if side == "YES":
            return [
                f"Major opposing candidate announces with strong endorsements/polling",
                f"Candidate drops out, suspends campaign, or withdraws",
                f"Party convention/primary results show clear opposition majority",
            ]
        else:
            return [
                f"Official party endorsement or primary victory confirmed",
                f"All competing candidates drop out leaving only one",
                f"Poll shows 70%+ lead with no credible challengers",
            ]

    # Geopolitical / conflict markets
    if any(k in ql for k in ["war", "ceasefire", "attack", "missile", "troops", "enter", "invade", "ban"]):
        if side == "YES":
            return [
                f"Official government statement confirms the event occurred",
                f"Multiple credible news outlets report confirmed event from primary sources",
                f"Market resolution criteria met per official resolver announcement",
            ]
        else:
            return [
                f"Official denial from all relevant parties with no contradicting reports",
                f"Deadline expires with no confirmed event from authoritative sources",
                f"Physical/logistical impossibility confirmed (travel ban, military positioning)",
            ]

    # Generic fallback (still question-aware)
    qwords = q.rstrip("?").replace("Will", "").replace("be the", "").strip()[:50]
    if side == "YES":
        return [
            f"Official sources deny or rule out: {qwords}",
            f"Deadline passes without confirmation from primary resolution source",
            f"Opposing outcome confirmed by authoritative reporting",
        ]
    else:
        return [
            f"Official confirmation of: {qwords}",
            f"Primary resolution source reports the event occurred",
            f"Market price moves sharply toward YES (>20pp) on news confirmation",
        ]


def _first_queries(m: dict) -> list[str]:
    """Generate targeted research queries from market metadata.

    Returns 3 queries ordered best-to-least: primary question, domain deep-dive,
    disconfirming angle. Forager will run them in order.
    """
    q = m.get("question", "").rstrip("?")
    vertical = m.get("vertical", "other")
    tags = m.get("theme_tags") or []
    yes = m.get("yes_price", 0.5)
    side = m.get("suggested_side") or _suggest_side(m)
    year = datetime.now(timezone.utc).year
    ql = q.lower()

    # ── Tier 1: Central banks ────────────────────────────────────────────────
    if any(k in ql for k in ["rba", "reserve bank australia", "cash rate"]):
        return [
            f"RBA cash rate decision June {year} ASX rate futures probability",
            f"Australia inflation CPI April May {year} RBA outlook",
            f"RBA governor Bullock speech June {year} rate guidance",
        ]
    if any(k in ql for k in ["fomc", "federal reserve", "fed rate", "fed funds"]):
        return [
            f"FOMC rate decision {year} CME FedWatch probability",
            f"Fed funds futures implied probability next meeting",
            f"Federal Reserve chair Powell inflation signals {year}",
        ]
    if any(k in ql for k in ["ecb", "european central bank"]):
        return [
            f"ECB rate decision {year} Lagarde forward guidance",
            f"Eurozone inflation {year} ECB policy outlook",
            f"ECB deposit rate probability {year} expectations",
        ]
    if any(k in ql for k in ["cpi", "inflation", "pce", "consumer price"]):
        return [
            f"{q} latest data forecast consensus {year}",
            f"inflation expectation {year} core PCE consensus",
            f"{q} disconfirming evidence alternative data",
        ]

    # ── Tier 2: Geopolitical clusters ────────────────────────────────────────
    if any(k in ql for k in ["iran", "tehran", "nuclear deal", "irna"]):
        return [
            f"{q} IRNA official statement {year}",
            f"Iran nuclear talks US negotiations status {year}",
            f"Iran airspace military NOTAM aviation {year}",
        ]
    if any(k in ql for k in ["ukraine", "ceasefire", "peace deal"]):
        return [
            f"{q} Kyiv Washington announcement {year}",
            f"Ukraine ceasefire framework Zelensky response {year}",
            f"Ukraine Russia negotiations status TASS Ukrainska Pravda {year}",
        ]
    if any(k in ql for k in ["russia", "putin", "kremlin"]):
        return [
            f"{q} Kremlin official TASS {year}",
            f"Russia {q} confirmation denial {year}",
            f"Russia foreign ministry statement {year}",
        ]
    if any(k in ql for k in ["israel", "gaza", "hamas", "idf", "hezbollah"]):
        if "airspace" in ql or "notam" in ql or "aviation" in ql:
            return [
                f"Israel airspace NOTAM closure {year} ICAO aviation",
                f"Israel civil aviation authority airspace notice {year}",
                f"Israel airspace open commercial flights status {year}",
            ]
        return [
            f"{q} IDF official statement {year}",
            f"Israel Gaza ceasefire negotiations {year} update",
            f"Hamas response Israel latest {year}",
        ]
    if any(k in ql for k in ["romania", "bucharest"]):
        # Extract candidate name from "Will X be the next Prime Minister of Romania?"
        # pattern for more targeted queries
        _pm_match = re.search(r"will\s+([A-Za-zÀ-ɏ\-]+(?:\s+[A-Za-zÀ-ɏ\-]+)?)\s+be\s+the\s+next\s+prime\s+minister", m.get("question", ""), re.IGNORECASE)
        _candidate = _pm_match.group(1) if _pm_match else ""
        if _candidate:
            return [
                f"{_candidate} Romania premier candidatura {year} coalitie suport",
                f"Romania prime minister candidate polls {_candidate} Ciolacu PSD PNL {year}",
                f"Romania premier negocieri guvern Iohannis mandat formare {year}",
            ]
        return [
            f"{q} Digi24 Romania {year}",
            f"Romania political parties coalition negotiations prime minister {year}",
            f"Romania president parliament government formation confidence vote {year}",
        ]
    if any(k in ql for k in ["china", "beijing", "taiwan", "ccp"]):
        return [
            f"{q} Xinhua official statement {year}",
            f"China government announcement {year} official",
            f"Taiwan China military diplomatic {year}",
        ]
    if any(k in ql for k in ["korea", "seoul", "busan"]):
        return [
            f"{q} Korea Herald Yonhap {year}",
            f"South Korea election polls {year} official results",
            f"South Korea party PPP opposition {year}",
        ]
    if any(k in ql for k in ["colombia", "venezuela", "latin america", "cartel"]):
        return [
            f"{q} Colombia official election results {year}",
            f"Colombia election polls candidates {year}",
            f"{q} disconfirming evidence {year}",
        ]
    if any(k in ql for k in ["indonesia", "prabowo", "jakarta"]):
        return [
            f"{q} Jakarta official statement {year}",
            f"Indonesia president political stability {year}",
            f"Prabowo government coalition {year}",
        ]
    if any(k in ql for k in ["netherlands", "amsterdam", "wilders", "pvv"]):
        return [
            f"{q} NOS RTL polling {year}",
            f"Netherlands election polls {year} seat projections parties",
            f"Netherlands Tweede Kamer election results {year} official",
        ]
    if any(k in ql for k in ["turkey", "erdogan", "ankara", "turkish election"]):
        return [
            f"{q} Turkish official statement {year}",
            f"Turkey election polls TRT opposition {year}",
            f"{q} disconfirming evidence AKP opposition {year}",
        ]
    if any(k in ql for k in ["germany", "berlin", "bundestag", "scholz", "cdu", "spd", "afd"]):
        return [
            f"{q} ARD ZDF polls {year} Germany election",
            f"Germany Bundestag coalition negotiations {year}",
            f"{q} disconfirming scenario evidence {year}",
        ]
    if any(k in ql for k in ["france", "paris", "macron", "assemblee"]):
        return [
            f"{q} French official statement BFMTV {year}",
            f"France polls coalition government {year}",
            f"{q} disconfirming evidence opposition {year}",
        ]

    # ── Tier 3: US politics ──────────────────────────────────────────────────
    if any(k in ql for k in ["primary", "nominee", "senate", "governor", "democratic", "republican"]):
        state_hint = next(
            (s.title() for s in [
                "maine", "iowa", "minnesota", "washington", "michigan",
                "nevada", "florida", "texas", "california", "wyoming",
                "nebraska", "south carolina", "north carolina", "georgia",
                "arizona", "ohio", "pennsylvania", "wisconsin", "virginia",
                "colorado", "new hampshire", "new mexico", "kentucky", "louisiana",
            ] if s in ql),
            ""
        )
        return [
            f"{q} latest polls {year} {state_hint}".strip(),
            f"{q} challenger endorsement field {year}",
            f"{q} disconfirming evidence opponent announcement",
        ]
    if any(k in ql for k in ["trump", "harris", "congress", "senate", "white house"]):
        return [
            f"{q} latest news {year}",
            f"{q} official statement announcement",
            f"{q} disconfirming scenario evidence",
        ]

    # ── Tier 3b: FDA / regulatory ────────────────────────────────────────────
    if any(k in ql for k in ["fda", "pdufa", "drug approval", "nda", "bla", "clinical trial"]):
        drug_match = re.search(r"will\s+([A-Za-z\-\d]+(?:\s+[A-Za-z\-\d]+)?)\s+(?:receive\s+)?(?:fda\s+)?approval", m.get("question", ""), re.IGNORECASE)
        drug_name = drug_match.group(1).strip() if drug_match else "drug"
        return [
            f"FDA PDUFA date decision {drug_name} {year} action letter approval",
            f"{drug_name} FDA advisory committee meeting recommendation {year}",
            f"{drug_name} clinical trial results efficacy safety data {year}",
        ]
    # ── Tier 3c: Space launches ───────────────────────────────────────────────
    if any(k in ql for k in ["spacex", "starship", "falcon", "launch", "orbit", "nasa", "rocket"]):
        return [
            f"{q} launch schedule {year} status update",
            f"SpaceX launch manifest window {year} webcast",
            f"{q} scrub delay range closure {year}",
        ]
    # ── Tier 3d: Macro data releases ─────────────────────────────────────────
    if any(k in ql for k in ["nonfarm payroll", "nfp", "jobs report", "unemployment"]):
        return [
            f"NFP nonfarm payrolls forecast consensus Bloomberg {year}",
            f"ADP employment change private payrolls {year}",
            f"jobless claims initial unemployment {year} trend",
        ]
    if any(k in ql for k in ["gdp", "gross domestic"]):
        return [
            f"GDP growth forecast consensus {year} BEA advance estimate",
            f"GDPNow Atlanta Fed nowcast {year}",
            f"{q} disconfirming evidence recession growth {year}",
        ]
    if any(k in ql for k in ["tariff", "trade war", "trade deal"]):
        return [
            f"{q} official announcement White House USTR {year}",
            f"US China trade tariff negotiations {year} Bloomberg",
            f"{q} disconfirming evidence trade deal collapse {year}",
        ]

    # ── Tier 4: Economics / assets ───────────────────────────────────────────
    if any(k in ql for k in ["gold", "xauusd", "silver", "platinum"]):
        return [
            f"Gold price forecast {year} analyst consensus technical",
            f"XAU USD target May June {year} Goldman Sachs",
            f"{q} disconfirming bearish case evidence",
        ]
    if any(k in ql for k in ["bitcoin", "btc", "ethereum", "crypto", "hyperliquid"]):
        return [
            f"{q} market analysis {year}",
            f"crypto market sentiment {year} on-chain data",
            f"{q} disconfirming bearish scenario",
        ]

    # ── Tier 4b: US legal / arrest / criminal ────────────────────────────────
    if any(k in ql for k in ["arrested", "indicted", "charged", "convicted", "sentenced", "extradited"]):
        # Extract name from "Will X be arrested" pattern
        _legal_match = re.search(r"will\s+([A-Za-z\s\-]{3,30}?)\s+(?:be\s+)?(?:arrested|indicted|charged|convicted|sentenced)", m.get("question", ""), re.IGNORECASE)
        _person = _legal_match.group(1).strip() if _legal_match else ""
        return [
            f"{_person or q} arrest indictment charges news {year}",
            f"{_person or q} criminal investigation DOJ FBI status {year}",
            f"{_person or q} legal case dropped dismissed evidence {year}",
        ]

    # ── Tier 5: Tech / AI ────────────────────────────────────────────────────
    if any(k in ql for k in ["anthropic", "openai", "gemini", "valuation", "ipo"]):
        return [
            f"{q} latest funding valuation report {year}",
            f"Anthropic OpenAI valuation fundraise {year}",
            f"{q} disconfirming evidence lower valuation",
        ]

    # ── Fallback ─────────────────────────────────────────────────────────────
    tag_hint = tags[0].replace("_", " ") if tags else ""
    return [
        f"{q} {year}",
        f"{q} latest news official statement {year}",
        f"{q} disconfirming evidence {tag_hint}".strip(),
    ]


# ── DB helpers ──────────────────────────────────────────────────────────────────

def _open_position_cids(conn) -> set[str]:
    return {r["condition_id"] for r in conn.execute(
        "SELECT DISTINCT condition_id FROM positions "
        "WHERE status IN ('open','filled','partially_filled')"
    ).fetchall()}


def _recently_reviewed_cids(conn, days: int) -> set[str]:
    rows = conn.execute("""
        SELECT DISTINCT condition_id FROM hidden_gem_reviews
        WHERE julianday(created_at) >= julianday('now', ?)
          AND decision != 'reject'
    """, (f"-{days} days",)).fetchall()
    return {r["condition_id"] for r in rows}


def _b_researched_cids(conn, days: int) -> set[str]:
    """Markets already researched by Command B in the last N days.

    We skip these in G_scan to avoid re-queuing markets that B already
    processed — even if they look attractive by the scoring formula.
    Only re-include after `days` days so stale research can be refreshed.
    """
    # Check triage_scores (G output) — any market that went through G recently
    rows = conn.execute("""
        SELECT DISTINCT condition_id FROM triage_scores
        WHERE julianday(captured_at) >= julianday('now', ?)
    """, (f"-{days} days",)).fetchall()
    cids = {r["condition_id"] for r in rows}
    # Also check pre_bet_checklists — any market that went through D (post-B)
    rows2 = conn.execute("""
        SELECT DISTINCT condition_id FROM pre_bet_checklists
        WHERE julianday(created_at) >= julianday('now', ?)
    """, (f"-{days} days",)).fetchall()
    cids |= {r["condition_id"] for r in rows2}
    return cids


def _price_series(conn, condition_id: str, window_days: int = 14) -> list[float]:
    rows = conn.execute("""
        SELECT yes_price FROM snapshots
        WHERE condition_id = ?
          AND julianday(captured_at) >= julianday('now', ?)
        ORDER BY captured_at
    """, (condition_id, f"-{window_days} days")).fetchall()
    return [float(r["yes_price"]) for r in rows]


# ── Scoring ─────────────────────────────────────────────────────────────────────

def _score_candidate(m: dict, matched_strategies: set[str], conn) -> float:
    """Composite discoverability score (0-100), improved vs v1."""
    age_days = _market_age_days(m.get("first_seen_at"))
    price_history = _price_series(conn, m["condition_id"])

    # Fix: young markets (< 7 days) get age_share = 0.5 (neutral), not 0
    # They're NEW and might be mispriced — not penalized for being fresh
    if age_days is not None and age_days < 7:
        age_adj = 0.5
    else:
        age_adj = age_days

    ag = attention_gap_score(
        volume=m.get("volume") or 0,
        market_age_days=age_adj,
        liquidity=m.get("liquidity"),
    )
    sp = stale_price_score(price_history)  # uses real DB history when available
    liq = liquidity_score(m.get("liquidity"))
    spr = spread_score(m.get("spread"))
    strategy_bonus = min(len(matched_strategies) / 3.0, 1.0)

    base_score = combined_raw_discoverability(
        attention_gap=ag,
        stale_price=sp,
        liquidity=liq,
        spread=spr,
        strategy_bonus=strategy_bonus,
    )

    # Information asymmetry bonus: local language edge = +10 points
    _, ia_bonus = _detect_info_asymmetry(m.get("question", ""))
    asymmetry_bonus = 10.0 * ia_bonus

    # New-market bonus: markets < 7 days old may be mispriced (fresh, less researched).
    # Graded: 0-3 days = +7 pts, 3-7 days = +4 pts, else 0.
    # With startDate now properly populated, new markets get naturally low attention_gap
    # scores (age_share = 3/60 = 0.05) — this bonus compensates so fresh markets
    # aren't systematically buried under 60-day-old markets.
    if age_days is not None and age_days < 3:
        freshness_bonus = 7.0
    elif age_days is not None and age_days < 7:
        freshness_bonus = 4.0
    else:
        freshness_bonus = 0.0

    # Vertical quality adjustment:
    # - Known verticals (politics, geopolitics, economics, tech) get no penalty
    # - "other" with language asymmetry: no penalty (language edge compensates)
    # - "other" without language asymmetry: -8 pts (needs extra justification)
    vertical = m.get("vertical", "other")
    vertical_penalty = 0.0
    if vertical == "other" and ia_bonus < 0.5:
        vertical_penalty = -8.0

    # Very low volume (<$2000) without language edge: additional -5 pts penalty
    # Prevents ultra-niche markets with <$2k volume from inflating scores
    vol = m.get("volume", 0) or 0
    low_vol_penalty = -5.0 if (vol < 2000 and ia_bonus < 0.5) else 0.0

    return round(
        base_score + asymmetry_bonus + freshness_bonus + vertical_penalty + low_vol_penalty,
        2,
    )


# ── CLOB order flow imbalance ───────────────────────────────────────────────────

def _order_flow_imbalance(tokens: list[str]) -> dict | None:
    """Fetch top-10 CLOB order book levels for the YES token and compute bid/ask depth imbalance.

    Returns dict with {ofi, bid_depth, ask_depth, spread_cents, token_id} or None on failure.
    ofi (Order Flow Imbalance) is in [-1, +1]:
        +1  = all liquidity on bid side (strong buy pressure)
        -1  = all liquidity on ask side (strong sell pressure)
         0  = balanced
    """
    if not tokens:
        return None
    yes_token = tokens[0]
    try:
        r = httpx.get(
            f"https://clob.polymarket.com/book?token_id={yes_token}",
            timeout=5,
            headers={"User-Agent": "Signal/1.0"},
        )
        if r.status_code != 200:
            return None
        book = r.json()
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        # Top 10 levels each side
        bid_vol = sum(float(b["size"]) for b in bids[:10])
        ask_vol = sum(float(a["size"]) for a in asks[:10])
        total = bid_vol + ask_vol
        if total < 1.0:
            return None
        ofi = (bid_vol - ask_vol) / total
        # Spread in cents: best ask - best bid (in probability space)
        spread_cents = None
        if bids and asks:
            try:
                best_bid = float(bids[0]["price"])
                best_ask = float(asks[0]["price"])
                spread_cents = round((best_ask - best_bid) * 100, 1)
            except Exception:  # noqa: BLE001
                pass
        return {
            "ofi": round(ofi, 3),
            "bid_depth": round(bid_vol, 0),
            "ask_depth": round(ask_vol, 0),
            "spread_cents": spread_cents,
            "token_id": yes_token[:16] + "…",
        }
    except Exception:  # noqa: BLE001
        return None


# ── PredictIt / Manifold divergence anchors ─────────────────────────────────────

def _predictit_divergence_check(
    question: str,
    yes_price: float,
    markets_cache: list[dict],
) -> dict | None:
    """Match Polymarket question against PredictIt market list and return divergence.

    Returns dict with {pi_price, divergence, name, url, match_score} or None.
    Only fires when Jaccard overlap ≥ 0.30 AND price gap ≥ 0.08 (8 pp).
    """
    if not markets_cache:
        return None
    from lib.integrations.predictit import find_match  # noqa: PLC0415
    match = find_match(question, markets_cache)
    if match is None:
        return None
    divergence = abs(match["yes_price"] - yes_price)
    if divergence < 0.08:
        return None
    return {
        "pi_price": match["yes_price"],
        "polymarket_yes": yes_price,
        "divergence": round(divergence, 3),
        "name": match["name"],
        "url": match["url"],
        "match_score": match["match_score"],
    }


def _manifold_divergence_check(
    question: str,
    yes_price: float,
    markets_cache: list[dict],
) -> dict | None:
    """Match Polymarket question against Manifold Markets list and return divergence.

    Returns dict with {mf_prob, divergence, question, url, match_score} or None.
    Fires when Jaccard ≥ 0.28 AND price gap ≥ 0.08.
    """
    if not markets_cache:
        return None
    from lib.integrations.manifold import find_match  # noqa: PLC0415
    match = find_match(question, markets_cache)
    if match is None:
        return None
    divergence = abs(match["probability"] - yes_price)
    if divergence < 0.08:
        return None
    return {
        "mf_prob": match["probability"],
        "polymarket_yes": yes_price,
        "divergence": round(divergence, 3),
        "question": match["question"],
        "url": match["url"],
        "match_score": match["match_score"],
    }


# ── Metaculus cross-calibration — direct REST API ────────────────────────────────

def _metaculus_divergence_check(question: str, yes_price: float) -> dict | None:
    """Metaculus REST API v2 — community_prediction returned directly (no snippet parsing).

    Uses /api2/questions/?search={query} which gives community_prediction as a float.
    More reliable than old snippet approach which required regex on web-search excerpts.
    Returns {metaculus_prob, divergence, title, url, num_forecasters} or None.
    """
    try:
        from lib.integrations.metaculus_direct import search_question  # noqa: PLC0415
        result = search_question(question)
        if result is None:
            return None
        meta_prob = result["metaculus_prob"]
        divergence = abs(meta_prob - yes_price)
        if divergence < 0.08:
            return None
        return {
            "metaculus_prob": meta_prob,
            "polymarket_yes": yes_price,
            "divergence": round(divergence, 3),
            "title": result.get("title", "")[:80],
            "url": result.get("url", ""),
            "num_forecasters": result.get("num_forecasters", 0),
            "match_score": result.get("match_score", 0.0),
        }
    except Exception:  # noqa: BLE001
        return None


# ── Kalshi divergence anchor ─────────────────────────────────────────────────────

def _kalshi_divergence_check(
    question: str,
    yes_price: float,
    markets_cache: list[dict],
) -> dict | None:
    """Match Polymarket question against Kalshi CFTC-regulated market list.

    Kalshi has a different participant base (institutional, US-regulated) and
    often shows 5–15pp systematic divergence on US elections and macro events.
    Returns {kalshi_price, divergence, title, url, match_score} or None.
    Fires when Jaccard ≥ 0.28 AND price gap ≥ 0.08 (8 pp).
    """
    if not markets_cache:
        return None
    from lib.integrations.kalshi import find_match  # noqa: PLC0415
    match = find_match(question, markets_cache)
    if match is None:
        return None
    divergence = abs(match["yes_price"] - yes_price)
    if divergence < 0.08:
        return None
    return {
        "kalshi_price": match["yes_price"],
        "polymarket_yes": yes_price,
        "divergence": round(divergence, 3),
        "title": match["title"],
        "url": match["url"],
        "match_score": match["match_score"],
    }


# ── GJO divergence anchor ────────────────────────────────────────────────────────

def _gjo_divergence_check(
    question: str,
    yes_price: float,
    questions_cache: list[dict],
) -> dict | None:
    """Match Polymarket question against Good Judgment Open superforecaster list.

    GJO participants are selected by track record — their aggregate is more
    accurate than naive crowd forecasting.  GJO divergence ≥ 0.15 is a
    strong signal that the market is mispriced.
    Returns {gjo_prob, divergence, question, url, match_score} or None.
    Fires when Jaccard ≥ 0.25 AND price gap ≥ 0.10 (10 pp).
    """
    if not questions_cache:
        return None
    from lib.integrations.gjo import find_match  # noqa: PLC0415
    match = find_match(question, questions_cache)
    if match is None:
        return None
    divergence = abs(match["probability"] - yes_price)
    if divergence < 0.10:
        return None
    return {
        "gjo_prob": match["probability"],
        "polymarket_yes": yes_price,
        "divergence": round(divergence, 3),
        "question": match["question"],
        "url": match["url"],
        "match_score": match["match_score"],
    }


# ── Whale order detection ─────────────────────────────────────────────────────────

def _whale_check(tokens: list[str], condition_id: str):
    """Fast CLOB whale scan for the enrichment loop.

    check_fills=False keeps it quick — trade-fill history is slow to fetch and
    is re-checked freshly in Command B when the candidate is actually researched.

    Returns WhaleReport | None.
    """
    if not tokens:
        return None
    try:
        from lib.integrations.polymarket_whales import detect_whale_activity  # noqa: PLC0415
        return detect_whale_activity(tokens, condition_id=condition_id, check_fills=False)
    except Exception:  # noqa: BLE001
        return None


# ── LLM intuition layer — the "feel" ranker ─────────────────────────────────────

def _format_market_for_llm(c: dict, ctx: dict) -> str:
    """Format a single candidate as readable prose for the LLM vibe-check.

    Deliberately avoids numeric scores — presents raw facts only so the LLM
    can reason from narrative, not from formula outputs.
    """
    yes_pct = c["yes_price"] * 100
    no_pct  = (1.0 - c["yes_price"]) * 100
    vol  = c.get("volume", 0) or 0
    days = c.get("days_to_end", 0) or 0

    lines = [
        f'MARKET: "{c["question"]}"',
        f'  Price: YES={yes_pct:.1f}%  NO={no_pct:.1f}%',
        f'  Volume traded: ${vol:,.0f}  |  Expires in: {days:.0f} days ({c.get("end_date", "?")})',
    ]

    # ── Cross-platform divergence — facts, no scores ──────────────────────────
    divs: list[str] = []
    if ctx.get("metaculus"):
        d = ctx["metaculus"]
        divs.append(
            f'Metaculus community={d["metaculus_prob"]*100:.0f}% '
            f'({d.get("num_forecasters", "?")} forecasters)'
        )
    if ctx.get("predictit"):
        d = ctx["predictit"]
        divs.append(f'PredictIt={d["pi_price"]*100:.0f}%')
    if ctx.get("manifold"):
        d = ctx["manifold"]
        divs.append(f'Manifold={d["mf_prob"]*100:.0f}%')
    if ctx.get("kalshi"):
        d = ctx["kalshi"]
        divs.append(f'Kalshi={d["kalshi_price"]*100:.0f}%')
    if ctx.get("gjo"):
        d = ctx["gjo"]
        divs.append(f'Good Judgment Open (superforecasters)={d["gjo_prob"]*100:.0f}%')
    if divs:
        lines.append(f'  Other platforms: {" | ".join(divs)}')

    # ── Language advantage ────────────────────────────────────────────────────
    lang = (c.get("local_language") or "English").strip()
    if lang.lower() not in ("english", "en", ""):
        lines.append(f'  Non-English sources available: {lang}')

    # ── Market characteristics (as plain labels, not scores) ─────────────────
    strat_labels = {
        "cheap_optionality": "low-price option (<15%)",
        "stale_price": "price has not moved recently (possible stale consensus)",
        "compounder_research_candidate": "high-probability market (>85%)",
        "low_volume_research_sweetspot": "low-attention market (thin trading)",
    }
    strats = [strat_labels.get(s, s) for s in (c.get("matched_strategies") or [])]
    if strats:
        lines.append(f'  Characteristics: {", ".join(strats)}')

    # ── Order book (informational, labelled as such) ─────────────────────────
    ofi = ctx.get("ofi")
    if ofi and abs(ofi.get("ofi", 0)) > 0.25:
        direction = "buy (YES)" if ofi["ofi"] > 0 else "sell (NO)"
        lines.append(
            f'  Order book: imbalance toward {direction} side '
            f'(bid ${ofi.get("bid_depth",0):,.0f} vs ask ${ofi.get("ask_depth",0):,.0f})'
            f'  — informational only, not a signal weight'
        )

    # ── Large orders (informational only, explicit disclaimer) ───────────────
    whale = ctx.get("whale")
    if whale:
        lines.append(
            f'  Large resting orders detected: up to ${whale.get("max_usd", 0):,.0f} '
            f'| dominant side: {whale.get("dominant", "?")}  '
            f'— informational context only, many large bets on Polymarket are degens'
        )

    # ── Structural constraints (pace ceiling / legislative timeline) ──────────
    structural_type = ctx.get("structural_type") or c.get("structural_type")
    if structural_type == "production_count_market":
        lines.append(
            "  STRUCTURAL: Production/count market — verify pace math before assuming YES. "
            "Check current count vs target vs hours remaining."
        )
    elif structural_type and "legislative" in str(structural_type).lower():
        timeline_type = ctx.get("legislative_timeline_type", "")
        margin = ctx.get("legislative_safety_margin", 0)
        is_ceiling = ctx.get("structural_ceiling", False) or c.get("structural_ceiling", False)
        if is_ceiling:
            lines.append(
                f"  STRUCTURAL CEILING: Legislative timeline is {timeline_type} "
                f"(safety_margin={margin:.2f}x). Process may not complete before deadline."
            )
        elif timeline_type:
            lines.append(
                f"  Legislative timeline: {timeline_type} (safety_margin={margin:.2f}x)"
            )

    return "\n".join(lines)


def _llm_vibe_check(
    candidates: list[dict],
    contexts: dict,
    top_n: int,
) -> list[dict] | None:
    """LLM-powered intuitive market ranking — the core of the new Command G.

    Instead of formula scores, Ollama reads each market as narrative and
    identifies hidden gems: markets where the crowd is fundamentally wrong,
    not just marginally wrong.

    Whale activity, OFI, and divergence data are shown as context only —
    the LLM decides how much weight to give them.

    Returns top_n re-ranked candidates with llm_reasoning + hidden_gem_type,
    or None if Ollama is unavailable (caller falls back to pre-score ranking).
    """
    # Format candidates as readable market descriptions (do this FIRST so we can
    # persist the same payload to the handoff file even when Ollama is disabled).
    market_blocks: list[str] = []
    for i, c in enumerate(candidates, 1):
        ctx = contexts.get(c["condition_id"], {})
        block = _format_market_for_llm(c, ctx)
        market_blocks.append(f"--- MARKET {i} [condition_id: {c['condition_id']}] ---\n{block}")
    markets_text = "\n\n".join(market_blocks)

    # ── Manual-Claude handoff path (Ollama-free) ─────────────────────────────
    # Always emit a handoff JSON so the operator can have Opus 4.7 / Sonnet
    # rank these candidates after the cycle. Falls through to the legacy Ollama
    # code path below ONLY if OllamaAdapter says it's available (currently
    # always False in this codebase as of 2026-05-23).
    try:
        import json as _json, os as _os, time as _time, uuid as _uuid  # noqa: PLC0415
        handoff_dir = _os.path.join(
            _os.path.dirname(_os.path.abspath(__file__)),
            "llm_handoff",
        )
        _os.makedirs(handoff_dir, exist_ok=True)
        ranking_input = []
        for c in candidates:
            ctx = contexts.get(c["condition_id"], {})
            ranking_input.append({
                "condition_id": c["condition_id"],
                "question": c.get("question"),
                "yes_price": c.get("yes_price"),
                "volume": c.get("volume"),
                "days_to_end": c.get("days_to_end"),
                "end_date": c.get("end_date"),
                "vertical": c.get("vertical"),
                "discoverability_score": c.get("discoverability_score"),
                "matched_strategies": c.get("matched_strategies", []),
                "local_language": c.get("local_language"),
                "polymarket_url": c.get("polymarket_url"),
                "context": {k: v for k, v in ctx.items() if k in
                            ("metaculus", "predictit", "manifold", "kalshi", "gjo",
                             "ofi", "whale", "structural_type")},
            })
        fname = f"g_vibe_check_{_time.strftime('%Y%m%dT%H%M%S')}_{_uuid.uuid4().hex[:8]}.json"
        with open(_os.path.join(handoff_dir, fname), "w", encoding="utf-8") as _f:
            _json.dump({
                "task": "g_vibe_check",
                "status": "pending",
                "top_n_requested": top_n,
                "candidates": ranking_input,
                "markets_text_for_llm": markets_text,
                "expected_schema": {
                    "ranking": [{
                        "rank": 1,
                        "condition_id": "0x...",
                        "hidden_gem_type": "language_polling_edge|resolution_wording_trap|cross_platform_divergence|insider_whale_flow|stale_consensus|narrative_bubble_short|catalyst_proximity|none",
                        "llm_reasoning": "1-3 sentences: why this is a hidden gem (or why not)",
                        "suggested_side": "YES|NO",
                        "skip_reason": "str — only if not picked",
                    }],
                },
                "instructions_for_claude": (
                    "Re-rank candidates by hidden-gem potential. Pick top_n; for each "
                    "explain in 1-3 sentences why this is mispriced (not why it's interesting). "
                    "Prefer language_polling_edge for non-English markets, "
                    "resolution_wording_trap (SHORT) for ambiguous wording, "
                    "cross_platform_divergence ONLY if you verified the matched contract is the "
                    "same event (not text overlap). Distrust PredictIt false-matches on "
                    "primaries (Eric Jones case)."
                ),
            }, _f, ensure_ascii=False, indent=2, default=str)
        print(f"  [LLM handoff] g_vibe_check → {fname}")
    except Exception as _e:  # noqa: BLE001
        print(f"  [LLM handoff] failed to write g_vibe_check: {_e}")

    try:
        sys.path.insert(0, "../forager")
        from forager.llm_adapters import OllamaAdapter  # noqa: PLC0415
        if not OllamaAdapter.is_available():
            return None
        adapter = OllamaAdapter()
        installed = adapter.list_models()
        if installed:
            adapter.model = adapter.best_available_model()
    except Exception:  # noqa: BLE001
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"""Today is {today}. You are a contrarian prediction market analyst with a track record of finding 20-40pp mispricings.

You find markets where the crowd is FUNDAMENTALLY wrong — not marginally, but structurally.
Your approach is intuitive and narrative-driven. You read markets like stories, not spreadsheets.

════════════════════════════════════════════════════════
PROVEN HIGH-YIELD PATTERNS (from our own resolved trades)
════════════════════════════════════════════════════════

PATTERN A — language_polling_edge (CONFIRMED REPEATABLE EDGE):
  Market: Korean gubernatorial election. English price: 29% YES for Kim Kyung-soo.
  What we found: Korean Gallup (May 11-12) showed Kim 45% vs opponent 38% (+7pp, outside MOE).
  English traders couldn't read Gallup Korea. Result: +25pp edge confirmed.
  YOUR JOB: For ANY market involving a non-English election/political event — ask yourself
  "what do local polls actually show?" Local data almost always contradicts English price.

PATTERN B — resolution_wording_trap (NEGATIVE — AVOID or SHORT):
  Market: "Will a new Gemini flagship be released by May 22?" Price: 8.5% YES.
  Trap: YES requires a 'reasoning flagship model'. Flash/Nano tier is EXPLICITLY excluded.
  Google released Gemini 3.5 Flash — non-qualifying. Market briefly rose to 2.1¢ then resolved NO.
  YOUR JOB: When YES criteria uses "flagship", "major", "leading", "significant" — these are
  WORDING TRAPS. Flag as resolution_wording_trap. The obvious event often doesn't qualify.

PATTERN C — tight_threshold_momentum (EXIT DISCIPLINE):
  Market: "Will Figure F03 push 250k packages by May 21?" Entry: 30%.
  Robots were at 97% of pace target. Market rose to 98% on live stream momentum.
  Resolved NO. Selling at 72% (above our 65% estimate) was correct.
  YOUR JOB: Production/count markets at 80-98% price are usually narrative bubbles.
  Pace math is often tighter than the crowd assumes. These are SHORT opportunities.

════════════════════════════════════════════════════════
HOW TO THINK ABOUT EACH MARKET
════════════════════════════════════════════════════════

Step 1 — LANGUAGE CHECK: Is this market about a non-English entity/region?
  → If YES: What do LOCAL polls/surveys show? Korean, Israeli, Turkish, Romanian markets
    are systematically mispriced because English traders can't access local polling data.
  → Look for: candidate names, local political parties, regional entities.

Step 2 — RESOLUTION TRAP CHECK: Does the YES criteria use vague qualitative words?
  → "flagship", "major", "leading", "significant", "historic", "substantial"
  → These words create resolution ambiguity. The most obvious event often doesn't qualify.
  → Flag these as resolution_wording_trap and suggest NO or SKIP.

Step 3 — CATALYST TIMING: Is there a specific upcoming event that resolves this?
  → Election on specific date, scheduled meeting, announced deadline, countdown event.
  → If the event is already scheduled and evidence points one way — this is actionable.
  → "Sleeping" markets (flat price, low volume) with known upcoming catalysts = hidden gems.

Step 4 — NARRATIVE BUBBLE SHORT: Is the market at 75-98% on something uncertain?
  → Production targets, legislative timelines, complex multi-condition requirements.
  → When market prices 90% YES on something with 50% true probability = SHORT SIGNAL.
  → Crowd overconfidence on countable events is the most common bubble pattern.

Step 5 — STRUCTURAL ANALYSIS: For count/production/legislative markets specifically:
  → Does the pace math actually support the YES price?
  → Can the legislative process physically complete before the deadline?
  → These structural checks catch markets that look plausible but are mechanically constrained.

════════════════════════════════════════════════════════
HARD RULES
════════════════════════════════════════════════════════
- DO NOT select on cross-platform divergence alone — all platforms can be wrong simultaneously
- DO NOT select because of large order activity — Polymarket degens put big money on bad bets
- DO NOT select moonshots (<5%) without a SPECIFIC articulated mechanism
- DO select any market where you can name the EXACT information the crowd is missing
- DO include NO (short) picks when you see clear narrative bubble or resolution trap
- TRUST narrative intuition over any numerical formula
- PRIORITIZE markets with specific upcoming events in the resolution window

Markets:
{markets_text}

════════════════════════════════════════════════════════
OUTPUT FORMAT
════════════════════════════════════════════════════════
Respond with ONLY a JSON array, sorted by conviction (most convinced first).
Select exactly {top_n} markets. Use this exact structure:
[
  {{
    "rank": 1,
    "condition_id": "exact_condition_id_from_market_header",
    "reasoning": "2-3 sentences: the SPECIFIC information the crowd is missing, what you found, why price is wrong",
    "hidden_gem_type": "language_polling_edge OR resolution_wording_trap OR tight_threshold_momentum OR narrative_bubble_short OR sleeper_catalyst OR local_knowledge_edge OR stale_consensus OR legislative_timeline_impossible OR structural_ceiling_no OR crowd_bias OR contrarian_fundamentals",
    "suggested_direction": "YES or NO"
  }}
]

For hidden_gem_type — choose the MOST SPECIFIC type:
  language_polling_edge      — local polls contradict English market price
  resolution_wording_trap    — YES criteria technically excludes the most likely event (→ NO)
  tight_threshold_momentum   — pace math is tight, market at 70-98% on uncertain outcome
  narrative_bubble_short     — crowd overconfident, price >> true probability (→ NO)
  sleeper_catalyst           — specific known upcoming event not yet priced in
  local_knowledge_edge       — insider/local knowledge unavailable to English traders
  stale_consensus            — price stuck, situation changed, crowd hasn't noticed
  legislative_timeline_impos — process cannot complete before deadline (→ NO)
  structural_ceiling_no      — physical/mechanical constraint makes YES unreachable
  crowd_bias                 — thin market systematically mis-priced by attention gap
  contrarian_fundamentals    — fundamental analysis contradicts dominant narrative"""

    try:
        print(f"\n[LLM] Sending {len(candidates)} candidates for vibe-check (model: {adapter.model})...")
        response = adapter.chat(prompt)
        # Extract JSON array (handle markdown code blocks)
        match = re.search(r'\[[\s\S]*?\](?=\s*$|\s*```)', response) or re.search(r'\[[\s\S]*\]', response)
        if not match:
            print("[LLM] Could not extract JSON from response — falling back to pre-score ranking")
            return None
        ranked = json.loads(match.group(0))
        if not isinstance(ranked, list) or not ranked:
            return None

        # Build cid → candidate lookup
        cid_map = {c["condition_id"]: c for c in candidates}
        result: list[dict] = []
        seen_cids: set[str] = set()
        for item in ranked:
            cid = item.get("condition_id", "")
            if cid in cid_map and cid not in seen_cids:
                seen_cids.add(cid)
                c = dict(cid_map[cid])  # copy to avoid mutating original
                c["llm_reasoning"]          = item.get("reasoning", "")
                c["hidden_gem_type"]        = item.get("hidden_gem_type", "unknown")
                c["llm_suggested_direction"] = item.get("suggested_direction", c.get("suggested_side", "YES"))
                # Override suggested_side with LLM direction (it had full context)
                c["suggested_side"] = c["llm_suggested_direction"]
                result.append(c)

        print(f"[LLM] Vibe-check complete: {len(result)} candidates ranked")
        if result:
            print("[LLM] Top picks:")
            for r in result[:5]:
                print(f"  #{r.get('rank','?')} [{r['hidden_gem_type']}] {r['question'][:60]}")
                print(f"      → {r['llm_reasoning'][:120]}...")
        return result[:top_n] if result else None

    except Exception as _e:  # noqa: BLE001
        print(f"[LLM] Vibe-check error: {_e} — falling back to pre-score ranking")
        return None


# ── Main triage logic ────────────────────────────────────────────────────────────

async def _fetch_all_markets() -> list:
    """Dual scan: top markets by volume + neglected markets by liquidity ascending."""
    all_markets = []
    seen_cids: set[str] = set()

    async with httpx.AsyncClient(timeout=30) as client:
        # Pass 1: Top markets sorted by volume (high-volume popular markets)
        print(f"  Pass 1: Scanning top {MAX_PAGES_POPULAR * 100:,} markets (volume ranked)...")
        popular = await fetch_active_markets(
            client,
            max_pages=MAX_PAGES_POPULAR,
            sort="volume",
            min_volume_usd=MIN_VOLUME_DISCOVERY,
            days_min=MIN_DAYS_TO_RESOLUTION,
            days_max=MAX_DAYS_TO_RESOLUTION,
            discovery_mode=True,
            min_yes_price=MIN_YES_PRICE_DISCOVERY,
            max_yes_price=MAX_YES_PRICE_DISCOVERY,
        )
        for m in popular:
            if m.condition_id not in seen_cids:
                seen_cids.add(m.condition_id)
                all_markets.append(m)
        print(f"    -> Found {len(popular)} markets (pass 1)")
        print(f"       filter stats: {markets_mod.LAST_FETCH_STATS}")
        FETCH_AUDIT.append({
            "pass": "volume_desc",
            "requested_rows": MAX_PAGES_POPULAR * 100,
            "accepted_rows": len(popular),
            "filter_stats": dict(markets_mod.LAST_FETCH_STATS),
        })

        # Pass 2: Neglected markets (liquidity ascending = least-watched first)
        print(f"  Pass 2: Scanning {MAX_PAGES_NEGLECTED * 100:,} neglected markets (liquidity ascending)...")
        neglected = await fetch_active_markets(
            client,
            max_pages=MAX_PAGES_NEGLECTED,
            sort="liquidity_asc",
            min_volume_usd=MIN_VOLUME_NEGLECTED_DISCOVERY,
            days_min=MIN_DAYS_TO_RESOLUTION,
            days_max=MAX_DAYS_TO_RESOLUTION,
            discovery_mode=True,
            min_yes_price=MIN_YES_PRICE_DISCOVERY,
            max_yes_price=MAX_YES_PRICE_DISCOVERY,
        )
        added = 0
        for m in neglected:
            if m.condition_id not in seen_cids:
                seen_cids.add(m.condition_id)
                all_markets.append(m)
                added += 1
        print(f"    -> Found {added} new markets (pass 2, {len(neglected) - added} dupes)")
        print(f"       filter stats: {markets_mod.LAST_FETCH_STATS}")
        FETCH_AUDIT.append({
            "pass": "liquidity_asc",
            "requested_rows": MAX_PAGES_NEGLECTED * 100,
            "accepted_rows": len(neglected),
            "new_unique_rows": added,
            "duplicate_rows": len(neglected) - added,
            "filter_stats": dict(markets_mod.LAST_FETCH_STATS),
        })

    return all_markets


async def _run_triage() -> list[dict]:
    """Fetch markets from both passes, apply strategies, score, rank."""
    print(f"Scanning Polymarket (dual-pass: up to {(MAX_PAGES_POPULAR + MAX_PAGES_NEGLECTED) * 100:,} total)...")

    with db.connect() as conn:
        open_cids = _open_position_cids(conn) if SKIP_OPEN_POSITIONS else set()
        reviewed_cids = _recently_reviewed_cids(conn, SKIP_RECENTLY_REVIEWED_DAYS)
        b_researched = _b_researched_cids(conn, SKIP_B_RESEARCHED_DAYS)
        skip_cids = open_cids | reviewed_cids | b_researched
        if b_researched:
            print(f"  B-researched skip: {len(b_researched)} markets (last {SKIP_B_RESEARCHED_DAYS}d)")

    markets = await _fetch_all_markets()

    print(f"  Total unique markets in scope: {len(markets)}")
    print(f"  Markets to skip: {len(skip_cids)} (open positions + recently reviewed)")

    # Vertical distribution report
    vertical_counts: dict[str, int] = {}
    for m in markets:
        v = m.vertical or "other"
        vertical_counts[v] = vertical_counts.get(v, 0) + 1
    print("  Vertical breakdown: " + " | ".join(
        f"{v}:{n}" for v, n in sorted(vertical_counts.items(), key=lambda x: -x[1])
    ))

    with db.connect() as conn:
        # Upsert all markets + capture price snapshots for stale_price strategy.
        # One snapshot per market per 12h (idempotent: skip if recent exists).
        snap_added = 0
        _now_iso = datetime.now(timezone.utc).isoformat()
        # Pre-fetch condition_ids that already have a snapshot within the last 12h
        _recent_snaps: set[str] = {
            r[0] for r in conn.execute("""
                SELECT DISTINCT condition_id FROM snapshots
                WHERE ABS((julianday(captured_at) - julianday(?)) * 24.0) < 12.0
            """, (_now_iso,)).fetchall()
        }
        for m in markets:
            try:
                db.upsert_market(
                    conn,
                    condition_id=m.condition_id,
                    question=m.question,
                    slug=m.slug,
                    end_date=m.end_date,
                    vertical=m.vertical,
                )
            except Exception:
                pass
            if m.condition_id in _recent_snaps:
                continue  # skip: snapshot already taken today
            try:
                db.add_snapshot(
                    conn,
                    condition_id=m.condition_id,
                    yes_price=m.yes_price,
                    volume=m.volume,
                    liquidity=m.liquidity,
                    no_price=m.no_price,
                    best_bid=m.best_bid,
                    best_ask=m.best_ask,
                    spread=m.spread,
                    yes_entry_price=m.yes_entry_price,
                    no_entry_price=m.no_entry_price,
                    source="command_g_scan",
                )
                snap_added += 1
            except Exception:
                pass
        conn.commit()
        if snap_added:
            print(f"  Price snapshots captured: {snap_added} (builds stale_price history)")

        candidates = []
        for m in markets:
            if m.condition_id in skip_cids:
                continue

            mdict = {
                "condition_id": m.condition_id,
                "question": m.question,
                "slug": m.slug,
                "vertical": m.vertical,
                "theme_tags": m.theme_tags or classify_theme_tags(m.question),
                "yes_price": m.yes_price,
                "no_price": m.no_price,
                "best_bid": m.best_bid,
                "best_ask": m.best_ask,
                "spread": m.spread,
                "yes_entry_price": m.yes_entry_price,
                "no_entry_price": m.no_entry_price,
                "volume": m.volume,
                "liquidity": m.liquidity,
                "days_to_end": m.days_to_end,
                "end_date": m.end_date[:10] if m.end_date else None,
                # Use Gamma's startDate as market age anchor for attention_gap_score.
                # This is when the market was CREATED on Polymarket, not our DB timestamp.
                "first_seen_at": m.start_date,
            }

            # Strategy matching (stale_price now uses real price history)
            matched: set[str] = set()
            if cheap_optionality(mdict):
                matched.add("cheap_optionality")
            if compounder_research_candidate(mdict):
                matched.add("compounder_research_candidate")
            if low_volume_research_sweetspot(mdict):
                matched.add("low_volume_research_sweetspot")
            # Get real price history for stale_price
            ps = _price_series(conn, m.condition_id)
            if stale_price(mdict, ps):
                matched.add("stale_price")

            # G_scan is BROAD — we no longer require a strategy match.
            # Any market with volume >= MIN_VOLUME_DISCOVERY and in the time window
            # qualifies. G_rank (run_command_g2.py) does the real quality filtering.
            # matched is still computed for scoring bonus but not required.

            score = _score_candidate(mdict, matched, conn)
            if score < MIN_SCORE:
                continue

            archetype = _classify_archetype(mdict, matched)
            side = _suggest_side(mdict)
            queries = _first_queries(mdict)
            kc = _kill_criteria_template(mdict)  # fast template; Ollama called later for top-N
            lang = _local_language(m.question)
            _, ia_score = _detect_info_asymmetry(m.question)

            candidates.append({
                "condition_id": m.condition_id,
                "question": m.question,
                "slug": m.slug,
                "vertical": m.vertical,
                "theme_tags": mdict["theme_tags"],
                "yes_price": m.yes_price,
                "no_price": m.no_price or round(1.0 - m.yes_price, 4),
                "spread": m.spread,
                "volume": round(m.volume, 0),
                "liquidity": round(m.liquidity or 0, 0),
                "days_to_end": round(m.days_to_end, 1),
                "end_date": m.end_date[:10] if m.end_date else None,
                "discoverability_score": score,
                "matched_strategies": sorted(matched),
                "archetype": archetype,
                "suggested_side": side,
                "first_queries": queries,
                "kill_criteria": kc,
                "local_language": lang,
                "information_asymmetry": ia_score,
                "polymarket_url": f"https://polymarket.com/event/{m.slug}" if m.slug else None,
                "metaculus_divergence": None,  # filled in for top-N
                "predictit_divergence": None,   # filled in for top-N
                "manifold_divergence": None,    # filled in for top-N
                "order_flow_imbalance": None,  # filled in for top-N
                "tokens": m.tokens,            # CLOB token IDs (YES=0, NO=1)
            })

    # Sort by base pre-score descending (used only as initial ordering for context collection,
    # NOT as the final ranking — that is done by the LLM vibe-check below).
    candidates.sort(key=lambda x: x["discoverability_score"], reverse=True)

    # ── Write candidates_wide.json for G_rank (run_command_g2.py) ─────────────
    # G_scan outputs the top CANDIDATES_WIDE_N by base score.
    # G_rank reads this file and applies real hidden-gem criteria to pick the best 20-25.
    wide_path = os.path.join(os.path.dirname(__file__), "candidates_wide.json")
    if G_WIDE_STRATIFIED:
        wide_candidates, wide_selection_summary = _select_stratified_wide_pool(candidates, CANDIDATES_WIDE_N)
    else:
        wide_candidates = candidates[:CANDIDATES_WIDE_N]
        wide_selection_summary = {
            "stratified": False,
            "target_n": CANDIDATES_WIDE_N,
            "selected_n": len(wide_candidates),
            "bucket_counts": {"top_discoverability": len(wide_candidates)},
        }
    with open(wide_path, "w", encoding="utf-8") as _wf:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_universe_total": len(candidates),
            "market_fetch_audit": FETCH_AUDIT,
            "wide_selection_summary": wide_selection_summary,
            "total": len(wide_candidates),
            "candidates": wide_candidates,
        }, _wf, indent=2, ensure_ascii=False, default=str)
    print(f"\n[G_scan] {len(wide_candidates)} candidates written to candidates_wide.json")
    print(f"  Wide selection: {wide_selection_summary}")
    print(f"  Next: run run_command_g2.py to rank and select hidden gems")

    # Enrich a wider pool for context collection.
    # We go deeper (TOP_N * 5) so the LLM has more diversity to choose from —
    # hidden gems are often NOT at the top of the mathematical pre-score.
    enrich_pool = candidates[:TOP_N * 5]

    # ── Pre-load divergence anchor market lists (one call each, reused per candidate) ──
    print("\nLoading divergence anchors (PredictIt / Manifold / Kalshi / GJO)...")
    try:
        from lib.integrations.predictit import fetch_all_markets as _pi_fetch
        _pi_markets = _pi_fetch()
        print(f"  PredictIt: {len(_pi_markets)} active contracts loaded")
    except Exception:  # noqa: BLE001
        _pi_markets = []
        print("  PredictIt: unavailable (skipped)")
    try:
        from lib.integrations.manifold import fetch_all_markets as _mf_fetch
        _mf_markets = _mf_fetch()
        print(f"  Manifold:  {len(_mf_markets)} open markets loaded")
    except Exception:  # noqa: BLE001
        _mf_markets = []
        print("  Manifold: unavailable (skipped)")
    try:
        from lib.integrations.kalshi import fetch_all_markets as _kalshi_fetch
        _kalshi_markets = _kalshi_fetch()
        print(f"  Kalshi:    {len(_kalshi_markets)} open contracts loaded")
    except Exception:  # noqa: BLE001
        _kalshi_markets = []
        print("  Kalshi: unavailable (skipped)")
    try:
        from lib.integrations.gjo import fetch_all_questions as _gjo_fetch
        _gjo_questions = _gjo_fetch()
        print(f"  GJO:       {len(_gjo_questions)} superforecaster questions loaded")
    except Exception:  # noqa: BLE001
        _gjo_questions = []
        print("  GJO: unavailable (skipped)")

    # ── Context collection phase ──────────────────────────────────────────────────
    # Collect ALL external signals (divergence, OFI, whale) into a contexts dict.
    # These are CONTEXT for the LLM, not score multipliers.
    # The score is NEVER modified here — it remains the raw pre-score from above.
    contexts: dict[str, dict] = {}   # condition_id → {metaculus, predictit, manifold, ...}

    enrich_count = min(TOP_N * 3, len(enrich_pool))
    print(f"\nCollecting context for top {enrich_count} candidates "
          f"(Ollama kill criteria + divergence anchors + CLOB)...")

    for i, c in enumerate(enrich_pool[:enrich_count]):
        cid = c["condition_id"]
        ctx: dict = {}

        # ── Ollama enrichment: kill criteria + thesis (useful regardless of ranking) ──
        draft = candidate_research_draft(c)
        if draft:
            c["ollama_draft"] = draft
            if isinstance(draft.get("thesis"), str) and draft["thesis"].strip():
                c["thesis"] = draft["thesis"].strip()
            if isinstance(draft.get("why_signal_may_miss"), str) and draft["why_signal_may_miss"].strip():
                c["why_signal_may_miss"] = draft["why_signal_may_miss"].strip()
            if isinstance(draft.get("disconfirming_angle"), str) and draft["disconfirming_angle"].strip():
                c["disconfirming_angle"] = draft["disconfirming_angle"].strip()
            if isinstance(draft.get("local_language"), str) and draft["local_language"].strip():
                c["local_language"] = draft["local_language"].strip()
            if isinstance(draft.get("kill_criteria"), list):
                kc = [str(x).strip() for x in draft["kill_criteria"] if str(x).strip()]
                if len(kc) >= 3:
                    c["kill_criteria"] = kc[:5]
            if isinstance(draft.get("first_queries"), list):
                queries = [str(x).strip() for x in draft["first_queries"] if str(x).strip()]
                if queries:
                    c["first_queries"] = queries[:5]
            print(f"  [{i+1}] Ollama draft: {c['question'][:55]}")
        else:
            end_date_str = c.get("end_date") or ""
            ollama_kc = _kill_criteria_ollama(c["question"], c["suggested_side"], end_date=end_date_str)
            if ollama_kc:
                c["kill_criteria"] = ollama_kc

        # ── Metaculus (context only — no score change) ───────────────────────
        if i < 12:
            divergence = _metaculus_divergence_check(c["question"], c["yes_price"])
            if divergence:
                c["metaculus_divergence"] = divergence
                ctx["metaculus"] = divergence
                print(f"  [{i+1}] Metaculus: Poly={c['yes_price']:.2f} vs "
                      f"Meta={divergence['metaculus_prob']:.2f} "
                      f"(Δ{divergence['divergence']:.0%}) — context only")

        # ── PredictIt (context only) ─────────────────────────────────────────
        pi_div = _predictit_divergence_check(c["question"], c["yes_price"], _pi_markets)
        if pi_div:
            c["predictit_divergence"] = pi_div
            ctx["predictit"] = pi_div
            print(f"  [{i+1}] PredictIt: Poly={c['yes_price']:.2f} vs "
                  f"PI={pi_div['pi_price']:.2f} (Δ{pi_div['divergence']:.0%}) — context only")

        # ── Manifold (context only) ──────────────────────────────────────────
        mf_div = _manifold_divergence_check(c["question"], c["yes_price"], _mf_markets)
        if mf_div:
            c["manifold_divergence"] = mf_div
            ctx["manifold"] = mf_div
            print(f"  [{i+1}] Manifold: Poly={c['yes_price']:.2f} vs "
                  f"MF={mf_div['mf_prob']:.2f} (Δ{mf_div['divergence']:.0%}) — context only")

        # ── Kalshi (context only) ────────────────────────────────────────────
        kalshi_div = _kalshi_divergence_check(c["question"], c["yes_price"], _kalshi_markets)
        if kalshi_div:
            c["kalshi_divergence"] = kalshi_div
            ctx["kalshi"] = kalshi_div
            print(f"  [{i+1}] Kalshi: Poly={c['yes_price']:.2f} vs "
                  f"Kalshi={kalshi_div['kalshi_price']:.2f} (Δ{kalshi_div['divergence']:.0%}) — context only")

        # ── GJO (context only) ───────────────────────────────────────────────
        gjo_div = _gjo_divergence_check(c["question"], c["yes_price"], _gjo_questions)
        if gjo_div:
            c["gjo_divergence"] = gjo_div
            ctx["gjo"] = gjo_div
            print(f"  [{i+1}] GJO: Poly={c['yes_price']:.2f} vs "
                  f"GJO={gjo_div['gjo_prob']:.2f} (Δ{gjo_div['divergence']:.0%}) — context only")

        # ── GDELT Cloud spike (context only) ─────────────────────────────────
        if i < 20:
            try:
                from lib.integrations.tgstat import _extract_key_terms as _gkt  # noqa: PLC0415
                from lib.integrations.gdelt_cloud import event_density_spike  # noqa: PLC0415
                _gdelt_q = _gkt(c["question"], n=4)
                if _gdelt_q:
                    _spike = event_density_spike(_gdelt_q, days=7, spike_threshold=1.5)
                    if _spike:
                        c["gdelt_cloud_spike"] = _spike
                        ctx["gdelt_spike"] = _spike
                        print(f"  [{i+1}] GDELT☁ news spike x{_spike['spike_ratio']:.2f} "
                              f"(sig={_spike['latest_significance']:.3f}) — context only")
            except Exception:  # noqa: BLE001
                pass

        # ── CLOB order flow imbalance (context only) ─────────────────────────
        if i < 25:
            tokens = c.get("tokens") or []
            ofi_data = _order_flow_imbalance(tokens)
            if ofi_data:
                c["order_flow_imbalance"] = ofi_data
                ctx["ofi"] = ofi_data
                ofi_val = ofi_data["ofi"]
                if abs(ofi_val) > 0.25:
                    direction = "BUY" if ofi_val > 0 else "SELL"
                    print(f"  [{i+1}] CLOB OFI {ofi_val:+.2f} ({direction} pressure) "
                          f"bid=${ofi_data['bid_depth']:.0f} ask=${ofi_data['ask_depth']:.0f} "
                          f"— context only")

        # ── Structural analysis — pace ceiling + legislative timeline ────────
        # Flags markets with hard structural constraints.
        # ZERO score impact — purely informational context for LLM.
        if i < 30:
            try:
                from lib.analysis.pace_calculator import detect_pace_market  # noqa: PLC0415
                from lib.analysis.legislative_calculator import (  # noqa: PLC0415
                    detect_legislative_market, guess_process_template,
                )
                _q = c.get("question", "")
                _days = c.get("days_to_end", 0) or 0

                if detect_pace_market(_q):
                    ctx["structural_type"] = "production_count_market"
                    ctx["structural_note"] = (
                        "PACE MARKET: Verify current count, elapsed time, and target. "
                        "Check if baseline_rate * hours_remaining >= target."
                    )

                elif detect_legislative_market(_q) and _days > 0:
                    _leg = guess_process_template(_q, _days)
                    if _leg:
                        ctx["structural_type"] = "legislative_market"
                        ctx["structural_ceiling"] = _leg.is_structural_ceiling
                        ctx["legislative_timeline_type"] = _leg.timeline_type
                        ctx["legislative_safety_margin"] = round(_leg.safety_margin, 2)
                        if _leg.is_structural_ceiling:
                            print(
                                f"  [{i+1}] ⚖️  LEGISLATIVE {_leg.timeline_type}: "
                                f"needs {_leg.min_total_days:.0f}d min vs {_days:.0f}d deadline "
                                f"(margin={_leg.safety_margin:.2f}x) — structural context"
                            )
                            # Add to market card so LLM sees it
                            c["structural_ceiling"] = True
                            c["structural_type"] = _leg.timeline_type
            except Exception:  # noqa: BLE001
                pass

        # ── Whale detection (INFORMATIONAL ONLY — zero score impact) ─────────
        # Logged to triage_scores for learning/calibration.
        # Does NOT change discoverability_score. Does NOT trigger escalation.
        # Many large Polymarket bets are degens, not insiders.
        if i < 20:
            _whale_tokens = c.get("tokens") or []
            _whale = _whale_check(_whale_tokens, c["condition_id"])
            if _whale:
                c["whale_alert"] = True
                c["whale_signals"] = len(_whale.signals)
                c["whale_max_usd"] = _whale.max_size_usd
                c["whale_dominant"] = _whale.dominant_side
                c["whale_escalate"] = _whale.escalate
                ctx["whale"] = {
                    "max_usd": _whale.max_size_usd,
                    "dominant": _whale.dominant_side,
                    "signals_count": len(_whale.signals),
                    "escalate": _whale.escalate,
                }
                _esc_tag = " (escalating pattern)" if _whale.escalate else ""
                print(f"  [{i+1}] 🐋 Whale detected: {len(_whale.signals)} signals | "
                      f"${_whale.max_size_usd:,.0f} max | {_whale.dominant_side} side"
                      f"{_esc_tag} — informational only, no score impact")

        contexts[cid] = ctx

    # ── LLM vibe-check: the actual ranking ────────────────────────────────────────
    # Pass the enriched pool + all collected context to the LLM.
    # The LLM reads markets as narratives and picks hidden gems through intuition,
    # not formula scoring. This is the core philosophy change.
    print(f"\n{'='*60}")
    print("LLM VIBE-CHECK: Finding hidden gems through narrative analysis")
    print(f"{'='*60}")

    llm_ranked = _llm_vibe_check(enrich_pool[:enrich_count], contexts, TOP_N)

    if llm_ranked:
        # LLM produced a ranking — apply diversity filter on top to avoid
        # one country/event dominating all slots, then return.
        print(f"\n[LLM] Using LLM-ranked candidates (diversity filter applied)")
        top_candidates = _select_diverse_top_n(llm_ranked, TOP_N, _MAX_PER_CLUSTER)
        # Mark these as LLM-ranked so downstream can display appropriately
        for c in top_candidates:
            c.setdefault("ranking_method", "llm_vibe_check")
    else:
        # LLM unavailable or failed — fall back to pure pre-score ranking.
        # NOTE: even in fallback, whale/OFI/divergence do NOT boost the score
        # (they were never added above). The fallback uses the raw base pre-score only.
        print("\n[FALLBACK] Ollama unavailable — using base pre-score ranking (no whale/OFI boost)")
        enrich_pool.sort(key=lambda x: x["discoverability_score"], reverse=True)
        top_candidates = _select_diverse_top_n(enrich_pool, TOP_N, _MAX_PER_CLUSTER)
        for c in top_candidates:
            c.setdefault("ranking_method", "pre_score_fallback")

    return top_candidates


# ── Auto-generate Command A queue file ──────────────────────────────────────────

def _write_forager_queue(candidates: list[dict], path: str, output_n: int | None = None) -> None:
    """Write a ready-to-run Command A forager_queue Python file.

    Args:
        candidates: ranked candidate list (will be sliced to output_n)
        path: output file path
        output_n: how many candidates to write; defaults to TOP_N (G_scan default)
    """
    _n = output_n if output_n is not None else TOP_N
    lines = [
        '"""Auto-generated Command A queue from Command G triage.',
        f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
        'Run: cd C:\\\\Signal\\\\bot && python forager_queue_auto.py',
        '"""',
        'import sys, os, json',
        'sys.path.insert(0, ".")',
        'from dotenv import load_dotenv; load_dotenv(".env")',
        'import db; db.init()',
        'from tools.workflows import _record_workflow_step',
        '',
        '# Auto-discovered candidates — review before running Command B',
        'forager_queue = [',
    ]

    for i, c in enumerate(candidates[:_n]):
        priority = "P0" if i < 3 else ("P1" if i < 7 else "P2")
        anchor_parts: list[str] = []
        if c.get("metaculus_divergence"):
            d = c["metaculus_divergence"]
            anchor_parts.append(
                f"Metaculus {d['metaculus_prob']*100:.0f}% vs "
                f"Polymarket {c['yes_price']*100:.0f}% ({d['divergence']*100:.0f}pp gap)"
            )
        if c.get("predictit_divergence"):
            d = c["predictit_divergence"]
            anchor_parts.append(
                f"PredictIt {d['pi_price']*100:.0f}% vs "
                f"Polymarket {c['yes_price']*100:.0f}% ({d['divergence']*100:.0f}pp gap)"
            )
        if c.get("manifold_divergence"):
            d = c["manifold_divergence"]
            anchor_parts.append(
                f"Manifold {d['mf_prob']*100:.0f}% vs "
                f"Polymarket {c['yes_price']*100:.0f}% ({d['divergence']*100:.0f}pp gap)"
            )
        anchor_note = (". ".join(anchor_parts) + ". ") if anchor_parts else ""
        # Thesis: prefer LLM reasoning (has full narrative context) over generic anchor note
        llm_reason = c.get("llm_reasoning", "")
        hidden_gem_type = c.get("hidden_gem_type", "unknown")
        ranking_method = c.get("ranking_method", "unknown")
        if llm_reason:
            thesis = llm_reason
        else:
            thesis = (
                f"{anchor_note}Suggested side: {c['suggested_side']}. "
                f"Strategies: {', '.join(c['matched_strategies'])}. "
                f"Vertical: {c['vertical']}."
            )
        thesis = c.get("thesis") or thesis
        why_signal_may_miss = c.get("why_signal_may_miss") or "Check local language sources."
        disconfirming_angle = c.get("disconfirming_angle") or "Review kill criteria below."

        kc_json = json.dumps(c["kill_criteria"], ensure_ascii=False)
        queries_json = json.dumps(c["first_queries"], ensure_ascii=False)
        draft_json = json.dumps(c.get("ollama_draft") or {}, ensure_ascii=False)

        # Resolve region-specific seed URLs for this candidate
        lang = c.get("local_language") or ""
        try:
            from lib.integrations.region_sources import get_seed_urls_for_language as _get_seed_urls  # noqa: PLC0415
            from lib.integrations.telegram_web import channels_for_language as _tg_channels  # noqa: PLC0415
            region_urls = _get_seed_urls(lang, max_sources=8, include_telegram=True) if lang and lang != "english" else []
            tg_channels = _tg_channels(lang, max_channels=4) if lang and lang != "english" else []
        except Exception:  # noqa: BLE001
            region_urls = []
            tg_channels = []
        region_urls_json = json.dumps(region_urls, ensure_ascii=False)
        tg_channels_json = json.dumps(tg_channels, ensure_ascii=False)
        tokens_json = json.dumps(c.get("tokens") or [], ensure_ascii=False)
        whale_alert_val = "True" if c.get("whale_alert") else "False"

        lines.extend([
            '    {',
            f'        "priority": "{priority}",',
            f'        "condition_id": "{c["condition_id"]}",',
            f'        "question": {json.dumps(c["question"])},',
            f'        "yes_price": {c["yes_price"]},',
            f'        "no_price": {c["no_price"]},',
            f'        "end_date": "{c["end_date"] or ""}",',
            f'        "spread": {c["spread"] or "None"},',
            f'        "archetype": "{c["archetype"]}",',
            f'        "vertical": "{c["vertical"]}",',
            f'        "thesis": {json.dumps(thesis)},',
            f'        "why_signal_may_miss": {json.dumps(why_signal_may_miss)},',
            f'        "disconfirming_angle": {json.dumps(disconfirming_angle)},',
            f'        "kill_criteria": {kc_json},',
            f'        "seed_query": {json.dumps(c["first_queries"][0] if c["first_queries"] else c["question"])},',
            f'        "first_queries": {queries_json},',
            f'        "local_language": {json.dumps(c["local_language"])},',
            f'        "region_urls": {region_urls_json},',
            f'        "telegram_channels": {tg_channels_json},',
            f'        "tokens": {tokens_json},',
            # whale_alert is present for informational display but has no downstream effect
            f'        "whale_alert": {whale_alert_val},',
            f'        "whale_max_usd": {c.get("whale_max_usd") or 0},',
            f'        "whale_dominant": {json.dumps(c.get("whale_dominant") or "")},',
            # LLM reasoning fields — the "why" behind this selection
            f'        "hidden_gem_type": {json.dumps(hidden_gem_type)},',
            f'        "llm_reasoning": {json.dumps(llm_reason)},',
            f'        "ranking_method": {json.dumps(ranking_method)},',
            f'        "ollama_draft": {draft_json},',
            '    },',
        ])

    lines.extend([
        ']',
        '',
        'WF_ID = 7',
        '_record_workflow_step(',
        '    WF_ID, "forager_queue_built",',
        '    allowed_writes=["forager_threads"], writes_count=len(forager_queue),',
        '    output_json={"total_candidates": len(forager_queue),',
        '                 "queue": [{"priority": c["priority"], "question": c["question"][:60]}',
        '                           for c in forager_queue]},',
        ')',
        'print(f"Forager queue loaded: {len(forager_queue)} candidates")',
        'for c in forager_queue:',
        '    print(f"  [{c[\'priority\']}] {c[\'question\'][:65]}")',
        '    print(f"        yes={c[\'yes_price\']} | end={c[\'end_date\']}")',
    ])

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nAuto-queue written to: {path}")


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("COMMAND G v2: Market Triage — Full Universe Scan")
    print("=" * 70)
    print(f"  Dual-pass scan | TOP_N={TOP_N} | min_score={MIN_SCORE}")
    print(f"  discovery_mode=True (all markets, incl. economics/crypto/health)")
    print()

    wf_id = _start_workflow_log(
        "market_triage_discovery_v2",
        "Market Triage v2 — Full Universe Scan",
        input_payload={"top_n": TOP_N, "min_score": MIN_SCORE},
        agent_name="claude-code",
        notes="Command G v2 — dual-pass scan with economics vertical + Ollama enrichment",
    )
    print(f"Workflow run: {wf_id}\n")

    candidates = asyncio.run(_run_triage())
    top = candidates[:TOP_N]

    _record_workflow_step(
        wf_id, "discovery_scan",
        allowed_writes=["markets"],
        writes_count=len(candidates),
        output_json={
            "total_candidates": len(candidates),
            "top_n": len(top),
            "strategy_coverage": {
                s: sum(1 for c in candidates if s in c["matched_strategies"])
                for s in ["cheap_optionality", "compounder_research_candidate",
                          "low_volume_research_sweetspot", "stale_price"]
            },
        },
    )
    _finish_workflow_log(wf_id, status="completed", output_json={
        "candidates_found": len(candidates),
        "top_score": top[0]["discoverability_score"] if top else 0,
    })

    # ── Print ranked table ─────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"TOP {len(top)} RESEARCH CANDIDATES")
    print(f"{'='*70}\n")

    if not top:
        print("No candidates found. Try: increasing MAX_PAGES or lowering MIN_SCORE.")
        return candidates, wf_id

    ranking_method = top[0].get("ranking_method", "unknown") if top else "unknown"
    print(f"Ranking method: {ranking_method}\n")

    for i, c in enumerate(top, 1):
        strats = "+".join(s.split("_")[0][:4] for s in c["matched_strategies"])
        # Cross-platform divergence (shown as facts, no boost mention)
        anchor_notes: list[str] = []
        if c.get("metaculus_divergence"):
            d = c["metaculus_divergence"]
            anchor_notes.append(f"Meta={d['metaculus_prob']*100:.0f}%")
        if c.get("predictit_divergence"):
            d = c["predictit_divergence"]
            anchor_notes.append(f"PI={d['pi_price']*100:.0f}%")
        if c.get("manifold_divergence"):
            d = c["manifold_divergence"]
            anchor_notes.append(f"MF={d['mf_prob']*100:.0f}%")
        anchor_str = (" | " + " / ".join(anchor_notes) + f" vs Poly={c['yes_price']*100:.0f}%") if anchor_notes else ""
        ia_note = f" [LANG:{c['local_language'].split()[0]}]" if c.get("information_asymmetry", 0) > 0.5 else ""
        # Whale shown as informational tag only, no boost value
        whale_note = " 🐋" if c.get("whale_alert") else ""
        # Hidden gem type from LLM (the key new output)
        gem_type = c.get("hidden_gem_type", "")
        gem_note = f" [{gem_type}]" if gem_type and gem_type != "unknown" else ""
        print(f"{i:2d}. [{c['vertical'][:10]}] {c['question'][:62]}")
        print(f"     YES={c['yes_price']:.3f} | vol=${c['volume']:,.0f} | "
              f"{c['days_to_end']:.0f}d | side={c['suggested_side']}{anchor_str}{ia_note}{whale_note}{gem_note}")
        # Show LLM reasoning (the "why" — most important new output)
        llm_reason = c.get("llm_reasoning", "")
        if llm_reason:
            print(f"     WHY: {llm_reason[:120]}")
        else:
            print(f"     {strats} | {c['archetype']}")
        print(f"     {c['polymarket_url'] or c['condition_id'][:24]}")
        # Show Telegram channels that will be seeded for this candidate
        try:
            from lib.integrations.telegram_web import channels_for_language as _tgcl  # noqa: PLC0415
            lang_here = c.get("local_language") or ""
            tg_here = _tgcl(lang_here, max_channels=3) if lang_here and lang_here != "english" else []
            if tg_here:
                print(f"     TG: {' | '.join('@' + ch for ch in tg_here)}")
        except Exception:  # noqa: BLE001
            pass
        print()

    # ── Score / ranking tracking ───────────────────────────────────────────────
    # Persist per-run data for learning and calibration.
    # whale_max_usd logged for learning (did whale detection correlate with good picks?)
    # but whale data does NOT influence ranking — it's pure informational tracking.
    now_iso = datetime.now(timezone.utc).isoformat()
    drift_notes: list[str] = []
    try:
        with db.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS triage_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id TEXT NOT NULL,
                    run_id INTEGER,
                    captured_at TEXT NOT NULL,
                    discoverability_score REAL NOT NULL,
                    rank INTEGER,
                    metaculus_boost REAL,
                    ofi_boost REAL,
                    ofi REAL,
                    yes_price REAL,
                    whale_boost REAL
                )
            """)
            # Schema migrations (idempotent)
            for _col, _type in [
                ("whale_boost", "REAL"),
                ("whale_max_usd", "REAL"),
                ("hidden_gem_type", "TEXT"),
                ("ranking_method", "TEXT"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE triage_scores ADD COLUMN {_col} {_type}")
                except Exception:  # noqa: BLE001
                    pass  # column already exists

            for rank, c in enumerate(top, 1):
                cid = c["condition_id"]
                score = c["discoverability_score"]
                prev = conn.execute("""
                    SELECT discoverability_score, rank, captured_at FROM triage_scores
                    WHERE condition_id = ?
                    ORDER BY captured_at DESC LIMIT 1
                """, (cid,)).fetchone()
                if prev:
                    delta = score - prev["discoverability_score"]
                    prev_rank = prev["rank"]
                    if abs(delta) >= 5.0:
                        direction = "↑" if delta > 0 else "↓"
                        rank_change = f" (rank {prev_rank}→{rank})" if prev_rank != rank else ""
                        drift_notes.append(
                            f"  {direction} {c['question'][:55]}: {delta:+.1f} pts{rank_change}"
                        )
                conn.execute("""
                    INSERT INTO triage_scores
                        (condition_id, run_id, captured_at, discoverability_score, rank,
                         metaculus_boost, ofi_boost, ofi, yes_price,
                         whale_boost, whale_max_usd, hidden_gem_type, ranking_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cid, wf_id, now_iso, score, rank,
                    None,  # metaculus_boost — no longer computed (context only)
                    None,  # ofi_boost — no longer computed (context only)
                    (c.get("order_flow_imbalance") or {}).get("ofi"),
                    c.get("yes_price"),
                    None,  # whale_boost — zeroed out; whale is informational only
                    c.get("whale_max_usd"),  # kept for learning/calibration
                    c.get("hidden_gem_type"),
                    c.get("ranking_method"),
                ))
            conn.commit()
    except Exception as _e:  # noqa: BLE001
        pass  # score tracking is non-critical; never block main output

    if drift_notes:
        print(f"\n{'='*55}")
        print("SCORE DRIFT (vs last run, |delta| >= 5pts):")
        for note in drift_notes:
            print(note)
        print(f"{'='*55}")

    # ── Write G_scan queue (separate file — G2 owns forager_queue_auto.py) ────
    # G_scan writes to g_scan_queue.py so it doesn't overwrite G2's final output.
    # If running G without G2, copy g_scan_queue.py → forager_queue_auto.py manually.
    gscan_queue_path = os.path.join(os.path.dirname(__file__), "g_scan_queue.py")
    _write_forager_queue(top, gscan_queue_path)

    print(f"\nG_scan queue → g_scan_queue.py ({len(top)} candidates)")
    print(f"Next step: run Command G2 (hidden gem ranker) → forager_queue_auto.py → B:")
    print(f"  python run_command_g2.py")
    print(f"  python run_command_b.py")
    print(f"\nWorkflow run: {wf_id}")
    return candidates, wf_id


if __name__ == "__main__":
    candidates, wf_id = main()
    out_path = os.path.join(os.path.dirname(__file__), "triage_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, default=str)
    print(f"Results saved to {out_path}")
