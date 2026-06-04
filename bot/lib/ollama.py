"""LLM helper module — Claude manual handoff mode (Ollama disabled).

Historical context: this module used to dispatch to local Ollama. As of
2026-05-23 the user decided to remove Ollama from the cycle and instead
have Claude (Opus 4.7 / Sonnet) handle every LLM step manually when the
operator runs the pipeline interactively.

How the new pattern works:
  - Every advisory-LLM function (dossier_draft, monitoring_draft, etc.)
    now serialises its full prompt + context into a JSON handoff file
    under ``bot/llm_handoff/<task>_<timestamp>_<id>.json``.
  - The function returns an empty/safe default ({} or []) so callers
    fall through to their rule-based path and the pipeline does NOT
    block waiting for an LLM response.
  - After the pipeline finishes the operator (or Claude in a fresh
    session) reads the handoff files, processes them with Opus 4.7,
    and writes ``<orig>.response.json`` next to each request. A
    follow-up tool can then inject responses back into the DB.

This keeps the cycle fast and deterministic and removes the silent
Ollama-fallback that was masking the absence of real LLM reasoning.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

HANDOFF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "llm_handoff")


def _ensure_dir() -> None:
    os.makedirs(HANDOFF_DIR, exist_ok=True)


def _write_handoff(task: str, prompt: str, context: dict[str, Any],
                   expected_schema: dict[str, Any] | None = None) -> str:
    """Persist a Claude-handoff JSON request file. Returns absolute path."""
    _ensure_dir()
    stamp = time.strftime("%Y%m%dT%H%M%S")
    uid = uuid.uuid4().hex[:8]
    fname = f"{task}_{stamp}_{uid}.json"
    path = os.path.join(HANDOFF_DIR, fname)
    payload = {
        "task": task,
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt": prompt,
        "context": context,
        "expected_schema": expected_schema or {},
        "instructions_for_claude": (
            "Read prompt + context, produce a JSON value matching expected_schema. "
            "Save your response as <thisfile>.response.json next to this file."
        ),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"  [LLM handoff] {task} -> {os.path.basename(path)}")
    return path


# ── Backward-compat thin shims so callers don't break ─────────────────

def ollama_available(timeout: float = 2.0) -> bool:
    """Always False under manual-Claude mode."""
    return False


def ollama_chat(prompt: str, **kwargs: Any) -> str:  # noqa: ARG001
    return ""


def ollama_json(prompt: str, **kwargs: Any) -> Any:  # noqa: ARG001
    return kwargs.get("fallback")


# ── Advisory drafts: now write handoffs and return safe defaults ──────

def candidate_research_draft(candidate: dict[str, Any]) -> dict[str, Any]:
    _write_handoff(
        task="candidate_research_draft",
        prompt="Create a compact prediction-market research draft for the candidate "
               "JSON in context. Generate: thesis, why_signal_may_miss, "
               "disconfirming_angle, kill_criteria (3 items), first_queries (3), "
               "local_language, source_plan, risk_flags.",
        context={"candidate": candidate},
        expected_schema={
            "thesis": "str", "why_signal_may_miss": "str",
            "disconfirming_angle": "str", "kill_criteria": ["str"],
            "first_queries": ["str"], "local_language": "str | null",
            "source_plan": ["str"], "risk_flags": ["str"],
        },
    )
    return {}


def dossier_draft(candidate: dict[str, Any], packet: dict[str, Any] | None) -> dict[str, Any]:
    _write_handoff(
        task="dossier_draft",
        prompt="Build a second-layer dossier draft for the prediction-market "
               "candidate. Use the Forager packet for evidence. Be conservative.",
        context={"candidate": candidate, "packet": packet or {}},
        expected_schema={
            "resolution_notes": ["str"], "evidence_notes": ["str"],
            "actor_notes": ["str"], "causal_factors": ["str"],
            "scenarios": ["str"], "premortems": ["str"],
            "pre_bet_notes": ["str"], "confidence_adjustment": "float",
        },
    )
    return {}


def monitoring_draft(position: dict[str, Any], packet: dict[str, Any] | None) -> dict[str, Any]:
    _write_handoff(
        task="monitoring_draft",
        prompt="Review the open paper position + fresh Forager packet. "
               "Produce kill_criteria, advisory_recommendation (HOLD/REVIEW/EXIT), "
               "reason, next_queries. Prefer REVIEW when ambiguous.",
        context={"position": position, "packet": packet or {}},
        expected_schema={
            "kill_criteria": ["str"], "advisory_recommendation": "HOLD|REVIEW|EXIT",
            "reason": "str", "next_queries": ["str"],
        },
    )
    return {}


def learning_review_draft(context: dict[str, Any]) -> dict[str, Any]:
    _write_handoff(
        task="learning_review_draft",
        prompt="Draft a learning review for a resolved signal. Be process-focused.",
        context=context,
        expected_schema={
            "why_right_or_wrong": "str", "repeatable_lesson": "str",
            "error_flags": {"resolution_error": 0, "probability_error": 0,
                            "evidence_error": 0, "timing_error": 0, "sizing_error": 0},
            "rule_update": "str | null",
        },
    )
    return {}
