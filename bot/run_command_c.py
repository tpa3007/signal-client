"""Command C — Aladdin Signal Commit (paper only).

Runs validate_signal_gate then commits paper signal + position + fill for
any market that passed Signal L2 with decision='approved_for_signal'.

Auto-reads dossier_results.json written by Command D. Fails closed if the file
is missing or has no approved markets.

Restricted: paper_only=True always. Real money is never executed here.
"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")

import db; db.init()
from datetime import datetime, timezone
import httpx
from tools.workflows import _start_workflow_log, _record_workflow_step, _finish_workflow_log
from lib.gates import validate_signal_gate
from lib.ledger_meta import approval_strength as _approval_strength
from markets import _execution_prices


def _load_approved() -> list[dict]:
    """Load approved markets from dossier_results.json (written by Command D).

    Run Command D first to populate it. Missing or empty approvals fail closed.
    """
    dossier_path = os.path.join(os.path.dirname(__file__), "dossier_results.json")
    if os.path.exists(dossier_path):
        try:
            with open(dossier_path, encoding="utf-8") as f:
                data = json.load(f)
            approved = data.get("approved", [])
            if approved:
                print(f"[Command C] Loaded {len(approved)} approved markets from dossier_results.json")
                return approved
            else:
                print("[Command C] dossier_results.json exists but has 0 approved markets.")
                print("  Run Command D to build dossiers and get approvals.")
        except Exception as exc:
            print(f"[Command C] WARNING: could not load dossier_results.json: {exc}")
    else:
        print("[Command C] dossier_results.json not found. Run Command D first.")
    return []

APPROVED = _load_approved()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _float_or_none(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _refresh_live_snapshot(conn, condition_id: str) -> dict:
    """Fetch a live Gamma snapshot before the final gate.

    Command D can approve on a snapshot that becomes stale by the time Command C
    runs. C is the final fail-closed layer, so it refreshes the executable price
    itself instead of asking the operator to run a separate maintenance step.
    """
    try:
        r = httpx.get(
            "https://gamma-api.polymarket.com/markets",
            params={"condition_ids": condition_id},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        if not items:
            return {"ok": False, "error": "market_not_found"}
        m = items[0]
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if not prices or len(prices) < 2:
            return {"ok": False, "error": "missing_outcome_prices"}
        yes_price = float(prices[0])
        no_price = float(prices[1])
        best_bid = _float_or_none(m.get("bestBid"))
        best_ask = _float_or_none(m.get("bestAsk"))
        spread = _float_or_none(m.get("spread"))
        yes_entry, no_entry, spread = _execution_prices(
            yes_price, no_price, best_bid, best_ask, spread
        )
        db.add_snapshot(
            conn,
            condition_id=condition_id,
            yes_price=yes_price,
            no_price=no_price,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            yes_entry_price=yes_entry,
            no_entry_price=no_entry,
            volume=_float_or_none(m.get("volumeNum") or m.get("volume")),
            liquidity=_float_or_none(m.get("liquidityNum") or m.get("liquidity")),
            source="command_c_live_refresh",
        )
        conn.commit()
        return {
            "ok": True,
            "yes_price": yes_price,
            "no_price": no_price,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "yes_entry_price": yes_entry,
            "no_entry_price": no_entry,
            "spread": spread,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _existing_open_position(conn, condition_id: str, side: str) -> dict | None:
    row = conn.execute(
        """
        SELECT id, signal_id, opened_at, side_entry_price, yes_equivalent_entry
        FROM positions
        WHERE condition_id = ?
          AND intended_side = ?
          AND status IN ('open', 'pending')
        ORDER BY opened_at DESC, id DESC
        LIMIT 1
        """,
        (condition_id, side),
    ).fetchone()
    return dict(row) if row else None


def _operator_handoff_blockers(candidate: dict) -> list[str]:
    """Command C is paper-only, but it still must not formalize weak automation."""
    required = {
        "operator_approved": "operator_approved",
        "operator_probability": "operator_probability",
        "market_mechanics_verified": "market_mechanics_verified",
        "operator_reject_reasons_checked": "operator_reject_reasons_checked",
        "disconfirming_evidence_checked": "disconfirming_evidence_checked",
        "cluster_exposure_checked": "cluster_exposure_checked",
    }
    blockers: list[str] = []
    for field, label in required.items():
        value = candidate.get(field)
        if field == "operator_probability":
            try:
                if value is None or not (0.0 <= float(value) <= 1.0):
                    blockers.append(label)
            except (TypeError, ValueError):
                blockers.append(label)
        elif value is not True:
            blockers.append(label)
    if candidate.get("primary_archetype") == "cross_platform_divergence" and candidate.get("resolution_equivalence_checked") is not True:
        blockers.append("resolution_equivalence_checked")
    return blockers


def run_signal_commit(candidate: dict) -> dict:
    cid = candidate["condition_id"]
    print(f"\n  Processing: {candidate['question'][:60]}")
    print(f"  Side={candidate['side']} | prob={candidate['probability_yes']} | conf={candidate['confidence']}")

    wf_id = _start_workflow_log(
        "aladdin_signal_commit",
        "L3 signal commit",
        input_payload={
            "condition_id": cid,
            "side": candidate["side"],
            "probability_yes": candidate["probability_yes"],
            "confidence": candidate["confidence"],
            "paper_only": True,
            "dry_run": False,
            "l2_wf_id": candidate["l2_wf_id"],
        },
        agent_name="claude-code",
        notes="Command C — paper signal after L2 approved_for_signal.",
    )

    handoff_blockers = _operator_handoff_blockers(candidate)
    if handoff_blockers:
        blocker = "missing_operator_handoff: " + ", ".join(handoff_blockers)
        print(f"  BLOCKED: {blocker}")
        _record_workflow_step(
            wf_id,
            "operator_handoff_gate",
            status="blocked",
            condition_id=cid,
            allowed_writes=[],
            blocker=blocker,
            output_json={"missing": handoff_blockers},
        )
        _finish_workflow_log(wf_id, status="blocked", output_json={"blocker": blocker})
        return {
            "workflow_run_id": wf_id,
            "gate_passed": False,
            "signal_created": False,
            "blocked_reason": blocker,
        }

    with db.connect() as conn:
        refresh = _refresh_live_snapshot(conn, cid)
        if refresh.get("ok"):
            print(
                "  Live snapshot refreshed: "
                f"yes={refresh['yes_price']:.4f} "
                f"yes_entry={refresh['yes_entry_price']:.4f} "
                f"no_entry={refresh['no_entry_price']:.4f}"
            )
        else:
            print(f"  Live snapshot refresh failed: {refresh.get('error')}")
            blocker = (
                "live_snapshot_refresh_failed: "
                f"{refresh.get('error')}; rerun Command C with network access or "
                "refresh the market snapshot before committing."
            )
            _record_workflow_step(
                wf_id,
                "live_snapshot_refresh",
                status="blocked",
                condition_id=cid,
                allowed_writes=[],
                blocker=blocker,
                output_json={"live_refresh": refresh},
            )
            _finish_workflow_log(wf_id, status="blocked", output_json={"blocker": blocker})
            return {
                "workflow_run_id": wf_id,
                "gate_passed": False,
                "signal_created": False,
                "blocked_reason": blocker,
            }
        gate = validate_signal_gate(
            conn,
            condition_id=cid,
            probability_yes=candidate["probability_yes"],
            confidence=candidate["confidence"],
            intended_side=candidate["side"],
            primary_archetype=candidate.get("primary_archetype"),
        )
        print(f"  Gate: ok={gate['ok']} | edge={gate.get('executable_edge')} | "
              f"side={gate.get('side')} | blockers={gate['blockers']}")

    _record_workflow_step(
        wf_id,
        "validate_signal_gate",
        status="completed" if gate["ok"] else "blocked",
        condition_id=cid,
        allowed_writes=[],
        blocker=", ".join(gate.get("blockers") or []) if not gate["ok"] else None,
        output_json={
            "ok": gate["ok"],
            "blockers": gate.get("blockers"),
            "side": gate.get("side"),
            "edge": gate.get("executable_edge"),
            "stake": gate.get("proposed_stake_usd"),
            "live_refresh": refresh,
        },
    )

    if not gate["ok"]:
        _finish_workflow_log(wf_id, status="blocked", output_json={"gate": gate})
        return {
            "workflow_run_id": wf_id,
            "gate_passed": False,
            "signal_created": False,
            "blocked_reason": ", ".join(gate["blockers"]),
        }

    # Commit paper signal
    side_entry_price = float(gate.get("side_entry_price") or gate["yes_equivalent_entry"])
    yes_equivalent_entry = float(gate["yes_equivalent_entry"])
    with db.connect() as conn:
        existing = _existing_open_position(conn, cid, gate["side"])
        if existing:
            blocker = (
                f"duplicate_open_position: position_id={existing['id']} "
                f"signal_id={existing.get('signal_id')}"
            )
            print(f"  BLOCKED: {blocker}")
            _record_workflow_step(
                wf_id,
                "commit_paper_signal",
                status="blocked",
                condition_id=cid,
                allowed_writes=[],
                blocker=blocker,
                output_json={"existing_position": existing},
            )
            _finish_workflow_log(wf_id, status="blocked", output_json={"blocker": blocker})
            return {
                "workflow_run_id": wf_id,
                "gate_passed": True,
                "signal_created": False,
                "blocked_reason": blocker,
                "duplicate_position_id": existing["id"],
            }

        market = conn.execute(
            "SELECT vertical, end_date FROM markets WHERE condition_id = ?",
            (cid,),
        ).fetchone()

        signal_id = db.add_signal(
            conn,
            condition_id=cid,
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
            reasoning=candidate["reasoning"],
            sources_json=json.dumps(candidate.get("sources", [])),
            tokens_in=None,
            tokens_out=None,
            cache_read_tokens=None,
            cost_usd=0.0,
            gate_status="gated",
            gate_audit_note="Command C validate_signal_gate passed with operator handoff",
            primary_archetype=candidate.get("primary_archetype"),
            operator_approved=True,
            signal_generation_epoch="gated_v2_after_MR",
            confidence_source="operator_override",
            approval_strength=_approval_strength(
                edge=gate.get("executable_edge"),
                confidence=gate.get("confidence"),
                checklist_score=candidate.get("checklist_score"),
                operator_approved=True,
            ),
        )
        position_id = db.add_position(
            conn,
            condition_id=cid,
            signal_id=signal_id,
            opened_at=None,
            intended_side=gate["side"],
            intended_entry_price=side_entry_price,
            side_entry_price=side_entry_price,
            yes_equivalent_entry=yes_equivalent_entry,
            intended_stake_usd=float(gate["proposed_stake_usd"]),
            stake_source="paper",
            status="open",
            thesis_snapshot_text=candidate["reasoning"],
            primary_archetype=candidate.get("primary_archetype"),
            signal_generation_epoch="gated_v2_after_MR",
            confidence_source="operator_override",
            approval_strength=_approval_strength(
                edge=gate.get("executable_edge"),
                confidence=gate.get("confidence"),
                checklist_score=candidate.get("checklist_score"),
                operator_approved=True,
            ),
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
            condition_id=cid,
            created_at=None,
            analyst="aladdin-signal-commit",
            model="aladdin-signal-commit",
            yes_price_at_analysis=float(
                (gate["snapshot"] or {}).get("yes_price") or gate["yes_equivalent_entry"]
            ),
            probability_yes=float(gate["probability_yes"]),
            confidence=float(gate["confidence"]),
            edge=float(gate["executable_edge"]),
            decision="signal",
            no_signal_reason=None,
            signal_id=signal_id,
            reasoning=candidate["reasoning"],
            sources_json=json.dumps(candidate.get("sources", [])),
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
        wf_id,
        "commit_paper_signal",
        status="completed",
        condition_id=cid,
        allowed_writes=["analyses", "signals", "positions", "fills"],
        writes_count=4,
        output_json=commit_output,
    )
    _finish_workflow_log(wf_id, status="completed", output_json=commit_output)

    print(f"  Paper signal committed:")
    print(f"    signal_id={signal_id} | position_id={position_id} | fill_id={fill_id}")
    print(f"    side={gate['side']} | entry={side_entry_price:.4f} | "
          f"stake=${gate['proposed_stake_usd']:.2f} | shares={shares:.2f}")

    return {
        "workflow_run_id": wf_id,
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
        "shares": shares,
        "edge": gate["executable_edge"],
    }


def main():
    print("=== COMMAND C: Aladdin Signal Commit (paper only) ===\n")
    print(f"Approved markets from L2 (WF 21): {len(APPROVED)}\n")
    if not APPROVED:
        print("FAIL CLOSED: no approved markets loaded. Run Command D first.")
        return

    results = []
    for candidate in APPROVED:
        result = run_signal_commit(candidate)
        results.append(result)

    print("\n=== COMMAND C SUMMARY ===")
    for r, c in zip(results, APPROVED):
        if r["signal_created"]:
            print(f"  [SIGNAL CREATED] {c['question'][:55]}")
            print(f"    signal_id={r['signal_id']} | side={r['side']} | "
                  f"stake=${r['stake_usd']:.2f} | edge={r['edge']:.4f}")
        else:
            print(f"  [BLOCKED] {c['question'][:55]}")
            print(f"    reason={r['blocked_reason']}")

    signals_created = sum(1 for r in results if r["signal_created"])
    print(f"\nTotal paper signals created: {signals_created}")
    if signals_created:
        print("Command F (monitoring) should be configured for open positions.")

    return results


if __name__ == "__main__":
    main()
