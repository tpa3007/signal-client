"""Export Signal SQLite state for the React dashboard.

The dashboard is intentionally a read-only UI. This exporter turns the local
bot.db into a compact JSON snapshot served by Vite from dashboard-web/public.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

sys.path.insert(0, ".")
from lib.ledger_meta import edge_archetype_from_primary
try:
    from lib.calibration import calibration_stats
except Exception:  # noqa: BLE001
    calibration_stats = None


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = Path(__file__).resolve().parent
DB_PATH = BOT_DIR / "bot.db"
MONITOR_PATH = BOT_DIR / "monitor_results.json"
HANDOFF_DIR = BOT_DIR / "llm_handoff"
DEFAULT_OUT = ROOT / "dashboard-web" / "public" / "data" / "signal-dashboard.json"


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _repair_text(value: str) -> str:
    replacements = {
        "â": "—",
        "â": "–",
        "â¢": "•",
        "â": "“",
        "â": "”",
        "â": "‘",
        "â": "’",
        "â¥": "≥",
        "â¤": "≤",
        "Â·": "·",
        "Â¢": "¢",
    }
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    return value


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _repair_text(value)
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    return value


def _iso_to_date(value: str | None) -> str:
    if not value:
        return ""
    return value[:10]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        clean = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _days_to_expiry(value: str | None) -> float | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    delta = parsed - datetime.now(timezone.utc)
    return round(delta.total_seconds() / 86400, 1)


def _market_url(slug: str | None) -> str:
    if not slug:
        return ""
    return f"https://polymarket.com/event/{slug}"


def _source_name(url: str) -> str:
    clean = url.replace("https://", "").replace("http://", "")
    return clean.split("/", 1)[0] or "source"


def _status(signal: dict[str, Any], position: dict[str, Any]) -> str:
    # A closed position is CLOSED even if signal.resolved lagged behind.
    if signal.get("resolved") or position.get("status") == "closed":
        return "CLOSED"
    if position.get("status") in {"open", "pending"}:
        return "COMMITTED"
    return "DRAFT"


def _category(vertical: str | None, question: str | None) -> str:
    text = f"{vertical or ''} {question or ''}".lower()
    if "private" in text or "valuation" in text or "openai" in text or "spacex" in text:
        return "Private Markets"
    if "election" in text or "primary" in text or "governor" in text or "mayor" in text:
        return "Elections"
    if "iran" in text or "israel" in text or "trump" in text or "putin" in text:
        return "Geopolitics"
    if "fed" in text or "rba" in text or "rate" in text:
        return "Macro"
    if "ai" in text or "gemini" in text or "gpt" in text:
        return "AI"
    return (vertical or "General").replace("_", " ").title()


def _load_latest_snapshot(conn: sqlite3.Connection, condition_id: str) -> dict[str, Any]:
    return _row_to_dict(conn.execute(
        """
        SELECT *
        FROM snapshots
        WHERE condition_id = ?
        ORDER BY captured_at DESC, id DESC
        LIMIT 1
        """,
        (condition_id,),
    ).fetchone())


def _load_latest_checklist(conn: sqlite3.Connection, condition_id: str) -> dict[str, Any]:
    return _row_to_dict(conn.execute(
        """
        SELECT *
        FROM pre_bet_checklists
        WHERE condition_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (condition_id,),
    ).fetchone())


def _load_price_history(conn: sqlite3.Connection, condition_id: str, max_points: int = 40) -> list[dict[str, Any]]:
    """Return a downsampled YES-price series for sparklines: [{t, p}]."""
    rows = conn.execute(
        """
        SELECT captured_at, yes_price
        FROM snapshots
        WHERE condition_id = ? AND yes_price IS NOT NULL
        ORDER BY captured_at ASC
        """,
        (condition_id,),
    ).fetchall()
    if not rows:
        return []
    n = len(rows)
    if n <= max_points:
        sample = rows
    else:
        step = n / max_points
        sample = [rows[min(int(i * step), n - 1)] for i in range(max_points)]
        if sample[-1] is not rows[-1]:
            sample[-1] = rows[-1]  # always keep most recent
    out = []
    for r in sample:
        try:
            out.append({"t": _iso_to_date(r["captured_at"]), "p": round(float(r["yes_price"]), 4)})
        except (TypeError, ValueError):
            continue
    return out


