"""
dashboard/watchlist.py -- Multi-Ticker Watchlist Scanner

Scans a configurable list of tickers in parallel and shows:
  - Live price and % change
  - Signal: BUY / SELL / HOLD with composite score
  - RSI, EMA trend, MA Cross, Volume ratio
  - Entry / SL / TP levels from the signal recommendation
  - Per-symbol strategy selection and notification toggle
  - Full expandable detail panel per ticker (with mini chart)
  - Alert badge + Discord/Telegram push when signals fire

Per-symbol settings are persisted to watchlist_settings.json (shared
with the background worker so notifications run even when UI is closed).

Clicking any row switches the main chart to that ticker.
"""

from __future__ import annotations

import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import os

import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore")

# ── Settings persistence ───────────────────────────────────────────────────────
_SETTINGS_DIR  = Path(os.getenv("SETTINGS_DIR", "/app/logs"))
_WATCHLIST_FILE = _SETTINGS_DIR / "watchlist_settings.json"


def _load_watchlist_cfg() -> dict:
    """Load per-symbol watchlist settings from disk."""
    for path in [_WATCHLIST_FILE, Path(".cache/watchlist_settings.json")]:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_watchlist_cfg(cfg: dict):
    """Persist per-symbol watchlist settings to disk (shared with background worker)."""
    for dirpath in [_SETTINGS_DIR, Path(".cache")]:
        try:
            dirpath.mkdir(parents=True, exist_ok=True)
            path = dirpath / "watchlist_settings.json"
            tmp  = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            tmp.replace(path)
            return
        except Exception:
            continue


# ── Default watchlist presets ──────────────────────────────────────────────────
PRESET_LISTS = {
    "US Tech":          ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD"],
    "Crypto (Kraken)":  ["XBTUSD", "ETHUSD", "SOLUSD", "ADAUSD", "XRPUSD"],
    "Crypto (KuCoin)":  ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"],
    "US Indices":       ["SPY", "QQQ", "IWM", "DIA", "VIX"],
    "Commodities":      ["GLD", "SLV", "USO", "UNG", "WEAT"],
    "Gulf / MENA":      ["AAPL", "MSFT", "ARAMCO.SR", "EMAAR.DU", "FAB.AD"],
}

_STRATEGY_OPTS  = ["Multi-Strategy", "Markov Chains", "Markov + Multi"]
_STRATEGY_VALS  = ["multi", "markov", "markov_multi"]

_C = {
    "green":    "#00c9a7",
    "red":      "#ff4560",
    "amber":    "#f5a623",
    "blue":     "#4c9be8",
    "text_pri": "#dce4f5",
    "text_sec": "#8899bb",
    "text_mute": "#4a5a7a",
    "bg":       "#080e1a",
    "bg_surf":  "#0c1322",
    "bg_panel": "#101828",
    "border":   "#1a2540",
    "border_lit": "#2a3f6f",
}

SIG_STYLE = {
    "BUY":  (_C["green"],    "BUY",  "rgba(0,201,167,0.10)"),
    "SELL": (_C["red"],      "SELL", "rgba(255,69,96,0.10)"),
    "HOLD": (_C["text_sec"], "HOLD", "transparent"),
}

SCAN_CACHE_TTL = 60


