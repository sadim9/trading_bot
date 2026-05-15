"""
data/ingestion.py — Market data ingestion layer.

Sources: Yahoo Finance | BitOasis | Binance | CoinGecko | CSV | Synthetic sample

Critical design decisions:
  • yfinance: uses explicit start/end DATES (not period=) to force fresh data.
    period= returns Yahoo's cached snapshots which can be 10+ days stale.
    end = tomorrow's date ensures today's intraday bars are fully included.
  • Module-level _CACHE: keyed by (symbol, interval, start_date, source).
    TTL is enforced by the dashboard layer, not here.
  • add_technical_indicators: uses ffill/bfill on rolling-window columns so
    the minimum viable bar count is ~30 (not 220 as with raw dropna).
"""

import os
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False


# ── In-memory cache ────────────────────────────────────────────────────────────
_CACHE: Dict[str, pd.DataFrame] = {}

# ── Timezone conversion ────────────────────────────────────────────────────────
def convert_to_local_time(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a UTC DatetimeIndex to the system's local timezone.
    This makes chart x-axis labels show local time (e.g. Qatar UTC+3)
    instead of UTC — fixing the "data appears 3h behind" issue.

    All crypto APIs (Kraken, KuCoin, Binance, BitOasis) return UTC timestamps.
    Python's datetime.now().astimezone().utcoffset() detects the system offset.
    On a Qatar machine this is +03:00, so 13:00 UTC becomes 16:00 local.
    """
    if df.empty:
        return df
    try:
        local_offset = datetime.now(timezone.utc).astimezone().utcoffset()
        if local_offset and local_offset.total_seconds() != 0:
            df = df.copy()
            df.index = df.index + local_offset
            df.index.name = "Date (Local)"
    except Exception:
        pass  # silently keep UTC if conversion fails
    return df


def _cache_key(symbol: str, interval: str, start: str) -> str:
    return f"{symbol}_{interval}_{start}"


def clear_ingestion_cache():
    """Force-clear the module-level cache so next call fetches live data."""
    _CACHE.clear()


# ── Timezone helper ────────────────────────────────────────────────────────────
def _strip_tz(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if hasattr(index, "tz") and index.tz is not None:
        return index.tz_convert(None)
    return index


# ── Column normaliser ──────────────────────────────────────────────────────────
def _normalise_df(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
    df.columns = [str(c).strip().title() for c in df.columns]
    if "Close" not in df.columns and "Adj Close" in df.columns:
        df = df.rename(columns={"Adj Close": "Close"})
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing  = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Available: {list(df.columns)}")
    df = df[required].copy()
    df.index = pd.to_datetime(df.index)
    df.index = _strip_tz(df.index)
    df.index.name = "Date"
    df.sort_index(inplace=True)
    df.dropna(inplace=True)
    df["Symbol"] = symbol
    return df


# ── Interval → max lookback (days) for Yahoo Finance ──────────────────────────
INTERVAL_MAX_DAYS = {
    "1m": 7,  "2m": 60, "5m": 60, "15m": 60, "30m": 60,
    "60m": 730, "90m": 60, "1h": 730, "1d": 3650,
    "5d": 3650, "1wk": 3650, "1mo": 3650, "3mo": 3650,
}

PERIOD_DAYS = {
    "1d": 1, "5d": 5, "7d": 7, "30d": 30, "60d": 60,
    "1mo": 30, "2mo": 60, "3mo": 90, "6mo": 180,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
    "ytd": 365, "max": 3650,
}


def fetch_yahoo(symbol: str, interval: str = "1d", period: str = "2y") -> pd.DataFrame:
    """
    Download OHLCV from Yahoo Finance using explicit start/end dates.

    Using start= / end= instead of period= forces Yahoo to return genuinely
    fresh bars up to the current moment. period= uses a server-side snapshot
    cache that can be 10+ days stale.

    end is set to tomorrow to ensure today's bars are fully included.
    """
    if not YF_AVAILABLE:
        raise ImportError("yfinance not installed. Run: pip install yfinance")

    # Compute start date from period string
    lookback_days = PERIOD_DAYS.get(period, 730)
    max_days      = INTERVAL_MAX_DAYS.get(interval, lookback_days)
    lookback_days = min(lookback_days, max_days)

    now       = datetime.now(timezone.utc)
    start_dt  = now - timedelta(days=lookback_days)
    # end = tomorrow so today's incomplete bar is always included
    end_dt    = now + timedelta(days=1)

    start_str = start_dt.strftime("%Y-%m-%d")
    end_str   = end_dt.strftime("%Y-%m-%d")

    key = _cache_key(symbol, interval, start_str)
    if key in _CACHE:
        return _CACHE[key].copy()

    df         = pd.DataFrame()
    last_error = ""

    # Method 1: yf.download — most reliable in yfinance 0.2.x
    try:
        raw = yf.download(
            tickers=symbol,
            start=start_str,
            end=end_str,
            interval=interval,
            auto_adjust=True,
            progress=False,
            show_errors=False,
        )
        if not raw.empty:
            df = _normalise_df(raw, symbol)
    except Exception as e:
        last_error = str(e)

    # Method 2: Ticker.history fallback
    if df.empty:
        try:
            raw = yf.Ticker(symbol).history(
                start=start_str,
                end=end_str,
                interval=interval,
                auto_adjust=True,
                actions=False,
            )
            if not raw.empty:
                df = _normalise_df(raw, symbol)
            else:
                last_error += " | ticker.history empty"
        except Exception as e:
            last_error += f" | {e}"

    if df.empty:
        raise ValueError(
            f"No data from Yahoo Finance for '{symbol}' "
            f"(interval={interval}, {start_str} → {end_str}).\n"
            f"Check: symbol correct? Internet working? {last_error}"
        )

    if len(df) < 5:
        raise ValueError(
            f"Only {len(df)} bars returned for '{symbol}'. "
            f"Try a longer period or daily interval."
        )

    _CACHE[key] = df
    return df.copy()


def fetch_csv(filepath: str, symbol: str = "CUSTOM") -> pd.DataFrame:
    """
    Load OHLCV data from a local CSV file.

    Security: the filepath is validated to prevent path traversal attacks.
    Only files with a .csv extension are accepted.
    """
    import os
    # Normalise and resolve the path
    abs_path = os.path.realpath(os.path.abspath(filepath))
    # Only allow .csv files
    if not abs_path.lower().endswith(".csv"):
        raise ValueError(f"Only .csv files are allowed, got: {filepath!r}")
    # Prevent directory traversal: reject if path contains null bytes
    if "\x00" in filepath:
        raise ValueError("Null byte in filepath is not allowed")
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"CSV file not found: {abs_path}")

    df = pd.read_csv(abs_path, index_col=0)
    df.columns = [c.strip().title() for c in df.columns]
    df.index   = pd.to_datetime(df.index)
    df.index   = _strip_tz(df.index)
    return _normalise_df(df, symbol)


def generate_sample_data(
    symbol: str = "SAMPLE",
    n_days: int = 750,
    seed: int = 42,
) -> pd.DataFrame:
    """Geometric Brownian Motion synthetic OHLCV — works fully offline."""
    np.random.seed(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n_days)
    n     = len(dates)   # use actual count — bdate_range may differ from n_days

    mu, sigma = 0.0003, 0.015
    price  = 100.0
    closes = [price]
    for _ in range(n - 1):
        price = max(price * (1 + np.random.normal(mu, sigma)), 0.01)
        closes.append(price)
    closes  = np.array(closes)
    highs   = closes * (1 + np.abs(np.random.normal(0, 0.005, n)))
    lows    = closes * (1 - np.abs(np.random.normal(0, 0.005, n)))
    opens   = np.concatenate([[closes[0]], closes[:-1]])
    volumes = np.random.lognormal(mean=13, sigma=0.5, size=n).astype(int)
    df = pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows,
         "Close": closes, "Volume": volumes, "Symbol": symbol},
        index=dates,
    )
    df.index.name = "Date"
    return df


def add_technical_indicators(df: pd.DataFrame, cfg=None) -> pd.DataFrame:
    """
    Compute all technical indicators. Uses ffill/bfill on rolling-window
    columns so minimum viable bar count is ~30 (not 220).
    """
    from config import CONFIG
    c  = cfg or CONFIG.strategy
    df = df.copy()

    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    vol   = df["Volume"]

    # ── Trend ──────────────────────────────────────────────────────────────────
    df["ema_fast"]   = close.ewm(span=c.ema_fast,    adjust=False).mean()
    df["ema_slow"]   = close.ewm(span=c.ema_slow,    adjust=False).mean()
    df["ema_cross"]  = (df["ema_fast"] > df["ema_slow"]).astype(int)
    ema_mf           = close.ewm(span=c.macd_fast,   adjust=False).mean()
    ema_ms           = close.ewm(span=c.macd_slow,   adjust=False).mean()
    df["macd"]       = ema_mf - ema_ms
    df["macd_signal"]= df["macd"].ewm(span=c.macd_signal, adjust=False).mean()
    df["macd_hist"]  = df["macd"] - df["macd_signal"]

    # ── Mean Reversion ─────────────────────────────────────────────────────────
    delta     = close.diff()
    avg_gain  = delta.clip(lower=0).ewm(com=c.rsi_period-1, adjust=False).mean()
    avg_loss  = (-delta.clip(upper=0)).ewm(com=c.rsi_period-1, adjust=False).mean()
    rs        = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    df["bb_mid"]   = close.rolling(c.bb_period).mean()
    bb_std         = close.rolling(c.bb_period).std()
    df["bb_upper"] = df["bb_mid"] + c.bb_std * bb_std
    df["bb_lower"] = df["bb_mid"] - c.bb_std * bb_std
    denom          = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
    df["bb_pct"]   = (close - df["bb_lower"]) / denom

    # ── Momentum ───────────────────────────────────────────────────────────────
    df["roll_high"]   = high.rolling(c.breakout_lookback).max()
    df["roll_low"]    = low.rolling(c.breakout_lookback).min()
    df["breakout_up"] = (close > df["roll_high"].shift(1)).astype(int)
    df["breakout_dn"] = (close < df["roll_low"].shift(1)).astype(int)
    df["vol_ma"]      = vol.rolling(20).mean()
    df["vol_ratio"]   = vol / df["vol_ma"].replace(0, np.nan)

    tr  = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    # ── AI features ────────────────────────────────────────────────────────────
    df["returns_1d"]        = close.pct_change(1)
    df["returns_5d"]        = close.pct_change(5)
    df["returns_20d"]       = close.pct_change(20)
    df["volatility"]        = df["returns_1d"].rolling(20).std()
    df["price_vs_ema_fast"] = close / df["ema_fast"] - 1
    df["price_vs_ema_slow"] = close / df["ema_slow"] - 1

    # ── Smart warmup: ffill rolling-window NaN before final dropna ─────────────
    # EWM columns (ema, macd, rsi) produce values from bar 1 — no NaN.
    # Rolling columns produce NaN for first window-size rows.
    # ffill/bfill from first valid value → minimum 30 bars instead of 220.
    rolling_cols = [
        "bb_mid", "bb_upper", "bb_lower", "bb_pct",
        "roll_high", "roll_low", "vol_ma", "vol_ratio", "atr",
        "returns_5d", "returns_20d", "volatility",
        "price_vs_ema_fast", "price_vs_ema_slow",
    ]
    for col in rolling_cols:
        if col in df.columns:
            df[col] = df[col].ffill().bfill()

    df.dropna(inplace=True)
    return df


# ── Period → candle count helper ──────────────────────────────────────────────
_INTERVAL_MINUTES: dict = {
    "1m": 1, "2m": 2, "3m": 3, "5m": 5, "10m": 10, "15m": 15,
    "30m": 30, "45m": 45, "1h": 60, "2h": 120, "4h": 240, "6h": 360,
    "8h": 480, "12h": 720, "1d": 1440, "3d": 4320, "1wk": 10080,
    "60m": 60, "90m": 90,
}

def _period_to_candles(period: str, interval: str) -> int:
    """
    Convert a period string (e.g. "6mo") and interval (e.g. "1h") into the
    number of candles needed to cover that period.

    Used to request the correct `limit` from Kraken / KuCoin / Binance APIs
    which take a count rather than a date range.
    """
    days = PERIOD_DAYS.get(period, 730)
    mins = _INTERVAL_MINUTES.get(interval, 60)
    candles = int((days * 1440) / max(mins, 1))
    # Add 10% buffer for weekends / missing bars
    return int(candles * 1.1)


def load_data(
    symbol: str,
    interval: str = "1d",
    period: str = "2y",
    source: str = "yfinance",
    csv_path: Optional[str] = None,
    crypto_limit: int = 1000,
    twelvedata_api_key: str = "",
) -> pd.DataFrame:
    """
    Unified entry point: fetch raw OHLCV → add all indicators.

    Sources: "kraken" | "kucoin" | "yfinance" | "bitoasis" | "binance" |
             "coingecko" | "twelvedata" | "tradingview" | "csv" | "sample"

    Commodity symbols (XAUUSD, XAGUSD, USOIL, UKOIL, …) are automatically
    normalised to the correct yfinance futures ticker (GC=F, SI=F, CL=F, BZ=F)
    when source == "yfinance".

    For crypto sources that take a `limit` count, the limit is derived from
    the requested `period` + `interval` so the chart respects the selected range.
    """
    # Compute period-aware limit for crypto APIs
    period_limit = _period_to_candles(period, interval)
    effective_limit = max(crypto_limit, period_limit)

    if source == "kraken":
        from data.crypto_feeds import fetch_kraken
        raw = fetch_kraken(symbol, interval=interval, limit=min(effective_limit, 720))

    elif source == "kucoin":
        from data.crypto_feeds import fetch_kucoin
        raw = fetch_kucoin(symbol, interval=interval, limit=min(effective_limit, 1500))

    elif source == "bitoasis":
        from data.crypto_feeds import fetch_bitoasis_ohlcv
        raw = fetch_bitoasis_ohlcv(
            symbol=symbol, interval=interval,
            limit=max(crypto_limit, 1000),
            api_key=os.getenv("BITOASIS_API_KEY", ""),
            api_secret=os.getenv("BITOASIS_API_SECRET", ""),
        )

    elif source == "binance":
        from data.crypto_feeds import load_crypto
        _, raw = None, None
        raw, _ = load_crypto(symbol, interval=interval, limit=max(crypto_limit, 1000))

    elif source == "coingecko":
        from data.crypto_feeds import fetch_coingecko
        raw = fetch_coingecko(symbol, interval=interval)

    elif source == "yfinance":
        # Commodity symbol normalisation:
        # Map canonical commodity names (XAUUSD, USOIL, etc.) to yfinance futures
        # tickers (GC=F, CL=F, etc.) transparently. Non-commodity symbols pass through.
        from data.commodity_feeds import COMMODITY_YFINANCE_MAP
        yf_symbol = COMMODITY_YFINANCE_MAP.get(symbol.upper(), symbol)
        raw = fetch_yahoo(yf_symbol, interval, period)

    elif source == "twelvedata":
        # Twelve Data REST API (free tier: 800 credits/day).
        # Resolves canonical commodity names to Twelve Data symbols (XAU/USD, WTI/USD, etc.)
        from data.commodity_feeds import COMMODITY_SYMBOLS, fetch_twelvedata
        key = twelvedata_api_key
        if not key:
            # Try CONFIG singleton as fallback
            try:
                from config import CONFIG as _cfg
                key = _cfg.data.twelvedata_api_key
            except Exception:
                pass
        meta   = COMMODITY_SYMBOLS.get(symbol.upper(), {})
        td_sym = meta.get("td", symbol)   # e.g. "XAU/USD"
        raw    = fetch_twelvedata(td_sym, interval=interval, period=period, api_key=key)
        # _normalise_df strips timezone info and ensures correct column names
        raw    = _normalise_df(raw, symbol)

    elif source == "tradingview":
        from data.tradingview_feed import fetch_tradingview
        raw = fetch_tradingview(symbol, interval=interval, period=period)

    elif source == "csv":
        if not csv_path:
            raise ValueError("csv_path required when source='csv'")
        raw = fetch_csv(csv_path, symbol)

    else:
        raw = generate_sample_data(symbol)

    df_with_indicators = add_technical_indicators(raw)
    return convert_to_local_time(df_with_indicators)
