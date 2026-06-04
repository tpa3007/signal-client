"""Command M: manual shortlist gate between G2 and Command R/B.

G2 is intentionally broad and formula-heavy. Command M turns its top-25 into a
human/strong-LLM workbench: it labels each candidate as `b_candidate`, `watch`,
or `reject`, writes a short report, and emits a small queue that should be fed
to Command R before Command B spends search API.

Typical flow:
    python run_command_g.py
    python run_command_g2.py
    python run_command_m.py
    $env:FORAGER_QUEUE_PATH="manual_shortlist_queue.py"; python run_command_r.py
    $env:FORAGER_QUEUE_PATH="forager_queue_reasoned.py"; python run_command_b.py
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

INPUT_JSON = ROOT / os.getenv("SIGNAL_COMMAND_M_INPUT", "g2_top25.json")
OUT_QUEUE = ROOT / os.getenv("SIGNAL_COMMAND_M_OUT_QUEUE", "manual_shortlist_queue.py")
OUT_MD = ROOT / os.getenv("SIGNAL_COMMAND_M_OUT_MD", "manual_shortlist_report.md")
QUEUE_N = int(os.getenv("SIGNAL_COMMAND_M_QUEUE_N", "7"))
WATCH_FALLBACK_N = int(os.getenv("SIGNAL_COMMAND_M_WATCH_FALLBACK_N", "5"))


def _safe_write_text(path: Path, text: str) -> Path:
    """Write text, falling back to a timestamped path if the target is locked."""
    try:
        path.write_text(text, encoding="utf-8")
        return path
    except PermissionError:
        fallback = path.with_name(
            f"{path.stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{path.suffix}"
        )
        fallback.write_text(text, encoding="utf-8")
        print(f"[warn] Could not write {path.name}; wrote {fallback.name} instead")
        return fallback


def _lower(candidate: dict[str, Any]) -> str:
    return str(candidate.get("question") or "").lower()


def _is_macro_bracket(candidate: dict[str, Any]) -> bool:
    ql = _lower(candidate)
    macro_terms = (
        "gdp", "cpi", "inflation", "unemployment", "interest rate", "rate decision",
        "growth in q",
    )
    return any(term in ql for term in macro_terms) and any(
        scope in ql for scope in ("between", "%", "q1", "q2", "q3", "q4")
    )


def _is_private_provider_market(candidate: dict[str, Any]) -> bool:
    ql = _lower(candidate)
    return "valuation hit" in ql and any(
        company in ql
        for company in ("openai", "anthropic", "spacex", "anduril", "stripe", "canva", "databricks", "kraken")
    )


def _is_central_bank_sequence_market(candidate: dict[str, Any]) -> bool:
    ql = _lower(candidate)
    bank_terms = (
        "bank of england", "bank of brazil", "reserve bank", "rba", "fomc",
        "fed ", "ecb", "bank of japan", "bank of russia", "selic", "cash rate",
    )
    action_terms = ("increase", "decrease", "no change", "hike", "cut", "interest rates", "cash rate", "key rate")
    return any(term in ql for term in bank_terms) and any(term in ql for term in action_terms)


def _is_resolution_clause_market(candidate: dict[str, Any]) -> bool:
    ql = _lower(candidate)
    return any(term in ql for term in ("before gta vi", "before gta 6", "released before", "50/50", "tie resolves"))


def _has_outcome_family_context(candidate: dict[str, Any]) -> bool:
    family = candidate.get("outcome_family")
    if not isinstance(family, dict):
        return False
    try:
        return int(family.get("peer_count") or 0) >= 3
    except (TypeError, ValueError):
        return False


def _is_geopolitical_tail_candidate(candidate: dict[str, Any]) -> bool:
    ql = _lower(candidate)
    geo_terms = (
        "iran", "israel", "lebanon", "hezbollah", "hamas", "hormuz", "kharg",
        "china", "taiwan", "philippines", "russia", "ukraine", "putin",
        "netanyahu", "trump", "nato", "beirut", "irgc", "coup", "war powers",
    )
    event_terms = (
        "meeting", "agreement", "visit", "ground operation", "invade", "capture",
        "ceasefire", "evacuates", "coup", "out as minister", "leaves iran",
        "terrorist organization", "war powers",
    )
    return any(term in ql for term in geo_terms) and any(term in ql for term in event_terms)


def _is_local_election(candidate: dict[str, Any]) -> bool:
    ql = _lower(candidate)
    return any(term in ql for term in ("election", "mayor", "governor", "gubernatorial", "seat")) and (
        str(candidate.get("local_language") or "").lower() not in ("", "english")
        or any(place in ql for place in ("korea", "jeonbuk", "daejeon", "ulsan", "peru", "iran"))
    )


def _has_divergence(candidate: dict[str, Any]) -> bool:
    for field in (
        "metaculus_divergence",
        "predictit_divergence",
        "manifold_divergence",
        "kalshi_divergence",
        "gjo_divergence",
    ):
        value = candidate.get(field)
        if isinstance(value, dict):
            try:
                if float(value.get("match_score", 1.0)) < 0.55:
                    continue
            except (TypeError, ValueError):
                pass
            return True
        if value:
            return True
    breakdown = candidate.get("gem_breakdown") or {}
    return any("divergence" in str(key).lower() or "metaculus" in str(key).lower() for key in breakdown)


def _is_extreme_price_without_specific_edge(candidate: dict[str, Any]) -> bool:
    yes = float(candidate.get("yes_price") or 0.5)
    if not (yes <= 0.03 or yes >= 0.97):
        return False
    if _has_divergence(candidate):
        return False
    breakdown = candidate.get("gem_breakdown") or {}
    return not any("bubble" in str(key).lower() for key in breakdown)


def _external_probability(candidate: dict[str, Any]) -> float | None:
    probs: list[float] = []
    checks = [
        ("metaculus_divergence", "metaculus_prob"),
        ("predictit_divergence", "pi_price"),
        ("manifold_divergence", "mf_prob"),
        ("kalshi_divergence", "kalshi_price"),
        ("gjo_divergence", "gjo_prob"),
    ]
    for field, prob_key in checks:
        value = candidate.get(field)
        if isinstance(value, dict) and value.get(prob_key) is not None:
            try:
                probs.append(float(value[prob_key]))
            except (TypeError, ValueError):
                pass
    divergences = candidate.get("divergences") or {}
    for value in divergences.values():
        if not isinstance(value, dict):
            continue
        for prob_key in ("metaculus_prob", "pi_price", "mf_prob", "kalshi_price", "gjo_prob"):
            if value.get(prob_key) is None:
                continue
            try:
                probs.append(float(value[prob_key]))
                break
            except (TypeError, ValueError):
                pass
    if not probs:
        return None
    return sum(probs) / len(probs)


def _divergence_side(candidate: dict[str, Any]) -> str | None:
    external = _external_probability(candidate)
    if external is None:
        return None
    yes = float(candidate.get("yes_price") or 0.5)
    if external - yes >= 0.05:
        return "YES"
    if yes - external >= 0.05:
        return "NO"
    return None


def _query_contamination(candidate: dict[str, Any]) -> bool:
    ql = _lower(candidate)
    queries = " ".join(str(q) for q in (candidate.get("first_queries") or [])).lower()
    if _is_macro_bracket(candidate) and any(term in queries for term in ("election polls", "party ppp", "opposition")):
        return True
    if "valuation" in ql and any(term in queries for term in ("election", "polls", "battlefield")):
        return True
    return False


def _is_sports_spread_or_match(candidate: dict[str, Any]) -> bool:
    ql = _lower(candidate)
    slug = " ".join(
        str(candidate.get(k) or "").lower()
        for k in ("slug", "event_slug", "url")
    )
    return ql.startswith("spread:") or bool(
        re.search(r"\b(fifwc|fifa|f1|mls|nba|nfl|nhl|mlb)\b", slug)
    )


def _cluster_key(candidate: dict[str, Any]) -> str:
    ql = _lower(candidate)
    for place in (
        "busan", "incheon", "gyeonggi", "gyeongnam", "gyeongbuk", "jeonbuk",
        "jeonnam", "daejeon", "daegu", "ulsan", "seoul", "sejong", "jeju",
        "chungbuk", "chungnam", "gangwon", "korea",
    ):
        if place in ql and any(x in ql for x in ("mayor", "governor", "gubernatorial", "seat")):
            return f"korea:{place}"
    for company in ("openai", "anthropic", "spacex", "anduril", "stripe", "canva"):
        if company in ql and "valuation" in ql:
            return f"private:{company}"
    tokens = [t for t in re.findall(r"[a-z0-9]+", ql) if len(t) > 3]
    return " ".join(tokens[:4]) or ql[:40]


def review_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return operator-shortlist metadata for a G2 candidate.

    This is deliberately conservative. It does not claim truth; it decides
    whether the candidate deserves scarce Command B API and operator time.
    """
    score = 0
    green: list[str] = []
    red: list[str] = []
    ql = _lower(candidate)

    yes = float(candidate.get("yes_price") or 0.5)
    spread = float(candidate.get("spread") or 0.0)
    days = float(candidate.get("days_to_end") or 999)
    local_language = str(candidate.get("local_language") or "English")

    if _is_sports_spread_or_match(candidate):
        return {
            "status": "reject",
            "score": -99,
            "recommended_side": None,
            "green_flags": [],
            "red_flags": ["sports spread/match market; not a Signal research target"],
            "operator_note": "Hard reject: country/team names can look like language arbitrage, but this is not a policy/election/macro edge.",
        }

    if candidate.get("archetype") == "private_market_valuation" or _is_private_provider_market(candidate):
        score += 4
        green.append("private-market/NPM mechanics can create real resolution edge")

    if _is_central_bank_sequence_market(candidate):
        score += 4
        green.append("central-bank sequence/policy-mechanics research path exists")

    if _is_resolution_clause_market(candidate):
        score += 4
        green.append("resolution-clause mechanics research path exists")

    if _has_outcome_family_context(candidate):
        score += 4
        green.append("outcome-family/bracket context exists; compare sibling prices before B")

    if _is_local_election(candidate):
        score += 3
        green.append(f"local-election/local-language research path exists ({local_language})")

    if _has_divergence(candidate):
        score += 2
        green.append("cross-platform divergence is present, but scope must be rechecked")
        div_side = _divergence_side(candidate)
        if div_side:
            green.append(f"divergence-implied side is {div_side}")
        if 0.15 <= yes <= 0.75:
            score += 2
            green.append("divergence is in a researchable price band")

    if 0.15 <= yes <= 0.75:
        score += 1
        green.append("price is in a researchable range")
    elif yes < 0.08:
        red.append("very cheap moonshot; needs a concrete catalyst before B")
        if not _has_divergence(candidate) and not (
            _is_private_provider_market(candidate)
            or _is_central_bank_sequence_market(candidate)
            or _is_resolution_clause_market(candidate)
        ):
            score -= 1
    elif yes > 0.85:
        red.append("very high confidence market; needs strong contradiction before B")
        if not _has_divergence(candidate):
            score -= 1

    if _is_extreme_price_without_specific_edge(candidate):
        red.append("extreme price without concrete contradiction; do not spend B yet")
        score -= 2

    if days <= 30:
        score += 1
        green.append("near-term catalyst/deadline")
    if days < 4:
        if _is_local_election(candidate) and 0.15 <= yes <= 0.75:
            green.append("near-term local election with immediate local-source path")
        else:
            red.append("too close to expiry for slow research unless source is already known")

    if _is_geopolitical_tail_candidate(candidate) and yes < 0.15 and days <= 45 and not _has_divergence(candidate):
        red.append("cheap near-term geopolitical tail; May-31 learning says reject without hard catalyst")
        score -= 3

    if spread >= 0.08:
        red.append(f"wide spread ({spread:.0%}) may erase edge")

    if _is_macro_bracket(candidate):
        red.append("macro bracket is not a language-arbitrage market by itself")
        if not _has_divergence(candidate):
            score -= 3

    if _query_contamination(candidate):
        red.append("seed queries appear contaminated by another archetype")
        score -= 2

    concrete_green = [
        flag for flag in green
        if "price is in a researchable range" not in flag
        and "near-term catalyst/deadline" not in flag
    ]
    if not concrete_green:
        red.append("no concrete edge path beyond formula score")
        score -= 1

    whale_dominant = str(candidate.get("whale_dominant") or "").upper()
    suggested_side = str(candidate.get("suggested_side") or "YES").upper()
    if candidate.get("whale_alert") and whale_dominant and whale_dominant != suggested_side:
        red.append(f"large resting orders lean {whale_dominant}; treat as context, not proof")

    div_side = _divergence_side(candidate)
    if div_side and suggested_side in {"YES", "NO"} and div_side != suggested_side:
        red.append(f"formula suggested {suggested_side}, but divergence implies {div_side}; M overrides research side")

    hard_block = False
    if yes < 0.08 and not _has_divergence(candidate):
        hard_block = True
    if days < 4 and yes < 0.15:
        hard_block = True
    if _is_geopolitical_tail_candidate(candidate) and yes < 0.15 and days <= 45 and not _has_divergence(candidate):
        hard_block = True

    if _is_extreme_price_without_specific_edge(candidate) or hard_block:
        status = "reject"
    elif score >= 5 and len(red) <= 1:
        status = "b_candidate"
    elif score >= 3 and len(red) <= 3:
        status = "watch"
    else:
        status = "reject"

    return {
        "status": status,
        "operator_score": score,
        "green_flags": green,
        "red_flags": red,
        "manual_suggested_side": div_side or suggested_side,
        "cluster_key": _cluster_key(candidate),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_candidates(path: Path = INPUT_JSON) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Command M input not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(c) for c in payload.get("candidates", []) if isinstance(c, dict)]


