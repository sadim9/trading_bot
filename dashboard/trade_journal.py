"""
dashboard/trade_journal.py — Trade Journal & P&L Analytics

Renders:
  1. Portfolio summary  — total P&L, win rate, profit factor, expectancy
  2. Equity curve       — cumulative P&L chart (strategy vs flat line)
  3. Per-trade waterfall bar chart (green = win, red = loss)
  4. Trade history table — filterable, sortable, with close-trade action
  5. Manual trade entry form — log trades placed outside the bot

Data sources (priority order):
  1. FastAPI + PostgreSQL via /api/v1/trades  (primary — authenticated)
  2. logs/executed_trades.csv                 (fallback if API unavailable)
  - logs/signals.json                         (signal history for reference)
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

TRADE_LOG = "logs/executed_trades.csv"
SIGNAL_LOG = "logs/signals.json"

# ── colour palette (matches terminal theme) ─────────────────────────────────
_GREEN  = "#00C9A7"
_RED    = "#FF4560"
_BLUE   = "#4B9FFF"
_AMBER  = "#FFB800"
_MUTE   = "#4A5568"
_BG     = "#0C1322"
_SURFACE = "#111827"
_BORDER = "#1A2540"
_TEXT   = "#DCE4F5"


# ────────────────────────────────────────────────────────────────────────────
#  Data helpers
# ────────────────────────────────────────────────────────────────────────────

def _load_from_api() -> pd.DataFrame:
    """
    Fetch trades from the FastAPI backend (/api/v1/trades) and normalise
    column names to match the CSV layout expected by the rest of the UI.
    Returns an empty DataFrame on any failure.
    """
    try:
        from dashboard.auth import get_api_client
        client = get_api_client()
        if client is None:
            return pd.DataFrame()
        result = client.list_trades(size=500)
        trades = result.get("trades", [])
        if not trades:
            return pd.DataFrame()

        df = pd.DataFrame(trades)

        # ── Normalise column names to CSV layout ──────────────────────────
        # API → CSV mapping
        if "id" in df.columns:
            df["order_id"] = df["id"]
        if "entry_price" in df.columns:
            df["fill_price"] = df["entry_price"]   # CSV uses fill_price
        if "opened_at" in df.columns:
            df["timestamp"] = pd.to_datetime(df["opened_at"], errors="coerce")
        if "notes" in df.columns:
            df["reason"] = df["notes"]
        if "is_paper" in df.columns:
            df["broker"] = df.apply(
                lambda r: (r.get("broker") or "manual") + (" [paper]" if r.get("is_paper") else " [live]"),
                axis=1,
            )

        # Coerce numeric
        for col in ["pnl", "pnl_pct", "fill_price", "entry_price",
                    "exit_price", "quantity", "stop_loss", "take_profit"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Parse timestamps
        for col in ["timestamp", "closed_at"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        df["_source"] = "db"
        return df

    except Exception:
        return pd.DataFrame()


def _read_trades() -> pd.DataFrame:
    """
    Load trade data — tries the PostgreSQL API first, falls back to CSV.
    Always returns a DataFrame with at minimum the columns the UI expects.
    """
    # ── 1. Try database API ───────────────────────────────────────────────
    df_api = _load_from_api()
    if not df_api.empty:
        return df_api

    # ── 2. CSV fallback ───────────────────────────────────────────────────
    if not os.path.exists(TRADE_LOG):
        return pd.DataFrame()
    try:
        df = pd.read_csv(TRADE_LOG, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df

    # Ensure required columns exist
    for col in ["pnl", "pnl_pct", "exit_price", "closed_at", "status", "fill_price", "entry_price"]:
        if col not in df.columns:
            df[col] = ""

    # Coerce numeric columns
    for col in ["pnl", "pnl_pct", "fill_price", "entry_price", "exit_price", "quantity", "stop_loss", "take_profit", "kelly_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Parse timestamps
    for col in ["timestamp", "closed_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df["_source"] = "csv"
    return df


def _closed_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Return only rows with status == 'closed' and a valid pnl."""
    if df.empty:
        return df
    mask = (df.get("status", pd.Series(dtype=str)) == "closed") & df["pnl"].notna()
    return df[mask].copy()


