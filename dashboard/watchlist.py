"""
dashboard/watchlist.py — Multi-Ticker Watchlist Scanner

Scans a configurable list of tickers in parallel and shows:
  - Live price and % change
  - Signal: BUY / SELL / HOLD with composite score
  - RSI, EMA trend, MA Cross, Volume ratio
  - Entry / SL / TP levels from the signal recommendation
  - Full expandable detail panel per ticker (with mini chart)
  - Alert badge + Discord/WhatsApp push when signals fire

Clicking any row switches the main chart to that ticker.
"""

from __future__ import annotations

import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore")

# ── Default watchlist presets ──────────────────────────────────────────────────
PRESET_LISTS = {
    "US Tech":           ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD"],
    "Crypto (Kraken)":  ["XBTUSD", "ETHUSD", "SOLUSD", "ADAUSD", "XRPUSD"],
    "Crypto (KuCoin)":  ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"],
    "US Indices":        ["SPY", "QQQ", "IWM", "DIA", "VIX"],
    "Commodities":       ["GLD", "SLV", "USO", "UNG", "WEAT"],
    "Gulf / MENA":       ["AAPL", "MSFT", "ARAMCO.SR", "EMAAR.DU", "FAB.AD"],
}

SIG_STYLE = {
    "BUY":  ("var(--green)", "▲ BUY",  "rgba(0,201,167,0.10)"),
    "SELL": ("var(--red)",   "▼ SELL", "rgba(255,69,96,0.10)"),
    "HOLD": ("var(--text-sec)", "◆ HOLD", "transparent"),
}

SCAN_CACHE_TTL = 60   # seconds


# ── Scan one ticker ────────────────────────────────────────────────────────────
def _scan_one(symbol: str, interval: str, source: str) -> Optional[dict]:
    """
    Fetch data + compute full signal breakdown for one ticker.
    Designed to run in a ThreadPoolExecutor.
    """
    try:
        from data.ingestion import load_data
        from signals.aggregator import SignalAggregator
        from strategies.ma_cross import MACrossStrategy
        from config import CONFIG

        df = load_data(symbol, interval=interval, period="60d", source=source,
                       crypto_limit=300)
        if df is None or len(df) < 5:
            return None

        close    = float(df["Close"].iloc[-1])
        prev     = float(df["Close"].iloc[-2])
        chg_pct  = (close / prev - 1) * 100 if prev else 0.0
        rsi_v    = float(df["rsi"].iloc[-1])       if "rsi"       in df.columns else 50.0
        ema_fast = float(df["ema_fast"].iloc[-1])  if "ema_fast"  in df.columns else close
        ema_slow = float(df["ema_slow"].iloc[-1])  if "ema_slow"  in df.columns else close
        vol_r    = float(df["vol_ratio"].iloc[-1]) if "vol_ratio" in df.columns else 1.0
        atr_v    = float(df["atr"].iloc[-1])       if "atr"       in df.columns else 0.0

        agg = SignalAggregator(CONFIG)
        rec = agg.analyse(df, symbol)

        mac     = MACrossStrategy(9, 21)
        mac_res = mac.score(df)
        sub     = mac_res.sub_scores or {}
        cross_up   = bool(sub.get("cross_up",   0))
        cross_down = bool(sub.get("cross_down", 0))
        short_ma   = sub.get("short_ma", 0)
        long_ma    = sub.get("long_ma",  0)

        if cross_up:   mac_str = "GOLDEN X"
        elif cross_down: mac_str = "DEATH X"
        elif short_ma > long_ma: mac_str = "Bull"
        else:          mac_str = "Bear"

        # Strategy breakdown
        breakdown = {}
        for sname, sdata in rec.strategy_breakdown.items():
            breakdown[sname] = {
                "score":  sdata.get("score", 0),
                "signal": sdata.get("signal", "HOLD"),
            }

        return {
            "symbol":     symbol,
            "df":         df,           # kept for mini-chart rendering
            "price":      close,
            "chg_pct":    chg_pct,
            "signal":     rec.signal,
            "score":      rec.composite_score,
            "conf":       rec.confidence_pct,
            "entry":      rec.entry_price,
            "sl":         rec.stop_loss,
            "tp":         rec.take_profit,
            "pos_pct":    rec.position_size_pct,
            "rsi":        rsi_v,
            "atr":        atr_v,
            "vol_r":      vol_r,
            "ema_trend":  "↑" if ema_fast > ema_slow else "↓",
            "mac":        mac_str,
            "bars":       len(df),
            "breakdown":  breakdown,
            "reasoning":  rec.reasoning[:5],  # first 5 lines
            "ts":         datetime.now(),
            "error":      None,
        }
    except Exception as e:
        return {
            "symbol": symbol, "error": str(e)[:80],
            "signal": "?", "score": 0, "price": 0,
        }


