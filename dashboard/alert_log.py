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
    # outcome tracking — filled when price hits SL or TP
    "status", "exit_price", "pnl", "pnl_pct", "closed_at",
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


_DEDUP_WINDOW_SECONDS = 120


def _recently_logged(log_path: Path, symbol: str, signal: str) -> bool:
    """Return True if the same symbol+signal was logged within the dedup window."""
    try:
        if not log_path.exists():
            return False
        with open(log_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=_DEDUP_WINDOW_SECONDS)
        for row in reversed(rows):
            if row.get("symbol") == symbol and row.get("signal") == signal:
                try:
                    ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        return True
                except Exception:
                    pass
                break
    except Exception:
        pass
    return False


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

    if _recently_logged(log_path, symbol, signal):
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
        "status":         "open",
        "exit_price":     "",
        "pnl":            "",
        "pnl_pct":        "",
        "closed_at":      "",
    }
    try:
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_COLUMNS)
            writer.writerow(row)
    except Exception:
        pass


def update_alert_outcomes(symbol: str, current_price: float) -> int:
    """
    Check every open alert for *symbol* against *current_price*.
    Close alerts whose SL or TP has been crossed and write realized P&L back.
    Returns the number of alerts closed this call.
    """
    closed = 0
    for log_path in [_LOG_FILE, Path(".cache/alert_log.csv")]:
        if not log_path.exists():
            continue
        try:
            rows = []
            with open(log_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                existing_cols = reader.fieldnames or []
                for row in reader:
                    # Migrate rows that pre-date the outcome columns
                    if "status" not in row:
                        row["status"]    = "open"
                        row["exit_price"] = ""
                        row["pnl"]       = ""
                        row["pnl_pct"]   = ""
                        row["closed_at"] = ""

                    if (
                        row.get("symbol") == symbol
                        and row.get("status", "open") == "open"
                    ):
                        try:
                            sig = row.get("signal", "")
                            ep  = float(row.get("entry_price") or row.get("price") or 0)
                            sl  = float(row.get("stop_loss")  or 0)
                            tp  = float(row.get("take_profit") or 0)
                            amt = float(row.get("planned_amount") or 0)

                            exit_px     = None
                            exit_reason = None

                            if sig == "BUY":
                                if sl and current_price <= sl:
                                    exit_px, exit_reason = sl, "stop_loss"
                                elif tp and current_price >= tp:
                                    exit_px, exit_reason = tp, "take_profit"
                            elif sig == "SELL":
                                if sl and current_price >= sl:
                                    exit_px, exit_reason = sl, "stop_loss"
                                elif tp and current_price <= tp:
                                    exit_px, exit_reason = tp, "take_profit"

                            if exit_px and ep:
                                if sig == "BUY":
                                    pct = (exit_px - ep) / ep
                                else:
                                    pct = (ep - exit_px) / ep
                                pnl = pct * amt if amt else pct * ep
                                row["status"]    = "closed"
                                row["exit_price"] = round(exit_px, 6)
                                row["pnl"]       = round(pnl, 4)
                                row["pnl_pct"]   = round(pct * 100, 4)
                                row["closed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                                closed += 1
                        except Exception:
                            pass

                    rows.append(row)

            # Rewrite only if something changed
            if closed:
                with open(log_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=_COLUMNS, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
        except Exception:
            pass
        break  # only write to the first path that exists
    return closed


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

    # Migrate existing CSVs that predate outcome columns
    for col in ("status", "exit_price", "pnl", "pnl_pct", "closed_at"):
        if col not in df.columns:
            df[col] = "" if col != "status" else "open"

    # Summary stats
    total      = len(df)
    n_buy      = (df["signal"] == "BUY").sum()
    n_sell     = (df["signal"] == "SELL").sum()
    n_open     = (df["status"] == "open").sum()
    n_closed   = (df["status"] == "closed").sum()
    total_planned = float(df["planned_amount"].fillna(0).sum()) if "planned_amount" in df.columns else 0.0

    # Realized P&L from closed alerts
    closed_df   = df[df["status"] == "closed"].copy()
    realized_pnl = 0.0
    wins = losses = 0
    if not closed_df.empty:
        _pnl_vals = pd.to_numeric(closed_df["pnl"], errors="coerce").dropna()
        realized_pnl = float(_pnl_vals.sum())
        wins   = int((_pnl_vals > 0).sum())
        losses = int((_pnl_vals <= 0).sum())
    win_rate = wins / n_closed * 100 if n_closed else 0.0
    pnl_col  = _GREEN if realized_pnl >= 0 else _RED

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-bottom:10px">
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">TOTAL ALERTS</div>
        <div style="font-size:15px;font-weight:600;color:var(--text-pri)">{total}</div>
      </div>
      <div style="background:var(--bg-card);border:1px solid rgba(0,201,167,0.3);border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">BUY / SELL</div>
        <div style="font-size:15px;font-weight:600"><span style="color:{_GREEN}">{n_buy}</span><span style="color:var(--text-mute)"> / </span><span style="color:{_RED}">{n_sell}</span></div>
      </div>
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">OPEN / CLOSED</div>
        <div style="font-size:15px;font-weight:600;color:var(--text-pri)">{n_open} / {n_closed}</div>
      </div>
      <div style="background:var(--bg-card);border:1px solid {("rgba(0,201,167,0.3)" if realized_pnl >= 0 else "rgba(255,69,96,0.3)")};border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">REALIZED P&L</div>
        <div style="font-size:15px;font-weight:600;color:{pnl_col}">${realized_pnl:+,.2f}</div>
      </div>
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:4px;
        padding:8px 10px;font-family:var(--mono)">
        <div style="font-size:8px;color:var(--text-mute);letter-spacing:.12em;margin-bottom:2px">WIN RATE</div>
        <div style="font-size:15px;font-weight:600;color:{_GREEN if win_rate >= 50 else _RED}">{win_rate:.0f}%</div>
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
        sig      = str(row.get("signal", ""))
        sym      = str(row.get("symbol", ""))
        price    = float(row.get("price", 0) or 0)
        score    = float(row.get("score", 0) or 0)
        conf     = float(row.get("confidence", 0) or 0)
        amt      = float(row.get("planned_amount", 0) or 0)
        sl       = float(row.get("stop_loss", 0) or 0)
        tp       = float(row.get("take_profit", 0) or 0)
        mode     = str(row.get("strategy_mode", ""))
        ts_raw   = str(row.get("timestamp", ""))
        status   = str(row.get("status", "open") or "open")
        exit_px_raw = row.get("exit_price", "")
        pnl_raw     = row.get("pnl", "")
        pnl_pct_raw = row.get("pnl_pct", "")
        closed_at   = str(row.get("closed_at", "") or "")

        exit_px  = float(exit_px_raw)  if exit_px_raw not in ("", None) else None
        realized_pnl  = float(pnl_raw) if pnl_raw not in ("", None) else None
        realized_pct  = float(pnl_pct_raw) if pnl_pct_raw not in ("", None) else None

        # Format timestamps in local TZ
        try:
            ts_dt    = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            local_tz = timezone(timedelta(hours=tz_offset))
            ts_local = ts_dt.astimezone(local_tz).strftime("%b %d %H:%M:%S")
        except Exception:
            ts_local = ts_raw[:19] if len(ts_raw) > 19 else ts_raw

        closed_at_local = ""
        if closed_at:
            try:
                ca_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                closed_at_local = ca_dt.astimezone(timezone(timedelta(hours=tz_offset))).strftime("%b %d %H:%M")
            except Exception:
                closed_at_local = closed_at[:16]

        sig_col  = _GREEN if sig == "BUY" else _RED
        sig_bg   = "rgba(0,201,167,0.07)" if sig == "BUY" else "rgba(255,69,96,0.07)"
        sig_bdr  = "rgba(0,201,167,0.3)"  if sig == "BUY" else "rgba(255,69,96,0.3)"
        arrow    = "▲" if sig == "BUY" else "▼"

        # Planned P&L estimates (shown only while open)
        pl_buy_pct  = (tp / price - 1) * 100 if tp and price else 0
        pl_sell_pct = (price / tp - 1) * 100  if tp and price else 0
        target_pnl  = amt * (pl_buy_pct if sig == "BUY" else pl_sell_pct) / 100
        sl_loss     = amt * abs(price - sl) / price if sl and price else 0

        # Status badge
        if status == "closed":
            status_html = f'<span style="background:rgba(75,159,255,0.15);color:{_BLUE};font-size:8px;padding:1px 5px;border-radius:3px;margin-left:6px">CLOSED</span>'
        else:
            status_html = f'<span style="background:rgba(0,201,167,0.12);color:{_GREEN};font-size:8px;padding:1px 5px;border-radius:3px;margin-left:6px">OPEN</span>'

        # P&L row — realized if closed, planned if still open
        if status == "closed" and realized_pnl is not None:
            pnl_color   = _GREEN if realized_pnl >= 0 else _RED
            pnl_label   = "REALIZED P&L"
            pnl_display = f'${realized_pnl:+,.2f}'
            pct_display = f' ({realized_pct:+.2f}%)' if realized_pct is not None else ""
            exit_display = f'<div><span style="color:var(--text-mute)">EXIT PRICE </span><span style="color:{_AMBER}">${exit_px:,.4f}</span></div>' if exit_px else ""
            closed_display = f'<div><span style="color:var(--text-mute)">CLOSED </span><span style="color:var(--text-sec)">{closed_at_local}</span></div>' if closed_at_local else ""
            pnl_row = (
                f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px 8px;font-size:10px;margin-top:6px;'
                f'padding-top:6px;border-top:1px solid rgba(255,255,255,0.05)">'
                f'<div><span style="color:var(--text-mute)">{pnl_label} </span>'
                f'<span style="color:{pnl_color};font-weight:700">{pnl_display}{pct_display}</span></div>'
                f'{exit_display}{closed_display}</div>'
            )
        else:
            pnl_row = (
                f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px 8px;font-size:9px;margin-top:4px;color:var(--text-mute)">'
                f'<div>SL <span style="color:{_RED}">${sl:,.4f}</span></div>'
                f'<div>TP <span style="color:{_GREEN}">${tp:,.4f}</span></div>'
                f'<div>TARGET P&L <span style="color:{_GREEN if target_pnl >= 0 else _RED}">${target_pnl:+,.0f}</span> · MAX LOSS <span style="color:{_RED}">-${sl_loss:,.0f}</span></div>'
                f'</div>'
            ) if sl and tp else ""

        st.markdown(f"""
        <div style="background:{sig_bg};border:1px solid {sig_bdr};border-left:3px solid {sig_col};
          border-radius:4px;padding:10px 14px;margin:4px 0;font-family:var(--mono)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div>
              <span style="font-size:13px;font-weight:700;color:{sig_col}">{arrow} {sig}</span>
              <span style="font-size:11px;color:var(--text-pri);margin-left:8px;font-weight:600">{sym}</span>
              <span style="font-size:9px;color:var(--text-mute);margin-left:8px">{mode.upper()}</span>
              {status_html}
            </div>
            <div style="font-size:9px;color:var(--text-mute)">{ts_local}</div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px 8px;font-size:10px">
            <div><span style="color:var(--text-mute)">ENTRY </span><span style="color:var(--amber);font-weight:600">${price:,.4f}</span></div>
            <div><span style="color:var(--text-mute)">SCORE </span><span style="color:var(--text-pri)">{score:+.3f}</span></div>
            <div><span style="color:var(--text-mute)">CONF </span><span style="color:var(--text-pri)">{conf:.0f}%</span></div>
            <div><span style="color:var(--text-mute)">PLANNED </span><span style="color:{_BLUE}">${amt:,.0f}</span></div>
          </div>
          {pnl_row}
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
