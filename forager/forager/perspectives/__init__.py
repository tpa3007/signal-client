"""Multi-perspective Forager — 4 sub-agents with distinct mental models.

Designed to remove the "single LLM linear pipeline" feel that the original
Forager had. Each perspective is a specialised analyst that looks at the
same thread context through a different lens, produces its own hypothesis
set, and writes a Claude-handoff JSON for manual processing.

Perspectives (each is a Python module with a `Perspective` subclass):
  - local_language   — reads local-language sources, validates language asymmetry
  - market_structure — CLOB OFI, whale flow, cross-platform divergence
  - disconfirmation  — actively hunts kill-criterion-confirming evidence
  - catalyst         — tracks scheduled events, deadlines, vote dates

Usage:
    from forager.perspectives import run_all_perspectives
    results = run_all_perspectives(thread_id, store, candidate_metadata)
    # results is dict[name → Perspective] with .hypotheses, .meta, .handoff_path
"""
from __future__ import annotations

from .base import Perspective, PerspectiveResult
from .local_language import LocalLanguagePerspective
from .market_structure import MarketStructurePerspective
from .disconfirmation import DisconfirmationPerspective
from .catalyst import CatalystPerspective
from .runner import (
    run_all_perspectives,
    merge_perspectives_to_hypotheses,
    perspective_summary,
    ALL_PERSPECTIVES,
)

__all__ = [
    "Perspective",
    "PerspectiveResult",
    "LocalLanguagePerspective",
    "MarketStructurePerspective",
    "DisconfirmationPerspective",
    "CatalystPerspective",
    "run_all_perspectives",
    "merge_perspectives_to_hypotheses",
    "perspective_summary",
    "ALL_PERSPECTIVES",
]
