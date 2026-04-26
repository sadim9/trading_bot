"""
data/crypto_feeds.py — Crypto Market Data Feeds

Priority order for Sadi (Doha, Qatar):
  1. BitOasis  — user's own exchange, AED-denominated, needs API credentials
  2. yfinance  — Yahoo Finance BTC-USD, accessible everywhere, 15-min delay
  3. CoinGecko — daily bars only, wide coverage, free, no auth
  4. Binance   — blocked in Qatar without VPN

BitOasis OHLCV endpoint:
  BitOasis is built on the Huobi/HTX infrastructure.
  Public market data: api.bitoasis.net/v1/market/history/kline
  Authenticated: api.bitoasis.net/v3/...

Symbol format:
  BitOasis: "btcaed", "ethaed"  (lowercase, no separator)
  yfinance: "BTC-USD", "ETH-USD"
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

# ── Cache ──────────────────────────────────────────────────────────────────────
_CRYPTO_CACHE: Dict[str, Tuple[pd.DataFrame, float]] = {}
CACHE_TTL = 30   # seconds

# ── Symbol catalogs ────────────────────────────────────────────────────────────
POPULAR_CRYPTO = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "BTC-AED", "ETH-AED", "XRP-AED", "LTC-AED",
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
]

BITOASIS_AED_PAIRS = {
    "BTC-AED":"btcaed", "ETH-AED":"ethaed", "XRP-AED":"xrpaed",
    "LTC-AED":"ltcaed", "SOL-AED":"solaed", "BNB-AED":"bnbaed",
    "ADA-AED":"adaaed", "DOGE-AED":"dogeaed",
}

# BitOasis/Huobi interval codes
BITOASIS_INTERVAL_MAP = {
    "1m":"1min", "5m":"5min", "15m":"15min", "30m":"30min",
    "1h":"60min", "4h":"4hour", "1d":"1day", "1wk":"1week",
}

BINANCE_INTERVAL_MAP = {
    "1m":"1m", "5m":"5m", "15m":"15m", "30m":"30m",
    "1h":"1h", "4h":"4h", "1d":"1d", "1wk":"1w",
}

COINGECKO_IDS = {
    "BTC":"bitcoin","ETH":"ethereum","SOL":"solana","BNB":"binancecoin",
    "XRP":"ripple","ADA":"cardano","DOGE":"dogecoin","AVAX":"avalanche-2",
    "DOT":"polkadot","LTC":"litecoin","MATIC":"matic-network",
}


# ── Validation ─────────────────────────────────────────────────────────────────
def _validate_symbol(symbol: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9\-]", "", symbol).upper()
    if not clean:
        raise ValueError(f"Invalid crypto symbol: {symbol!r}")
    return clean


def _symbol_to_bitoasis(symbol: str) -> str:
    """Convert any symbol format to BitOasis kline symbol (lowercase, no sep)."""
    sym = _validate_symbol(symbol)
    if sym in BITOASIS_AED_PAIRS:
        return BITOASIS_AED_PAIRS[sym]
    # Strip quote currency suffix and any separators to get base asset
    for suffix in ("USDT", "BUSD", "USD", "AED"):
        if sym.endswith(suffix) and len(sym) > len(suffix):
            base = sym[:-len(suffix)].rstrip("-").rstrip("_")
            return (base + "AED").lower()
    # Already in BitOasis format or unknown — strip separators
    return sym.lower().replace("-", "").replace("_", "")


def _symbol_to_coingecko_id(symbol: str) -> str:
    base = symbol.upper()
    for suffix in ["USDT","USD","AED","BUSD","BTC","ETH"]:
        if base.endswith(suffix) and base != suffix:
            base = base[:-len(suffix)].rstrip("-")
            break
    return COINGECKO_IDS.get(base, base.lower())


# ══════════════════════════════════════════════════════════════════════════════
#  BITOASIS MARKET DATA
# ══════════════════════════════════════════════════════════════════════════════
BITOASIS_MARKET_BASE = "https://api.bitoasis.net/v1"
BITOASIS_API_BASE    = "https://api.bitoasis.net/v3"


def fetch_bitoasis_ohlcv(
    symbol: str,
    interval: str = "1h",
    limit: int = 1000,
    api_key: str = "",
    api_secret: str = "",
) -> pd.DataFrame:
    """
    Fetch OHLCV kline data from BitOasis.

    Tries the public market data endpoint first (no auth needed).
    Falls back to authenticated API if credentials are provided and
    the public endpoint returns no data.

    Returns AED-denominated OHLCV data directly from the user's exchange.

    Args:
        symbol:     "BTC-AED", "ETH-AED", "BTCUSDT", "BTC-USD" — any format
        interval:   "1m","5m","15m","1h","4h","1d","1wk"
        limit:      Number of bars to fetch (max 2000)
        api_key:    BitOasis API key (or set BITOASIS_API_KEY env var)
        api_secret: BitOasis API secret (or set BITOASIS_API_SECRET env var)
    """
    if not REQUESTS_OK:
        raise ImportError("pip install requests")

    _key    = api_key    or os.getenv("BITOASIS_API_KEY",    "")
    _secret = api_secret or os.getenv("BITOASIS_API_SECRET", "")

    bo_sym = _symbol_to_bitoasis(symbol)
    bo_ivl = BITOASIS_INTERVAL_MAP.get(interval, "60min")
    limit  = min(int(limit), 2000)

    cache_key = f"bitoasis_{bo_sym}_{bo_ivl}_{limit}"
    if cache_key in _CRYPTO_CACHE:
        df_c, ts = _CRYPTO_CACHE[cache_key]
        if time.time() - ts < CACHE_TTL:
            return df_c.copy()

    df         = pd.DataFrame()
    last_error = ""

    # ── Attempt 1: Public Huobi-compatible kline endpoint ────────────────────
    try:
        resp = requests.get(
            f"{BITOASIS_MARKET_BASE}/market/history/kline",
            params={"symbol": bo_sym, "period": bo_ivl, "size": limit},
            timeout=10,
        )
        if resp.status_code == 200:
            klines = resp.json().get("data", [])
            if klines:
                df = _parse_huobi_klines(klines, symbol)
        elif resp.status_code == 404:
            last_error = f"Symbol '{bo_sym}' not found on public endpoint"
        else:
            last_error = f"HTTP {resp.status_code}"
    except Exception as e:
        last_error = str(e)

    # ── Attempt 2: Authenticated v3 API ──────────────────────────────────────
    if df.empty and _key and _secret:
        try:
            df = _fetch_bitoasis_auth(bo_sym, bo_ivl, limit, _key, _secret)
        except Exception as e:
            last_error += f" | auth: {e}"

    # ── Attempt 3: Alternative Huobi endpoint ─────────────────────────────────
    if df.empty:
        try:
            resp = requests.get(
                f"{BITOASIS_MARKET_BASE}/market/detail/merged",
                params={"symbol": bo_sym},
                timeout=5,
            )
            if resp.status_code == 200:
                # Can't get history from this endpoint but confirms symbol exists
                last_error += " | symbol exists but no kline data returned"
        except Exception:
            pass

    if df.empty:
        # Provide clear actionable message
        raise ValueError(
            f"BitOasis returned no data for '{bo_sym}' ({interval}).\n"
            f"Cause: {last_error}\n\n"
            f"To use BitOasis data you need:\n"
            f"  1. Valid API credentials: set BITOASIS_API_KEY and "
            f"BITOASIS_API_SECRET environment variables, or enter them in "
            f"the Auto-Trade sidebar panel.\n"
            f"  2. Supported AED pairs: {', '.join(BITOASIS_AED_PAIRS.keys())}\n"
            f"  3. For instant access without credentials, switch source to 'yfinance'."
        )

    _CRYPTO_CACHE[cache_key] = (df, time.time())
    return df.copy()


def _parse_huobi_klines(klines: list, symbol: str) -> pd.DataFrame:
    """Parse Huobi/BitOasis kline list into normalised DataFrame."""
    df = pd.DataFrame(klines)
    # Huobi format: {id, open, high, low, close, vol, amount, count}
    col_map = {"id":"ts","open":"Open","high":"High","low":"Low",
               "close":"Close","vol":"Volume","amount":"Amount"}
    df = df.rename(columns={k:v for k,v in col_map.items() if k in df.columns})

    if "ts" not in df.columns and "id" in df.columns:
        df["ts"] = df["id"]

    ts_col = "ts" if "ts" in df.columns else df.columns[0]
    df.index = pd.to_datetime(df[ts_col], unit="s", utc=True).dt.tz_localize(None)
    df.index.name = "Date"

    for col in ["Open","High","Low","Close","Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Volume" not in df.columns and "Amount" in df.columns:
        df["Volume"] = pd.to_numeric(df["Amount"], errors="coerce")

    df["Symbol"] = symbol.upper()
    df = df[["Open","High","Low","Close","Volume","Symbol"]].sort_index()
    df.dropna(subset=["Open","High","Low","Close"], inplace=True)
    return df


def _fetch_bitoasis_auth(sym: str, ivl: str, limit: int, key: str, secret: str) -> pd.DataFrame:
    """HMAC-signed request to BitOasis v3 API."""
    ts       = str(int(time.time() * 1000))
    path     = "/v3/market/klines"
    body     = json.dumps({"symbol": sym, "interval": ivl, "limit": limit})
    msg      = ts + "GET" + path + body
    sig      = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    key_bytes = b""  # clear after use

    headers = {
        "Content-Type":    "application/json",
        "X-API-Key":       key,
        "X-API-Sign":      sig,
        "X-API-Timestamp": ts,
    }
    resp = requests.get(
        f"{BITOASIS_API_BASE}{path}",
        headers=headers,
        params={"symbol": sym, "interval": ivl, "limit": limit},
        timeout=10,
    )
    resp.raise_for_status()
    data   = resp.json()
    klines = data.get("data", data) if isinstance(data, dict) else data
    if not klines:
        raise ValueError("Authenticated endpoint returned empty data")
    return _parse_huobi_klines(klines, sym)


def get_bitoasis_price(symbol: str, api_key: str = "", api_secret: str = "") -> Optional[float]:
    """Fetch current bid/ask mid-price from BitOasis."""
    if not REQUESTS_OK:
        return None
    _key    = api_key    or os.getenv("BITOASIS_API_KEY",    "")
    _secret = api_secret or os.getenv("BITOASIS_API_SECRET", "")
    bo_sym  = _symbol_to_bitoasis(symbol)
    try:
        resp = requests.get(
            f"{BITOASIS_MARKET_BASE}/market/detail/merged",
            params={"symbol": bo_sym}, timeout=5,
        )
        if resp.status_code == 200:
            tick = resp.json().get("tick", {})
            bid  = float(tick.get("bid", [0])[0])  if tick.get("bid") else 0
            ask  = float(tick.get("ask", [0])[0])  if tick.get("ask") else 0
            if bid and ask:
                return (bid + ask) / 2
            return float(tick.get("close", 0)) or None
    except Exception:
        pass
    # Fallback: use broker layer
    if _key and _secret:
        try:
            from brokers.bitoasis import BitOasisBroker
            base = symbol.upper()
            for s in ("USDT","USD","AED"):
                base = base.replace(s, "")
            b = BitOasisBroker(api_key=_key, api_secret=_secret, paper_trading=True)
            return b.get_price(f"{base}-AED")
        except Exception:
            pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  BINANCE MARKET DATA (blocked in Qatar — use with VPN)
# ══════════════════════════════════════════════════════════════════════════════
BINANCE_BASE = "https://api.binance.com"


def fetch_binance(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    if not REQUESTS_OK:
        raise ImportError("pip install requests")
    sym    = _validate_symbol(symbol.replace("-", ""))
    ivl    = BINANCE_INTERVAL_MAP.get(interval, interval)
    limit  = min(int(limit), 1000)
    ck     = f"binance_{sym}_{ivl}_{limit}"
    if ck in _CRYPTO_CACHE:
        df_c, ts = _CRYPTO_CACHE[ck]
        if time.time() - ts < CACHE_TTL:
            return df_c.copy()

    try:
        resp = requests.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": sym, "interval": ivl, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        raise ConnectionError(f"Binance: {e} (may be geo-blocked in Qatar — use VPN or switch to yfinance)")

    raw = resp.json()
    if not raw:
        raise ValueError(f"Binance returned no data for {sym}")

    df = pd.DataFrame(raw, columns=[
        "open_time","Open","High","Low","Close","Volume",
        "close_time","quote_vol","trades","taker_base","taker_quote","ignore"
    ])
    for col in ["Open","High","Low","Close","Volume"]:
        df[col] = df[col].astype(float)
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_localize(None)
    df.index.name = "Date"
    df = df[["Open","High","Low","Close","Volume"]].copy()
    df["Symbol"] = sym
    df.sort_index(inplace=True)
    _CRYPTO_CACHE[ck] = (df, time.time())
    return df.copy()


def get_binance_24h(symbol: str) -> dict:
    if not REQUESTS_OK:
        return {}
    try:
        sym  = _validate_symbol(symbol.replace("-",""))
        resp = requests.get(
            f"{BINANCE_BASE}/api/v3/ticker/24hr",
            params={"symbol": sym}, timeout=5,
        )
        if resp.status_code == 200:
            d = resp.json()
            return {
                "price":      float(d.get("lastPrice",0)),
                "change_pct": float(d.get("priceChangePercent",0)),
                "high_24h":   float(d.get("highPrice",0)),
                "low_24h":    float(d.get("lowPrice",0)),
                "volume_24h": float(d.get("quoteVolume",0)),
                "trades_24h": int(d.get("count",0)),
            }
    except Exception:
        pass
    return {}


def load_crypto(symbol: str, interval: str = "1h", limit: int = 500) -> Tuple[pd.DataFrame, str]:
    """Try Binance → yfinance fallback."""
    sym_upper = symbol.strip().upper()
    binance_sym = sym_upper.replace("-","").replace("USD","USDT")
    if not binance_sym.endswith("USDT"):
        binance_sym += "USDT"
    try:
        df = fetch_binance(binance_sym, interval=interval, limit=limit)
        return df, f"Binance ({binance_sym})"
    except Exception:
        pass
    # yfinance fallback
    try:
        from data.ingestion import fetch_yahoo
        yf_sym = sym_upper
        for s in ("USDT","BUSD"):
            if yf_sym.endswith(s): yf_sym = yf_sym[:-len(s)] + "-USD"; break
        df = fetch_yahoo(yf_sym, interval=interval)
        return df, f"Yahoo Finance ({yf_sym})"
    except Exception as e:
        raise ValueError(f"Could not load '{symbol}': {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  COINGECKO
# ══════════════════════════════════════════════════════════════════════════════
def fetch_coingecko(symbol: str, interval: str = "1d", days: int = 90) -> pd.DataFrame:
    if not REQUESTS_OK:
        raise ImportError("pip install requests")
    coin_id = _symbol_to_coingecko_id(symbol)
    ck = f"cg_{coin_id}_{days}"
    if ck in _CRYPTO_CACHE:
        df_c, ts = _CRYPTO_CACHE[ck]
        if time.time() - ts < CACHE_TTL:
            return df_c.copy()
    resp = requests.get(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc",
        params={"vs_currency":"usd","days":str(min(days,365))},
        timeout=10,
    )
    if resp.status_code == 404:
        raise ValueError(f"CoinGecko: coin '{coin_id}' not found")
    resp.raise_for_status()
    raw = resp.json()
    if not raw:
        raise ValueError(f"CoinGecko: no data for {coin_id}")
    df = pd.DataFrame(raw, columns=["timestamp","Open","High","Low","Close"])
    df.index = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df.index.name = "Date"
    df["Volume"] = 0.0
    df["Symbol"] = symbol.upper()
    df = df[["Open","High","Low","Close","Volume","Symbol"]].sort_index()
    _CRYPTO_CACHE[ck] = (df, time.time())
    return df.copy()


def clear_cache():
    """Clear all in-memory price caches."""
    _CRYPTO_CACHE.clear()
    try:
        from data.ingestion import clear_ingestion_cache
        clear_ingestion_cache()
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
#  KRAKEN — Real-time, no API key, accessible from Qatar
#  Docs: https://docs.kraken.com/rest/#tag/Market-Data/operation/getOHLCData
# ══════════════════════════════════════════════════════════════════════════════
KRAKEN_BASE = "https://api.kraken.com/0/public"

KRAKEN_INTERVAL_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440, "1wk": 10080,
}

# Kraken uses non-standard symbol names
KRAKEN_SYMBOLS = {
    "BTC":  "XBT",   # Kraken calls Bitcoin XBT
    "BTCUSD": "XBTUSD", "BTCUSDT": "XBTUSD", "BTC-USD": "XBTUSD",
    "BTC-AED": "XBTAED", "BTCAED": "XBTAED",
    "ETH":  "ETH",
    "ETHUSD": "ETHUSD", "ETHUSDT": "ETHUSD", "ETH-USD": "ETHUSD",
    "ETH-AED": "ETHAED", "ETHAED": "ETHAED",
    "XRPUSD": "XRPUSD", "XRP-USD": "XRPUSD",
    "SOLUSD": "SOLUSD", "SOL-USD": "SOLUSD",
    "ADAUSD": "ADAUSD", "ADA-USD": "ADAUSD",
    "DOGEUSD": "XDGUSD","DOGE-USD": "XDGUSD",
    "DOGEUSDT": "XDGUSD",
}


def _to_kraken_symbol(symbol: str) -> str:
    """Convert any symbol format to Kraken pair name."""
    sym = _validate_symbol(symbol)
    if sym in KRAKEN_SYMBOLS:
        return KRAKEN_SYMBOLS[sym]
    # Strip quote currency and add USD
    for suffix in ("USDT", "BUSD", "AED"):
        if sym.endswith(suffix) and len(sym) > len(suffix):
            base = sym[:-len(suffix)].rstrip("-")
            # Map BTC→XBT for Kraken
            base = "XBT" if base == "BTC" else base
            quote = "AED" if suffix == "AED" else "USD"
            return base + quote
    # Already a Kraken pair
    return sym.replace("BTC", "XBT")


def fetch_kraken(
    symbol: str,
    interval: str = "1h",
    limit: int = 720,
) -> pd.DataFrame:
    """
    Fetch real-time OHLCV from Kraken public REST API.
    No API key required. Accessible from Qatar and UAE.
    Returns the last `limit` candles (max 720 per Kraken's limit).

    Args:
        symbol:   Any format: "BTC-USD", "BTCUSDT", "BTC-AED", "XBTUSD"
        interval: "1m","5m","15m","30m","1h","4h","1d","1wk"
        limit:    Max bars to return (Kraken caps at 720)
    """
    if not REQUESTS_OK:
        raise ImportError("pip install requests")

    kraken_pair = _to_kraken_symbol(symbol)
    minutes     = KRAKEN_INTERVAL_MINUTES.get(interval, 60)
    limit       = min(int(limit), 720)

    cache_key = f"kraken_{kraken_pair}_{minutes}"
    if cache_key in _CRYPTO_CACHE:
        df_c, ts = _CRYPTO_CACHE[cache_key]
        if time.time() - ts < CACHE_TTL:
            return df_c.copy()

    try:
        resp = requests.get(
            f"{KRAKEN_BASE}/OHLC",
            params={"pair": kraken_pair, "interval": minutes},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(
            f"Cannot reach Kraken API ({e}). "
            f"Check internet connection or try a different network."
        )
    except Exception as e:
        raise ConnectionError(f"Kraken request failed: {e}")

    data = resp.json()
    if data.get("error"):
        errs = data["error"]
        if any("Unknown asset pair" in str(e) for e in errs):
            raise ValueError(
                f"Kraken: unknown pair '{kraken_pair}'. "
                f"Use formats like XBTUSD, ETHUSD, XBTAED. "
                f"Tried converting from: '{symbol}'"
            )
        raise ValueError(f"Kraken API error: {errs}")

    result = data.get("result", {})
    # Result has the pair data + a 'last' timestamp key
    ohlc_data = None
    for key in result:
        if key != "last":
            ohlc_data = result[key]
            break

    if not ohlc_data:
        raise ValueError(f"Kraken returned no OHLC data for {kraken_pair}")

    # Kraken format: [time, open, high, low, close, vwap, volume, count]
    df = pd.DataFrame(ohlc_data, columns=[
        "timestamp", "Open", "High", "Low", "Close", "vwap", "Volume", "count"
    ])
    df["Open"]   = df["Open"].astype(float)
    df["High"]   = df["High"].astype(float)
    df["Low"]    = df["Low"].astype(float)
    df["Close"]  = df["Close"].astype(float)
    df["Volume"] = df["Volume"].astype(float)

    df.index = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True).dt.tz_localize(None)
    df.index.name = "Date"
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df["Symbol"] = symbol.upper()
    df.sort_index(inplace=True)
    df = df.tail(limit)

    _CRYPTO_CACHE[cache_key] = (df, time.time())
    return df.copy()


def get_kraken_price(symbol: str) -> Optional[float]:
    """Fetch real-time last trade price from Kraken."""
    if not REQUESTS_OK:
        return None
    try:
        pair = _to_kraken_symbol(symbol)
        resp = requests.get(
            f"{KRAKEN_BASE}/Ticker",
            params={"pair": pair},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if not data.get("error"):
                result = data.get("result", {})
                for key in result:
                    c = result[key].get("c", [0])  # c = last trade closed
                    return float(c[0]) if c else None
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  KUCOIN — Real-time, no API key, accessible worldwide including Qatar
#  Docs: https://www.kucoin.com/docs/rest/spot-trading/market-data/get-klines
# ══════════════════════════════════════════════════════════════════════════════
KUCOIN_BASE = "https://api.kucoin.com/api/v1"

KUCOIN_INTERVAL_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1hour", "4h": "4hour", "1d": "1day", "1wk": "1week",
}


def _to_kucoin_symbol(symbol: str) -> str:
    """Convert symbol to KuCoin format: BTC-USDT."""
    sym = _validate_symbol(symbol)
    # Handle AED pairs — KuCoin doesn't have AED, use USDT
    for suffix in ("AED",):
        if sym.endswith(suffix) and len(sym) > len(suffix):
            return sym[:-len(suffix)].rstrip("-") + "-USDT"
    # Handle USDT pairs
    for suffix in ("USDT", "USD"):
        if sym.endswith(suffix) and len(sym) > len(suffix):
            base = sym[:-len(suffix)].rstrip("-")
            return f"{base}-USDT"
    # Handle yfinance style BTC-USD
    if "-" in sym:
        parts = sym.split("-")
        return f"{parts[0]}-USDT"
    return f"{sym}-USDT"


def fetch_kucoin(
    symbol: str,
    interval: str = "1h",
    limit: int = 500,
) -> pd.DataFrame:
    """
    Fetch real-time OHLCV from KuCoin public REST API.
    No API key required. Accessible from Qatar and worldwide.
    Returns up to 1500 candles.

    Args:
        symbol:   Any format: "BTC-USD", "BTCUSDT", "BTC-AED", "BTC-USDT"
        interval: "1m","5m","15m","30m","1h","4h","1d","1wk"
        limit:    Bars to return (max 1500 per KuCoin)
    """
    if not REQUESTS_OK:
        raise ImportError("pip install requests")

    kucoin_sym = _to_kucoin_symbol(symbol)
    kucoin_ivl = KUCOIN_INTERVAL_MAP.get(interval, "1hour")
    limit      = min(int(limit), 1500)

    cache_key = f"kucoin_{kucoin_sym}_{kucoin_ivl}_{limit}"
    if cache_key in _CRYPTO_CACHE:
        df_c, ts = _CRYPTO_CACHE[cache_key]
        if time.time() - ts < CACHE_TTL:
            return df_c.copy()

    # KuCoin wants startAt / endAt as Unix timestamps
    import datetime as dt
    end_ts   = int(dt.datetime.now(dt.timezone.utc).timestamp())
    # Calculate startAt from limit and interval
    interval_seconds = {
        "1min": 60, "5min": 300, "15min": 900, "30min": 1800,
        "1hour": 3600, "4hour": 14400, "1day": 86400, "1week": 604800,
    }
    secs_back = interval_seconds.get(kucoin_ivl, 3600) * limit
    start_ts  = end_ts - secs_back

    try:
        resp = requests.get(
            f"{KUCOIN_BASE}/market/candles",
            params={
                "symbol":  kucoin_sym,
                "type":    kucoin_ivl,
                "startAt": start_ts,
                "endAt":   end_ts,
            },
            timeout=10,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(
            f"Cannot reach KuCoin API ({e}). "
            f"Check internet connection."
        )
    except Exception as e:
        raise ConnectionError(f"KuCoin request failed: {e}")

    data = resp.json()
    if data.get("code") != "200000":
        raise ValueError(f"KuCoin error: {data.get('msg','Unknown error')} (symbol: {kucoin_sym})")

    raw = data.get("data", [])
    if not raw:
        raise ValueError(f"KuCoin returned no data for {kucoin_sym}")

    # KuCoin format: [timestamp, open, close, high, low, volume, turnover]
    # Note: KuCoin returns newest first — reverse!
    df = pd.DataFrame(raw, columns=[
        "timestamp", "Open", "Close", "High", "Low", "Volume", "Turnover"
    ])
    df["Open"]   = df["Open"].astype(float)
    df["High"]   = df["High"].astype(float)
    df["Low"]    = df["Low"].astype(float)
    df["Close"]  = df["Close"].astype(float)
    df["Volume"] = df["Volume"].astype(float)

    df.index = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True).dt.tz_localize(None)
    df.index.name = "Date"
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df["Symbol"] = symbol.upper()
    df.sort_index(inplace=True)   # ascending (oldest first)

    _CRYPTO_CACHE[cache_key] = (df, time.time())
    return df.copy()


def get_kucoin_price(symbol: str) -> Optional[float]:
    """Fetch real-time last price from KuCoin."""
    if not REQUESTS_OK:
        return None
    try:
        sym  = _to_kucoin_symbol(symbol)
        resp = requests.get(
            f"{KUCOIN_BASE}/market/orderbook/level1",
            params={"symbol": sym},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == "200000":
                return float(data["data"].get("price", 0)) or None
    except Exception:
        pass
    return None
