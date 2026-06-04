"""Realised-PnL formulas for binary YES/NO contracts."""
from __future__ import annotations


def realized_pnl(side: str, entry_price: float, bet_amount: float, resolved_yes: float) -> float:
    """
    Standard binary payout: if your side wins, payout = bet / entry; loss is the full bet.
    YES wins when resolved_yes > 0.5; NO wins when resolved_yes < 0.5.
    At exactly 0.5 the existing convention treats it as a YES loss / NO loss (no payout).
    """
    side = side.upper()
    if side == "YES":
        return bet_amount * (1.0 / entry_price - 1) if resolved_yes > 0.5 else -bet_amount
    if side == "NO":
        return bet_amount * (1.0 / (1.0 - entry_price) - 1) if resolved_yes < 0.5 else -bet_amount
    raise ValueError(f"side must be YES or NO, got {side!r}")
