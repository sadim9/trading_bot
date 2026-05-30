"""
ml/features.py — Feature engineering for return prediction.

Transforms the OHLCV + existing technical-indicator DataFrame (from
data/ingestion.py) into a clean ML feature matrix following the signal
categories described in Kelly & Xiu (2023):
  - Price momentum (short reversal, medium/long momentum)
  - Trend (EMA cross, price vs moving averages)
  - Mean reversion (RSI, Bollinger %B, stochastic)
  - Volatility (ATR, realised vol, vol-of-vol)
  - Volume (vol ratio, OBV momentum)
  - Breakout (range position, channel breakouts)

All features are cross-sectionally rank-standardised to [-1, 1] to match
the paper's pre-processing and to make signals comparable across symbols.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Tuple


# ── Feature names ──────────────────────────────────────────────────────────────
FEATURE_COLS = [
    # Momentum
    "f_ret_1",      # 1-bar return (short-term reversal signal)
    "f_ret_5",      # 5-bar return
    "f_ret_20",     # 20-bar return (1-month momentum)
    "f_ret_60",     # 60-bar return (3-month momentum)
    "f_ret_120",    # 120-bar return (6-month momentum)
    # Trend
    "f_ema_cross",  # EMA fast > slow (0/1)
    "f_vs_ema_f",   # price / ema_fast - 1
    "f_vs_ema_s",   # price / ema_slow - 1
    "f_macd_norm",  # MACD / price (normalised)
    "f_macd_hist",  # MACD histogram / price
    # Mean reversion
    "f_rsi_norm",   # RSI mapped to [-1, 1]
    "f_bb_pct",     # Bollinger %B (already 0-1, remapped)
    "f_stoch",      # Stochastic %K
    "f_close_vs_high",  # close / rolling 20-bar high - 1
    "f_close_vs_low",   # close / rolling 20-bar low  - 1
    # Volatility
    "f_atr_norm",   # ATR / close
    "f_realvol",    # realised 20-bar vol of returns
    "f_vol_accel",  # change in realised vol (vol-of-vol proxy)
    # Volume
    "f_vol_ratio",  # volume / 20-bar avg volume
    "f_obv_mom",    # OBV 5-bar momentum (normalised)
    # Breakout
    "f_breakout_u", # price broke above 20-bar high (0/1)
    "f_breakout_d", # price broke below 20-bar low  (0/1)
    "f_range_pos",  # (close - low20) / (high20 - low20)
    # Accruals proxy
    "f_price_accel",# second derivative of price (momentum acceleration)
]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Engineer ML features from an OHLCV + indicators DataFrame.

    Returns a DataFrame with columns = FEATURE_COLS, same index as df,
    with NaN rows dropped.  The returned frame may be shorter than df
    because multi-bar lookback features need warmup.
    """
    c = df["Close"]
    h = df["High"]
    lo = df["Low"]
    v = df["Volume"]

    feat = pd.DataFrame(index=df.index)

    # ── Momentum ──────────────────────────────────────────────────────────────
    feat["f_ret_1"]   = c.pct_change(1)
    feat["f_ret_5"]   = c.pct_change(5)
    feat["f_ret_20"]  = c.pct_change(20)
    feat["f_ret_60"]  = c.pct_change(60)
    feat["f_ret_120"] = c.pct_change(120)

    # ── Trend ─────────────────────────────────────────────────────────────────
    feat["f_ema_cross"] = df["ema_cross"].astype(float) if "ema_cross" in df.columns else (
        (df["ema_fast"] > df["ema_slow"]).astype(float) if "ema_fast" in df.columns else 0.0
    )
    feat["f_vs_ema_f"] = df["price_vs_ema_fast"] if "price_vs_ema_fast" in df.columns else c / c.ewm(span=50).mean() - 1
    feat["f_vs_ema_s"] = df["price_vs_ema_slow"] if "price_vs_ema_slow" in df.columns else c / c.ewm(span=200).mean() - 1
    _macd = df["macd"] if "macd" in df.columns else c.ewm(span=12).mean() - c.ewm(span=26).mean()
    feat["f_macd_norm"] = _macd / c.replace(0, np.nan)
    _hist = df["macd_hist"] if "macd_hist" in df.columns else _macd - _macd.ewm(span=9).mean()
    feat["f_macd_hist"] = _hist / c.replace(0, np.nan)

    # ── Mean reversion ────────────────────────────────────────────────────────
    _rsi = df["rsi"] if "rsi" in df.columns else pd.Series(50.0, index=df.index)
    feat["f_rsi_norm"] = (_rsi - 50.0) / 50.0          # maps [0,100] → [-1, 1]
    _bb_pct = df["bb_pct"] if "bb_pct" in df.columns else 0.5
    feat["f_bb_pct"] = _bb_pct * 2 - 1                  # maps [0,1] → [-1, 1]

    _roll_h20 = h.rolling(20).max()
    _roll_l20 = lo.rolling(20).min()
    _hilo = (_roll_h20 - _roll_l20).replace(0, np.nan)
    feat["f_stoch"]     = (c - _roll_l20) / _hilo
    feat["f_close_vs_high"] = c / _roll_h20 - 1
    feat["f_close_vs_low"]  = c / _roll_l20 - 1

    # ── Volatility ────────────────────────────────────────────────────────────
    _atr = df["atr"] if "atr" in df.columns else (h - lo).rolling(14).mean()
    feat["f_atr_norm"]  = _atr / c.replace(0, np.nan)
    _rv = df["volatility"] if "volatility" in df.columns else c.pct_change().rolling(20).std()
    feat["f_realvol"]   = _rv
    feat["f_vol_accel"] = _rv.pct_change(5)

    # ── Volume ────────────────────────────────────────────────────────────────
    _vr = df["vol_ratio"] if "vol_ratio" in df.columns else v / v.rolling(20).mean()
    feat["f_vol_ratio"] = _vr
    # OBV 5-bar momentum
    _obv = (np.sign(c.diff()) * v).cumsum()
    feat["f_obv_mom"]   = _obv.pct_change(5)

    # ── Breakout ──────────────────────────────────────────────────────────────
    feat["f_breakout_u"] = (c > _roll_h20.shift(1)).astype(float)
    feat["f_breakout_d"] = (c < _roll_l20.shift(1)).astype(float)
    feat["f_range_pos"]  = (c - _roll_l20) / _hilo

    # ── Price acceleration ────────────────────────────────────────────────────
    feat["f_price_accel"] = feat["f_ret_1"].diff(3)

    # ── Clip extreme values (winsorise at 1st/99th pct per column) ────────────
    for col in feat.columns:
        lo_p = feat[col].quantile(0.01)
        hi_p = feat[col].quantile(0.99)
        feat[col] = feat[col].clip(lo_p, hi_p)

    feat.replace([np.inf, -np.inf], np.nan, inplace=True)
    feat.dropna(inplace=True)

    return feat[FEATURE_COLS]


def rank_standardise(series: pd.Series) -> pd.Series:
    """Rank-standardise a series to [-1, 1]."""
    r = series.rank(pct=True)
    return r * 2 - 1


def build_dataset(
    df: pd.DataFrame,
    horizon: int = 1,
    min_bars: int = 60,
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Build aligned (X, y) where y = forward return over `horizon` bars.

    Returns (features_df, target_series) with matching index.
    Requires at least `min_bars` samples after feature construction.
    """
    feat = build_features(df)
    if len(feat) < min_bars:
        raise ValueError(f"Need ≥{min_bars} bars after feature engineering; got {len(feat)}")

    # Forward return as target (shift back so we predict close[t+horizon]/close[t]-1)
    fwd_ret = df["Close"].pct_change(horizon).shift(-horizon)
    fwd_ret = fwd_ret.reindex(feat.index).dropna()
    feat    = feat.reindex(fwd_ret.index)

    # Cross-sectional rank-standardise features
    for col in feat.columns:
        feat[col] = rank_standardise(feat[col])

    return feat, fwd_ret


def get_feature_names() -> List[str]:
    return list(FEATURE_COLS)
