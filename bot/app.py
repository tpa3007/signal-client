"""
Polymarket research bot — Streamlit web dashboard.

Run:
    streamlit run app.py

Opens at http://localhost:8501. Auto-refreshes every 30s.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st
import altair as alt

import config
import db

# ---------------- Page setup ----------------

st.set_page_config(
    page_title="Polymarket Research Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
    .main > div { padding-top: 1rem; }
    [data-testid="stMetricValue"] { font-size: 1.8rem; }
    [data-testid="stMetric"] {
        background: rgba(0, 255, 100, 0.04);
        border: 1px solid rgba(0, 255, 100, 0.15);
        border-radius: 6px;
        padding: 12px 16px;
    }
    h1 { font-family: 'JetBrains Mono', monospace; color: #00ff64; letter-spacing: 0.05em; }
    h2 { color: #00ff64; border-bottom: 1px solid rgba(0,255,100,0.2); padding-bottom: 4px; }
    .stTabs [data-baseweb="tab"] { font-weight: 600; }
    .stTabs [aria-selected="true"] { color: #00ff64; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ---------------- Data ----------------

db.init()


@st.cache_data(ttl=20)
def load_signals() -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT s.id, s.condition_id, s.created_at, s.model,
                   s.yes_price_at_signal AS yes_equivalent_price,
                   CASE WHEN s.side = 'NO'
                        THEN 1.0 - s.yes_price_at_signal
                        ELSE s.yes_price_at_signal END AS market_price,
                   s.claude_prob, s.confidence, s.side, s.edge, s.bet_amount,
                   s.reasoning, s.sources_json, s.cost_usd,
                   s.resolved, s.realized_pnl,
                   COALESCE(s.real_money, 0) AS real_money,
                   s.real_entry_price, s.real_bet_usd, s.real_shares,
                   s.real_filled_at, s.real_max_payout, s.real_pnl_actual,
                   m.question, m.end_date, m.resolved_yes,
                   COALESCE(m.vertical,'unknown') AS vertical
            FROM signals s
            LEFT JOIN markets m ON m.condition_id = s.condition_id
            ORDER BY s.created_at DESC
        """, conn, parse_dates=["created_at", "end_date"])
    if not df.empty:
        df["sources"] = df["sources_json"].apply(
            lambda s: json.loads(s) if s else []
        )
    return df


@st.cache_data(ttl=20)
def load_analyses() -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT a.id, a.run_date, a.condition_id, a.created_at, a.analyst,
                   a.model, a.yes_price_at_analysis AS market_price,
                   a.probability_yes, a.confidence, a.edge, a.decision,
                   a.no_signal_reason, a.signal_id, a.reasoning, a.sources_json,
                   m.question, m.end_date, m.resolved, m.resolved_yes,
                   COALESCE(m.vertical,'unknown') AS vertical
            FROM analyses a
            LEFT JOIN markets m ON m.condition_id = a.condition_id
            ORDER BY a.created_at DESC
        """, conn, parse_dates=["created_at", "end_date"])
    if not df.empty:
        df["sources"] = df["sources_json"].apply(
            lambda s: json.loads(s) if s else []
        )
    return df


@st.cache_data(ttl=20)
def load_runs() -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT run_date, started_at, finished_at,
                   markets_seen, haiku_filtered AS triaged,
                   sonnet_analyzed AS deep, signals_emitted, total_cost_usd
            FROM daily_runs ORDER BY run_date DESC
        """, conn, parse_dates=["run_date", "started_at", "finished_at"])
    return df


@st.cache_data(ttl=20)
def load_market_snapshots(condition_id: str) -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT captured_at, yes_price, no_price, best_bid, best_ask, spread,
                   yes_entry_price, no_entry_price, volume
            FROM snapshots
            WHERE condition_id = ?
            ORDER BY captured_at ASC
        """, conn, params=(condition_id,), parse_dates=["captured_at"])
    return df


@st.cache_data(ttl=20)
def load_hidden_gem_reviews() -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT h.*, m.question, m.end_date, COALESCE(m.vertical,'unknown') AS vertical
            FROM hidden_gem_reviews h
            LEFT JOIN markets m ON m.condition_id = h.condition_id
            ORDER BY h.total_score DESC, h.created_at DESC
        """, conn, parse_dates=["created_at", "end_date"])
    return df


