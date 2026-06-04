"""Command P — Private Market Intelligence.

Specialized scan for Polymarket private-company valuation markets powered by
Nasdaq Private Market (NPM) data. This is a research workflow only: it does not
create signals or positions.

Why this exists:
  Private-company markets are not normal "company is worth X" questions. Many
  resolve to a provider mark such as NPM Price, with publication cadence, lag,
  IPO/direct-listing clauses, corporate-action clauses, and revision rules.
  Command P extracts those mechanics before any Forager/D/C cycle.

Outputs:
  - bot/private_market_candidates.json
  - bot/private_market_report.md
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

sys.path.insert(0, ".")
load_dotenv(".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import db; db.init()
from markets import _execution_prices, classify_theme_tags
from tools.workflows import _finish_workflow_log, _record_workflow_step, _start_workflow_log

GAMMA = "https://gamma-api.polymarket.com"

MAX_PAGES = int(os.getenv("SIGNAL_COMMAND_P_MAX_PAGES", "100"))
PAGE_SIZE = 100
MIN_VOLUME_USD = float(os.getenv("SIGNAL_COMMAND_P_MIN_VOLUME", "0"))
P_QUEUE_N = int(os.getenv("SIGNAL_COMMAND_P_QUEUE_N", "6"))
P_QUEUE_MAX_PER_COMPANY = int(os.getenv("SIGNAL_COMMAND_P_QUEUE_MAX_PER_COMPANY", "1"))

PRIVATE_COMPANY_HINTS = (
    "openai", "anthropic", "spacex", "space x", "anduril", "stripe",
    "databricks", "perplexity", "xai", "figma", "revolut", "neuralink",
)
NPM_HINTS = (
    "nasdaq private market", "npm price", "npm prices", "secondmarket.com",
    "private market valuation", "private-company", "private company",
)


@dataclass
class PrivateMarketMechanics:
    provider: str | None
    metric: str | None
    publication_cadence: str | None
    reporting_lag: str | None
    threshold: str | None
    direction: str | None
    period_end: str | None
    ipo_clause: bool
    corporate_action_clause: bool
    revision_rule: str | None
    source_url: str | None
    ambiguity_flags: list[str]


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("вЂ™", "'")
        .replace("вЂњ", '"')
        .replace("вЂќ", '"')
        .replace("вЂ”", "-")
    )


def _load_prices(m: dict) -> tuple[float | None, float | None]:
    prices = m.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            prices = []
    if not prices or len(prices) < 2:
        return None, None
    try:
        yes = float(prices[0])
    except (TypeError, ValueError):
        return None, None
    try:
        no = float(prices[1])
    except (TypeError, ValueError):
        no = 1.0 - yes
    return yes, no


def _text_for_market(m: dict) -> str:
    fields = [
        _clean_text(m.get("question")),
        _clean_text(m.get("description")),
        _clean_text(m.get("resolutionSource")),
        _clean_text(m.get("groupItemTitle")),
        _clean_text(m.get("slug")),
    ]
    events = m.get("events") or []
    for event in events:
        if isinstance(event, dict):
            fields.append(_clean_text(event.get("title")))
            fields.append(_clean_text(event.get("description")))
    return "\n".join(fields)


def is_private_market(m: dict) -> bool:
    text = _text_for_market(m).lower()
    return any(h in text for h in NPM_HINTS) or (
        "valuation" in text and any(h in text for h in PRIVATE_COMPANY_HINTS)
    )


def _extract_company(question: str, slug: str = "") -> str | None:
    text = f"{question} {slug}".lower()
    canonical = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "spacex": "SpaceX",
        "space x": "SpaceX",
        "anduril": "Anduril",
        "stripe": "Stripe",
        "databricks": "Databricks",
        "perplexity": "Perplexity",
        "xai": "xAI",
        "figma": "Figma",
        "revolut": "Revolut",
        "neuralink": "Neuralink",
    }
    for key, name in canonical.items():
        if key in text:
            return name
    m = re.search(r"Will\s+([A-Z][A-Za-z0-9 .-]{2,40}?)['’]s valuation", question)
    if m:
        return m.group(1).strip()
    return None


def _extract_threshold(question: str) -> tuple[str | None, str | None]:
    q = question.replace(",", "")
    direction = None
    if re.search(r"\(LOW\)", q, re.I):
        direction = "<="
    elif re.search(r"\(HIGH\)", q, re.I):
        direction = ">="
    elif re.search(r"\b(hit|reach|exceed|above|at least|cross)\b|↑", q, re.I):
        direction = ">="
    elif re.search(r"\b(below|under|fall|drop|less than)\b|↓", q, re.I):
        direction = "<="
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*([TtBbMm])\b", q)
    if not m:
        return None, direction
    unit = m.group(2).upper()
    return f"${m.group(1)}{unit}", direction


def parse_npm_mechanics(market: dict) -> PrivateMarketMechanics:
    question = market.get("question") or ""
    text = _text_for_market(market)
    lower = text.lower()
    threshold, direction = _extract_threshold(question)

    provider = None
    if "nasdaq private market" in lower or "npm price" in lower or "npm prices" in lower:
        provider = "Nasdaq Private Market (NPM)"

    metric = None
    if "npm price" in lower or "npm prices" in lower:
        metric = "NPM Price"
    elif "private market valuation" in lower:
        metric = "private market valuation"

    publication_cadence = None
    reporting_lag = None
    if "published for trading days only" in lower:
        publication_cadence = "trading_days_only"
    if "updated once daily" in lower:
        publication_cadence = publication_cadence or "daily"
    lag_match = re.search(r"updated once daily at ([0-9: ]+[AP]M ET).*?following calendar day", text, re.I | re.S)
    if lag_match:
        reporting_lag = f"once daily at {lag_match.group(1).strip()} on following calendar day"
    elif "following calendar day" in lower:
        reporting_lag = "following_calendar_day"

    period_end = None
    end = market.get("endDate") or market.get("endDateIso")
    if end:
        period_end = str(end)
    date_match = re.search(r"by\s+([A-Z][a-z]+ \d{1,2}, \d{4})", question)
    if date_match:
        period_end = date_match.group(1)

    revision_rule = None
    if "revisions to previously published npm data" in lower:
        if "will not be considered" in lower:
            revision_rule = "post-publication revisions ignored except clearly erroneous corrections"
        else:
            revision_rule = "revisions mentioned; inspect exact wording"

    source_url = None
    source_match = re.search(r"https?://fe\.secondmarket\.com/[^\s)\]\"']+", text)
    if source_match:
        source_url = source_match.group(0).rstrip(".,;")
    else:
        source = market.get("resolutionSource")
        if isinstance(source, str) and source.startswith("http"):
            source_url = source

    flags: list[str] = []
    if provider is None:
        flags.append("provider_not_explicit")
    if metric is None:
        flags.append("metric_not_explicit")
    if publication_cadence is None:
        flags.append("publication_cadence_missing")
    if reporting_lag is None:
        flags.append("reporting_lag_missing")
    if threshold is None:
        flags.append("threshold_parse_missing")
    if direction is None:
        flags.append("direction_parse_missing")
    if source_url is None:
        flags.append("resolution_source_url_missing")
    if "ipo" in lower or "direct listing" in lower:
        ipo_clause = True
    else:
        ipo_clause = False
        flags.append("ipo_clause_missing")
    if "acquired" in lower or "merges" in lower or "corporate action" in lower:
        corporate_action_clause = True
    else:
        corporate_action_clause = False
        flags.append("corporate_action_clause_missing")
    if revision_rule is None:
        flags.append("revision_rule_missing")

    return PrivateMarketMechanics(
        provider=provider,
        metric=metric,
        publication_cadence=publication_cadence,
        reporting_lag=reporting_lag,
        threshold=threshold,
        direction=direction,
        period_end=period_end,
        ipo_clause=ipo_clause,
        corporate_action_clause=corporate_action_clause,
        revision_rule=revision_rule,
        source_url=source_url,
        ambiguity_flags=flags,
    )


def _mechanics_score(mechanics: PrivateMarketMechanics) -> float:
    required = [
        mechanics.provider,
        mechanics.metric,
        mechanics.publication_cadence,
        mechanics.reporting_lag,
        mechanics.threshold,
        mechanics.direction,
        mechanics.source_url,
        mechanics.revision_rule,
    ]
    score = sum(1 for x in required if x) / len(required)
    if mechanics.ipo_clause:
        score += 0.08
    if mechanics.corporate_action_clause:
        score += 0.08
    return min(1.0, round(score, 3))


def _oracle_lag_score(mechanics: PrivateMarketMechanics) -> float:
    score = 0.2
    if mechanics.provider == "Nasdaq Private Market (NPM)":
        score += 0.25
    if mechanics.reporting_lag:
        score += 0.25
    if mechanics.publication_cadence == "trading_days_only":
        score += 0.15
    if mechanics.revision_rule:
        score += 0.1
    return min(1.0, round(score, 3))


def _current_valuation_from_text(text: str) -> str | None:
    m = re.search(r"Current Valuation:\s*\$?\s*([0-9.]+)\s*([TtBbMm])", text)
    if m:
        return f"${m.group(1)}{m.group(2).upper()}"
    return None


def build_candidate(market: dict) -> dict:
    yes, no = _load_prices(market)
    best_bid = _float_or_none(market.get("bestBid"))
    best_ask = _float_or_none(market.get("bestAsk"))
    spread = _float_or_none(market.get("spread"))
    yes_entry, no_entry, spread = _execution_prices(
        yes or 0.5, no if no is not None else 0.5, best_bid, best_ask, spread
    )
    mechanics = parse_npm_mechanics(market)
    text = _text_for_market(market)
    question = _clean_text(market.get("question"))
    slug = _clean_text(market.get("slug"))
    company = _extract_company(question, slug)
    current_valuation = _current_valuation_from_text(text)
    volume = _float_or_none(market.get("volumeNum") or market.get("volume")) or 0.0
    liquidity = _float_or_none(market.get("liquidityNum") or market.get("liquidity")) or 0.0
    mechanics_score = _mechanics_score(mechanics)
    oracle_lag = _oracle_lag_score(mechanics)
    # Prioritize markets where mechanics are clear, oracle lag exists, and there
    # is enough liquidity/volume to make a later signal executable.
    liquidity_component = min(1.0, liquidity / 25000.0)
    volume_component = min(1.0, volume / 50000.0)
    research_priority = round(
        0.35 * mechanics_score + 0.30 * oracle_lag + 0.20 * volume_component + 0.15 * liquidity_component,
        3,
    )
    return {
        "condition_id": market.get("conditionId") or market.get("id"),
        "question": question,
        "slug": slug,
        "url": f"https://polymarket.com/event/{slug}" if slug else None,
        "company": company,
        "current_valuation_text": current_valuation,
        "yes_price": yes,
        "no_price": no,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "yes_entry_price": yes_entry,
        "no_entry_price": no_entry,
        "volume": volume,
        "liquidity": liquidity,
        "end_date": market.get("endDate"),
        "active": market.get("active"),
        "closed": market.get("closed"),
        "mechanics": asdict(mechanics),
        "mechanics_score": mechanics_score,
        "oracle_lag_score": oracle_lag,
        "research_priority_score": research_priority,
        "recommended_research_queries": _research_queries(company, mechanics),
    }


def _research_queries(company: str | None, mechanics: PrivateMarketMechanics) -> list[str]:
    if not company:
        company = "private company"
    queries = [
        f"{company} tender offer secondary sale valuation 2026",
        f"{company} funding round valuation IPO filing 2026",
        f"{company} mutual fund mark valuation disclosure 2026",
        f"{company} employee share sale tender offer",
    ]
    if mechanics.source_url:
        queries.insert(0, f"NPM Price {company} Nasdaq Private Market valuation")
    return queries


async def _fetch_private_markets() -> tuple[list[dict], dict]:
    seen: set[str] = set()
    matches: list[dict] = []
    stats = {"raw": 0, "private_matches": 0, "below_min_volume": 0, "duplicates": 0}
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        for page in range(MAX_PAGES):
            r = await client.get(
                f"{GAMMA}/markets",
                params={
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                    "active": "true",
                    "closed": "false",
                    "order": "volume",
                    "ascending": "false",
                },
            )
            r.raise_for_status()
            data = r.json()
            page_data = data if isinstance(data, list) else data.get("data", [])
            if not page_data:
                break
            for m in page_data:
                stats["raw"] += 1
                cid = m.get("conditionId") or m.get("id")
                if not cid or cid in seen:
                    stats["duplicates"] += 1
                    continue
                seen.add(cid)
                volume = _float_or_none(m.get("volumeNum") or m.get("volume")) or 0.0
                if volume < MIN_VOLUME_USD:
                    stats["below_min_volume"] += 1
                    continue
                if is_private_market(m):
                    stats["private_matches"] += 1
                    matches.append(m)
            await asyncio.sleep(0.05)
    return matches, stats


def _persist_candidates(candidates: list[dict]) -> None:
    with db.connect() as conn:
        for c in candidates:
            cid = c["condition_id"]
            if not cid:
                continue
            db.upsert_market(
                conn,
                condition_id=cid,
                question=c["question"] or "",
                slug=c.get("slug") or "",
                end_date=c.get("end_date"),
                vertical="tech_business",
            )
            db.set_market_tags(
                conn,
                condition_id=cid,
                tags=["private_market_valuation", "npm_resolution"],
                source="command_p",
            )
            db.add_snapshot(
                conn,
                condition_id=cid,
                yes_price=float(c["yes_price"] if c["yes_price"] is not None else 0.5),
                no_price=c.get("no_price"),
                best_bid=c.get("best_bid"),
                best_ask=c.get("best_ask"),
                spread=c.get("spread"),
                yes_entry_price=c.get("yes_entry_price"),
                no_entry_price=c.get("no_entry_price"),
                volume=c.get("volume"),
                liquidity=c.get("liquidity"),
                source="command_p_private_market_scan",
            )
        conn.commit()


def _write_outputs(candidates: list[dict], stats: dict, wf_id: int, queue: list[dict]) -> tuple[str, str]:
    base_dir = os.path.dirname(__file__)
    json_path = os.path.join(base_dir, "private_market_candidates.json")
    report_path = os.path.join(base_dir, "private_market_report.md")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workflow_run_id": wf_id,
        "stats": stats,
        "total_candidates": len(candidates),
        "queue_candidates": queue,
        "candidates": candidates,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    lines = [
        "# Command P — Private Market Intelligence",
        "",
        f"Generated: `{payload['generated_at']}`",
        f"Workflow run: `{wf_id}`",
        "",
        "## Summary",
        "",
        f"- Raw Gamma markets scanned: `{stats.get('raw', 0)}`",
        f"- Private/NPM candidates found: `{len(candidates)}`",
        f"- Diversified B queue candidates: `{len(queue)}`",
        f"- Minimum volume filter: `${MIN_VOLUME_USD:,.0f}`",
        "",
        "## Diversified B Queue",
        "",
        "| # | Company | Market | YES | Volume | Priority | Why queued |",
        "|---:|---|---|---:|---:|---:|---|",
    ]
    for i, c in enumerate(queue, 1):
        mechanics = c.get("mechanics") or {}
        lines.append(
            f"| {i} | {c.get('company') or '?'} | {c.get('question')} | "
            f"`{(c.get('yes_price') if c.get('yes_price') is not None else 0):.3f}` | "
            f"`${c.get('volume', 0):,.0f}` | `{c['research_priority_score']:.2f}` | "
            f"{mechanics.get('metric') or 'provider metric'} / {mechanics.get('reporting_lag') or 'lag unknown'} |"
        )
    lines.extend([
        "",
        "## Candidate Ranking",
        "",
        "| # | Company | Market | YES | Volume | NPM mechanics | Oracle lag | Priority | Flags |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for i, c in enumerate(candidates, 1):
        flags = ", ".join(c["mechanics"]["ambiguity_flags"][:4])
        lines.append(
            f"| {i} | {c.get('company') or '?'} | {c.get('question')} | "
            f"`{(c.get('yes_price') if c.get('yes_price') is not None else 0):.3f}` | "
            f"`${c.get('volume', 0):,.0f}` | `{c['mechanics_score']:.2f}` | "
            f"`{c['oracle_lag_score']:.2f}` | `{c['research_priority_score']:.2f}` | {flags} |"
        )
    lines.extend([
        "",
        "## Required Gate Before B/D/C",
        "",
        "Private company valuation market != fundamental valuation market.",
        "Before any formal signal, verify:",
        "",
        "- resolution provider and exact metric",
        "- NPM publication cadence and reporting lag",
        "- current published NPM mark",
        "- threshold direction and period",
        "- IPO/direct listing fallback",
        "- corporate action treatment",
        "- revision rule",
        "- whether external secondary marks are relevant or only narrative context",
        "",
        "## Next Step",
        "",
        "Pick 3-5 candidates from this report, then run focused B research using the `recommended_research_queries` in the JSON output.",
    ])
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return json_path, report_path


def select_private_queue(candidates: list[dict], n: int = P_QUEUE_N) -> list[dict]:
    selected: list[dict] = []
    per_company: dict[str, int] = {}

    def queue_score(c: dict) -> float:
        yes = float(c.get("yes_price") or 0.0)
        end = str(c.get("end_date") or "")
        near_term = 1.0 if end.startswith(("2026-06", "2026-07", "2026-08")) else 0.0
        mid_price = max(0.0, 1.0 - abs(yes - 0.5) / 0.5)
        # Keep some convexity, but avoid pure dust and already-decided ladders.
        actionable = 1.0 if 0.05 <= yes <= 0.85 else (0.45 if 0.02 < yes < 0.95 else 0.0)
        volume = min(1.0, float(c.get("volume") or 0.0) / 10000.0)
        return round(
            0.34 * near_term
            + 0.26 * mid_price
            + 0.18 * actionable
            + 0.12 * float(c.get("mechanics_score") or 0.0)
            + 0.10 * volume,
            4,
        )

    ranked = sorted(candidates, key=queue_score, reverse=True)
    for c in ranked:
        company = c.get("company") or "unknown"
        if per_company.get(company, 0) >= P_QUEUE_MAX_PER_COMPANY:
            continue
        yes = c.get("yes_price")
        if float(c.get("volume") or 0.0) < 3000.0:
            continue
        # Avoid effectively resolved crumbs unless the operator manually chooses
        # them from private_market_candidates.json.
        if yes is None or yes <= 0.01 or yes >= 0.99:
            continue
        selected.append(c)
        per_company[company] = per_company.get(company, 0) + 1
        if len(selected) >= n:
            break
    return selected


def _write_forager_queue(candidates: list[dict]) -> str:
    path = os.path.join(os.path.dirname(__file__), "private_market_forager_queue.py")
    lines = [
        '"""Auto-generated Command P private-market queue.',
        "",
        "Review before copying to forager_queue_auto.py or importing into Command B.",
        '"""',
        "forager_queue = [",
    ]
    for i, c in enumerate(candidates):
        priority = "P0" if i < 3 else "P1"
        mechanics = c["mechanics"]
        company = c.get("company") or "private company"
        threshold = mechanics.get("threshold") or "threshold"
        metric = mechanics.get("metric") or "provider metric"
        side = "YES"
        yes = float(c.get("yes_price") or 0.5)
        # Simple initial side suggestion for B only:
        # low-price HIGH thresholds and high-price LOW thresholds are often where
        # oracle mechanics matter. B/D must recompute probability and side.
        ql = (c.get("question") or "").lower()
        if "(low)" in ql and yes > 0.65:
            side = "NO"
        elif "(high)" in ql and yes > 0.90:
            side = "NO"
        thesis = (
            f"PRIVATE_MARKET_VALUATION: {company} resolves to {metric} via "
            f"{mechanics.get('provider')}. Threshold={threshold}, "
            f"lag={mechanics.get('reporting_lag')}. Research the NPM mark mechanics, "
            "not generic fundamental valuation."
        )
        kill_criteria = [
            f"Latest NPM Price for {company} already makes {threshold} unreachable/reached under rules",
            f"Resolution source or Polymarket rules differ from parsed {metric} mechanics",
            f"IPO/direct listing/corporate action clause changes the relevant valuation metric",
        ]
        seed_query = c["recommended_research_queries"][0]
        source_url = mechanics.get("source_url")
        item = {
            "priority": priority,
            "condition_id": c["condition_id"],
            "question": c["question"],
            "yes_price": c["yes_price"],
            "no_price": c["no_price"],
            "end_date": c["end_date"],
            "spread": c["spread"],
            "archetype": "private_market_valuation",
            "vertical": "tech_business",
            "thesis": thesis,
            "why_signal_may_miss": (
                "Market may be pricing fundamental valuation while resolution follows NPM "
                "publication cadence, lag, revisions, IPO, and corporate-action clauses."
            ),
            "disconfirming_angle": (
                "Find latest NPM mark or secondary/tender evidence that invalidates the "
                "apparent price dislocation."
            ),
            "kill_criteria": kill_criteria,
            "seed_query": seed_query,
            "first_queries": c["recommended_research_queries"],
            "local_language": "English",
            "region_urls": [(source_url, 0.95, "official_npm_resolution_source")] if source_url else [],
            "official_urls": [source_url] if source_url else [],
            "telegram_channels": [],
            "tokens": [],
            "suggested_side": side,
            "private_market_mechanics": mechanics,
            "ranking_method": "command_p_private_market_intelligence",
        }
        lines.append(f"    {repr(item)},")
    lines.append("]")
    lines.append("")
    lines.append(f"print('Private-market queue loaded: {len(candidates)} candidates')")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


