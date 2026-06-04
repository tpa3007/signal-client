"""Command E — Resolution Tracker & Outcome Learning.

Checks every open signal against the Polymarket Gamma API, marks resolved
markets, computes realized PnL, and writes structured outcome_learning_reviews
so that every resolved bet generates a calibration signal.

Pipeline position:
    Command C (signal commit) → open positions
    **Command E** → resolution check → PnL compute → outcome learning log

Run daily or after a market's end_date passes.  Safe to re-run (idempotent).

Output: resolution_report.json + printed summary.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone

import httpx

sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")

import db; db.init()
from tools.workflows import _start_workflow_log, _record_workflow_step, _finish_workflow_log
from lib.pnl import realized_pnl as _realized_pnl
from lib.ollama import learning_review_draft

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Brier score: lower is better.  Perfect = 0, worst = 1.
# brier_score = (p - outcome)^2   where outcome ∈ {0,1}
# market_brier: using the market's price at signal time as the baseline forecast

# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _brier_score(probability: float, outcome: float) -> float:
    """Squared probability error. Lower is better."""
    return round((probability - outcome) ** 2, 4)


def _outcome_side(resolved_yes: float) -> str:
    """Convert resolved_yes (0.0 or 1.0) to YES/NO string."""
    return "YES" if resolved_yes >= 0.5 else "NO"


def _why_right_or_wrong(
    signal_side: str,
    signal_prob: float,
    signal_entry: float,
    resolved_yes: float,
    realized_pnl: float,
    question: str,
    brier: float,
    market_brier: float,
) -> str:
    """Generate a structured outcome narrative for the learning review."""
    outcome = _outcome_side(resolved_yes)
    won = (signal_side == outcome)
    better_than_market = brier < market_brier

    parts = []
    if won:
        parts.append(f"WON: {signal_side} position resolved correctly (outcome={outcome}).")
        if signal_prob > signal_entry + 0.05:
            parts.append(f"Probability estimate {signal_prob:.1%} was ABOVE market price {signal_entry:.1%} — edge realised.")
        elif signal_prob < signal_entry - 0.05:
            parts.append(f"WARNING: probability {signal_prob:.1%} was below entry {signal_entry:.1%} — won despite negative edge estimate.")
    else:
        parts.append(f"LOST: {signal_side} position resolved against thesis (outcome={outcome}).")
        if signal_prob > 0.6:
            parts.append(f"High-confidence prediction {signal_prob:.1%} was wrong — examine evidence quality.")
        else:
            parts.append(f"Low-confidence prediction {signal_prob:.1%} was wrong — acceptable base-rate miss.")

    if better_than_market:
        parts.append(f"Brier {brier:.3f} < market {market_brier:.3f} — outperformed crowd probability.")
    else:
        parts.append(f"Brier {brier:.3f} ≥ market {market_brier:.3f} — crowd was better calibrated.")

    pnl_str = f"+${realized_pnl:.2f}" if realized_pnl >= 0 else f"-${abs(realized_pnl):.2f}"
    parts.append(f"Realized PnL: {pnl_str}.")
    return "  ".join(parts)


def _classify_errors(
    signal_side: str,
    signal_prob: float,
    signal_entry: float,
    resolved_yes: float,
    brier: float,
    market_brier: float,
) -> dict[str, int]:
    """Flag error categories for calibration learning."""
    outcome = _outcome_side(resolved_yes)
    won = (signal_side == outcome)

    return {
        "resolution_error": 0,  # Would be 1 if resolution was disputed/incorrect
        "probability_error": 1 if (not won and signal_prob > 0.65) else 0,
        "evidence_error": 1 if (not won and brier > market_brier + 0.05) else 0,
        "timing_error": 0,  # Would be 1 if thesis was correct but timing was off
        "sizing_error": 0,  # Would be 1 if position was over/under-sized given confidence
    }


ERROR_TAXONOMY = (
    "wrong_resolution_read",
    "stale_source",
    "overtrusted_local_poll",
    "narrative_overfit",
    "catalyst_overweight",
    "liquidity_trap",
    "correlated_exposure",
    "false_cross_platform_divergence",
    "provider_metric_misread",
    "deadline_misread",
    "model_overconfidence",
    "operator_override_bad",
    "search_backend_degraded_but_approved",
)


def _classify_error_taxonomy(
    *,
    question: str,
    signal_side: str,
    signal_prob: float,
    signal_entry: float,
    resolved_yes: float,
    brier: float,
    market_brier: float,
    archetype: str | None,
) -> dict[str, int]:
    """Structured error tags for updating G2/M/R/D weights later."""
    outcome = _outcome_side(resolved_yes)
    won = signal_side == outcome
    ql = question.lower()
    arch = (archetype or "").lower()
    tags = {name: 0 for name in ERROR_TAXONOMY}

    if won:
        return tags
    if signal_prob >= 0.65:
        tags["model_overconfidence"] = 1
    if brier > market_brier + 0.05:
        tags["narrative_overfit"] = 1
    if any(k in ql for k in ("by ", "before ", "deadline", "may 31", "june 3")):
        tags["deadline_misread"] = 1
    if any(k in arch for k in ("catalyst", "deadline", "legislative")):
        tags["catalyst_overweight"] = 1
    if any(k in arch for k in ("local", "election")) and any(k in ql for k in ("poll", "election", "seats", "governor")):
        tags["overtrusted_local_poll"] = 1
    if any(k in ql for k in ("npm price", "valuation", "nasdaq private market")):
        tags["provider_metric_misread"] = 1
    if signal_entry <= 0.05 or signal_entry >= 0.95:
        tags["liquidity_trap"] = 1
    return tags


def _primary_error_type(tags: dict[str, int], legacy_errors: dict[str, int]) -> str | None:
    for name in ERROR_TAXONOMY:
        if tags.get(name):
            return name
    for name in ("resolution_error", "probability_error", "evidence_error", "timing_error", "sizing_error"):
        if legacy_errors.get(name):
            return name
    return None


def _repeatable_lesson(
    signal_side: str,
    signal_prob: float,
    resolved_yes: float,
    brier: float,
    market_brier: float,
    archetype: str | None,
) -> str:
    """Distil one actionable lesson from this outcome."""
    outcome = _outcome_side(resolved_yes)
    won = (signal_side == outcome)
    arch = archetype or "unknown"

    if won and brier < market_brier:
        return (
            f"[{arch}] Research edge confirmed: calibrated probability outperformed market. "
            f"Continue applying this approach to similar markets."
        )
    if won and brier >= market_brier:
        return (
            f"[{arch}] Win but no calibration edge: market was equally well-calibrated. "
            f"Investigate whether edge was genuine or luck."
        )
    if not won and brier < market_brier:
        return (
            f"[{arch}] Lost but better calibrated than market: base-rate miss in a hard-to-predict category. "
            f"No evidence of systematic error; continue process."
        )
    return (
        f"[{arch}] Lost AND underperformed market calibration. "
        f"Review: Was evidence quality sufficient? Was disconfirming evidence searched? "
        f"Was kill criteria monitoring in place?"
    )


# ── Polymarket API ─────────────────────────────────────────────────────────────

async def _fetch_market_status(client: httpx.AsyncClient, condition_id: str) -> dict | None:
    """Fetch market status from Gamma API.  Returns dict or None on failure."""
    async def _fetch_by_slug() -> dict | None:
        try:
            with db.connect() as _conn:
                row = _conn.execute(
                    "SELECT slug FROM markets WHERE condition_id = ?",
                    (condition_id,),
                ).fetchone()
            slug = (row["slug"] if row else None) if hasattr(row, "keys") else (row[0] if row else None)
            if not slug:
                return None
            rs = await client.get(f"{GAMMA_BASE}/markets/slug/{slug}", timeout=15)
            rs.raise_for_status()
            data = rs.json()
            return data if isinstance(data, dict) else None
        except Exception as exc:
            print(f"    [API] Slug fallback failed for {condition_id[:16]}: {exc}")
            return None

    try:
        r = await client.get(
            f"{GAMMA_BASE}/markets",
            params={"condition_ids": condition_id},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        if items:
            return items[0]
        return await _fetch_by_slug()
    except Exception as exc:
        print(f"    [API] Failed for {condition_id[:16]}: {exc}")
        return await _fetch_by_slug()


def _parse_resolved_yes(market_data: dict) -> float | None:
    """Extract resolved_yes (0.0 or 1.0) from market data."""
    if not market_data.get("closed"):
        return None
    prices = market_data.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            return None
    if prices and len(prices) >= 2:
        return float(prices[0])
    return None


# ── Resolution engine ──────────────────────────────────────────────────────────

async def _resolve_market(conn, condition_id: str, client: httpx.AsyncClient) -> dict:
    """Check one market, mark resolved if closed, compute PnL on all signals."""
    market_data = await _fetch_market_status(client, condition_id)
    if not market_data:
        return {"condition_id": condition_id, "status": "api_error"}

    if not market_data.get("closed"):
        return {"condition_id": condition_id, "status": "still_open"}

    resolved_yes = _parse_resolved_yes(market_data)
    if resolved_yes is None:
        return {"condition_id": condition_id, "status": "price_data_missing"}

    now = _utc_now()

    # Update market row
    conn.execute("""
        UPDATE markets SET resolved = 1, resolved_yes = ?, resolved_at = ?
        WHERE condition_id = ?
    """, (resolved_yes, now, condition_id))

    # Update all open signals for this market
    sigs = conn.execute("""
        SELECT s.id, s.side, s.yes_price_at_signal, s.bet_amount,
               s.claude_prob, s.confidence, s.real_money,
               s.realized_pnl AS existing_realized_pnl,
               a.id AS analysis_id, a.decision AS a_decision,
               p.id AS position_id, p.primary_archetype,
               p.status AS position_status, p.closed_at AS position_closed_at
        FROM signals s
        LEFT JOIN analyses a ON a.signal_id = s.id
        LEFT JOIN positions p ON p.signal_id = s.id
        WHERE s.condition_id = ? AND s.resolved = 0
        ORDER BY s.id
    """, (condition_id,)).fetchall()

    market_row = conn.execute(
        "SELECT question, end_date FROM markets WHERE condition_id = ?", (condition_id,)
    ).fetchone()
    question = market_row["question"] if market_row else condition_id[:40]

    signals_resolved = []
    for s in sigs:
        hypothetical_resolution_pnl = _realized_pnl(
            side=s["side"],
            entry_price=s["yes_price_at_signal"],
            bet_amount=s["bet_amount"],
            resolved_yes=resolved_yes,
        )
        hypothetical_resolution_pnl = round(hypothetical_resolution_pnl, 2)

        position_was_closed = s["position_status"] in {"closed", "cancelled"}
        existing_realized = s["existing_realized_pnl"]
        if position_was_closed and existing_realized is not None:
            pnl = round(float(existing_realized), 2)
        else:
            pnl = hypothetical_resolution_pnl

        # Mark signal resolved.  For early exits, preserve actual trade PnL
        # instead of replacing it with a hypothetical hold-to-resolution PnL.
        conn.execute(
            "UPDATE signals SET resolved = 1, realized_pnl = ? WHERE id = ?",
            (pnl, s["id"]),
        )

        # Update position status only for genuinely open positions.
        # Closed/cancelled rows are trade outcomes; resolution is a market outcome.
        if s["position_id"]:
            if not position_was_closed and s["position_status"] != "resolved":
                conn.execute(
                    "UPDATE positions SET status = 'resolved', closed_at = ?, closed_reason = 'resolution' WHERE id = ?",
                    (now, s["position_id"]),
                )
                db.add_pnl_event(
                    conn,
                    position_id=s["position_id"],
                    event_type="resolution",
                    value_usd=round(s["bet_amount"] + pnl, 2),
                    delta_pnl_usd=pnl,
                    note=f"Market resolved YES={resolved_yes:.0f}. PnL={pnl:+.2f}",
                    event_at=now,
                )
            elif position_was_closed:
                db.add_pnl_event(
                    conn,
                    position_id=s["position_id"],
                    event_type="market_resolution_after_exit",
                    value_usd=None,
                    delta_pnl_usd=0.0,
                    note=(
                        f"Market resolved YES={resolved_yes:.0f} after position was already "
                        f"{s['position_status']}; preserved trade PnL={pnl:+.2f}; "
                        f"hypothetical hold-to-resolution PnL={hypothetical_resolution_pnl:+.2f}"
                    ),
                    event_at=now,
                )

        # Brier scores
        signal_prob = float(s["claude_prob"] or s["yes_price_at_signal"])
        entry_price = float(s["yes_price_at_signal"])
        brier = _brier_score(signal_prob, resolved_yes)
        market_brier = _brier_score(entry_price, resolved_yes)

        # Outcome learning review
        outcome = _outcome_side(resolved_yes)
        errors = _classify_errors(
            signal_side=s["side"],
            signal_prob=signal_prob,
            signal_entry=entry_price,
            resolved_yes=resolved_yes,
            brier=brier,
            market_brier=market_brier,
        )
        archetype = s["primary_archetype"]
        error_tags = _classify_error_taxonomy(
            question=question,
            signal_side=s["side"],
            signal_prob=signal_prob,
            signal_entry=entry_price,
            resolved_yes=resolved_yes,
            brier=brier,
            market_brier=market_brier,
            archetype=archetype,
        )
        primary_error_type = _primary_error_type(error_tags, errors)
        lesson = _repeatable_lesson(s["side"], signal_prob, resolved_yes, brier, market_brier, archetype)
        why = _why_right_or_wrong(
            signal_side=s["side"],
            signal_prob=signal_prob,
            signal_entry=entry_price,
            resolved_yes=resolved_yes,
            realized_pnl=pnl,
            question=question,
            brier=brier,
            market_brier=market_brier,
        )
        draft = learning_review_draft({
            "condition_id": condition_id,
            "question": question,
            "predicted_side": s["side"],
            "outcome_side": outcome,
            "signal_probability_yes": signal_prob,
            "entry_price": entry_price,
            "resolved_yes": resolved_yes,
            "realized_pnl": pnl,
            "brier": brier,
            "market_brier": market_brier,
            "archetype": archetype,
            "heuristic_why": why,
            "heuristic_lesson": lesson,
            "heuristic_errors": errors,
            "heuristic_error_taxonomy": error_tags,
            "primary_error_type": primary_error_type,
        })
        if isinstance(draft.get("why_right_or_wrong"), str) and draft["why_right_or_wrong"].strip():
            why = draft["why_right_or_wrong"].strip()
        if isinstance(draft.get("repeatable_lesson"), str) and draft["repeatable_lesson"].strip():
            lesson = draft["repeatable_lesson"].strip()
        if isinstance(draft.get("error_flags"), dict):
            for key in errors:
                if key in draft["error_flags"]:
                    try:
                        errors[key] = 1 if int(draft["error_flags"][key]) else 0
                    except (TypeError, ValueError):
                        pass

        db.add_outcome_learning_review(
            conn,
            condition_id=condition_id,
            signal_id=s["id"],
            analysis_id=s["analysis_id"],
            created_at=None,
            analyst="command-e-auto",
            outcome_side=outcome,
            predicted_side=s["side"],
            entry_price=entry_price,
            probability_yes=signal_prob,
            confidence=float(s["confidence"] or 0.5),
            realized_pnl=pnl,
            brier_score=brier,
            market_brier_score=market_brier,
            outcome_summary=(
                f"Market '{question[:60]}' resolved {outcome}. "
                f"Signal side: {s['side']} @ {entry_price:.3f}. "
                f"Trade PnL: {pnl:+.2f}; hold-to-resolution PnL: {hypothetical_resolution_pnl:+.2f}."
            ),
            why_right_or_wrong=why,
            resolution_error=errors["resolution_error"],
            probability_error=errors["probability_error"],
            evidence_error=errors["evidence_error"],
            timing_error=errors["timing_error"],
            sizing_error=errors["sizing_error"],
            luck_factor=0.5,
            repeatable_lesson=lesson,
            rule_update=(
                draft.get("rule_update")
                if isinstance(draft.get("rule_update"), str)
                else (
                    "Early-exit learning: preserve actual trade PnL separately from "
                    "hypothetical hold-to-resolution PnL."
                    if position_was_closed
                    else None
                )
            ),
            error_taxonomy_json=json.dumps(error_tags, sort_keys=True),
            primary_error_type=primary_error_type,
        )

        signals_resolved.append({
            "signal_id": s["id"],
            "side": s["side"],
            "entry_price": entry_price,
            "resolved_yes": resolved_yes,
            "pnl": pnl,
            "brier": brier,
            "market_brier": market_brier,
            "archetype": archetype,
            "primary_error_type": primary_error_type,
        })

    return {
        "condition_id": condition_id,
        "question": question[:70],
        "status": "resolved",
        "resolved_yes": resolved_yes,
        "outcome": _outcome_side(resolved_yes),
        "signals_resolved": len(signals_resolved),
        "signals": signals_resolved,
        "total_pnl": round(sum(s["pnl"] for s in signals_resolved), 2),
    }


# ── Calibration stats ──────────────────────────────────────────────────────────

def _compute_calibration_stats(conn) -> dict:
    """Compute aggregate calibration statistics from outcome_learning_reviews."""
    rows = conn.execute("""
        SELECT probability_yes, outcome_side, realized_pnl,
               brier_score, market_brier_score
        FROM outcome_learning_reviews
        WHERE probability_yes IS NOT NULL
        ORDER BY created_at DESC
    """).fetchall()

    if not rows:
        return {"message": "No resolved outcomes yet"}

    n = len(rows)
    wins = sum(1 for r in rows if r["realized_pnl"] and r["realized_pnl"] > 0)
    avg_brier = sum(r["brier_score"] or 0 for r in rows) / n
    avg_market_brier = sum(r["market_brier_score"] or 0 for r in rows) / n
    total_pnl = sum(r["realized_pnl"] or 0 for r in rows)
    avg_prob = sum(r["probability_yes"] or 0 for r in rows) / n

    # Calibration bins (how often did 80% predictions resolve YES?)
    bins = {
        "0-20%": {"count": 0, "yes": 0},
        "20-40%": {"count": 0, "yes": 0},
        "40-60%": {"count": 0, "yes": 0},
        "60-80%": {"count": 0, "yes": 0},
        "80-100%": {"count": 0, "yes": 0},
    }
    for r in rows:
        p = r["probability_yes"] or 0
        o = 1 if r["outcome_side"] == "YES" else 0
        if p < 0.20:
            b = "0-20%"
        elif p < 0.40:
            b = "20-40%"
        elif p < 0.60:
            b = "40-60%"
        elif p < 0.80:
            b = "60-80%"
        else:
            b = "80-100%"
        bins[b]["count"] += 1
        bins[b]["yes"] += o

    calibration = {}
    for label, data in bins.items():
        if data["count"] > 0:
            calibration[label] = {
                "n": data["count"],
                "yes_rate": round(data["yes"] / data["count"], 3),
            }

    return {
        "total_resolved": n,
        "wins": wins,
        "win_rate_pct": round(wins / n * 100, 1),
        "total_pnl_usd": round(total_pnl, 2),
        "avg_brier_score": round(avg_brier, 4),
        "avg_market_brier": round(avg_market_brier, 4),
        "brier_edge": round(avg_market_brier - avg_brier, 4),  # positive = better than market
        "avg_confidence": round(avg_prob, 3),
        "calibration_bins": calibration,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

async def _run_async() -> tuple[list[dict], dict]:
    """Async resolution pass over all open signals."""
    import asyncio  # noqa: PLC0415

    with db.connect() as conn:
        # All condition_ids with at least one unresolved signal
        rows = conn.execute("""
            SELECT DISTINCT s.condition_id
            FROM signals s
            JOIN markets m ON m.condition_id = s.condition_id
            WHERE s.resolved = 0 AND m.resolved = 0
            ORDER BY m.end_date ASC NULLS LAST
        """).fetchall()
        cids = [r["condition_id"] for r in rows]

    print(f"Open condition IDs to check: {len(cids)}")

    results = []
    async with httpx.AsyncClient(timeout=20) as client:
        for cid in cids:
            print(f"  Checking {cid[:20]}...")
            with db.connect() as conn:
                r = await _resolve_market(conn, cid, client)
                conn.commit()
            results.append(r)
            status = r["status"]
            if status == "resolved":
                print(
                    f"    RESOLVED: outcome={r['outcome']} | "
                    f"signals={r['signals_resolved']} | pnl={r['total_pnl']:+.2f}"
                )
            elif status == "still_open":
                print(f"    Still open.")
            else:
                print(f"    Status: {status}")

    return results


def main():
    import asyncio  # noqa: PLC0415

    print("=== COMMAND E: Resolution Tracker & Outcome Learning ===\n")

    wf_id = _start_workflow_log(
        "resolution_tracker",
        "Resolution tracking + outcome learning",
        input_payload={},
        agent_name="claude-code",
        notes="Command E — idempotent resolution check for all open signals",
    )
    print(f"Workflow run ID: {wf_id}\n")

    results = asyncio.run(_run_async())

    resolved = [r for r in results if r["status"] == "resolved"]
    still_open = [r for r in results if r["status"] == "still_open"]
    errors = [r for r in results if r["status"] not in ("resolved", "still_open")]

    _record_workflow_step(
        wf_id,
        "resolution_pass",
        allowed_writes=["markets", "signals", "positions", "pnl_events", "outcome_learning_reviews"],
        writes_count=sum(r.get("signals_resolved", 0) for r in resolved),
        output_json={
            "markets_checked": len(results),
            "resolved": len(resolved),
            "still_open": len(still_open),
            "errors": len(errors),
            "total_pnl": round(sum(r.get("total_pnl", 0) for r in resolved), 2),
        },
    )

    # Calibration stats
    with db.connect() as conn:
        cal = _compute_calibration_stats(conn)

    _record_workflow_step(
        wf_id,
        "calibration_stats",
        allowed_writes=[],
        output_json=cal,
    )

    _finish_workflow_log(wf_id, status="completed", output_json={
        "resolved_count": len(resolved),
        "total_pnl": round(sum(r.get("total_pnl", 0) for r in resolved), 2),
    })

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n=== COMMAND E SUMMARY ===")
    print(f"Markets checked     : {len(results)}")
    print(f"Newly resolved      : {len(resolved)}")
    print(f"Still open          : {len(still_open)}")
    print(f"API errors          : {len(errors)}")

    if resolved:
        total_pnl = sum(r.get("total_pnl", 0) for r in resolved)
        print(f"\nResolved this run:")
        for r in resolved:
            pnl_str = f"+${r['total_pnl']:.2f}" if r['total_pnl'] >= 0 else f"-${abs(r['total_pnl']):.2f}"
            print(f"  {r['outcome']}: {r.get('question','')[:55]} | {pnl_str}")
        print(f"\nTotal PnL this run  : {'+' if total_pnl >= 0 else ''}{total_pnl:.2f}")

    if cal.get("total_resolved"):
        print(f"\nCumulative calibration stats ({cal['total_resolved']} resolved bets):")
        print(f"  Win rate      : {cal.get('win_rate_pct'):.1f}%")
        print(f"  Total PnL     : ${cal.get('total_pnl_usd'):.2f}")
        print(f"  Avg Brier     : {cal.get('avg_brier_score'):.4f} (market: {cal.get('avg_market_brier'):.4f})")
        edge = cal.get("brier_edge", 0)
        edge_sign = "+" if edge >= 0 else ""
        print(f"  Brier edge    : {edge_sign}{edge:.4f} ({'better' if edge >= 0 else 'worse'} than market)")
        if cal.get("calibration_bins"):
            print(f"  Calibration buckets:")
            for bucket, data in cal["calibration_bins"].items():
                print(f"    {bucket}: n={data['n']} | YES rate={data['yes_rate']:.0%}")
    else:
        print("\n  No resolved bets yet — calibration stats will appear after first resolution.")

    print(f"\nWorkflow run: {wf_id}")
    return results, wf_id


if __name__ == "__main__":
    results, wf_id = main()
    out_path = os.path.join(os.path.dirname(__file__), "resolution_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")