def build_shortlist(candidates: list[dict[str, Any]], limit: int = QUEUE_N) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reviewed: list[dict[str, Any]] = []
    for c in candidates:
        item = dict(c)
        item["manual_shortlist"] = review_candidate(item)
        item["suggested_side"] = item["manual_shortlist"]["manual_suggested_side"]
        item["requires_operator_review"] = True
        item["ranking_method"] = f"{item.get('ranking_method', 'unknown')}+command_m_manual_shortlist"
        reviewed.append(item)

    reviewed.sort(
        key=lambda c: (
            c["manual_shortlist"]["status"] == "b_candidate",
            c["manual_shortlist"]["operator_score"],
            float(c.get("gem_score") or 0),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    cluster_counts: dict[str, int] = {}
    for c in reviewed:
        meta = c["manual_shortlist"]
        if meta["status"] != "b_candidate":
            continue
        key = meta["cluster_key"]
        if cluster_counts.get(key, 0) >= 1:
            continue
        selected.append(c)
        cluster_counts[key] = cluster_counts.get(key, 0) + 1
        if len(selected) >= limit:
            break

    target = min(limit, WATCH_FALLBACK_N)
    if len(selected) < target:
        watch_candidates = [
            c for c in reviewed
            if c["manual_shortlist"]["status"] == "watch"
            and c["manual_shortlist"]["operator_score"] >= 3
            and not _is_extreme_price_without_specific_edge(c)
        ]
        watch_candidates.sort(key=_watch_fallback_rank, reverse=True)
        for c in watch_candidates:
            meta = c["manual_shortlist"]
            key = meta["cluster_key"]
            if cluster_counts.get(key, 0) >= 1:
                continue
            item = dict(c)
            item["manual_shortlist"] = dict(meta)
            item["manual_shortlist"]["queue_reason"] = "watch_fallback_operator_review_required"
            item["requires_operator_review"] = True
            selected.append(item)
            cluster_counts[key] = cluster_counts.get(key, 0) + 1
            if len(selected) >= target:
                break

    return selected, reviewed


def _watch_fallback_rank(candidate: dict[str, Any]) -> tuple:
    meta = candidate["manual_shortlist"]
    yes = float(candidate.get("yes_price") or 0.5)
    researchable_price = 0.15 <= yes <= 0.75
    extreme_price = yes < 0.05 or yes > 0.95
    red_count = len(meta.get("red_flags") or [])
    return (
        researchable_price,
        _has_divergence(candidate),
        not extreme_price,
        -red_count,
        meta.get("operator_score", 0),
        float(candidate.get("gem_score") or 0),
    )


def _write_queue(candidates: list[dict[str, Any]]) -> None:
    lines = [
        '"""Auto-generated by Command M manual shortlist gate.',
        "",
        "Feed this to Command R, then Command B. Do not treat this as D approval.",
        '"""',
        "forager_queue = [",
    ]
    for i, c in enumerate(candidates):
        item = dict(c)
        item["priority"] = "P0" if i < 3 else "P1"
        lines.append(f"    {repr(item)},")
    lines.append("]")
    lines.append("")
    lines.append(f"print('Manual shortlist queue loaded: {len(candidates)} candidates')")
    _safe_write_text(OUT_QUEUE, "\n".join(lines) + "\n")


def _write_report(selected: list[dict[str, Any]], reviewed: list[dict[str, Any]]) -> None:
    status_counts: dict[str, int] = {}
    for c in reviewed:
        status = c["manual_shortlist"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    md = [
        "# Command M Manual Shortlist Report",
        "",
        f"Generated: `{datetime.now(timezone.utc).isoformat()}`",
        f"Input: `{INPUT_JSON}`",
        f"Output queue: `{OUT_QUEUE}`",
        "",
        "Command M is a conservative pre-B gate. It spends Command B only on candidates with a concrete edge path.",
        "",
        "## Summary",
        "",
        f"- Selected for Command R/B: `{len(selected)}`",
        f"- Status counts: `{status_counts}`",
        "",
        "## Selected",
    ]
    if not selected:
        md.append("")
        md.append("No candidates passed the manual shortlist gate.")
    for i, c in enumerate(selected, 1):
        meta = c["manual_shortlist"]
        md.extend([
            "",
            f"### {i}. {c.get('question')}",
            "",
            f"- Status: `{meta['status']}`",
            f"- Operator score: `{meta['operator_score']}`",
            f"- YES price: `{c.get('yes_price')}`",
            f"- Suggested side: `{c.get('suggested_side', 'YES')}`",
            f"- Queue reason: `{meta.get('queue_reason', 'direct_b_candidate')}`",
            f"- Polymarket: {c.get('polymarket_url', '')}",
            "- Green flags: " + ("; ".join(meta["green_flags"]) or "none"),
            "- Red flags: " + ("; ".join(meta["red_flags"]) or "none"),
        ])

    md.extend(["", "## Full Review"])
    for i, c in enumerate(reviewed, 1):
        meta = c["manual_shortlist"]
        md.extend([
            "",
            f"### {i}. [{meta['status']}] {c.get('question')}",
            "",
            f"- Score: `{meta['operator_score']}` | G2: `{c.get('gem_score')}` | YES: `{c.get('yes_price')}`",
            "- Green: " + ("; ".join(meta["green_flags"]) or "none"),
            "- Red: " + ("; ".join(meta["red_flags"]) or "none"),
        ])
    _safe_write_text(OUT_MD, "\n".join(md).rstrip() + "\n")


def main() -> list[dict[str, Any]]:
    candidates = _load_candidates()
    selected, reviewed = build_shortlist(candidates)
    _write_queue(selected)
    _write_report(selected, reviewed)
    print("=== COMMAND M: Manual Shortlist Gate ===")
    print(f"Input candidates: {len(candidates)}")
    print(f"Selected for Command R/B: {len(selected)}")
    for i, c in enumerate(selected, 1):
        meta = c["manual_shortlist"]
        print(f"  {i}. [{meta['operator_score']}] {c.get('question')[:80]}")
        if meta["red_flags"]:
            print(f"     red: {'; '.join(meta['red_flags'][:2])}")
    print(f"Queue:  {OUT_QUEUE}")
    print(f"Report: {OUT_MD}")
    print("\nNext:")
    print(f"  $env:FORAGER_QUEUE_PATH='{OUT_QUEUE.name}'; python run_command_r.py")
    return selected


if __name__ == "__main__":
    main()
