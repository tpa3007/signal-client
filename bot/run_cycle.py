"""End-to-end Signal cycle runner and auditor.

This runner is intentionally conservative. It does not try to make the system
"fully automatic"; it makes the manual/strong-LLM cycle observable:

    G -> G2 -> M -> R -> B -> D -> C -> F

Each step is checked for required artifacts before the next step can run. The
cycle writes one markdown and one JSON report so operator time goes to the real
question: where did the candidate quality degrade?
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable


@dataclass(frozen=True)
class StepSpec:
    key: str
    label: str
    command: list[str]
    required_before: tuple[str, ...] = ()
    expected_after: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    optional: bool = False


STEPS: tuple[StepSpec, ...] = (
    StepSpec(
        key="G",
        label="Universe scan",
        command=[PYTHON, "run_command_g.py"],
        expected_after=("candidates_wide.json", "triage_report.json", "g_scan_queue.py"),
    ),
    StepSpec(
        key="G2",
        label="Hidden-gem ranker",
        command=[PYTHON, "run_command_g2.py"],
        required_before=("candidates_wide.json",),
        expected_after=("g2_top25.json", "forager_queue_auto.py"),
    ),
    StepSpec(
        key="M",
        label="Manual shortlist desk",
        command=[PYTHON, "run_command_m.py"],
        required_before=("g2_top25.json",),
        expected_after=("manual_shortlist_queue.py", "manual_shortlist_report.md"),
    ),
    StepSpec(
        key="R",
        label="Reasoning memo gate",
        command=[PYTHON, "run_command_r.py"],
        required_before=("manual_shortlist_queue.py",),
        expected_after=("forager_queue_reasoned.py", "reasoning_memos.json", "reasoning_memos.md"),
        env={"FORAGER_QUEUE_PATH": "manual_shortlist_queue.py"},
    ),
    StepSpec(
        key="B",
        label="Forager research",
        command=[PYTHON, "run_command_b.py"],
        required_before=("forager_queue_reasoned.py",),
        expected_after=("forager_results.json",),
        env={"FORAGER_QUEUE_PATH": "forager_queue_reasoned.py"},
    ),
    StepSpec(
        key="D",
        label="Signal L2 dossier gate",
        command=[PYTHON, "run_command_d.py"],
        required_before=("forager_results.json", "forager_queue_reasoned.py"),
        expected_after=("dossier_results.json",),
        env={"FORAGER_QUEUE_PATH": "forager_queue_reasoned.py"},
    ),
    StepSpec(
        key="C",
        label="Paper signal commit",
        command=[PYTHON, "run_command_c.py"],
        required_before=("dossier_results.json",),
        optional=True,
    ),
    StepSpec(
        key="F",
        label="Position monitor",
        command=[PYTHON, "run_command_f.py"],
        optional=True,
        expected_after=("monitor_results.json",),
    ),
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _artifact(path: str) -> Path:
    return ROOT / path


def _exists_all(paths: tuple[str, ...]) -> list[str]:
    return [p for p in paths if not _artifact(p).exists()]


def _slice_steps(start: str, end: str) -> list[StepSpec]:
    keys = [s.key for s in STEPS]
    if start not in keys:
        raise ValueError(f"Unknown --from step {start!r}; valid: {', '.join(keys)}")
    if end not in keys:
        raise ValueError(f"Unknown --to step {end!r}; valid: {', '.join(keys)}")
    i = keys.index(start)
    j = keys.index(end)
    if i > j:
        raise ValueError("--from must be before --to")
    return list(STEPS[i : j + 1])


def _count_candidates(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        if isinstance(payload.get("candidates"), list):
            return len(payload["candidates"])
        if isinstance(payload.get("approved"), list):
            return len(payload["approved"])
        if isinstance(payload.get("results"), list):
            return len(payload["results"])
    return 0


def _load_python_queue(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "forager_queue" in names or "CANDIDATES" in names:
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                return []
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _memo_count(memos: Any) -> int:
    if isinstance(memos, list):
        return len(memos)
    if isinstance(memos, dict):
        if isinstance(memos.get("memos"), list):
            return len(memos["memos"])
        if isinstance(memos.get("total_candidates"), int):
            return int(memos["total_candidates"])
    return _count_candidates(memos)


def audit_artifacts(active_steps: set[str] | None = None) -> dict[str, Any]:
    active_steps = active_steps or {step.key for step in STEPS}
    wide = _read_json(ROOT / "candidates_wide.json") or {}
    g2 = _read_json(ROOT / "g2_top25.json") or {}
    memos = _read_json(ROOT / "reasoning_memos.json") or []
    forager = _read_json(ROOT / "forager_results.json") or []
    dossier = _read_json(ROOT / "dossier_results.json") or {}
    monitor = _read_json(ROOT / "monitor_results.json") or []
    reasoned_queue = _load_python_queue(ROOT / "forager_queue_reasoned.py")

    fetch_audit = wide.get("market_fetch_audit") if isinstance(wide, dict) else []
    market_raw = 0
    market_accepted = 0
    if isinstance(fetch_audit, list):
        for item in fetch_audit:
            if not isinstance(item, dict):
                continue
            stats = item.get("filter_stats") if isinstance(item.get("filter_stats"), dict) else {}
            market_raw += int(item.get("raw_rows") or stats.get("raw") or 0)
            market_accepted += int(item.get("new_unique_rows") or item.get("accepted_rows") or stats.get("accepted") or 0)
    candidate_universe_total = int(wide.get("candidate_universe_total") or 0) if isinstance(wide, dict) else 0

    dossier_results = dossier.get("results") if isinstance(dossier, dict) else []
    if not isinstance(dossier_results, list):
        dossier_results = []
    gate_counts: dict[str, int] = {}
    for row in dossier_results:
        decision = ((row or {}).get("gate") or {}).get("decision") or "unknown"
        gate_counts[decision] = gate_counts.get(decision, 0) + 1

    stale_holds = [
        row for row in monitor
        if isinstance(row, dict)
        and row.get("recommendation") == "HOLD"
        and (row.get("hard_blockers") or ("documents_not_crawled" in (row.get("blockers") or [])))
    ] if isinstance(monitor, list) else []
    operator_review_complete = [
        c for c in reasoned_queue
        if (c.get("operator_review") or {}).get("operator_probability") is not None
        and str((c.get("operator_review") or {}).get("decisive_fact_status") or "").lower() != "unverified"
    ]
    operator_ready = [
        c for c in reasoned_queue
        if (c.get("operator_review") or {}).get("approved_for_d")
        and (c.get("operator_review") or {}).get("operator_probability") is not None
    ]

    return {
        "market_fetch_passes": fetch_audit,
        "market_scope_raw_sum": market_raw,
        "market_scope_accepted_sum": market_accepted,
        "candidate_universe_total": candidate_universe_total,
        "wide_candidates": _count_candidates(wide),
        "g2_shortlist": _count_candidates(g2),
        "reasoning_memos": _memo_count(memos),
        "forager_results": _count_candidates(forager),
        "dossier_gate_counts": gate_counts,
        "approved_for_c": _count_candidates(dossier),
        "monitor_results": len(monitor) if isinstance(monitor, list) else 0,
        "monitor_stale_holds": len(stale_holds),
        "reasoned_queue": len(reasoned_queue),
        "operator_review_complete": len(operator_review_complete),
        "operator_ready_for_d": len(operator_ready),
        "warnings": _audit_warnings(
            wide,
            g2,
            memos,
            forager,
            dossier,
            monitor,
            market_raw,
            market_accepted,
            candidate_universe_total,
            stale_holds,
            reasoned_queue,
            operator_review_complete,
            operator_ready,
            active_steps,
        ),
    }


def _audit_warnings(
    wide: Any,
    g2: Any,
    memos: Any,
    forager: Any,
    dossier: Any,
    monitor: Any,
    market_raw: int,
    market_accepted: int,
    candidate_universe_total: int,
    stale_holds: list[dict[str, Any]],
    reasoned_queue: list[dict[str, Any]],
    operator_review_complete: list[dict[str, Any]],
    operator_ready: list[dict[str, Any]],
    active_steps: set[str],
) -> list[str]:
    warnings: list[str] = []
    wide_n = _count_candidates(wide)
    g2_n = _count_candidates(g2)
    memo_n = len(memos) if isinstance(memos, list) else _count_candidates(memos)
    forager_n = _count_candidates(forager)
    approved_n = _count_candidates(dossier)

    if market_raw and market_raw < 10000:
        warnings.append(f"Command G raw API coverage looks low: {market_raw} rows scanned, target is closer to 10k+.")
    if candidate_universe_total and candidate_universe_total < 2000:
        warnings.append(
            f"Command G filtered candidate universe is thin: {candidate_universe_total}; filters may be too aggressive."
        )
    elif market_accepted and market_accepted < 2000:
        warnings.append(f"Command G accepted scope is thin after filters: {market_accepted}; inspect skip/filter stats.")
    if wide_n and wide_n < 200:
        warnings.append(f"Command G wide pool is thin: {wide_n} candidates; target is 200-300.")
    if g2_n and g2_n < 10:
        warnings.append(f"Command G2 shortlist is thin: {g2_n}; expected 10-25 for operator review.")
    if memo_n and forager_n and forager_n < memo_n:
        warnings.append(f"Command B researched fewer items ({forager_n}) than Command R memos ({memo_n}).")
    if forager_n and approved_n == 0:
        warnings.append("Command D approved 0 candidates after Forager research; inspect gate reasons before assuming no edge exists.")
    if reasoned_queue and len(operator_review_complete) < len(reasoned_queue):
        warnings.append(
            f"Operator review incomplete: {len(operator_review_complete)}/{len(reasoned_queue)} reasoned candidates have an operator probability and decisive status."
        )
    if "C" in active_steps and reasoned_queue and not operator_ready:
        warnings.append(
            "Command C is in the requested path, but 0 reasoned candidates are operator-ready for D; keep the cycle in no-commit mode."
        )
    if stale_holds:
        warnings.append(f"Command F has {len(stale_holds)} HOLD rows with hard blockers; HOLD should mean freshly checked, not stale.")
    if "F" in active_steps and isinstance(monitor, list):
        reviews = [r for r in monitor if isinstance(r, dict) and "REVIEW" in str(r.get("recommendation", ""))]
        exits = [r for r in monitor if isinstance(r, dict) and "EXIT" in str(r.get("recommendation", ""))]
        if reviews or exits:
            warnings.append(f"Command F attention required: {len(reviews)} review, {len(exits)} exit-like recommendations.")
    if isinstance(wide, dict) and isinstance(wide.get("market_fetch_audit"), list):
        for item in wide["market_fetch_audit"]:
            if not isinstance(item, dict):
                continue
            stats = item.get("filter_stats") if isinstance(item.get("filter_stats"), dict) else {}
            raw = int(stats.get("raw") or item.get("requested_rows") or 0)
            if not raw:
                continue
            accepted = int(item.get("accepted_rows") or stats.get("accepted") or 0)
            new_unique = int(item.get("new_unique_rows") or accepted)
            pass_name = str(item.get("pass") or "scan")
            for key, label in (
                ("date_window", "date window"),
                ("volume", "volume floor"),
                ("price_extreme", "price window"),
            ):
                count = int(stats.get(key) or 0)
                if pass_name == "liquidity_asc" and key == "volume" and (accepted >= 1000 or new_unique >= 500):
                    continue
                if count / raw >= 0.25:
                    warnings.append(
                        f"Command G {pass_name} filter is heavy: {label} removed {count}/{raw} rows."
                    )
    return warnings


def _run_step(step: StepSpec, dry_run: bool) -> dict[str, Any]:
    missing = _exists_all(step.required_before)
    if missing:
        return {
            "step": step.key,
            "label": step.label,
            "status": "blocked",
            "reason": f"missing required artifact(s): {', '.join(missing)}",
        }

    if dry_run:
        return {
            "step": step.key,
            "label": step.label,
            "status": "dry_run",
            "command": step.command,
            "env": step.env or {},
        }

    env = os.environ.copy()
    env.update(step.env or {})
    started = datetime.now(timezone.utc)
    proc = subprocess.run(
        step.command,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    completed = datetime.now(timezone.utc)
    missing_after = _exists_all(step.expected_after)
    stale_after = []
    for rel in step.expected_after:
        path = _artifact(rel)
        if path.exists() and path.stat().st_mtime < started.timestamp():
            stale_after.append(rel)
    status = "completed" if proc.returncode == 0 and not missing_after and not stale_after else "failed"
    return {
        "step": step.key,
        "label": step.label,
        "status": status,
        "returncode": proc.returncode,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "missing_after": missing_after,
        "stale_after": stale_after,
        "stdout_tail": proc.stdout[-5000:],
        "stderr_tail": proc.stderr[-5000:],
    }


def write_cycle_report(cycle_id: str, step_results: list[dict[str, Any]], audit: dict[str, Any]) -> tuple[Path, Path]:
    json_path = ROOT / f"cycle_report_{cycle_id}.json"
    md_path = ROOT / f"cycle_report_{cycle_id}.md"
    payload = {
        "cycle_id": cycle_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "steps": step_results,
        "audit": audit,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Signal Cycle Report — {cycle_id}",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Step Results",
        "",
    ]
    for row in step_results:
        lines.append(f"- **{row['step']} / {row['label']}**: `{row['status']}`")
        if row.get("reason"):
            lines.append(f"  - Reason: {row['reason']}")
        if row.get("missing_after"):
            lines.append(f"  - Missing after run: `{', '.join(row['missing_after'])}`")
        if row.get("stale_after"):
            lines.append(f"  - Stale after run: `{', '.join(row['stale_after'])}`")
    lines.extend([
        "",
        "## Artifact Audit",
        "",
        f"- Market raw rows scanned: `{audit['market_scope_raw_sum']}`",
        f"- Market accepted/new rows: `{audit['market_scope_accepted_sum']}`",
        f"- Candidate universe total: `{audit['candidate_universe_total']}`",
        f"- Wide candidates: `{audit['wide_candidates']}`",
        f"- G2 shortlist: `{audit['g2_shortlist']}`",
        f"- Reasoning memos: `{audit['reasoning_memos']}`",
        f"- Forager results: `{audit['forager_results']}`",
        f"- D approved for C: `{audit['approved_for_c']}`",
        f"- Monitor results: `{audit['monitor_results']}`",
        f"- Reasoned queue: `{audit['reasoned_queue']}`",
        f"- Operator review complete: `{audit['operator_review_complete']}`",
        f"- Operator-ready for D: `{audit['operator_ready_for_d']}`",
        "",
        "## D Gate Counts",
        "",
    ])
    for key, value in sorted((audit.get("dossier_gate_counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Warnings", ""])
    warnings = audit.get("warnings") or []
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No audit warnings.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run/audit the full Signal Command cycle.")
    parser.add_argument("--from", dest="start", default="G", help="First step key: G, G2, M, R, B, D, C, F")
    parser.add_argument("--to", dest="end", default="R", help="Last step key: G, G2, M, R, B, D, C, F")
    parser.add_argument(
        "--mode",
        choices=("operator_review_required", "scan_only", "research_only", "no_commit", "paper_commit_after_operator"),
        default="operator_review_required",
        help=(
            "Safety mode. Default stops at R so the operator layer judges before B/D/C. "
            "Use paper_commit_after_operator only when operator_review has been filled."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Only validate commands/artifacts; do not execute steps.")
    parser.add_argument("--skip-c", action="store_true", help="Skip Command C paper commit.")
    parser.add_argument("--skip-f", action="store_true", help="Skip Command F monitoring.")
    args = parser.parse_args()

    if args.mode == "scan_only":
        args.start, args.end = "G", "G2"
    elif args.mode == "research_only":
        if args.end.upper() in {"C", "F"}:
            args.end = "D"
    elif args.mode == "no_commit":
        if args.end.upper() in {"C", "F"}:
            args.end = "D"
    elif args.mode == "operator_review_required" and args.end.upper() in {"B", "D", "C", "F"}:
        print("[mode] operator_review_required: stopping at R. Use --mode research_only/no_commit/paper_commit_after_operator to continue.")
        args.end = "R"

    steps = _slice_steps(args.start.upper(), args.end.upper())
    if args.mode in {"research_only", "no_commit"}:
        steps = [s for s in steps if s.key != "C"]
    if args.skip_c:
        steps = [s for s in steps if s.key != "C"]
    if args.mode in {"operator_review_required", "scan_only", "research_only", "no_commit"}:
        steps = [s for s in steps if s.key != "F"]
    if args.skip_f:
        steps = [s for s in steps if s.key != "F"]

    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    print(f"=== SIGNAL CYCLE {cycle_id} ===")
    print(f"mode={args.mode}")
    print(" -> ".join(step.key for step in steps))
    print()

    results: list[dict[str, Any]] = []
    for step in steps:
        print(f"[{step.key}] {step.label}")
        result = _run_step(step, dry_run=args.dry_run)
        results.append(result)
        print(f"  {result['status']}")
        if result["status"] in {"blocked", "failed"}:
            print(f"  stopping fail-closed: {result.get('reason') or result.get('missing_after') or result.get('returncode')}")
            break

    audit = audit_artifacts({step.key for step in steps})
    json_path, md_path = write_cycle_report(cycle_id, results, audit)
    print(f"\nReport JSON: {json_path}")
    print(f"Report MD:   {md_path}")
    if audit.get("warnings"):
        print("\nWarnings:")
        for warning in audit["warnings"]:
            print(f"  - {warning}")
    return 1 if any(r["status"] in {"blocked", "failed"} for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