def _compute_metrics(closed: pd.DataFrame) -> dict:
    """Compute portfolio-level analytics from closed trades."""
    m: dict = {}
    if closed.empty:
        return m

    pnl      = closed["pnl"].dropna()
    pnl_pct  = closed["pnl_pct"].dropna() / 100   # convert to fraction

    wins     = pnl[pnl > 0]
    losses   = pnl[pnl <= 0]

    m["total_trades"]   = len(pnl)
    m["winning"]        = len(wins)
    m["losing"]         = len(losses)
    m["win_rate"]       = len(wins) / len(pnl) * 100 if len(pnl) else 0
    m["total_pnl"]      = pnl.sum()
    m["avg_win"]        = wins.mean() if len(wins)   else 0
    m["avg_loss"]       = losses.mean() if len(losses) else 0
    m["avg_trade"]      = pnl.mean()

    gross_profit = wins.sum()
    gross_loss   = abs(losses.sum())
    m["profit_factor"] = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    wr   = len(wins)   / len(pnl) if len(pnl) else 0
    lr   = 1 - wr
    avg_w_pct = pnl_pct[pnl_pct > 0].mean() if len(pnl_pct[pnl_pct > 0]) else 0
    avg_l_pct = pnl_pct[pnl_pct <= 0].mean() if len(pnl_pct[pnl_pct <= 0]) else 0
    m["expectancy_pct"] = (wr * avg_w_pct - lr * abs(avg_l_pct)) * 100

    # Max consecutive losses
    streak = cur = 0
    for v in pnl:
        cur = cur - 1 if v <= 0 else 0
        streak = min(streak, cur)
    m["max_loss_streak"] = abs(streak)

    # Cumulative P&L drawdown
    cum = pnl.cumsum()
    roll_max = cum.cummax()
    dd = cum - roll_max
    m["max_drawdown"] = dd.min() if not dd.empty else 0

    return m


# ────────────────────────────────────────────────────────────────────────────
#  Chart builders
# ────────────────────────────────────────────────────────────────────────────

def _equity_chart(closed: pd.DataFrame) -> Optional[object]:
    """Cumulative P&L equity curve."""
    if not PLOTLY_OK or closed.empty:
        return None
    c = closed.sort_values("closed_at").copy()
    c["cum_pnl"] = c["pnl"].cumsum()
    c["trade_n"] = range(1, len(c) + 1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=c["trade_n"], y=c["cum_pnl"],
        name="Cumulative P&L",
        line=dict(color=_BLUE, width=2.5),
        fill="tozeroy",
        fillcolor="rgba(75,159,255,0.07)",
        mode="lines+markers",
        marker=dict(
            size=6,
            color=[_GREEN if v >= 0 else _RED for v in c["cum_pnl"]],
        ),
        hovertemplate="<b>Trade %{x}</b><br>Cum P&L: %{y:+,.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=_MUTE, width=1, dash="dot"))
    fig.update_layout(
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="IBM Plex Mono", size=11),
        margin=dict(l=50, r=20, t=10, b=30),
        height=220,
        xaxis=dict(gridcolor=_BORDER, title="Trade #", showgrid=True),
        yaxis=dict(gridcolor=_BORDER, title="P&L", showgrid=True, side="right"),
        showlegend=False,
        hovermode="x unified",
    )
    return fig


