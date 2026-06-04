"""
Polymarket research bot — terminal dashboard (Bloomberg-style).

Usage:
    python dashboard.py            # one-shot snapshot
    python dashboard.py --live     # auto-refresh every 10s
"""
from __future__ import annotations
import io
import sys
import time
import json
from datetime import datetime, timezone

# Force UTF-8 stdout on Windows for box-drawing chars
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

import db
import config

console = Console()

ACCENT = "bright_green"
BORDER = "bright_green"
DIM = "bright_black"
WIN = "bright_green"
LOSS = "red"
WARN = "yellow"
HEAD = "bold bright_green"


# ---------- Data loaders ----------

def _load_summary() -> dict:
    """One-shot summary stats from SQLite."""
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]
        wins = conn.execute(
            "SELECT COUNT(*) AS n FROM signals WHERE resolved=1 AND realized_pnl>0"
        ).fetchone()["n"]
        losses = conn.execute(
            "SELECT COUNT(*) AS n FROM signals WHERE resolved=1 AND realized_pnl<=0"
        ).fetchone()["n"]
        opens = conn.execute(
            "SELECT COUNT(*) AS n FROM signals WHERE resolved=0"
        ).fetchone()["n"]
        pnl_row = conn.execute(
            "SELECT SUM(realized_pnl) AS p, SUM(bet_amount) AS b FROM signals WHERE resolved=1"
        ).fetchone()
        pnl = pnl_row["p"] or 0.0
        wagered_closed = pnl_row["b"] or 0.0
        wagered_all = conn.execute(
            "SELECT SUM(bet_amount) AS b FROM signals"
        ).fetchone()["b"] or 0.0
        avg_edge_row = conn.execute(
            "SELECT AVG(edge) AS e FROM signals"
        ).fetchone()
        avg_edge = avg_edge_row["e"] or 0.0
        best = conn.execute(
            "SELECT MAX(realized_pnl) AS p FROM signals WHERE resolved=1"
        ).fetchone()["p"] or 0.0
        worst = conn.execute(
            "SELECT MIN(realized_pnl) AS p FROM signals WHERE resolved=1"
        ).fetchone()["p"] or 0.0
        last_run = conn.execute(
            "SELECT * FROM daily_runs ORDER BY run_date DESC LIMIT 1"
        ).fetchone()
        total_api_cost = conn.execute(
            "SELECT SUM(total_cost_usd) AS s FROM daily_runs"
        ).fetchone()["s"] or 0.0
    closed = wins + losses
    return {
        "total": total, "wins": wins, "losses": losses, "opens": opens,
        "closed": closed,
        "win_rate": (wins / closed * 100) if closed else None,
        "pnl": pnl, "roi": (pnl / wagered_closed * 100) if wagered_closed else None,
        "wagered_all": wagered_all, "avg_edge": avg_edge * 100,
        "best": best, "worst": worst,
        "last_run": last_run, "total_api_cost": total_api_cost,
    }


def _load_open_signals(limit: int = 12) -> list:
    with db.connect() as conn:
        return conn.execute("""
            SELECT s.*, m.question, m.end_date
            FROM signals s JOIN markets m ON m.condition_id = s.condition_id
            WHERE s.resolved = 0
            ORDER BY s.created_at DESC LIMIT ?
        """, (limit,)).fetchall()


def _load_closed_signals(limit: int = 10) -> list:
    with db.connect() as conn:
        return conn.execute("""
            SELECT s.*, m.question
            FROM signals s JOIN markets m ON m.condition_id = s.condition_id
            WHERE s.resolved = 1
            ORDER BY s.created_at DESC LIMIT ?
        """, (limit,)).fetchall()


def _load_recent_runs(limit: int = 7) -> list:
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM daily_runs ORDER BY run_date DESC LIMIT ?", (limit,)
        ).fetchall()


# ---------- Panels ----------

def _header() -> Panel:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    bar = Text()
    bar.append("POLYMARKET RESEARCH BOT", style=HEAD)
    bar.append("   |   ", style=DIM)
    bar.append("paper-trading", style="yellow")
    bar.append("   |   ", style=DIM)
    bar.append(now, style=DIM)
    return Panel(Align.left(bar), border_style=BORDER, box=box.SQUARE, padding=(0, 1))


