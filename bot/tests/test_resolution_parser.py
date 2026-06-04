"""Stage 7: resolution parser — detect ambiguous market terms."""
from __future__ import annotations

import pytest

import db
import mcp_server  # ensures all tools register

from lib.resolution_parser import parse_resolution_clarity


def test_empty_text_returns_neutral():
    r = parse_resolution_clarity("")
    assert r["warnings"] == []
    assert r["ambiguity_score"] == 0.5
    assert r["clarity_score"] == 0.5


def test_unambiguous_text_zero_warnings():
    text = "Resolves YES if Nirav Shah wins the certified Maine Democratic primary on June 9, 2026."
    r = parse_resolution_clarity(text)
    assert r["ambiguity_score"] == 0.0
    assert r["n_high"] == 0 and r["n_medium"] == 0 and r["n_low"] == 0


def test_subjective_ranking_high_severity():
    text = "Will Google have the best AI model at the end of June 2026?"
    r = parse_resolution_clarity(text)
    assert r["ambiguity_score"] > 0.3
    assert any(w["code"] == "subjective_rank" for w in r["warnings"])
    assert any(w["severity"] == "high" for w in r["warnings"])


def test_consensus_keyword_high_severity():
    text = "Resolves based on consensus benchmarks."
    r = parse_resolution_clarity(text)
    assert any(w["code"] == "consensus" and w["severity"] == "high" for w in r["warnings"])


def test_release_deadline_pattern_catches_real_case():
    """The Gemini 3.5 trap our actual -53% loser fell into."""
    text = "Google publicly announces and releases Gemini 3.5 by May 31, 2026."
    r = parse_resolution_clarity(text)
    codes = [w["code"] for w in r["warnings"]]
    assert "release_deadline" in codes
    assert "official_modifier" in codes


def test_qualifying_modifier():
    text = "Resolves YES on the first qualifying public release."
    r = parse_resolution_clarity(text)
    assert any(w["code"] == "qualifying_modifier" for w in r["warnings"])


def test_undefined_quorum():
    text = "Most members of parliament vote in favor."
    r = parse_resolution_clarity(text)
    assert any(w["code"] == "undefined_quorum" for w in r["warnings"])


def test_dissolution_event_pattern():
    text = "Israeli parliament dissolved by May 31, 2026."
    r = parse_resolution_clarity(text)
    assert any(w["code"] == "dissolution_event" for w in r["warnings"])


def test_score_clamped_at_one():
    # Stack many high-severity terms
    text = "Approximately the best leading AI model, qualifying by consensus."
    r = parse_resolution_clarity(text)
    assert r["ambiguity_score"] == 1.0
    assert r["clarity_score"] == 0.0


def test_suggestion_appears_when_high_severity():
    text = "Best AI model by consensus."
    r = parse_resolution_clarity(text)
    assert r["suggestion"] is not None
    assert "high-severity" in r["suggestion"].lower() or "do not enter" in r["suggestion"].lower()


def test_no_suggestion_for_clean_text():
    text = "Resolves YES if X wins the June 9 election per official results."
    r = parse_resolution_clarity(text)
    assert r["suggestion"] is None


def test_dedup_same_rule_fires_once():
    """A rule that matches multiple times shouldn't add weight twice."""
    text = "Approximately approximately approximately the best best best"
    r = parse_resolution_clarity(text)
    # Should see at most one "approximately" and one "general_superlative"
    codes = [w["code"] for w in r["warnings"]]
    assert codes.count("approximately") <= 1
    assert codes.count("general_superlative") <= 1


def _call(_tool_name, **kw):
    t = mcp_server.mcp._tool_manager._tools[_tool_name]
    fn = getattr(t, "fn", None)
    return fn(**kw)


def test_record_resolution_map_persists_parser_warnings(tmp_db):
    now = "2026-06-01T00:00:00+00:00"
    with db.connect() as c:
        c.execute("""INSERT INTO markets (condition_id, question, slug, end_date,
                  first_seen_at, last_seen_at, vertical)
                  VALUES (?, ?, 's', '2026-08-01', ?, ?, 'tech_business')""",
                  ("0xparserpersist", "Will Google release its best AI model by June 2026?", now, now))
        c.commit()
    res = _call("record_resolution_map",
        condition_id="0xparserpersist",
        yes_criteria="YES if Google releases the best AI model publicly by the deadline.",
        no_criteria="NO otherwise.",
        primary_resolution_source="Polymarket rules",
        deadline_text="By June 30, 2026",
        ambiguity_cases="best model and publicly released are ambiguous",
    )
    assert res["ok"] is True
    assert res["parser_warnings"]
    with db.connect() as c:
        row = c.execute("""SELECT parser_warnings_json, parser_ambiguity_score, parser_suggestion
                           FROM resolution_maps WHERE condition_id = ?""",
                        ("0xparserpersist",)).fetchone()
    assert row["parser_warnings_json"]
    assert row["parser_ambiguity_score"] is not None
    assert row["parser_suggestion"] is not None