def _load_smart_money(conn: sqlite3.Connection, condition_id: str) -> dict[str, Any]:
    """Aggregate tracked-wallet positioning for a market."""
    rows = conn.execute(
        """
        SELECT first_entry_side, total_usd, timing_alpha, resolved, outcome_yes, p_yes_equiv
        FROM wallet_market_entries
        WHERE condition_id = ?
        """,
        (condition_id,),
    ).fetchall()
    if not rows:
        return {}
    yes_usd = sum(_f(r["total_usd"]) for r in rows if (r["first_entry_side"] or "").upper() == "YES")
    no_usd = sum(_f(r["total_usd"]) for r in rows if (r["first_entry_side"] or "").upper() == "NO")
    total_usd = yes_usd + no_usd
    alphas = [_f(r["timing_alpha"]) for r in rows if r["timing_alpha"] is not None]
    return {
        "walletCount": len(rows),
        "totalUsd": round(total_usd, 2),
        "yesUsd": round(yes_usd, 2),
        "noUsd": round(no_usd, 2),
        "yesShare": round(yes_usd / total_usd, 3) if total_usd else None,
        "dominantSide": "YES" if yes_usd > no_usd else "NO" if no_usd > yes_usd else "SPLIT",
        "avgTimingAlpha": round(sum(alphas) / len(alphas), 3) if alphas else None,
    }


