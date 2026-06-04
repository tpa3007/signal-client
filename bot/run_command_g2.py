"""Command G2 — Hidden Gem Ranker: From Wide Candidates to Research Queue.

Reads candidates_wide.json produced by Command G (G_scan) and applies real
hidden-gem criteria to select the best 20-25 markets for Command B deep research.

The 4 criteria (in priority order):
  1. LANGUAGE ARBITRAGE (20-65%): Non-English market at actionable price.
     Local polls/news diverge from English price. Kim Kyung-soo was the proof.
     Score: +60 (HIGH asymmetry, 20-65%) / +35 (MOD asymmetry) / +20 (moonshot <20%)

  2. CROSS-PLATFORM DIVERGENCE: Polymarket vs Metaculus/PredictIt/Kalshi gap >8pp.
     Different audience, different pricing. Gap = someone is wrong = edge.
     Score: +40 per platform (divergence >= 15pp), +20 (8-15pp)

  3. UPCOMING SPECIFIC CATALYST: Known event within resolution window.
     Election date, scheduled meeting, announced deadline. Timing edge.
     Score: +25 if catalyst within 30 days, +15 within 60 days

  4. NARRATIVE BUBBLE SHORT: Market at 75-98% YES on something uncertain.
     Count/production/legislative ceiling. Crowd overconfidence = short edge.
     Score: +35

Pipeline:
    Command G (G_scan) → candidates_wide.json → **Command G2** → forager_queue_auto.py → Command B

Usage:
    cd C:\\Signal\\bot && python run_command_g2.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")
sys.path.insert(0, "../forager")
from dotenv import load_dotenv
load_dotenv(".env")
load_dotenv("../forager/.env", override=False)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import db; db.init()
from run_command_g import (
    _detect_info_asymmetry,
    _local_language,
    _first_queries,
    _kill_criteria_template,
    _llm_vibe_check,
    _select_diverse_top_n,
    _topic_cluster_key,
    _write_forager_queue,
    _order_flow_imbalance,
    _metaculus_divergence_check,
    _predictit_divergence_check,
    _manifold_divergence_check,
    _kalshi_divergence_check,
    _gjo_divergence_check,
    _whale_check,
    _open_position_cids,
    _b_researched_cids,
    SKIP_B_RESEARCHED_DAYS,
    TOP_N,
)
from tools.workflows import _start_workflow_log, _record_workflow_step, _finish_workflow_log

# ── Configuration ──────────────────────────────────────────────────────────────

OUTPUT_N = int(os.getenv("SIGNAL_G2_OUTPUT_N", "25"))   # wide shortlist saved to g2_top25.json
B_QUEUE_N = int(os.getenv("SIGNAL_G2_B_QUEUE_N", "5"))   # how many go to forager_queue_auto.py (B's budget)
LLM_POOL_N = int(os.getenv("SIGNAL_G2_LLM_POOL", "80"))  # how many G2 sends to LLM vibe-check
MAX_B_QUEUE_PER_EXACT_EVENT = int(os.getenv("SIGNAL_G2_MAX_B_QUEUE_PER_EXACT_EVENT", "1"))

# ── Scoring weights ────────────────────────────────────────────────────────────

# Criterion 1: Language arbitrage
LANG_HIGH_PRIME = 60   # HIGH asymmetry lang + price 20-65%: Korean, Romanian, Turkish elections
LANG_HIGH_FRINGE = 20  # HIGH asymmetry lang + price <20% or >65%: moonshot or compounder
LANG_MOD_PRIME = 35    # MOD asymmetry lang + price 20-65%: French, German, Spanish
LANG_MOD_FRINGE = 10   # MOD asymmetry + fringe price

# Criterion 2: Cross-platform divergence (per platform)
DIV_LARGE = 40   # divergence >= 15pp
DIV_MEDIUM = 20  # divergence 8-15pp
MIN_DIVERGENCE_MATCH_SCORE = float(os.getenv("SIGNAL_G2_MIN_DIVERGENCE_MATCH_SCORE", "0.55"))

# Criterion 3: Upcoming catalyst
CATALYST_NEAR = 25   # specific catalyst within 30 days
CATALYST_FAR = 15    # catalyst within 60 days

# Criterion 4: Narrative bubble SHORT
BUBBLE_SHORT = 35   # 75-98% YES on count/legislative/uncertain market
TACTICAL_BATTLEFIELD_PENALTY = int(os.getenv("SIGNAL_G2_TACTICAL_BATTLEFIELD_PENALTY", "35"))
EXTREME_PRICE_EDGE_CAP = int(os.getenv("SIGNAL_G2_EXTREME_PRICE_EDGE_CAP", "25"))
GEOPOLITICAL_TAIL_EDGE_CAP = int(os.getenv("SIGNAL_G2_GEOPOLITICAL_TAIL_EDGE_CAP", "10"))
PRIVATE_PROVIDER_MECHANICS = int(os.getenv("SIGNAL_G2_PRIVATE_PROVIDER_MECHANICS", "45"))
CENTRAL_BANK_SEQUENCE = int(os.getenv("SIGNAL_G2_CENTRAL_BANK_SEQUENCE", "40"))
RESOLUTION_CLAUSE_MECHANICS = int(os.getenv("SIGNAL_G2_RESOLUTION_CLAUSE_MECHANICS", "40"))
BRACKET_FAMILY_MECHANICS = int(os.getenv("SIGNAL_G2_BRACKET_FAMILY_MECHANICS", "35"))
BRACKET_FAMILY_NEAR_DAYS = int(os.getenv("SIGNAL_G2_BRACKET_FAMILY_NEAR_DAYS", "14"))

# ── Catalyst detection ─────────────────────────────────────────────────────────

# Keywords that indicate a SPECIFIC SCHEDULED event (not vague "by year" language)
_CATALYST_KEYWORDS = [
    # Elections — highly specific
    r"election",
    r"vote", r"ballot",
    r"primary",
    r"referendum",
    r"runoff", r"second round",
    # Meetings — scheduled
    r"summit",
    r"meeting", r"session",
    r"congress", r"parliament",
    r"convention",
    # Deadlines — named
    r"deadline",
    r"by (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
    r"by (?:january|february|march|april|june|july|august|september|october|november|december)",
    r"before (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
    # Hearings / trials
    r"trial",
    r"hearing",
    r"verdict",
    r"sentenc",
    # Appointments
    r"inaugur",
    r"swear",
    r"confirm",
    r"appoint",
    # Central bank meetings
    r"fomc",
    r"rate decision",
    r"rba",
    r"ecb meeting",
]

# Markets where crowd is often overconfident (narrative bubble territory)
_BUBBLE_PATTERNS = [
    # Count / production
    r"will .+ reach \d",
    r"will .+ exceed \d",
    r"will .+ pass \d",
    r"packages? (delivered|shipped|deployed)",
    r"units? (sold|produced|deployed)",
    r"km|miles|kilometers",
    # Legislative ceilings
    r"will .+ (pass|sign|approve|ratify|enact) .* by",
    r"congress will",
    r"senate will",
    r"bill .* pass",
    r"legislation",
    r"amendment",
    # Prediction bubbles (common 80-95% markets that often resolve NO)
    r"stay (?:above|below) \$?\d",
    r"remain (?:above|below)",
    r"not (?:fall|drop|crash)",
]


def _has_specific_catalyst(question: str, days_to_end: float) -> int:
    """Return catalyst score based on question + time remaining.

    Returns 0 if no catalyst detected, CATALYST_NEAR if within 30 days,
    CATALYST_FAR if within 60 days.
    """
    ql = question.lower()
    for pattern in _CATALYST_KEYWORDS:
        if re.search(pattern, ql):
            if days_to_end <= 30:
                return CATALYST_NEAR
            elif days_to_end <= 60:
                return CATALYST_FAR
    return 0


def _is_bubble_candidate(question: str, yes_price: float) -> bool:
    """True if this looks like a narrative bubble SHORT opportunity.

    High-YES market (>=75%) on a count/legislative/production question.
    """
    if yes_price < 0.75:
        return False
    ql = question.lower()
    for pattern in _BUBBLE_PATTERNS:
        if re.search(pattern, ql):
            return True
    return False


def _is_extreme_price_without_specific_edge(c: dict, divergences: dict) -> bool:
    """True for 0/100-ish markets where G2 only has generic language/catalyst hints.

    Local-language + near-deadline is useful when the price is researchable. At
    1-3% or 97-99%, it usually means the market already encodes the obvious
    outcome, so we need a concrete contradiction before spending B.
    """
    yes = float(c.get("yes_price") or 0.5)
    if not (yes <= 0.03 or yes >= 0.97):
        return False
    if _is_bubble_candidate(c.get("question", ""), yes):
        return False
    return not bool(divergences)


def _is_tactical_battlefield_market(c: dict) -> bool:
    ql = c.get("question", "").lower()
    if not any(w in ql for w in ("capture", "enter", "re-enter", "withdraw")):
        return False
    if not any(w in ql for w in ("russia", "ukraine", "israel", "gaza", "lebanon", "iran")):
        return False
    return float(c.get("days_to_end") or 999) <= 14 or bool(
        re.search(r"\bby (?:may|jun|june|jul|july) \d{1,2}", ql)
    )


def _is_macro_bracket_market(question: str) -> bool:
    ql = question.lower()
    if not any(k in ql for k in ("gdp", "cpi", "inflation", "unemployment", "rate", "selic")):
        return False
    return any(k in ql for k in ("between", "%", "growth", "q1", "q2", "q3", "q4"))


def _is_private_provider_market(question: str) -> bool:
    ql = question.lower()
    return "valuation hit" in ql and any(
        company in ql
        for company in ("openai", "anthropic", "spacex", "anduril", "stripe", "canva", "databricks", "kraken")
    )


def _is_central_bank_sequence_market(question: str) -> bool:
    ql = question.lower()
    bank_terms = (
        "bank of england", "bank of brazil", "reserve bank", "rba", "fomc",
        "fed ", "ecb", "bank of japan", "bank of russia", "selic", "cash rate",
    )
    action_terms = ("increase", "decrease", "no change", "hike", "cut", "interest rates", "cash rate", "key rate")
    return any(term in ql for term in bank_terms) and any(term in ql for term in action_terms)


def _is_resolution_clause_market(question: str) -> bool:
    ql = question.lower()
    return any(term in ql for term in ("before gta vi", "before gta 6", "released before", "50/50", "tie resolves"))


def _is_generic_diplomacy_or_publicity_market(question: str) -> bool:
    ql = question.lower()
    generic_patterns = (
        "speak to",
        "have a diplomatic meeting",
        "diplomatic meeting",
        "agreement by",
        "ceasefire cancelled",
        "ceasefire canceled",
        "publicly insult",
        "visit israel",
        "visit pakistan",
        "visit north korea",
        "enter iran",
        "next diplomatic",
    )
    return any(pattern in ql for pattern in generic_patterns)


def _is_geopolitical_tail_market(c: dict) -> bool:
    ql = str(c.get("question") or "").lower()
    geo_terms = (
        "iran", "israel", "lebanon", "hezbollah", "hamas", "hormuz", "kharg",
        "china", "taiwan", "philippines", "russia", "ukraine", "putin",
        "netanyahu", "trump", "nato", "rsf", "khartoum", "sudan",
    )
    event_terms = (
        "meeting", "agreement", "visit", "enter", "invade", "capture", "control",
        "warships", "test a nuclear weapon", "leave nato", "pardoned",
    )
    if not any(term in ql for term in geo_terms):
        return False
    return any(term in ql for term in event_terms)


def _language_arbitrage_is_actionable(c: dict) -> bool:
    """True when language asymmetry likely maps to a real local-info edge.

    G2 previously gave large language points to macro brackets and generic
    leader-meeting questions. Those may need research, but the "local language"
    label is not by itself an edge path. Keep language scoring for elections,
    local political offices, party-seat markets, and private/local procedural
    situations where local sources plausibly lead English markets.
    """
    question = c.get("question", "")
    ql = question.lower()
    if _is_macro_bracket_market(question):
        return False
    if _is_generic_diplomacy_or_publicity_market(question) or _is_geopolitical_tail_market(c):
        return False
    if _is_tactical_battlefield_market(c) and not _has_primary_resolution_source(c):
        return False
    return True


def _has_primary_resolution_source(c: dict) -> bool:
    urls = list(c.get("official_urls") or [])
    urls.extend([u for u, *_ in (c.get("region_urls") or []) if isinstance(u, str)])
    text = " ".join(urls).lower()
    return any(
        marker in text
        for marker in (
            "liveuamap", "deepstatemap", "geoconfirmed", "understandingwar",
            "polymarket.com", "acleddata", "isw",
        )
    )


def _percent_scope_tokens(text: str) -> set[str]:
    cleaned = text.lower().replace("–", "-").replace("—", "-")
    if "%" not in cleaned and "percent" not in cleaned:
        return set()
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", cleaned))


def _divergence_scope_matches(question: str, divergence: dict) -> bool:
    """Reject external-platform matches that do not share bracket/scope terms."""
    ql = question.lower()
    name = str(divergence.get("name") or "").lower()
    country_terms = (
        "pakistan", "greenland", "israel", "germany", "korea", "china", "philippines",
        "russia", "ukraine", "lebanon", "ethiopia", "brazil", "colombia", "peru",
    )
    q_countries = {term for term in country_terms if term in ql}
    name_countries = {term for term in country_terms if term in name}
    if q_countries and name_countries and not (q_countries & name_countries):
        return False

    scoped_requirements = [
        (("first round", "1st round"), ("first round", "1st round")),
        (("primary",), ("primary",)),
        (("nominee", "nomination"), ("nominee", "nomination")),
        (("finish first",), ("finish first", "primary")),
        (("less than", "equal to", "at least", "between"), ("less than", "equal to", "at least", "between")),
    ]
    for q_terms, name_terms in scoped_requirements:
        if any(term in ql for term in q_terms) and not any(term in name for term in name_terms):
            return False

    q_scope = _percent_scope_tokens(question)
    if not q_scope:
        return True
    name_scope = _percent_scope_tokens(str(divergence.get("name") or ""))
    return bool(q_scope and q_scope <= name_scope)


def _broad_event_key(c: dict) -> str:
    """Coarse cap key for Command B queue diversity.

    Top-25 can contain clusters for operator review, but the API-budget queue
    should not spend five B slots on one tactical front, country race, or bracket.
    """
    ql = c.get("question", "").lower()
    if (
        ("russia" in ql and "ukraine" in ql)
        or ("zelenskyy" in ql and "putin" in ql)
        or ("putin" in ql and "ukraine" in ql)
    ) and any(
        w in ql for w in ("ceasefire", "peace deal", "peace", "diplomatic meeting", "talk to putin", "zelenskyy")
    ):
        return "russia_ukraine_peace_process"
    if "netanyahu" in ql or "israel" in ql:
        return "israel_politics_security"
    if (
        "russia" in ql
        and any(w in ql for w in ("capture", "enter", "re-enter"))
        and ("may 31" in ql or float(c.get("days_to_end") or 999) <= 10)
    ):
        return "ukraine_battlefield_near_deadline"
    if "korea" in ql or any(w in ql for w in ("seoul", "jeonbuk", "daejeon", "ulsan")):
        if any(w in ql for w in ("election", "mayoral", "gubernatorial", "governor")):
            return "korea_local_elections"
    if "colombia" in ql and "presidential" in ql:
        return "colombia_presidential"
    if "brazil" in ql and "presidential" in ql:
        return "brazil_presidential"
    if "valuation hit" in ql:
        return "private_market_valuation"
    return f"{c.get('vertical', 'unknown')}:{c.get('archetype', 'unknown')}"


def _correlated_event_key(question: str) -> str:
    ql = question.lower()
    korea_places = (
        "seoul", "jeonbuk", "jeonnam", "busan", "daejeon", "ulsan", "jeju",
        "gyeonggi", "gangwon", "gyeongnam", "gyeongbuk", "chungnam", "chungbuk",
        "incheon", "daegu", "gwangju", "sejong",
    )
    for place in korea_places:
        if place in ql:
            if "gubernatorial" in ql or "governor" in ql:
                return f"korea:{place}:governor"
            if "mayoral" in ql or "mayor" in ql:
                return f"korea:{place}:mayor"
            if "by-election" in ql or "by elections" in ql or "seat" in ql:
                return f"korea:{place}:seat"
    if "colombia" in ql and "presidential" in ql:
        return "colombia:presidential"
    if "brazil" in ql and "presidential" in ql:
        return "brazil:presidential"
    return _topic_cluster_key(question)


def _is_bracket_family_candidate(c: dict) -> bool:
    """Return True for markets where edge can live inside an outcome family.

    These are not generic "between" markets. The repeatable failure from the
    2026-06-01 cycle was a Korean local-election margin bracket: the edge only
    appeared after comparing all sibling outcomes in the same Polymarket event.
    """
    ql = str(c.get("question") or "").lower()
    if not any(term in ql for term in ("election", "mayoral", "gubernatorial", "governor", "turnout")):
        return False
    if not any(term in ql for term in ("between", "less than", "or more", "at least", "%")):
        return False
    return any(
        place in ql
        for place in (
            "korea", "seoul", "busan", "incheon", "gyeonggi", "gyeongnam",
            "gyeongbuk", "jeonbuk", "jeonnam", "daegu", "daejeon", "ulsan",
            "sejong", "jeju", "chungbuk", "chungnam", "gangwon",
        )
    )


def _bracket_family_key(c: dict) -> str | None:
    if not _is_bracket_family_candidate(c):
        return None
    ql = str(c.get("question") or "").lower()
    places = (
        "seoul", "busan", "incheon", "gyeonggi", "gyeongnam", "gyeongbuk",
        "jeonbuk", "jeonnam", "daegu", "daejeon", "ulsan", "sejong",
        "jeju", "chungbuk", "chungnam", "gangwon",
    )
    place = next((p for p in places if p in ql), "korea")
    if "turnout" in ql:
        kind = "turnout"
    elif "gubernatorial" in ql or "governor" in ql:
        kind = "governor_margin"
    elif "mayoral" in ql or "mayor" in ql:
        kind = "mayor_margin"
    else:
        kind = "election_bracket"
    return f"korea:{place}:{kind}"


def _attach_bracket_family_context(candidates: list[dict]) -> int:
    """Annotate sibling bracket markets so G2/M can reason at event-family level."""
    groups: dict[str, list[dict]] = {}
    for c in candidates:
        key = _bracket_family_key(c)
        if not key:
            continue
        groups.setdefault(key, []).append(c)

    annotated = 0
    for key, peers in groups.items():
        if len(peers) < 3:
            continue
        rows = []
        for p in peers:
            try:
                yes = float(p.get("yes_price") or 0.0)
            except (TypeError, ValueError):
                yes = 0.0
            rows.append({
                "condition_id": p.get("condition_id"),
                "question": p.get("question"),
                "yes_price": yes,
                "slug": p.get("slug"),
            })
        rows.sort(key=lambda x: x["yes_price"], reverse=True)
        for p in peers:
            p["outcome_family"] = {
                "family_key": key,
                "family_type": "local_election_bracket",
                "peer_count": len(peers),
                "top_peer_prices": rows[:8],
                "why_matters": (
                    "Mutually related election-bracket outcomes should be compared "
                    "as a family; the best edge may be the modal bracket, not the "
                    "highest-discoverability individual market."
                ),
            }
            annotated += 1
    return annotated


def _broad_event_cap(key: str) -> int:
    if key == "ukraine_battlefield_near_deadline":
        return 1
    if key in ("russia_ukraine_peace_process", "israel_politics_security"):
        return 1
    if key in ("korea_local_elections", "colombia_presidential", "brazil_presidential"):
        return 2
    if key == "private_market_valuation":
        return 2
    return 3


def _select_b_queue_candidates(candidates: list[dict], n: int) -> list[dict]:
    """Select a diverse, API-budgeted queue for Command B."""
    selected: list[dict] = []
    exact_counts: dict[str, int] = {}
    broad_counts: dict[str, int] = {}
    exact_overflow: list[dict] = []

    for c in candidates:
        exact = _correlated_event_key(c.get("question", ""))
        broad = _broad_event_key(c)
        if exact_counts.get(exact, 0) >= MAX_B_QUEUE_PER_EXACT_EVENT:
            exact_overflow.append(c)
            continue
        if broad_counts.get(broad, 0) >= _broad_event_cap(broad):
            continue
        selected.append(c)
        exact_counts[exact] = exact_counts.get(exact, 0) + 1
        broad_counts[broad] = broad_counts.get(broad, 0) + 1
        if len(selected) >= n:
            break

    if len(selected) < n:
        seen = {c.get("condition_id") for c in selected}
        for c in exact_overflow:
            if c.get("condition_id") in seen:
                continue
            selected.append(c)
            seen.add(c.get("condition_id"))
            if len(selected) >= n:
                break

    return selected[:n]


def _non_research_market_reason(candidate: dict) -> str | None:
    """Reject markets that look searchable but are poor Signal research targets."""
    ql = str(candidate.get("question") or "").lower()
    slug = str(candidate.get("slug") or candidate.get("event_slug") or candidate.get("url") or "").lower()
    if ql.startswith("spread:") or re.search(r"\b(fifwc|fifa|f1|mls|nba|nfl|nhl|mlb)\b", slug):
        return "sports_spread_or_match_market"
    weather_terms = (
        "temperature", "weather", "rain", "snow", "precipitation", "wind speed",
        "highest temperature", "lowest temperature",
    )
    if any(term in ql for term in weather_terms):
        return "weather_or_sensor_market"
    if any(term in ql for term in ("stock price", "bitcoin", "ethereum", "solana")) and any(
        term in ql for term in ("above", "below", "hit")
    ):
        return "pure_price_level_market"
    return None


def _open_position_cluster_keys(conn) -> set[str]:
    rows = conn.execute(
        """
        SELECT COALESCE(m.question, p.condition_id) AS question
        FROM positions p
        LEFT JOIN markets m ON m.condition_id = p.condition_id
        WHERE p.status IN ('open','filled','partially_filled')
        """
    ).fetchall()
    return {_correlated_event_key(r["question"]) for r in rows if r["question"]}


# ── Core scoring ───────────────────────────────────────────────────────────────

def _hidden_gem_score(
    c: dict,
    divergences: dict,
) -> tuple[float, dict]:
    """Compute hidden gem score for a candidate. Returns (score, breakdown_dict)."""
    score = 0.0
    breakdown: dict = {}

    yes = c.get("yes_price", 0.5)
    days = c.get("days_to_end", 30) or 30
    question = c.get("question", "")

    if _is_private_provider_market(question):
        score += PRIVATE_PROVIDER_MECHANICS
        breakdown["provider_mechanics"] = f"+{PRIVATE_PROVIDER_MECHANICS} PRIVATE_PROVIDER_MECHANICS"

    if _is_central_bank_sequence_market(question):
        score += CENTRAL_BANK_SEQUENCE
        breakdown["central_bank"] = f"+{CENTRAL_BANK_SEQUENCE} CENTRAL_BANK_SEQUENCE"

    if _is_resolution_clause_market(question):
        score += RESOLUTION_CLAUSE_MECHANICS
        breakdown["resolution_clause"] = f"+{RESOLUTION_CLAUSE_MECHANICS} RESOLUTION_CLAUSE_MECHANICS"

    family = c.get("outcome_family") or {}
    if family and days <= BRACKET_FAMILY_NEAR_DAYS and 0.08 <= yes <= 0.70:
        score += BRACKET_FAMILY_MECHANICS
        breakdown["bracket_family"] = (
            f"+{BRACKET_FAMILY_MECHANICS} LOCAL_ELECTION_BRACKET_FAMILY"
            f"(peers={family.get('peer_count')})"
        )

    # ── Criterion 1: Language arbitrage ───────────────────────────────────────
    lang, ia = _detect_info_asymmetry(question)
    if ia > 0 and not _language_arbitrage_is_actionable(c):
        breakdown["lang_rejected"] = f"+0 LANG({lang}) not_actionable_without_specific_local_edge"
    elif ia >= 0.60:
        if 0.20 <= yes <= 0.65:
            pts = LANG_HIGH_PRIME
            breakdown["lang"] = f"+{pts} HIGH_LANG({lang}) in 20-65% range"
        else:
            pts = LANG_HIGH_FRINGE
            breakdown["lang"] = f"+{pts} HIGH_LANG({lang}) fringe price({yes:.2f})"
        score += pts
    elif ia >= 0.40:
        if 0.20 <= yes <= 0.65:
            pts = LANG_MOD_PRIME
            breakdown["lang"] = f"+{pts} MOD_LANG({lang}) in 20-65% range"
        else:
            pts = LANG_MOD_FRINGE
            breakdown["lang"] = f"+{pts} MOD_LANG({lang}) fringe price({yes:.2f})"
        score += pts

    # ── Criterion 2: Cross-platform divergence ────────────────────────────────
    div_score = 0.0
    div_parts: list[str] = []
    for platform, div_key, prob_key in [
        ("metaculus", "metaculus", "metaculus_prob"),
        ("predictit", "predictit", "pi_price"),
        ("kalshi",    "kalshi",    "kalshi_price"),
        ("manifold",  "manifold",  "mf_prob"),
        ("gjo",       "gjo",       "gjo_prob"),
    ]:
        d = divergences.get(platform)
        if d is None:
            continue
        if not _divergence_scope_matches(c.get("question", ""), d):
            continue
        match_score = float(d.get("match_score") or 0.0)
        if match_score < MIN_DIVERGENCE_MATCH_SCORE:
            continue
        div = d.get("divergence", 0)
        if div >= 0.15:
            div_score += DIV_LARGE
            div_parts.append(f"{platform.upper()} +{DIV_LARGE}pp(Δ{div:.0%})")
        elif div >= 0.08:
            div_score += DIV_MEDIUM
            div_parts.append(f"{platform.upper()} +{DIV_MEDIUM}pp(Δ{div:.0%})")
    if div_parts:
        score += div_score
        breakdown["divergence"] = f"+{div_score:.0f} {' '.join(div_parts)}"

    # ── Criterion 3: Upcoming specific catalyst ───────────────────────────────
    cat_pts = _has_specific_catalyst(question, days)
    if cat_pts:
        score += cat_pts
        breakdown["catalyst"] = f"+{cat_pts} catalyst({'<30d' if cat_pts == CATALYST_NEAR else '<60d'})"

    # ── Criterion 4: Narrative bubble SHORT ───────────────────────────────────
    if _is_bubble_candidate(question, yes):
        score += BUBBLE_SHORT
        breakdown["bubble"] = f"+{BUBBLE_SHORT} NARRATIVE_BUBBLE_SHORT(YES={yes:.2f})"

    if _is_tactical_battlefield_market(c) and not _has_primary_resolution_source(c):
        score -= TACTICAL_BATTLEFIELD_PENALTY
        breakdown["battlefield_penalty"] = (
            f"-{TACTICAL_BATTLEFIELD_PENALTY} tactical_battlefield_no_primary_map"
        )

    if _is_extreme_price_without_specific_edge(c, divergences) and score > EXTREME_PRICE_EDGE_CAP:
        breakdown["extreme_price_cap"] = (
            f"cap@{EXTREME_PRICE_EDGE_CAP} extreme_price_without_specific_edge"
        )
        score = EXTREME_PRICE_EDGE_CAP

    if _is_geopolitical_tail_market(c) and not divergences and not breakdown.get("bubble"):
        if score > GEOPOLITICAL_TAIL_EDGE_CAP:
            breakdown["geopolitical_tail_cap"] = (
                f"cap@{GEOPOLITICAL_TAIL_EDGE_CAP} geopolitical_plausibility_not_edge"
            )
            score = GEOPOLITICAL_TAIL_EDGE_CAP

    return round(score, 1), breakdown


def _rank_context(c: dict) -> dict:
    """Explain why G2 ranked this anomaly and why it is not edge yet."""
    breakdown = c.get("gem_breakdown") or {}
    why_ranked: list[str] = []
    if breakdown.get("lang"):
        why_ranked.append("local-language or local-info asymmetry clue")
    if breakdown.get("divergence") or breakdown.get("metaculus"):
        why_ranked.append("cross-platform divergence clue")
    if breakdown.get("catalyst"):
        why_ranked.append("near-term catalyst/deadline clue")
    if breakdown.get("bubble"):
        why_ranked.append("possible narrative-bubble short clue")
    if c.get("private_market_mechanics") or c.get("archetype") == "private_market_valuation":
        why_ranked.append("provider-metric/private-market mechanics clue")
    if breakdown.get("provider_mechanics"):
        why_ranked.append("private-provider metric mechanics clue")
    if breakdown.get("central_bank"):
        why_ranked.append("central-bank sequence/policy mechanics clue")
    if breakdown.get("resolution_clause"):
        why_ranked.append("resolution-clause mechanics clue")
    if breakdown.get("bracket_family"):
        why_ranked.append("local-election outcome-family / margin-bracket clue")
    if c.get("outcome_family") and not breakdown.get("bracket_family"):
        why_ranked.append("related outcome-family context is available")
    if not why_ranked:
        why_ranked.append("formula/LLM anomaly from wide scan")

    why_not_edge_yet = [
        "G2 has not verified resolution mechanics",
        "G2 has not answered decisive or disconfirming questions",
        "G2 score is not an operator probability or expected value estimate",
    ]
    yes = float(c.get("yes_price") or 0.5)
    if yes <= 0.08 or yes >= 0.92:
        why_not_edge_yet.append("extreme price requires concrete contradiction, not just curiosity")
    if breakdown.get("catalyst") and not (
        breakdown.get("lang")
        or breakdown.get("divergence")
        or breakdown.get("metaculus")
        or breakdown.get("bubble")
    ):
        why_not_edge_yet.append("near deadline alone is not an edge path")

    what_must_be_true = [
        "Command M must find a concrete market-error hypothesis",
        "Command R must produce a falsifiable edge thesis and market-mechanics checklist",
        "Command B must answer the decisive questions with relevant sources",
        "Operator/Codex/Opus review must set an explicit probability before D/C",
    ]
    if breakdown.get("divergence") or breakdown.get("metaculus"):
        what_must_be_true.append("Divergence must survive resolution-equivalence checking")
    if c.get("private_market_mechanics") or c.get("archetype") == "private_market_valuation" or breakdown.get("provider_mechanics"):
        what_must_be_true.append("Provider metric, cadence, lag, and latest mark must be verified")
    if breakdown.get("central_bank"):
        what_must_be_true.append("Policy sequence, latest guidance, market-implied rates, and shock data must be checked")
    if breakdown.get("resolution_clause"):
        what_must_be_true.append("Rule clause, fallback, deadline timezone, and availability definition must be verified")
    if breakdown.get("bracket_family"):
        what_must_be_true.append("All sibling brackets must be compared against local polls, turnout, and official margin rules")

    return {
        "why_ranked": why_ranked,
        "why_not_edge_yet": why_not_edge_yet,
        "what_must_be_true_for_edge": what_must_be_true,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("COMMAND G2: Hidden Gem Ranker")
    print("=" * 70)
    print(f"  Reads candidates_wide.json | Shortlist {OUTPUT_N} → B queue {B_QUEUE_N}")
    print(f"  Divergence match gate: match_score >= {MIN_DIVERGENCE_MATCH_SCORE:.2f}")
    print(f"  LLM pool: top {LLM_POOL_N} by G2 score\n")

    # Load candidates_wide.json
    wide_path = os.path.join(os.path.dirname(__file__), "candidates_wide.json")
    if not os.path.exists(wide_path):
        print("ERROR: candidates_wide.json not found. Run Command G first.")
        return []

    with open(wide_path, encoding="utf-8") as f:
        wide_data = json.load(f)

    all_candidates = wide_data.get("candidates", [])
    generated_at = wide_data.get("generated_at", "?")
    print(f"Loaded {len(all_candidates)} candidates from G_scan ({generated_at[:16]})\n")
    bracket_family_n = _attach_bracket_family_context(all_candidates)
    if bracket_family_n:
        print(
            f"Annotated {bracket_family_n} local-election bracket candidates "
            "with outcome-family context.\n"
        )

    if not all_candidates:
        print("No candidates in wide file. Re-run Command G.")
        return []

    with db.connect() as conn:
        skip_cids = _open_position_cids(conn) | _b_researched_cids(conn, SKIP_B_RESEARCHED_DAYS)
        open_cluster_keys = _open_position_cluster_keys(conn)
    before_skip = len(all_candidates)
    all_candidates = [
        c for c in all_candidates
        if c.get("condition_id") not in skip_cids
        and _correlated_event_key(c.get("question", "")) not in open_cluster_keys
    ]
    skipped_stale = before_skip - len(all_candidates)
    if skipped_stale:
        print(
            f"G2 freshness filter: skipped {skipped_stale} open/recently researched "
            f"markets (last {SKIP_B_RESEARCHED_DAYS}d)\n"
        )
    if not all_candidates:
        print("All wide candidates were open/recently researched. Re-run Command G.")
        return []

    wf_id = _start_workflow_log(
        "hidden_gem_ranker",
        "G2 Hidden Gem Ranker",
        input_payload={"input_candidates": len(all_candidates), "output_n": OUTPUT_N, "b_queue_n": B_QUEUE_N},
        agent_name="claude-code",
        notes="G2 — ranks G_scan wide candidates by language/divergence/catalyst/bubble criteria",
    )
    print(f"Workflow run: {wf_id}\n")

    # ── Load divergence anchor caches (one call each, reused for all candidates) ─
    print("Loading divergence anchors (PredictIt / Manifold / Kalshi / GJO)...")
    try:
        from lib.integrations.predictit import fetch_all_markets as _pi_fetch
        _pi_markets = _pi_fetch()
        print(f"  PredictIt: {len(_pi_markets)} contracts")
    except Exception:
        _pi_markets = []
        print("  PredictIt: unavailable")
    try:
        from lib.integrations.manifold import fetch_all_markets as _mf_fetch
        _mf_markets = _mf_fetch()
        print(f"  Manifold:  {len(_mf_markets)} markets")
    except Exception:
        _mf_markets = []
        print("  Manifold: unavailable")
    try:
        from lib.integrations.kalshi import fetch_all_markets as _kalshi_fetch
        _kalshi_markets = _kalshi_fetch()
        print(f"  Kalshi:    {len(_kalshi_markets)} contracts")
    except Exception:
        _kalshi_markets = []
        print("  Kalshi: unavailable")
    try:
        from lib.integrations.gjo import fetch_all_questions as _gjo_fetch
        _gjo_questions = _gjo_fetch()
        print(f"  GJO:       {len(_gjo_questions)} questions")
    except Exception:
        _gjo_questions = []
        print("  GJO: unavailable")

    # ── Score every candidate by G2 hidden-gem criteria ────────────────────────
    print(f"\nScoring {len(all_candidates)} candidates by hidden-gem criteria...")
    scored: list[dict] = []
    lang_prime_count = 0
    divergence_count = 0
    catalyst_count = 0
    bubble_count = 0
    non_research_rejects = 0

    for c in all_candidates:
        reject_reason = _non_research_market_reason(c)
        if reject_reason:
            c["g2_reject_reason"] = reject_reason
            non_research_rejects += 1
            continue
        # Quick cross-platform divergence for all candidates (Metaculus is API-based)
        # We skip Metaculus here (too slow for 300 markets) — do it in enrichment below.
        # PredictIt/Manifold/Kalshi are cached.
        divs: dict = {}
        pi = _predictit_divergence_check(c["question"], c["yes_price"], _pi_markets)
        if pi and _divergence_scope_matches(c["question"], pi):
            divs["predictit"] = pi
        mf = _manifold_divergence_check(c["question"], c["yes_price"], _mf_markets)
        if mf and _divergence_scope_matches(c["question"], mf):
            divs["manifold"] = mf
        kal = _kalshi_divergence_check(c["question"], c["yes_price"], _kalshi_markets)
        if kal and _divergence_scope_matches(c["question"], kal):
            divs["kalshi"] = kal
        gjo = _gjo_divergence_check(c["question"], c["yes_price"], _gjo_questions)
        if gjo and _divergence_scope_matches(c["question"], gjo):
            divs["gjo"] = gjo

        gem_score, breakdown = _hidden_gem_score(c, divs)

        # Track counts for summary
        if breakdown.get("lang", "").startswith(f"+{LANG_HIGH_PRIME}"):
            lang_prime_count += 1
        if breakdown.get("divergence"):
            divergence_count += 1
        if breakdown.get("catalyst"):
            catalyst_count += 1
        if breakdown.get("bubble"):
            bubble_count += 1

        c["gem_score"] = gem_score
        c["gem_breakdown"] = breakdown
        c["divergences"] = divs
        scored.append(c)

    # Sort by gem_score DESC, break ties by discoverability_score
    scored.sort(key=lambda x: (x["gem_score"], x["discoverability_score"]), reverse=True)

    print(f"\nG2 criteria distribution (top {LLM_POOL_N}):")
    print(f"  Language PRIME (20-65%): {lang_prime_count}")
    print(f"  Cross-platform divergence: {divergence_count}")
    print(f"  Specific catalyst: {catalyst_count}")
    print(f"  Narrative bubble SHORT: {bubble_count}")
    print(f"  Non-research rejects: {non_research_rejects}")

    # Show top-20 by gem_score before LLM
    print(f"\nTop 20 by G2 hidden-gem score:")
    for i, c in enumerate(scored[:20], 1):
        lang, ia = _detect_info_asymmetry(c["question"])
        lang_tag = f" [{lang}]" if ia > 0 else ""
        print(f"  {i:2d}. [{c['gem_score']:4.0f}] YES={c['yes_price']:.3f} "
              f"{c['question'][:55]}{lang_tag}")
        if c["gem_breakdown"]:
            print(f"        {' | '.join(c['gem_breakdown'].values())}")

    # ── Enrich top LLM_POOL_N: Metaculus + CLOB + whale ──────────────────────
    pool = scored[:LLM_POOL_N]
    contexts: dict[str, dict] = {}

    print(f"\nEnriching top {len(pool)} candidates (Metaculus + CLOB + whale)...")
    for i, c in enumerate(pool):
        cid = c["condition_id"]
        ctx = dict(c.get("divergences") or {})

        # Metaculus (API call per market — only for the enriched pool)
        if i < 40:
            meta = _metaculus_divergence_check(c["question"], c["yes_price"])
            if (
                meta
                and _divergence_scope_matches(c["question"], meta)
                and float(meta.get("match_score") or 0.0) >= MIN_DIVERGENCE_MATCH_SCORE
            ):
                c["metaculus_divergence"] = meta
                ctx["metaculus"] = meta
                # Update gem_score with metaculus divergence
                meta_pts = DIV_LARGE if meta["divergence"] >= 0.15 else DIV_MEDIUM
                c["gem_score"] += meta_pts
                c["gem_breakdown"]["metaculus"] = (
                    f"+{meta_pts} METACULUS(Δ{meta['divergence']:.0%})"
                )
                print(f"  [{i+1}] Metaculus: Poly={c['yes_price']:.2f} vs "
                      f"Meta={meta['metaculus_prob']:.2f} "
                      f"(Δ{meta['divergence']:.0%})")

        # Copy any divergences from the first-pass scoring
        for platform, key in [("predictit", "predictit"), ("manifold", "manifold"),
                               ("kalshi", "kalshi"), ("gjo", "gjo")]:
            d = c.get("divergences", {}).get(platform)
            if d:
                ctx[platform] = d
                setattr(c, platform + "_divergence", d) if False else None
                c[platform + "_divergence"] = d

        # CLOB order flow imbalance
        if i < 30:
            tokens = c.get("tokens") or []
            ofi = _order_flow_imbalance(tokens)
            if ofi:
                c["order_flow_imbalance"] = ofi
                ctx["ofi"] = ofi

        # Whale detection
        if i < 20:
            tokens = c.get("tokens") or []
            whale = _whale_check(tokens, cid)
            if whale:
                c["whale_alert"] = True
                c["whale_max_usd"] = whale.max_size_usd
                c["whale_dominant"] = whale.dominant_side
                c["whale_escalate"] = whale.escalate
                ctx["whale"] = {
                    "max_usd": whale.max_size_usd,
                    "dominant": whale.dominant_side,
                    "signals_count": len(whale.signals),
                }

        contexts[cid] = ctx

    # Re-sort after Metaculus enrichment (scores may have changed)
    pool.sort(key=lambda x: (x["gem_score"], x["discoverability_score"]), reverse=True)

    # ── LLM vibe-check ────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("LLM VIBE-CHECK: Finding hidden gems through narrative analysis")
    print(f"{'='*60}")
    print(f"  Sending top {min(LLM_POOL_N, len(pool))} candidates to Ollama...")

    llm_ranked = _llm_vibe_check(pool[:LLM_POOL_N], contexts, OUTPUT_N)

    if llm_ranked:
        print(f"\n[LLM] Using LLM-ranked candidates (diversity filter applied)")
        top_candidates = _select_diverse_top_n(llm_ranked, OUTPUT_N)
        for c in top_candidates:
            c.setdefault("ranking_method", "g2_llm_vibe_check")
    else:
        print("\n[FALLBACK] Ollama unavailable — using G2 gem_score ranking")
        top_candidates = _select_diverse_top_n(pool, OUTPUT_N)
        for c in top_candidates:
            c.setdefault("ranking_method", "g2_gem_score")

    # Enrich kill criteria + first_queries for final output
    for c in top_candidates:
        if not c.get("kill_criteria"):
            c["kill_criteria"] = _kill_criteria_template(c)
        if not c.get("first_queries"):
            c["first_queries"] = _first_queries(c)
        if not c.get("local_language"):
            c["local_language"] = _local_language(c.get("question", ""))
        c["g2_review_frame"] = _rank_context(c)
        c["requires_operator_review"] = True

    # ── Print final ranked table ───────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"G2 FINAL: TOP {len(top_candidates)} HIDDEN GEM CANDIDATES")
    print(f"{'='*70}\n")

    for i, c in enumerate(top_candidates, 1):
        lang, ia = _detect_info_asymmetry(c["question"])
        lang_tag = f" [LANG:{lang}]" if ia > 0.4 else ""
        gem_type = c.get("hidden_gem_type", "")
        gem_note = f" [{gem_type}]" if gem_type and gem_type != "unknown" else ""
        divs_note = ""
        if c.get("metaculus_divergence"):
            d = c["metaculus_divergence"]
            divs_note += f" Meta={d['metaculus_prob']*100:.0f}%"
        if c.get("predictit_divergence"):
            d = c["predictit_divergence"]
            divs_note += f" PI={d['pi_price']*100:.0f}%"
        if divs_note:
            divs_note = f" |{divs_note} vs Poly={c['yes_price']*100:.0f}%"

        print(f"{i:2d}. [{c['vertical'][:10]}] {c['question'][:62]}")
        print(f"     YES={c['yes_price']:.3f} | G2={c['gem_score']:.0f}pts | "
              f"{c['days_to_end']:.0f}d{lang_tag}{divs_note}{gem_note}")
        llm_reason = c.get("llm_reasoning", "")
        breakdown = c.get("gem_breakdown", {})
        if llm_reason:
            print(f"     WHY: {llm_reason[:120]}")
        elif breakdown:
            print(f"     G2: {' | '.join(breakdown.values())}")
        url = c.get("polymarket_url") or ""
        if url:
            print(f"     {url}")
        print()

    # ── Summary stats ──────────────────────────────────────────────────────────
    lang_picks = sum(1 for c in top_candidates if c.get("gem_breakdown", {}).get("lang"))
    div_picks = sum(1 for c in top_candidates if c.get("gem_breakdown", {}).get("divergence")
                    or c.get("gem_breakdown", {}).get("metaculus"))
    cat_picks = sum(1 for c in top_candidates if c.get("gem_breakdown", {}).get("catalyst"))
    bubble_picks = sum(1 for c in top_candidates if c.get("gem_breakdown", {}).get("bubble"))

    print(f"{'='*70}")
    print(f"G2 SUMMARY:")
    print(f"  Input from G_scan:     {len(all_candidates)} candidates")
    print(f"  After G2 scoring:      {len(scored)} scored")
    print(f"  Output to B:           {len(top_candidates)} candidates")
    print(f"  By criterion:")
    print(f"    Language arbitrage:  {lang_picks}")
    print(f"    Cross-platform div:  {div_picks}")
    print(f"    Upcoming catalyst:   {cat_picks}")
    print(f"    Narrative bubble:    {bubble_picks}")

    _record_workflow_step(
        wf_id, "hidden_gem_ranking",
        allowed_writes=[],
        writes_count=len(top_candidates),
        output_json={
            "input_n": len(all_candidates),
            "output_n": len(top_candidates),
            "lang_picks": lang_picks,
            "div_picks": div_picks,
            "cat_picks": cat_picks,
            "bubble_picks": bubble_picks,
        },
    )
    _finish_workflow_log(wf_id, status="completed", output_json={
        "output_n": len(top_candidates),
        "top_gem_score": top_candidates[0]["gem_score"] if top_candidates else 0,
    })

    # ── Save full top-25 shortlist as reference ────────────────────────────────
    top25_path = os.path.join(os.path.dirname(__file__), "g2_top25.json")
    with open(top25_path, "w", encoding="utf-8") as _f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(top_candidates),
            "b_queue_n": B_QUEUE_N,
            "candidates": top_candidates,
        }, _f, indent=2, ensure_ascii=False, default=str)
    print(f"\nFull top-{len(top_candidates)} shortlist saved to: {top25_path}")

    # ── Pick best B_QUEUE_N for Command B (diversity-filtered) ────────────────
    b_candidates = _select_b_queue_candidates(top_candidates, B_QUEUE_N)
    print(f"\nTop {len(b_candidates)} for Command B (API-budget queue):")
    for i, c in enumerate(b_candidates, 1):
        lang, ia = _detect_info_asymmetry(c["question"])
        lang_tag = f" [{lang}]" if ia > 0.4 else ""
        print(f"  {i}. [{c['gem_score']:.0f}pts] YES={c['yes_price']:.3f} "
              f"{c['question'][:60]}{lang_tag}")

    # ── Write forager_queue_auto.py (B_QUEUE_N only) ───────────────────────────
    queue_path = os.path.join(os.path.dirname(__file__), "forager_queue_auto.py")
    _write_forager_queue(b_candidates, queue_path, output_n=B_QUEUE_N)

    print(f"\nNext step: run the manual shortlist/reasoning gates before Command B:")
    print(f"  python run_command_m.py")
    print(f"  $env:FORAGER_QUEUE_PATH='manual_shortlist_queue.py'; python run_command_r.py")
    print(f"  $env:FORAGER_QUEUE_PATH='forager_queue_reasoned.py'; python run_command_b.py")
    print(f"\nWorkflow run: {wf_id}")
    return b_candidates


if __name__ == "__main__":
    main()
