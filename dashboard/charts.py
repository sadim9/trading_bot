"""
dashboard/charts.py — Institutional-Quality Plotly Chart Engine

Generates TradingView-style charts with:
  - OHLC Candlesticks
  - EMA 50/200 overlays
  - Bollinger Bands with fill
  - Support & Resistance levels
  - RSI subplot (shaded zones)
  - MACD subplot (histogram + signal)
  - Volume subplot (coloured by direction)
  - Trade signals as annotated arrows
  - Entry / Stop-Loss / Take-Profit horizontal lines
  - Full dark theme (#131722 background — TradingView palette)
"""

from __future__ import annotations
from typing import List, Optional
import pandas as pd
import numpy as np

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False


# ── TradingView Dark Palette ───────────────────────────────────────────────────
THEME = dict(
    bg          = "#131722",      # chart background
    bg_panel    = "#1E222D",      # panel / subplot bg
    grid        = "#1E2433",      # gridline colour
    text        = "#D1D4DC",      # default text
    text_dim    = "#787B86",      # secondary text
    candle_up   = "#26A69A",      # bullish candle
    candle_dn   = "#EF5350",      # bearish candle
    ema_fast    = "#F7931A",      # EMA 50  (orange)
    ema_slow    = "#2196F3",      # EMA 200 (blue)
    bb_mid      = "#9B59B6",      # BB middle band
    bb_fill     = "rgba(155,89,182,0.08)",
    vol_up      = "rgba(38,166,154,0.65)",
    vol_dn      = "rgba(239,83,80,0.65)",
    rsi_line    = "#60A5FA",
    rsi_ob      = "rgba(239,83,80,0.12)",
    rsi_os      = "rgba(38,166,154,0.12)",
    macd_line   = "#60A5FA",
    macd_signal = "#FB923C",
    macd_pos    = "rgba(38,166,154,0.75)",
    macd_neg    = "rgba(239,83,80,0.75)",
    buy_arrow   = "#00E676",
    sell_arrow  = "#FF1744",
    entry_line  = "#FFC107",
    sl_line     = "#FF5252",
    tp_line     = "#69F0AE",
    sr_support   = "rgba(38,166,154,0.4)",
    sr_resist    = "rgba(239,83,80,0.4)",
    # MA Cross — exact colours from user's original Pine Script indicator
    mac_short    = "#FF6D00",               # Short MA  (orange)
    mac_long     = "#43A047",               # Long MA   (green)
    mac_cross    = "#2962FF",               # Cross point (blue X)
    mac_bull_fill= "rgba(38,166,154,0.07)", # bullish zone fill
    mac_bear_fill= "rgba(239,83,80,0.07)",  # bearish zone fill
    mac_golden   = "#00E676",               # golden cross annotation
    mac_death    = "#FF5252",               # death cross annotation
    # Markov Chains signals — distinct diamond shape + purple palette
    mkv_buy      = "#CE93D8",               # Markov BUY  (purple)
    mkv_sell     = "#FF8A65",               # Markov SELL (deep orange)
    mkv_entry    = "rgba(206,147,216,0.15)",# entry zone fill
)

# ── Light Mode Palette ─────────────────────────────────────────────────────────
LIGHT_THEME = dict(
    bg          = "#F2F6FC",      # chart background — cool off-white
    bg_panel    = "#E8EEF8",      # panel / subplot bg
    grid        = "#C8D4E8",      # gridlines — clearly visible but subtle
    text        = "#0B1929",      # near-black for high contrast
    text_dim    = "#4A6580",      # secondary labels
    candle_up   = "#007A5E",      # bullish — darker green readable on white
    candle_dn   = "#C0001E",      # bearish — deeper red readable on white
    ema_fast    = "#D0620A",      # EMA 50  (burnt orange — readable)
    ema_slow    = "#1555A2",      # EMA 200 (deep blue)
    bb_mid      = "#6030BE",      # BB middle band (dark purple)
    bb_fill     = "rgba(96,48,190,0.07)",
    vol_up      = "rgba(0,122,94,0.55)",
    vol_dn      = "rgba(192,0,30,0.55)",
    rsi_line    = "#1555A2",
    rsi_ob      = "rgba(192,0,30,0.10)",
    rsi_os      = "rgba(0,122,94,0.10)",
    macd_line   = "#1555A2",
    macd_signal = "#C0600A",
    macd_pos    = "rgba(0,122,94,0.70)",
    macd_neg    = "rgba(192,0,30,0.70)",
    buy_arrow   = "#005C44",      # deep green arrow on light bg
    sell_arrow  = "#A00018",      # deep red arrow
    entry_line  = "#96620A",      # amber — visible on white
    sl_line     = "#C0001E",
    tp_line     = "#00735C",
    sr_support   = "rgba(0,115,92,0.40)",
    sr_resist    = "rgba(192,0,30,0.40)",
    # MA Cross
    mac_short    = "#C0600A",               # Short MA  (dark orange)
    mac_long     = "#2E7D32",               # Long MA   (forest green)
    mac_cross    = "#1555A2",               # Cross point (deep blue)
    mac_bull_fill= "rgba(0,115,92,0.07)",
    mac_bear_fill= "rgba(192,0,30,0.07)",
    mac_golden   = "#005C44",
    mac_death    = "#A00018",
    # Markov Chains
    mkv_buy      = "#6030BE",               # Markov BUY  (dark purple)
    mkv_sell     = "#C0600A",               # Markov SELL (dark orange)
    mkv_entry    = "rgba(96,48,190,0.12)",
)

