"""Base classes for the multi-perspective Forager layer."""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


HANDOFF_DIR_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "bot",
    "llm_handoff",
    "perspectives",
)


@dataclass
class PerspectiveResult:
    """What a perspective returns after processing a thread."""
    name: str
    hypotheses: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    handoff_path: str | None = None
    notes: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class Perspective:
    """Base class for a Forager perspective.

    Subclasses override:
      - name (class attribute)
      - persona_prompt (str describing the role for the LLM)
      - extract_context(thread_data) → dict with relevant slices
      - rule_based_hypotheses(thread_data, context) → list[dict] (fallback)

    The base class handles handoff JSON writing and stitches together a
    PerspectiveResult.
    """
    name: str = "base"
    persona_prompt: str = ""

    def __init__(self, handoff_dir: str | None = None) -> None:
        self.handoff_dir = handoff_dir or HANDOFF_DIR_DEFAULT
        os.makedirs(self.handoff_dir, exist_ok=True)

    # ── Override points ─────────────────────────────────────────────────────

    def extract_context(self, thread_data: dict[str, Any]) -> dict[str, Any]:
        """Pull the slice of thread_data this perspective cares about."""
        return {
            "seed_query": thread_data.get("seed_query", ""),
            "market_id": thread_data.get("market_id", ""),
            "question": thread_data.get("question", ""),
        }

    def rule_based_hypotheses(self, thread_data: dict, context: dict) -> list[dict]:
        """Default rule-based fallback when LLM handoff hasn't been processed."""
        return []

    def domain_flags(self, thread_data: dict, context: dict) -> list[str]:
        """Domain-specific flags this perspective surfaces (override per agent)."""
        return []

    def evidence_refs(self, thread_data: dict, context: dict) -> list[str]:
        """URLs or source identifiers this perspective considers authoritative."""
        return []

    # ── Core flow ───────────────────────────────────────────────────────────

    def run(self, thread_data: dict[str, Any]) -> PerspectiveResult:
        """Execute the perspective: extract context, write LLM handoff, build
        a PerspectiveResult with rule-based fallback hypotheses."""
        context = self.extract_context(thread_data)
        flags = self.domain_flags(thread_data, context)
        refs = self.evidence_refs(thread_data, context)
        rule_hyps = self.rule_based_hypotheses(thread_data, context)
        handoff_path = self._write_handoff(thread_data, context, flags, refs)

        return PerspectiveResult(
            name=self.name,
            hypotheses=rule_hyps,
            flags=flags,
            evidence_refs=refs,
            handoff_path=handoff_path,
            notes=f"Rule-based fallback; LLM handoff at {os.path.basename(handoff_path)}",
            meta={"persona": self.persona_prompt[:80]},
        )

    def _write_handoff(
        self,
        thread_data: dict,
        context: dict,
        flags: list[str],
        refs: list[str],
    ) -> str:
        stamp = time.strftime("%Y%m%dT%H%M%S")
        uid = uuid.uuid4().hex[:8]
        fname = f"perspective_{self.name}_{stamp}_{uid}.json"
        path = os.path.join(self.handoff_dir, fname)
        payload = {
            "task": f"perspective_{self.name}",
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "persona": self.persona_prompt,
            "thread_id": thread_data.get("thread_id"),
            "market_id": thread_data.get("market_id"),
            "question": thread_data.get("question", ""),
            "context": context,
            "domain_flags": flags,
            "evidence_refs": refs,
            "expected_schema": {
                "hypotheses": [{
                    "direction": "YES|NO|UNCERTAIN",
                    "title": "str",
                    "hypothesis_text": "str — must be from this perspective's lens",
                    "confidence": "0.0-1.0",
                    "evidence_score": "0.0-1.0",
                    "perspective_specific_notes": "str",
                }],
                "key_observation": "str — what THIS perspective uniquely sees",
                "kill_signal_for_thesis": "str — what would make this perspective flip",
            },
            "instructions_for_claude": (
                f"Adopt the {self.name} persona only. Generate 2-4 hypotheses "
                "purely from THIS perspective's lens. Do not duplicate what "
                "another perspective would say. If your perspective has nothing "
                "to add (e.g. no local-language data for an English-only market), "
                "return empty hypotheses with a clear notes field."
            ),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        return path