def _waterfall_chart(closed: pd.DataFrame) -> Optional[object]:
    """Per-trade P&L bar chart (green = profit, red = loss)."""
    if not PLOTLY_OK or closed.empty:
        return None
    c = closed.sort_values("closed_at").copy()
    colors = [_GREEN if v >= 0 else _RED for v in c["pnl"]]
    labels = c.get("symbol", pd.Series(["?"] * len(c))).tolist()

    fig = go.Figure(go.Bar(
        x=list(range(1, len(c) + 1)),
        y=c["pnl"].tolist(),
        marker_color=colors,
        customdata=list(zip(
            labels,
            c.get("side", pd.Series(["?"] * len(c))).tolist(),
            c.get("pnl_pct", pd.Series([0] * len(c))).tolist(),
        )),
        hovertemplate=(
            "<b>Trade %{x} — %{customdata[0]}</b><br>"
            "Side: %{customdata[1]}<br>"
            "P&L: %{y:+,.2f} (%{customdata[2]:+.2f}%)<extra></extra>"
        ),
    ))
    fig.add_hline(y=0, line=dict(color=_MUTE, width=1))
    fig.update_layout(
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="IBM Plex Mono", size=11),
        margin=dict(l=50, r=20, t=10, b=30),
        height=160,
        xaxis=dict(gridcolor=_BORDER, title="Trade #"),
        yaxis=dict(gridcolor=_BORDER, title="P&L", side="right"),
        showlegend=False,
    )
    return fig


# ────────────────────────────────────────────────────────────────────────────
#  Section renderers
# ────────────────────────────────────────────────────────────────────────────

_MONO = "font-family:'IBM Plex Mono',monospace"


def _kpi(label: str, value: str, colour: str = _TEXT) -> str:
    return (
        f'<div style="background:{_SURFACE};border:1px solid {_BORDER};border-radius:5px;'
        f'padding:10px 14px;text-align:center">'
        f'<div style="{_MONO};font-size:9px;color:{_MUTE};letter-spacing:0.12em;text-transform:uppercase">{label}</div>'
        f'<div style="{_MONO};font-size:18px;font-weight:700;color:{colour};margin-top:4px">{value}</div>'
        f'</div>'
    )


def _section(title: str) -> str:
    return (
        f'<div style="{_MONO};font-size:9px;font-weight:600;letter-spacing:0.18em;'
        f'text-transform:uppercase;color:{_MUTE};padding:8px 0 4px;margin-top:8px;'
        f'border-top:1px solid {_BORDER}">{title}</div>'
    )


