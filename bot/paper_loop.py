"""
Daily orchestrator. Run once per day (manually or via Windows Task Scheduler).

Flow:
  1. Fetch active geopolitics/politics markets (vol >$10k, 7-180 days to resolution)
  2. Snapshot today's price for every tracked market (for PnL computation later)
  3. Haiku triage on new/changed markets — cheap pre-filter
  4. Sonnet deep research on top N triaged-positive markets
  5. Compute edge = |claude_prob - market_price|, emit signal if edge > threshold
  6. Log everything to SQLite. No money moves.
"""
from __future__ import annotations
import asyncio
import json
import sys
from datetime import datetime, timezone

import httpx
from rich.console import Console
from rich.table import Table

import config
import db
from markets import fetch_active_markets, Market
from research import triage_batch, research_batch

console = Console()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _decide_signal(market: Market, prob: float, confidence: float) -> tuple[str | None, float, float, str | None]:
    """Return (side, executable_edge, bet_amount, no_signal_reason). side=None if no signal."""
    yes_entry = market.yes_entry_price if market.yes_entry_price is not None else market.yes_price
    no_price = market.no_price if market.no_price is not None else 1.0 - market.yes_price
    no_entry = market.no_entry_price if market.no_entry_price is not None else no_price
    yes_edge = prob - yes_entry
    no_edge = (1.0 - prob) - no_entry
    side = "YES" if yes_edge >= no_edge else "NO"
    edge = yes_edge if side == "YES" else no_edge
    if edge < config.EDGE_THRESHOLD:
        return None, edge, 0.0, "edge_below_threshold"
    if market.spread is not None and market.spread > config.MAX_SPREAD:
        return None, edge, 0.0, "spread_too_wide"
    if confidence < 0.35:
        return None, edge, 0.0, "confidence_below_threshold"
    # Quarter-Kelly on confidence-adjusted edge. Paper $1000 bankroll.
    bankroll = 1000.0
    raw = bankroll * 0.25 * edge * confidence
    bet = min(max(round(raw, 2), 1.0), 25.0)
    return side, edge, bet, None