@st.cache_data(ttl=20)
def load_evidence() -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT e.*, m.question, COALESCE(m.vertical,'unknown') AS vertical
            FROM evidence e
            LEFT JOIN markets m ON m.condition_id = e.condition_id
            ORDER BY e.created_at DESC
        """, conn, parse_dates=["created_at"])
    return df


@st.cache_data(ttl=20)
def load_anomalies() -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT a.*, m.question, COALESCE(m.vertical,'unknown') AS vertical
            FROM anomalies a
            LEFT JOIN markets m ON m.condition_id = a.condition_id
            ORDER BY a.severity DESC, a.created_at DESC
        """, conn, parse_dates=["created_at"])
    return df


@st.cache_data(ttl=20)
def load_causal_factors() -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT c.*, m.question, COALESCE(m.vertical,'unknown') AS vertical
            FROM causal_factors c
            LEFT JOIN markets m ON m.condition_id = c.condition_id
            ORDER BY c.importance DESC, c.created_at DESC
        """, conn, parse_dates=["created_at"])
    return df


@st.cache_data(ttl=20)
def load_premortems() -> pd.DataFrame:
    with db.connect() as conn:
        df = pd.read_sql_query("""
            SELECT p.*, m.question, COALESCE(m.vertical,'unknown') AS vertical
            FROM premortems p
            LEFT JOIN markets m ON m.condition_id = p.condition_id
            ORDER BY p.severity DESC, p.created_at DESC
        """, conn, parse_dates=["created_at"])
    return df


signals = load_signals()
analyses = load_analyses()
runs = load_runs()
hidden_reviews = load_hidden_gem_reviews()
evidence = load_evidence()
anomalies = load_anomalies()
causal_factors = load_causal_factors()
premortems = load_premortems()

# ---------------- Header ----------------

st.markdown("# POLYMARKET RESEARCH BOT")
sub_col1, sub_col2 = st.columns([3, 1])
with sub_col1:
    st.caption("Paper-trading geopolitics + politics vertical · powered by Claude Desktop MCP")
with sub_col2:
    st.caption(f"Refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

# ---------------- KPI row ----------------

total = len(signals)
total_analyses = len(analyses)
closed = signals[signals["resolved"] == 1] if total else signals
opens = signals[signals["resolved"] == 0] if total else signals
wins = int((closed["realized_pnl"] > 0).sum()) if len(closed) else 0
losses = int((closed["realized_pnl"] <= 0).sum()) if len(closed) else 0
win_rate = (wins / len(closed) * 100) if len(closed) else None
total_pnl = float(closed["realized_pnl"].sum()) if len(closed) else 0.0
wagered_closed = float(closed["bet_amount"].sum()) if len(closed) else 0.0
roi = (total_pnl / wagered_closed * 100) if wagered_closed else None
wagered_all = float(signals["bet_amount"].sum()) if total else 0.0
signal_rate = (total / total_analyses * 100) if total_analyses else None

k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
k1.metric("Analyses", total_analyses)
k2.metric("Signals", total, f"{signal_rate:.1f}% rate" if signal_rate is not None else None)
k3.metric("Closed", len(closed), f"{wins}W / {losses}L" if len(closed) else None)
k4.metric("Win rate", f"{win_rate:.1f}%" if win_rate is not None else "—")
pnl_delta = f"{total_pnl:+.2f}" if len(closed) else None
k5.metric("Realized PnL", f"${total_pnl:+.2f}", pnl_delta, delta_color="off")
k6.metric("ROI", f"{roi:+.1f}%" if roi is not None else "—")
k7.metric("Wagered", f"${wagered_all:.2f}")

st.divider()

# ---------------- Tabs ----------------

live_positions = signals[signals["real_money"] == 1] if total else signals
tab_live, tab_research, tab_open, tab_closed, tab_pnl, tab_vert, tab_runs, tab_detail = st.tabs([
    f"💰 LIVE ({len(live_positions)})",
    f"🧪 Research Log ({len(analyses)})",
    f"🎯 Paper Open ({len(opens)})",
    f"✅ Closed ({len(closed)})",
    "📈 PnL chart",
    "🧭 By vertical",
    f"📅 Runs ({len(runs)})",
    "🔍 Signal detail",
])

with tab_live:
    if len(live_positions) == 0:
        st.info("No real-money positions yet. Use `mark_live_position` or `record_live_position` MCP tool to register one.")
    else:
        open_live = live_positions[live_positions["resolved"] == 0]
        closed_live = live_positions[live_positions["resolved"] == 1]
        total_at_risk = float(open_live["real_bet_usd"].sum()) if len(open_live) else 0.0
        total_potential = float(open_live["real_max_payout"].sum()) if len(open_live) else 0.0
        total_realized = float(closed_live["real_pnl_actual"].fillna(0).sum()) if len(closed_live) else 0.0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Open positions", len(open_live))
        c2.metric("Closed positions", len(closed_live))
        c3.metric("At risk", f"${total_at_risk:.2f}")
        c4.metric("Max potential", f"${total_potential:.2f}",
                  f"{total_potential/total_at_risk:.2f}x" if total_at_risk else None,
                  delta_color="off")
        c5.metric("Realized PnL", f"${total_realized:+.2f}",
                  delta_color="off")

        st.subheader("Open live positions")
        if len(open_live):
            df = open_live[[
                "id", "real_filled_at", "side", "question", "real_entry_price",
                "real_bet_usd", "real_shares", "real_max_payout", "end_date",
                "claude_prob",
            ]].copy()
            df["real_filled_at"] = pd.to_datetime(df["real_filled_at"]).dt.strftime("%Y-%m-%d")
            df["end_date"] = df["end_date"].dt.strftime("%Y-%m-%d")
            df["potential_x"] = (df["real_max_payout"] / df["real_bet_usd"]).round(2)
            df = df.rename(columns={
                "id": "ID", "real_filled_at": "Filled", "side": "Side",
                "question": "Market", "real_entry_price": "Entry",
                "real_bet_usd": "Bet", "real_shares": "Shares",
                "real_max_payout": "Max payout", "end_date": "Resolves",
                "claude_prob": "Claude P", "potential_x": "X multiplier",
            })
            st.dataframe(df, hide_index=True, width="stretch",
                column_config={
                    "Entry": st.column_config.NumberColumn(format="%.3f"),
                    "Bet": st.column_config.NumberColumn(format="$%.2f"),
                    "Shares": st.column_config.NumberColumn(format="%.2f"),
                    "Max payout": st.column_config.NumberColumn(format="$%.2f"),
                    "Claude P": st.column_config.NumberColumn(format="%.2f"),
                    "X multiplier": st.column_config.NumberColumn(format="%.2fx"),
                    "Market": st.column_config.TextColumn(width="large"),
                },
            )

        if len(closed_live):
            st.subheader("Closed live positions")
            df = closed_live[[
                "real_filled_at", "side", "question", "real_entry_price",
                "real_bet_usd", "real_pnl_actual",
            ]].copy()
            df["real_filled_at"] = pd.to_datetime(df["real_filled_at"]).dt.strftime("%Y-%m-%d")
            df["result"] = df["real_pnl_actual"].apply(
                lambda p: "WIN" if (p or 0) > 0 else "LOSS"
            )
            df = df.rename(columns={
                "real_filled_at": "Date", "side": "Side", "question": "Market",
                "real_entry_price": "Entry", "real_bet_usd": "Bet",
                "real_pnl_actual": "PnL", "result": "Result",
            })
            st.dataframe(df, hide_index=True, width="stretch",
                column_config={
                    "Entry": st.column_config.NumberColumn(format="%.3f"),
                    "Bet": st.column_config.NumberColumn(format="$%.2f"),
                    "PnL": st.column_config.NumberColumn(format="$%+.2f"),
                    "Market": st.column_config.TextColumn(width="large"),
                },
            )

        # Calendar of upcoming resolutions
        st.subheader("Resolution calendar")
        if len(open_live):
            cal = open_live.sort_values("end_date")[
                ["end_date", "side", "question", "real_bet_usd", "real_max_payout"]
            ].copy()
            cal["end_date"] = pd.to_datetime(cal["end_date"]).dt.strftime("%Y-%m-%d")
            cal["days"] = ((pd.to_datetime(open_live.sort_values("end_date")["end_date"]).dt.tz_localize(None)
                            - pd.Timestamp.utcnow().tz_localize(None)).dt.days)
            cal = cal.rename(columns={
                "end_date": "Resolves", "side": "Side", "question": "Market",
                "real_bet_usd": "Bet", "real_max_payout": "Max",
            })
            cal = cal[["Resolves", "days", "Side", "Market", "Bet", "Max"]]
            cal = cal.rename(columns={"days": "Days left"})
            st.dataframe(cal, hide_index=True, width="stretch",
                column_config={
                    "Bet": st.column_config.NumberColumn(format="$%.2f"),
                    "Max": st.column_config.NumberColumn(format="$%.2f"),
                    "Market": st.column_config.TextColumn(width="large"),
                },
            )

with tab_research:
    if len(analyses) == 0:
        st.info("No analyses logged yet. Run `record_analysis` after researching a market.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        signals_logged = int((analyses["decision"] == "signal").sum())
        no_signal = int((analyses["decision"] == "no_signal").sum())
        avg_edge = float(analyses["edge"].mean()) if len(analyses) else 0.0
        avg_conf = float(analyses["confidence"].mean()) if len(analyses) else 0.0
        c1.metric("Analyses", len(analyses))
        c2.metric("Signals", signals_logged, f"{signals_logged/len(analyses)*100:.1f}%")
        c3.metric("No-signal", no_signal)
        c4.metric("Avg edge/conf", f"{avg_edge:.1%} / {avg_conf:.2f}")

        df = analyses[[
            "created_at", "decision", "no_signal_reason", "vertical", "question",
            "market_price", "probability_yes", "edge", "confidence", "signal_id",
        ]].copy()
        df["created_at"] = df["created_at"].dt.strftime("%Y-%m-%d %H:%M")
        df = df.rename(columns={
            "created_at": "Time",
            "decision": "Decision",
            "no_signal_reason": "Reason",
            "vertical": "Vertical",
            "question": "Market",
            "market_price": "Mkt",
            "probability_yes": "Estimate",
            "edge": "Edge",
            "confidence": "Conf",
            "signal_id": "Signal",
        })
        st.dataframe(
            df, hide_index=True, width="stretch",
            column_config={
                "Mkt": st.column_config.NumberColumn(format="%.2f"),
                "Estimate": st.column_config.NumberColumn(format="%.2f"),
                "Edge": st.column_config.NumberColumn(format="%.1%"),
                "Conf": st.column_config.NumberColumn(format="%.2f"),
                "Market": st.column_config.TextColumn(width="large"),
            },
        )

        st.subheader("Decision mix")
        mix_df = analyses.groupby(["decision", "no_signal_reason"], dropna=False).size().reset_index(name="count")
        mix_df["no_signal_reason"] = mix_df["no_signal_reason"].fillna("signal")
        mix_chart = alt.Chart(mix_df).mark_bar().encode(
            x=alt.X("count:Q", title="Count"),
            y=alt.Y("no_signal_reason:N", title="Reason"),
            color=alt.Color("decision:N", title="Decision"),
            tooltip=["decision", "no_signal_reason", "count"],
        ).properties(height=260)
        st.altair_chart(mix_chart, width="stretch")

    st.subheader("Hidden-gem layer")
    if len(hidden_reviews) == 0:
        st.info("No hidden-gem reviews yet. Use `record_hidden_gem_review` after the evidence and skeptic pass.")
    else:
        gem_df = hidden_reviews[[
            "created_at", "decision", "total_score", "vertical", "question",
            "executable_edge", "attention_gap_score", "evidence_asymmetry_score",
            "stale_price_score", "catalyst_score", "next_check_at",
        ]].copy()
        gem_df["created_at"] = gem_df["created_at"].dt.strftime("%Y-%m-%d %H:%M")
        gem_df = gem_df.rename(columns={
            "created_at": "Time",
            "decision": "Decision",
            "total_score": "Score",
            "vertical": "Vertical",
            "question": "Market",
            "executable_edge": "Exec edge",
            "attention_gap_score": "Attention gap",
            "evidence_asymmetry_score": "Evidence asym",
            "stale_price_score": "Stale price",
            "catalyst_score": "Catalyst",
            "next_check_at": "Next check",
        })
        st.dataframe(
            gem_df, hide_index=True, width="stretch",
            column_config={
                "Score": st.column_config.NumberColumn(format="%.1f"),
                "Exec edge": st.column_config.NumberColumn(format="%.1%"),
                "Attention gap": st.column_config.NumberColumn(format="%.2f"),
                "Evidence asym": st.column_config.NumberColumn(format="%.2f"),
                "Stale price": st.column_config.NumberColumn(format="%.2f"),
                "Catalyst": st.column_config.NumberColumn(format="%.2f"),
                "Market": st.column_config.TextColumn(width="large"),
            },
        )

    st.subheader("Evidence ledger")
    if len(evidence) == 0:
        st.info("No evidence items recorded yet. Use `record_evidence` to preserve source-level claims.")
    else:
        ev_df = evidence[[
            "created_at", "stance", "vertical", "question", "claim",
            "strength", "reliability", "freshness", "source_name",
        ]].copy()
        ev_df["created_at"] = ev_df["created_at"].dt.strftime("%Y-%m-%d %H:%M")
        ev_df = ev_df.rename(columns={
            "created_at": "Time",
            "stance": "Stance",
            "vertical": "Vertical",
            "question": "Market",
            "claim": "Claim",
            "strength": "Strength",
            "reliability": "Reliability",
            "freshness": "Freshness",
            "source_name": "Source",
        })
        st.dataframe(
            ev_df.head(50), hide_index=True, width="stretch",
            column_config={
                "Strength": st.column_config.NumberColumn(format="%.2f"),
                "Reliability": st.column_config.NumberColumn(format="%.2f"),
                "Freshness": st.column_config.NumberColumn(format="%.2f"),
                "Market": st.column_config.TextColumn(width="large"),
                "Claim": st.column_config.TextColumn(width="large"),
            },
        )

    st.subheader("Contrarian lens")
    c1, c2, c3 = st.columns(3)
    c1.metric("Causal factors", len(causal_factors))
    c2.metric("Anomalies", len(anomalies))
    c3.metric("Premortems", len(premortems))

    if len(anomalies):
        anom_df = anomalies[[
            "created_at", "status", "implied_direction", "severity",
            "confidence", "vertical", "question", "observation", "why_it_matters",
        ]].copy()
        anom_df["created_at"] = anom_df["created_at"].dt.strftime("%Y-%m-%d %H:%M")
        anom_df = anom_df.rename(columns={
            "created_at": "Time",
            "status": "Status",
            "implied_direction": "Direction",
            "severity": "Severity",
            "confidence": "Conf",
            "vertical": "Vertical",
            "question": "Market",
            "observation": "Observation",
            "why_it_matters": "Why it matters",
        })
        st.dataframe(
            anom_df.head(30), hide_index=True, width="stretch",
            column_config={
                "Severity": st.column_config.NumberColumn(format="%.2f"),
                "Conf": st.column_config.NumberColumn(format="%.2f"),
                "Market": st.column_config.TextColumn(width="large"),
                "Observation": st.column_config.TextColumn(width="large"),
                "Why it matters": st.column_config.TextColumn(width="large"),
            },
        )

    if len(causal_factors):
        factor_df = causal_factors[[
            "direction", "importance", "uncertainty", "vertical", "question",
            "factor_name", "mechanism", "observable_signal", "current_state",
        ]].copy()
        factor_df = factor_df.rename(columns={
            "direction": "Direction",
            "importance": "Importance",
            "uncertainty": "Uncertainty",
            "vertical": "Vertical",
            "question": "Market",
            "factor_name": "Factor",
            "mechanism": "Mechanism",
            "observable_signal": "Observable signal",
            "current_state": "Current state",
        })
        st.dataframe(
            factor_df.head(30), hide_index=True, width="stretch",
            column_config={
                "Importance": st.column_config.NumberColumn(format="%.2f"),
                "Uncertainty": st.column_config.NumberColumn(format="%.2f"),
                "Market": st.column_config.TextColumn(width="large"),
                "Mechanism": st.column_config.TextColumn(width="large"),
            },
        )

    st.subheader("Learning")
    resolved_analyses = analyses[
        (analyses["resolved"] == 1) & analyses["resolved_yes"].notna()
    ] if len(analyses) else analyses
    if len(resolved_analyses) == 0:
        st.info("Forecast quality metrics will appear after analyzed markets resolve.")
    else:
        q = resolved_analyses.copy()
        q["outcome"] = (q["resolved_yes"] > 0.5).astype(float)
        q["brier"] = (q["probability_yes"] - q["outcome"]) ** 2
        q["market_brier"] = (q["market_price"] - q["outcome"]) ** 2
        q["relative_brier"] = q["market_brier"] - q["brier"]
        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Resolved forecasts", len(q))
        l2.metric("Brier", f"{q['brier'].mean():.3f}")
        l3.metric("Market Brier", f"{q['market_brier'].mean():.3f}")
        l4.metric("Relative", f"{q['relative_brier'].mean():+.3f}")

        q["prob_bucket"] = (q["probability_yes"] * 10).clip(0, 9.999).astype(int) * 10
        cal = q.groupby("prob_bucket").agg(
            n=("id", "count"),
            avg_forecast=("probability_yes", "mean"),
            empirical_yes=("outcome", "mean"),
            avg_brier=("brier", "mean"),
        ).reset_index()
        cal["bucket"] = cal["prob_bucket"].apply(lambda b: f"{b}-{b+10}%")
        st.dataframe(
            cal[["bucket", "n", "avg_forecast", "empirical_yes", "avg_brier"]],
            hide_index=True, width="stretch",
            column_config={
                "avg_forecast": st.column_config.NumberColumn(format="%.2f"),
                "empirical_yes": st.column_config.NumberColumn(format="%.2f"),
                "avg_brier": st.column_config.NumberColumn(format="%.3f"),
            },
        )

    if len(analyses):
        no_sig = analyses[analyses["decision"] == "no_signal"].copy()
        if len(no_sig):
            st.caption("Use MCP `false_negative_review` for missed-alpha candidates from no-signal analyses.")

with tab_open:
    if len(opens) == 0:
        st.info("No open signals yet. Run a daily analysis via Claude Desktop.")
    else:
        df = opens[[
            "id", "created_at", "side", "question", "market_price",
            "claude_prob", "edge", "confidence", "bet_amount", "end_date"
        ]].copy()
        df["created_at"] = df["created_at"].dt.strftime("%Y-%m-%d")
        df["end_date"] = df["end_date"].dt.strftime("%Y-%m-%d")
        df = df.rename(columns={
            "id": "ID", "created_at": "Date", "side": "Side",
            "question": "Market", "market_price": "Mkt",
            "claude_prob": "Claude", "edge": "Edge", "confidence": "Conf",
            "bet_amount": "Bet", "end_date": "Resolves",
        })
        st.dataframe(
            df, hide_index=True, width="stretch",
            column_config={
                "Mkt": st.column_config.NumberColumn(format="%.2f"),
                "Claude": st.column_config.NumberColumn(format="%.2f"),
                "Edge": st.column_config.NumberColumn(format="%.1%"),
                "Conf": st.column_config.NumberColumn(format="%.2f"),
                "Bet": st.column_config.NumberColumn(format="$%.2f"),
                "Market": st.column_config.TextColumn(width="large"),
            },
        )

        st.subheader("Edge × Confidence")
        chart_df = opens[["question", "edge", "confidence", "bet_amount", "side"]].copy()
        chart_df["abs_edge"] = chart_df["edge"].abs() * 100
        chart_df["edge_pct"] = chart_df["edge"] * 100
        chart_df["short"] = chart_df["question"].str.slice(0, 50)
        scatter = alt.Chart(chart_df).mark_circle(size=200, opacity=0.7).encode(
            x=alt.X("edge_pct:Q", title="Edge (%)"),
            y=alt.Y("confidence:Q", title="Confidence", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("side:N", scale=alt.Scale(
                domain=["YES", "NO"], range=["#00ff64", "#ff4060"])),
            size=alt.Size("bet_amount:Q", title="Bet size",
                          scale=alt.Scale(range=[100, 600])),
            tooltip=["short", "side", "edge_pct", "confidence", "bet_amount"],
        ).properties(height=320)
        st.altair_chart(scatter, width="stretch")

with tab_closed:
    if len(closed) == 0:
        st.info("No resolved signals yet. Ask Claude *«resolve closed signals»* after some markets close.")
    else:
        df = closed[[
            "created_at", "side", "question", "market_price",
            "bet_amount", "realized_pnl", "resolved_yes"
        ]].copy()
        df["created_at"] = df["created_at"].dt.strftime("%Y-%m-%d")
        df["outcome"] = df["resolved_yes"].apply(
            lambda y: "YES" if y is not None and y > 0.5 else "NO"
        )
        df["result"] = df["realized_pnl"].apply(
            lambda p: "WIN" if (p or 0) > 0 else "LOSS"
        )
        df = df[[
            "created_at", "side", "question", "market_price",
            "outcome", "bet_amount", "realized_pnl", "result"
        ]].rename(columns={
            "created_at": "Date", "side": "Side", "question": "Market",
            "market_price": "Entry", "outcome": "Outcome",
            "bet_amount": "Bet", "realized_pnl": "PnL", "result": "Result",
        })
        st.dataframe(
            df, hide_index=True, width="stretch",
            column_config={
                "Entry": st.column_config.NumberColumn(format="%.2f"),
                "Bet": st.column_config.NumberColumn(format="$%.2f"),
                "PnL": st.column_config.NumberColumn(format="$%+.2f"),
                "Market": st.column_config.TextColumn(width="large"),
            },
        )

with tab_pnl:
    if len(closed) == 0:
        st.info("Cumulative PnL chart will appear after the first signals resolve.")
    else:
        df = closed.sort_values("created_at").copy()
        df["cum_pnl"] = df["realized_pnl"].cumsum()
        line = alt.Chart(df).mark_line(
            color="#00ff64", strokeWidth=2, point=alt.OverlayMarkDef(size=80)
        ).encode(
            x=alt.X("created_at:T", title="Date"),
            y=alt.Y("cum_pnl:Q", title="Cumulative PnL (USD)"),
            tooltip=["created_at", "question", "realized_pnl", "cum_pnl"],
        ).properties(height=400)
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
            color="gray", strokeDash=[4, 4]
        ).encode(y="y:Q")
        st.altair_chart(line + zero, width="stretch")

        st.subheader("Per-trade PnL")
        bars = alt.Chart(df).mark_bar().encode(
            x=alt.X("created_at:T", title="Date"),
            y=alt.Y("realized_pnl:Q", title="PnL"),
            color=alt.condition(
                alt.datum.realized_pnl > 0,
                alt.value("#00ff64"), alt.value("#ff4060")
            ),
            tooltip=["created_at", "question", "realized_pnl"],
        ).properties(height=240)
        st.altair_chart(bars, width="stretch")

with tab_vert:
    if total == 0:
        st.info("No signals yet.")
    else:
        agg_rows = []
        for v, group in signals.groupby("vertical"):
            closed_v = group[group["resolved"] == 1]
            open_v = group[group["resolved"] == 0]
            wins_v = int((closed_v["realized_pnl"] > 0).sum()) if len(closed_v) else 0
            pnl_v = float(closed_v["realized_pnl"].sum()) if len(closed_v) else 0.0
            wagered_v = float(closed_v["bet_amount"].sum()) if len(closed_v) else 0.0
            avg_edge_v = float(group["edge"].mean()) * 100
            agg_rows.append({
                "Vertical": v,
                "Total": len(group),
                "Open": len(open_v),
                "Closed": len(closed_v),
                "Wins": wins_v,
                "Win rate %": round(wins_v / len(closed_v) * 100, 1) if len(closed_v) else None,
                "PnL $": round(pnl_v, 2),
                "ROI %": round(pnl_v / wagered_v * 100, 1) if wagered_v else None,
                "Avg edge %": round(avg_edge_v, 2),
                "Wagered $": round(float(group["bet_amount"].sum()), 2),
            })
        agg = pd.DataFrame(agg_rows).sort_values("Total", ascending=False)
        st.dataframe(
            agg, hide_index=True, width="stretch",
            column_config={
                "PnL $": st.column_config.NumberColumn(format="$%+.2f"),
                "Wagered $": st.column_config.NumberColumn(format="$%.2f"),
            },
        )

        st.subheader("Signals per vertical")
        chart = alt.Chart(signals).mark_bar().encode(
            x=alt.X("vertical:N", title="Vertical"),
            y=alt.Y("count():Q", title="Signals"),
            color=alt.Color("side:N", scale=alt.Scale(
                domain=["YES", "NO"], range=["#00ff64", "#ff4060"])),
            tooltip=["vertical", "side", "count()"],
        ).properties(height=280)
        st.altair_chart(chart, width="stretch")

        if len(closed) > 0:
            st.subheader("Realized PnL by vertical")
            closed_chart = closed.copy()
            pnl_chart = alt.Chart(closed_chart).mark_bar().encode(
                x=alt.X("vertical:N", title="Vertical"),
                y=alt.Y("sum(realized_pnl):Q", title="Cumulative PnL ($)"),
                color=alt.condition(
                    "datum.realized_pnl > 0",
                    alt.value("#00ff64"), alt.value("#ff4060")
                ),
                tooltip=["vertical", "sum(realized_pnl)"],
            ).properties(height=280)
            st.altair_chart(pnl_chart, width="stretch")

with tab_runs:
    if len(runs) == 0:
        st.info("No daily runs recorded yet.")
    else:
        df = runs.copy()
        df["run_date"] = df["run_date"].dt.strftime("%Y-%m-%d")
        df["finished_at"] = df["finished_at"].dt.strftime("%H:%M")
        df = df[[
            "run_date", "finished_at", "markets_seen",
            "deep", "signals_emitted", "total_cost_usd",
        ]].rename(columns={
            "run_date": "Date", "finished_at": "Finished",
            "markets_seen": "Seen", "deep": "Deep",
            "signals_emitted": "Signals", "total_cost_usd": "API cost",
        })
        st.dataframe(
            df, hide_index=True, width="stretch",
            column_config={
                "API cost": st.column_config.NumberColumn(format="$%.4f"),
            },
        )

        if len(runs) >= 2:
            st.subheader("Signals per day")
            chart_df = runs.sort_values("run_date")
            chart = alt.Chart(chart_df).mark_bar(color="#00ff64").encode(
                x=alt.X("run_date:T", title="Date"),
                y=alt.Y("signals_emitted:Q", title="Signals"),
                tooltip=["run_date", "markets_seen", "deep", "signals_emitted"],
            ).properties(height=240)
            st.altair_chart(chart, width="stretch")

with tab_detail:
    if total == 0:
        st.info("No signals to inspect.")
    else:
        labels = {
            int(r["id"]): f"#{r['id']} · {r['side']} · {r['question'][:70]}"
            for _, r in signals.iterrows()
        }
        sel = st.selectbox(
            "Pick a signal to inspect:",
            options=list(labels.keys()),
            format_func=lambda k: labels[k],
        )
        if sel:
            row = signals[signals["id"] == sel].iloc[0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Market price", f"{row['market_price']:.2f}")
            c2.metric("Claude estimate", f"{row['claude_prob']:.2f}")
            c3.metric("Edge", f"{row['edge']*100:+.1f}%")
            c4.metric("Confidence", f"{row['confidence']:.2f}")

            st.markdown(f"**Market:** {row['question']}")
            if row.get("end_date") is not None and pd.notna(row["end_date"]):
                st.markdown(f"**Resolves:** {row['end_date'].strftime('%Y-%m-%d')}")
            st.markdown(f"**Side:** `{row['side']}`  |  **Bet:** `${row['bet_amount']:.2f}`")
            if row["resolved"]:
                pnl = row["realized_pnl"] or 0
                color = "🟢" if pnl > 0 else "🔴"
                st.markdown(f"**Realized PnL:** {color} `${pnl:+.2f}`")

            st.markdown("---")
            st.markdown("### Reasoning")
            st.write(row["reasoning"] or "—")

            sources = row["sources"] if isinstance(row["sources"], list) else []
            if sources:
                st.markdown("### Sources")
                for s in sources:
                    if s.startswith("http"):
                        st.markdown(f"- [{s}]({s})")
                    else:
                        st.markdown(f"- {s}")

            # Price history
            hist = load_market_snapshots(row["condition_id"])
            if not hist.empty and len(hist) >= 2:
                st.markdown("### Market price over time")
                hist_chart = alt.Chart(hist).mark_line(
                    color="#00aaff", point=True
                ).encode(
                    x=alt.X("captured_at:T", title="Date"),
                    y=alt.Y("yes_price:Q", title="YES price",
                            scale=alt.Scale(domain=[0, 1])),
                    tooltip=["captured_at", "yes_price"],
                ).properties(height=260)
                claude_line = alt.Chart(pd.DataFrame({
                    "y": [row["claude_prob"]],
                    "label": [f"Claude: {row['claude_prob']:.2f}"]
                })).mark_rule(color="#00ff64", strokeDash=[6, 4]).encode(y="y:Q")
                st.altair_chart(hist_chart + claude_line, width="stretch")

# ---------------- Footer ----------------

st.divider()
left, right = st.columns([3, 1])
with left:
    st.caption(
        f"Edge threshold: ≥{config.EDGE_THRESHOLD*100:.0f}% · "
        f"Min volume: ${config.MIN_VOLUME_USD:,.0f} · "
        f"Resolution window: {config.MIN_DAYS_TO_RESOLUTION}–{config.MAX_DAYS_TO_RESOLUTION}d · "
        "Run daily analysis via Claude Desktop chat."
    )
with right:
    if st.button("🔄 Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()
