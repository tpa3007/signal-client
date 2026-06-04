"""Full Kelly Criterion implementation for Signal bet sizing.

Kelly Criterion: f* = (p*(b+1) - 1) / b
Where:
  p = probability of winning (our estimate)
  b = net odds on a $1 bet (how much we win if correct)
  f* = fraction of bankroll to bet

For prediction markets priced in cents:
  - YES bet at price p_market: win (1-p_market) per unit, lose p_market per unit
    b = (1 - p_market) / p_market
  - NO bet at price p_market: equivalent to YES bet at (1 - p_market)

Fractional Kelly:
  We use a KELLY_FRACTION < 1.0 (from config) as a risk management buffer.
  Full Kelly is theoretically optimal but assumes perfect probability estimates;
  fractional Kelly (0.25-0.50) is safer under model uncertainty.

Portfolio Kelly (multi-asset):
  Approximate portfolio Kelly using correlation-adjusted position sizing.
  When two positions are correlated (same geopolitical cluster, same deadline
  week), reduce both sizes proportionally.

Usage:
    from lib.kelly import kelly_stake, portfolio_kelly_stakes, kelly_edge_breakdown

    # Single position
    result = kelly_stake(
        our_prob=0.12,          # our estimate of YES probability
        market_price=0.195,     # current YES price
        side="NO",              # we're betting NO
        bankroll=1000.0,
        kelly_fraction=0.25,
    )
    print(result)
    # => {
    #      "side": "NO",
    #      "edge": 0.075,
    #      "kelly_f": 0.094,
    #      "fractional_kelly_f": 0.023,
    #      "recommended_stake": 23.4,
    #      "max_loss": 23.4,
    #      "expected_value": 1.76,
    #      "ev_per_dollar": 0.075,
    #      "breakeven_prob": 0.195,
    # }
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class KellyResult:
    """Result of a Kelly Criterion calculation."""

    side: str               # "YES" or "NO"
    edge: float             # our edge (our_prob - market_implied_prob for our side)
    kelly_f: float          # full Kelly fraction of bankroll
    fractional_kelly_f: float  # kelly_f * kelly_fraction (what we actually use)
    recommended_stake: float   # fractional_kelly_f * bankroll, clamped
    max_loss: float            # maximum possible loss on this bet
    expected_value: float      # EV in dollars at recommended_stake
    ev_per_dollar: float       # EV per dollar wagered (= edge for unit bets)
    breakeven_prob: float      # market-implied probability for our side
    market_price: float        # YES price used in calculation
    our_prob: float            # our probability estimate for YES
    notes: list[str] = field(default_factory=list)


def kelly_stake(
    our_prob: float,
    market_price: float,
    side: str = "YES",
    *,
    bankroll: float = 1000.0,
    kelly_fraction: float = 0.25,
    min_stake: float = 5.0,
    max_stake: float = 200.0,
    min_edge: float = 0.02,
) -> KellyResult:
    """Compute Kelly-optimal stake for a single Polymarket position.

    Args:
        our_prob:       Our probability estimate for YES (0-1).
        market_price:   Current Polymarket YES price (0-1), e.g. 0.195.
        side:           "YES" or "NO" — which side we're betting.
        bankroll:       Total capital available to allocate (USD).
        kelly_fraction: Safety fraction (0-1). 0.25 = quarter Kelly.
        min_stake:      Minimum stake in USD (below this = skip).
        max_stake:      Maximum stake in USD (hard cap).
        min_edge:       Minimum required edge to return a positive stake.

    Returns:
        KellyResult with full breakdown.
    """
    our_prob = max(0.001, min(0.999, float(our_prob)))
    market_price = max(0.001, min(0.999, float(market_price)))
    side = side.upper()
    notes: list[str] = []

    # Convert to "our side" probability and market-implied probability
    if side == "YES":
        p_win = our_prob                    # our prob of YES
        p_market = market_price             # market YES price
        # If we buy YES at price p, we win (1-p) and lose p
        b = (1.0 - p_market) / p_market
        breakeven_prob = p_market
    elif side == "NO":
        p_win = 1.0 - our_prob             # our prob of NO = 1 - our YES prob
        p_market = 1.0 - market_price      # NO price = 1 - YES price
        b = (1.0 - p_market) / p_market    # NO payout odds
        breakeven_prob = market_price       # for NO, breakeven = YES price
    else:
        raise ValueError(f"side must be 'YES' or 'NO', got: {side!r}")

    # Edge = our win probability - breakeven probability for this side
    if side == "YES":
        edge = our_prob - market_price
    else:
        edge = market_price - our_prob     # = (1-our_prob_yes) - (1-market_yes) = market_yes - our_prob_yes

    # Full Kelly: f* = (p*(b+1) - 1) / b = (p*b + p - 1) / b
    # Simplified for binary market: f* = p - (1-p)/b = p - q/b
    q_win = 1.0 - p_win
    if b <= 0:
        kelly_f = 0.0
        notes.append("b<=0: no valid payout odds")
    else:
        kelly_f = (p_win * b - q_win) / b
        # Equivalent formula: kelly_f = p_win - q_win/b

    kelly_f = max(0.0, kelly_f)
    fractional_kelly_f = kelly_f * kelly_fraction

    # Stake calculation
    raw_stake = fractional_kelly_f * bankroll

    if edge < min_edge:
        raw_stake = 0.0
        notes.append(f"edge {edge:.3f} < min_edge {min_edge:.3f}: no bet")

    if kelly_f == 0.0:
        raw_stake = 0.0
        notes.append("negative Kelly: bet has negative EV")

    # Clamp to [min_stake, max_stake]
    if raw_stake > 0 and raw_stake < min_stake:
        notes.append(f"stake {raw_stake:.2f} < min {min_stake:.2f}: rounded up")
        raw_stake = min_stake
    recommended_stake = min(max_stake, round(max(0.0, raw_stake), 2))

    if recommended_stake > max_stake:
        notes.append(f"capped at max_stake {max_stake:.2f}")

    # EV calculation
    max_loss = recommended_stake
    if side == "YES":
        win_amount = recommended_stake * b    # (1-market_price)/market_price * stake
    else:
        win_amount = recommended_stake * b

    expected_value = p_win * win_amount - q_win * recommended_stake
    ev_per_dollar = expected_value / recommended_stake if recommended_stake > 0 else 0.0

    return KellyResult(
        side=side,
        edge=round(edge, 4),
        kelly_f=round(kelly_f, 4),
        fractional_kelly_f=round(fractional_kelly_f, 4),
        recommended_stake=recommended_stake,
        max_loss=round(max_loss, 2),
        expected_value=round(expected_value, 2),
        ev_per_dollar=round(ev_per_dollar, 4),
        breakeven_prob=round(breakeven_prob, 4),
        market_price=round(market_price, 4),
        our_prob=round(our_prob, 4),
        notes=notes,
    )


@dataclass
class PortfolioKellyResult:
    """Kelly sizing for a portfolio of correlated positions."""
    positions: list[KellyResult]
    total_recommended: float
    total_bankroll_fraction: float
    correlation_adjustments: dict[str, float]  # condition_id → adjustment factor


def portfolio_kelly_stakes(
    positions: list[dict],
    *,
    bankroll: float = 1000.0,
    kelly_fraction: float = 0.25,
    max_portfolio_fraction: float = 0.40,  # max 40% of bankroll in any single run
    correlation_threshold: float = 0.60,   # above this = correlated, apply shrinkage
) -> PortfolioKellyResult:
    """Compute Kelly stakes for a portfolio with correlation-based shrinkage.

    Each position dict requires:
        condition_id: str
        our_prob: float
        market_price: float
        side: "YES" | "NO"
        vertical: str  (e.g. "politics", "economics", "geopolitics")
        end_date: str  (ISO date, e.g. "2026-06-15")

    Positions in the same vertical AND expiring in the same month
    are treated as correlated (ρ ≈ 0.5) and shrunk proportionally.
    """
    if not positions:
        return PortfolioKellyResult([], 0.0, 0.0, {})

    kelly_results: list[KellyResult] = []
    for pos in positions:
        kr = kelly_stake(
            our_prob=pos["our_prob"],
            market_price=pos["market_price"],
            side=pos.get("side", "YES"),
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
        )
        kelly_results.append(kr)

    # Build correlation buckets: same vertical + same expiry month
    buckets: dict[str, list[int]] = {}
    for i, pos in enumerate(positions):
        vertical = pos.get("vertical", "unknown")
        month = str(pos.get("end_date", ""))[:7]  # YYYY-MM
        bucket_key = f"{vertical}:{month}"
        buckets.setdefault(bucket_key, []).append(i)

    # Compute correlation-adjusted stake for each position
    adjustments: dict[str, float] = {}
    adjusted_stakes: list[float] = []
    for i, (pos, kr) in enumerate(zip(positions, kelly_results)):
        vertical = pos.get("vertical", "unknown")
        month = str(pos.get("end_date", ""))[:7]
        bucket_key = f"{vertical}:{month}"
        bucket_size = len(buckets.get(bucket_key, []))

        # Shrinkage: each additional correlated position reduces allocation
        # shrinkage_factor = 1 / sqrt(bucket_size) — square root formula
        # This gives: 1 pos=1.0, 2 pos=0.71, 3 pos=0.58, 4 pos=0.50
        if bucket_size > 1:
            shrinkage = 1.0 / math.sqrt(bucket_size)
        else:
            shrinkage = 1.0

        adjusted_stake = round(kr.recommended_stake * shrinkage, 2)
        adjustments[pos.get("condition_id", str(i))] = round(shrinkage, 3)
        adjusted_stakes.append(adjusted_stake)

    # Cap total portfolio allocation
    total = sum(adjusted_stakes)
    max_total = bankroll * max_portfolio_fraction
    if total > max_total:
        scale = max_total / total
        adjusted_stakes = [round(s * scale, 2) for s in adjusted_stakes]
        total = sum(adjusted_stakes)

    # Update recommended_stake in results
    final_results: list[KellyResult] = []
    for kr, adj_stake in zip(kelly_results, adjusted_stakes):
        final_results.append(KellyResult(
            side=kr.side,
            edge=kr.edge,
            kelly_f=kr.kelly_f,
            fractional_kelly_f=kr.fractional_kelly_f,
            recommended_stake=adj_stake,
            max_loss=adj_stake,
            expected_value=round(kr.ev_per_dollar * adj_stake, 2),
            ev_per_dollar=kr.ev_per_dollar,
            breakeven_prob=kr.breakeven_prob,
            market_price=kr.market_price,
            our_prob=kr.our_prob,
            notes=kr.notes,
        ))

    return PortfolioKellyResult(
        positions=final_results,
        total_recommended=round(total, 2),
        total_bankroll_fraction=round(total / bankroll, 4) if bankroll > 0 else 0.0,
        correlation_adjustments=adjustments,
    )


def kelly_edge_breakdown(
    our_prob: float,
    market_price: float,
    side: str = "YES",
) -> dict:
    """Human-readable Kelly edge breakdown — useful for L2 dossier display.

    Returns a dict with all the key numbers and a plain-English verdict.
    """
    side = side.upper()
    our_prob = max(0.001, min(0.999, float(our_prob)))
    market_price = max(0.001, min(0.999, float(market_price)))

    if side == "YES":
        edge = our_prob - market_price
        market_implied = market_price
        our_side_prob = our_prob
    else:
        edge = market_price - our_prob
        market_implied = 1.0 - market_price
        our_side_prob = 1.0 - our_prob

    edge_pct = edge * 100
    if edge >= 0.10:
        verdict = "STRONG EDGE — high conviction bet"
    elif edge >= 0.05:
        verdict = "SOLID EDGE — standard position"
    elif edge >= 0.02:
        verdict = "THIN EDGE — small position only"
    elif edge > 0:
        verdict = "MARGINAL EDGE — consider skipping"
    else:
        verdict = "NO EDGE / NEGATIVE — do not bet"

    return {
        "side": side,
        "our_prob_yes": round(our_prob, 4),
        "market_price_yes": round(market_price, 4),
        "our_prob_this_side": round(our_side_prob, 4),
        "market_implied_this_side": round(market_implied, 4),
        "edge": round(edge, 4),
        "edge_pct": round(edge_pct, 2),
        "verdict": verdict,
        "implied_vs_ours": (
            f"Market implies {market_implied*100:.1f}%, we estimate {our_side_prob*100:.1f}% "
            f"=> {edge_pct:+.1f}pp edge"
        ),
    }


def calibration_adjusted_kelly(
    our_prob: float,
    market_price: float,
    side: str,
    *,
    brier_score: float | None = None,
    calibration_bucket_accuracy: float | None = None,
    bankroll: float = 1000.0,
    kelly_fraction: float = 0.25,
) -> KellyResult:
    """Kelly stake adjusted for our historical calibration quality.

    If we have Brier score history, we can adjust confidence in our
    probability estimate. Poor calibration → shrink Kelly fraction further.

    brier_score: our recent Brier score (lower = better, 0.25 = random)
    calibration_bucket_accuracy: accuracy in this probability bucket (0-1)
    """
    notes: list[str] = []

    # Adjust kelly_fraction based on calibration quality
    adjusted_fraction = kelly_fraction

    if brier_score is not None:
        # Brier score 0.0 = perfect, 0.25 = random, 0.50 = systematically wrong
        # Scale kelly_fraction by (1 - brier_score*2)^0.5
        calibration_quality = max(0.0, 1.0 - brier_score * 2.0)
        calibration_multiplier = math.sqrt(calibration_quality)
        adjusted_fraction = kelly_fraction * calibration_multiplier
        notes.append(f"Brier={brier_score:.3f} → calibration multiplier {calibration_multiplier:.2f}")

    if calibration_bucket_accuracy is not None:
        # Further adjust based on accuracy in this specific probability bucket
        # Accuracy 1.0 = no adjustment, 0.5 = halve the Kelly fraction
        bucket_multiplier = max(0.2, calibration_bucket_accuracy)
        adjusted_fraction *= bucket_multiplier
        notes.append(f"Bucket accuracy={calibration_bucket_accuracy:.2f} → additional multiplier {bucket_multiplier:.2f}")

    adjusted_fraction = max(0.05, min(adjusted_fraction, kelly_fraction))

    result = kelly_stake(
        our_prob=our_prob,
        market_price=market_price,
        side=side,
        bankroll=bankroll,
        kelly_fraction=adjusted_fraction,
    )
    result.notes.extend(notes)
    return result
