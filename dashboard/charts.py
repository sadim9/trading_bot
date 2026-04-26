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

    df = df.tail(n_candles).copy()

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
        increasing=dict(line=dict(color=THEME["candle_up"], width=1),
                        fillcolor=THEME["candle_up"]),
        decreasing=dict(line=dict(color=THEME["candle_dn"], width=1),
                        fillcolor=THEME["candle_dn"]),
        whiskerwidth=0.8,
    ), row=1, col=1)

    # ── EMA 50 & 200 ─────────────────────────────────────────────────────────
    if "ema_fast" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema_fast"],
            name="EMA 50",
            line=dict(color=THEME["ema_fast"], width=1.5),
            hovertemplate="%{y:.4f}",
        ), row=1, col=1)

    if "ema_slow" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema_slow"],
            name="EMA 200",
            line=dict(color=THEME["ema_slow"], width=1.8),
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
            fillcolor=THEME["mac_bull_fill"] if mac_bull_zone.iloc[-1] else THEME["mac_bear_fill"],
            showlegend=False,
            hoverinfo="skip",
        ), row=1, col=1)

        # Long MA line — #43A047 green
        fig.add_trace(go.Scatter(
            x=df.index, y=mac_long,
            name=f"SMA {ma_long_period}",
            line=dict(color=THEME["mac_long"], width=1.8),
            hovertemplate=f"SMA{ma_long_period}: %{{y:.4f}}<extra></extra>",
        ), row=1, col=1)

        # Short MA line — #FF6D00 orange
        fig.add_trace(go.Scatter(
            x=df.index, y=mac_short,
            name=f"SMA {ma_short_period}",
            line=dict(color=THEME["mac_short"], width=1.5),
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
                marker=dict(symbol="x", size=16, color=THEME["mac_cross"],
                            line=dict(color=THEME["mac_cross"], width=3)),
                hovertemplate="Cross @ %{y:.4f}<extra></extra>",
            ), row=1, col=1)

        # Annotate each cross with GOLDEN / DEATH label
        for idx in df.index[mac_cross_up]:
            fig.add_annotation(
                x=idx, y=float(mac_short.loc[idx]),
                text="G",
                font=dict(color=THEME["mac_golden"], size=11, family="JetBrains Mono, monospace"),
                bgcolor="rgba(0,230,118,0.15)",
                bordercolor=THEME["mac_golden"],
                borderwidth=1,
                showarrow=True,
                arrowcolor=THEME["mac_golden"],
                arrowhead=2,
                ay=25,
                row=1, col=1,
            )
        for idx in df.index[mac_cross_down]:
            fig.add_annotation(
                x=idx, y=float(mac_short.loc[idx]),
                text="D",
                font=dict(color=THEME["mac_death"], size=11, family="JetBrains Mono, monospace"),
                bgcolor="rgba(255,82,82,0.15)",
                bordercolor=THEME["mac_death"],
                borderwidth=1,
                showarrow=True,
                arrowcolor=THEME["mac_death"],
                arrowhead=2,
                ay=-25,
                row=1, col=1,
            )

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    if all(c in df.columns for c in ["bb_upper", "bb_mid", "bb_lower"]):
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_upper"],
            name="BB Upper",
            line=dict(color=THEME["bb_mid"], width=1, dash="dot"),
            showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_lower"],
            name="BB Lower",
            line=dict(color=THEME["bb_mid"], width=1, dash="dot"),
            fill="tonexty",
            fillcolor=THEME["bb_fill"],
            showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_mid"],
            name="BB Mid",
            line=dict(color=THEME["bb_mid"], width=1, dash="dash"),
            opacity=0.6,
        ), row=1, col=1)

    # ── Support & Resistance ──────────────────────────────────────────────────
    supports, resistances = _support_resistance(df, n_levels=2)
    x_range = [df.index[0], df.index[-1]]

    for lvl in supports:
        fig.add_shape(type="line",
            x0=x_range[0], x1=x_range[1], y0=lvl, y1=lvl,
            line=dict(color=THEME["sr_support"], width=1.2, dash="dot"),
            row=1, col=1)
        fig.add_annotation(
            x=x_range[1], y=lvl, text=f"S {lvl:.2f}",
            font=dict(color=THEME["candle_up"], size=10),
            showarrow=False, xanchor="right",
            row=1, col=1)

    for lvl in resistances:
        fig.add_shape(type="line",
            x0=x_range[0], x1=x_range[1], y0=lvl, y1=lvl,
            line=dict(color=THEME["sr_resist"], width=1.2, dash="dot"),
            row=1, col=1)
        fig.add_annotation(
            x=x_range[1], y=lvl, text=f"R {lvl:.2f}",
            font=dict(color=THEME["candle_dn"], size=10),
            showarrow=False, xanchor="right",
            row=1, col=1)

    # ── Entry / SL / TP lines ────────────────────────────────────────────────
    if entry_price and signal_type in ("BUY", "SELL"):
        for price, color, label in [
            (entry_price, THEME["entry_line"], f"Entry {entry_price:.4f}"),
            (stop_loss,   THEME["sl_line"],    f"SL {stop_loss:.4f}"),
            (take_profit, THEME["tp_line"],    f"TP {take_profit:.4f}"),
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
                    bgcolor=THEME["bg_panel"],
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
                            color=THEME["buy_arrow"],
                            line=dict(color="#00C853", width=1)),
                hovertemplate="BUY @ %{y:.4f}<extra></extra>",
            ), row=1, col=1)

        if sell_x:
            fig.add_trace(go.Scatter(
                x=sell_x, y=sell_y,
                mode="markers",
                name="SELL Signal",
                marker=dict(symbol="triangle-down", size=14,
                            color=THEME["sell_arrow"],
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
                    color=THEME["mkv_buy"],
                    line=dict(color=THEME["mkv_buy"], width=2),
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
                    color=THEME["mkv_sell"],
                    line=dict(color=THEME["mkv_sell"], width=2),
                ),
                hovertemplate="Markov SELL @ %{y:.4f}<extra></extra>",
            ), row=1, col=1)

    # ── ROW 2: Volume ─────────────────────────────────────────────────────────
    vol_colors = [
        THEME["vol_up"] if c >= o else THEME["vol_dn"]
        for c, o in zip(df["Close"], df["Open"])
    ]
    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"],
        name="Volume",
        marker_color=vol_colors,
        showlegend=False,
    ), row=2, col=1)

    if "vol_ma" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["vol_ma"],
            name="Vol MA",
            line=dict(color="#F59E0B", width=1.2),
            showlegend=False,
        ), row=2, col=1)

    # ── ROW 3: RSI ────────────────────────────────────────────────────────────
    if "rsi" in df.columns:
        # Overbought shading
        fig.add_hrect(y0=70, y1=100, row=3, col=1,
                      fillcolor=THEME["rsi_ob"], line_width=0)
        # Oversold shading
        fig.add_hrect(y0=0, y1=30, row=3, col=1,
                      fillcolor=THEME["rsi_os"], line_width=0)
        # RSI line
        fig.add_trace(go.Scatter(
            x=df.index, y=df["rsi"],
            name="RSI",
            line=dict(color=THEME["rsi_line"], width=1.5),
            hovertemplate="RSI: %{y:.1f}<extra></extra>",
        ), row=3, col=1)
        # Level lines
        for lvl, color in [(70, THEME["candle_dn"]), (30, THEME["candle_up"]), (50, THEME["text_dim"])]:
            fig.add_hline(y=lvl, row=3, col=1,
                          line=dict(color=color, width=0.8, dash="dot"))

    # ── ROW 4: MACD ───────────────────────────────────────────────────────────
    if all(c in df.columns for c in ["macd", "macd_signal", "macd_hist"]):
        hist_colors = [
            THEME["macd_pos"] if v >= 0 else THEME["macd_neg"]
            for v in df["macd_hist"]
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=df["macd_hist"],
            name="MACD Hist",
            marker_color=hist_colors,
            showlegend=False,
        ), row=4, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd"],
            name="MACD",
            line=dict(color=THEME["macd_line"], width=1.5),
        ), row=4, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd_signal"],
            name="Signal",
            line=dict(color=THEME["macd_signal"], width=1.2),
        ), row=4, col=1)
        fig.add_hline(y=0, row=4, col=1,
                      line=dict(color=THEME["text_dim"], width=0.8))

    # ── Global dark styling ───────────────────────────────────────────────────
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=THEME["bg"],
        plot_bgcolor =THEME["bg"],
        font=dict(family="JetBrains Mono, monospace", color=THEME["text"], size=11),
        title=dict(
            text=f"<b>{symbol}</b>",
            font=dict(size=18, color=THEME["text"]),
            x=0.01,
        ),
        legend=dict(
            orientation="h", y=1.01, x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=10),
        ),
        margin=dict(l=60, r=20, t=50, b=20),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=THEME["bg_panel"],
            bordercolor=THEME["grid"],
            font=dict(color=THEME["text"]),
        ),
        dragmode="pan",
        xaxis_rangeslider_visible=False,
        height=820,
        # uirevision: keeps zoom/pan state across Streamlit reruns.
        # Only reset when the symbol changes.
        uirevision=f"chart_{symbol}",
        transition=dict(duration=200, easing="cubic-in-out"),
    )

    # Grid styling for all axes
    axis_style = dict(
        gridcolor=THEME["grid"],
        gridwidth=0.5,
        zerolinecolor=THEME["grid"],
        showgrid=True,
        tickfont=dict(size=10, color=THEME["text_dim"]),
        linecolor=THEME["grid"],
    )

    for i in range(1, 5):
        fig.update_xaxes(
            axis_style,
            row=i, col=1,
            showticklabels=(i == 4),
            automargin=False,   # automargin causes layout recalc = jitter
            fixedrange=False,   # allow zoom/pan on x-axis
            # Smooth scrolling: don't snap to bars
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
