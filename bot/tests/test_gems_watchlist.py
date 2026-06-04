"""Watchlist tools should hide rejected reviews even when raw score is high."""
from __future__ import annotations

import json

import db
import mcp_server


def _call(name, **kwargs):
    tool = mcp_server.mcp._tool_manager._tools[name]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or getattr(tool, "callback", None)
    return fn(**kwargs)


def _seed_market(c, cid: str, question: str = "Will test market resolve yes?"):
    db.upsert_market(
        c,
        condition_id=cid,
        question=question,
        slug="test-market",
        end_date="2026-06-01T00:00:00Z",
        vertical="test_vertical",
    )


def test_moonshot_watchlist_excludes_rejected_reviews(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xrejectmoon", "Rejected moonshot")
        _seed_market(c, "0xwatchmoon", "Watch moonshot")
        base = dict(
            created_at=None,
            analyst="test",
            side="YES",
            entry_price=0.05,
            payout_multiple=20.0,
            implied_probability=0.05,
            estimated_probability=0.06,
            probability_edge=0.01,
            catalyst_score=0.7,
            mechanism_score=0.7,
            evidence_score=0.7,
            resolution_score=0.7,
            liquidity_score=0.7,
            spread_score=0.7,
            narrative_heat_score=0.7,
            anti_random_score=0.7,
            risk_tier="moonshot",
            thesis="test thesis",
            kill_criteria="test kill criteria",
            next_research_step="test next step",
            sources_json=json.dumps([]),
        )
        db.add_moonshot_review(c, condition_id="0xrejectmoon", total_score=99.0, decision="reject_no_edge", **base)
        db.add_moonshot_review(c, condition_id="0xwatchmoon", total_score=50.0, decision="watchlist", **base)
        c.commit()

    out = _call("moonshot_watchlist", limit=10, min_score=45)
    ids = {m["condition_id"] for m in out["markets"]}
    assert "0xwatchmoon" in ids
    assert "0xrejectmoon" not in ids


def test_hidden_gem_watchlist_excludes_rejected_reviews(tmp_db):
    with db.connect() as c:
        _seed_market(c, "0xrejectgem", "Rejected hidden gem")
        _seed_market(c, "0xwatchgem", "Watch hidden gem")
        base = dict(
            created_at=None,
            analyst="test",
            executable_edge=0.1,
            liquidity_score=0.8,
            spread_score=0.8,
            attention_gap_score=0.8,
            evidence_asymmetry_score=0.8,
            stale_price_score=0.8,
            catalyst_score=0.8,
            resolution_clarity_score=0.8,
            thesis="test thesis",
            disconfirming_evidence="test disconfirming evidence",
            next_check_at=None,
        )
        db.add_hidden_gem_review(c, condition_id="0xrejectgem", total_score=99.0, decision="reject_thin_research", **base)
        db.add_hidden_gem_review(c, condition_id="0xwatchgem", total_score=50.0, decision="watchlist", **base)
        c.commit()

    out = _call("hidden_gem_watchlist", limit=10, min_score=40)
    ids = {m["condition_id"] for m in out["markets"]}
    assert "0xwatchgem" in ids
    assert "0xrejectgem" not in ids
