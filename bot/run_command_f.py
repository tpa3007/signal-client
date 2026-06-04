"""Command F — Forager Position Monitor (paper only).

Runs a lightweight Forager refresh on each open paper position and emits a
HOLD / REVIEW / EXIT recommendation based on updated SDV and evidence quality.

Designed to run daily (or ad-hoc) on open positions expiring within a
configurable horizon.  Never touches real money.

Exit logic:
- EXIT (adverse): SDV < 0.25 AND new disconfirming evidence found → thesis broken
- EXIT (stale):   position within 2 days of expiry with no new evidence
- REVIEW:         SDV dropped 0.15+ vs entry baseline, or strong contradicting claims
- HOLD:           everything else (default)
"""
import sys, os, json
from datetime import datetime, timezone, timedelta

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
from tools.workflows import _start_workflow_log, _record_workflow_step, _finish_workflow_log
from lib.ollama import monitoring_draft

from forager.service import ForagerService
from forager.models import CoreResearchLoopRequest, DepthMode
from forager.memory.sqlite_store import SQLiteForagerStore
from forager.memory import InMemoryForagerStore


def _packet_dict(packet):
    if packet is None:
        return None
    if isinstance(packet, dict):
        return packet
    if hasattr(packet, "model_dump"):
        return packet.model_dump()
    if hasattr(packet, "dict"):
        return packet.dict()
    return {}


def _send_toast(title: str, message: str) -> None:
    """Send a Windows desktop toast notification via plyer (silently skips if unavailable)."""
    try:
        from plyer import notification  # noqa: PLC0415
        notification.notify(
            title=title,
            message=message[:250],
            app_name="Signal",
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        pass  # plyer not installed or not on Windows — never block monitoring


def _get_position_kill_criteria(condition_id: str) -> list[str]:
    """Load kill criteria for a position: check moonshot_reviews, then forager_queue_auto."""
    criteria: list[str] = []
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT kill_criteria FROM moonshot_reviews WHERE condition_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (condition_id,),
            ).fetchone()
            if row and row["kill_criteria"]:
                raw = row["kill_criteria"]
                # Kill criteria stored as free text — split on sentence boundaries
                import re  # noqa: PLC0415
                parts = re.split(r"(?<=[.!?])\s+|;\s*|\n+", raw.strip())
                criteria = [p.strip() for p in parts if len(p.strip()) > 15][:5]
    except Exception:  # noqa: BLE001
        pass
    return criteria

# ── Configuration ─────────────────────────────────────────────────────────────

# Only monitor positions expiring within this many days (env-overridable)
import os as _os
MONITOR_HORIZON_DAYS = int(_os.getenv("SIGNAL_COMMAND_F_HORIZON_DAYS", "14") or "14")
# Optional: restrict monitoring to one market (condition_id prefix) for a targeted recheck
SIGNAL_COMMAND_F_ONLY_CID = _os.getenv("SIGNAL_COMMAND_F_ONLY_CID", "").strip().lower()

# Minimum Forager SDV from entry to skip re-monitoring (positions already well-researched)
SDV_RESEARCH_SKIP_THRESHOLD = 0.80

# Thresholds for recommendation levels
SDV_EXIT_ADVERSE_THRESHOLD = 0.25   # SDV below this + disconf = EXIT
SDV_REVIEW_DROP_THRESHOLD = 0.15    # SDV dropped by this much vs original = REVIEW
EXPIRY_STALE_DAYS = 2               # Within this many days of expiry with no new signal = REVIEW

# MTM-based take-profit / stop-loss (added 2026-05-23 — see Architecture Audit P1).
# Computed as side-aware: for YES, profit_pct = (cur_yes / entry_yes) - 1;
# for NO, profit_pct = ((1 - cur_yes) / (1 - entry_yes)) - 1.
TAKE_PROFIT_RATIO = 2.0   # current value ≥ 2.0× entry → suggest closing
STOP_LOSS_RATIO = 0.4     # current value ≤ 0.4× entry AND > 5d remaining → review for exit
STOP_LOSS_MIN_DAYS = 5    # don't stop-loss if already near resolution