async def main_async() -> list[dict]:
    print("=" * 70)
    print("COMMAND P: Private Market Intelligence")
    print("=" * 70)
    wf_id = _start_workflow_log(
        "command_p_private_market_intelligence",
        "Private-company NPM market scan",
        input_payload={"max_pages": MAX_PAGES, "min_volume_usd": MIN_VOLUME_USD},
        agent_name="codex",
        notes="Research-only scan. Does not create signals or positions.",
    )
    markets, stats = await _fetch_private_markets()
    candidates = [build_candidate(m) for m in markets]
    candidates.sort(key=lambda c: c["research_priority_score"], reverse=True)
    _persist_candidates(candidates)
    queue = select_private_queue(candidates)
    json_path, report_path = _write_outputs(candidates, stats, wf_id, queue)
    queue_path = _write_forager_queue(queue)
    _record_workflow_step(
        wf_id,
        "private_market_scan",
        status="completed",
        allowed_writes=["markets", "snapshots", "market_tags"],
        writes_count=len(candidates) * 3,
        output_json={
            "stats": stats,
            "total_candidates": len(candidates),
            "json_path": json_path,
            "report_path": report_path,
            "queue_path": queue_path,
            "queue_candidates": len(queue),
        },
    )
    _finish_workflow_log(
        wf_id,
        status="completed",
        output_json={
            "total_candidates": len(candidates),
            "json_path": json_path,
            "report_path": report_path,
            "queue_path": queue_path,
            "queue_candidates": len(queue),
        },
    )
    print(f"Scanned raw markets: {stats['raw']}")
    print(f"Private/NPM candidates: {len(candidates)}")
    for i, c in enumerate(candidates[:15], 1):
        print(
            f"{i:2d}. {c.get('company') or '?'} | YES={c.get('yes_price'):.3f} "
            f"| priority={c['research_priority_score']:.2f} | {c.get('question')}"
        )
        print(f"    mechanics={c['mechanics_score']:.2f} lag={c['oracle_lag_score']:.2f} "
              f"flags={c['mechanics']['ambiguity_flags'][:3]}")
    print("\nDiversified queue:")
    for i, c in enumerate(queue, 1):
        print(
            f"  {i}. {c.get('company') or '?'} | YES={c.get('yes_price'):.3f} | "
            f"{c.get('question')}"
        )
    print(f"\nJSON: {json_path}")
    print(f"Report: {report_path}")
    print(f"B queue: {queue_path} ({len(queue)} candidates)")
    return candidates


def main() -> list[dict]:
    return asyncio.run(main_async())


if __name__ == "__main__":
    main()
