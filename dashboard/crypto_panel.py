"""
dashboard/crypto_panel.py — Crypto Market Data Panel for Streamlit

Renders:
  - Exchange selector (Binance / CoinGecko / yfinance)
  - Crypto symbol picker with popular coins
  - Live 24h stats ticker (price, % change, high, low, volume)
  - Auto-refresh controls specific to crypto
  - Quick-switch buttons for top coins

Called from app.py above the main chart area when source is crypto.
"""

from __future__ import annotations
import streamlit as st
import pandas as pd
from typing import Optional


# Organised by category for the UI picker
CRYPTO_CATEGORIES = {
    "Major (USDT)": [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "MATICUSDT",
        "LINKUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "XLMUSDT",
    ],
    "AED Pairs (BitOasis)": [
        "BTC-AED", "ETH-AED", "XRP-AED", "LTC-AED",
    ],
    "USD Pairs (yfinance)": [
        "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    ],
}

# Source → display name + tooltip
CRYPTO_SOURCES = {
    "binance":   ("Binance",   "Real-time OHLCV from Binance. No API key needed. Best for USDT pairs."),
    "coingecko": ("CoinGecko", "Free fallback. Daily bars only. Wider coin coverage."),
    "yfinance":  ("Yahoo Finance", "Yahoo Finance crypto. Use BTC-USD format."),
}

THEME = dict(
    bg      = "#131722",
    panel   = "#1E222D",
    border  = "#2A2E39",
    text    = "#D1D4DC",
    dim     = "#787B86",
    green   = "#26A69A",
    red     = "#EF5350",
    orange  = "#F7931A",
    blue    = "#2196F3",
)


def _stat_card(label: str, value: str, delta: str = "", color: str = "#D1D4DC"):
    """Render a compact stat card."""
    st.markdown(
        f"""<div style="background:{THEME['panel']};border:1px solid {THEME['border']};
                border-radius:6px;padding:10px 14px;text-align:center">
              <div style="color:{THEME['dim']};font-size:10px;margin-bottom:2px">{label}</div>
              <div style="color:{color};font-size:16px;font-weight:700;font-family:monospace">{value}</div>
              {"<div style='color:"+color+";font-size:11px'>"+delta+"</div>" if delta else ""}
            </div>""",
        unsafe_allow_html=True,
    )


def render_crypto_selector() -> tuple[str, str, str, int]:
    """
    Render the crypto exchange + symbol selector.
    Returns (symbol, source, interval, limit).
    """
    st.markdown(
        f"<div style='background:{THEME['panel']};border:1px solid {THEME['border']};"
        f"border-radius:8px;padding:12px 16px;margin-bottom:12px'>",
        unsafe_allow_html=True,
    )
    st.markdown("**🪙 Crypto Market Data**", unsafe_allow_html=False)

    # Source selector
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    source_label = c1.selectbox(
        "Exchange",
        list(CRYPTO_SOURCES.keys()),
        format_func=lambda k: CRYPTO_SOURCES[k][0],
        key="crypto_source",
        help="\n".join(f"{CRYPTO_SOURCES[k][0]}: {CRYPTO_SOURCES[k][1]}" for k in CRYPTO_SOURCES),
    )

    # Symbol — show relevant options per source
    if source_label == "binance":
        category = c2.selectbox("Category", list(CRYPTO_CATEGORIES.keys()), key="crypto_cat")
        all_syms  = CRYPTO_CATEGORIES[category]
    elif source_label == "coingecko":
        all_syms  = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple",
                     "cardano", "dogecoin", "avalanche-2", "polkadot", "litecoin"]
        c2.caption("Use CoinGecko coin IDs")
    else:
        all_syms  = CRYPTO_CATEGORIES["USD Pairs (yfinance)"]

    symbol = c2.selectbox("Symbol", all_syms, key="crypto_sym") if source_label != "coingecko" else \
             c2.selectbox("Coin ID", all_syms, key="crypto_sym_cg")

    # Or type a custom symbol
    custom = c3.text_input("Custom", placeholder="e.g. APEUSDT", key="crypto_custom")
    if custom.strip():
        symbol = custom.strip().upper()

    # Interval
    if source_label == "binance":
        ivl_opts = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    elif source_label == "coingecko":
        ivl_opts = ["1d"]      # CoinGecko free tier = daily only
    else:
        ivl_opts = ["1m", "5m", "15m", "1h", "1d", "1wk"]

    interval = c4.selectbox("Interval", ivl_opts, index=ivl_opts.index("1h") if "1h" in ivl_opts else 0,
                             key="crypto_ivl")

    # Bar limit
    limit = 500
    if source_label == "binance":
        limit = st.slider("Bars to load", 50, 1000, 500, 50, key="crypto_limit",
                          help="Binance max = 1000 bars per request")

    st.markdown("</div>", unsafe_allow_html=True)
    return symbol, source_label, interval, limit


def render_24h_ticker(symbol: str, source: str):
    """
    Show live 24-hour stats above the chart.
    Only available from Binance (free public endpoint).
    """
    if source != "binance":
        return

    try:
        from data.crypto_feeds import get_binance_24h, _validate_symbol
        sym   = _validate_symbol(symbol.replace("-", "").replace("USD", "USDT"))
        stats = get_binance_24h(sym)
        if not stats:
            return

        price     = stats.get("price", 0)
        chg_pct   = stats.get("change_pct", 0)
        high_24h  = stats.get("high_24h", 0)
        low_24h   = stats.get("low_24h", 0)
        vol_24h   = stats.get("volume_24h", 0)
        trades    = stats.get("trades_24h", 0)

        chg_color = THEME["green"] if chg_pct >= 0 else THEME["red"]
        chg_arrow = "▲" if chg_pct >= 0 else "▼"
        vol_str   = f"${vol_24h/1e9:.2f}B" if vol_24h > 1e9 else f"${vol_24h/1e6:.1f}M"

        cols = st.columns(6)
        with cols[0]: _stat_card("Last Price",    f"${price:,.4f}", f"{chg_arrow} {abs(chg_pct):.2f}%", chg_color)
        with cols[1]: _stat_card("24h Change",    f"{chg_pct:+.2f}%", color=chg_color)
        with cols[2]: _stat_card("24h High",      f"${high_24h:,.4f}", color=THEME["green"])
        with cols[3]: _stat_card("24h Low",       f"${low_24h:,.4f}",  color=THEME["red"])
        with cols[4]: _stat_card("24h Volume",    vol_str,             color=THEME["blue"])
        with cols[5]: _stat_card("24h Trades",    f"{trades:,}",       color=THEME["dim"])

        st.markdown(
            f"<div style='color:{THEME['dim']};font-size:10px;text-align:right;margin-top:-6px'>"
            f"Live · Binance · {sym}</div>",
            unsafe_allow_html=True,
        )
    except Exception:
        pass   # silently skip if Binance unreachable


def render_quick_switch(current_symbol: str) -> Optional[str]:
    """
    Quick-switch buttons for top coins.
    Returns new symbol if user clicked a button, else None.
    """
    st.markdown(
        "<div style='margin-bottom:6px'>"
        "<span style='color:#787B86;font-size:11px'>Quick switch → </span></div>",
        unsafe_allow_html=True,
    )
    quick_coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]
    cols = st.columns(len(quick_coins))
    for i, coin in enumerate(quick_coins):
        label = coin.replace("USDT", "")
        active = current_symbol.upper().replace("-", "").replace("USDT", "") == label
        style  = "primary" if active else "secondary"
        if cols[i].button(label, type=style, use_container_width=True, key=f"qs_{coin}"):
            return coin
    return None