# ── Scan one ticker ────────────────────────────────────────────────────────────
def _scan_one(symbol: str, interval: str, source: str,
              strategy_mode: str = "multi") -> Optional[dict]:
    """Fetch data + compute full signal breakdown for one ticker."""
    try:
        from data.ingestion import load_data
        from signals.aggregator import SignalAggregator
        from strategies.ma_cross import MACrossStrategy
        from config import CONFIG

        df = None
        last_err = ""
        for _src in [source, "yfinance", "sample"]:
            try:
                df = load_data(symbol, interval=interval, period="60d",
                               source=_src, crypto_limit=300)
                if df is not None and len(df) >= 5:
                    break
            except Exception as _e:
                last_err = str(_e)
                df = None
                continue

        if df is None or len(df) < 5:
            return {"symbol": symbol, "error": f"No data ({last_err[:60]})",
                    "signal": "?", "price": 0, "score": 0}

        close    = float(df["Close"].iloc[-1])
        prev     = float(df["Close"].iloc[-2])
        chg_pct  = (close / prev - 1) * 100 if prev else 0.0
        rsi_v    = float(df["rsi"].iloc[-1])       if "rsi"       in df.columns else 50.0
        ema_fast = float(df["ema_fast"].iloc[-1])  if "ema_fast"  in df.columns else close
        ema_slow = float(df["ema_slow"].iloc[-1])  if "ema_slow"  in df.columns else close
        vol_r    = float(df["vol_ratio"].iloc[-1]) if "vol_ratio" in df.columns else 1.0
        atr_v    = float(df["atr"].iloc[-1])       if "atr"       in df.columns else 0.0

        agg = SignalAggregator(CONFIG, strategy_mode=strategy_mode)
        rec = agg.analyse(df, symbol)

        mac     = MACrossStrategy(9, 21)
        mac_res = mac.score(df)
        sub     = mac_res.sub_scores or {}
        cross_up   = bool(sub.get("cross_up",   0))
        cross_down = bool(sub.get("cross_down", 0))
        short_ma   = sub.get("short_ma", 0)
        long_ma    = sub.get("long_ma",  0)

        if cross_up:         mac_str = "GOLDEN X"
        elif cross_down:     mac_str = "DEATH X"
        elif short_ma > long_ma: mac_str = "Bull"
        else:                mac_str = "Bear"

        breakdown = {}
        for sname, sdata in rec.strategy_breakdown.items():
            breakdown[sname] = {
                "score":  sdata.get("score", 0),
                "signal": sdata.get("signal", "HOLD"),
            }

        return {
            "symbol":    symbol,
            "df":        df,
            "price":     close,
            "chg_pct":   chg_pct,
            "signal":    rec.signal,
            "score":     rec.composite_score,
            "conf":      rec.confidence_pct,
            "entry":     rec.entry_price,
            "sl":        rec.stop_loss,
            "tp":        rec.take_profit,
            "pos_pct":   rec.position_size_pct,
            "rsi":       rsi_v,
            "atr":       atr_v,
            "vol_r":     vol_r,
            "ema_trend": "UP" if ema_fast > ema_slow else "DN",
            "mac":       mac_str,
            "bars":      len(df),
            "breakdown": breakdown,
            "reasoning": rec.reasoning[:5],
            "ts":        datetime.now(),
            "error":     None,
            "strategy_mode": strategy_mode,
        }
    except Exception as e:
        return {
            "symbol": symbol, "error": str(e)[:80],
            "signal": "?", "score": 0, "price": 0,
        }


def scan_watchlist(
    symbols: List[str],
    interval: str = "1h",
    source: str = "yfinance",
    sym_strategies: dict = None,
    max_workers: int = 6,
) -> List[dict]:
    """Scan all symbols in parallel, applying per-symbol strategy overrides."""
    if sym_strategies is None:
        sym_strategies = {}
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(
                _scan_one,
                sym,
                # per-symbol interval override, fallback to global interval
                sym_strategies.get(sym, {}).get("interval_override", "(default)") if sym_strategies.get(sym, {}).get("interval_override", "(default)") != "(default)" else interval,
                # per-symbol source override, fallback to global source
                sym_strategies.get(sym, {}).get("source_override", "(default)") if sym_strategies.get(sym, {}).get("source_override", "(default)") != "(default)" else source,
                sym_strategies.get(sym, {}).get("strategy", "multi"),
            ): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)
    order = {"BUY": 0, "SELL": 1, "HOLD": 2, "?": 3, None: 4}
    results.sort(key=lambda x: (order.get(x.get("signal", "?"), 3),
                                 -abs(x.get("score", 0))))
    return results


