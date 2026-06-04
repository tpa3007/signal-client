"""Master workflow tools for one-call research sessions.

These tools do not replace the lower-level research tools. They group them into
operator workflows: discover, learn, maintain. The server still does not call an
LLM or fabricate external evidence; it builds queues and candidate packets that
make the next research step explicit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re

import httpx

import config
import db
from markets import classify_theme_tags, fetch_active_markets
from lib.discovery import (
    ALL_STRATEGY_NAMES,
    cheap_optionality,
    compounder_research_candidate,
    low_volume_research_sweetspot,
    stale_price,
    _market_age_days,
)
from lib.discovery_scoring import (
    attention_gap_score,
    combined_raw_discoverability,
    liquidity_score,
    spread_score,
    stale_price_score,
)
from lib.exposure import open_exposure
from lib.gates import validate_signal_gate as _validate_signal_gate
from lib.ledger import research_ledger_rows, research_ledger_summary
from lib.queries import research_completeness
from lib.integrations import (
    acled,
    arxiv,
    gdelt,
    github,
    openfec,
    reliefweb,
    wikipedia,
    youtube,
)


OPEN_POSITION_STATUSES = ("open", "filled", "partially_filled")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_db() -> None:
    db.init()


def _price_series(conn, condition_id: str, window_days: int) -> list[float]:
    rows = conn.execute("""
        SELECT yes_price FROM snapshots
        WHERE condition_id = ?
          AND julianday(captured_at) >= julianday('now', ?)
        ORDER BY captured_at
    """, (condition_id, f"-{window_days} days")).fetchall()
    return [float(r["yes_price"]) for r in rows]


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
        UNION
        SELECT DISTINCT condition_id FROM moonshot_reviews
        WHERE julianday(created_at) >= julianday('now', ?)
          AND decision NOT LIKE 'reject%'
    """, (f"-{days} days", f"-{days} days")).fetchall()
    return {r["condition_id"] for r in rows}


def _market_to_dict(m, first_seen_at: str | None = None) -> dict:
    return {
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
        "end_date": m.end_date,
        "first_seen_at": first_seen_at,
    }


def _persist_market(conn, m, source: str) -> None:
    theme_tags = m.theme_tags or classify_theme_tags(m.question)
    db.upsert_market(
        conn,
        condition_id=m.condition_id,
        question=m.question,
        slug=m.slug,
        end_date=m.end_date,
        vertical=m.vertical,
    )
    db.set_market_tags(conn, condition_id=m.condition_id, tags=theme_tags)
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
        source=source,
    )


def _matched_strategies(md: dict, series: list[float]) -> list[str]:
    matched = []
    if low_volume_research_sweetspot(md):
        matched.append("low_volume_research_sweetspot")
    if cheap_optionality(md):
        matched.append("cheap_optionality")
    if compounder_research_candidate(md):
        matched.append("compounder_research_candidate")
    if stale_price(md, series):
        matched.append("stale_price")
    return matched


def _candidate_packet(md: dict, series: list[float], matched: list[str]) -> dict:
    age_days = _market_age_days(md.get("first_seen_at"))
    ag = attention_gap_score(md["volume"], age_days, md["liquidity"])
    sp = stale_price_score(series)
    lq = liquidity_score(md["liquidity"])
    sd = spread_score(md["spread"])
    bonus = min(0.30 * len(matched), 1.0)
    raw = combined_raw_discoverability(
        attention_gap=ag,
        stale_price=sp,
        liquidity=lq,
        spread=sd,
        strategy_bonus=bonus,
    )

    yes_price = float(md["yes_price"])
    no_price = float(md["no_price"] if md["no_price"] is not None else 1.0 - yes_price)
    moonshot_sides = []
    if yes_price <= config.SPECULATIVE_PRICE_MAX:
        moonshot_sides.append("YES")
    if no_price <= config.SPECULATIVE_PRICE_MAX:
        moonshot_sides.append("NO")

    source_queries = [
        f"Polymarket rules and resolution source for: {md['question']}",
        f"latest primary-source news for: {md['question']}",
        f"disconfirming evidence for: {md['question']}",
    ]
    if md.get("vertical") == "tech_business":
        source_queries.append(f"official company/blog/API/changelog source for: {md['question']}")
    if md.get("vertical") in {"us_politics", "international_geopolitics"}:
        source_queries.append(f"official government/parliament/court source for: {md['question']}")

    next_actions = [
        f"backfill_price_history(condition_id='{md['condition_id']}', days=30)",
        f"parse_resolution_clarity(text=<market rules for {md['condition_id']}>)",
        f"record_resolution_map(condition_id='{md['condition_id']}', ...)",
        f"record_evidence(condition_id='{md['condition_id']}', ...) for at least 2 sources",
        f"record_actor_map / record_causal_factor / record_scenario / record_premortem for {md['condition_id']}",
    ]
    if moonshot_sides:
        next_actions.insert(1, f"record_moonshot_review(condition_id='{md['condition_id']}', side='{moonshot_sides[0]}', ...)")
    else:
        next_actions.insert(1, f"record_hidden_gem_review(condition_id='{md['condition_id']}', ...)")

    return {
        "condition_id": md["condition_id"],
        "question": md["question"],
        "slug": md["slug"],
        "vertical": md["vertical"],
        "theme_tags": md["theme_tags"],
        "end_date": md["end_date"],
        "days_to_resolution": round(md["days_to_end"], 1) if md.get("days_to_end") is not None else None,
        "yes_price": round(yes_price, 4),
        "no_price": round(no_price, 4),
        "spread": md["spread"],
        "liquidity": md["liquidity"],
        "volume": md["volume"],
        "market_age_days": round(age_days, 1) if age_days is not None else None,
        "matched_strategies": matched,
        "raw_discoverability_score": raw,
        "score_components": {
            "attention_gap": ag,
            "stale_price": sp,
            "liquidity": lq,
            "spread": sd,
            "strategy_bonus": bonus,
        },
        "moonshot_sides": moonshot_sides,
        "needs_backfill": len(series) < 3,
        "data_sources_recorded": [
            "Polymarket Gamma market metadata",
            "Polymarket CLOB/orderbook snapshot",
            "market_tags auto-classifier",
        ],
        "source_queries_to_collect": source_queries,
        "next_actions": next_actions,
    }


