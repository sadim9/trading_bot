"""
data/commodity_feeds.py — Free commodity price feeds
Supports two backends:
  1. yfinance  — futures symbols (GC=F, SI=F, CL=F, BZ=F). No key required.
  2. Twelve Data — spot forex-pair style (XAU/USD). Free key at twelvedata.com.

Usage:
    from data.commodity_feeds import (
        COMMODITY_SYMBOLS, COMMODITY_YFINANCE_MAP,
        fetch_twelvedata, get_commodity_yf,
        clear_commodity_cache,
    )
"""

from __future__ import annotations

import time
import threading
import requests
import pandas as pd
import yfinance as yf
from typing import Optional

# ── Symbol catalogue ──────────────────────────────────────────────────────────
# Each entry: display_name → {yf: yfinance futures symbol, td: Twelve Data symbol,
#                              label: short label, category: metals|energy}
COMMODITY_SYMBOLS: dict[str, dict] = {
    "XAUUSD": {
        "yf":       "GC=F",
        "td":       "XAU/USD",
        "label":    "Gold",
        "category": "metals",
        "icon":     "🥇",
        "desc":     "Spot Gold / US Dollar",
    },
    "XAGUSD": {
        "yf":       "SI=F",
        "td":       "XAG/USD",
        "label":    "Silver",
        "category": "metals",
        "icon":     "🥈",
        "desc":     "Spot Silver / US Dollar",
    },
    "USOIL": {
        "yf":       "CL=F",
        "td":       "WTI/USD",
        "label":    "WTI Oil",
        "category": "energy",
        "icon":     "🛢️",
        "desc":     "WTI Crude Oil (NYMEX)",
    },
    "UKOIL": {
        "yf":       "BZ=F",
        "td":       "BRENT/USD",
        "label":    "Brent",
        "category": "energy",
        "icon":     "⛽",
        "desc":     "Brent Crude Oil (ICE)",
    },
    "XPTUSD": {
        "yf":       "PL=F",
        "td":       "XPT/USD",
        "label":    "Platinum",
        "category": "metals",
        "icon":     "💿",
        "desc":     "Spot Platinum / US Dollar",
    },
    "NGAS": {
        "yf":       "NG=F",
        "td":       "NATGAS/USD",
        "label":    "Nat Gas",
        "category": "energy",
        "icon":     "🔥",
        "desc":     "Natural Gas (Henry Hub)",
    },
}

# Quick reverse-lookup: yf ticker → canonical name
YFINANCE_TO_CANONICAL: dict[str, str] = {
    v["yf"]: k for k, v in COMMODITY_SYMBOLS.items()
}

# Flat map used by ingestion.py to normalise user-typed symbols for yfinance
COMMODITY_YFINANCE_MAP: dict[str, str] = {
    k: v["yf"] for k, v in COMMODITY_SYMBOLS.items()
}
# Also accept lowercase and common aliases
_extra_aliases = {
    "GOLD": "GC=F", "SILVER": "SI=F",
    "WTI": "CL=F",  "WTIUSD": "CL=F",
    "BRENT": "BZ=F","BRENTUSD": "BZ=F",
    "OIL": "CL=F",  "NATGAS": "NG=F",
    "PLATINUM": "PL=F", "PALLADIUM": "PA=F",
    "XPDUSD": "PA=F",
    # Lower-case variants
    "xauusd": "GC=F", "xagusd": "SI=F",
    "usoil":  "CL=F", "ukoil":  "BZ=F",
}
COMMODITY_YFINANCE_MAP.update(_extra_aliases)


# ── In-memory cache ───────────────────────────────────────────────────────────
_CACHE: dict[str, tuple] = {}   # key → (df, timestamp)
_LOCK  = threading.Lock()

_INTERVAL_TTL = {
    "1min": 30, "5min": 60, "15min": 90,
    "30min": 120, "1h": 180, "4h": 300, "1day": 600,
}


def clear_commodity_cache() -> None:
    """Flush the commodity data cache (call after source/symbol change)."""
    with _LOCK:
        _CACHE.clear()


# ── Twelve Data helper ────────────────────────────────────────────────────────
_TD_BASE = "https://api.twelvedata.com"

# Map our internal interval codes → Twelve Data interval strings
_TD_INTERVAL_MAP = {
    "1m":  "1min",  "5m":  "5min",  "15m": "15min",
    "30m": "30min", "1h":  "1h",    "4h":  "4h",
    "1d":  "1day",  "1wk": "1week",
}

# Map period strings → approximate outputsize (number of candles)
_PERIOD_OUTPUTSIZE = {
    "7d":  200,  "30d": 500,  "60d": 700,
    "6mo": 1000, "1y":  1000, "2y":  1000, "5y": 1000,
}