# Kill criteria templates per market archetype (generic defaults)
_GENERIC_KILL_CRITERIA_NO = [
    "Strong YES resolution evidence found",
    "Unexpected policy reversal announced",
    "Event occurred contrary to original thesis",
]

_GENERIC_KILL_CRITERIA_YES = [
    "NO resolution evidence confirmed",
    "Market cancelled or suspended",
    "Thesis-breaking development announced",
]


def _make_store() -> ForagerService:
    db_path = os.environ.get("FORAGER_DB_PATH", "").strip()
    if db_path:
        print(f"[forager] Using SQLiteForagerStore: {db_path}")
        return SQLiteForagerStore(db_path)
    print("[forager] Using InMemoryForagerStore")
    return InMemoryForagerStore()


def _days_to_expiry(end_date_str: str | None) -> float | None:
    if not end_date_str:
        return None
    try:
        # Handle both ISO format and date-only strings
        if "T" in end_date_str:
            dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (dt - now).total_seconds() / 86400
    except Exception:
        return None


def _load_all_open_positions() -> list[dict]:
    """Load ALL open paper positions (no horizon filter) for MTM-only scan."""
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT
                p.id AS position_id,
                p.condition_id,
                p.intended_side,
                p.intended_entry_price,
                p.intended_stake_usd,
                p.end_date,
                p.thesis_snapshot_text,
                p.signal_id,
                s.yes_price_at_signal,
                s.side_entry_price AS signal_side_entry_price,
                s.yes_equivalent_entry AS signal_yes_equivalent_entry,
                s.claude_prob,
                s.confidence AS signal_confidence,
                s.edge,
                s.reasoning AS signal_reasoning,
                m.question,
                m.end_date AS market_end_date
            FROM positions p
            LEFT JOIN signals s ON p.signal_id = s.id
            LEFT JOIN markets m ON p.condition_id = m.condition_id
            WHERE p.status = 'open' AND p.stake_source IN ('paper', 'real_money')
            ORDER BY p.end_date ASC
        """).fetchall()
    positions = []
    for r in rows:
        d = dict(r)
        dte = _days_to_expiry(d.get("end_date") or d.get("market_end_date"))
        d["days_to_expiry"] = round(dte, 1) if dte is not None else 999.0
        positions.append(d)
    return positions


def _mtm_scan_all_positions() -> list[dict]:
    """Scan ALL open positions for MTM-based TAKE_PROFIT / STOP_LOSS via CLOB only.

    This runs for every open position regardless of monitoring horizon, catching
    long-dated positions like resolved markets (YES→$1.00) that would otherwise
    slip through the 14-day Forager research window.
    """
    positions = _load_all_open_positions()
    alerts = []
    print(f"\n[MTM Scan] Checking {len(positions)} open positions for TAKE_PROFIT/STOP_LOSS...")
    for pos in positions:
        cid = pos["condition_id"]
        side = pos.get("intended_side", "")
        dte = pos.get("days_to_expiry", 999.0)
        entry = _entry_side_price(pos)
        cur_yes = _current_market_price(cid)
        if cur_yes is None:
            continue
        ratio = _mtm_ratio(side, entry, cur_yes)
        if ratio >= TAKE_PROFIT_RATIO:
            signal = "TAKE_PROFIT"
        elif ratio <= STOP_LOSS_RATIO and dte > STOP_LOSS_MIN_DAYS:
            signal = "STOP_LOSS_REVIEW"
        else:
            continue  # no action needed
        reason = (
            f"MTM {ratio:.2f}x entry | {side} @${entry:.4f} → live YES=${cur_yes:.4f} | {dte:.1f}d left"
        )
        alerts.append({
            "position_id": pos["position_id"],
            "condition_id": cid,
            "question": (pos.get("question") or "")[:65],
            "side": side,
            "entry_price": entry,
            "current_yes": cur_yes,
            "mtm_ratio": round(ratio, 3),
            "days_to_expiry": dte,
            "signal": signal,
            "reason": reason,
        })
        print(f"  !! [{signal}] #{pos['position_id']} {(pos.get('question') or '')[:55]} | {reason}")
        if signal in ("TAKE_PROFIT",):
            _send_toast(f"Signal: {signal}", f"[{side}] {(pos.get('question') or '')[:60]}\n{reason[:100]}")
    if not alerts:
        print("[MTM Scan] No TAKE_PROFIT / STOP_LOSS triggers found.")
    return alerts


def _load_open_positions(horizon_days: int) -> list[dict]:
    """Load open paper positions expiring within horizon_days."""
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT
                p.id AS position_id,
                p.condition_id,
                p.intended_side,
                p.intended_entry_price,
                p.intended_stake_usd,
                p.end_date,
                p.thesis_snapshot_text,
                p.signal_id,
                s.yes_price_at_signal,
                s.side_entry_price AS signal_side_entry_price,
                s.yes_equivalent_entry AS signal_yes_equivalent_entry,
                s.claude_prob,
                s.confidence AS signal_confidence,
                s.edge,
                s.reasoning AS signal_reasoning,
                m.question,
                m.end_date AS market_end_date
            FROM positions p
            LEFT JOIN signals s ON p.signal_id = s.id
            LEFT JOIN markets m ON p.condition_id = m.condition_id
            WHERE p.status = 'open' AND p.stake_source IN ('paper', 'real_money')
            ORDER BY p.end_date ASC
        """).fetchall()
    positions = []
    for r in rows:
        d = dict(r)
        if SIGNAL_COMMAND_F_ONLY_CID and not str(d.get("condition_id") or "").lower().startswith(SIGNAL_COMMAND_F_ONLY_CID):
            continue
        dte = _days_to_expiry(d.get("end_date") or d.get("market_end_date"))
        if dte is not None and dte <= horizon_days:
            d["days_to_expiry"] = round(dte, 1)
            positions.append(d)
    return positions