# ── Main render ────────────────────────────────────────────────────────────────
def render_watchlist(main_symbol: str, main_source: str, main_interval: str):
    """
    Render the full watchlist panel.
    Returns the symbol clicked by the user (or None).
    """
    clicked_symbol = None

    # Load persisted per-symbol settings
    wl_cfg = st.session_state.get("_wl_cfg")
    if wl_cfg is None:
        wl_cfg = _load_watchlist_cfg()
        st.session_state["_wl_cfg"] = wl_cfg

    # ── Controls row ──────────────────────────────────────────────────────────
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

    _wl_sources = ["yfinance", "kraken", "kucoin", "tradingview",
                   "bitoasis", "coingecko", "sample"]
    _wl_cur_src = st.session_state.get("wl_source", main_source)
    _wl_src_idx = _wl_sources.index(_wl_cur_src) if _wl_cur_src in _wl_sources else 0
    wl_source = c3.selectbox(
        "Source", _wl_sources, index=_wl_src_idx,
        key="wl_source", label_visibility="collapsed",
    )

    wl_interval = c4.selectbox(
        "Interval", ["5m", "15m", "1h", "4h", "1d"],
        index=2, key="wl_interval", label_visibility="collapsed",
    )

    scan_btn = c5.button("SCAN ALL", type="primary", use_container_width=True)

    symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
    if not symbols:
        st.info("Add some symbols above and click SCAN ALL")
        return None

    if main_symbol.upper() not in symbols:
        symbols = [main_symbol.upper()] + symbols

    # ── Per-symbol settings panel ─────────────────────────────────────────────
    with st.expander("Per-Symbol Settings (Strategy & Notifications)", expanded=False):
        st.markdown(
            '<div style="font-family:monospace;font-size:9px;letter-spacing:.1em;'
            'color:#4a5a7a;padding:4px 0 8px">Configure strategy and background '
            'notification settings per symbol. Changes are saved immediately and '
            'used by the background worker even when the dashboard is closed.</div>',
            unsafe_allow_html=True,
        )
        cfg_changed = False
        hdr1, hdr2, hdr3, hdr4, hdr5 = st.columns([1.5, 1.8, 1.5, 1.5, 0.8])
        hdr1.markdown('<span style="font-family:monospace;font-size:9px;color:#4a5a7a">SYMBOL</span>', unsafe_allow_html=True)
        hdr2.markdown('<span style="font-family:monospace;font-size:9px;color:#4a5a7a">STRATEGY</span>', unsafe_allow_html=True)
        hdr3.markdown('<span style="font-family:monospace;font-size:9px;color:#4a5a7a">INTERVAL</span>', unsafe_allow_html=True)
        hdr4.markdown('<span style="font-family:monospace;font-size:9px;color:#4a5a7a">SOURCE OVERRIDE</span>', unsafe_allow_html=True)
        hdr5.markdown('<span style="font-family:monospace;font-size:9px;color:#4a5a7a">NOTIFY</span>', unsafe_allow_html=True)

        _ivl_opts_sym = ["(default)", "5m", "15m", "1h", "4h", "1d"]
        src_opts_sym = ["(default)"] + _wl_sources
        for sym in symbols:
            sym_data = wl_cfg.get(sym, {})
            col1, col2, col3, col4, col5 = st.columns([1.5, 1.8, 1.5, 1.5, 0.8])
            col1.markdown(
                f'<div style="font-family:monospace;font-size:11px;color:#dce4f5;'
                f'padding-top:6px">{sym}</div>', unsafe_allow_html=True
            )
            cur_strat = sym_data.get("strategy", "multi")
            strat_idx = _STRATEGY_VALS.index(cur_strat) if cur_strat in _STRATEGY_VALS else 0
            new_strat_label = col2.selectbox(
                f"strat_{sym}", _STRATEGY_OPTS, index=strat_idx,
                label_visibility="collapsed", key=f"wl_strat_{sym}",
            )
            new_strat = _STRATEGY_VALS[_STRATEGY_OPTS.index(new_strat_label)]

            cur_ivl_override = sym_data.get("interval_override", "(default)")
            ivl_ov_idx = _ivl_opts_sym.index(cur_ivl_override) if cur_ivl_override in _ivl_opts_sym else 0
            new_ivl_ov = col3.selectbox(
                f"ivl_{sym}", _ivl_opts_sym, index=ivl_ov_idx,
                label_visibility="collapsed", key=f"wl_ivl_{sym}",
            )

            cur_src_override = sym_data.get("source_override", "(default)")
            src_ov_idx = src_opts_sym.index(cur_src_override) if cur_src_override in src_opts_sym else 0
            new_src_ov = col4.selectbox(
                f"src_{sym}", src_opts_sym, index=src_ov_idx,
                label_visibility="collapsed", key=f"wl_src_{sym}",
            )

            cur_notify = sym_data.get("notify", True)
            new_notify = col5.toggle("", value=cur_notify, key=f"wl_notify_{sym}")

            # Detect changes
            if (new_strat != cur_strat
                    or new_ivl_ov != cur_ivl_override
                    or new_src_ov != cur_src_override
                    or new_notify != cur_notify):
                wl_cfg[sym] = {
                    "strategy":         new_strat,
                    "interval_override": new_ivl_ov,
                    "source_override":  new_src_ov,
                    "source": new_src_ov if new_src_ov != "(default)" else wl_source,
                    "notify":           new_notify,
                }
                cfg_changed = True

        if cfg_changed:
            st.session_state["_wl_cfg"] = wl_cfg
            _save_watchlist_cfg(wl_cfg)
            st.toast("Watchlist settings saved — background worker updated")

    # Build per-symbol strategy map for this scan
    sym_strategies = {sym: wl_cfg.get(sym, {}) for sym in symbols}

    # ── Cache + scan trigger ──────────────────────────────────────────────────
    cache_key  = f"wl_results_{wl_source}_{wl_interval}"
    last_scan  = st.session_state.get("wl_last_scan", 0)
    cached     = st.session_state.get(cache_key, [])
    needs_scan = scan_btn or not cached or (time.time() - last_scan > SCAN_CACHE_TTL)

    if needs_scan:
        with st.spinner(f"Scanning {len(symbols)} tickers..."):
            results = scan_watchlist(
                symbols, interval=wl_interval, source=wl_source,
                sym_strategies=sym_strategies,
            )
        st.session_state[cache_key]      = results
        st.session_state["wl_last_scan"] = time.time()
    else:
        results = cached
        age = int(time.time() - last_scan)
        st.caption(f"Scan from {age}s ago - next auto-scan in {max(0, SCAN_CACHE_TTL - age)}s")

    if not results:
        st.warning("No data returned. Check symbols and source.")
        return None

    # ── Summary strip ─────────────────────────────────────────────────────────
    buys  = sum(1 for r in results if r.get("signal") == "BUY")
    sells = sum(1 for r in results if r.get("signal") == "SELL")
    holds = sum(1 for r in results if r.get("signal") == "HOLD")
    total = len(results)

    st.markdown(
        f'<div style="display:flex;gap:16px;margin-bottom:10px;font-family:monospace;'
        f'font-size:11px;padding:8px 12px;background:#0c1322;border-radius:4px;'
        f'border:1px solid #1a2540">'
        f'<span style="color:#00c9a7">BUY: <b>{buys}</b></span>'
        f'<span style="color:#ff4560">SELL: <b>{sells}</b></span>'
        f'<span style="color:#8899bb">HOLD: <b>{holds}</b></span>'
        f'<span style="color:#4a5a7a">/ {total} tickers</span>'
        f'<span style="color:#4a5a7a;margin-left:auto">'
        f'{wl_interval} · {wl_source.upper()}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Column headers ────────────────────────────────────────────────────────
    GRID = "130px 90px 70px 75px 55px 60px 55px 65px 70px 80px 90px"
    st.markdown(
        f'<div style="display:grid;grid-template-columns:{GRID};'
        f'gap:4px;padding:5px 8px;font-family:monospace;font-size:9px;'
        f'letter-spacing:.12em;text-transform:uppercase;color:#4a5a7a;'
        f'border-bottom:1px solid #1a2540">'
        f'<span>SYMBOL</span><span>PRICE</span><span>CHG</span>'
        f'<span>SIGNAL</span><span>SCORE</span><span>RSI</span>'
        f'<span>TREND</span><span>MA X</span><span>VOL</span>'
        f'<span>STRATEGY</span><span>ACTION</span></div>',
        unsafe_allow_html=True,
    )

    # ── Result rows ───────────────────────────────────────────────────────────
    for r in results:
        sym      = r.get("symbol", "?")
        err      = r.get("error")
        is_active = sym == main_symbol.upper()
        sym_mode  = r.get("strategy_mode", wl_cfg.get(sym, {}).get("strategy", "multi"))
        mode_short = {"multi": "MULTI", "markov": "MRKV", "markov_multi": "MRK+M"}.get(sym_mode, sym_mode.upper()[:5])

        if err:
            st.markdown(
                f'<div style="display:grid;grid-template-columns:{GRID};gap:4px;'
                f'padding:6px 8px;font-family:monospace;font-size:10px;'
                f'border-bottom:1px solid #1a2540;opacity:0.4">'
                f'<span style="color:#dce4f5">{sym}</span>'
                f'<span style="color:#ff4560;grid-column:2/-1">Error: {err}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            continue

        price   = r.get("price",   0)
        chg     = r.get("chg_pct", 0)
        sig     = r.get("signal",  "HOLD")
        score   = r.get("score",   0)
        conf    = r.get("conf",    0)
        rsi     = r.get("rsi",     50)
        ema_tr  = r.get("ema_trend", "?")
        mac     = r.get("mac",     "?")
        vol_r   = r.get("vol_r",   1.0)
        entry   = r.get("entry",   price)
        sl      = r.get("sl",      price)
        tp      = r.get("tp",      price)
        pos_pct = r.get("pos_pct", 0)

        sig_col, sig_label, sig_bg = SIG_STYLE.get(sig, SIG_STYLE["HOLD"])
        chg_col  = "#00c9a7" if chg >= 0 else "#ff4560"
        chg_arr  = "+" if chg >= 0 else ""
        rsi_col  = "#ff4560" if rsi > 70 else ("#00c9a7" if rsi < 30 else "#8899bb")
        mac_col  = ("#00c9a7" if "GOLDEN" in mac or mac == "Bull"
                     else "#ff4560" if "DEATH" in mac or mac == "Bear"
                     else "#8899bb")
        ema_col  = "#00c9a7" if ema_tr == "UP" else "#ff4560"
        vol_col  = "#f5a623" if vol_r > 2.0 else "#8899bb"
        row_bg   = "rgba(75,159,255,0.06)" if is_active else sig_bg
        border   = "border-left:3px solid #4c9be8;" if is_active else ""
        notify_on = wl_cfg.get(sym, {}).get("notify", True)
        bell_col  = "#f5a623" if notify_on else "#2a3f6f"

        st.markdown(
            f'<div style="display:grid;grid-template-columns:{GRID};'
            f'gap:4px;padding:7px 8px;font-family:monospace;font-size:11px;'
            f'background:{row_bg};border-bottom:1px solid #1a2540;{border}'
            f'border-radius:2px;align-items:center">'
            f'<span style="color:#dce4f5;font-weight:{"700" if is_active else "400"}">'
            f'{"[A] " if is_active else ""}{sym}</span>'
            f'<span style="color:#dce4f5">${price:,.4f}</span>'
            f'<span style="color:{chg_col}">{chg_arr}{abs(chg):.2f}%</span>'
            f'<span style="color:{sig_col};font-weight:600">{sig_label}</span>'
            f'<span style="color:{sig_col}">{score:+.2f}</span>'
            f'<span style="color:{rsi_col}">{rsi:.1f}</span>'
            f'<span style="color:{ema_col}">{ema_tr}</span>'
            f'<span style="color:{mac_col};font-size:9px">{mac}</span>'
            f'<span style="color:{vol_col}">{vol_r:.1f}x</span>'
            f'<span style="color:#8899bb;font-size:9px">'
            f'<span style="color:{bell_col}">{"[N]" if notify_on else "[-]"}</span> {mode_short}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Action buttons
        ab1, ab2 = st.columns([1, 1])
        if not is_active:
            if ab1.button(f"Chart {sym}", key=f"wl_sw_{sym}",
                          use_container_width=True, help=f"Switch chart to {sym}"):
                clicked_symbol = sym

        with st.expander(f"{sym} -- {sig_label}  @  ${price:,.4f}", expanded=False):
            _render_ticker_detail(r, sym, sig, score, conf)

    # ── Alert firing (on-screen + push channels) ──────────────────────────────
    engine = st.session_state.get("alert_engine")
    if engine:
        for r in results:
            sig = r.get("signal")
            sym = r.get("symbol", "")
            do_notify = wl_cfg.get(sym, {}).get("notify", True)
            if sig in ("BUY", "SELL") and not r.get("error") and do_notify:
                engine.fire(
                    symbol=sym,
                    signal=sig,
                    price=r.get("price", 0),
                    reason=(
                        f"Watchlist [{wl_interval}] {sig} | "
                        f"score {r.get('score', 0):+.3f} | "
                        f"RSI {r.get('rsi', 50):.1f} | "
                        f"conf {r.get('conf', 0):.0f}% | "
                        f"mode {r.get('strategy_mode', 'multi')}"
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

    rr     = abs(tp - entry) / max(abs(sl - entry), 1e-9)
    sl_pct = (sl / entry - 1) * 100 if entry else 0
    tp_pct = (tp / entry - 1) * 100 if entry else 0

    # KPIs
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Entry",       f"${entry:,.4f}")
    k2.metric("Stop Loss",   f"${sl:,.4f}",  delta=f"{sl_pct:.2f}%")
    k3.metric("Take Profit", f"${tp:,.4f}",  delta=f"+{tp_pct:.2f}%")
    k4.metric("R:R Ratio",   f"{rr:.2f}:1")
    k5.metric("Position",    f"{pos_pct:.1f}%")

    # Mini candlestick chart
    if df is not None and HAVE_PLOTLY:
        try:
            df_plot = df.tail(60)
            fig_mini = go.Figure()
            fig_mini.add_trace(go.Candlestick(
                x=df_plot.index,
                open=df_plot["Open"], high=df_plot["High"],
                low=df_plot["Low"],   close=df_plot["Close"],
                name=sym,
                increasing=dict(line=dict(color=THEME["candle_up"]),
                                fillcolor=THEME["candle_up"]),
                decreasing=dict(line=dict(color=THEME["candle_dn"]),
                                fillcolor=THEME["candle_dn"]),
                showlegend=False,
            ))
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
            if sig in ("BUY", "SELL"):
                for px, clr, lbl in [
                    (entry, THEME["entry_line"], f"Entry {entry:.4f}"),
                    (sl,    THEME["sl_line"],    f"SL {sl:.4f}"),
                    (tp,    THEME["tp_line"],    f"TP {tp:.4f}"),
                ]:
                    fig_mini.add_hline(
                        y=px, line=dict(color=clr, width=1.2, dash="dash"),
                        annotation_text=lbl,
                        annotation_font=dict(color=clr, size=9),
                    )
            fig_mini.update_layout(
                paper_bgcolor=THEME["bg"],
                plot_bgcolor=THEME["bg"],
                font=dict(color=THEME["text"], family="monospace"),
                height=220,
                margin=dict(l=40, r=20, t=10, b=20),
                xaxis=dict(gridcolor=THEME["grid"], showticklabels=True,
                           rangeslider_visible=False, tickfont=dict(size=9)),
                yaxis=dict(gridcolor=THEME["grid"], side="right",
                           tickfont=dict(size=9)),
                hovermode="x unified",
            )
            st.plotly_chart(fig_mini, width="stretch",
                            config=dict(displayModeBar=False))
        except Exception:
            pass

    # Indicator snapshot
    ind_cols = st.columns(4)
    ind_cols[0].metric("RSI 14",     f"{rsi:.1f}")
    ind_cols[1].metric("ATR",        f"{atr:.4f}")
    ind_cols[2].metric("Vol Ratio",  f"{vol_r:.2f}x")
    ind_cols[3].metric("Confidence", f"{conf:.0f}%")

    # Strategy breakdown bars
    breakdown = r.get("breakdown", {})
    if breakdown:
        st.markdown(
            '<div style="font-family:monospace;font-size:9px;letter-spacing:.12em;'
            'text-transform:uppercase;color:#4a5a7a;margin:6px 0 4px">'
            'STRATEGY BREAKDOWN</div>',
            unsafe_allow_html=True,
        )
        wmap = {"trend": 0.30, "momentum": 0.25, "mean_reversion": 0.25,
                "ai_model": 0.20, "markov_chains": 1.0}
        for sname, sdata in breakdown.items():
            sc   = sdata.get("score", 0)
            pct  = int((sc + 1) / 2 * 100)
            fill = "#00c9a7" if sc > 0.1 else ("#ff4560" if sc < -0.1 else "#2a3f6f")
            w    = wmap.get(sname, 0.25)
            st.markdown(
                f'<div style="margin:3px 0">'
                f'<div style="display:flex;justify-content:space-between;'
                f'font-family:monospace;font-size:10px;color:#8899bb">'
                f'<span>{sname.replace("_", " ").title()} {w:.0%}</span>'
                f'<span style="color:{fill}">{sc:+.3f}</span></div>'
                f'<div style="height:3px;background:#1a2540;border-radius:2px">'
                f'<div style="width:{pct}%;height:100%;background:{fill};'
                f'border-radius:2px"></div></div></div>',
                unsafe_allow_html=True,
            )

    # Signal reasoning
    reasoning = r.get("reasoning", [])
    if reasoning:
        with st.expander("Signal Reasoning", expanded=False):
            for line in reasoning:
                if line and not line.startswith("["):
                    st.markdown(
                        f'<div style="font-family:monospace;font-size:10px;'
                        f'color:#8899bb;padding:2px 0">{line}</div>',
                        unsafe_allow_html=True,
                    )
