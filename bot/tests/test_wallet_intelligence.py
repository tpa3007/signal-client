from __future__ import annotations

import sqlite3

import run_command_w as w
from lib.wallet_intelligence import (
    classify_player_style,
    convergence_vote_weight,
    score_position_signal,
)


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _wallet_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(w.SCHEMA_SQL)
    return conn


def test_score_position_signal_filters_dust_and_scores_real_position():
    dust = score_position_signal(
        {"outcome": "Yes", "size": 10, "avgPrice": 0.40},
        label="smart",
        composite_score=35,
        our_side="NO",
    )
    assert dust["signal_tier"] == "ignore"
    assert "dust_position" in dust["flags"]

    signal = score_position_signal(
        {"outcome": "No", "size": 400, "avgPrice": 0.64, "cashPnl": 12},
        label="insider",
        composite_score=55,
        our_side="YES",
    )
    assert signal["side"] == "NO"
    assert signal["agreement"] == "disagree"
    assert signal["signal_tier"] in {"medium", "high"}
    assert convergence_vote_weight(signal) > 0


def test_classify_player_style_marks_early_specialist_and_flags_thin_sample():
    intel = classify_player_style(
        {
            "markets_resolved": 2,
            "total_volume_usd": 8_000,
            "timing_alpha": 0.78,
            "best_category_edge": 0.08,
            "category_hhi": 0.72,
            "bio": "political research",
        },
        composite_score=44,
    )

    assert intel["player_style"] == "early_specialist_insider_candidate"
    assert "thin_resolved_sample" in intel["risk_flags"]
    assert intel["trust_score"] < 44


def test_command_w_gamma_lookup_uses_condition_ids_and_validates_identity(tmp_path, monkeypatch):
    conn = _wallet_db(tmp_path / "w.db")
    w._market_cache.clear()
    w._slug_from_cid_hint.clear()

    calls = []

    def fake_get(_url, params, timeout, headers):
        calls.append(params)
        assert "condition_ids" in params
        return _Response([
            {
                "conditionId": "0xabc",
                "question": "Will this exact market resolve Yes?",
                "slug": "exact-market",
                "outcomePrices": '["0.42","0.58"]',
                "resolved": False,
                "endDate": "2026-07-01T00:00:00Z",
            }
        ])

    monkeypatch.setattr(w.requests, "get", fake_get)

    meta = w.get_market_meta("0xabc", conn)

    assert meta["condition_id"] == "0xabc"
    assert meta["last_price_yes"] == 0.42
    assert calls[0]["condition_ids"] == "0xabc"


def test_command_w_gamma_lookup_rejects_mismatched_slug_fallback(tmp_path, monkeypatch):
    conn = _wallet_db(tmp_path / "w.db")
    w._market_cache.clear()
    w._slug_from_cid_hint.clear()
    w._slug_from_cid_hint["0xwanted"] = "some-market-123"

    def fake_get(_url, params, timeout, headers):
        if "condition_ids" in params:
            return _Response([])
        return _Response([
            {
                "conditionId": "0xwrong",
                "question": "Wrong market",
                "slug": "some-market",
                "outcomePrices": '["0.99","0.01"]',
            }
        ])

    monkeypatch.setattr(w.requests, "get", fake_get)

    assert w.get_market_meta("0xwanted", conn) is None