def _build_monitor_request(position: dict) -> CoreResearchLoopRequest:
    """Build a fast monitoring research loop for a position."""
    question = position.get("question") or ""
    side = position.get("intended_side", "")
    entry_price = position.get("intended_entry_price", 0.5)

    # Seed query derived from question and side
    if side == "NO":
        seed_query = f"{question[:120]} evidence against unlikely confirmation"
    else:
        seed_query = f"{question[:120]} latest evidence confirmation update"

    kill_criteria = _get_position_kill_criteria(position["condition_id"])
    if not kill_criteria:
        draft = monitoring_draft(position, None)
        if isinstance(draft.get("kill_criteria"), list):
            kill_criteria = [str(x).strip() for x in draft["kill_criteria"] if str(x).strip()][:5]
    if not kill_criteria:
        kill_criteria = _GENERIC_KILL_CRITERIA_NO if side == "NO" else _GENERIC_KILL_CRITERIA_YES

    return CoreResearchLoopRequest(
        seed_query=seed_query,
        market_id=position["condition_id"],
        depth=DepthMode.SHALLOW,   # Fast: 1 round, fewer queries
        recursive_rounds=1,
        max_queries_per_round=3,
        results_per_query=3,
        max_sources_per_round=4,
        include_local_language=False,
        execute_translations=False,
        run_semantic_graph=True,
        build_evidence_drafts=False,   # Skip slow evidence draft step
        require_disconfirming_evidence=True,
        kill_criteria=kill_criteria,
    )


def _current_market_price(condition_id: str) -> float | None:
    """Fetch current YES price from Polymarket CLOB. Returns None on failure."""
    try:
        import httpx  # noqa: PLC0415
        r = httpx.get(f"https://clob.polymarket.com/markets/{condition_id}", timeout=8)
        if r.status_code == 200:
            d = r.json()
            return float(d["tokens"][0]["price"])
    except Exception:  # noqa: BLE001
        pass
    return None