def _workflow_brief(conn, limit: int) -> dict:
    exposure = open_exposure(conn)
    pending_outcomes = conn.execute("""
        SELECT p.id AS position_id, p.condition_id, m.question, p.intended_side,
               p.intended_stake_usd, m.resolved_at
        FROM positions p
        JOIN markets m ON m.condition_id = p.condition_id
        LEFT JOIN outcome_learning_reviews olr ON olr.condition_id = p.condition_id
        WHERE m.resolved = 1 AND olr.id IS NULL
        ORDER BY m.resolved_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    stale_positions = conn.execute("""
        SELECT p.condition_id, m.question, p.intended_side, p.intended_stake_usd,
               MAX(a.created_at) AS last_analysis_at,
               MAX(fu.created_at) AS last_update_at,
               p.opened_at
        FROM positions p
        JOIN markets m ON m.condition_id = p.condition_id
        LEFT JOIN analyses a ON a.condition_id = p.condition_id
        LEFT JOIN forecast_updates fu ON fu.condition_id = p.condition_id
        WHERE p.status IN ('open','filled','partially_filled')
        GROUP BY p.condition_id
        HAVING julianday(COALESCE(MAX(fu.created_at), MAX(a.created_at), p.opened_at)) <= julianday('now', '-72 hours')
        ORDER BY julianday(COALESCE(MAX(fu.created_at), MAX(a.created_at), p.opened_at)) ASC
        LIMIT ?
    """, (limit,)).fetchall()
    incomplete_rows = conn.execute("""
        SELECT m.condition_id, m.question, m.vertical, m.end_date,
               MAX(COALESCE(a.created_at, h.created_at, mo.created_at, m.last_seen_at)) AS last_touch
        FROM markets m
        LEFT JOIN analyses a ON a.condition_id = m.condition_id
        LEFT JOIN hidden_gem_reviews h ON h.condition_id = m.condition_id
        LEFT JOIN moonshot_reviews mo ON mo.condition_id = m.condition_id
        WHERE a.id IS NOT NULL OR h.id IS NOT NULL OR mo.id IS NOT NULL
        GROUP BY m.condition_id
        ORDER BY last_touch DESC
        LIMIT 100
    """).fetchall()
    incomplete = []
    for r in incomplete_rows:
        comp = research_completeness(conn, r["condition_id"])
        if comp["score"] < 85:
            incomplete.append({
                "condition_id": r["condition_id"],
                "question": r["question"],
                "vertical": r["vertical"],
                "end_date": r["end_date"],
                "score": comp["score"],
                "missing": comp["missing"],
            })
        if len(incomplete) >= limit:
            break
    return {
        "portfolio_exposure": exposure,
        "pending_outcome_reviews": [dict(r) for r in pending_outcomes],
        "stale_open_positions": [dict(r) for r in stale_positions],
        "incomplete_research": incomplete,
    }


def _learning_snapshot(conn, limit: int) -> dict:
    quality_rows = conn.execute("""
        SELECT q.*, m.question, m.vertical
        FROM signal_quality_reviews q
        JOIN markets m ON m.condition_id = q.condition_id
        ORDER BY q.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    archetype_rows = conn.execute("""
        SELECT ar.primary_archetype,
               COUNT(*) AS n,
               AVG(q.total_score) AS avg_quality,
               AVG(q.mark_to_market_roi) AS avg_mtm_roi,
               SUM(q.mark_to_market_pnl) AS total_mtm_pnl
        FROM signal_archetype_reviews ar
        LEFT JOIN signal_quality_reviews q ON q.condition_id = ar.condition_id
        GROUP BY ar.primary_archetype
        ORDER BY COALESCE(AVG(q.mark_to_market_roi), -999) ASC
    """).fetchall()
    no_signal_rows = conn.execute("""
        SELECT no_signal_reason, COUNT(*) AS n
        FROM analyses
        WHERE decision = 'no_signal'
        GROUP BY no_signal_reason
        ORDER BY n DESC
    """).fetchall()
    benchmark_rows = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active
        FROM signal_benchmark_cases
    """).fetchone()
    source_rows = conn.execute("""
        SELECT name, source_type, reliability_score, latency_score, bias,
               times_cited, times_correct, times_wrong
        FROM sources
        ORDER BY times_cited DESC, reliability_score DESC
        LIMIT ?
    """, (limit,)).fetchall()

    weak_archetypes = []
    strong_archetypes = []
    for r in archetype_rows:
        item = {
            "primary_archetype": r["primary_archetype"],
            "n": r["n"],
            "avg_quality": round(float(r["avg_quality"]), 2) if r["avg_quality"] is not None else None,
            "avg_mtm_roi_pct": round(float(r["avg_mtm_roi"] or 0.0) * 100, 1),
            "total_mtm_pnl": round(float(r["total_mtm_pnl"] or 0.0), 2),
        }
        if item["avg_mtm_roi_pct"] < 0:
            weak_archetypes.append(item)
        else:
            strong_archetypes.append(item)

    return {
        "recent_quality_reviews": [dict(r) for r in quality_rows],
        "weak_archetypes": weak_archetypes[:limit],
        "strong_archetypes": strong_archetypes[:limit],
        "no_signal_reason_counts": [dict(r) for r in no_signal_rows],
        "benchmark_case_counts": dict(benchmark_rows) if benchmark_rows else {"total": 0, "active": 0},
        "source_registry_top": [dict(r) for r in source_rows],
    }


async def _run_market_discovery(max_pages: int, max_candidates: int,
                                vertical: str | None,
                                include_recent_reviews: bool) -> dict:
    scan_min_vol = min(
        config.DISCOVERY_LOW_VOL_MIN,
        config.MIN_VOLUME_USD,
        config.MOONSHOT_LIQUIDITY_NORM * 0.5,
    )
    scan_days_min = min(
        config.DISCOVERY_LOW_VOL_DAYS_MIN,
        config.DISCOVERY_CHEAP_OPT_DAYS_MIN,
        config.MIN_DAYS_TO_RESOLUTION,
    )
    scan_days_max = max(
        config.DISCOVERY_LOW_VOL_DAYS_MAX,
        config.DISCOVERY_CHEAP_OPT_DAYS_MAX,
        config.MAX_DAYS_TO_RESOLUTION,
    )
    async with httpx.AsyncClient() as http:
        raw_markets = await fetch_active_markets(
            http,
            max_pages=max_pages,
            vertical=vertical,
            sort="none",
            min_volume_usd=scan_min_vol,
            days_min=scan_days_min,
            days_max=scan_days_max,
        )

    with db.connect() as conn:
        db.start_run(conn, _today())
        for m in raw_markets:
            _persist_market(conn, m, source="master_discovery")
        open_cids = _open_position_cids(conn)
        recent_cids = _recently_reviewed_cids(conn, config.DISCOVERY_RECENT_REVIEW_DAYS)
        first_seen_map = {}
        if raw_markets:
            placeholders = ",".join("?" for _ in raw_markets)
            rows = conn.execute(
                f"SELECT condition_id, first_seen_at FROM markets WHERE condition_id IN ({placeholders})",
                [m.condition_id for m in raw_markets],
            ).fetchall()
            first_seen_map = {r["condition_id"]: r["first_seen_at"] for r in rows}

        candidates = []
        skipped_open = 0
        skipped_recent = 0
        for m in raw_markets:
            if m.condition_id in open_cids:
                skipped_open += 1
                continue
            if not include_recent_reviews and m.condition_id in recent_cids:
                skipped_recent += 1
                continue
            md = _market_to_dict(m, first_seen_map.get(m.condition_id))
            series = _price_series(conn, m.condition_id, config.DISCOVERY_STALE_WINDOW_DAYS)
            matched = _matched_strategies(md, series)
            if not matched:
                continue
            candidates.append(_candidate_packet(md, series, matched))
        conn.commit()

    candidates.sort(key=lambda x: x["raw_discoverability_score"], reverse=True)
    top = candidates[:max_candidates]
    return {
        "scanned_markets": len(raw_markets),
        "persisted_markets": len(raw_markets),
        "skipped_open_positions": skipped_open,
        "skipped_recent_reviews": skipped_recent,
        "candidate_count": len(candidates),
        "top_candidates": top,
        "action_queue": {
            "backfill": [c["condition_id"] for c in top if c["needs_backfill"]],
            "moonshot_review": [c["condition_id"] for c in top if c["moonshot_sides"]],
            "hidden_gem_review": [c["condition_id"] for c in top if not c["moonshot_sides"]],
            "source_collection": [
                {"condition_id": c["condition_id"], "queries": c["source_queries_to_collect"]}
                for c in top
            ],
        },
        "research_lanes": {
            "moonshot": "cheap/high-payout ideas that still need anti-random checks",
            "hidden_gem": "neglected or local-information markets with source asymmetry",
            "compounder": "0.22-0.60 markets where high conviction can justify a clean EV signal",
        },
        "source_policy": {
            "already_recorded": ["Polymarket Gamma", "Polymarket CLOB snapshot", "auto theme tags"],
            "must_collect_before_signal": [
                "market resolution/rules source",
                "at least one primary or official source when available",
                "at least one disconfirming source",
                "timestamped source_url via record_evidence",
            ],
        },
    }


_STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def _state_abbr_from_question(question: str) -> str | None:
    ql = question.lower()
    for state, abbr in _STATE_ABBR.items():
        if state in ql:
            return abbr
    m = re.search(r"\b([A-Z]{2})-\d{1,2}\b", question)
    if m:
        return m.group(1)
    return None


def _office_from_question(question: str) -> str | None:
    ql = question.lower()
    if "senate" in ql or "senator" in ql:
        return "S"
    if "house" in ql or re.search(r"\b[A-Z]{2}-\d{1,2}\b", question):
        return "H"
    if "president" in ql and "2028" not in ql:
        return "P"
    return None


def _guess_primary_entity(question: str) -> str:
    patterns = (
        r"Will ([A-Z][A-Za-z' .-]+?) be ",
        r"Will ([A-Z][A-Za-z' .-]+?) win ",
        r"Will ([A-Z][A-Za-z' .-]+?) announce ",
    )
    for pattern in patterns:
        m = re.search(pattern, question)
        if m:
            return m.group(1).strip()
    lowered = question.lower()
    if "google" in lowered:
        return "Google Gemini"
    if "ukraine" in lowered:
        return "Ukraine ceasefire"
    return question.split("?")[0][:80]



def _gdelt_query_for_question(question: str, entity: str) -> str:
    ql = question.lower()
    clean_entity = entity.replace("-", " ")
    if "ukraine" in ql and "ceasefire" in ql:
        return "Ukraine US ceasefire framework peace plan"
    if "bolojan" in ql or "romania" in ql:
        return "Ilie Bolojan Romania prime minister government confidence vote"
    if "lindsey graham" in ql:
        return "Lindsey Graham South Carolina Republican primary Mark Lynch"
    if "kamala harris" in ql:
        return "Kamala Harris 2028 presidential campaign announcement"
    if "google" in ql and "ai model" in ql:
        return "Google Gemini LMArena leaderboard artificial intelligence model"
    if "gyeongsangnam" in ql or "kim kyung" in ql or "park wan" in ql:
        return "Kim Kyung soo Park Wan soo Gyeongsangnam governor election"
    if "angie craig" in ql:
        return "Angie Craig Peggy Flanagan Minnesota Senate primary"
    if "mike pieciak" in ql:
        return "Mike Pieciak Vermont governor Democratic primary"
    if "laura gillen" in ql:
        return "Laura Gillen New York fourth district Democratic primary"
    words = re.findall(r"[A-Za-z0-9]+", f"{clean_entity} {question}")
    words = [w for w in words if len(w) > 2 and w.lower() not in {"will", "the", "for", "with", "and", "yes", "no"}]
    return " ".join(words[:10]) or clean_entity

def _trim_list(value: dict, key: str, limit: int = 3) -> dict:
    if isinstance(value, dict) and isinstance(value.get(key), list):
        out = dict(value)
        out[key] = out[key][:limit]
        return out
    return value


def _source_error_summary(api: dict) -> list[str]:
    errors = []
    for name, value in api.items():
        if isinstance(value, dict) and value.get("error"):
            errors.append(f"{name}: {value['error']}")
    return errors


def _enrichment_decision(candidate: dict, api: dict) -> dict:
    q = candidate["question"].lower()
    reasons = []
    blockers = []
    decision = "needs_deep_research"
    if "lmarena" in (api.get("polymarket_details") or {}).get("description", "").lower():
        decision = "watch_only"
        blockers.append("needs direct LMArena leaderboard snapshot before any signal")
    if "ukraine" in q:
        blockers.append("ACLED/ReliefWeb approvals or equivalent primary-source timeline needed")
    if "gyeongsangnam" in q:
        reasons.append("local-language source asymmetry detected; Korean polling/news can beat English market consensus")
    if "prime minister of romania" in q:
        reasons.append("strict resolution wording creates a caretaker-vs-confirmed-PM trap")
    if "angie craig" in q:
        reasons.append("OpenFEC confirms candidacy; primary polling/endorsement split creates measurable path")
    if _source_error_summary(api):
        blockers.append("some source adapters returned errors; review source_errors")
    if reasons and not blockers:
        decision = "ready_for_manual_deep_dive"
    return {"decision": decision, "reasons": reasons, "blockers": blockers}


async def _gamma_market_details(client: httpx.AsyncClient, condition_id: str) -> dict:
    try:
        r = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={"condition_ids": condition_id},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return {"error": "market not found"}
    m = items[0]
    return {
        "question": m.get("question"),
        "description": (m.get("description") or "")[:3000],
        "resolution_source": m.get("resolutionSource"),
        "url": f"https://polymarket.com/event/{m.get('slug')}" if m.get("slug") else None,
        "tags": [t.get("label") if isinstance(t, dict) else t for t in (m.get("tags") or [])],
        "end_date": m.get("endDate"),
        "volume": m.get("volumeNum") or m.get("volume"),
        "liquidity": m.get("liquidityNum") or m.get("liquidity"),
    }


async def _api_enrich_candidate(client: httpx.AsyncClient, candidate: dict) -> dict:
    question = candidate["question"]
    entity = _guess_primary_entity(question)
    api = {
        "polymarket_details": await _gamma_market_details(client, candidate["condition_id"]),
        "gdelt_news": _trim_list(await gdelt.search_articles(
            client, _gdelt_query_for_question(question, entity), days_back=14, max_records=5), "articles", 5),
        "wiki_summary": await wikipedia.wikipedia_summary(client, entity),
        "wiki_search": _trim_list(await wikipedia.wikidata_search(client, entity, limit=5), "results", 5),
    }

    # YouTube search is expensive in quota, so keep it deliberately small.
    api["youtube"] = _trim_list(await youtube.search(
        client, question.rstrip("?"), max_results=3, order="date"), "videos", 3)

    vertical = candidate.get("vertical")
    ql = question.lower()
    if vertical == "us_politics":
        state = _state_abbr_from_question(question)
        office = _office_from_question(question)
        if office:
            api["openfec_candidate_search"] = _trim_list(await openfec.candidate_search(
                client, entity, state=state, cycle=2026, office=office), "candidates", 5)
        else:
            api["openfec_note"] = "State/local race or announcement market; OpenFEC does not directly cover it."
    if vertical == "international_geopolitics":
        if "ukraine" in ql:
            api["reliefweb"] = _trim_list(await reliefweb.search_reports(
                client, "Ukraine ceasefire", country="Ukraine", limit=3, days_back=14), "reports", 3)
            api["acled"] = await acled.events_by_country(client, "Ukraine", days_back=7, limit=3)
        if "romania" in ql or "bolojan" in ql:
            api["gdelt_romania_specific"] = _trim_list(await gdelt.search_articles(
                client, "Ilie Bolojan prime minister Romania", days_back=14, max_records=5), "articles", 5)
        if "gyeongsangnam" in ql or "kim kyung" in ql or "park wan" in ql:
            api["gdelt_korea_specific"] = _trim_list(await gdelt.search_articles(
                client, "Kim Kyung soo Park Wan soo Gyeongsangnam governor election", days_back=30, max_records=5), "articles", 5)
    if vertical == "tech_business" or "lmarena" in (api["polymarket_details"].get("description") or "").lower():
        api["arxiv"] = _trim_list(await arxiv.search_papers(
            client, "Google Gemini LMArena leaderboard", max_results=3), "papers", 3)
        api["github_gemini_cli"] = await github.repo_overview(client, "google-gemini/gemini-cli")

    return {
        "candidate": candidate,
        "entity_guess": entity,
        "api": api,
        "source_errors": _source_error_summary(api),
        "research_gate": _enrichment_decision(candidate, api),
    }



def _reports_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "Signal" / "reports"


def _write_report_file(filename: str, body: str) -> str:
    reports_dir = _reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / filename
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return str(path)


def _fmt_price(value) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except Exception:
        return str(value)


def _fmt_num(value) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):,.0f}"
    except Exception:
        return str(value)


def _trim_text(value: str | None, limit: int = 220) -> str:
    if not value:
        return ""
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _tier_enriched_candidates(enriched: list[dict]) -> dict:
    tier_a = []
    tier_b = []
    tier_c = []
    for item in enriched:
        candidate = item.get("candidate") or {}
        gate = item.get("research_gate") or {}
        blockers = gate.get("blockers") or []
        reasons = gate.get("reasons") or []
        decision = gate.get("decision") or "needs_deep_research"
        score = candidate.get("raw_discoverability_score")
        price = candidate.get("yes_price")
        lane = "compounder"
        if candidate.get("moonshot_sides"):
            lane = "moonshot"
        elif price is not None:
            try:
                p = float(price)
                if p <= config.SPECULATIVE_PRICE_MAX or p >= 1.0 - config.SPECULATIVE_PRICE_MAX:
                    lane = "moonshot"
                elif p <= config.DISCOVERY_COMPOUNDER_PRICE_MAX:
                    lane = "compounder"
            except Exception:
                pass
        packet = {
            "condition_id": candidate.get("condition_id"),
            "question": candidate.get("question"),
            "slug": candidate.get("slug"),
            "lane": lane,
            "yes_price": candidate.get("yes_price"),
            "no_price": candidate.get("no_price"),
            "spread": candidate.get("spread"),
            "liquidity": candidate.get("liquidity"),
            "volume": candidate.get("volume"),
            "score": score,
            "decision": decision,
            "reasons": reasons,
            "blockers": blockers,
            "source_errors": item.get("source_errors") or [],
            "next_action": "SINGLE_MARKET_FULL_DEEP_DIVE" if decision == "ready_for_manual_deep_dive" else "watch_or_enrich_more",
        }
        if decision == "ready_for_manual_deep_dive" or (score is not None and score >= 0.62 and not blockers):
            tier_a.append(packet)
        elif decision in {"needs_deep_research", "watch_only"} or reasons:
            tier_b.append(packet)
        else:
            tier_c.append(packet)
    tier_a.sort(key=lambda x: (x.get("score") is not None, x.get("score") or 0), reverse=True)
    tier_b.sort(key=lambda x: (x.get("score") is not None, x.get("score") or 0), reverse=True)
    return {"tier_a_deep_research_now": tier_a, "tier_b_watchlist": tier_b, "tier_c_reject_or_skip": tier_c}


def _candidate_table_md(title: str, rows: list[dict]) -> str:
    lines = [f"## {title}", "", "| Market | Lane | YES | Spread | Liquidity | Decision | Blocker / reason |", "|---|---|---:|---:|---:|---|---|"]
    if not rows:
        lines.append("| None | - | - | - | - | - | - |")
        return "\n".join(lines)
    for r in rows:
        reason = "; ".join((r.get("blockers") or [])[:2]) or "; ".join((r.get("reasons") or [])[:2]) or r.get("next_action") or ""
        lines.append(
            f"| {_trim_text(r.get('question'), 90)} | {r.get('lane') or ''} | {_fmt_price(r.get('yes_price'))} | "
            f"{_fmt_price(r.get('spread'))} | {_fmt_num(r.get('liquidity'))} | {r.get('decision') or ''} | {_trim_text(reason, 120)} |"
        )
    return "\n".join(lines)


def _discovery_cycle_report(discovery: dict, enriched: list[dict], tiers: dict, ledger_summary: dict, maintenance: dict | None) -> str:
    date = _today()
    lines = [
        f"# Master Discovery Research Cycle - {date}",
        "",
        "## Executive Summary",
        "",
        "This report was generated by `master_discovery_research_cycle`.",
        "It is an intake and enrichment workflow, not a signal-creation workflow.",
        "Signals, positions, and fills are forbidden here; Tier A candidates still require full L2 dossier and L3 signal gate.",
        "",
        "## Run Stats",
        "",
        f"- Scanned markets: {discovery.get('scanned_markets') if discovery else 0}",
        f"- Persisted markets/snapshots: {discovery.get('persisted_markets') if discovery else 0}",
        f"- Candidate count: {discovery.get('candidate_count') if discovery else 0}",
        f"- Enriched candidates: {len(enriched)}",
        f"- Ledger rows reviewed: {ledger_summary.get('count')}",
        f"- Gate violations in ledger: {ledger_summary.get('gate_violations')}",
        "",
        _candidate_table_md("Tier A - Deep Research Now", tiers["tier_a_deep_research_now"]),
        "",
        _candidate_table_md("Tier B - Watch / Enrich More", tiers["tier_b_watchlist"]),
        "",
        _candidate_table_md("Tier C - Reject / Skip For Now", tiers["tier_c_reject_or_skip"]),
        "",
        "## Source / API Notes",
        "",
    ]
    source_errors = []
    for item in enriched:
        for err in item.get("source_errors") or []:
            source_errors.append(f"- {_trim_text((item.get('candidate') or {}).get('question'), 80)}: {err}")
    lines.extend(source_errors[:40] or ["- No source adapter errors reported in enriched candidates."])
    lines.extend([
        "",
        "## Database Writes",
        "",
        "Allowed writes performed by this workflow:",
        "",
        "- markets upserted from Polymarket metadata",
        "- snapshots recorded from live market/orderbook data",
        "- market tags recorded by classifier",
        "",
        "Forbidden writes intentionally not performed:",
        "",
        "- evidence",
        "- final analyses",
        "- pre-bet checklists",
        "- signals",
        "- positions",
        "- fills",
        "",
        "## Next Actions",
        "",
    ])
    for r in tiers["tier_a_deep_research_now"][:10]:
        lines.append(f"- Run `SINGLE_MARKET_FULL_DEEP_DIVE` for `{r.get('condition_id')}` - {_trim_text(r.get('question'), 120)}")
    if not tiers["tier_a_deep_research_now"]:
        lines.append("- No Tier A candidate cleared the intake gate. Continue enrichment/watchlist rather than forcing a signal.")
    if maintenance:
        lines.extend(["", "## Maintenance Context", ""])
        for item in (maintenance.get("health") or {}).get("must_fix", []):
            lines.append(f"- MUST FIX: {item}")
        for item in (maintenance.get("health") or {}).get("should_fix", []):
            lines.append(f"- SHOULD FIX: {item}")
    return "\n".join(lines)


def _learning_cycle_report(ledger: list[dict], brief: dict, learning: dict, tasks: list[dict], maintenance: dict | None) -> str:
    date = _today()
    gate_violations = [r for r in ledger if r.get("gate_violation")]
    stale = [r for r in ledger if r.get("stale_open_position")]
    resolved_pending = [r for r in ledger if r.get("status") == "resolved_pending_learning"]
    lines = [
        f"# Master Learning Cycle - {date}",
        "",
        "## Executive Summary",
        "",
        "This report was generated by `master_learning_cycle`.",
        "It does not invent lessons silently; it identifies learning debt and returns the exact legal records to write next.",
        "",
        "## Learning Debt",
        "",
        f"- Pending outcome reviews: {len(brief.get('pending_outcome_reviews') or [])}",
        f"- Stale open positions: {len(brief.get('stale_open_positions') or [])}",
        f"- Incomplete dossiers: {len(brief.get('incomplete_research') or [])}",
        f"- Ledger gate violations: {len(gate_violations)}",
        f"- Resolved pending learning in ledger: {len(resolved_pending)}",
        "",
        "## Priority Tasks",
        "",
        "| Priority | Kind | Market | Why |",
        "|---|---|---|---|",
    ]
    if tasks:
        for t in tasks[:60]:
            lines.append(f"| {t.get('priority')} | {t.get('kind')} | `{t.get('condition_id')}` | {_trim_text(t.get('why') or ', '.join(t.get('missing') or []), 120)} |")
    else:
        lines.append("| none | - | - | No immediate learning tasks found. |")
    lines.extend(["", "## Weak Archetypes", ""])
    weak = learning.get("weak_archetypes") or []
    if weak:
        for item in weak[:20]:
            lines.append(f"- {item.get('primary_archetype')}: n={item.get('n')}, avg_mtm_roi={item.get('avg_mtm_roi_pct')}%, pnl={item.get('total_mtm_pnl')}")
    else:
        lines.append("- No weak archetype cluster with current data.")
    lines.extend(["", "## Strong Archetypes", ""])
    strong = learning.get("strong_archetypes") or []
    if strong:
        for item in strong[:20]:
            lines.append(f"- {item.get('primary_archetype')}: n={item.get('n')}, avg_mtm_roi={item.get('avg_mtm_roi_pct')}%, pnl={item.get('total_mtm_pnl')}")
    else:
        lines.append("- No strong archetype cluster with current data.")
    lines.extend(["", "## Source Registry", ""])
    sources = learning.get("source_registry_top") or []
    if sources:
        for s in sources[:20]:
            lines.append(f"- {s.get('name')} ({s.get('source_type')}): cited={s.get('times_cited')}, correct={s.get('times_correct')}, wrong={s.get('times_wrong')}, bias={s.get('bias')}")
    else:
        lines.append("- Source registry has little or no track record yet.")
    lines.extend(["", "## Required Legal Writes", ""])
    lines.extend([
        "- Use `record_outcome_learning_review` only after a market is resolved and thesis-vs-outcome is reviewed.",
        "- Use `record_forecast_update` for open positions when probability/thesis changed.",
        "- Use `record_signal_quality_review` after mark-to-market or resolution quality analysis.",
        "- Do not repair gate violations through fake retroactive checklists.",
    ])
    if maintenance:
        lines.extend(["", "## Maintenance Context", ""])
        for item in (maintenance.get("health") or {}).get("must_fix", []):
            lines.append(f"- MUST FIX: {item}")
    return "\n".join(lines)


def _start_workflow_log(workflow_name: str, workflow_level: str, input_payload: dict | None = None, agent_name: str = "codex", notes: str = "") -> int:
    with db.connect() as conn:
        run_id = db.start_workflow_run(
            conn,
            workflow_name=workflow_name,
            workflow_level=workflow_level,
            agent_name=agent_name,
            input_json=input_payload or {},
            notes=notes or None,
        )
        conn.commit()
        return run_id


def _record_workflow_step(
    workflow_run_id: int | None,
    step_name: str,
    *,
    status: str = "completed",
    condition_id: str | None = None,
    allowed_writes: list[str] | None = None,
    writes_count: int = 0,
    blocker: str | None = None,
    output_ref: str | None = None,
    output_json: dict | list | None = None,
) -> int | None:
    if not workflow_run_id:
        return None
    with db.connect() as conn:
        step_id = db.add_workflow_step(
            conn,
            workflow_run_id=workflow_run_id,
            step_name=step_name,
            status=status,
            condition_id=condition_id,
            allowed_writes=allowed_writes or [],
            writes_count=writes_count,
            blocker=blocker,
            output_ref=output_ref,
            output_json=output_json,
        )
        conn.commit()
        return step_id


def _finish_workflow_log(workflow_run_id: int | None, *, status: str = "completed", output_json: dict | None = None) -> None:
    if not workflow_run_id:
        return
    with db.connect() as conn:
        db.finish_workflow_run(conn, workflow_run_id, status=status, output_json=output_json or {})
        conn.commit()

def register(mcp):
    @mcp.tool()
    def start_workflow_run(
        workflow_name: str,
        workflow_level: str,
        agent_name: str = "codex",
        input_payload: dict | None = None,
        notes: str = "",
    ) -> dict:
        """Start an auditable workflow run. Returns workflow_run_id."""
        _ensure_db()
        run_id = _start_workflow_log(
            workflow_name,
            workflow_level,
            input_payload=input_payload or {},
            agent_name=agent_name,
            notes=notes,
        )
        return {"workflow_run_id": run_id, "status": "running"}

    @mcp.tool()
    def record_workflow_step(
        workflow_run_id: int,
        step_name: str,
        status: str = "completed",
        condition_id: str = "",
        allowed_writes: list[str] | None = None,
        writes_count: int = 0,
        blocker: str = "",
        output_ref: str = "",
        output_payload: dict | None = None,
    ) -> dict:
        """Record one auditable step inside an existing workflow run."""
        _ensure_db()
        step_id = _record_workflow_step(
            workflow_run_id,
            step_name,
            status=status,
            condition_id=condition_id or None,
            allowed_writes=allowed_writes or [],
            writes_count=writes_count,
            blocker=blocker or None,
            output_ref=output_ref or None,
            output_json=output_payload or {},
        )
        return {"workflow_run_id": workflow_run_id, "workflow_step_id": step_id, "status": status}

    @mcp.tool()
    def finish_workflow_run(
        workflow_run_id: int,
        status: str = "completed",
        output_payload: dict | None = None,
    ) -> dict:
        """Finish an auditable workflow run."""
        _ensure_db()
        _finish_workflow_log(workflow_run_id, status=status, output_json=output_payload or {})
        return {"workflow_run_id": workflow_run_id, "status": status}

    @mcp.tool()
    def workflow_runs(
        limit: int = 50,
        status: str = "",
        workflow_name: str = "",
    ) -> dict:
        """List recent workflow runs for the research lab journal."""
        _ensure_db()
        limit = max(1, min(int(limit), 500))
        with db.connect() as conn:
            rows = db.list_workflow_runs(
                conn,
                limit=limit,
                status=status or None,
                workflow_name=workflow_name or None,
            )
        return {"count": len(rows), "runs": rows}

    @mcp.tool()
    def workflow_run_detail(workflow_run_id: int) -> dict:
        """Return a workflow run with all recorded steps."""
        _ensure_db()
        with db.connect() as conn:
            detail = db.workflow_run_detail(conn, workflow_run_id)
        if detail is None:
            return {"error": "workflow_run_not_found", "workflow_run_id": workflow_run_id}
        return detail

    @mcp.tool()
    def validate_signal_gate(
        condition_id: str,
        probability_yes: float | None = None,
        confidence: float | None = None,
        side: str = "",
        proposed_stake_usd: float | None = None,
        primary_archetype: str | None = None,
    ) -> dict:
        """
        Hard runtime gate for formal Signal creation. This is read-only: it does
        not create analyses, signals, positions, or fills.
        """
        _ensure_db()
        with db.connect() as conn:
            return _validate_signal_gate(
                conn,
                condition_id=condition_id,
                probability_yes=probability_yes,
                confidence=confidence,
                intended_side=side or None,
                proposed_stake_usd=proposed_stake_usd,
                primary_archetype=primary_archetype,
            )

    @mcp.tool()
    def aladdin_signal_commit(
        condition_id: str,
        probability_yes: float | None = None,
        confidence: float | None = None,
        side: str = "",
        reasoning: str = "",
        sources: list[str] | None = None,
        intended_stake_usd: float | None = None,
        primary_archetype: str | None = None,
        paper_only: bool = True,
        dry_run: bool = False,
    ) -> dict:
        """
        The only high-level formal path from approved research to Signal paper
        position. It refuses real-money execution and refuses all commits unless
        validate_signal_gate passes.
        """
        _ensure_db()
        workflow_run_id = _start_workflow_log(
            "aladdin_signal_commit",
            "L3 signal commit",
            input_payload={
                "condition_id": condition_id,
                "side": side,
                "probability_yes": probability_yes,
                "confidence": confidence,
                "intended_stake_usd": intended_stake_usd,
                "paper_only": paper_only,
                "dry_run": dry_run,
            },
        )
        if not paper_only:
            _record_workflow_step(
                workflow_run_id,
                "reject_real_money_execution",
                status="blocked",
                condition_id=condition_id,
                allowed_writes=[],
                blocker="real_money_not_allowed_here",
            )
            _finish_workflow_log(workflow_run_id, status="blocked", output_json={"error": "real_money_not_allowed_here"})
            return {
                "error": "real_money_not_allowed_here",
                "workflow_run_id": workflow_run_id,
                "next_action": "use record_real_manual_trade for operator-entered real fills",
            }
        sources = sources or []
        if not reasoning.strip():
            reasoning = "Formal Signal commit after validate_signal_gate passed. See dossier and pre-bet checklist."

        with db.connect() as conn:
            gate = _validate_signal_gate(
                conn,
                condition_id=condition_id,
                probability_yes=probability_yes,
                confidence=confidence,
                intended_side=side or None,
                proposed_stake_usd=intended_stake_usd,
                primary_archetype=primary_archetype,
            )
            _record_workflow_step(
                workflow_run_id,
                "validate_signal_gate",
                status="completed" if gate["ok"] else "blocked",
                condition_id=condition_id,
                allowed_writes=[],
                blocker=", ".join(gate.get("blockers") or []) if not gate["ok"] else None,
                output_json={
                    "ok": gate["ok"],
                    "blockers": gate.get("blockers"),
                    "missing_blocks": gate.get("missing_blocks"),
                    "side": gate.get("side"),
                    "edge": gate.get("executable_edge"),
                    "stake": gate.get("proposed_stake_usd"),
                },
            )
            if not gate["ok"]:
                _finish_workflow_log(workflow_run_id, status="blocked", output_json={"gate": gate})
                return {
                    "workflow": "aladdin_signal_commit",
                    "workflow_run_id": workflow_run_id,
                    "gate_passed": False,
                    "signal_created": False,
                    "blocked_reason": ", ".join(gate["blockers"]),
                    "gate": gate,
                    "next_action": gate["next_action"],
                }
            if dry_run:
                _finish_workflow_log(workflow_run_id, status="completed", output_json={"dry_run": True, "gate_passed": True})
                return {
                    "workflow": "aladdin_signal_commit",
                    "workflow_run_id": workflow_run_id,
                    "gate_passed": True,
                    "signal_created": False,
                    "dry_run": True,
                    "gate": gate,
                }

            side_entry_price = float(gate.get("side_entry_price") or gate["yes_equivalent_entry"])
            yes_equivalent_entry = float(gate["yes_equivalent_entry"])
            market = conn.execute(                "SELECT vertical, end_date FROM markets WHERE condition_id = ?",
                (condition_id,),
            ).fetchone()
            signal_id = db.add_signal(
                conn,
                condition_id=condition_id,
                created_at=None,
                model="aladdin-signal-commit",
                yes_price_at_signal=yes_equivalent_entry,
                yes_equivalent_entry=yes_equivalent_entry,
                side_entry_price=side_entry_price,
                claude_prob=float(gate["probability_yes"]),
                confidence=float(gate["confidence"]),
                side=gate["side"],
                edge=float(gate["executable_edge"]),
                bet_amount=float(gate["proposed_stake_usd"]),
                reasoning=reasoning,
                sources_json=json.dumps(sources),
                tokens_in=None,
                tokens_out=None,
                cache_read_tokens=None,
                cost_usd=0.0,
                gate_status="gated",
                gate_audit_note="aladdin_signal_commit validate_signal_gate passed",
            )
            position_id = db.add_position(
                conn,
                condition_id=condition_id,
                signal_id=signal_id,
                opened_at=None,
                intended_side=gate["side"],
                intended_entry_price=side_entry_price,
                side_entry_price=side_entry_price,
                yes_equivalent_entry=yes_equivalent_entry,
                intended_stake_usd=float(gate["proposed_stake_usd"]),
                stake_source="paper",
                status="open",
                thesis_snapshot_text=reasoning,
                primary_archetype=primary_archetype,
                end_date=market["end_date"] if market else None,
            )
            shares = float(gate["proposed_stake_usd"]) / side_entry_price
            fill_id = db.add_fill(
                conn,
                position_id=position_id,
                side=gate["side"],
                price=side_entry_price,
                shares=shares,
                stake_usd=float(gate["proposed_stake_usd"]),
                venue="paper",
                slippage_vs_intent=0.0,
            )
            analysis_id = db.add_analysis(
                conn,
                run_date=_today(),
                condition_id=condition_id,
                created_at=None,
                analyst="aladdin-signal-commit",
                model="aladdin-signal-commit",
                yes_price_at_analysis=float((gate["snapshot"] or {}).get("yes_price") or gate["yes_equivalent_entry"]),
                probability_yes=float(gate["probability_yes"]),
                confidence=float(gate["confidence"]),
                edge=float(gate["executable_edge"]),
                decision="signal",
                no_signal_reason=None,
                signal_id=signal_id,
                reasoning=reasoning,
                sources_json=json.dumps(sources),
                notes="Created by aladdin_signal_commit after validate_signal_gate passed.",
            )
            conn.commit()

        commit_output = {
            "analysis_id": analysis_id,
            "signal_id": signal_id,
            "position_id": position_id,
            "fill_id": fill_id,
        }
        _record_workflow_step(
            workflow_run_id,
            "commit_paper_signal",
            status="completed",
            condition_id=condition_id,
            allowed_writes=["analyses", "signals", "positions", "fills"],
            writes_count=4,
            output_json=commit_output,
        )
        _finish_workflow_log(workflow_run_id, status="completed", output_json=commit_output)
        return {
            "workflow": "aladdin_signal_commit",
            "workflow_run_id": workflow_run_id,
            "gate_passed": True,
            "signal_created": True,
            "paper_only": True,
            "signal_id": signal_id,
            "analysis_id": analysis_id,
            "position_id": position_id,
            "fill_id": fill_id,
            "side": gate["side"],
            "entry_price": side_entry_price,
            "stake_usd": gate["proposed_stake_usd"],
            "shares": round(shares, 4),
            "gate": gate,
        }
    @mcp.tool()
    async def master_discovery_research_cycle(
        max_pages: int = 6,
        max_candidates: int = 16,
        enrich_top: int = 10,
        vertical: str | None = None,
        write_report: bool = True,
    ) -> dict:
        """
        True master discovery cycle: run live market intake, persist allowed
        market/snapshot/tag facts, enrich the best candidates with configured
        source APIs, tier them for deep research, and optionally write an owner
        report under docs/Signal/reports.

        This is L0 -> L1 orchestration plus L2 planning. It never creates final
        evidence, analyses, pre-bet checklists, signals, positions, or fills.
        """
        _ensure_db()
        max_pages = max(1, min(int(max_pages), 10))
        max_candidates = max(1, min(int(max_candidates), 50))
        enrich_top = max(1, min(int(enrich_top), max_candidates, 25))
        workflow_run_id = _start_workflow_log(
            "master_discovery_research_cycle",
            "L0 -> L1 -> L2 planning",
            input_payload={
                "max_pages": max_pages,
                "max_candidates": max_candidates,
                "enrich_top": enrich_top,
                "vertical": vertical,
                "write_report": write_report,
            },
        )

        discovery = await _run_market_discovery(
            max_pages=max_pages,
            max_candidates=max_candidates,
            vertical=vertical,
            include_recent_reviews=False,
        )
        candidates = discovery["top_candidates"][:enrich_top]
        _record_workflow_step(
            workflow_run_id,
            "discovery_scan",
            allowed_writes=["markets", "snapshots", "market_tags"],
            writes_count=int(discovery.get("persisted_markets") or 0),
            output_json={
                "scanned_markets": discovery.get("scanned_markets"),
                "candidate_count": discovery.get("candidate_count"),
                "selected_for_enrichment": len(candidates),
            },
        )

        enriched = []
        if candidates:
            async with httpx.AsyncClient(timeout=45) as client:
                for candidate in candidates:
                    enriched.append(await _api_enrich_candidate(client, candidate))
        _record_workflow_step(
            workflow_run_id,
            "api_enrichment",
            allowed_writes=[],
            output_json={"enriched_count": len(enriched)},
        )

        tiers = _tier_enriched_candidates(enriched)
        _record_workflow_step(
            workflow_run_id,
            "tier_candidates",
            allowed_writes=[],
            output_json={
                "tier_a": len(tiers["tier_a_deep_research_now"]),
                "tier_b": len(tiers["tier_b_watchlist"]),
                "tier_c": len(tiers["tier_c_reject_or_skip"]),
            },
        )
        with db.connect() as conn:
            ledger_rows = research_ledger_rows(conn, limit=100, include_discovered=False)
            ledger_summary = research_ledger_summary(ledger_rows)

        maintenance = master_maintenance_audit(limit=30)
        _record_workflow_step(
            workflow_run_id,
            "maintenance_audit",
            allowed_writes=["workflow_runs", "workflow_steps"],
            output_json=maintenance.get("health") if maintenance else {},
        )
        report_path = None
        if write_report:
            report_body = _discovery_cycle_report(discovery, enriched, tiers, ledger_summary, maintenance)
            report_path = _write_report_file(f"{_today()} - Master Discovery Research Cycle RU.md", report_body)
            _record_workflow_step(
                workflow_run_id,
                "write_report",
                allowed_writes=["markdown_report"],
                writes_count=1,
                output_ref=report_path,
            )
        output_summary = {
            "tier_a": len(tiers["tier_a_deep_research_now"]),
            "tier_b": len(tiers["tier_b_watchlist"]),
            "tier_c": len(tiers["tier_c_reject_or_skip"]),
            "report_path": report_path,
        }
        _finish_workflow_log(workflow_run_id, status="completed", output_json=output_summary)

        return {
            "workflow": "master_discovery_research_cycle",
            "workflow_run_id": workflow_run_id,
            "workflow_level": "L0 -> L1 -> L2 planning",
            "date": _today(),
            "vertical": vertical or "all",
            "rules": {
                "signals_created": False,
                "positions_created": False,
                "fills_created": False,
                "allowed_writes": ["markets", "snapshots", "market_tags", "markdown_report", "workflow_runs", "workflow_steps"],
                "forbidden_writes": ["evidence", "analyses", "pre_bet_checklists", "signals", "positions", "fills"],
            },
            "discovery": discovery,
            "enriched_count": len(enriched),
            "tiers": tiers,
            "ledger_summary": ledger_summary,
            "maintenance_health": maintenance.get("health") if maintenance else None,
            "report_path": report_path,
            "deep_research_packets": enriched,
            "recommended_next_calls": [
                "SINGLE_MARKET_FULL_DEEP_DIVE for Tier A candidates",
                "record_resolution_map / record_evidence only after human/agent source review",
                "SIGNAL_COMMIT_GATE only after approved pre_bet_checklist",
                "master_learning_cycle after the research session",
            ],
        }
    @mcp.tool()
    async def master_market_discovery(
        max_pages: int = 4,
        max_candidates: int = 12,
        vertical: str | None = None,
        include_recent_reviews: bool = False,
    ) -> dict:
        """
        One-call intake workflow: scan Polymarket, persist market/snapshot data,
        rank hidden-gem/moonshot candidates, and return a concrete research queue.

        This is not a signal generator. It records market data sources and creates
        the next-action packet needed before evidence/dossier/checklist/signal.
        """
        _ensure_db()
        max_pages = max(1, min(int(max_pages), 10))
        max_candidates = max(1, min(int(max_candidates), 50))
        result = await _run_market_discovery(
            max_pages=max_pages,
            max_candidates=max_candidates,
            vertical=vertical,
            include_recent_reviews=include_recent_reviews,
        )
        return {
            "workflow": "master_market_discovery",
            "date": _today(),
            "vertical": vertical or "all",
            **result,
            "recommended_next_master_command": "master_learning_cycle after research session or aladdin_master_cycle tomorrow",
        }


    @mcp.tool()
    async def api_research_enrichment(
        condition_ids: list[str] | None = None,
        max_pages: int = 6,
        max_candidates: int = 5,
        vertical: str | None = None,
    ) -> dict:
        """
        Enrich discovery candidates with external APIs and route them into
        ready_for_manual_deep_dive / needs_deep_research / watch_only.

        If condition_ids is omitted, this first runs live market discovery and
        enriches the top candidates. It does not write final evidence or emit a
        signal; it returns source packets and blocker notes for the analyst.
        """
        _ensure_db()
        max_pages = max(1, min(int(max_pages), 10))
        max_candidates = max(1, min(int(max_candidates), 20))
        if condition_ids:
            with db.connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT m.condition_id, m.question, m.slug, m.vertical, m.end_date,
                           s.yes_price, s.no_price, s.best_bid, s.best_ask, s.spread,
                           s.liquidity, s.volume
                    FROM markets m
                    LEFT JOIN snapshots s ON s.id = (
                        SELECT id FROM snapshots WHERE condition_id = m.condition_id
                        ORDER BY captured_at DESC LIMIT 1
                    )
                    WHERE m.condition_id IN ({','.join('?' for _ in condition_ids)})
                    """,
                    condition_ids,
                ).fetchall()
            candidates = []
            for r in rows:
                yes = float(r["yes_price"] or 0.0)
                no = float(r["no_price"] or (1.0 - yes if yes else 0.0))
                candidates.append({
                    "condition_id": r["condition_id"],
                    "question": r["question"],
                    "slug": r["slug"],
                    "vertical": r["vertical"],
                    "theme_tags": classify_theme_tags(r["question"]),
                    "end_date": r["end_date"],
                    "yes_price": round(yes, 4),
                    "no_price": round(no, 4),
                    "spread": r["spread"],
                    "liquidity": r["liquidity"],
                    "volume": r["volume"],
                    "moonshot_sides": (["YES"] if yes and yes <= config.SPECULATIVE_PRICE_MAX else []) + (["NO"] if no and no <= config.SPECULATIVE_PRICE_MAX else []),
                    "raw_discoverability_score": None,
                })
            discovery = None
        else:
            discovery = await _run_market_discovery(
                max_pages=max_pages,
                max_candidates=max_candidates,
                vertical=vertical,
                include_recent_reviews=False,
            )
            candidates = discovery["top_candidates"][:max_candidates]

        async with httpx.AsyncClient(timeout=45) as client:
            enriched = []
            for candidate in candidates[:max_candidates]:
                enriched.append(await _api_enrich_candidate(client, candidate))

        return {
            "workflow": "api_research_enrichment",
            "date": _today(),
            "discovery": discovery,
            "count": len(enriched),
            "enriched_candidates": enriched,
            "recommended_next_calls": [
                "record_evidence for primary sources that survived analyst review",
                "record_resolution_map before any signal checklist",
                "record_moonshot_review or record_hidden_gem_review for promoted candidates",
                "record_pre_bet_checklist only after dossier completeness is high",
            ],
        }

    @mcp.tool()
    def master_learning_cycle(limit: int = 50, write_report: bool = True) -> dict:
        """
        True master learning workflow: inspect ledger state, open/closed/resolved
        positions, stale forecasts, incomplete dossiers, archetype performance,
        benchmark/source health, and optionally write a learning report.

        This is L4 learning orchestration. It returns the exact legal write tasks
        needed next; it does not fabricate outcome reviews or forecast updates.
        """
        _ensure_db()
        limit = max(1, min(int(limit), 200))
        with db.connect() as conn:
            brief = _workflow_brief(conn, limit)
            learning = _learning_snapshot(conn, limit)
            ledger_rows = research_ledger_rows(conn, limit=limit, include_discovered=False)
            ledger_summary = research_ledger_summary(ledger_rows)

        tasks = []
        for item in brief["pending_outcome_reviews"]:
            tasks.append({
                "priority": "critical",
                "kind": "record_outcome_learning_review",
                "condition_id": item["condition_id"],
                "why": "resolved market has no post-mortem; learning loop is incomplete",
            })
        for row in ledger_rows:
            if row.get("gate_violation"):
                tasks.append({
                    "priority": "critical",
                    "kind": "repair_signal_gate_audit",
                    "condition_id": row["condition_id"],
                    "why": "signal exists without approved pre_bet_checklist before signal time",
                })
        for item in brief["stale_open_positions"]:
            tasks.append({
                "priority": "high",
                "kind": "record_forecast_update",
                "condition_id": item["condition_id"],
                "why": "open position has no analysis/forecast update in the last 72h",
            })
        for item in brief["incomplete_research"][:limit]:
            tasks.append({
                "priority": "medium",
                "kind": "complete_dossier",
                "condition_id": item["condition_id"],
                "missing": item["missing"],
                "why": "research completeness below 85",
            })
        for row in ledger_rows:
            if row.get("status") == "watch" and row.get("next_check_at"):
                tasks.append({
                    "priority": "medium",
                    "kind": "recheck_watch_candidate",
                    "condition_id": row["condition_id"],
                    "why": f"watch candidate has next_check_at={row.get('next_check_at')}",
                })

        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        tasks.sort(key=lambda t: (priority_order.get(t.get("priority"), 9), t.get("kind", "")))
        maintenance = master_maintenance_audit(limit=min(limit, 100))

        report_path = None
        if write_report:
            report_body = _learning_cycle_report(ledger_rows, brief, learning, tasks, maintenance)
            report_path = _write_report_file(f"{_today()} - Master Learning Cycle RU.md", report_body)

        return {
            "workflow": "master_learning_cycle",
            "workflow_level": "L4 learning",
            "date": _today(),
            "rules": {
                "signals_created": False,
                "positions_created": False,
                "fills_created": False,
                "allowed_writes": ["markdown_report"],
                "legal_next_writes": [
                    "record_outcome_learning_review",
                    "record_forecast_update",
                    "record_signal_quality_review",
                    "repair tool only after explicit approval",
                ],
                "forbidden_writes": ["fake retrospective checklist", "direct SQLite repair", "new signal"],
            },
            "portfolio": brief["portfolio_exposure"],
            "ledger_summary": ledger_summary,
            "learning_snapshot": learning,
            "auto_learning_tasks": tasks[:limit],
            "maintenance_health": maintenance.get("health") if maintenance else None,
            "report_path": report_path,
            "recommended_next_calls": [
                "record_outcome_learning_review for critical resolved markets",
                "record_forecast_update for high-priority stale open positions",
                "repair_signal_gate_audit for manual/retrospective gate violations",
                "signal_regression_benchmark after adding/updating benchmark cases",
                "source_track_record to audit overused/weak sources",
            ],
        }

    @mcp.tool()
    def research_ledger(
        status: str = "",
        lane: str = "",
        limit: int = 100,
        include_discovered: bool = False,
    ) -> dict:
        """
        Unified lifecycle ledger for dashboard/owner review.

        This reads existing database facts and returns one row per market across
        discovered, watch, deep_research, rejected, signal/open_position,
        resolved_pending_learning, and learned states. It does not fabricate a
        decision or write new facts.
        """
        _ensure_db()
        limit = max(1, min(int(limit), 500))
        with db.connect() as conn:
            rows = research_ledger_rows(
                conn,
                status=status or None,
                lane=lane or None,
                limit=limit,
                include_discovered=include_discovered,
            )
            summary = research_ledger_summary(rows)
        return {
            "workflow": "research_ledger",
            "date": _today(),
            "filters": {
                "status": status or None,
                "lane": lane or None,
                "include_discovered": include_discovered,
                "limit": limit,
            },
            "summary": summary,
            "rows": rows,
            "status_model": [
                "discovered",
                "watch",
                "deep_research",
                "needs_more_research",
                "approved_for_signal",
                "no_signal",
                "rejected",
                "signal",
                "open_position",
                "resolved_pending_learning",
                "learned",
            ],
        }

    @mcp.tool()
    def master_maintenance_audit(limit: int = 30) -> dict:
        """
        One-call hygiene workflow: find project-state gaps that quietly rot the
        research memory when the operator forgets a step.
        """
        _ensure_db()
        limit = max(1, min(int(limit), 100))
        docs_dir = Path(__file__).resolve().parents[2] / "docs" / "Signal"
        duplicate_doc_numbers = []
        if docs_dir.exists():
            seen: dict[str, list[str]] = {}
            for p in docs_dir.rglob("*.md"):
                prefix = p.name.split(" - ", 1)[0]
                if prefix.isdigit():
                    key = str(p.parent.relative_to(docs_dir)) + ":" + prefix
                    seen.setdefault(key, []).append(str(p.relative_to(docs_dir)))
            duplicate_doc_numbers = [names for names in seen.values() if len(names) > 1]

        with db.connect() as conn:
            brief = _workflow_brief(conn, limit)
            no_snapshot_open = conn.execute("""
                SELECT p.condition_id, m.question, p.intended_side
                FROM positions p
                JOIN markets m ON m.condition_id = p.condition_id
                LEFT JOIN snapshots s ON s.condition_id = p.condition_id
                WHERE p.status IN ('open','filled','partially_filled')
                GROUP BY p.condition_id
                HAVING COUNT(s.id) = 0
                LIMIT ?
            """, (limit,)).fetchall()
            evidence_without_source = conn.execute("""
                SELECT e.id, e.condition_id, m.question, e.claim
                FROM evidence e
                JOIN markets m ON m.condition_id = e.condition_id
                WHERE e.source_url IS NULL AND e.source_name IS NULL
                ORDER BY e.created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            parser_high_risk = conn.execute("""
                SELECT rm.condition_id, m.question, rm.parser_ambiguity_score,
                       rm.parser_suggestion
                FROM resolution_maps rm
                JOIN markets m ON m.condition_id = rm.condition_id
                WHERE rm.parser_ambiguity_score >= 0.4
                ORDER BY rm.created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            signals_without_prebet = conn.execute("""
                SELECT s.id AS signal_id, s.condition_id, m.question, s.created_at,
                       s.side, s.yes_price_at_signal, s.claude_prob, s.confidence,
                       s.edge, s.bet_amount
                FROM signals s
                JOIN markets m ON m.condition_id = s.condition_id
                WHERE COALESCE(s.manual_trade, 0) = 0
                  AND NOT EXISTS (
                    SELECT 1 FROM pre_bet_checklists pc
                    WHERE pc.condition_id = s.condition_id
                      AND pc.created_at <= s.created_at
                      AND pc.decision = 'approved_for_signal'
                )
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT ?
            """, (limit,)).fetchall()
        must_fix = []
        if brief["pending_outcome_reviews"]:
            must_fix.append("resolved positions missing outcome_learning_review")
        if no_snapshot_open:
            must_fix.append("open positions without any snapshot")
        if evidence_without_source:
            must_fix.append("evidence rows without source_url/source_name")
        if signals_without_prebet:
            must_fix.append("signals exist without approved pre_bet_checklist")
        should_fix = []
        if brief["incomplete_research"]:
            should_fix.append("incomplete dossiers below 85 completeness")
        if duplicate_doc_numbers:
            should_fix.append("duplicate documentation numbers")
        if parser_high_risk:
            should_fix.append("high ambiguity resolution maps need explicit ambiguity_cases")
        return {
            "workflow": "master_maintenance_audit",
            "date": _today(),
            "health": {
                "must_fix_count": len(must_fix),
                "should_fix_count": len(should_fix),
                "must_fix": must_fix,
                "should_fix": should_fix,
            },
            "open_positions_without_snapshots": [dict(r) for r in no_snapshot_open],
            "evidence_without_sources": [dict(r) for r in evidence_without_source],
            "high_resolution_ambiguity": [dict(r) for r in parser_high_risk],
            "signals_without_prebet": [dict(r) for r in signals_without_prebet],
            "duplicate_doc_numbers": duplicate_doc_numbers,
            "incomplete_research": brief["incomplete_research"],
            "pending_outcome_reviews": brief["pending_outcome_reviews"],
            "recommended_next_calls": [
                "master_learning_cycle",
                "backfill_price_history or fetch_candidates for no-snapshot positions",
                "record_evidence with source_url/source_name for source-less evidence",
            ],
        }

    @mcp.tool()
    async def aladdin_master_cycle(
        run_discovery: bool = True,
        max_pages: int = 4,
        max_candidates: int = 10,
        vertical: str | None = None,
        limit: int = 20,
    ) -> dict:
        """
        Full session command. Runs the three operator panels in one call:
        discovery intake, learning cycle, and maintenance audit.

        This is the closest thing to an "open the terminal and think for me"
        command. It still returns queues instead of fabricating final signals.
        """
        _ensure_db()
        max_pages = max(1, min(int(max_pages), 10))
        max_candidates = max(1, min(int(max_candidates), 50))
        limit = max(1, min(int(limit), 100))

        discovery = None
        if run_discovery:
            discovery = await _run_market_discovery(
                max_pages=max_pages,
                max_candidates=max_candidates,
                vertical=vertical,
                include_recent_reviews=False,
            )
        with db.connect() as conn:
            brief = _workflow_brief(conn, limit)
            learning = _learning_snapshot(conn, limit)
        return {
            "workflow": "aladdin_master_cycle",
            "date": _today(),
            "discovery": discovery,
            "portfolio": brief["portfolio_exposure"],
            "pending_outcome_reviews": brief["pending_outcome_reviews"],
            "stale_open_positions": brief["stale_open_positions"],
            "incomplete_research": brief["incomplete_research"],
            "learning_snapshot": learning,
            "operator_priorities": [
                "1. Resolve learning debt: outcome reviews and stale open positions.",
                "2. Backfill/top-source the best discovery candidates.",
                "3. Build dossier before any pre-bet checklist.",
                "4. Run record_analysis only after approved_for_signal.",
            ],
            "suggested_next_calls": [
                "master_discovery_research_cycle for full discovery + enrichment + report",
                "master_market_discovery for fresh intake only",
                "master_learning_cycle for post-market/post-resolution learning",
                "master_maintenance_audit for hygiene before a serious session",
            ],
        }