def render_trade_journal():
    """Main entry point — renders the full trade journal UI."""

    df = _read_trades()
    closed = _closed_trades(df)
    open_trades = df[df.get("status", pd.Series(dtype=str)) == "open"] if not df.empty else pd.DataFrame()

    # ═══════════════════════════════════════════════════════════════════════
    #  HEADER
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown(
        f'<div style="{_MONO};font-size:18px;font-weight:700;color:{_TEXT};'
        f'letter-spacing:0.06em;margin-bottom:4px">TRADE JOURNAL</div>'
        f'<div style="{_MONO};font-size:10px;color:{_MUTE};margin-bottom:16px">'
        f'Record, track and analyse every trade — bot-executed and manual</div>',
        unsafe_allow_html=True,
    )

    # ═══════════════════════════════════════════════════════════════════════
    #  PORTFOLIO SUMMARY KPIs
    # ═══════════════════════════════════════════════════════════════════════
    m = _compute_metrics(closed)

    if m:
        st.markdown(_section("PORTFOLIO SUMMARY"), unsafe_allow_html=True)
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        total_pnl = m.get("total_pnl", 0)
        pf = m.get("profit_factor", 0)
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        kpi_data = [
            (k1, "TOTAL P&L", f"{total_pnl:+,.2f}", _GREEN if total_pnl >= 0 else _RED),
            (k2, "WIN RATE",  f"{m.get('win_rate', 0):.1f}%",
             _GREEN if m.get("win_rate", 0) >= 50 else _RED),
            (k3, "PROFIT FACTOR", pf_str,
             _GREEN if pf >= 1 else _RED),
            (k4, "TRADES", str(m.get("total_trades", 0)), _TEXT),
            (k5, "EXPECTANCY", f"{m.get('expectancy_pct', 0):+.2f}%",
             _GREEN if m.get("expectancy_pct", 0) >= 0 else _RED),
            (k6, "MAX DD",   f"{m.get('max_drawdown', 0):+,.2f}",
             _RED if m.get("max_drawdown", 0) < 0 else _TEXT),
        ]
        for col, label, value, colour in kpi_data:
            col.markdown(_kpi(label, value, colour), unsafe_allow_html=True)

        # Secondary metrics row
        s1, s2, s3, s4 = st.columns(4)
        s1.markdown(_kpi("AVG WIN",       f"{m.get('avg_win', 0):+,.2f}",  _GREEN),   unsafe_allow_html=True)
        s2.markdown(_kpi("AVG LOSS",      f"{m.get('avg_loss', 0):+,.2f}", _RED),      unsafe_allow_html=True)
        s3.markdown(_kpi("AVG TRADE",     f"{m.get('avg_trade', 0):+,.2f}", _TEXT),    unsafe_allow_html=True)
        s4.markdown(_kpi("MAX LOSS STREAK", str(m.get("max_loss_streak", 0)), _AMBER), unsafe_allow_html=True)
    else:
        st.info(
            "No closed trades to analyse yet. Use the **Log Trade** form below "
            "to record your first trade, or execute one through the bot.",
            icon="ℹ️",
        )

    # ═══════════════════════════════════════════════════════════════════════
    #  CHARTS
    # ═══════════════════════════════════════════════════════════════════════
    if not closed.empty:
        st.markdown(_section("P&L PERFORMANCE"), unsafe_allow_html=True)

        fig_eq = _equity_chart(closed)
        if fig_eq:
            st.plotly_chart(fig_eq, width="stretch", config={"displayModeBar": False})

        fig_wf = _waterfall_chart(closed)
        if fig_wf:
            st.plotly_chart(fig_wf, width="stretch", config={"displayModeBar": False})

    # ═══════════════════════════════════════════════════════════════════════
    #  OPEN POSITIONS
    # ═══════════════════════════════════════════════════════════════════════
    if not open_trades.empty:
        st.markdown(_section(f"OPEN POSITIONS ({len(open_trades)})"), unsafe_allow_html=True)

        close_cols = ["order_id", "symbol", "side", "quantity", "fill_price",
                      "stop_loss", "take_profit", "timestamp", "broker", "reason"]
        show_open = open_trades[[c for c in close_cols if c in open_trades.columns]].copy()

        # Format timestamps
        if "timestamp" in show_open.columns:
            show_open["timestamp"] = show_open["timestamp"].dt.strftime("%Y-%m-%d %H:%M")

        st.dataframe(show_open, width="stretch", hide_index=True)

        # Close trade form
        with st.expander("Close a Position", expanded=False):
            oid_list = open_trades["order_id"].dropna().tolist()
            sel_oid  = st.selectbox("Select Order ID", oid_list, key="close_oid")
            exit_px  = st.number_input("Exit Price", min_value=0.0, step=0.01, key="close_exit_px")
            exit_rsn = st.selectbox(
                "Exit Reason",
                ["manual", "take_profit", "stop_loss", "signal_flip", "other"],
                key="close_reason",
            )
            if st.button("Close Trade", type="primary", key="do_close_trade"):
                if sel_oid and exit_px > 0:
                    _closed_ok = False
                    # ── Try API first ──────────────────────────────────────
                    try:
                        from dashboard.auth import get_api_client
                        _client = get_api_client()
                        if _client:
                            # Compute PnL from entry price if available
                            _row = open_trades[open_trades["order_id"] == sel_oid].iloc[0]
                            _entry = float(_row.get("fill_price") or _row.get("entry_price") or exit_px)
                            _qty   = float(_row.get("quantity", 1))
                            _side  = str(_row.get("side", "buy"))
                            _pnl_pct = ((exit_px - _entry) / _entry) if _side == "buy" else ((_entry - exit_px) / _entry)
                            _pnl     = _pnl_pct * _entry * _qty
                            _client.close_trade(sel_oid, exit_px, _pnl, _pnl_pct)
                            _closed_ok = True
                    except Exception as _api_err:
                        st.caption(f"API close failed ({_api_err}), trying CSV fallback…")

                    # ── CSV fallback ───────────────────────────────────────
                    if not _closed_ok:
                        try:
                            from brokers.order_manager import OrderManager
                            mgr = OrderManager()
                            _closed_ok = mgr.close_trade(sel_oid, exit_px, exit_rsn)
                        except Exception as _csv_err:
                            st.error(f"Could not close trade: {_csv_err}")

                    if _closed_ok:
                        st.success(f"Trade {sel_oid} closed at {exit_px:.4f}.")
                        st.rerun()
                    else:
                        st.error("Could not find the trade or it is already closed.")
                else:
                    st.warning("Select an order ID and enter a valid exit price.")

    # ═══════════════════════════════════════════════════════════════════════
    #  TRADE HISTORY TABLE (closed + cancelled)
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown(_section("TRADE HISTORY"), unsafe_allow_html=True)

    # Filters
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 2])
    filter_sym    = fc1.text_input("Filter Symbol", placeholder="e.g. XBTUSD", key="jnl_sym_filter")
    filter_side   = fc2.selectbox("Filter Side", ["All", "buy", "sell"], key="jnl_side_filter")
    filter_status = fc3.selectbox("Filter Status", ["All", "closed", "open", "cancelled", "error"], key="jnl_status_filter")
    filter_broker = fc4.text_input("Filter Broker", placeholder="bitoasis / ibkr / manual", key="jnl_broker_filter")

    if df.empty:
        st.markdown(
            f'<div style="{_MONO};font-size:11px;color:{_MUTE};padding:20px;'
            f'text-align:center">No trades recorded yet.</div>',
            unsafe_allow_html=True,
        )
    else:
        disp = df.copy()
        if filter_sym:
            disp = disp[disp["symbol"].str.upper().str.contains(filter_sym.upper(), na=False)]
        if filter_side != "All":
            disp = disp[disp["side"] == filter_side]
        if filter_status != "All":
            disp = disp[disp.get("status", pd.Series(dtype=str)) == filter_status]
        if filter_broker:
            disp = disp[disp.get("broker", pd.Series(dtype=str)).str.contains(filter_broker, case=False, na=False)]

        show_cols = [c for c in [
            "timestamp", "symbol", "side", "quantity", "fill_price",
            "exit_price", "pnl", "pnl_pct", "status", "exit_reason",
            "broker", "order_id", "reason",
        ] if c in disp.columns]

        disp_fmt = disp[show_cols].copy()
        if "timestamp" in disp_fmt.columns:
            disp_fmt["timestamp"] = disp_fmt["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        if "pnl" in disp_fmt.columns:
            disp_fmt["pnl"] = disp_fmt["pnl"].apply(
                lambda x: f"{x:+,.4f}" if pd.notna(x) else ""
            )
        if "pnl_pct" in disp_fmt.columns:
            disp_fmt["pnl_pct"] = disp_fmt["pnl_pct"].apply(
                lambda x: f"{x:+.2f}%" if pd.notna(x) else ""
            )

        st.dataframe(
            disp_fmt.sort_values("timestamp", ascending=False, key=lambda s: pd.to_datetime(s, errors="coerce")).head(200),
            width="stretch",
            hide_index=True,
        )

        # Export
        csv_bytes = disp[show_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            "Export to CSV",
            data=csv_bytes,
            file_name=f"trade_journal_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            key="jnl_export",
        )

    # ═══════════════════════════════════════════════════════════════════════
    #  MANUAL TRADE ENTRY FORM
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown(_section("LOG A TRADE MANUALLY"), unsafe_allow_html=True)
    st.markdown(
        f'<div style="{_MONO};font-size:10px;color:{_MUTE};margin-bottom:10px">'
        f'Record trades placed outside the bot for a complete journal.</div>',
        unsafe_allow_html=True,
    )

    with st.form("manual_trade_form", clear_on_submit=True):
        m1, m2, m3 = st.columns(3)
        m_sym  = m1.text_input("Symbol *",       placeholder="BTC-AED / AAPL", key="mt_sym")
        m_side = m2.selectbox("Side *",          ["buy", "sell"],               key="mt_side")
        m_qty  = m3.number_input("Quantity *",    min_value=0.0, step=0.0001, format="%.6f", key="mt_qty")

        m4, m5, m6 = st.columns(3)
        m_entry  = m4.number_input("Entry Price *",   min_value=0.0, step=0.01, format="%.4f", key="mt_entry")
        m_sl     = m5.number_input("Stop Loss",       min_value=0.0, step=0.01, format="%.4f", key="mt_sl")
        m_tp     = m6.number_input("Take Profit",     min_value=0.0, step=0.01, format="%.4f", key="mt_tp")

        m7, m8 = st.columns(2)
        m_broker = m7.text_input("Broker",  value="manual",   key="mt_broker")
        m_reason = m8.text_input("Reason",  placeholder="e.g. Manual BTC buy — support bounce", key="mt_reason")

        submitted = st.form_submit_button("Log Trade", type="primary", use_container_width=True)

    if submitted:
        if not m_sym or not m_qty or not m_entry:
            st.error("Symbol, Quantity and Entry Price are required.")
        else:
            _logged_id = None

            # ── Try API first ─────────────────────────────────────────────
            try:
                from dashboard.auth import get_api_client
                _client = get_api_client()
                if _client:
                    _payload = {
                        "symbol":      m_sym.strip().upper(),
                        "side":        m_side,
                        "order_type":  "market",
                        "quantity":    float(m_qty),
                        "entry_price": float(m_entry),
                        "stop_loss":   float(m_sl) if m_sl else None,
                        "take_profit": float(m_tp) if m_tp else None,
                        "broker":      m_broker.strip() or "manual",
                        "is_paper":    True,
                        "notes":       m_reason.strip() or "Manual entry",
                    }
                    _res    = _client.create_trade(_payload)
                    _logged_id = _res.get("id")
            except Exception as _api_err:
                st.caption(f"API log failed ({_api_err}), writing to CSV fallback…")

            # ── CSV fallback ──────────────────────────────────────────────
            if not _logged_id:
                try:
                    from brokers.order_manager import OrderManager
                    mgr = OrderManager()
                    _logged_id = mgr.log_manual_trade(
                        symbol=m_sym.strip().upper(),
                        side=m_side,
                        quantity=float(m_qty),
                        entry_price=float(m_entry),
                        stop_loss=float(m_sl) if m_sl else None,
                        take_profit=float(m_tp) if m_tp else None,
                        broker=m_broker.strip() or "manual",
                        reason=m_reason.strip() or "Manual entry",
                    )
                except Exception as _csv_err:
                    st.error(f"Failed to log trade: {_csv_err}")
                    _logged_id = None

            if _logged_id:
                st.success(f"Trade logged with ID: `{_logged_id}` — it will appear above as an open position.")
                st.rerun()
            else:
                st.error("Trade could not be saved. Check the API server connection.")

    # ═══════════════════════════════════════════════════════════════════════
    #  SIGNAL LOG (reference)
    # ═══════════════════════════════════════════════════════════════════════
    if os.path.exists(SIGNAL_LOG):
        st.markdown(_section("RECENT SIGNAL LOG"), unsafe_allow_html=True)
        import json
        sigs = []
        try:
            with open(SIGNAL_LOG, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            sigs.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass

        if sigs:
            sig_df = pd.DataFrame(sigs).tail(30).iloc[::-1]
            show_sig_cols = [c for c in [
                "timestamp", "symbol", "signal", "score", "confidence_pct",
                "entry_price", "stop_loss", "take_profit",
            ] if c in sig_df.columns]
            if show_sig_cols:
                sig_disp = sig_df[show_sig_cols].copy()
                if "score" in sig_disp.columns:
                    sig_disp["score"] = sig_disp["score"].apply(
                        lambda x: f"{float(x):+.4f}" if pd.notna(x) else ""
                    )
                st.dataframe(sig_disp, width="stretch", hide_index=True)
        else:
            st.caption("No signals recorded yet — load a chart and signals will appear here.")
