"""
strategies/ma_cross.py — Moving Average Crossover Strategy

Pine Script equivalent of:
    short = ta.sma(close, shortlen)
    long  = ta.sma(close, longlen)
    cross = ta.cross(short, long)

Detects:
  Golden Cross: short SMA crosses ABOVE long SMA → BUY
  Death Cross:  short SMA crosses BELOW long SMA → SELL

Returns StrategyResult with:
  +1.0 on fresh golden cross
  +0.5 if short is above long (sustained bull)
  -1.0 on fresh death cross
  -0.5 if short is below long (sustained bear)
   0.0 at exact cross (ambiguous bar)

Also exposes:
  .short_ma   — current short SMA value
  .long_ma    — current long SMA value
  .cross_up   — True if golden cross this bar
  .cross_down — True if death cross this bar
"""

import pandas as pd
import numpy as np
from strategies.base import BaseStrategy, StrategyResult, score_to_signal


class MACrossStrategy(BaseStrategy):

    def __init__(self, short_period: int = 9, long_period: int = 21):
        super().__init__(f"MA Cross (SMA{short_period}/SMA{long_period})")
        self.short_period = short_period
        self.long_period  = long_period

        # Expose for dashboard and order manager
        self.short_ma:   float = 0.0
        self.long_ma:    float = 0.0
        self.cross_up:   bool  = False
        self.cross_down: bool  = False

    def score(self, df: pd.DataFrame) -> StrategyResult:
        reasons = []

        if len(df) < self.long_period + 2:
            return StrategyResult(
                score=0.0, signal="HOLD",
                reasons=["Insufficient bars for MA Cross"],
                strategy_name=self.name,
            )

        close = df["Close"]
        short = close.rolling(self.short_period).mean()
        long_ = close.rolling(self.long_period).mean()

        s_cur  = float(short.iloc[-1])
        s_prev = float(short.iloc[-2])
        l_cur  = float(long_.iloc[-1])
        l_prev = float(long_.iloc[-2])

        self.short_ma   = s_cur
        self.long_ma    = l_cur

        # Cross detection — mirrors ta.cross() in Pine
        self.cross_up   = s_prev <= l_prev and s_cur > l_cur
        self.cross_down = s_prev >= l_prev and s_cur < l_cur

        raw_score = 0.0

        if self.cross_up:
            raw_score = 1.0
            gap_pct = (s_cur / l_cur - 1) * 100
            reasons.append(
                f"GOLDEN CROSS: SMA{self.short_period} ({s_cur:.4f}) crossed ABOVE "
                f"SMA{self.long_period} ({l_cur:.4f}) | gap {gap_pct:+.3f}%"
            )
        elif self.cross_down:
            raw_score = -1.0
            gap_pct = (l_cur / s_cur - 1) * 100
            reasons.append(
                f"DEATH CROSS: SMA{self.short_period} ({s_cur:.4f}) crossed BELOW "
                f"SMA{self.long_period} ({l_cur:.4f}) | gap {gap_pct:+.3f}%"
            )
        elif s_cur > l_cur:
            raw_score = 0.5
            gap_pct = (s_cur / l_cur - 1) * 100
            reasons.append(
                f"SMA{self.short_period} above SMA{self.long_period} "
                f"({gap_pct:+.3f}%) — sustained uptrend"
            )
        elif s_cur < l_cur:
            raw_score = -0.5
            gap_pct = (l_cur / s_cur - 1) * 100
            reasons.append(
                f"SMA{self.short_period} below SMA{self.long_period} "
                f"({gap_pct:+.3f}%) — sustained downtrend"
            )
        else:
            reasons.append(
                f"SMA{self.short_period} and SMA{self.long_period} at parity — neutral"
            )

        signal = score_to_signal(raw_score, buy_thresh=0.8, sell_thresh=-0.8)

        return StrategyResult(
            score=raw_score,
            signal=signal,
            reasons=reasons,
            strategy_name=self.name,
            sub_scores={
                "short_ma":   round(s_cur, 6),
                "long_ma":    round(l_cur, 6),
                "cross_up":   int(self.cross_up),
                "cross_down": int(self.cross_down),
            },
        )