def fetch_twelvedata(
    symbol:     str,
    interval:   str = "1h",
    period:     str = "6mo",
    api_key:    str = "",
) -> pd.DataFrame:
    """
    Fetch OHLCV data from Twelve Data free REST API.

    Parameters
    ----------
    symbol   : Twelve Data symbol, e.g. "XAU/USD", "XAG/USD", "WTI/USD"
    interval : internal interval code ("1m","5m","1h","1d", …)
    period   : lookback period string ("7d","30d","6mo","1y","2y")
    api_key  : Twelve Data API key (free at twelvedata.com)

    Returns
    -------
    DataFrame with columns: Open, High, Low, Close, Volume
    Index: DatetimeIndex (UTC-aware)

    Raises
    ------
    ValueError  – API error or missing key
    requests.HTTPError – network / HTTP failure
    """
    if not api_key:
        raise ValueError(
            "Twelve Data API key is required.\n"
            "Get a free key at https://twelvedata.com/pricing (800 credits/day)."
        )

    td_interval  = _TD_INTERVAL_MAP.get(interval, "1h")
    outputsize   = min(_PERIOD_OUTPUTSIZE.get(period, 500), 5000)
    cache_key    = f"td_{symbol}_{td_interval}_{outputsize}"

    with _LOCK:
        if cache_key in _CACHE:
            df_c, ts = _CACHE[cache_key]
            ttl = _INTERVAL_TTL.get(td_interval, 180)
            if time.time() - ts < ttl:
                return df_c

    url    = f"{_TD_BASE}/time_series"
    params = {
        "symbol":     symbol,
        "interval":   td_interval,
        "outputsize": outputsize,
        "apikey":     api_key,
        "order":      "ASC",
        "timezone":   "UTC",
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "error":
        code = data.get("code", "")
        msg  = data.get("message", str(data))
        if code == 400:
            raise ValueError(f"Twelve Data: symbol '{symbol}' not found — {msg}")
        if code == 429:
            raise ValueError("Twelve Data: rate limit reached (800 credits/day on free plan)")
        raise ValueError(f"Twelve Data API error {code}: {msg}")

    values = data.get("values", [])
    if not values:
        raise ValueError(f"Twelve Data returned no data for {symbol}/{td_interval}")

    df = pd.DataFrame(values)
    df.index = pd.to_datetime(df["datetime"], utc=True)
    df.index.name = "Datetime"
    df = df.rename(columns={
        "open":   "Open",
        "high":   "High",
        "low":    "Low",
        "close":  "Close",
        "volume": "Volume",
    })
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    df.sort_index(inplace=True)

    with _LOCK:
        _CACHE[cache_key] = (df, time.time())

    return df


# ── yfinance commodity helper ─────────────────────────────────────────────────

def get_commodity_yf(
    symbol:   str,
    interval: str = "1h",
    period:   str = "6mo",
) -> pd.DataFrame:
    """
    Fetch commodity OHLCV via yfinance, accepting both canonical names
    (XAUUSD, USOIL …) and raw yfinance futures tickers (GC=F, CL=F …).

    Returns a normalised DataFrame identical to other yfinance loads so
    existing indicator code works unchanged.
    """
    # Resolve to yfinance ticker
    yf_sym = COMMODITY_YFINANCE_MAP.get(symbol.upper(), symbol)
    # If it's already a yf futures ticker, pass it through
    cache_key = f"yf_{yf_sym}_{interval}_{period}"
    with _LOCK:
        if cache_key in _CACHE:
            df_c, ts = _CACHE[cache_key]
            ttl = _INTERVAL_TTL.get(interval, 180)
            if time.time() - ts < ttl:
                return df_c

    # yfinance period/interval compatibility
    _yf_period = period
    # For short intervals yfinance caps history:
    # 1m → max 7d, 5m/15m → max 60d, 1h → max 730d
    _cap = {"1m": "7d", "5m": "60d", "15m": "60d"}
    if interval in _cap and _yf_period not in ("7d", "30d", "60d"):
        _yf_period = _cap[interval]

    ticker = yf.Ticker(yf_sym)
    df = ticker.history(period=_yf_period, interval=interval, auto_adjust=True)

    if df is None or df.empty:
        raise ValueError(f"yfinance returned no data for {yf_sym} ({symbol})")

    # Normalise columns
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index, utc=True)
    df.sort_index(inplace=True)
    df.dropna(subset=["Close"], inplace=True)

    with _LOCK:
        _CACHE[cache_key] = (df, time.time())

    return df


# ── Convenience: get last price for the quick-picker strip ────────────────────

def get_commodity_last_price(symbol: str, source: str = "yfinance", api_key: str = "") -> Optional[dict]:
    """
    Return {"price": float, "change_pct": float, "label": str} for the strip.
    Falls back gracefully on error.
    """
    try:
        meta = COMMODITY_SYMBOLS.get(symbol.upper(), {})
        if source == "twelvedata" and api_key:
            td_sym = meta.get("td", symbol)
            df = fetch_twelvedata(td_sym, interval="1h", period="7d", api_key=api_key)
        else:
            df = get_commodity_yf(symbol, interval="1h", period="5d")

        if df is None or len(df) < 2:
            return None

        price  = float(df["Close"].iloc[-1])
        prev   = float(df["Close"].iloc[-2])
        change = (price / prev - 1) * 100 if prev else 0.0
        return {
            "price":      price,
            "change_pct": change,
            "label":      meta.get("label", symbol),
            "icon":       meta.get("icon",  "◆"),
            "desc":       meta.get("desc",  ""),
        }
    except Exception:
        return None