def scan_watchlist(
    symbols: List[str],
    interval: str = "1h",
    source:   str = "yfinance",
    max_workers: int = 6,
) -> List[dict]:
    """Scan all symbols in parallel, return list of result dicts."""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_scan_one, sym, interval, source): sym for sym in symbols}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)
    order = {"BUY": 0, "SELL": 1, "HOLD": 2, "?": 3}
    results.sort(key=lambda x: (order.get(x.get("signal", "?"), 3),
                                 -abs(x.get("score", 0))))
    return results


# ── Main render ────────────────────────────────────────────────────────────────
def render_watchlist(main_symbol: str, main_source: str, main_interval: str):
    """
    Render the full watchlist panel with expandable per-ticker detail views.
    Returns the symbol clicked by the user (or None).
    """
    clicked_symbol = None

    # ── Controls ──────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 1.5, 1.5])

    preset = c1.selectbox("Preset", ["Custom"] + list(PRESET_LISTS.keys()), key="wl_preset")
    if preset != "Custom" and st.session_state.get("wl_last_preset") != preset:
        st.session_state["wl_symbols_text"] = ", ".join(PRESET_LISTS[preset])
        st.session_state["wl_last_preset"]  = preset

    symbols_raw = c2.text_input(
        "Symbols",
        value=st.session_state.get("wl_symbols_text", "AAPL, MSFT, NVDA, GOOGL, TSLA"),
        key="wl_symbols_input",
        label_visibility="collapsed",
        placeholder="AAPL, MSFT, NVDA ...",
    )

    wl_source = c3.selectbox(
        "Source",
        ["yfinance", "kraken", "kucoin", "bitoasis", "sample"],
        index=["yfinance", "kraken", "kucoin", "bitoasis", "sample"].index(
            st.session_state.get("wl_source", main_source)
            if st.session_state.get("wl_source", main_source) in
            ["yfinance", "kraken", "kucoin", "bitoasis", "sample"] else "yfinance"
        ),
        key="wl_source",
        label_visibility="collapsed",
    )

    wl_interval = c4.selectbox(
        "Interval",
        ["5m", "15m", "1h", "4h", "1d"],
        index=2,
        key="wl_interval",
        label_visibility="collapsed",
    )

    scan_btn = c5.button("⟳ SCAN ALL", type="primary", use_container_width=True)

    symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
    if not symbols:
        st.info("Add some symbols above and click SCAN ALL")
        return None

    # Auto-add the main chart symbol if not already in the list
    if main_symbol.upper() not in symbols:
        symbols = [main_symbol.upper()] + symbols

    # ── Cache + trigger ───────────────────────────────────────────────────────
    cache_key  = f"wl_results_{wl_source}_{wl_interval}"
    last_scan  = st.session_state.get("wl_last_scan", 0)
    cached     = st.session_state.get(cache_key, [])
    needs_scan = scan_btn or not cached or (time.time() - last_scan > SCAN_CACHE_TTL)

    if needs_scan:
        with st.spinner(f"Scanning {len(symbols)} tickers..."):
            results = scan_watchlist(symbols, interval=wl_interval, source=wl_source)
        st.session_state[cache_key]      = results
        st.session_state["wl_last_scan"] = time.time()
    else:
        results = cached
        age = int(time.time() - last_scan)
        st.caption(f"Scan from {age}s ago · next auto-scan in {max(0, SCAN_CACHE_TTL - age)}s")

    if not results:
        st.warning("No data returned. Check symbols and source.")
        return None

    # ── Summary strip ─────────────────────────────────────────────────────────
    buys  = sum(1 for r in results if r.get("signal") == "BUY")
    sells = sum(1 for r in results if r.get("signal") == "SELL")
    holds = sum(1 for r in results if r.get("signal") == "HOLD")
    total = len(results)

    st.markdown(
        f'<div style="display:flex;gap:16px;margin-bottom:10px;font-family:var(--mono);font-size:11px;'
        f'padding:8px 12px;background:var(--bg-surface);border-radius:4px;'
        f'border:1px solid var(--border)">'
        f'<span style="color:var(--green)">▲ BUY: <b>{buys}</b></span>'
        f'<span style="color:var(--red)">▼ SELL: <b>{sells}</b></span>'
        f'<span style="color:var(--text-sec)">◆ HOLD: <b>{holds}</b></span>'
        f'<span style="color:var(--text-mute)">/ {total} tickers scanned</span>'
        f'<span style="color:var(--text-mute);margin-left:auto">{wl_interval} · {wl_source.upper()}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Column headers ────────────────────────────────────────────────────────
    GRID = "140px 95px 75px 80px 60px 65px 55px 65px 80px 85px"
    st.markdown(
        f'<div style="display:grid;grid-template-columns:{GRID};'
        f'gap:4px;padding:5px 8px;font-family:var(--mono);font-size:9px;'
        f'letter-spacing:.12em;text-transform:uppercase;color:var(--text-mute);'
        f'border-bottom:1px solid var(--border)">'
        f'<span>SYMBOL</span><span>PRICE</span><span>CHANGE</span>'
        f'<span>SIGNAL</span><span>SCORE</span><span>RSI</span>'
        f'<span>TREND</span><span>MA CROSS</span><span>VOL</span>'
        f'<span>ACTION</span></div>',
        unsafe_allow_html=True,
    )

    # ── Result rows with expandable details ───────────────────────────────────
    for r in results:
        sym       = r.get("symbol", "?")
        err       = r.get("error")
        is_active = sym == main_symbol.upper()

        if err:
            st.markdown(
                f'<div style="display:grid;grid-template-columns:{GRID};gap:4px;'
                f'padding:6px 8px;font-family:var(--mono);font-size:10px;'
                f'border-bottom:1px solid var(--border);opacity:0.4">'
                f'<span style="color:var(--text-pri)">{sym}</span>'
                f'<span style="color:var(--red)" style="grid-column:2/-1">Error: {err}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            continue

        price   = r.get("price",    0)
        chg     = r.get("chg_pct",  0)
        sig     = r.get("signal",   "HOLD")
        score   = r.get("score",    0)
        conf    = r.get("conf",     0)
        rsi     = r.get("rsi",      50)
        ema_tr  = r.get("ema_trend","?")
        mac     = r.get("mac",      "?")
        vol_r   = r.get("vol_r",    1.0)
        entry   = r.get("entry",    price)
        sl      = r.get("sl",       price)
        tp      = r.get("tp",       price)
        pos_pct = r.get("pos_pct",  0)

        sig_col, sig_label, sig_bg = SIG_STYLE.get(sig, SIG_STYLE["HOLD"])
        chg_col  = "var(--green)" if chg >= 0 else "var(--red)"
        chg_arr  = "▲" if chg >= 0 else "▼"
        rsi_col  = "var(--red)" if rsi > 70 else ("var(--green)" if rsi < 30 else "var(--text-sec)")
        mac_col  = ("var(--green)" if "GOLDEN" in mac or mac == "Bull"
                     else "var(--red)"  if "DEATH"  in mac or mac == "Bear"
                     else "var(--text-sec)")
        ema_col  = "var(--green)" if ema_tr == "↑" else "var(--red)"
        vol_col  = "var(--amber)" if vol_r > 2.0 else "var(--text-sec)"
        row_bg   = "rgba(75,159,255,0.06)" if is_active else sig_bg
        border   = "border-left:3px solid var(--blue)" if is_active else ""

        st.markdown(
            f'<div style="display:grid;grid-template-columns:{GRID};'
            f'gap:4px;padding:7px 8px;font-family:var(--mono);font-size:11px;'
            f'background:{row_bg};border-bottom:1px solid var(--border);{border};'
            f'border-radius:2px;align-items:center">'
            f'<span style="color:var(--text-pri);font-weight:{"700" if is_active else "400"}">'
            f'{"▶ " if is_active else ""}{sym}</span>'
            f'<span style="color:var(--text-pri)">${price:,.4f}</span>'
            f'<span style="color:{chg_col}">{chg_arr}{abs(chg):.2f}%</span>'
            f'<span style="color:{sig_col};font-weight:600">{sig_label}</span>'
            f'<span style="color:{sig_col}">{score:+.2f}</span>'
            f'<span style="color:{rsi_col}">{rsi:.1f}</span>'
            f'<span style="color:{ema_col}">{ema_tr}</span>'
            f'<span style="color:{mac_col};font-size:9px">{mac}</span>'
            f'<span style="color:{vol_col}">{vol_r:.1f}×</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Action buttons row
        ab1, ab2, ab3 = st.columns([1, 1, 1])
        if not is_active:
            if ab1.button(f"📊 Chart", key=f"wl_sw_{sym}", use_container_width=True,
                          help=f"Switch main chart to {sym}"):
                clicked_symbol = sym

        # Expandable detail panel
        with st.expander(
            f"🔍 {sym} — Full Details  ·  {sig_label}  @  ${price:,.4f}",
            expanded=False,
        ):
            _render_ticker_detail(r, sym, sig, score, conf)

    # ── Alert firing ──────────────────────────────────────────────────────────
    engine = st.session_state.get("alert_engine")
    if engine:
        for r in results:
            sig = r.get("signal")
            sym = r.get("symbol", "")
            if sig in ("BUY", "SELL") and not r.get("error"):
                engine.fire(
                    symbol=sym,
                    signal=sig,
                    price=r.get("price", 0),
                    reason=(
                        f"Watchlist [{wl_interval}] {sig} | "
                        f"score {r.get('score',0):+.3f} | "
                        f"RSI {r.get('rsi',50):.1f} | "
                        f"conf {r.get('conf',0):.0f}%"
                    ),
                    confidence=r.get("conf", 0),
                )

    return clicked_symbol


# ── Per-ticker expanded detail panel ─────────────────────────────────────────
def _render_ticker_detail(r: dict, sym: str, sig: str, score: float, conf: float):
    """Render the full detail panel for a single ticker inside an expander."""
    try:
        import plotly.graph_objects as go
        from dashboard.charts import THEME, PLOTLY_OK
        HAVE_PLOTLY = PLOTLY_OK
    except ImportError:
        HAVE_PLOTLY = False

    price   = r.get("price",   0)
    entry   = r.get("entry",   price)
    sl      = r.get("sl",      price)
    tp      = r.get("tp",      price)
    pos_pct = r.get("pos_pct", 0)
    rsi     = r.get("rsi",     50)
    vol_r   = r.get("vol_r",   1.0)
    atr     = r.get("atr",     0)
    df      = r.get("df")

    rr = abs(tp - entry) / max(abs(sl - entry), 1e-9)
    sl_pct = (sl / entry - 1) * 100 if entry else 0
    tp_pct = (tp / entry - 1) * 100 if entry else 0

    # ── KPIs ────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Entry",      f"${entry:,.4f}")
    k2.metric("Stop Loss",  f"${sl:,.4f}", delta=f"{sl_pct:.2f}%")
    k3.metric("Take Profit",f"${tp:,.4f}", delta=f"+{tp_pct:.2f}%")
    k4.metric("R:R Ratio",  f"{rr:.2f}:1")
    k5.metric("Position",   f"{pos_pct:.1f}%")

    # ── Mini chart ────────────────────────────────────────────────────────
    if df is not None and HAVE_PLOTLY:
        try:
            df_plot = df.tail(60)
            color   = THEME["candle_up"] if df_plot["Close"].iloc[-1] >= df_plot["Close"].iloc[0] else THEME["candle_dn"]
            fig_mini = go.Figure()
            fig_mini.add_trace(go.Candlestick(
                x=df_plot.index,
                open=df_plot["Open"], high=df_plot["High"],
                low=df_plot["Low"],   close=df_plot["Close"],
                name=sym,
                increasing=dict(line=dict(color=THEME["candle_up"]), fillcolor=THEME["candle_up"]),
                decreasing=dict(line=dict(color=THEME["candle_dn"]), fillcolor=THEME["candle_dn"]),
                showlegend=False,
            ))
            # EMA fast/slow if available
            if "ema_fast" in df_plot.columns:
                fig_mini.add_trace(go.Scatter(
                    x=df_plot.index, y=df_plot["ema_fast"],
                    line=dict(color=THEME["ema_fast"], width=1.2),
                    name="EMA Fast", showlegend=False,
                ))
            if "ema_slow" in df_plot.columns:
                fig_mini.add_trace(go.Scatter(
                    x=df_plot.index, y=df_plot["ema_slow"],
                    line=dict(color=THEME["ema_slow"], width=1.2),
                    name="EMA Slow", showlegend=False,
                ))
            # Entry/SL/TP lines
            if sig in ("BUY", "SELL"):
                for px, clr, lbl in [
                    (entry, THEME["entry_line"], f"Entry {entry:.4f}"),
                    (sl,    THEME["sl_line"],    f"SL {sl:.4f}"),
                    (tp,    THEME["tp_line"],    f"TP {tp:.4f}"),
                ]:
                    fig_mini.add_hline(y=px, line=dict(color=clr, width=1.2, dash="dash"),
                                       annotation_text=lbl,
                                       annotation_font=dict(color=clr, size=9))

            fig_mini.update_layout(
                paper_bgcolor=THEME["bg"],
                plot_bgcolor=THEME["bg"],
                font=dict(color=THEME["text"], family="monospace"),
                height=220,
                margin=dict(l=40, r=20, t=10, b=20),
                xaxis=dict(gridcolor=THEME["grid"], showticklabels=True,
                           rangeslider_visible=False, tickfont=dict(size=9)),
                yaxis=dict(gridcolor=THEME["grid"], side="right", tickfont=dict(size=9)),
                hovermode="x unified",
            )
            st.plotly_chart(fig_mini, width="stretch", config=dict(displayModeBar=False))
        except Exception:
            pass

    # ── Strategy breakdown ──────────────────────────────────────────────
    breakdown = r.get("breakdown", {})
    if breakdown:
        st.markdown(
            '<div style="font-family:var(--mono);font-size:9px;letter-spacing:.12em;'
            'text-transform:uppercase;color:var(--text-mute);margin:6px 0 4px">STRATEGY BREAKDOWN</div>',
            unsafe_allow_html=True,
        )
        wmap = {"trend": 0.30, "momentum": 0.25, "mean_reversion": 0.25, "ai_model": 0.20, "markov_chains": 1.0}
        for sname, sdata in breakdown.items():
            sc   = sdata.get("score", 0)
            pct  = int((sc + 1) / 2 * 100)
            fill = "var(--green)" if sc > 0.1 else ("var(--red)" if sc < -0.1 else "var(--border-lit)")
            w    = wmap.get(sname, 0.25)
            st.markdown(
                f'<div style="margin:3px 0">'
                f'<div style="display:flex;justify-content:space-between;'
                f'font-family:var(--mono);font-size:10px;color:var(--text-sec)">'
                f'<span>{sname.replace("_"," ").title()} · {w:.0%}</span>'
                f'<span style="color:{fill}">{sc:+.3f}</span>'
                f'</div>'
                f'<div style="height:3px;background:var(--border);border-radius:2px">'
                f'<div style="width:{pct}%;height:100%;background:{fill};border-radius:2px"></div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

    # ── Signal reasoning ─────────────────────────────────────────────────
    reasoning = r.get("reasoning", [])
    if reasoning:
        with st.expander("Signal Reasoning", expanded=False):
            for line in reasoning:
                if line and not line.startswith("["):
                    st.markdown(
                        f'<div style="font-family:var(--mono);font-size:10px;'
                        f'color:var(--text-sec);padding:2px 0">{line}</div>',
                        unsafe_allow_html=True,
                    )

    # ── Indicator snapshot ────────────────────────────────────────────────
    ind_c1, ind_c2, ind_c3 = st.columns(3)
    ind_c1.metric("RSI 14",    f"{rsi:.1f}",  delta="Overbought" if rsi > 70 else ("Oversold" if rsi < 30 else "Neutral"))
    ind_c2.metric("Vol Ratio", f"{vol_r:.2f}×", delta="Spike" if vol_r > 2 else "")
    ind_c3.metric("ATR",       f"${atr:.4f}" if atr > 0 else "—")
