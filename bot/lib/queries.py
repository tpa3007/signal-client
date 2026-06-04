"""Reusable read-side DB queries. Each function takes an open sqlite3 connection."""
from __future__ import annotations


def latest_probability(conn, condition_id: str) -> float | None:
    """Most recent calibrated probability (from analyses or forecast_updates)."""
    row = conn.execute("""
        SELECT probability_yes FROM (
            SELECT created_at, probability_yes
            FROM analyses
            WHERE condition_id = ?
            UNION ALL
            SELECT created_at, updated_probability_yes AS probability_yes
            FROM forecast_updates
            WHERE condition_id = ?
        )
        ORDER BY created_at DESC LIMIT 1
    """, (condition_id, condition_id)).fetchone()
    return float(row["probability_yes"]) if row else None


def latest_execution_context(conn, condition_id: str) -> dict | None:
    """Latest snapshot enriched with executable YES/NO entry prices."""
    row = conn.execute("""
        SELECT yes_price, no_price, best_bid, best_ask, spread, yes_entry_price, no_entry_price,
               volume, liquidity, captured_at
        FROM snapshots
        WHERE condition_id = ?
        ORDER BY captured_at DESC LIMIT 1
    """, (condition_id,)).fetchone()
    if not row:
        return None
    market_price = float(row["yes_price"])
    no_price = float(row["no_price"]) if row["no_price"] is not None else 1.0 - market_price
    return {
        "market_price": market_price,
        "no_price": no_price,
        "best_bid": float(row["best_bid"]) if row["best_bid"] is not None else None,
        "best_ask": float(row["best_ask"]) if row["best_ask"] is not None else None,
        "spread": float(row["spread"]) if row["spread"] is not None else None,
        "yes_entry_price": float(row["yes_entry_price"]) if row["yes_entry_price"] is not None else market_price,
        "no_entry_price": float(row["no_entry_price"]) if row["no_entry_price"] is not None else no_price,
        "volume": row["volume"],
        "liquidity": row["liquidity"],
        "captured_at": row["captured_at"],
    }


def latest_snapshot_with_age(conn, condition_id: str, max_age_min: int) -> tuple[dict | None, float | None, bool]:
    """
    Return (row_as_dict, age_minutes, is_stale).
    row is None when no snapshot exists; is_stale=True when age > max_age_min.
    """
    row = conn.execute("""
        SELECT yes_price, no_price, best_bid, best_ask, spread,
               yes_entry_price, no_entry_price, captured_at,
               (julianday('now') - julianday(captured_at)) * 24.0 * 60.0 AS age_min
        FROM snapshots
        WHERE condition_id = ?
        ORDER BY captured_at DESC LIMIT 1
    """, (condition_id,)).fetchone()
    if not row:
        return None, None, False
    age_min = float(row["age_min"]) if row["age_min"] is not None else None
    is_stale = age_min is not None and age_min > max_age_min
    return dict(row), age_min, is_stale


def market_row(conn, condition_id: str):
    return conn.execute(
        "SELECT question FROM markets WHERE condition_id = ?", (condition_id,)
    ).fetchone()


def research_completeness(conn, condition_id: str) -> dict:
    """Weighted 0-100 completeness score across the 7 research-memory tables."""
    counts = {
        "analyses": conn.execute(
            "SELECT COUNT(*) AS n FROM analyses WHERE condition_id = ?", (condition_id,)
        ).fetchone()["n"],
        "evidence": conn.execute(
            "SELECT COUNT(*) AS n FROM evidence WHERE condition_id = ?", (condition_id,)
        ).fetchone()["n"],
        "actors": conn.execute(
            "SELECT COUNT(*) AS n FROM actor_maps WHERE condition_id = ?", (condition_id,)
        ).fetchone()["n"],
        "causal_factors": conn.execute(
            "SELECT COUNT(*) AS n FROM causal_factors WHERE condition_id = ?", (condition_id,)
        ).fetchone()["n"],
        "anomalies": conn.execute(
            "SELECT COUNT(*) AS n FROM anomalies WHERE condition_id = ?", (condition_id,)
        ).fetchone()["n"],
        "scenarios": conn.execute(
            "SELECT COUNT(*) AS n FROM scenario_trees WHERE condition_id = ?", (condition_id,)
        ).fetchone()["n"],
        "premortems": conn.execute(
            "SELECT COUNT(*) AS n FROM premortems WHERE condition_id = ?", (condition_id,)
        ).fetchone()["n"],
        "hidden_gem_reviews": conn.execute(
            "SELECT COUNT(*) AS n FROM hidden_gem_reviews WHERE condition_id = ?", (condition_id,)
        ).fetchone()["n"],
    }
    checks = {
        "has_analysis": counts["analyses"] >= 1,
        "has_evidence_base": counts["evidence"] >= 2,
        "has_actor_map": counts["actors"] >= 1,
        "has_causal_model": counts["causal_factors"] >= 2,
        "has_scenario_tree": counts["scenarios"] >= 3,
        "has_premortem": counts["premortems"] >= 1,
        "has_hidden_gem_review": counts["hidden_gem_reviews"] >= 1,
    }
    weights = {
        "has_analysis": 0.16,
        "has_evidence_base": 0.18,
        "has_actor_map": 0.12,
        "has_causal_model": 0.18,
        "has_scenario_tree": 0.14,
        "has_premortem": 0.14,
        "has_hidden_gem_review": 0.08,
    }
    score = round(100.0 * sum(weights[k] for k, ok in checks.items() if ok), 1)
    missing = [k for k, ok in checks.items() if not ok]
    return {"score": score, "counts": counts, "checks": checks, "missing": missing}
