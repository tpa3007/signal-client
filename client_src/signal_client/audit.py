"""Client-mode portfolio audit logic.

This is deliberately conservative. It produces a research/risk review of a
client's own Polymarket positions and never creates trades or private Signal
ledger records.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _side(position: dict[str, Any]) -> str:
    outcome = str(position.get("outcome") or position.get("outcomeName") or "").lower()
    if "yes" in outcome:
        return "YES"
    if "no" in outcome:
        return "NO"
    side = str(position.get("side") or "").upper()
    return side if side in {"YES", "NO"} else "UNKNOWN"


def _category(title: str) -> str:
    text = title.lower()
    rules = [
        ("macro", ("inflation", "cpi", "fed", "ecb", "rates", "gdp", "jobs", "unemployment")),
        ("elections", ("election", "mayor", "governor", "president", "senate", "parliament")),
        ("geopolitics", ("war", "sanction", "nato", "iran", "cuba", "ukraine", "israel", "china")),
        ("private_markets", ("valuation", "ipo", "stripe", "openai", "databricks", "canva")),
        ("crypto", ("bitcoin", "btc", "ethereum", "crypto", "solana")),
        ("sports", ("nba", "nfl", "mlb", "soccer", "champions", "world cup")),
    ]
    for name, keys in rules:
        if any(k in text for k in keys):
            return name
    return "other"


def normalize_position(position: dict[str, Any]) -> dict[str, Any]:
    title = position.get("title") or position.get("question") or position.get("market") or "Untitled market"
    size = _float(position.get("size") or position.get("shares"))
    avg_price = _float(position.get("avgPrice") or position.get("averagePrice") or position.get("price"))
    cur_price = _float(position.get("curPrice") or position.get("currentPrice") or position.get("price"), avg_price)
    value = _float(position.get("currentValue") or position.get("value"), size * cur_price)
    cost = _float(position.get("initialValue") or position.get("costBasis"), size * avg_price)
    pnl = _float(position.get("cashPnl") or position.get("pnl"), value - cost)
    end_date = position.get("endDate") or position.get("end_date")
    return {
        "condition_id": position.get("conditionId") or position.get("condition_id") or "",
        "title": str(title),
        "side": _side(position),
        "category": _category(str(title)),
        "size": round(size, 4),
        "avg_price": round(avg_price, 4),
        "current_price": round(cur_price, 4),
        "current_value_usd": round(value, 2),
        "cost_basis_usd": round(cost, 2),
        "pnl_usd": round(pnl, 2),
        "end_date": end_date,
    }


def audit_positions(
    positions: list[dict[str, Any]],
    *,
    rules: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    thresholds = rules.get("thresholds") or {}
    max_single_position_pct = _float(thresholds.get("max_single_position_pct"), 0.20)
    near_deadline_days = _float(thresholds.get("near_deadline_days"), 7.0)
    review_loss_pct = _float(thresholds.get("review_loss_pct"), -0.25)

    normalized = [normalize_position(p) for p in positions]
    total_value = sum(p["current_value_usd"] for p in normalized)
    by_category = defaultdict(float)
    for p in normalized:
        by_category[p["category"]] += p["current_value_usd"]

    audited = []
    for p in normalized:
        flags: list[str] = []
        position_pct = p["current_value_usd"] / total_value if total_value > 0 else 0.0
        if position_pct > max_single_position_pct:
            flags.append("concentration_review")
        if p["side"] == "UNKNOWN":
            flags.append("unknown_side")
        if p["avg_price"] > 0:
            roi = p["pnl_usd"] / max(p["cost_basis_usd"], 1.0)
            if roi <= review_loss_pct:
                flags.append("drawdown_review")
        else:
            roi = None
        end_dt = _parse_dt(p["end_date"])
        days_to_end = None
        if end_dt:
            days_to_end = (end_dt - now).total_seconds() / 86400.0
            if days_to_end <= near_deadline_days:
                flags.append("near_deadline")
            if days_to_end < 0:
                flags.append("past_deadline")
        if p["current_price"] <= 0.08 and p["side"] != "UNKNOWN":
            flags.append("lottery_tail")
        if p["current_price"] >= 0.90 and p["side"] != "UNKNOWN":
            flags.append("crowded_high_price")

        decision = "monitor"
        if {"past_deadline", "unknown_side"} & set(flags):
            decision = "must_review"
        elif {"concentration_review", "drawdown_review", "near_deadline"} & set(flags):
            decision = "review"

        audited.append({
            **p,
            "portfolio_pct": round(position_pct * 100, 2),
            "roi_pct": round(roi * 100, 2) if roi is not None else None,
            "days_to_end": round(days_to_end, 2) if days_to_end is not None else None,
            "flags": flags,
            "decision": decision,
        })

    decisions = Counter(p["decision"] for p in audited)
    return {
        "schema": "signal-client-audit-v1",
        "generated_at": now.isoformat(),
        "positions_count": len(audited),
        "total_value_usd": round(total_value, 2),
        "category_value_usd": {k: round(v, 2) for k, v in sorted(by_category.items())},
        "decision_counts": dict(decisions),
        "positions": sorted(audited, key=lambda p: (p["decision"] != "must_review", -p["portfolio_pct"])),
        "rules_version": rules.get("version"),
        "boundary": "Research/education only. No financial advice. No trades are created.",
    }


def build_run_report(audit: dict[str, Any], *, include_wallet: str | None = None) -> dict[str, Any]:
    return {
        "schema": "signal-client-run-report-v1",
        "generated_at": audit["generated_at"],
        "positions_count": audit["positions_count"],
        "total_value_bucket": _value_bucket(audit["total_value_usd"]),
        "decision_counts": audit["decision_counts"],
        "category_counts": dict(Counter(p["category"] for p in audit["positions"])),
        "flag_counts": dict(Counter(flag for p in audit["positions"] for flag in p["flags"])),
        "rules_version": audit.get("rules_version"),
        "wallet": include_wallet,
    }


def _value_bucket(value: float) -> str:
    if value < 100:
        return "lt_100"
    if value < 1_000:
        return "100_999"
    if value < 10_000:
        return "1k_10k"
    return "gt_10k"


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Signal Client Portfolio Audit",
        "",
        f"Generated: {audit['generated_at']}",
        "",
        audit["boundary"],
        "",
        "## Summary",
        "",
        f"- Positions: {audit['positions_count']}",
        f"- Current value: ${audit['total_value_usd']:,.2f}",
        f"- Decisions: {audit['decision_counts']}",
        "",
        "## Positions",
        "",
        "| Decision | Side | Value | PnL | Portfolio | Flags | Market |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for p in audit["positions"]:
        flags = ", ".join(p["flags"]) if p["flags"] else "-"
        title = p["title"].replace("|", " ")
        lines.append(
            f"| {p['decision']} | {p['side']} | ${p['current_value_usd']:,.2f} | "
            f"${p['pnl_usd']:,.2f} | {p['portfolio_pct']:.2f}% | {flags} | {title[:90]} |"
        )
    lines.extend([
        "",
        "## Notes",
        "",
        "- This client artifact has no access to the author's private Signal database.",
        "- If sharing is enabled, the structured run report is anonymized unless wallet consent is explicit.",
    ])
    return "\n".join(lines) + "\n"
