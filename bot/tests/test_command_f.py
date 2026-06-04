import pytest

import run_command_f as command_f


def test_mtm_ratio_no_uses_side_entry_price():
    ratio = command_f._mtm_ratio("NO", 0.059, 0.953)

    assert ratio == pytest.approx((1.0 - 0.953) / 0.059)


def test_entry_side_price_prefers_normalized_signal_price():
    legacy_position = {
        "intended_side": "NO",
        "intended_entry_price": 0.225,
        "signal_side_entry_price": 0.775,
    }

    assert command_f._entry_side_price(legacy_position) == pytest.approx(0.775)


def test_entry_side_price_falls_back_to_position_price():
    new_position_without_joined_signal = {
        "intended_side": "NO",
        "intended_entry_price": 0.059,
        "signal_side_entry_price": None,
    }

    assert command_f._entry_side_price(new_position_without_joined_signal) == pytest.approx(0.059)


def test_crawl_errors_are_hard_only_when_no_documents_were_written():
    blockers = ["crawl_error:https://polymarket.com/event/example"]

    assert command_f._hard_monitor_blockers(blockers, documents_written=0) == blockers
    assert command_f._hard_monitor_blockers(blockers, documents_written=2) == []


def test_documents_not_crawled_is_always_hard_blocker():
    blockers = ["documents_not_crawled"]

    assert command_f._hard_monitor_blockers(blockers, documents_written=2) == blockers
