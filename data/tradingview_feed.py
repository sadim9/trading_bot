"""
data/tradingview_feed.py — TradingView unofficial data feed.

Uses the `tradingview_ta` library (free, no API key required) and the
`tvdatafeed` library (unofficial TradingView OHLCV history, free).

Install (already added to requirements.txt):
    pip install tradingview-ta tvdatafeed-enhanced

TradingView TA:  Real-time technical analysis summaries (oscillators, MAs)
tvdatafeed-enhanced: Historical OHLCV bars from TradingView charting engine

Symbol format examples:
  BTCUSD (Crypto)  →  exchange="BINANCE"
  AAPL (Stock)     →  exchange="NASDAQ"
  XAUUSD (Gold)    →  exchange="TVC" or "OANDA"
  EURUSD (FX)      →  exchange="OANDA"
  US30 (Index)     →  exchange="DJ"

Usage:
  from data.tradingview_feed import fetch_tradingview, get_tv_analysis
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Exchange inference map ────────────────────────────────────────────────────
# Maps common symbol patterns to their TradingView exchange
_EXCHANGE_MAP: dict[str, str] = {
    # Crypto
    "BTCUSD": "BINANCE", "ETHUSD": "BINANCE",
    "XBTUSD": "KRAKEN",  "ETHUSD_KRAKEN": "KRAKEN",
    "BTC-USD": "BINANCE", "ETH-USD": "BINANCE",
    "BTC-USDT": "BINANCE", "ETH-USDT": "BINANCE",
    "SOL-USDT": "BINANCE", "BNB-USDT": "BINANCE",
    # Commodities
    "XAUUSD": "TVC", "XAGUSD": "TVC",
    "GOLD": "TVC",   "SILVER": "TVC",
    "USOIL": "TVC",  "UKOIL": "TVC",
    # FX
    "EURUSD": "OANDA", "GBPUSD": "OANDA", "USDJPY": "OANDA",
    "AUDUSD": "OANDA", "USDCAD": "OANDA",
    # US Indices
    "SPX": "SP500",   "SPY": "AMEX",
    "QQQ": "NASDAQ",  "NDX": "NASDAQ",
    "US30": "DJ",     "DJIA": "DJ",
    # US Stocks (default NASDAQ, override if needed)
    "AAPL": "NASDAQ", "MSFT": "NASDAQ", "NVDA": "NASDAQ",
    "GOOGL": "NASDAQ","AMZN": "NASDAQ", "META": "NASDAQ",
    "TSLA": "NASDAQ", "AMD": "NASDAQ",
}

# Interval mapping: our format → tvdatafeed Interval
_TV_INTERVALS: dict[str, str] = {
    "1m":  "1",   "5m":  "5",   "15m": "15",
    "30m": "30",  "1h":  "60",  "4h":  "240",
    "1d":  "1D",  "1wk": "1W",  "1mo": "1M",
}

# Period → approximate bar count
_PERIOD_BARS: dict[str, int] = {
    "7d": 700, "30d": 720, "60d": 1440,
    "6mo": 1080, "1y": 1440, "2y": 1440,
    "5y": 1200,
}


def _infer_exchange(symbol: str) -> str:
    """Guess the best TradingView exchange for a symbol."""
    sym_upper = symbol.upper().replace("-", "").replace("_", "")
    if sym_upper in _EXCHANGE_MAP:
        return _EXCHANGE_MAP[sym_upper]
    # Heuristics
    if sym_upper.endswith("USD") and len(sym_upper) <= 9:
        return "BINANCE"  # crypto
    if sym_upper.endswith("USDT"):
        return "BINANCE"
    return "NASDAQ"  # default for stocks


def _tv_symbol(symbol: str) -> str:
    """Normalise symbol for TradingView (remove dashes, etc.)."""
    return symbol.upper().replace("-", "").replace("_", "")


def fetch_tradingview(
    symbol: str,
    interval: str = "1h",
    period: str = "60d",
    exchange: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV history from TradingView using the unofficial tvdatafeed library.

    Args:
        symbol:   Trading symbol, e.g. "BTCUSD", "AAPL", "XAUUSD"
        interval: Candle interval: "1m","5m","15m","30m","1h","4h","1d","1wk"
        period:   History period: "7d","30d","60d","6mo","1y","2y","5y"
        exchange: TradingView exchange (auto-detected if None)

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume, Symbol
        Index: DatetimeIndex (UTC)

    Raises:
        ImportError if tvdatafeed is not installed
        RuntimeError if data fetch fails
    """
    try:
        from tvDatafeed import TvDatafeed, Interval as TvInterval
    except ImportError:
        raise ImportError(
            "tvdatafeed-enhanced not installed. Run: pip install tvdatafeed-enhanced\n"
            "Note: tvdatafeed is an unofficial library. Use at your own risk."
        )

    tv_sym = _tv_symbol(symbol)
    exch   = exchange or _infer_exchange(symbol)
    n_bars = _PERIOD_BARS.get(period, 720)

    # Map interval to TvInterval enum
    tv_interval_str = _TV_INTERVALS.get(interval, "60")  # default 1h
    interval_map = {
        "1":   TvInterval.in_1_minute,
        "5":   TvInterval.in_5_minute,
        "15":  TvInterval.in_15_minute,
        "30":  TvInterval.in_30_minute,
        "60":  TvInterval.in_1_hour,
        "240": TvInterval.in_4_hour,
        "1D":  TvInterval.in_daily,
        "1W":  TvInterval.in_weekly,
        "1M":  TvInterval.in_monthly,
    }
    tv_interval = interval_map.get(tv_interval_str, TvInterval.in_1_hour)

    try:
        # Use saved credentials if available, otherwise anonymous access
        _tv_user = None
        _tv_pass = None
        try:
            import streamlit as st
            _tv_user = st.session_state.get("_tv_username") or None
            _tv_pass = st.session_state.get("_tv_password") or None
        except Exception:
            pass
        # Fall back to environment variables if not set in session
        if not _tv_user:
            import os
            _tv_user = os.getenv("TRADINGVIEW_USERNAME") or None
            _tv_pass = os.getenv("TRADINGVIEW_PASSWORD") or None

        tv = TvDatafeed(username=_tv_user, password=_tv_pass)
        raw = tv.get_hist(symbol=tv_sym, exchange=exch,
                          interval=tv_interval, n_bars=min(n_bars, 5000))
    except Exception as e:
        raise RuntimeError(f"TradingView fetch failed for {symbol} on {exch}: {e}")

    if raw is None or raw.empty:
        raise RuntimeError(f"TradingView returned no data for {symbol} on {exch}")

    # Normalise column names
    col_map = {
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    }
    raw.columns = [col_map.get(c.lower(), c) for c in raw.columns]
    raw.index   = pd.to_datetime(raw.index, utc=True)
    raw.index   = raw.index.tz_localize(None)  # strip tz for consistency
    raw.index.name = "Date"
    raw.sort_index(inplace=True)

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in raw.columns:
            raw[col] = 0.0

    raw["Symbol"] = symbol
    raw = raw[["Open", "High", "Low", "Close", "Volume", "Symbol"]].copy()
    raw.dropna(subset=["Close"], inplace=True)
    return raw