ROW_HEIGHTS = [0.52, 0.14, 0.18, 0.16]   # [candles, volume, rsi, macd]


def _support_resistance(df: pd.DataFrame, n_levels: int = 3) -> tuple[list, list]:
    """
    Detect S/R via rolling pivot extremes.
    Returns (support_levels, resistance_levels) as price lists.
    """
    window = max(10, len(df) // 30)
    highs  = df["High"].rolling(window, center=True).max()
    lows   = df["Low"].rolling(window, center=True).min()

    resist = sorted(
        df["High"][df["High"] == highs].dropna().unique(),
        reverse=True
    )[:n_levels]
    support = sorted(
        df["Low"][df["Low"] == lows].dropna().unique()
    )[-n_levels:]

    return list(support), list(resist)


_INTRADAY_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h"}


def _intraday_xrange(df: pd.DataFrame, interval: str) -> dict:
    """
    Default the visible x-axis range so the chart doesn't open on ALL data.

    - Intraday (1m/5m/15m/1h/4h): show the last trading day.
    - Daily (1d): show the last 30 calendar days.
    - Weekly (1wk): show the last 26 weeks (~6 months).

    The full dataset remains loaded so panning backwards reveals earlier data.
    Returns a dict spread into xaxis kwargs; empty dict = no range restriction.
    """
    if len(df) < 2:
        return {}
    last_ts = df.index[-1]
    try:
        if interval in _INTRADAY_INTERVALS:
            day_start = pd.Timestamp(last_ts.date())
            x0 = day_start - pd.Timedelta(minutes=30)
            x1 = last_ts   + pd.Timedelta(hours=1)
            return {"range": [x0, x1]}
        if interval == "1d":
            x0 = last_ts - pd.Timedelta(days=30)
            return {"range": [x0, last_ts + pd.Timedelta(days=1)]}
        if interval == "1wk":
            x0 = last_ts - pd.Timedelta(weeks=26)
            return {"range": [x0, last_ts + pd.Timedelta(days=7)]}
    except Exception:
        pass
    return {}


def build_chart(
    df: pd.DataFrame,
    symbol: str,
    signals: Optional[List[dict]] = None,
    entry_price: Optional[float] = None,
    stop_loss: Optional[float]   = None,
    take_profit: Optional[float] = None,
    signal_type: Optional[str]   = None,
    n_candles: int = 120,
    # MA Cross parameters
    ma_short_period: int = 9,
    ma_long_period:  int = 21,
    show_ma_cross:   bool = True,
    # Markov Chains signals overlay
    markov_signals: Optional[List[dict]] = None,
    show_markov:    bool = False,
    # Theme
    light_mode: bool = False,
    # Timezone: offset from UTC in hours (e.g. 3.0 for UTC+3)
    tz_offset_hours: float = 0.0,
    # Bar interval — used to set default x-axis range for intraday charts
    interval: str = "1d",
) -> "go.Figure":
    """
    Build the full institutional chart figure.

    Args:
        df:              DataFrame with OHLCV + technical indicators
        symbol:          Ticker label
        signals:         List of historical signal dicts {date, signal, price}
        entry_price:     Current recommendation entry level
        stop_loss:       Current recommendation SL level
        take_profit:     Current recommendation TP level
        signal_type:     "BUY" | "SELL" | "HOLD"
        n_candles:       Number of most-recent bars to display
        ma_short_period: Short SMA period (default 9, matches Pine indicator)
        ma_long_period:  Long SMA period  (default 21, matches Pine indicator)
        show_ma_cross:   Toggle MA Cross overlay visibility

    Returns:
        plotly Figure object (ready for st.plotly_chart)
    """
    if not PLOTLY_OK:
        raise ImportError("plotly not installed. Run: pip install plotly")

    # Select the active colour palette for this render
    T = LIGHT_THEME if light_mode else THEME

    df = df.tail(n_candles).copy()

    # ── Apply timezone offset to x-axis ──────────────────────────────────────
    # Shift all timestamps so the chart displays in the user's local timezone.
    # The index is stored as naive UTC; we add the offset so Plotly labels
    # show local time rather than UTC.
    if tz_offset_hours != 0.0:
        from pandas import Timedelta
        df.index = df.index + Timedelta(hours=tz_offset_hours)
        if signals:
            signals = [
                {**s, "date": s["date"] + Timedelta(hours=tz_offset_hours)
                 if hasattr(s.get("date"), "total_seconds") or hasattr(s.get("date"), "year")
                 else s["date"]}
                for s in signals
            ]
        if markov_signals:
            markov_signals = [
                {**s, "date": s["date"] + Timedelta(hours=tz_offset_hours)
                 if hasattr(s.get("date"), "total_seconds") or hasattr(s.get("date"), "year")
                 else s["date"]}
                for s in markov_signals
            ]

    # ── MA Cross computation ──────────────────────────────────────────────────
    # Computed fresh from the sliced df so cross detection is accurate
    # Uses enough extra history so the warmup period is handled correctly
    if show_ma_cross and len(df) >= ma_long_period:
        mac_short = df["Close"].rolling(ma_short_period).mean()
        mac_long  = df["Close"].rolling(ma_long_period).mean()

        # Cross detection: short crossed above/below long this bar
        mac_cross_up   = (mac_short > mac_long) & (mac_short.shift(1) <= mac_long.shift(1))
        mac_cross_down = (mac_short < mac_long) & (mac_short.shift(1) >= mac_long.shift(1))

        # Zone fill: separate df into bull/bear segments for the fill
        mac_bull_zone  = mac_short > mac_long
    else:
        mac_short = mac_long = mac_cross_up = mac_cross_down = mac_bull_zone = None

    # ── Create subplot grid ───────────────────────────────────────────────────
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.01,   # tighter gap = more chart real estate
        row_heights=ROW_HEIGHTS,
        subplot_titles=None,     # no titles = no extra height allocation
    )

    # ── ROW 1: Candlesticks ───────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Price",
        increasing=dict(line=dict(color=T["candle_up"], width=1),
                        fillcolor=T["candle_up"]),
        decreasing=dict(line=dict(color=T["candle_dn"], width=1),
                        fillcolor=T["candle_dn"]),
        whiskerwidth=0.8,
    ), row=1, col=1)

    # ── EMA 50 & 200 ─────────────────────────────────────────────────────────
    if "ema_fast" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema_fast"],
            name="EMA 50",
            line=dict(color=T["ema_fast"], width=1.5),
            hovertemplate="%{y:.4f}",
        ), row=1, col=1)

    if "ema_slow" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema_slow"],
            name="EMA 200",
            line=dict(color=T["ema_slow"], width=1.8),
            hovertemplate="%{y:.4f}",
        ), row=1, col=1)

    # ── MA Cross Lines (Short + Long SMA) ───────────────────────────────────────
    # Colours match the original Pine Script indicator exactly:
    #   Short MA = #FF6D00 (orange), Long MA = #43A047 (green)
    #   Cross point = #2962FF (blue X marker)
    if show_ma_cross and mac_short is not None:
        # Background fill between the two MAs (bull = green tint, bear = red tint)
        # We draw two overlapping fills using the "tonexty" mode
        fig.add_trace(go.Scatter(
            x=df.index, y=mac_long,
            name="_mac_long_fill_base",
            line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False,
            hoverinfo="skip",
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df.index, y=mac_short,
            name="_mac_short_fill",
            line=dict(color="rgba(0,0,0,0)", width=0),
            fill="tonexty",
            fillcolor=T["mac_bull_fill"] if mac_bull_zone.iloc[-1] else T["mac_bear_fill"],
            showlegend=False,
            hoverinfo="skip",
        ), row=1, col=1)

        # Long MA line — #43A047 green
        fig.add_trace(go.Scatter(
            x=df.index, y=mac_long,
            name=f"SMA {ma_long_period}",
            line=dict(color=T["mac_long"], width=1.8),
            hovertemplate=f"SMA{ma_long_period}: %{{y:.4f}}<extra></extra>",
        ), row=1, col=1)

        # Short MA line — #FF6D00 orange
        fig.add_trace(go.Scatter(
            x=df.index, y=mac_short,
            name=f"SMA {ma_short_period}",
            line=dict(color=T["mac_short"], width=1.5),
            hovertemplate=f"SMA{ma_short_period}: %{{y:.4f}}<extra></extra>",
        ), row=1, col=1)

        # Cross point markers — #2962FF blue X (matches Pine plot.style_cross)
        cross_x_vals = df.index[mac_cross_up | mac_cross_down]
        cross_y_vals = mac_short[mac_cross_up | mac_cross_down]
        if len(cross_x_vals) > 0:
            fig.add_trace(go.Scatter(
                x=cross_x_vals,
                y=cross_y_vals,
                mode="markers",
                name="MA Cross",
                marker=dict(symbol="x", size=16, color=T["mac_cross"],
                            line=dict(color=T["mac_cross"], width=3)),
                hovertemplate="Cross @ %{y:.4f}<extra></extra>",
            ), row=1, col=1)

        # Annotate each cross with GOLDEN / DEATH label
        for idx in df.index[mac_cross_up]:
            fig.add_annotation(
                x=idx, y=float(mac_short.loc[idx]),
                text="G",
                font=dict(color=T["mac_golden"], size=11, family="JetBrains Mono, monospace"),
                bgcolor="rgba(0,230,118,0.15)",
                bordercolor=T["mac_golden"],
                borderwidth=1,
                showarrow=True,
                arrowcolor=T["mac_golden"],
                arrowhead=2,
                ay=25,
                row=1, col=1,
            )
        for idx in df.index[mac_cross_down]:
            fig.add_annotation(
                x=idx, y=float(mac_short.loc[idx]),
                text="D",
                font=dict(color=T["mac_death"], size=11, family="JetBrains Mono, monospace"),
                bgcolor="rgba(255,82,82,0.15)",
                bordercolor=T["mac_death"],
                borderwidth=1,
                showarrow=True,
                arrowcolor=T["mac_death"],
                arrowhead=2,
                ay=-25,
                row=1, col=1,
            )

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    if all(c in df.columns for c in ["bb_upper", "bb_mid", "bb_lower"]):
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_upper"],
            name="BB Upper",
            line=dict(color=T["bb_mid"], width=1, dash="dot"),
            showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_lower"],
            name="BB Lower",
            line=dict(color=T["bb_mid"], width=1, dash="dot"),
            fill="tonexty",
            fillcolor=T["bb_fill"],
            showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_mid"],
            name="BB Mid",
            line=dict(color=T["bb_mid"], width=1, dash="dash"),
            opacity=0.6,
        ), row=1, col=1)

    # ── Support & Resistance ──────────────────────────────────────────────────
    supports, resistances = _support_resistance(df, n_levels=2)
    x_range = [df.index[0], df.index[-1]]

    for lvl in supports:
        fig.add_shape(type="line",
            x0=x_range[0], x1=x_range[1], y0=lvl, y1=lvl,
            line=dict(color=T["sr_support"], width=1.2, dash="dot"),
            row=1, col=1)
        fig.add_annotation(
            x=x_range[1], y=lvl, text=f"S {lvl:.2f}",
            font=dict(color=T["candle_up"], size=10),
            showarrow=False, xanchor="right",
            row=1, col=1)

    for lvl in resistances:
        fig.add_shape(type="line",
            x0=x_range[0], x1=x_range[1], y0=lvl, y1=lvl,
            line=dict(color=T["sr_resist"], width=1.2, dash="dot"),
            row=1, col=1)
        fig.add_annotation(
            x=x_range[1], y=lvl, text=f"R {lvl:.2f}",
            font=dict(color=T["candle_dn"], size=10),
            showarrow=False, xanchor="right",
            row=1, col=1)

    # ── Entry / SL / TP lines ────────────────────────────────────────────────
    if entry_price and signal_type in ("BUY", "SELL"):
        for price, color, label in [
            (entry_price, T["entry_line"], f"Entry {entry_price:.4f}"),
            (stop_loss,   T["sl_line"],    f"SL {stop_loss:.4f}"),
            (take_profit, T["tp_line"],    f"TP {take_profit:.4f}"),
        ]:
            if price:
                fig.add_shape(type="line",
                    x0=x_range[0], x1=x_range[1], y0=price, y1=price,
                    line=dict(color=color, width=1.5, dash="dash"),
                    row=1, col=1)
                fig.add_annotation(
                    x=x_range[0], y=price, text=label,
                    font=dict(color=color, size=10, family="monospace"),
                    showarrow=False, xanchor="left",
                    bgcolor=T["bg_panel"],
                    bordercolor=color, borderwidth=1,
                    row=1, col=1)

    # ── Historical trade signals (arrows) ────────────────────────────────────
    if signals:
        buy_x, buy_y   = [], []
        sell_x, sell_y = [], []
        for sig in signals:
            sig_date = pd.to_datetime(sig.get("date") or sig.get("timestamp", ""))
            if sig_date in df.index or (len(df) > 0 and sig_date >= df.index[0]):
                price = float(sig.get("price", sig.get("entry_price", 0)))
                if sig.get("signal") == "BUY":
                    buy_x.append(sig_date)
                    buy_y.append(price * 0.990)   # slightly below candle
                elif sig.get("signal") == "SELL":
                    sell_x.append(sig_date)
                    sell_y.append(price * 1.010)  # slightly above candle

        if buy_x:
            fig.add_trace(go.Scatter(
                x=buy_x, y=buy_y,
                mode="markers",
                name="BUY Signal",
                marker=dict(symbol="triangle-up", size=14,
                            color=T["buy_arrow"],
                            line=dict(color="#00C853", width=1)),
                hovertemplate="BUY @ %{y:.4f}<extra></extra>",
            ), row=1, col=1)

        if sell_x:
            fig.add_trace(go.Scatter(
                x=sell_x, y=sell_y,
                mode="markers",
                name="SELL Signal",
                marker=dict(symbol="triangle-down", size=14,
                            color=T["sell_arrow"],
                            line=dict(color="#D50000", width=1)),
                hovertemplate="SELL @ %{y:.4f}<extra></extra>",
            ), row=1, col=1)

    # ── Markov Chains BUY/SELL markers (diamond shape, purple/orange) ────────
    if show_markov and markov_signals:
        mkv_buy_x,  mkv_buy_y  = [], []
        mkv_sell_x, mkv_sell_y = [], []
        for sig in markov_signals:
            sig_date = pd.to_datetime(sig.get("date") or sig.get("timestamp", ""))
            price    = float(sig.get("price", sig.get("entry_price", 0)))
            direction = sig.get("signal", "")
            if direction == "BUY":
                mkv_buy_x.append(sig_date)
                mkv_buy_y.append(price * 0.983)
            elif direction == "SELL":
                mkv_sell_x.append(sig_date)
                mkv_sell_y.append(price * 1.017)

        if mkv_buy_x:
            fig.add_trace(go.Scatter(
                x=mkv_buy_x, y=mkv_buy_y,
                mode="markers",
                name="Markov BUY",
                marker=dict(
                    symbol="diamond",
                    size=13,
                    color=T["mkv_buy"],
                    line=dict(color=T["mkv_buy"], width=2),
                ),
                hovertemplate="Markov BUY @ %{y:.4f}<extra></extra>",
            ), row=1, col=1)

        if mkv_sell_x:
            fig.add_trace(go.Scatter(
                x=mkv_sell_x, y=mkv_sell_y,
                mode="markers",
                name="Markov SELL",
                marker=dict(
                    symbol="diamond",
                    size=13,
                    color=T["mkv_sell"],
                    line=dict(color=T["mkv_sell"], width=2),
                ),
                hovertemplate="Markov SELL @ %{y:.4f}<extra></extra>",
            ), row=1, col=1)

    # ── EMA Fast gradient fill (subtle area below EMA fast line) ────────────
    if "ema_fast" in df.columns:
        _close_last = float(df["Close"].iloc[-1])
        _ema_last   = float(df["ema_fast"].iloc[-1])
        _trend_up   = _close_last >= _ema_last
        _fill_col   = "rgba(38,166,154,0.06)" if _trend_up else "rgba(239,83,80,0.06)"
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema_fast"],
            name="_ema_fill_base",
            line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Close"],
            name="_ema_fill_top",
            line=dict(color="rgba(0,0,0,0)", width=0),
            fill="tonexty",
            fillcolor=_fill_col,
            showlegend=False, hoverinfo="skip",
        ), row=1, col=1)

    # ── Last-price annotation (right-side label) ──────────────────────────────
    _last_px = float(df["Close"].iloc[-1])
    _prev_px = float(df["Close"].iloc[-2]) if len(df) > 1 else _last_px
    _px_chg  = (_last_px / _prev_px - 1) * 100 if _prev_px else 0
    _px_col  = T["candle_up"] if _px_chg >= 0 else T["candle_dn"]
    fig.add_annotation(
        x=df.index[-1], y=_last_px,
        text=f" {_last_px:,.4f} ({_px_chg:+.2f}%) ",
        font=dict(color=_px_col, size=11, family="JetBrains Mono, monospace"),
        bgcolor=T["bg_panel"],
        bordercolor=_px_col,
        borderwidth=1,
        showarrow=False,
        xanchor="left",
        xref="x", yref="y",
        row=1, col=1,
    )
    # Horizontal dashed line at last price
    fig.add_hline(
        y=_last_px, row=1, col=1,
        line=dict(color=_px_col, width=0.8, dash="dot"),
    )

    # ── ROW 2: Volume — gradient opacity based on relative vol ────────────────
    _vol_mean = df["Volume"].mean()
    _vol_high = [v >= _vol_mean * 1.5 for v in df["Volume"]]
    _vol_hi_bull = "rgba(0,100,76,0.85)"   if light_mode else "rgba(38,166,154,0.85)"
    _vol_hi_bear = "rgba(160,0,20,0.85)"   if light_mode else "rgba(239,83,80,0.85)"
    vol_colors = []
    for c, o, hi in zip(df["Close"], df["Open"], _vol_high):
        if c >= o:
            vol_colors.append(_vol_hi_bull if hi else T["vol_up"])
        else:
            vol_colors.append(_vol_hi_bear if hi else T["vol_dn"])

    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"],
        name="Volume",
        marker=dict(
            color=vol_colors,
            line=dict(width=0),
        ),
        showlegend=False,
        hovertemplate="Vol: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    if "vol_ma" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["vol_ma"],
            name="Vol MA",
            line=dict(color="#F59E0B", width=1.2, dash="dot"),
            showlegend=False,
            hovertemplate="Vol MA: %{y:,.0f}<extra></extra>",
        ), row=2, col=1)

    # ── ROW 3: RSI with gradient fill ─────────────────────────────────────────
    if "rsi" in df.columns:
        # Shaded zones
        fig.add_hrect(y0=70, y1=100, row=3, col=1,
                      fillcolor=T["rsi_ob"], line_width=0)
        fig.add_hrect(y0=0,  y1=30,  row=3, col=1,
                      fillcolor=T["rsi_os"], line_width=0)
        # RSI area fill
        fig.add_trace(go.Scatter(
            x=df.index, y=[50] * len(df),
            name="_rsi_base", showlegend=False, hoverinfo="skip",
            line=dict(color="rgba(0,0,0,0)", width=0),
        ), row=3, col=1)
        rsi_vals = df["rsi"].fillna(50)
        rsi_fill_colors = [
            "rgba(38,166,154,0.15)" if v >= 50 else "rgba(239,83,80,0.15)"
            for v in rsi_vals
        ]
        fig.add_trace(go.Scatter(
            x=df.index, y=rsi_vals,
            name="RSI",
            line=dict(color=T["rsi_line"], width=1.8),
            fill="tonexty",
            fillcolor="rgba(96,165,250,0.08)",
            hovertemplate="RSI: %{y:.1f}<extra></extra>",
        ), row=3, col=1)
        # Level lines at 70 / 50 / 30
        for lvl, col in [(70, T["candle_dn"]), (50, T["text_dim"]), (30, T["candle_up"])]:
            fig.add_hline(y=lvl, row=3, col=1,
                          line=dict(color=col, width=0.8, dash="dot"))

    # ── ROW 3.5: Volume Profile (horizontal bars on price axis) ────────────
    # Group volume into price buckets and show as horizontal bars overlaid on price
    try:
        _vp_n_bins = 20
        _vp_close  = df["Close"].values
        _vp_vol    = df["Volume"].values.astype(float)
        _vp_bins   = np.linspace(_vp_close.min(), _vp_close.max(), _vp_n_bins + 1)
        _vp_mids   = (_vp_bins[:-1] + _vp_bins[1:]) / 2
        _vp_vols   = np.zeros(_vp_n_bins)
        for _px_v, _vol_v in zip(_vp_close, _vp_vol):
            _bin_idx = np.searchsorted(_vp_bins, _px_v, side="right") - 1
            _bin_idx = int(np.clip(_bin_idx, 0, _vp_n_bins - 1))
            _vp_vols[_bin_idx] += _vol_v
        # Normalise to fraction of price range for overlay
        _vp_max  = _vp_vols.max()
        _vp_norm = (_vp_vols / _vp_max) if _vp_max > 0 else _vp_vols
        _vp_width = (df.index[-1] - df.index[0]) * 0.08  # 8% of x range
        _x_right  = df.index[-1]
        for _mid, _norm in zip(_vp_mids, _vp_norm):
            if _norm > 0.02:  # skip tiny bars
                _is_upper = _mid >= _vp_mids[len(_vp_mids)//2]
                _vp_color = "rgba(38,166,154,0.25)" if _is_upper else "rgba(239,83,80,0.25)"
                fig.add_shape(
                    type="rect",
                    x0=_x_right, x1=_x_right + _vp_width * _norm,
                    y0=_mid - (_vp_bins[1] - _vp_bins[0]) / 2,
                    y1=_mid + (_vp_bins[1] - _vp_bins[0]) / 2,
                    fillcolor=_vp_color,
                    line=dict(width=0),
                    row=1, col=1,
                )
    except Exception:
        pass  # Volume profile is optional

    # ── ROW 4: MACD with divergence colouring ────────────────────────────────
    if all(c in df.columns for c in ["macd", "macd_signal", "macd_hist"]):
        hist   = df["macd_hist"]
        # Colour: brightening green/red when momentum is increasing
        hist_colors = []
        for i, v in enumerate(hist):
            prev = hist.iloc[i-1] if i > 0 else v
            if v >= 0:
                hist_colors.append("rgba(38,166,154,0.9)" if v >= prev else "rgba(38,166,154,0.5)")
            else:
                hist_colors.append("rgba(239,83,80,0.9)" if v <= prev else "rgba(239,83,80,0.5)")

        fig.add_trace(go.Bar(
            x=df.index, y=hist,
            name="MACD Hist",
            marker=dict(color=hist_colors, line=dict(width=0)),
            showlegend=False,
            hovertemplate="Hist: %{y:.5f}<extra></extra>",
        ), row=4, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd"],
            name="MACD",
            line=dict(color=T["macd_line"], width=1.6),
            hovertemplate="MACD: %{y:.5f}<extra></extra>",
        ), row=4, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd_signal"],
            name="Signal",
            line=dict(color=T["macd_signal"], width=1.2),
            hovertemplate="Signal: %{y:.5f}<extra></extra>",
        ), row=4, col=1)
        fig.add_hline(y=0, row=4, col=1,
                      line=dict(color=T["text_dim"], width=0.8))

    # ── Global dark styling ───────────────────────────────────────────────────
    _chg_sign  = "+" if _px_chg >= 0 else ""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=T["bg"],
        plot_bgcolor =T["bg"],
        font=dict(family="JetBrains Mono, monospace", color=T["text"], size=11),
        title=dict(
            text=(
                f"<b>{symbol}</b>  "
                f"<span style='font-size:14px;color:{_px_col}'>"
                f"{_last_px:,.4f}  {_chg_sign}{_px_chg:.2f}%</span>"
            ),
            font=dict(size=16, color=T["text"]),
            x=0.01,
        ),
        legend=dict(
            orientation="h", y=1.01, x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=10),
        ),
        margin=dict(l=60, r=80, t=48, b=20),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=T["bg_panel"],
            bordercolor=T["grid"],
            font=dict(color=T["text"], family="JetBrains Mono, monospace"),
            namelength=20,
        ),
        dragmode="pan",
        xaxis_rangeslider_visible=False,
        height=860,
        # Mobile touch support — allow pinch-to-zoom and two-finger pan
        modebar=dict(orientation="v"),
        # uirevision: keeps zoom/pan state across Streamlit reruns.
        # Only reset when the symbol changes.
        uirevision=f"chart_{symbol}",
        transition=dict(duration=200, easing="cubic-in-out"),
        # Range selector buttons (TradingView-style time range buttons)
        xaxis=dict(
            rangeselector=dict(
                buttons=[
                    dict(count=1,  label="1H",   step="hour",  stepmode="backward"),
                    dict(count=4,  label="4H",   step="hour",  stepmode="backward"),
                    dict(count=1,  label="TODAY", step="day",   stepmode="todate"),
                    dict(count=1,  label="1D",   step="day",   stepmode="backward"),
                    dict(count=3,  label="3D",   step="day",   stepmode="backward"),
                    dict(count=7,  label="1W",   step="day",   stepmode="backward"),
                    dict(count=1,  label="1M",   step="month", stepmode="backward"),
                    dict(step="all", label="ALL"),
                ],
                bgcolor=T["bg_panel"],
                activecolor=T["grid"],
                # Index of the button that appears highlighted on load.
                # 6 = "1M" for daily; for intraday the xaxis range overrides this anyway.
                active=6,
                font=dict(color=T["text"], size=9, family="JetBrains Mono, monospace"),
                x=0.0, y=1.01, xanchor="left",
            ),
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikecolor=T["text_dim"], spikethickness=1, spikedash="dot",
            # Default visible range keeps chart from opening on ALL data.
            # For intraday: last trading day. For 1d: last 30 days. For 1wk: last 26 weeks.
            **_intraday_xrange(df, interval),
        ),
        # Spike lines
        yaxis=dict(showspikes=True, spikemode="toaxis", spikesnap="cursor",
                   spikecolor=T["text_dim"], spikethickness=1, spikedash="dot"),
    )

    # Grid styling for all axes
    axis_style = dict(
        gridcolor=T["grid"],
        gridwidth=0.5,
        zerolinecolor=T["grid"],
        showgrid=True,
        tickfont=dict(size=10, color=T["text_dim"]),
        linecolor=T["grid"],
    )

    for i in range(1, 5):
        # Build timezone label for x-axis title on the bottom row
        if tz_offset_hours == 0:
            _tz_label = "UTC"
        else:
            _tz_sign  = "+" if tz_offset_hours >= 0 else ""
            _tz_label = f"UTC{_tz_sign}{tz_offset_hours:g}"
        fig.update_xaxes(
            axis_style,
            row=i, col=1,
            showticklabels=(i == 4),
            automargin=False,
            fixedrange=False,
            title_text=_tz_label if i == 4 else None,
            title_font=dict(size=9, color=T["text_dim"]),
            tickformatstops=[
                dict(dtickrange=[None, 60000],    value="%H:%M:%S"),
                dict(dtickrange=[60000, 3600000], value="%H:%M"),
                dict(dtickrange=[3600000, None],  value="%b %d"),
            ],
        )
        fig.update_yaxes(
            axis_style,
            row=i, col=1,
            side="right",
            automargin=False,
            fixedrange=False,
        )

    # RSI y-axis fixed range
    fig.update_yaxes(range=[0, 100], row=3, col=1, fixedrange=True)  # RSI fixed Y is intentional

    # Rangebreaks: only apply weekend gaps for traditional stocks.
    # Crypto (USDT pairs, BTC-USD etc.) trades 24/7 — no weekend gaps.
    _sym_upper = symbol.upper()
    _is_crypto = any(s in _sym_upper for s in ("USDT","BTC","ETH","SOL","BNB",
                                                 "XRP","ADA","DOGE","MATIC",
                                                 "AVAX","LINK","ATOM","USD"))
    if not _is_crypto:
        fig.update_xaxes(
            rangebreaks=[dict(bounds=["sat", "mon"])],
            row=1, col=1,
        )

    return fig


def build_mini_chart(df: pd.DataFrame, symbol: str, height: int = 200) -> "go.Figure":
    """Small sparkline chart for the signal panel header."""
    if not PLOTLY_OK:
        raise ImportError("plotly not installed")
    df = df.tail(60)
    color = THEME["candle_up"] if df["Close"].iloc[-1] >= df["Close"].iloc[0] else THEME["candle_dn"]
    fig = go.Figure(go.Scatter(
        x=df.index, y=df["Close"],
        mode="lines",
        line=dict(color=color, width=1.5),
        fill="tozeroy",
        fillcolor=color.replace(")", ",0.08)").replace("rgb", "rgba") if "rgb" in color else f"{color}15",
    ))
    fig.update_layout(
        paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["bg"],
        margin=dict(l=0, r=0, t=0, b=0), height=height,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig
