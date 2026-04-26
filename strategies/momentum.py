"""
strategies/momentum.py — Momentum / Breakout Strategy (Weight: 25%)

Signals:
  1. Breakout: close above rolling N-bar high (bullish) or below low (bearish)
  2. Volume confirmation: spike in volume validates the breakout
  3. Price momentum: N-day return velocity (acceleration)

Score logic:
  Breakout up + volume spike  → strong BUY  (+0.8 to +1.0)
  Breakout up, no volume      → weak BUY    (+0.3 to +0.5)
  Breakout down + volume      → strong SELL (-0.8 to -1.0)
  Momentum only (no breakout) → mild signal (±0.3)
"""

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, score_to_signal


class MomentumStrategy(BaseStrategy):

    def __init__(self, volume_spike_mult: float = 2.0):
        super().__init__("Momentum (Breakout + Volume)")
        self.volume_spike_mult = volume_spike_mult

    def score(self, df: pd.DataFrame) -> StrategyResult:
        reasons    = []
        breakout_s = 0.0
        volume_s   = 0.0
        momentum_s = 0.0

        # ── 1. Breakout Detection ─────────────────────────────────────────
        close       = self._last(df, "Close",       1)
        roll_high   = self._last(df, "roll_high",   2)   # prior bar's rolling high
        roll_low    = self._last(df, "roll_low",    2)   # prior bar's rolling low
        b_up        = self._last(df, "breakout_up", 1)
        b_dn        = self._last(df, "breakout_dn", 1)

        if b_up and roll_high is not None and close is not None:
            pct_break = (close / roll_high - 1) * 100
            breakout_s = min(0.80 + pct_break * 0.05, 1.0)
            reasons.append(
                f"🚀 Bullish breakout! Price closed {pct_break:.2f}% above {int(self._last(df,'roll_high',1)/roll_high*0 or 20)}-bar resistance"
            )
        elif b_dn and roll_low is not None and close is not None:
            pct_break = (roll_low / close - 1) * 100
            breakout_s = -min(0.80 + pct_break * 0.05, 1.0)
            reasons.append(
                f"📉 Bearish breakdown! Price closed {pct_break:.2f}% below support"
            )
        else:
            reasons.append("⚪ No breakout — price inside recent range")

        # ── 2. Volume Confirmation ────────────────────────────────────────
        vol_ratio = self._last(df, "vol_ratio", 1)

        if vol_ratio is not None:
            if vol_ratio >= self.volume_spike_mult:
                vol_mult  = vol_ratio / self.volume_spike_mult
                volume_s  = min(vol_mult * 0.40, 1.0)
                if breakout_s > 0:
                    volume_s = volume_s           # confirms bullish breakout
                elif breakout_s < 0:
                    volume_s = -volume_s          # confirms bearish breakdown
                reasons.append(
                    f"✅ Volume spike: {vol_ratio:.1f}x average ({vol_ratio:.1f}x > {self.volume_spike_mult}x threshold)"
                )
            elif vol_ratio >= 1.3:
                volume_s = 0.15 if breakout_s >= 0 else -0.15
                reasons.append(f"📊 Slightly elevated volume ({vol_ratio:.1f}x average)")
            else:
                if abs(breakout_s) > 0.5:
                    volume_s = -0.10 * (1 if breakout_s > 0 else -1)
                    reasons.append(f"⚠️ Breakout on low volume ({vol_ratio:.1f}x) — less reliable")
                else:
                    reasons.append(f"⚪ Normal volume ({vol_ratio:.1f}x average)")

        # ── 3. Price Momentum (rate of change) ───────────────────────────
        ret_1  = self._last(df, "returns_1d",  1)
        ret_5  = self._last(df, "returns_5d",  1)
        ret_20 = self._last(df, "returns_20d", 1)

        if all(v is not None for v in [ret_1, ret_5, ret_20]):
            # Weighted momentum score across timeframes
            mom_raw = ret_1 * 0.20 + ret_5 * 0.35 + ret_20 * 0.45
            momentum_s = np.tanh(mom_raw * 10)  # squash to [-1, 1]

            if mom_raw > 0.02:
                reasons.append(
                    f"📈 Strong positive momentum: 1d={ret_1*100:.1f}%, 5d={ret_5*100:.1f}%, 20d={ret_20*100:.1f}%"
                )
            elif mom_raw < -0.02:
                reasons.append(
                    f"📉 Strong negative momentum: 1d={ret_1*100:.1f}%, 5d={ret_5*100:.1f}%, 20d={ret_20*100:.1f}%"
                )
            else:
                reasons.append(
                    f"⚪ Neutral momentum: 1d={ret_1*100:.1f}%, 5d={ret_5*100:.1f}%, 20d={ret_20*100:.1f}%"
                )

        # ── Combine ───────────────────────────────────────────────────────
        raw_score = (
            breakout_s * 0.45
            + volume_s  * 0.30
            + momentum_s * 0.25
        )
        raw_score = max(-1.0, min(1.0, raw_score))
        signal    = score_to_signal(raw_score, buy_thresh=0.15, sell_thresh=-0.15)

        return StrategyResult(
            score=raw_score,
            signal=signal,
            reasons=reasons,
            strategy_name=self.name,
            sub_scores={
                "breakout": round(breakout_s, 3),
                "volume": round(volume_s, 3),
                "momentum": round(momentum_s, 3),
            },
        )