def get_tv_analysis(symbol: str, interval: str = "1h",
                    exchange: Optional[str] = None) -> dict:
    """
    Get real-time technical analysis summary from TradingView
    using the tradingview_ta library.

    Returns dict with keys:
        summary: {"RECOMMENDATION": "BUY"/"SELL"/"NEUTRAL", ...}
        oscillators: {name: {value, action}, ...}
        moving_averages: {name: {value, action}, ...}
        indicators: {name: value, ...}

    Raises ImportError if tradingview_ta is not installed.
    """
    try:
        from tradingview_ta import TA_Handler, Interval, Exchange
    except ImportError:
        raise ImportError(
            "tradingview_ta not installed. Run: pip install tradingview-ta"
        )

    tv_sym = _tv_symbol(symbol)
    exch   = exchange or _infer_exchange(symbol)

    # Map interval string to TA_Handler interval
    tv_intervals = {
        "1m": Interval.INTERVAL_1_MINUTE,
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "2h": Interval.INTERVAL_2_HOURS,
        "4h": Interval.INTERVAL_4_HOURS,
        "1d": Interval.INTERVAL_1_DAY,
        "1wk": Interval.INTERVAL_1_WEEK,
        "1mo": Interval.INTERVAL_1_MONTH,
    }
    tv_interval = tv_intervals.get(interval, Interval.INTERVAL_1_HOUR)

    # Determine screener (market category)
    sym_upper = tv_sym.upper()
    screener  = "crypto" if any(
        sym_upper.endswith(x) for x in ["USD", "USDT", "BTC", "ETH"]
    ) else "america"

    handler = TA_Handler(
        symbol=tv_sym,
        screener=screener,
        exchange=exch,
        interval=tv_interval,
    )
    try:
        analysis = handler.get_analysis()
        return {
            "summary":          analysis.summary,
            "oscillators":      analysis.oscillators,
            "moving_averages":  analysis.moving_averages,
            "indicators":       analysis.indicators,
        }
    except Exception as e:
        raise RuntimeError(f"TradingView TA analysis failed for {symbol}: {e}")
