"""Realised-PnL formula for binary YES/NO contracts."""
from __future__ import annotations

import pytest

from lib.pnl import realized_pnl


def test_yes_wins_when_yes_resolves_above_half():
    # Buy YES at 0.40 with $10; YES resolves true → payout = $10 / 0.40 = $25; profit = $15
    pnl = realized_pnl("YES", entry_price=0.40, bet_amount=10.0, resolved_yes=1.0)
    assert pnl == pytest.approx(15.0)


def test_yes_loses_when_yes_resolves_below_half():
    pnl = realized_pnl("YES", entry_price=0.40, bet_amount=10.0, resolved_yes=0.0)
    assert pnl == pytest.approx(-10.0)


def test_no_wins_when_yes_resolves_below_half():
    # Buy NO at 0.30 (i.e. NO ≈ 0.30, YES ≈ 0.70). YES resolves 0 → NO wins.
    # Payout = bet / (1 - YES_entry) = 10 / 0.70 = 14.29; profit = 4.29
    pnl = realized_pnl("NO", entry_price=0.30, bet_amount=10.0, resolved_yes=0.0)
    assert pnl == pytest.approx(10.0 * (1.0 / 0.70 - 1), rel=1e-6)


def test_no_loses_when_yes_resolves_above_half():
    pnl = realized_pnl("NO", entry_price=0.30, bet_amount=10.0, resolved_yes=1.0)
    assert pnl == pytest.approx(-10.0)


def test_exact_half_resolution_treated_as_loss_both_sides():
    """resolved_yes == 0.5 is an ambiguous middle. The existing convention is loss
    (strict > and < in the formula), which matches Polymarket's actual rule that
    a market never resolves at 0.5."""
    assert realized_pnl("YES", 0.40, 10.0, 0.5) == -10.0
    assert realized_pnl("NO", 0.30, 10.0, 0.5) == -10.0


def test_low_entry_huge_payout():
    """Cheap optionality: buying YES at 0.05 with $5 → payout $100, profit $95."""
    pnl = realized_pnl("YES", entry_price=0.05, bet_amount=5.0, resolved_yes=1.0)
    assert pnl == pytest.approx(95.0)


def test_invalid_side_raises():
    with pytest.raises(ValueError):
        realized_pnl("BOTH", 0.4, 10.0, 1.0)