def _status_panel(s: dict) -> Panel:
    t = Table.grid(padding=(0, 2), expand=True)
    t.add_column(style="bold", min_width=18)
    t.add_column(justify="right")

    last = s["last_run"]
    if last:
        date = last["run_date"]
        seen = last["markets_seen"] or 0
        deep = last["sonnet_analyzed"] or 0
        sigs = last["signals_emitted"] or 0
    else:
        date, seen, deep, sigs = "—", 0, 0, 0

    t.add_row("Status", Text("[*] ACTIVE", style=ACCENT))
    t.add_row("Last run", Text(str(date), style=ACCENT))
    t.add_row("Markets scanned", Text(str(seen), style=ACCENT))
    t.add_row("Deep analyzed", Text(str(deep), style=ACCENT))
    t.add_row("Signals emitted", Text(str(sigs), style=ACCENT))
    t.add_row("", "")
    t.add_row("Edge threshold", Text(f"≥ {config.EDGE_THRESHOLD*100:.0f}%", style="cyan"))
    t.add_row("Min volume", Text(f"${config.MIN_VOLUME_USD:,.0f}", style="cyan"))
    t.add_row("Resolution window",
              Text(f"{config.MIN_DAYS_TO_RESOLUTION}–{config.MAX_DAYS_TO_RESOLUTION}d", style="cyan"))
    t.add_row("Mode", Text("PAPER", style="yellow bold"))
    t.add_row("API cost (cum.)", Text(f"${s['total_api_cost']:.4f}", style=DIM))

    return Panel(t, title=Text("PIPELINE STATUS", style=HEAD),
                 border_style=BORDER, box=box.SQUARE, padding=(0, 1))


def _performance_panel(s: dict) -> Panel:
    t = Table.grid(padding=(0, 2), expand=True)
    t.add_column(style="bold", min_width=18)
    t.add_column(justify="right")

    t.add_row("Total signals", Text(str(s["total"]), style=ACCENT))
    wl = Text()
    wl.append(f"{s['wins']}W", style=WIN)
    wl.append(" / ", style=DIM)
    wl.append(f"{s['losses']}L", style=LOSS)
    wl.append(" / ", style=DIM)
    wl.append(f"{s['opens']}P", style=WARN)
    t.add_row("Win / Loss / Open", wl)

    if s["win_rate"] is not None:
        wrc = WIN if s["win_rate"] >= 55 else WARN if s["win_rate"] >= 45 else LOSS
        t.add_row("Win rate", Text(f"{s['win_rate']:.1f}%", style=wrc))
    else:
        t.add_row("Win rate", Text("—", style=DIM))

    t.add_row("", "")
    pnl_style = WIN if s["pnl"] >= 0 else LOSS
    pnl_str = f"+${s['pnl']:.2f}" if s["pnl"] >= 0 else f"-${abs(s['pnl']):.2f}"
    t.add_row("Realized PnL", Text(pnl_str, style=pnl_style))

    if s["roi"] is not None:
        roi_style = WIN if s["roi"] >= 0 else LOSS
        t.add_row("ROI", Text(f"{s['roi']:+.1f}%", style=roi_style))
    else:
        t.add_row("ROI", Text("—", style=DIM))

    t.add_row("Wagered (cum.)", Text(f"${s['wagered_all']:.2f}", style="cyan"))
    t.add_row("Avg edge", Text(f"{s['avg_edge']:.1f}%", style="cyan"))

    t.add_row("", "")
    if s["closed"]:
        t.add_row("Best trade",
                  Text(f"+${s['best']:.2f}", style=WIN))
        t.add_row("Worst trade",
                  Text(f"-${abs(s['worst']):.2f}", style=LOSS))
    else:
        t.add_row("Best trade", Text("—", style=DIM))
        t.add_row("Worst trade", Text("—", style=DIM))

    return Panel(t, title=Text("PERFORMANCE", style=HEAD),
                 border_style=BORDER, box=box.SQUARE, padding=(0, 1))


