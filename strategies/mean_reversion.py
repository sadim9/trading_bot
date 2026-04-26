"""
strategies/mean_reversion.py — Mean Reversion Strategy (Weight: 25%)

Signals:
  1. RSI: oversold (<30) → BUY, overbought (>70) → SELL
  2. Bollinger Bands: price at lower band → BUY, upper band → SELL
  3. RSI divergence detection (price new high but RSI lower → bearish div)

Score logic:
  Both RSI and BB agree → ±1.0 (high confidence)
  Only one fires → ±0.5 (moderate)
  Divergence adds conviction to the opposite signal
"""

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, score_to_signal


class MeanReversionStrategy(BaseStrategy):

    def __init__(self):
        super().__init__("Mean Reversion (RSI + BB)")

    def score(self, df: pd.DataFrame) -> StrategyResult:
        reasons   = []
        rsi_score = 0.0
        bb_score  = 0.0
        div_score = 0.0

        # ── 1. RSI ────────────────────────────────────────────────────────
        rsi = self._last(df, "rsi", 1)
        rsi_prev = self._last(df, "rsi", 2)

        if rsi is not None:
            if rsi < 25:
                rsi_score = 1.0
                reasons.append(f"🟢 RSI extremely oversold ({rsi:.1f}) — strong mean-reversion BUY")
            elif rsi < 30:
                rsi_score = 0.70
                reasons.append(f"🟢 RSI oversold ({rsi:.1f} < 30) — potential reversal up")
            elif rsi < 40:
                rsi_score = 0.25
                reasons.append(f"🟡 RSI in recovery zone ({rsi:.1f}) — mild bullish lean")
            elif rsi > 75:
                rsi_score = -1.0
                reasons.append(f"🔴 RSI extremely overbought ({rsi:.1f}) — strong mean-reversion SELL")
            elif rsi > 70:
                rsi_score = -0.70
                reasons.append(f"🔴 RSI overbought ({rsi:.1f} > 70) — potential reversal down")
            elif rsi > 60:
                rsi_score = -0.25
                reasons.append(f"🟡 RSI in extended zone ({rsi:.1f}) — mild bearish lean")
            else:
                reasons.append(f"⚪ RSI neutral ({rsi:.1f}) — no signal")

        # ── 2. Bollinger Bands ─────────────────────────────────────────────
        bb_pct   = self._last(df, "bb_pct",   1)
        bb_upper = self._last(df, "bb_upper",  1)
        bb_lower = self._last(df, "bb_lower",  1)
        close    = self._last(df, "Close",     1)
        bb_mid   = self._last(df, "bb_mid",    1)

        if bb_pct is not None and close is not None:
            if bb_pct < 0.0:
                bb_score = 1.0
                pct_below = (bb_lower - close) / bb_lower * 100
                reasons.append(f"🟢 Price {pct_below:.1f}% BELOW lower Bollinger Band — oversold")
            elif bb_pct < 0.20:
                bb_score = 0.60
                reasons.append(f"🟢 Price near lower Bollinger Band (BB% = {bb_pct:.2f})")
            elif bb_pct > 1.0:
                bb_score = -1.0
                pct_above = (close - bb_upper) / bb_upper * 100
                reasons.append(f"🔴 Price {pct_above:.1f}% ABOVE upper Bollinger Band — overbought")
            elif bb_pct > 0.80:
                bb_score = -0.60
                reasons.append(f"🔴 Price near upper Bollinger Band (BB% = {bb_pct:.2f})")
            else:
                band_pos = "upper half" if bb_pct > 0.5 else "lower half"
                reasons.append(f"⚪ Price in {band_pos} of BB (BB% = {bb_pct:.2f})")

        # ── 3. RSI Divergence (lookback 10 bars) ─────────────────────────
        if len(df) >= 10:
            price_window = df["Close"].iloc[-10:]
            rsi_window   = df["rsi"].iloc[-10:]

            price_high_idx = price_window.idxmax()
            price_low_idx  = price_window.idxmin()
            rsi_high_idx   = rsi_window.idxmax()
            rsi_low_idx    = rsi_window.idxmin()

            # Bearish divergence: price made new high but RSI didn't
            price_at_high = price_window.iloc[-1] >= price_window.quantile(0.85)
            rsi_not_high  = rsi_window.iloc[-1] <= rsi_window.quantile(0.50)
            if price_at_high and rsi_not_high:
                div_score = -0.25
                reasons.append("⚠️ Bearish RSI divergence detected — price high but RSI lagging")

            # Bullish divergence: price made new low but RSI didn't
            price_at_low  = price_window.iloc[-1] <= price_window.quantile(0.15)
            rsi_not_low   = rsi_window.iloc[-1] >= rsi_window.quantile(0.50)
            if price_at_low and rsi_not_low:
                div_score = 0.25
                reasons.append("✅ Bullish RSI divergence detected — price low but RSI holding up")

        # ── Combine ───────────────────────────────────────────────────────
        raw_score = (rsi_score * 0.55 + bb_score * 0.35 + div_score * 0.10)
        raw_score = max(-1.0, min(1.0, raw_score))
        signal    = score_to_signal(raw_score, buy_thresh=0.15, sell_thresh=-0.15)

        return StrategyResult(
            score=raw_score,
            signal=signal,
            reasons=reasons,
            strategy_name=self.name,
            sub_scores={
                "rsi": round(rsi_score, 3),
                "bollinger": round(bb_score, 3),
                "divergence": round(div_score, 3),
            },
        )
