"""Polymarket resolution-mechanics extractor.

The audit of 2026-06-02 found Command B ranked candidates without ever reading
the *actual* Polymarket resolution rules. It mistook Anthropic's funding-round
valuation for the resolution metric (which is the NPM Price from Nasdaq Private
Market) and misread the ``↓ $850B`` market (a *crash* test) as ``reach $850B``.

This module fetches the live market description + the sibling ladder from the
Gamma API and extracts the decisive mechanics every candidate must carry before
ranking:

  - resolution_metric   : what number actually resolves the market
  - direction           : peak / floor_or_crash / exact / range / point_in_time
  - threshold           : the listed amount (from groupItemTitle, e.g. "↓ $850B")
  - ladder              : sibling thresholds + prices (detects resolved siblings
                          and price-monotonicity anomalies)
  - flags               : machine-readable warnings for Command D

It is intentionally dependency-light (urllib) and fail-soft: any network/parse
error returns a partial dict with ``fetched=False`` rather than raising.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

GAMMA = "https://gamma-api.polymarket.com"
_UA = {"User-Agent": "Signal-MechanicsExtractor/1.0"}


def _get(url: str, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ── metric detection ──────────────────────────────────────────────────────

_METRIC_RULES = [
    ("private_provider_npm", ("npm", "nasdaq private market", "secondmarket")),
    ("bls_employment", ("bureau of labor statistics", "employment situation", "u-3", "unemployment rate")),
    ("bls_cpi", ("consumer price index", "cpi", "bureau of labor statistics")),
    ("fed_policy", ("federal reserve", "fomc", "federal funds", "fed funds")),
    ("central_bank", ("ecb", "bank of japan", "boj", "central bank", "rate decision")),
    ("election_official", ("electoral commission", "official results", "superior electoral",
                           "election commission", "valid votes", "returning officer")),
    ("exchange_listing", ("ipo", "direct listing", "primary exchange", "regular-hours trading")),
    ("media_consensus", ("consensus of credible reporting", "credible reporting", "official information")),
]


def detect_metric(description: str) -> str:
    d = (description or "").lower()
    for name, kws in _METRIC_RULES:
        if any(k in d for k in kws):
            return name
    return "unknown"


# ── direction / semantics detection ───────────────────────────────────────

def detect_direction(question: str, group_item_title: str, description: str) -> dict[str, Any]:
    """Classify how the market resolves on its target number.

    Returns {direction, evidence}. Directions:
      peak           — YES if value RISES to >= threshold at any time (↑)
      floor_or_crash — YES if value FALLS to <= threshold at any time (↓)
      exact          — YES only if value equals a single listed value
      range          — YES if value lands in [a, b]
      point_in_time  — resolves on value at a specific close/date
      threshold_geq  — generic "reaches or exceeds" without ↑/↓ grouping
    """
    git = (group_item_title or "").strip()
    q = (question or "").lower()
    d = (description or "").lower()
    ev: list[str] = []

    # The strongest signal is the grouped ladder arrow.
    if "↓" in git or git.lower().startswith("low") or "(low)" in q:
        ev.append(f"groupItemTitle={git!r} (down arrow / LOW)")
        return {"direction": "floor_or_crash", "evidence": ev}
    if "↑" in git or git.lower().startswith("high") or "(high)" in q:
        ev.append(f"groupItemTitle={git!r} (up arrow / HIGH)")
        return {"direction": "peak", "evidence": ev}

    # Exact-value brackets: "be 4.4%", "exactly", single equality.
    if re.search(r"\bexactly\b", d) or re.search(r"\bbe\s+\d+(\.\d+)?%", q):
        ev.append("exact-value phrasing in question/description")
        return {"direction": "exact", "evidence": ev}

    if re.search(r"\bbetween\b.+\band\b", q) or re.search(r"\bbetween\b.+\band\b", d):
        ev.append("range phrasing 'between X and Y'")
        return {"direction": "range", "evidence": ev}

    if "reaches or exceeds" in d or "reach or exceed" in d or "at any" in d:
        ev.append("'reaches or exceeds ... at any date' (peak/at-any-time)")
        return {"direction": "threshold_geq", "evidence": ev}

    if re.search(r"\bas of\b|\bat the close\b|\bon the (resolution|end) date\b", d):
        ev.append("point-in-time phrasing")
        return {"direction": "point_in_time", "evidence": ev}

    return {"direction": "unknown", "evidence": ev or ["no decisive phrasing found"]}


def _parse_prices(market: dict) -> float | None:
    op = market.get("outcomePrices")
    try:
        p = json.loads(op) if isinstance(op, str) else op
        return float(p[0]) if p else None
    except Exception:
        return None


def _ladder_from_event(event: dict) -> list[dict[str, Any]]:
    rows = []
    for m in event.get("markets", []) or []:
        rows.append({
            "question": m.get("question", ""),
            "groupItemTitle": m.get("groupItemTitle", ""),
            "yes": _parse_prices(m),
            "closed": m.get("closed"),
            "volume": m.get("volumeNum") or 0,
        })
    return rows


def _ladder_anomaly(ladder: list[dict[str, Any]]) -> str | None:
    """Detect a price-monotonicity inversion within a single ↑ or ↓ family.

    Within a peak (↑) family, higher threshold must have <= YES probability.
    A violation means at least one bracket is mispriced or mis-grouped.
    """
    def _thr(row):
        t = row.get("groupItemTitle") or row.get("question") or ""
        m = re.search(r"\$?([\d.]+)\s*([tbm])", t.lower())
        if not m:
            return None
        val = float(m.group(1))
        mult = {"t": 1e12, "b": 1e9, "m": 1e6}[m.group(2)]
        return val * mult

    for fam_key, fam in (("↑", [r for r in ladder if "↑" in (r.get("groupItemTitle") or "")]),
                         ("↓", [r for r in ladder if "↓" in (r.get("groupItemTitle") or "")])):
        pts = [(t, r["yes"]) for r in fam if (t := _thr(r)) is not None and r.get("yes") is not None and not r.get("closed")]
        pts.sort()
        if fam_key == "↑":
            # ascending threshold → YES should be non-increasing
            for (t1, y1), (t2, y2) in zip(pts, pts[1:]):
                if y2 > y1 + 0.05:
                    return f"↑ family inversion: {t2:.0f} YES={y2:.2f} > {t1:.0f} YES={y1:.2f}"
        else:
            # ↓ family: lower threshold → YES should be non-increasing (harder to crash that far)
            for (t1, y1), (t2, y2) in zip(pts, pts[1:]):
                if y1 > y2 + 0.05:
                    return f"↓ family inversion: {t1:.0f} YES={y1:.2f} > {t2:.0f} YES={y2:.2f}"
    return None


def extract_mechanics(condition_id: str = "", slug: str = "",
                      question: str = "") -> dict[str, Any]:
    """Fetch + parse resolution mechanics for a Polymarket market.

    Returns a structured dict; ``fetched=False`` on any failure (fail-soft).
    """
    out: dict[str, Any] = {
        "fetched": False, "condition_id": condition_id, "slug": slug,
        "resolution_metric": "unknown", "direction": "unknown",
        "threshold": None, "ladder": [], "flags": [], "yes_price": None,
        "end_date": None, "closed": None, "description_excerpt": "",
    }
    market = None
    try:
        if condition_id:
            data = _get(f"{GAMMA}/markets?condition_ids={condition_id}")
            market = data[0] if isinstance(data, list) and data else None
        if market is None and slug:
            data = _get(f"{GAMMA}/markets?slug={slug}")
            market = data[0] if isinstance(data, list) and data else None
    except Exception as exc:  # noqa: BLE001
        out["flags"].append(f"fetch_error:{exc}")
        return out
    if market is None:
        out["flags"].append("market_not_found")
        return out

    desc = market.get("description") or ""
    git = market.get("groupItemTitle") or ""
    q = question or market.get("question") or ""

    out["fetched"] = True
    out["yes_price"] = _parse_prices(market)
    out["end_date"] = market.get("endDate")
    out["closed"] = market.get("closed")
    out["description_excerpt"] = desc[:400]
    out["group_item_title"] = git
    out["resolution_metric"] = detect_metric(desc)
    dirinfo = detect_direction(q, git, desc)
    out["direction"] = dirinfo["direction"]
    out["direction_evidence"] = dirinfo["evidence"]

    m = re.search(r"\$?\s*([\d.]+\s*(?:trillion|billion|million|[tbm%]))", git, re.I) \
        or re.search(r"\$?\s*([\d.]+\s*(?:trillion|billion|million|[tbm]))", q, re.I)
    if m:
        out["threshold"] = m.group(1).strip()

    # Sibling ladder via the parent event
    try:
        events = market.get("events") or []
        ev_slug = events[0].get("slug") if events else None
        if ev_slug:
            evdata = _get(f"{GAMMA}/events?slug={ev_slug}")
            if isinstance(evdata, list) and evdata:
                out["ladder"] = _ladder_from_event(evdata[0])
    except Exception as exc:  # noqa: BLE001
        out["flags"].append(f"ladder_error:{exc}")

    # ── Flags for Command D ───────────────────────────────────────────────
    if out["resolution_metric"] == "private_provider_npm":
        out["flags"].append("metric_is_private_provider_mark: use NPM Price, NOT funding-round valuation")
    if out["resolution_metric"] == "unknown":
        out["flags"].append("resolution_metric_unparsed: operator must read rules")
    if out["direction"] == "floor_or_crash":
        out["flags"].append("direction_is_DOWNSIDE: YES means value FALLS to threshold, not rises to it")
    if out["direction"] in ("unknown",):
        out["flags"].append("direction_ambiguous: operator must confirm peak/floor/exact")
    if out["direction"] == "exact":
        out["flags"].append("exact_value_bracket: only a single print resolves YES")
    anom = _ladder_anomaly(out["ladder"])
    if anom:
        out["flags"].append(f"ladder_price_anomaly: {anom}")
    resolved_sibs = [r for r in out["ladder"] if r.get("closed")]
    if resolved_sibs:
        out["flags"].append(
            "resolved_siblings_exist: "
            + "; ".join(f"{r.get('groupItemTitle') or r.get('question','')[:30]}={r.get('yes')}"
                        for r in resolved_sibs[:4])
        )
    return out


def format_mechanics_for_forager(mech: dict[str, Any]) -> str:
    """Human-readable block for the B context_brief / D dossier."""
    if not mech.get("fetched"):
        return f"[MARKET MECHANICS] could not fetch ({', '.join(mech.get('flags', [])) or 'unknown'})"
    lines = [
        "[MARKET MECHANICS — verified from live Polymarket rules]",
        f"  resolution_metric: {mech['resolution_metric']}",
        f"  direction: {mech['direction']}  ({'; '.join(mech.get('direction_evidence', []))})",
        f"  threshold: {mech.get('threshold')}  | yes_price: {mech.get('yes_price')}  | ends: {mech.get('end_date')}",
    ]
    if mech.get("ladder"):
        lines.append("  sibling ladder:")
        for r in sorted(mech["ladder"], key=lambda x: -(x.get("yes") or 0))[:8]:
            tag = " [RESOLVED]" if r.get("closed") else ""
            lines.append(f"    {r.get('groupItemTitle') or r.get('question','')[:34]:<34} YES={r.get('yes')}{tag}")
    if mech.get("flags"):
        lines.append("  ⚠ FLAGS:")
        for f in mech["flags"]:
            lines.append(f"    - {f}")
    lines.append("  RULE EXCERPT: " + (mech.get("description_excerpt") or "")[:300])
    return "\n".join(lines)


if __name__ == "__main__":  # quick manual test
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cid = sys.argv[1] if len(sys.argv) > 1 else "0xac878146c9e2ee28f133d957d606684af8bb1d2ebbfb977928b203275d70ac4f"
    mech = extract_mechanics(condition_id=cid)
    print(format_mechanics_for_forager(mech))