async def run() -> None:
    db.init()
    run_date = _today_iso()
    console.rule(f"[bold cyan]Paper-trading run {run_date}")

    with db.connect() as conn:
        db.start_run(conn, run_date)

    async with httpx.AsyncClient() as http:
        console.print("[bold]1. Fetching markets...[/bold]")
        markets = await fetch_active_markets(http)
        console.print(f"   Found {len(markets)} candidate markets after filtering")
        if not markets:
            console.print("[yellow]No markets to analyze. Done.[/yellow]")
            return

    # 2. Snapshot prices for tracking
    console.print("\n[bold]2. Snapshotting prices...[/bold]")
    with db.connect() as conn:
        for m in markets:
            db.upsert_market(conn, condition_id=m.condition_id, question=m.question,
                             slug=m.slug, end_date=m.end_date)
            db.add_snapshot(conn, condition_id=m.condition_id, yes_price=m.yes_price,
                            volume=m.volume, liquidity=m.liquidity,
                            no_price=m.no_price,
                            best_bid=m.best_bid, best_ask=m.best_ask,
                            spread=m.spread,
                            yes_entry_price=m.yes_entry_price,
                            no_entry_price=m.no_entry_price)
        conn.commit()

    # 3. Haiku triage
    console.print(f"\n[bold]3. Haiku triage ({len(markets)} markets)...[/bold]")
    triaged = await triage_batch(markets, concurrency=5)
    interesting = [(m, v, r) for m, v, r in triaged if v.worth_research]
    haiku_cost = sum(r.cost_usd for _, _, r in triaged)
    console.print(f"   {len(interesting)}/{len(markets)} markets passed triage  |  cost ${haiku_cost:.4f}")

    if not interesting:
        with db.connect() as conn:
            db.finish_run(conn, run_date,
                          markets_seen=len(markets), haiku_filtered=0,
                          sonnet_analyzed=0, signals_emitted=0,
                          total_cost_usd=haiku_cost)
            conn.commit()
        return

    # Rank Haiku-positive markets by volume; analyze top N with Sonnet
    interesting.sort(key=lambda x: x[0].volume, reverse=True)
    to_deep = interesting[:config.MAX_SONNET_MARKETS_PER_DAY]
    console.print(f"\n[bold]4. Sonnet deep research on top {len(to_deep)}...[/bold]")

    deep_results = await research_batch([m for m, _, _ in to_deep], concurrency=3)
    sonnet_cost = sum(r.cost_usd for _, r in deep_results)
    console.print(f"   Done  |  cost ${sonnet_cost:.4f}")

    # 5. Emit signals
    console.print("\n[bold]5. Edge detection...[/bold]")
    analyzed: list[tuple[Market, float, float, str | None, float, float, str | None, "ResearchResult"]] = []
    for market, result in deep_results:
        if result.error or result.probability_yes is None or result.confidence is None:
            console.print(f"   [dim]skip[/dim] {market.question[:60]} — {result.error or 'no output'}")
            continue
        side, edge, bet, no_signal_reason = _decide_signal(
            market, result.probability_yes, result.confidence
        )
        analyzed.append((
            market, result.probability_yes, result.confidence, side,
            edge, bet, no_signal_reason, result,
        ))

    with db.connect() as conn:
        signals = []
        for m, prob, conf, side, edge, bet, no_signal_reason, res in analyzed:
            signal_id = None
            if side is not None:
                no_price = m.no_price if m.no_price is not None else 1.0 - m.yes_price
                yes_entry = m.yes_entry_price if m.yes_entry_price is not None else m.yes_price
                no_entry = m.no_entry_price if m.no_entry_price is not None else no_price
                yes_equivalent_entry = yes_entry if side == "YES" else 1.0 - no_entry
                side_entry_price = yes_entry if side == "YES" else no_entry
                signal_id = db.add_signal(
                    conn,
                    condition_id=m.condition_id, created_at=None,
                    model=res.model, yes_price_at_signal=yes_equivalent_entry,
                    yes_equivalent_entry=yes_equivalent_entry,
                    side_entry_price=side_entry_price,
                    claude_prob=prob, confidence=conf, side=side, edge=edge,
                    bet_amount=bet, reasoning=res.reasoning,
                    sources_json=json.dumps(res.sources),
                    tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                    cache_read_tokens=res.cache_read_tokens, cost_usd=res.cost_usd,
                    gate_status="legacy_gate_violation",
                    gate_audit_note="paper_loop legacy path does not enforce pre-bet gate",
                )
                signals.append((m, prob, conf, side, edge, bet, res))
            db.add_analysis(
                conn,
                run_date=run_date,
                condition_id=m.condition_id,
                created_at=None,
                analyst="claude-api",
                model=res.model,
                yes_price_at_analysis=m.yes_price,
                probability_yes=prob,
                confidence=conf,
                edge=edge,
                decision="signal" if side is not None else "no_signal",
                no_signal_reason=no_signal_reason,
                signal_id=signal_id,
                reasoning=res.reasoning,
                sources_json=json.dumps(res.sources),
                notes="paper_loop",
            )
        db.finish_run(conn, run_date,
                      markets_seen=len(markets),
                      haiku_filtered=len(interesting),
                      sonnet_analyzed=len(deep_results),
                      signals_emitted=len(signals),
                      total_cost_usd=round(haiku_cost + sonnet_cost, 4))
        conn.commit()

    # 6. Pretty print
    if signals:
        t = Table(title=f"Signals ({len(signals)})", show_header=True, header_style="bold cyan")
        t.add_column("Side", width=4)
        t.add_column("Market", max_width=55)
        t.add_column("Mkt", justify="right", width=6)
        t.add_column("Claude", justify="right", width=7)
        t.add_column("Edge", justify="right", width=7)
        t.add_column("Conf", justify="right", width=6)
        t.add_column("Bet", justify="right", width=6)
        for m, prob, conf, side, edge, bet, _ in signals:
            color = "bright_green" if side == "YES" else "bright_red"
            t.add_row(
                f"[{color}]{side}[/{color}]", m.question[:55],
                f"{m.yes_price:.2f}", f"{prob:.2f}",
                f"{edge:+.1%}", f"{conf:.2f}", f"${bet:.0f}",
            )
        console.print(t)
    else:
        console.print("   [dim]No edges this run.[/dim]")

    total_cost = haiku_cost + sonnet_cost
    console.print(f"\n[bold]Total cost today: ${total_cost:.4f}[/bold]")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(130)