def _mtm_ratio(side: str, entry_side_price: float, current_yes: float) -> float:
    """Side-aware MTM ratio using the stored side-entry price.

    positions.intended_entry_price stores the executable entry for the side
    being traded: YES price for YES positions, NO price for NO positions.
    """
    if side == "YES":
        return current_yes / max(entry_side_price, 0.001)
    return (1.0 - current_yes) / max(entry_side_price, 0.001)


def _entry_side_price(position: dict) -> float:
    """Return executable entry price for the held side.

    New signals store this explicitly. Some legacy positions stored a
    yes-equivalent value in positions.intended_entry_price, so prefer the
    normalized signal column when it exists.
    """
    entry = position.get("signal_side_entry_price")
    if entry is None:
        entry = position.get("intended_entry_price")
    try:
        return float(entry)
    except (TypeError, ValueError):
        return 0.5


def _documents_written(result) -> int:
    total = 0
    for step in getattr(result, "steps", []) or []:
        if step.get("step") == "crawl_extract":
            try:
                total += int(step.get("documents_written") or 0)
            except (TypeError, ValueError):
                pass
    return total


def _hard_monitor_blockers(blockers: list[str], documents_written: int) -> list[str]:
    """Return only genuinely hard blockers — ones that mean the search itself failed.

    IMPORTANT: 'documents_not_crawled' alone is a SOFT blocker.  It means Tavily
    fetched search results but the crawl step couldn't extract full text (e.g.
    Metaculus blocks headless crawlers).  The search still ran and SDV is
    meaningful, so we should not override a HOLD recommendation just because
    crawling failed.  Only escalate to hard when the search burst itself failed
    (no results returned at all).
    """
    hard: list[str] = []
    for blocker in blockers or []:
        text = str(blocker)
        # Only truly hard: search or extraction layer completely failed
        if text.startswith(("search_burst_failed:", "crawl_extract_failed:", "recursive_search_failed:")):
            hard.append(text)
        # crawl_error from specific URLs: only hard when no documents written at all
        # AND we also had a search_burst_failed (i.e. nothing worked)
        # — isolated crawl errors on individual URLs are soft.
    return hard


def _recommend(
    position: dict,
    sdv: float,
    disconf_found: bool,
    kc_covered: int,
    kc_total: int,
    days_to_expiry: float,
) -> tuple[str, str]:
    """Return (recommendation, reason) for a position.

    Order of checks (highest priority first):
      0a. TAKE_PROFIT: MTM ≥ TAKE_PROFIT_RATIO → close to lock gains
      0b. STOP_LOSS_REVIEW: MTM ≤ STOP_LOSS_RATIO and > STOP_LOSS_MIN_DAYS to go
      1.  EXIT_ADVERSE: SDV very low + disconfirming evidence
      2.  REVIEW_STALE: near expiry with low SDV
      3.  REVIEW_ADVERSE_KC/DISCONF: side-aware adverse evidence
      4.  HOLD (default)
    """
    side = position.get("intended_side", "")
    entry_price = _entry_side_price(position)
    signal_confidence = position.get("signal_confidence") or 0.5

    # ── 0. MTM-based take-profit / stop-loss (live CLOB) ─────────────────────
    current_yes = _current_market_price(position["condition_id"])
    if current_yes is not None:
        ratio = _mtm_ratio(side, entry_price, current_yes)
        if ratio >= TAKE_PROFIT_RATIO:
            return "TAKE_PROFIT", (
                f"MTM ratio {ratio:.2f}× entry ({side} @${entry_price:.3f} → "
                f"live YES={current_yes:.3f}). Lock gains, do not wait for resolution."
            )
        if ratio <= STOP_LOSS_RATIO and days_to_expiry > STOP_LOSS_MIN_DAYS:
            return "STOP_LOSS_REVIEW", (
                f"MTM ratio {ratio:.2f}× entry — adverse drawdown with {days_to_expiry:.1f}d "
                f"remaining. Review thesis before further loss."
            )

    # 1. Adverse evidence: SDV very low + disconfirming found
    if sdv < SDV_EXIT_ADVERSE_THRESHOLD and disconf_found:
        return "EXIT_ADVERSE", (
            f"SDV={sdv:.2f} (below {SDV_EXIT_ADVERSE_THRESHOLD}) "
            f"AND disconfirming evidence found. Thesis may be broken."
        )

    # 2. Stale near expiry: within EXPIRY_STALE_DAYS with low SDV
    if days_to_expiry <= EXPIRY_STALE_DAYS and sdv < 0.35:
        return "REVIEW_STALE", (
            f"{days_to_expiry:.1f}d to expiry, SDV={sdv:.2f}. "
            f"No strong evidence to update thesis."
        )

    # 3. Strong NO evidence for a YES position (or vice versa)
    kc_coverage_ratio = kc_covered / max(kc_total, 1)
    if side == "YES" and kc_coverage_ratio >= 0.67 and disconf_found:
        return "REVIEW_ADVERSE_KC", (
            f"YES position: {kc_covered}/{kc_total} kill criteria covered, "
            f"disconf evidence found. Consider exit."
        )
    if side == "NO" and sdv >= 0.65 and disconf_found:
        return "REVIEW_ADVERSE_DISCONF", (
            f"NO position: high SDV={sdv:.2f} with disconf evidence "
            f"suggests unexpected YES momentum."
        )

    # 4. Default: hold
    kc_str = f"{kc_covered}/{kc_total}" if kc_total else "n/a"
    return "HOLD", (
        f"SDV={sdv:.2f} | kc={kc_str} | disconf={disconf_found} "
        f"| {days_to_expiry:.1f}d remaining. Thesis intact."
    )


