"""Discovery strategies — pure filter functions over candidate-market dicts.

Each strategy takes a list of candidate dicts (shape produced by
``fetch_active_markets`` / Gamma) plus optional history lookups, and returns a
filtered subset annotated with the strategy name. A market may match more than
one strategy.

Each candidate dict is expected to expose at least: condition_id, question,
yes_price, volume, liquidity, spread, days_to_end, end_date, vertical,
first_seen_at (when available).
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Callable

import config


def _market_age_days(first_seen_at: str | None) -> float | None:
    if not first_seen_at:
        return None
    try:
        dt = datetime.fromisoformat(first_seen_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def low_volume_research_sweetspot(m: dict) -> bool:
    """Sweet spot where big desks ignore but research can still find edge."""
    vol = m.get("volume") or 0
    days = m.get("days_to_end")
    spread = m.get("spread")
    yes = m.get("yes_price")
    if yes is None or days is None:
        return False
    if not (config.DISCOVERY_LOW_VOL_MIN <= vol <= config.DISCOVERY_LOW_VOL_MAX):
        return False
    if not (config.DISCOVERY_LOW_VOL_DAYS_MIN <= days <= config.DISCOVERY_LOW_VOL_DAYS_MAX):
        return False
    if spread is not None and spread > config.MAX_SPREAD:
        return False
    if not (0.10 <= yes <= 0.90):
        return False
    return True


def compounder_research_candidate(m: dict) -> bool:
    """Mid-priced market where high-confidence research can compound.

    This lane is deliberately not a moonshot. It catches markets around
    22-60 cents on either side where a deep dossier might justify a 60-70%
    model probability and therefore strong hold-to-resolution EV.
    """
    yes = m.get("yes_price")
    no = m.get("no_price")
    vol = m.get("volume") or 0
    liq = m.get("liquidity") or 0
    spread = m.get("spread")
    days = m.get("days_to_end")
    if yes is None or days is None:
        return False
    try:
        yes = float(yes)
        no = float(no if no is not None else 1.0 - yes)
    except (TypeError, ValueError):
        return False
    if not (config.DISCOVERY_COMPOUNDER_DAYS_MIN <= days <= config.DISCOVERY_COMPOUNDER_DAYS_MAX):
        return False
    if not (config.DISCOVERY_COMPOUNDER_VOL_MIN <= vol <= config.DISCOVERY_COMPOUNDER_VOL_MAX):
        return False
    if liq < config.DISCOVERY_COMPOUNDER_LIQUIDITY_MIN:
        return False
    if spread is not None and spread > config.MAX_SPREAD:
        return False
    lo = config.DISCOVERY_COMPOUNDER_PRICE_MIN
    hi = config.DISCOVERY_COMPOUNDER_PRICE_MAX
    return (lo <= yes <= hi) or (lo <= no <= hi)


def stale_price(m: dict, price_series: list[float] | None) -> bool:
    """Market hasn't moved in a while — ripe for catalyst-driven repricing.

    Needs a price series of length >= 3 (typically from backfilled snapshots
    in the last DISCOVERY_STALE_WINDOW_DAYS days). Without enough history we
    decline (return False) so callers know to call backfill_price_history first.
    """
    vol = m.get("volume") or 0
    if vol < config.MIN_VOLUME_USD:
        return False
    age = _market_age_days(m.get("first_seen_at"))
    if age is None or age < config.DISCOVERY_STALE_AGE_MIN_DAYS:
        return False
    if not price_series or len(price_series) < 3:
        return False
    try:
        stdev = statistics.pstdev(price_series)
    except statistics.StatisticsError:
        return False
    return stdev <= config.DISCOVERY_STALE_STDEV_MAX


def cheap_optionality(m: dict) -> bool:
    """Powell / Yemen-style: extreme prices on NEGLECTED markets.

    An extreme price ($0.02 yes) on a heavily-watched market (Fed rate decision
    with $5M volume) is not a hidden gem — it's a pre-priced consensus. We gate
    on volume max to keep this strategy honest.
    """
    yes = m.get("yes_price")
    liq = m.get("liquidity") or 0
    vol = m.get("volume") or 0
    days = m.get("days_to_end")
    if yes is None or days is None:
        return False
    in_low = yes <= config.DISCOVERY_CHEAP_OPT_LOW_MAX
    in_high = yes >= config.DISCOVERY_CHEAP_OPT_HIGH_MIN
    if not (in_low or in_high):
        return False
    if liq < config.DISCOVERY_CHEAP_OPT_LIQUIDITY_MIN:
        return False
    if vol > config.DISCOVERY_CHEAP_OPT_VOL_MAX:
        return False
    if not (config.DISCOVERY_CHEAP_OPT_DAYS_MIN <= days <= config.DISCOVERY_CHEAP_OPT_DAYS_MAX):
        return False
    return True


# Strategy name → predicate. `stale_price` is special — it needs a price series
# so the dispatch happens in tools/discovery.py rather than here.
STRATEGIES: dict[str, Callable[[dict], bool]] = {
    "low_volume_research_sweetspot": low_volume_research_sweetspot,
    "cheap_optionality": cheap_optionality,
    "compounder_research_candidate": compounder_research_candidate,
}

# Names exposed to clients (including the stateful stale_price one).
ALL_STRATEGY_NAMES = (
    "low_volume_research_sweetspot",
    "stale_price",
    "cheap_optionality",
    "compounder_research_candidate",
)
