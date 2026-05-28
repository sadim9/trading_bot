"""
dashboard/alert_log.py — Buy/Sell Alert Log with Planned Trade Tracking

Persists every BUY/SELL alert to a CSV file and renders a live log table
in the dashboard. Each entry records:
  - timestamp, symbol, signal, price, strategy_mode, score, confidence
  - planned_amount (USD) from the user setting
  - planned_pnl estimate (for reference only)
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

_LOG_DIR  = Path(os.getenv("SETTINGS_DIR", "/app/logs"))
_LOG_FILE = _LOG_DIR / "alert_log.csv"

_COLUMNS = [
    "timestamp", "symbol", "signal", "price",
    "strategy_mode", "score", "confidence",
    "planned_amount", "entry_price", "stop_loss", "take_profit",
]

_GREEN = "#00C9A7"
_RED   = "#FF4560"
_AMBER = "#FFB800"
_BLUE  = "#4B9FFF"
_MUTE  = "#4A5568"


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _ensure_log():
    for path in [_LOG_DIR, Path(".cache")]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            log = path / "alert_log.csv"
            if not log.exists():
                with open(log, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=_COLUMNS)
                    writer.writeheader()
            return log
        except Exception:
            continue
    return None


def log_alert(
    symbol: str,
    signal: str,
    price: float,
    strategy_mode: str = "multi",
    score: float = 0.0,
    confidence: float = 0.0,
    planned_amount: float = 0.0,
    entry_price: float = 0.0,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
):
    """Append a BUY/SELL alert to the persistent log CSV."""
    if signal not in ("BUY", "SELL"):
        return

    log_path = _ensure_log()
    if log_path is None:
        return

    row = {
        "timestamp":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol":         symbol,
        "signal":         signal,
        "price":          round(float(price), 6),
        "strategy_mode":  strategy_mode,
        "score":          round(float(score), 4),
        "confidence":     round(float(confidence), 1),
        "planned_amount": round(float(planned_amount), 2),
        "entry_price":    round(float(entry_price), 6),
        "stop_loss":      round(float(stop_loss), 6),
        "take_profit":    round(float(take_profit), 6),
    }
    try:
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_COLUMNS)
            writer.writerow(row)
    except Exception:
        pass


def load_alert_log(max_rows: int = 500) -> pd.DataFrame:
    """Load the alert log CSV, returning a DataFrame (newest first)."""
    for path in [_LOG_FILE, Path(".cache/alert_log.csv")]:
        try:
            if path.exists():
                df = pd.read_csv(path)
                if df.empty:
                    return pd.DataFrame(columns=_COLUMNS)
                df = df.tail(max_rows).iloc[::-1].reset_index(drop=True)
                return df
        except Exception:
            continue
    return pd.DataFrame(columns=_COLUMNS)


# ── Streamlit render ──────────────────────────────────────────────────────────

def render_alert_log():
    """Render the Buy/Sell Alert Log section inside the LOG tab."""
    from dashboard.settings_store import save_settings

    st.markdown(
        '<div class="qt-section">SIGNAL ALERT LOG</div>',
        unsafe_allow_html=True,
    )

    # ── Planned Trade Amount setting ─────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 2, 2])
    _saved_amt = float(st.session_state.get("planned_trade_amount", 1000.0))
    planned_amt = c1.number_input(
        "Planned Trade Amount ($)",
        min_value=0.0,
        value=_saved_amt,
        step=100.0,
        format="%.2f",
        key="planned_trade_amount_input",
        help="This amount is recorded with each BUY/SELL alert for P&L tracking reference.",
    )
    if planned_amt != _saved_amt:
        st.session_state["planned_trade_amount"] = planned_amt
        save_settings()

    if c2.button("🗑 Clear Log", key="clear_alert_log", use_container_width=True):
        for path in [_LOG_FILE, Path(".cache/alert_log.csv")]:
            try:
                if path.exists():
                    with open(path, "w", newline="", encoding="utf-8") as f:
                        csv.DictWriter(f, fieldnames=_COLUMNS).writeheader()
            except Exception:
                pass
        st.toast("Alert log cleared")
        st.rerun()

    # ── Load & display ───────────────────────────────────────────────────────
    df = load_alert_log()

    if df.empty:
        st.markdown(
            '<div style="color:var(--text-mute);font-size:10px;padding:12px;'
            'font-family:var(--mono);text-align:center">'
            'No alerts logged yet. Alerts fire when a BUY or SELL signal is detected.</div>',
            unsafe_allow_html=True,
        )
        return

    # Summary stats
    total   = len(df)
    n_buy   = (df["signal"] == "BUY").sum()
    n_sell  = (df["signal"] == "SELL").sum()
    total_planned = float(df["planned_amount"].sum()) if "planned_amount" in df.columns else 0.0

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px">
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">TOTAL ALERTS</div>
        <div style="font-size:15px;font-weight:600;color:var(--text-pri)">{total}</div>
      </div>
      <div style="background:var(--bg-card);border:1px solid rgba(0,201,167,0.3);border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">BUY ALERTS</div>
        <div style="font-size:15px;font-weight:600;color:{_GREEN}">{n_buy}</div>
      </div>
      <div style="background:var(--bg-card);border:1px solid rgba(255,69,96,0.3);border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">SELL ALERTS</div>
        <div style="font-size:15px;font-weight:600;color:{_RED}">{n_sell}</div>
      </div>
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">TOTAL PLANNED ($)</div>
        <div style="font-size:15px;font-weight:600;color:{_BLUE}">${total_planned:,.0f}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Render rows as styled cards ───────────────────────────────────────────
    tz_offset = float(st.session_state.get("tz_offset_hours", 3.0))

    for _, row in df.head(50).iterrows():
        sig   = str(row.get("signal", ""))
        sym   = str(row.get("symbol", ""))
        price = float(row.get("price", 0))
        score = float(row.get("score", 0))
        conf  = float(row.get("confidence", 0))
        amt   = float(row.get("planned_amount", 0))
        sl    = float(row.get("stop_loss", 0))
        tp    = float(row.get("take_profit", 0))
        mode  = str(row.get("strategy_mode", ""))
        ts_raw = str(row.get("timestamp", ""))

        # Format timestamp in local TZ
        try:
            from datetime import datetime, timezone, timedelta
            ts_dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            local_tz = timezone(timedelta(hours=tz_offset))
            ts_local = ts_dt.astimezone(local_tz).strftime("%b %d %H:%M:%S")
        except Exception:
            ts_local = ts_raw[:19] if len(ts_raw) > 19 else ts_raw

        sig_col  = _GREEN if sig == "BUY" else _RED
        sig_bg   = "rgba(0,201,167,0.07)" if sig == "BUY" else "rgba(255,69,96,0.07)"
        sig_bdr  = "rgba(0,201,167,0.3)"  if sig == "BUY" else "rgba(255,69,96,0.3)"
        arrow    = "▲" if sig == "BUY" else "▼"

        # Planned P&L estimates
        pl_buy_pct  = (tp / price - 1) * 100 if tp and price else 0
        pl_sell_pct = (price / tp - 1) * 100  if tp and price else 0
        target_pnl  = amt * (pl_buy_pct if sig == "BUY" else pl_sell_pct) / 100
        sl_loss     = amt * abs(price - sl) / price if sl and price else 0

        st.markdown(f"""
        <div style="background:{sig_bg};border:1px solid {sig_bdr};border-left:3px solid {sig_col};
          border-radius:4px;padding:10px 14px;margin:4px 0;font-family:var(--mono)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div>
              <span style="font-size:13px;font-weight:700;color:{sig_col}">{arrow} {sig}</span>
              <span style="font-size:11px;color:var(--text-pri);margin-left:8px;font-weight:600">{sym}</span>
              <span style="font-size:9px;color:var(--text-mute);margin-left:8px">{mode.upper()}</span>
            </div>
            <div style="font-size:9px;color:var(--text-mute)">{ts_local}</div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px 8px;font-size:10px">
            <div><span style="color:var(--text-mute)">PRICE </span><span style="color:var(--amber);font-weight:600">${price:,.4f}</span></div>
            <div><span style="color:var(--text-mute)">SCORE </span><span style="color:var(--text-pri)">{score:+.3f}</span></div>
            <div><span style="color:var(--text-mute)">CONF </span><span style="color:var(--text-pri)">{conf:.0f}%</span></div>
            <div><span style="color:var(--text-mute)">PLANNED </span><span style="color:{_BLUE}">${amt:,.0f}</span></div>
            <div><span style="color:var(--text-mute)">TARGET P&L </span><span style="color:{_GREEN if target_pnl >= 0 else _RED}">${target_pnl:+,.0f}</span></div>
          </div>
          {f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px 8px;font-size:9px;margin-top:4px;color:var(--text-mute)"><div>SL <span style="color:{_RED}">${sl:,.4f}</span></div><div>TP <span style="color:{_GREEN}">${tp:,.4f}</span></div><div>MAX LOSS <span style="color:{_RED}">-${sl_loss:,.0f}</span></div></div>' if sl and tp else ""}
        </div>
        """, unsafe_allow_html=True)

    if len(df) > 50:
        st.caption(f"Showing 50 of {len(df)} alerts. Download CSV below for full history.")

    # Download button
    try:
        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇ Download Alert Log CSV",
            data=csv_data,
            file_name=f"alert_log_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            key="dl_alert_log",
        )
    except Exception:
        pass