def monitor_position(position: dict, forager: ForagerService) -> dict:
    cid_short = position["condition_id"][:16]
    question = (position.get("question") or "")[:60]
    side = position.get("intended_side", "")
    dte = position.get("days_to_expiry", "?")

    print(f"\n  [{side}] {question}")
    print(f"  CID={cid_short} | entry={_entry_side_price(position):.3f} | {dte}d to expiry")

    if isinstance(dte, (int, float)) and dte < 0:
        recommendation = "RESOLUTION_DUE"
        reason = (
            f"{dte:.1f}d past expiry. Do not run fresh thesis monitoring; "
            "send this market through Command E / resolution repair."
        )
        print(f"  => {recommendation}: {reason}")
        return {
            "position_id": position["position_id"],
            "condition_id": position["condition_id"],
            "question": question,
            "side": side,
            "days_to_expiry": dte,
            "sdv": 0.0,
            "disconf_found": False,
            "kc_covered": 0,
            "kc_total": 0,
            "recommendation": recommendation,
            "reason": reason,
            "thread_id": None,
            "packet_id": None,
            "blockers": [],
            "documents_written": 0,
            "hard_blockers": [],
            "kill_criteria_triggered": [],
            "ollama_monitoring": None,
        }

    request = _build_monitor_request(position)
    try:
        result = forager.run_core_research_loop(request)
    except Exception as exc:
        return {
            "position_id": position["position_id"],
            "condition_id": position["condition_id"],
            "recommendation": "REVIEW_FORAGER_ERROR",
            "reason": f"Forager monitoring failed; cannot honestly mark HOLD: {exc}",
            "sdv": 0.0,
            "error": str(exc),
        }

    packet = None
    if result.packet_id:
        packet = forager.store.latest_packet_for_thread(result.thread_id)
    packet_data = _packet_dict(packet)

    sdv = packet_data.get("signal_decision_value", 0) if packet_data else 0.0
    disconf_found = packet_data.get("disconfirming_found", False) if packet_data else False
    kc_step = next((s for s in result.steps if s.get("step") == "kill_criteria_search"), {})
    kc_covered = kc_step.get("criteria_covered", 0)
    kc_total = kc_step.get("criteria_total", 0)
    documents_written = _documents_written(result)
    hard_blockers = _hard_monitor_blockers(result.blockers, documents_written)

    recommendation, reason = _recommend(
        position, sdv, disconf_found, kc_covered, kc_total, dte
    )
    if recommendation == "HOLD" and hard_blockers:
        recommendation = "REVIEW_STALE_DATA"
        reason = (
            "Monitoring produced blockers, so HOLD would be misleading: "
            + ", ".join(str(b) for b in hard_blockers[:4])
        )
    ollama_monitoring = monitoring_draft(position, packet_data)
    if ollama_monitoring:
        advisory = str(ollama_monitoring.get("advisory_recommendation") or "").upper()
        advisory_reason = str(ollama_monitoring.get("reason") or "").strip()
        if advisory in {"REVIEW", "EXIT"} and recommendation == "HOLD":
            recommendation = f"REVIEW_OLLAMA_{advisory}"
            reason = advisory_reason or "Local Ollama monitoring draft flagged this position for review."

    print(f"  => SDV={sdv:.2f} | kc={kc_covered}/{kc_total} | disconf={disconf_found}")
    print(f"  => {recommendation}: {reason}")

    # ── Kill criteria watchdog ───────────────────────────────────────────────
    # For each stored kill criterion, run a targeted shallow Forager search.
    # If any criterion surfaces SDV > 0.60, escalate to REVIEW and toast.
    kill_criteria = _get_position_kill_criteria(position["condition_id"])
    triggered_criteria: list[str] = []
    if kill_criteria:
        print(f"  [watchdog] Checking {len(kill_criteria)} kill criteria...")
        for criterion in kill_criteria[:3]:  # cap at 3 to limit API calls
            try:
                kc_request = CoreResearchLoopRequest(
                    seed_query=criterion[:200],
                    market_id=position["condition_id"],
                    depth=DepthMode.SHALLOW,
                    recursive_rounds=1,
                    max_queries_per_round=2,
                    results_per_query=3,
                    max_sources_per_round=3,
                    include_local_language=False,
                    execute_translations=False,
                    run_semantic_graph=False,
                    build_evidence_drafts=False,
                    require_disconfirming_evidence=False,
                    kill_criteria=[criterion],
                )
                kc_result = forager.run_core_research_loop(kc_request)
                kc_packet = None
                if kc_result.packet_id:
                    kc_packet = forager.store.latest_packet_for_thread(kc_result.thread_id)
                kc_packet_data = _packet_dict(kc_packet)
                kc_sdv = kc_packet_data.get("signal_decision_value", 0) if kc_packet_data else 0.0
                if kc_sdv > 0.60:
                    triggered_criteria.append(criterion[:80])
                    print(f"  [watchdog] TRIGGERED: SDV={kc_sdv:.2f} | '{criterion[:60]}'")
            except Exception as exc:  # noqa: BLE001
                print(f"  [watchdog] error for criterion: {exc}")

    if triggered_criteria:
        recommendation = "REVIEW_KILL_CRITERION"
        reason = f"Kill criterion triggered (SDV>0.60): {triggered_criteria[0][:80]}"
        print(f"  !! KILL CRITERION TRIGGERED: {reason}")
        _send_toast(
            title=f"Signal: Kill criterion hit",
            message=f"{question[:50]}\n{triggered_criteria[0][:100]}",
        )

    # ── Toast for adverse exits ──────────────────────────────────────────────
    if "EXIT" in recommendation:
        _send_toast(
            title="Signal: EXIT signal",
            message=f"[{side}] {question[:60]}\n{reason[:120]}",
        )

    return {
        "position_id": position["position_id"],
        "condition_id": position["condition_id"],
        "question": question,
        "side": side,
        "days_to_expiry": dte,
        "sdv": sdv,
        "disconf_found": disconf_found,
        "kc_covered": kc_covered,
        "kc_total": kc_total,
        "recommendation": recommendation,
        "reason": reason,
        "thread_id": result.thread_id,
        "packet_id": result.packet_id,
        "blockers": result.blockers,
        "documents_written": documents_written,
        "hard_blockers": hard_blockers,
        "kill_criteria_triggered": triggered_criteria,
        "ollama_monitoring": ollama_monitoring,
    }


