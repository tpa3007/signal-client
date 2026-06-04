"""Command A runner: Signal -> Forager candidate intake.

Command G owns discovery. Command A now validates and lightly enriches the
auto-generated queue, using local Ollama drafts when fields are missing.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(".env")

import db; db.init()
from lib.ollama import candidate_research_draft
from tools.workflows import _record_workflow_step

WF_ID = 7
ROOT = Path(__file__).resolve().parent
AUTO_QUEUE_PATH = ROOT / "forager_queue_auto.py"
VALIDATED_JSON_PATH = ROOT / "forager_queue_validated.json"
MAX_QUEUE = int(__import__("os").getenv("SIGNAL_COMMAND_A_MAX_QUEUE", "0") or "0")


def _load_auto_queue() -> list[dict[str, Any]]:
    if not AUTO_QUEUE_PATH.exists():
        print(f"No auto queue found: {AUTO_QUEUE_PATH}")
        print("Run Command G first to discover candidates.")
        return []
    tree = ast.parse(AUTO_QUEUE_PATH.read_text(encoding="utf-8"), filename=str(AUTO_QUEUE_PATH))
    queue: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "forager_queue" in names:
                queue = ast.literal_eval(node.value)
                break
    return [dict(c) for c in queue if isinstance(c, dict)]


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fill_from_ollama(candidate: dict[str, Any]) -> None:
    missing = (
        not candidate.get("thesis")
        or len(candidate.get("kill_criteria") or []) < 3
        or not candidate.get("first_queries")
        or not candidate.get("why_signal_may_miss")
        or not candidate.get("disconfirming_angle")
    )
    if not missing:
        return
    draft = candidate_research_draft(candidate)
    if not draft:
        return
    candidate["ollama_draft"] = draft
    for key in ("thesis", "why_signal_may_miss", "disconfirming_angle", "local_language"):
        if not candidate.get(key) and isinstance(draft.get(key), str):
            candidate[key] = draft[key].strip()
    if len(candidate.get("kill_criteria") or []) < 3 and isinstance(draft.get("kill_criteria"), list):
        criteria = [str(x).strip() for x in draft["kill_criteria"] if str(x).strip()]
        if criteria:
            candidate["kill_criteria"] = criteria[:5]
    if not candidate.get("first_queries") and isinstance(draft.get("first_queries"), list):
        queries = [str(x).strip() for x in draft["first_queries"] if str(x).strip()]
        if queries:
            candidate["first_queries"] = queries[:5]
            candidate["seed_query"] = candidate.get("seed_query") or queries[0]


def _validate(candidate: dict[str, Any]) -> tuple[str, list[str]]:
    issues: list[str] = []
    required = ("priority", "condition_id", "question", "yes_price", "end_date")
    for key in required:
        if not candidate.get(key):
            issues.append(f"missing_{key}")
    yes = _as_float(candidate.get("yes_price"))
    no = _as_float(candidate.get("no_price"))
    if yes is None or not 0.0 < yes < 1.0:
        issues.append("bad_yes_price")
    if no is not None and not 0.0 < no < 1.0:
        issues.append("bad_no_price")
    if len(candidate.get("kill_criteria") or []) < 3:
        issues.append("too_few_kill_criteria")
    if not candidate.get("seed_query") and not candidate.get("first_queries"):
        issues.append("missing_seed_query")
    if not candidate.get("thesis"):
        issues.append("missing_thesis")
    if not candidate.get("disconfirming_angle"):
        issues.append("missing_disconfirming_angle")
    return ("ready" if not issues else "needs_review"), issues


def main() -> None:
    print("=== COMMAND A: Auto Queue Validation + Ollama Enrichment ===\n")
    queue = _load_auto_queue()
    if MAX_QUEUE > 0:
        queue = queue[:MAX_QUEUE]
    validated: list[dict[str, Any]] = []
    for candidate in queue:
        _fill_from_ollama(candidate)
        status, issues = _validate(candidate)
        candidate["validation_status"] = status
        candidate["validation_issues"] = issues
        validated.append(candidate)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(AUTO_QUEUE_PATH),
        "total_candidates": len(validated),
        "ready": sum(1 for c in validated if c["validation_status"] == "ready"),
        "needs_review": sum(1 for c in validated if c["validation_status"] != "ready"),
        "queue": validated,
    }
    with open(VALIDATED_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    _record_workflow_step(
        WF_ID,
        "forager_queue_validated",
        allowed_writes=["forager_threads"],
        writes_count=len(validated),
        output_json={
            "total_candidates": output["total_candidates"],
            "ready": output["ready"],
            "needs_review": output["needs_review"],
            "queue": [
                {
                    "priority": c.get("priority"),
                    "question": str(c.get("question", ""))[:60],
                    "status": c["validation_status"],
                    "issues": c["validation_issues"],
                }
                for c in validated
            ],
        },
    )

    print(f"Loaded candidates : {len(validated)}")
    print(f"Ready             : {output['ready']}")
    print(f"Needs review      : {output['needs_review']}")
    print(f"Validated JSON    : {VALIDATED_JSON_PATH}")
    for c in validated:
        issues = ", ".join(c["validation_issues"]) or "ok"
        print(f"  [{c.get('priority')}] {c.get('validation_status')} | {issues} | {str(c.get('question',''))[:65]}")


if __name__ == "__main__":
    main()
