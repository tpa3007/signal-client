"""Portfolio exposure aggregation and cap checks.

Exposure is measured as intended_stake_usd across OPEN positions, bucketed by:
  - vertical (markets.vertical)
  - primary_archetype (positions.primary_archetype, NULL bucket = 'unclassified')
  - deadline_week (ISO year-week of positions.end_date)
  - thematic tag (market_tags.tag)
  - single market (positions.condition_id)

Caps are expressed as fractions of BANKROLL_USD in config.
"""
from __future__ import annotations

from datetime import datetime, timezone

import config


def _iso_week(end_date: str | None) -> str | None:
    if not end_date:
        return None
    try:
        dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def open_exposure(conn) -> dict:
    """Snapshot of intended-stake exposure across OPEN positions.

    Returns a dict with: total_at_risk_usd, by_vertical, by_archetype,
    by_deadline_week, by_theme, by_market - each mapping bucket -> usd.
    """
    rows = conn.execute("""
        SELECT p.id, p.condition_id, p.intended_side, p.intended_stake_usd,
               p.primary_archetype, p.end_date,
               COALESCE(m.vertical, 'unknown') AS vertical
        FROM positions p
        LEFT JOIN markets m ON m.condition_id = p.condition_id
        WHERE p.status IN ('open', 'filled', 'partially_filled')
    """).fetchall()

    by_vertical: dict[str, float] = {}
    by_archetype: dict[str, float] = {}
    by_week: dict[str, float] = {}
    by_theme: dict[str, float] = {}
    by_market: dict[str, float] = {}
    total = 0.0
    for r in rows:
        stake = float(r["intended_stake_usd"] or 0.0)
        total += stake
        by_vertical[r["vertical"]] = by_vertical.get(r["vertical"], 0.0) + stake
        arch = r["primary_archetype"] or "unclassified"
        by_archetype[arch] = by_archetype.get(arch, 0.0) + stake
        wk = _iso_week(r["end_date"]) or "unknown"
        by_week[wk] = by_week.get(wk, 0.0) + stake
        by_market[r["condition_id"]] = by_market.get(r["condition_id"], 0.0) + stake
        tags = [t["tag"] for t in conn.execute(
            "SELECT tag FROM market_tags WHERE condition_id = ?",
            (r["condition_id"],),
        ).fetchall()]
        for tag in tags:
            by_theme[tag] = by_theme.get(tag, 0.0) + stake
    return {
        "total_at_risk_usd": round(total, 2),
        "by_vertical": {k: round(v, 2) for k, v in by_vertical.items()},
        "by_archetype": {k: round(v, 2) for k, v in by_archetype.items()},
        "by_deadline_week": {k: round(v, 2) for k, v in by_week.items()},
        "by_theme": {k: round(v, 2) for k, v in by_theme.items()},
        "by_market": {k: round(v, 2) for k, v in by_market.items()},
        "open_positions": len(rows),
    }


def _cap_usd(pct: float) -> float:
    return config.BANKROLL_USD * pct


def check_exposure(conn, *, condition_id: str, vertical: str,
                   primary_archetype: str | None, end_date: str | None,
                   proposed_stake_usd: float,
                   theme_tags: list[str] | None = None) -> dict:
    """Would adding `proposed_stake_usd` for the given bucket combo breach any cap?

    Returns:
      {
        "allowed": bool,
        "breaches": [{"bucket": "vertical|archetype|deadline_week|single_market",
                      "key": "...", "current_usd": ..., "proposed_usd": ...,
                      "cap_usd": ...}],
        "current": open_exposure snapshot,
        "highest_existing_share": float,   # used by sizing shrinkage
      }
    """
    snap = open_exposure(conn)
    bv = snap["by_vertical"].get(vertical, 0.0)
    arch_key = primary_archetype or "unclassified"
    ba = snap["by_archetype"].get(arch_key, 0.0)
    wk = _iso_week(end_date) or "unknown"
    bw = snap["by_deadline_week"].get(wk, 0.0)
    bm = snap["by_market"].get(condition_id, 0.0)
    if theme_tags is None:
        theme_tags = [r["tag"] for r in conn.execute(
            "SELECT tag FROM market_tags WHERE condition_id = ?",
            (condition_id,),
        ).fetchall()]
    theme_tags = sorted(set(theme_tags or []))
    theme_currents = {tag: snap["by_theme"].get(tag, 0.0) for tag in theme_tags}

    caps = {
        "vertical": (vertical, bv, _cap_usd(config.EXPOSURE_VERTICAL_CAP_PCT)),
        "archetype": (arch_key, ba, _cap_usd(config.EXPOSURE_ARCHETYPE_CAP_PCT)),
        "deadline_week": (wk, bw, _cap_usd(config.EXPOSURE_DEADLINE_WEEK_CAP_PCT)),
        "single_market": (condition_id, bm, _cap_usd(config.EXPOSURE_SINGLE_MARKET_CAP_PCT)),
    }
    for tag, current in theme_currents.items():
        caps[f"theme:{tag}"] = (tag, current, _cap_usd(config.EXPOSURE_THEME_CAP_PCT))
    breaches = []
    for bucket, (key, current, cap_usd) in caps.items():
        if current + proposed_stake_usd > cap_usd:
            bucket_name = "theme" if bucket.startswith("theme:") else bucket
            breaches.append({
                "bucket": bucket_name,
                "key": key,
                "current_usd": round(current, 2),
                "proposed_usd": round(proposed_stake_usd, 2),
                "after_usd": round(current + proposed_stake_usd, 2),
                "cap_usd": round(cap_usd, 2),
            })

    # Highest existing share BEFORE this proposal - used by sizing.shrinkage.
    highest = max(
        bv / _cap_usd(config.EXPOSURE_VERTICAL_CAP_PCT),
        ba / _cap_usd(config.EXPOSURE_ARCHETYPE_CAP_PCT),
        bw / _cap_usd(config.EXPOSURE_DEADLINE_WEEK_CAP_PCT),
        bm / _cap_usd(config.EXPOSURE_SINGLE_MARKET_CAP_PCT),
        *(current / _cap_usd(config.EXPOSURE_THEME_CAP_PCT) for current in theme_currents.values()),
    ) if config.BANKROLL_USD > 0 else 0.0
    highest = min(1.0, max(0.0, highest))

    return {
        "allowed": not breaches,
        "breaches": breaches,
        "current": snap,
        "highest_existing_share": round(highest, 4),
    }