def main():
    print("=== COMMAND F: Forager Position Monitor ===\n")
    print(f"Monitoring horizon: {MONITOR_HORIZON_DAYS} days")

    # ── Phase 0: MTM scan across ALL open positions (catches long-dated stops) ──
    mtm_alerts = _mtm_scan_all_positions()

    forager = ForagerService(store=_make_store())

    positions = _load_open_positions(MONITOR_HORIZON_DAYS)
    print(f"\nOpen paper positions within {MONITOR_HORIZON_DAYS}d horizon: {len(positions)}\n")

    if not positions:
        print("No positions require Forager monitoring. Done.")
        if mtm_alerts:
            print(f"\n!! {len(mtm_alerts)} MTM alert(s) require attention (see above).")
        return [], None

    # Prioritize: soonest expiry first, then by stake size
    positions.sort(key=lambda p: (p["days_to_expiry"], -p["intended_stake_usd"]))

    wf_id = _start_workflow_log(
        "forager_position_monitor",
        "Forager position monitoring",
        input_payload={"position_count": len(positions), "horizon_days": MONITOR_HORIZON_DAYS},
        agent_name="claude-code",
        notes="Command F daily monitoring run",
    )
    print(f"Workflow run ID: {wf_id}\n")

    results = []
    for pos in positions:
        r = monitor_position(pos, forager)
        results.append(r)

        _record_workflow_step(
            wf_id,
            f"monitor_{pos['condition_id'][:8]}",
            allowed_writes=["forager_threads", "forager_packets"],
            writes_count=1,
            output_json={
                "position_id": r["position_id"],
                "condition_id": r["condition_id"],
                "recommendation": r["recommendation"],
                "sdv": r.get("sdv", 0),
            },
        )

    _finish_workflow_log(wf_id, status="completed", output_json={"positions_monitored": len(results)})

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n=== COMMAND F SUMMARY ===")
    take_profits = [r for r in results if "TAKE_PROFIT" in r["recommendation"]]
    stop_losses = [r for r in results if "STOP_LOSS" in r["recommendation"]]
    exits_adverse = [r for r in results if "EXIT" in r["recommendation"]]
    reviews = [r for r in results if "REVIEW" in r["recommendation"]]
    holds = [r for r in results if r["recommendation"] == "HOLD"]

    print(f"TAKE_PROFIT : {len(take_profits)}")
    print(f"STOP_LOSS   : {len(stop_losses)}")
    print(f"HOLD        : {len(holds)}")
    print(f"REVIEW      : {len(reviews)}")
    print(f"EXIT        : {len(exits_adverse)}")

    if take_profits:
        print("\n$$ TAKE PROFIT SIGNALS:")
        for r in take_profits:
            print(f"  [{r['side']}] {r.get('question', r['condition_id'][:20])} | {r['reason']}")

    if stop_losses:
        print("\n!! STOP LOSS SIGNALS:")
        for r in stop_losses:
            print(f"  [{r['side']}] {r.get('question', r['condition_id'][:20])} | {r['reason']}")

    if exits_adverse:
        print("\n!! ADVERSE EXIT SIGNALS:")
        for r in exits_adverse:
            print(f"  [{r['side']}] {r.get('question', r['condition_id'][:20])} | {r['reason']}")

    if reviews:
        print("\n! REVIEW REQUIRED:")
        for r in reviews:
            print(f"  [{r['side']}] {r.get('question', r['condition_id'][:20])} | {r['reason']}")

    if mtm_alerts:
        print(f"\n[MTM ALL-POSITIONS SCAN] {len(mtm_alerts)} alert(s):")
        for a in mtm_alerts:
            print(f"  [{a['signal']}] #{a['position_id']} {a['question'][:55]} | MTM={a['mtm_ratio']:.2f}x | {a['days_to_expiry']:.0f}d")

    print(f"\nWorkflow run: {wf_id}")
    return results, wf_id


if __name__ == "__main__":
    results, wf_id = main()
    out_path = os.path.join(os.path.dirname(__file__), "monitor_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            [{k: v for k, v in r.items() if k not in ("packet",)} for r in results],
            f,
            indent=2,
            default=str,
        )
    print(f"\nResults saved to {out_path}")
