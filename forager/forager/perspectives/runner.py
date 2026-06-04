"""Orchestrator: run all 4 perspectives over a single thread and aggregate."""
from __future__ import annotations

from typing import Any

from .base import Perspective, PerspectiveResult
from .local_language import LocalLanguagePerspective
from .market_structure import MarketStructurePerspective
from .disconfirmation import DisconfirmationPerspective
from .catalyst import CatalystPerspective


ALL_PERSPECTIVES: list[type[Perspective]] = [
    LocalLanguagePerspective,
    MarketStructurePerspective,
    DisconfirmationPerspective,
    CatalystPerspective,
]


def run_all_perspectives(
    thread_data: dict[str, Any],
    *,
    handoff_dir: str | None = None,
    perspectives: list[type[Perspective]] | None = None,
) -> dict[str, PerspectiveResult]:
    """Run every perspective over thread_data, return name → PerspectiveResult.

    Each perspective writes its own handoff JSON for manual LLM follow-up.
    Rule-based hypotheses are also returned for immediate use.
    """
    targets = perspectives or ALL_PERSPECTIVES
    results: dict[str, PerspectiveResult] = {}
    for cls in targets:
        agent = cls(handoff_dir=handoff_dir)
        result = agent.run(thread_data)
        results[agent.name] = result
    return results


def merge_perspectives_to_hypotheses(
    results: dict[str, PerspectiveResult],
    max_per_perspective: int = 3,
) -> list[dict]:
    """Merge 4 perspectives into a single hypothesis list, tagging origin.

    Each hypothesis gets `_perspective: <name>` added to its dict so downstream
    consumers (gate logic, dossier builder) can weight per perspective.
    """
    merged: list[dict] = []
    for name, res in results.items():
        for h in res.hypotheses[:max_per_perspective]:
            tagged = dict(h)
            tagged["_perspective"] = name
            tagged["_flags"] = res.flags
            merged.append(tagged)
    return merged


def perspective_summary(results: dict[str, PerspectiveResult]) -> dict[str, Any]:
    """Human-readable digest of what each perspective contributed."""
    return {
        name: {
            "hypothesis_count": len(res.hypotheses),
            "flags": res.flags,
            "handoff": (res.handoff_path or "").split("/")[-1],
            "notes": res.notes,
        }
        for name, res in results.items()
    }
