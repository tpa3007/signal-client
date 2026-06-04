"""Status reports — daily summary, weekly stats, signal performance."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone, timedelta

from rich.console import Console
from rich.table import Table

import db
import config

console = Console()


def _resolve_pending_signals() -> int:
    """For signals on markets that have since closed, compute realized PnL."""
    n = 0
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT s.id, s.condition_id, s.side, s.yes_price_at_signal, s.bet_amount,
                   m.resolved, m.resolved_yes
            FROM signals s
            JOIN markets m ON m.condition_id = s.condition_id
            WHERE s.resolved = 0
        """).fetchall()
        for r in rows:
            if not r["resolved"] or r["resolved_yes"] is None:
                continue
            yes = r["resolved_yes"]
            entry = r["yes_price_at_signal"]
            bet = r["bet_amount"]
            if r["side"] == "YES":
                pnl = bet * (1.0 / entry - 1) if yes > 0.5 else -bet
            else:
                pnl = bet * (1.0 / (1 - entry) - 1) if yes < 0.5 else -bet
            conn.execute("UPDATE signals SET resolved = 1, realized_pnl = ? WHERE id = ?",
                         (round(pnl, 2), r["id"]))
            n += 1
        conn.commit()
    return n


def daily_summary() -> None:
    db.init()
    with db.connect() as conn:
        runs = conn.execute("""
            SELECT r.*, COALESCE(a.analysis_count, 0) AS analysis_count
            FROM daily_runs r
            LEFT JOIN (
                SELECT run_date, COUNT(*) AS analysis_count
                FROM analyses GROUP BY run_date
            ) a ON a.run_date = r.run_date
            ORDER BY r.run_date DESC LIMIT 14
        """).fetchall()
    t = Table(title="Recent runs", show_header=True, header_style="bold cyan")
    for c in ("Date", "Seen", "Triaged", "Deep", "Analyses", "Signals", "Cost"):
        t.add_column(c, justify="right" if c != "Date" else "left")
    for r in runs:
        t.add_row(
            r["run_date"], str(r["markets_seen"] or 0),
            str(r["haiku_filtered"] or 0), str(r["sonnet_analyzed"] or 0),
            str(r["analysis_count"] or 0),
            str(r["signals_emitted"] or 0),
            f"${(r['total_cost_usd'] or 0):.4f}",
        )
    console.print(t)

    with db.connect() as conn:
        total = conn.execute("SELECT SUM(total_cost_usd) AS s FROM daily_runs").fetchone()
        analyses = conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"]
        evidence = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
        reviews = conn.execute("SELECT COUNT(*) AS n FROM hidden_gem_reviews").fetchone()["n"]
        actors = conn.execute("SELECT COUNT(*) AS n FROM actor_maps").fetchone()["n"]
        factors = conn.execute("SELECT COUNT(*) AS n FROM causal_factors").fetchone()["n"]
        anomalies = conn.execute("SELECT COUNT(*) AS n FROM anomalies").fetchone()["n"]
        scenarios = conn.execute("SELECT COUNT(*) AS n FROM scenario_trees").fetchone()["n"]
        premortems = conn.execute("SELECT COUNT(*) AS n FROM premortems").fetchone()["n"]
        signals = conn.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]
        console.print(f"\n[bold]Cumulative spend: ${(total['s'] or 0):.4f}[/bold]")
        rate = (signals / analyses * 100) if analyses else 0.0
        console.print(f"[bold]Research log: {analyses} analyses -> {signals} signals ({rate:.1f}%)[/bold]")
        console.print(f"[bold]Research memory: {evidence} evidence items, {reviews} hidden-gem reviews[/bold]")
        console.print(
            f"[bold]Contrarian memory: {actors} actors, {factors} factors, "
            f"{anomalies} anomalies, {scenarios} scenarios, {premortems} premortems[/bold]"
        )
        resolved = conn.execute("""
            SELECT a.probability_yes, a.yes_price_at_analysis, m.resolved_yes
            FROM analyses a JOIN markets m ON m.condition_id = a.condition_id
            WHERE m.resolved = 1 AND m.resolved_yes IS NOT NULL
        """).fetchall()
        if resolved:
            brier = []
            market_brier = []
            for r in resolved:
                y = 1.0 if float(r["resolved_yes"]) > 0.5 else 0.0
                brier.append((float(r["probability_yes"]) - y) ** 2)
                market_brier.append((float(r["yes_price_at_analysis"]) - y) ** 2)
            avg_brier = sum(brier) / len(brier)
            avg_market = sum(market_brier) / len(market_brier)
            console.print(
                f"[bold]Forecast quality: {len(resolved)} resolved, "
                f"Brier {avg_brier:.3f}, market {avg_market:.3f}, "
                f"relative {avg_market - avg_brier:+.3f}[/bold]"
            )


def open_signals() -> None:
    db.init()
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT s.*, m.question, m.end_date,
                   CASE WHEN s.side = 'NO'
                        THEN 1.0 - s.yes_price_at_signal
                        ELSE s.yes_price_at_signal END AS side_entry_price
            FROM signals s JOIN markets m ON m.condition_id = s.condition_id
            WHERE s.resolved = 0
            ORDER BY s.created_at DESC LIMIT 50
        """).fetchall()
    if not rows:
        console.print("[dim]No open signals.[/dim]")
        return
    t = Table(title=f"Open signals ({len(rows)})", show_header=True, header_style="bold green")
    t.add_column("Date")
    t.add_column("Side", width=4)
    t.add_column("Market", max_width=50)
    t.add_column("Entry", justify="right")
    t.add_column("Claude", justify="right")
    t.add_column("Edge", justify="right")
    t.add_column("Bet", justify="right")
    for r in rows:
        color = "bright_green" if r["side"] == "YES" else "bright_red"
        t.add_row(
            r["created_at"][:10],
            f"[{color}]{r['side']}[/{color}]",
            (r["question"] or "")[:50],
            f"{r['side_entry_price']:.2f}",
            f"{r['claude_prob']:.2f}",
            f"{r['edge']:+.1%}",
            f"${r['bet_amount']:.0f}",
        )
    console.print(t)


def closed_performance() -> None:
    db.init()
    n_new = _resolve_pending_signals()
    if n_new:
        console.print(f"[dim]Resolved {n_new} signals into PnL.[/dim]\n")
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT s.*, m.question
            FROM signals s JOIN markets m ON m.condition_id = s.condition_id
            WHERE s.resolved = 1
            ORDER BY s.created_at DESC
        """).fetchall()
    if not rows:
        console.print("[dim]No closed signals yet.[/dim]")
        return
    wins = sum(1 for r in rows if (r["realized_pnl"] or 0) > 0)
    total_pnl = sum(r["realized_pnl"] or 0 for r in rows)
    total_bet = sum(r["bet_amount"] for r in rows)
    console.print(
        f"[bold]Closed: {len(rows)}  |  Wins: {wins} ({wins/len(rows)*100:.0f}%)  |  "
        f"PnL: ${total_pnl:+.2f}  |  ROI: {total_pnl/total_bet*100:+.1f}%[/bold]"
    )


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("all", "daily"):
        daily_summary(); print()
    if cmd in ("all", "open"):
        open_signals(); print()
    if cmd in ("all", "closed"):
        closed_performance()