def _load_evidence(conn: sqlite3.Connection, condition_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT source_url, source_name, claim, stance, strength, reliability
        FROM evidence
        WHERE condition_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 4
        """,
        (condition_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _load_actors(conn: sqlite3.Connection, condition_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT actor_name, actor_type, role, incentives, likely_action, influence_score
        FROM actor_maps
        WHERE condition_id = ?
        ORDER BY influence_score DESC, id DESC
        LIMIT 4
        """,
        (condition_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _build_analytics(conn: sqlite3.Connection, signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Portfolio-wide analytics: calibration, Brier-vs-market, exposure breakdowns."""
    analytics: dict[str, Any] = {}

    # Calibration buckets (predicted vs actual win rate)
    if calibration_stats is not None:
        try:
            stats = calibration_stats(str(DB_PATH))
            buckets = [
                {
                    "bucket": float(k),
                    "predicted": v["predicted_center"],
                    "actual": v["actual_win_rate"],
                    "count": v["count"],
                }
                for k, v in (stats.get("buckets") or {}).items()
            ]
            buckets.sort(key=lambda b: b["bucket"])
            analytics["calibration"] = {
                "resolved": stats.get("resolved", 0),
                "active": stats.get("calibration_active", False),
                "overconfident": stats.get("overconfident", False),
                "wellCalibrated": stats.get("well_calibrated", False),
                "averageDelta": stats.get("average_delta", 0),
                "buckets": buckets,
            }
        except Exception:  # noqa: BLE001
            pass

    # Brier vs market on resolved learning reviews
    rows = conn.execute(
        """
        SELECT brier_score, market_brier_score, outcome_side, primary_error_type, archetype_family
        FROM outcome_learning_reviews
        WHERE outcome_side IN ('YES', 'NO')
        """
    ).fetchall()
    if rows:
        our_briers = [_f(r["brier_score"]) for r in rows if r["brier_score"] is not None]
        mkt_briers = [_f(r["market_brier_score"]) for r in rows if r["market_brier_score"] is not None]
        beat_market = sum(
            1 for r in rows
            if r["brier_score"] is not None and r["market_brier_score"] is not None
            and _f(r["brier_score"]) < _f(r["market_brier_score"])
        )
        error_types: dict[str, int] = {}
        for r in rows:
            et = r["primary_error_type"]
            if et:
                error_types[et] = error_types.get(et, 0) + 1
        analytics["brier"] = {
            "resolved": len(rows),
            "ourAvgBrier": round(sum(our_briers) / len(our_briers), 4) if our_briers else None,
            "marketAvgBrier": round(sum(mkt_briers) / len(mkt_briers), 4) if mkt_briers else None,
            "beatMarketCount": beat_market,
            "errorTypes": error_types,
        }

    # Exposure by category and edge archetype (open committed only)
    open_signals = [s for s in signals if s["status"] == "COMMITTED"]
    by_category: dict[str, float] = {}
    by_archetype: dict[str, float] = {}
    for s in open_signals:
        cap = _f(s.get("realBetUsd")) or _f(s.get("allocatedCapital"))
        by_category[s.get("category", "General")] = by_category.get(s.get("category", "General"), 0) + cap
        arch = s.get("edgeArchetype") or "unknown"
        by_archetype[arch] = by_archetype.get(arch, 0) + cap
    analytics["exposure"] = {
        "byCategory": {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
        "byArchetype": {k: round(v, 2) for k, v in sorted(by_archetype.items(), key=lambda x: -x[1])},
    }

    return analytics


def _latest_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, workflow_name, status, started_at, completed_at, agent_name, notes
        FROM workflow_runs
        ORDER BY started_at DESC, id DESC
        LIMIT 8
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _build_diary_entry(task: str, data: dict[str, Any], response: dict[str, Any]) -> dict[str, Any] | None:
    created_at = data.get("created_at", "")
    if task == "dossier_draft":
        candidate = data.get("context", {}).get("candidate", {})
        packet = data.get("context", {}).get("packet", {})
        raw_hyps = packet.get("hypotheses", [])[:4]
        hypotheses = [
            {
                "direction": h.get("direction", "UNCERTAIN"),
                "title": h.get("title", ""),
                "text": h.get("hypothesis_text", ""),
                "confidence": round(float(h.get("confidence") or 0), 3),
            }
            for h in raw_hyps
        ]
        return {
            "type": "dossier",
            "date": created_at[:10],
            "timestamp": created_at,
            "heading": "Форейджер завершил исследование",
            "body": candidate.get("thesis") or "",
            "killCriteria": candidate.get("kill_criteria") or response.get("kill_criteria") or [],
            "scenarios": response.get("scenarios") or [],
            "premortems": response.get("premortems") or [],
            "hypotheses": hypotheses,
            "confidenceAdjustment": response.get("confidence_adjustment"),
            "signalDecisionLabel": packet.get("signal_decision_value_label") or "",
            "signalDecisionValue": round(float(packet.get("signal_decision_value") or 0), 3),
            "generator": "forager",
        }
    if task == "monitoring_draft":
        return {
            "type": "monitoring",
            "date": created_at[:10],
            "timestamp": created_at,
            "heading": str(response.get("advisory_recommendation") or "HOLD").upper(),
            "body": response.get("reason") or "",
            "killCriteria": response.get("kill_criteria") or [],
            "nextQueries": response.get("next_queries") or [],
            "hypotheses": [],
            "generator": "command_f",
        }
    return None


def _load_handoff_diary() -> dict[str, list[dict[str, Any]]]:
    """Scan llm_handoff/ and return {condition_id: [diary_entry, ...]}."""
    result: dict[str, list[dict[str, Any]]] = {}
    if not HANDOFF_DIR.exists():
        return result
    allowed_tasks = {"dossier_draft", "monitoring_draft"}
    for fpath in sorted(HANDOFF_DIR.glob("*.json")):
        if ".response." in fpath.name:
            continue
        try:
            data = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        task = data.get("task", "")
        if task not in allowed_tasks:
            continue
        ctx = data.get("context", {})
        if task == "dossier_draft":
            condition_id = ctx.get("candidate", {}).get("condition_id")
        else:
            condition_id = ctx.get("position", {}).get("condition_id")
        if not condition_id:
            continue
        response_path = fpath.parent / (fpath.stem + ".response.json")
        response: dict[str, Any] = {}
        if response_path.exists():
            try:
                raw = json.loads(response_path.read_text(encoding="utf-8", errors="replace"))
                response = raw.get("response") or raw
            except Exception:
                pass
        entry = _build_diary_entry(task, data, response)
        if entry:
            result.setdefault(condition_id, []).append(entry)
    # sort each list chronologically
    for entries in result.values():
        entries.sort(key=lambda e: e.get("timestamp", ""))
    return result


def _load_monitor_results() -> dict[str, dict[str, Any]]:
    if not MONITOR_PATH.exists():
        return {}
    try:
        payload = json.loads(MONITOR_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}
    return {
        item["condition_id"]: item
        for item in payload
        if isinstance(item, dict) and item.get("condition_id")
    }


def _fallback_recommendation(unrealized: float, days_to_expiry: float | None) -> tuple[str, str]:
    if unrealized <= -5:
        return "REVIEW", "Позиция в заметном минусе; стоит проверить тезис и свежие disconfirming facts."
    if days_to_expiry is not None and days_to_expiry <= 2:
        return "REVIEW", "Близкая дата резолюции; нужно руками проверить риск последнего новостного сдвига."
    return "HOLD", "Автоматический мониторинг не нашел явного повода менять позицию."


def _build_signal(conn: sqlite3.Connection, row: sqlite3.Row, monitor_results: dict[str, dict[str, Any]], handoff_diary: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    signal = dict(row)
    condition_id = signal["condition_id"]
    position = _row_to_dict(conn.execute(
        """
        SELECT *
        FROM positions
        WHERE signal_id = ?
        ORDER BY opened_at DESC, id DESC
        LIMIT 1
        """,
        (signal["id"],),
    ).fetchone())
    snapshot = _load_latest_snapshot(conn, condition_id)
    checklist = _load_latest_checklist(conn, condition_id)
    evidence_rows = _load_evidence(conn, condition_id)
    actor_rows = _load_actors(conn, condition_id)
    price_history = _load_price_history(conn, condition_id)
    smart_money = _load_smart_money(conn, condition_id)

    status = _status(signal, position)
    side = signal.get("side") or position.get("intended_side") or "YES"
    yes_entry = _f(signal.get("yes_equivalent_entry"), _f(signal.get("yes_price_at_signal")))
    side_entry = _f(signal.get("side_entry_price"), yes_entry if side == "YES" else 1 - yes_entry)
    current_yes = _f(snapshot.get("yes_price"), yes_entry)
    current_no = _f(snapshot.get("no_price"), 1 - current_yes)
    current_side = current_yes if side == "YES" else current_no
    stake = _f(position.get("intended_stake_usd"), _f(signal.get("bet_amount")))
    shares = stake / side_entry if side_entry else 0.0
    # Unrealized PnL is only meaningful for genuinely open positions.
    unrealized = (current_side - side_entry) * shares if status == "COMMITTED" else 0.0
    days_to_expiry = _days_to_expiry(signal.get("end_date"))
    monitor = monitor_results.get(condition_id, {})
    monitor_days = monitor.get("days_to_expiry")
    if monitor_days is not None:
        days_to_expiry = _f(monitor_days)
    fallback_recommendation, fallback_reason = _fallback_recommendation(unrealized, days_to_expiry)
    monitor_recommendation = str(monitor.get("recommendation") or fallback_recommendation).upper()
    monitor_reason = monitor.get("reason") or fallback_reason
    model_prob = _f(signal.get("claude_prob"))
    market_prob = yes_entry
    edge = _f(signal.get("edge"))
    is_real = bool(signal.get("real_money"))
    sources = _json_list(signal.get("sources_json"))
    source_evidence = [
        {
            "source_name": _source_name(str(url)),
            "source_url": url,
            "claim": "Operator source attached to this signal.",
            "stance": "SUPPORTS",
            "strength": 0.65,
            "reliability": 0.65,
        }
        for url in sources[:4]
        if isinstance(url, str) and url
    ]
    evidence_rows = [*source_evidence, *evidence_rows]
    if not evidence_rows:
        evidence_rows = [{
            "source_name": "Signal reasoning",
            "source_url": "",
            "claim": (signal.get("reasoning") or "No reasoning recorded.")[:260],
            "stance": "NEUTRAL",
            "strength": 0.35,
            "reliability": 0.45,
        }]

    if not actor_rows:
        actor_rows = [{
            "actor_name": "Market participants",
            "role": "Pricing the event",
            "incentives": "React to public news and liquidity",
            "likely_action": "Reprice on catalyst",
            "influence_score": 0.5,
        }]

    return {
        "id": f"sig-{signal['id']}",
        "signalId": signal["id"],
        "positionId": position.get("id"),
        "conditionId": condition_id,
        "title": signal.get("question") or condition_id,
        "marketUrl": _market_url(signal.get("slug")),
        "category": _category(signal.get("vertical"), signal.get("question")),
        "status": status,
        "createdAt": _iso_to_date(signal.get("created_at")),
        "openedAt": position.get("opened_at") or signal.get("created_at"),
        "endDate": _iso_to_date(signal.get("end_date")),
        "side": side,
        "qualityScore": round(_f(signal.get("confidence"), 0.5) * 10, 1),
        "polymarketPrice": round(market_prob, 4),
        "calculatedProbability": round(model_prob, 4),
        "edge": round(edge * 100, 1),
        "allocatedCapital": round(stake, 2),
        "realMoney": is_real,
        "realBetUsd": _f(signal.get("real_bet_usd")),
        "signalGenerationEpoch": signal.get("signal_generation_epoch") or position.get("signal_generation_epoch"),
        "edgeArchetype": edge_archetype_from_primary(
            signal.get("edge_archetype") or position.get("edge_archetype"),
            signal.get("question"),
        ),
        "confidenceSource": signal.get("confidence_source") or position.get("confidence_source"),
        "approvalStrength": signal.get("approval_strength") or position.get("approval_strength"),
        "postEntryReviewRequired": bool(
            signal.get("post_entry_review_required") or position.get("post_entry_review_required")
        ),
        "postEntryReviewReason": (
            signal.get("post_entry_review_reason") or position.get("post_entry_review_reason") or ""
        ),
        "sideEntryPrice": round(side_entry, 4),
        "yesEquivalentEntry": round(yes_entry, 4),
        "currentYesPrice": round(current_yes, 4),
        "currentNoPrice": round(current_no, 4),
        "currentSidePrice": round(current_side, 4),
        "unrealizedPnl": round(unrealized, 2),
        "daysToExpiry": days_to_expiry,
        "monitorRecommendation": monitor_recommendation,
        "monitorReason": monitor_reason,
        "monitorSdv": round(_f(monitor.get("sdv")), 4) if monitor else None,
        "killCriteriaCovered": monitor.get("kc_covered") if monitor else None,
        "killCriteriaTotal": monitor.get("kc_total") if monitor else None,
        "monitorBlockers": monitor.get("blockers") or [],
        "killCriteriaTriggered": monitor.get("kill_criteria_triggered") or [],
        "thesis": signal.get("reasoning") or "",
        "sources": sources,
        "evidence": evidence_rows,
        "actors": actor_rows,
        "priceHistory": price_history,
        "smartMoney": ({
            **smart_money,
            "agreesWithUs": (smart_money.get("dominantSide") == side)
            if smart_money.get("dominantSide") in {"YES", "NO"} else None,
        } if smart_money else None),
        "gateCheck": {
            "liquidityOk": bool(checklist.get("liquidity_ok", 1)),
            "noLineAnomaly": bool(checklist.get("spread_ok", 1)),
            "riskCleared": (checklist.get("decision") or signal.get("gate_status")) in {
                "approved_for_signal", "gated", "paper_only_low_edge", None
            },
            "gatePassed": (signal.get("gate_status") or "") == "gated",
            "decision": checklist.get("decision") or signal.get("gate_status") or "unknown",
            "checklistScore": _f(checklist.get("checklist_score")),
        },
        "review": {
            "outcome": "WON" if _f(signal.get("realized_pnl")) > 0 else "LOST",
            "pnl": _f(signal.get("realized_pnl")),
            "notes": signal.get("gate_audit_note") or "",
            "qualityRating": round(_f(signal.get("confidence"), 0.5) * 10, 1),
            "reviewedAt": _iso_to_date(signal.get("created_at")),
        } if signal.get("resolved") else None,
        "diaryEntries": _build_signal_diary(signal, handoff_diary or {}),
    }


def _build_signal_diary(signal: dict[str, Any], handoff_diary: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Assemble full diary timeline for a signal: created + handoff entries + resolved."""
    entries: list[dict[str, Any]] = []
    condition_id = signal.get("condition_id", "")
    # Entry 0: signal created
    entries.append({
        "type": "signal_created",
        "date": _iso_to_date(signal.get("created_at")),
        "timestamp": signal.get("created_at") or "",
        "heading": "Сигнал создан",
        "body": signal.get("reasoning") or signal.get("thesis") or "",
        "hypotheses": [],
        "killCriteria": [],
        "generator": "operator",
    })
    # Handoff entries (dossier + monitoring)
    entries.extend(handoff_diary.get(condition_id, []))
    # Final entry if resolved
    if signal.get("resolved"):
        pnl = _f(signal.get("realized_pnl"))
        outcome = "WON" if pnl > 0 else "LOST"
        entries.append({
            "type": "resolved",
            "date": _iso_to_date(signal.get("created_at")),
            "timestamp": signal.get("created_at") or "",
            "heading": outcome,
            "body": signal.get("gate_audit_note") or f"Результат: {'+' if pnl >= 0 else ''}{pnl:.2f}$",
            "hypotheses": [],
            "killCriteria": [],
            "generator": "system",
        })
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def export_dashboard_data(out_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        monitor_results = _load_monitor_results()
        handoff_diary = _load_handoff_diary()
        signal_rows = conn.execute(
            """
            SELECT s.*, m.question, m.slug, m.end_date, COALESCE(m.vertical, 'unknown') AS vertical
            FROM signals s
            LEFT JOIN markets m ON m.condition_id = s.condition_id
            ORDER BY s.created_at DESC, s.id DESC
            """
        ).fetchall()
        signals = [_build_signal(conn, r, monitor_results, handoff_diary) for r in signal_rows]
        open_signals = [s for s in signals if s["status"] == "COMMITTED"]
        closed_signals = [s for s in signals if s["status"] == "CLOSED"]
        real_open = [s for s in open_signals if s["realMoney"]]
        paper_open = [s for s in open_signals if not s["realMoney"]]
        closed_wins = [s for s in closed_signals if (s.get("review") or {}).get("outcome") == "WON"]

        summary = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "totalSignals": len(signals),
            "openSignals": len(open_signals),
            "closedSignals": len(closed_signals),
            "realExposure": round(sum(_f(s.get("realBetUsd")) or _f(s.get("allocatedCapital")) for s in real_open), 2),
            "paperExposure": round(sum(_f(s.get("allocatedCapital")) for s in paper_open), 2),
            "paperAccuracy": round((len(closed_wins) / len(closed_signals) * 100) if closed_signals else 0.0, 1),
            "realizedPnl": round(sum(_f((s.get("review") or {}).get("pnl")) for s in closed_signals), 2),
            "unrealizedPnl": round(sum(_f(s.get("unrealizedPnl")) for s in open_signals), 2),
            "avgEdge": round(sum(abs(_f(s.get("edge"))) for s in signals) / len(signals), 1) if signals else 0.0,
        }
        # flat global diary feed sorted newest-first
        global_diary = []
        for sig in signals:
            for entry in sig.get("diaryEntries", []):
                global_diary.append({**entry, "signalId": sig["id"], "signalTitle": sig["title"]})
        global_diary.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        payload = {
            "summary": summary,
            "signals": signals,
            "diary": global_diary[:200],
            "analytics": _build_analytics(conn, signals),
            "workflowRuns": _latest_runs(conn),
            "modelEvolution": [
                {
                    "date": "2026-05-24",
                    "version": "v3.0-private",
                    "status": "UPGRADE",
                    "title": "Private/NPM valuation workflow",
                    "description": "Added Command P and manual operator review for NPM-priced private-company valuation markets.",
                    "metric": "Private market gate",
                    "before": "generic",
                    "after": "provider-mark aware",
                },
                {
                    "date": "2026-05-24",
                    "version": "v2.9-human-loop",
                    "status": "CALIBRATION",
                    "title": "Reasoning-first candidate gate",
                    "description": "Command R/M path requires operator probability for reasoned candidates, preventing SDV-only approvals.",
                    "metric": "D gate failure mode",
                    "before": "auto probability",
                    "after": "manual probability",
                },
                {
                    "date": "2026-05-23",
                    "version": "v2.8-ledger",
                    "status": "CRITICAL_ADAPTATION",
                    "title": "Explicit side-entry price model",
                    "description": "Signal records now distinguish side_entry_price and yes_equivalent_entry for NO-side ledger correctness.",
                    "metric": "NO accounting",
                    "before": "mixed price",
                    "after": "explicit price",
                },
            ],
        }
    finally:
        conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _sanitize(payload)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    payload = export_dashboard_data(args.out)
    print(f"exported {len(payload['signals'])} signals -> {args.out}")


if __name__ == "__main__":
    main()