def _open_signals_panel(rows: list) -> Panel:
    t = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan",
              expand=True, pad_edge=False)
    t.add_column("Date", width=10)
    t.add_column("Side", width=4, justify="center")
    t.add_column("Market", overflow="ellipsis", no_wrap=True)
    t.add_column("Mkt", justify="right", width=6)
    t.add_column("Cl", justify="right", width=6)
    t.add_column("Edge", justify="right", width=7)
    t.add_column("Conf", justify="right", width=5)
    t.add_column("Bet", justify="right", width=7)
    t.add_column("Resolves", width=10)

    if not rows:
        t.add_row("", "", "[dim]no open signals[/dim]", "", "", "", "", "", "")
    for r in rows:
        side_style = WIN if r["side"] == "YES" else LOSS
        t.add_row(
            r["created_at"][:10],
            Text(r["side"], style=side_style),
            (r["question"] or "")[:60],
            f"{r['yes_price_at_signal']:.2f}",
            f"{r['claude_prob']:.2f}",
            f"{r['edge']*100:+.1f}%",
            f"{r['confidence']:.2f}",
            f"${r['bet_amount']:.0f}",
            (r["end_date"] or "")[:10],
        )
    return Panel(t, title=Text(f"OPEN SIGNALS ({len(rows)})", style=HEAD),
                 border_style=BORDER, box=box.SQUARE, padding=(0, 1))


def _closed_signals_panel(rows: list) -> Panel:
    t = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan",
              expand=True, pad_edge=False)
    t.add_column("Date", width=10)
    t.add_column("Side", width=4, justify="center")
    t.add_column("Market", overflow="ellipsis", no_wrap=True)
    t.add_column("Entry", justify="right", width=6)
    t.add_column("Bet", justify="right", width=7)
    t.add_column("PnL", justify="right", width=9)
    t.add_column("Result", width=7)

    if not rows:
        t.add_row("", "", "[dim]no closed signals yet[/dim]", "", "", "", "")
    for r in rows:
        side_style = WIN if r["side"] == "YES" else LOSS
        pnl = r["realized_pnl"] or 0
        pnl_style = WIN if pnl > 0 else LOSS
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        result = Text("WIN", style=WIN) if pnl > 0 else Text("LOSS", style=LOSS)
        t.add_row(
            r["created_at"][:10],
            Text(r["side"], style=side_style),
            (r["question"] or "")[:60],
            f"{r['yes_price_at_signal']:.2f}",
            f"${r['bet_amount']:.0f}",
            Text(pnl_str, style=pnl_style),
            result,
        )
    return Panel(t, title=Text(f"RECENT CLOSED ({len(rows)})", style=HEAD),
                 border_style=BORDER, box=box.SQUARE, padding=(0, 1))


def _runs_panel(rows: list) -> Panel:
    t = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan",
              expand=True, pad_edge=False)
    t.add_column("Date", width=10)
    t.add_column("Seen", justify="right", width=5)
    t.add_column("Deep", justify="right", width=5)
    t.add_column("Sigs", justify="right", width=5)
    t.add_column("Cost", justify="right", width=8)

    for r in rows:
        t.add_row(
            r["run_date"],
            str(r["markets_seen"] or 0),
            str(r["sonnet_analyzed"] or 0),
            str(r["signals_emitted"] or 0),
            f"${(r['total_cost_usd'] or 0):.4f}",
        )
    return Panel(t, title=Text("RECENT RUNS", style=HEAD),
                 border_style=BORDER, box=box.SQUARE, padding=(0, 1))


# ---------- Layout ----------

def render() -> Layout:
    s = _load_summary()
    open_sigs = _load_open_signals()
    closed = _load_closed_signals()
    runs = _load_recent_runs()

    layout = Layout()
    layout.split_column(
        Layout(_header(), name="head", size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=2),
        Layout(name="right", ratio=1),
    )
    layout["left"].split_column(
        Layout(_open_signals_panel(open_sigs), name="open"),
        Layout(_closed_signals_panel(closed), name="closed"),
    )
    layout["right"].split_column(
        Layout(_status_panel(s), name="status"),
        Layout(_performance_panel(s), name="perf"),
        Layout(_runs_panel(runs), name="runs"),
    )
    return layout


def main():
    db.init()
    if "--live" in sys.argv:
        with Live(render(), refresh_per_second=0.1, screen=False, console=console) as live:
            try:
                while True:
                    time.sleep(10)
                    live.update(render())
            except KeyboardInterrupt:
                pass
    else:
        console.print(render())


if __name__ == "__main__":
    main()
