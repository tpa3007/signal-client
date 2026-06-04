"""
Polymarket research MCP server.

Thin entry point: builds a FastMCP instance, then asks each module under
``bot/tools`` to register its tools. All scoring / pricing / sizing helpers
live in ``bot/lib``.

The intelligence lives in the Claude you're chatting with. The server just
provides data plumbing and state persistence. No Anthropic API calls happen here.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import db

# Tool modules - each exposes `register(mcp)` and self-contains its imports.
from tools import (
    intake,
    positions,
    research,
    causal,
    hold,
    gems,
    calibration,
    benchmark,
    portfolio,
    discovery,
    sources,
    workflows,
    elections,
    integrations,
)

# Back-compat re-exports: tests/legacy callers reach helpers via this module.
from lib.execution import (
    clamp01 as _clamp01,
    float_or_none as _float_or_none,
    execution_prices as _execution_prices,
    best_executable_edge as _best_executable_edge,
    no_signal_reason as _no_signal_reason,
)
from lib.queries import (
    latest_probability as _latest_probability,
    latest_execution_context as _latest_execution_context,
    market_row as _market_row,
    research_completeness as _research_completeness,
)
from lib.scoring import (
    hidden_gem_score as _hidden_gem_score,
    moonshot_score as _moonshot_score,
    resolution_completeness as _resolution_completeness,
    pre_bet_score as _pre_bet_score,
    signal_quality_score as _signal_quality_score,
    log_score as _log_score,
    quality_grade as _quality_grade,
    parse_dt as _parse_dt,
)
from lib.sizing import recommended_stake as _recommended_stake

# Re-export shared constants used by multiple tool groups.
from tools.intake import SIGNAL_ARCHETYPES, _today, _ensure_db  # noqa: F401


mcp = FastMCP("polymarket-research")

db.init()

for _module in (intake, positions, research, causal, hold, gems, calibration, benchmark, portfolio, discovery, sources, workflows, elections, integrations):
    _module.register(mcp)


if __name__ == "__main__":
    mcp.run()
