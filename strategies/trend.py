"""
strategies/trend.py — Trend-Following Strategy (Weight: 30%)

Signals:
  1. EMA crossover: 50-EMA crosses above/below 200-EMA (Golden/Death cross)
  2. MACD: MACD line vs signal line, histogram momentum

Score logic:
  EMA bullish  (+0.5) + MACD bullish  (+0.5) = +1.0 (strong BUY)
  EMA bullish  (+0.5) + MACD bearish  (-0.5) =  0.0 (HOLD — conflicted)
  EMA bearish  (-0.5) + MACD bearish  (-0.5) = -1.0 (strong SELL)
"""

import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, score_to_signal


class TrendStrategy(BaseStrategy):

    def __init__(self):
        super().__init__("Trend (EMA + MACD)")

    def score(self, df: pd.DataFrame) -> StrategyResult:
        reasons = []
        ema_score  = 0.0
        macd_score = 0.0

        # ── 1. EMA Crossover ─────────────────────────────────────────────
        ema_fast_cur  = self._last(df, "ema_fast",  1)
        ema_slow_cur  = self._last(df, "ema_slow",  1)
        ema_fast_prev = self._last(df, "ema_fast",  2)
        ema_slow_prev = self._last(df, "ema_slow",  2)
        close         = self._last(df, "Close",     1)

        if all(v is not None for v in [ema_fast_cur, ema_slow_cur]):
            if ema_fast_cur > ema_slow_cur:
                ema_score = 0.50
                gap_pct   = (ema_fast_cur / ema_slow_cur - 1) * 100
                # Golden cross just happened?
                if ema_fast_prev is not None and ema_slow_prev is not None:
                    if ema_fast_prev <= ema_slow_prev:
                        ema_score = 0.65   # fresh crossover bonus
                        reasons.append("🟢 Golden Cross: EMA50 just crossed above EMA200")
                    else:
                        reasons.append(f"🟢 EMA50 above EMA200 ({gap_pct:.2f}% gap) — uptrend")
            else:
                ema_score = -0.50
                gap_pct   = (ema_slow_cur / ema_fast_cur - 1) * 100
                if ema_fast_prev is not None and ema_slow_prev is not None:
                    if ema_fast_prev >= ema_slow_prev:
                        ema_score = -0.65  # fresh death-cross penalty
                        reasons.append("🔴 Death Cross: EMA50 just crossed below EMA200")
                    else:
                        reasons.append(f"🔴 EMA50 below EMA200 ({gap_pct:.2f}% gap) — downtrend")

            # Price position relative to EMAs adds granularity
            if close is not None and close > ema_fast_cur:
                reasons.append("✅ Price above EMA50 — short-term bullish")
            elif close is not None:
                reasons.append("⚠️ Price below EMA50 — short-term bearish")

        # ── 2. MACD ──────────────────────────────────────────────────────
        macd_cur    = self._last(df, "macd",       1)
        sig_cur     = self._last(df, "macd_signal",1)
        hist_cur    = self._last(df, "macd_hist",  1)
        hist_prev   = self._last(df, "macd_hist",  2)
        macd_prev   = self._last(df, "macd",       2)
        sig_prev    = self._last(df, "macd_signal",2)

        if all(v is not None for v in [macd_cur, sig_cur, hist_cur]):
            # MACD above signal
            if macd_cur > sig_cur:
                macd_score += 0.30
                # Just crossed?
                if macd_prev is not None and sig_prev is not None and macd_prev <= sig_prev:
                    macd_score += 0.20   # bullish crossover bonus
                    reasons.append("🟢 MACD bullish crossover (MACD crossed above signal line)")
                else:
                    reasons.append("🟢 MACD above signal line — bullish momentum")
            else:
                macd_score -= 0.30
                if macd_prev is not None and sig_prev is not None and macd_prev >= sig_prev:
                    macd_score -= 0.20
                    reasons.append("🔴 MACD bearish crossover (MACD crossed below signal line)")
                else:
                    reasons.append("🔴 MACD below signal line — bearish momentum")

            # Histogram growing / shrinking
            if hist_prev is not None:
                if hist_cur > hist_prev:
                    macd_score += 0.10
                    reasons.append("📈 MACD histogram expanding — momentum accelerating")
                else:
                    macd_score -= 0.10
                    reasons.append("📉 MACD histogram contracting — momentum fading")

        # Combine and clamp
        raw_score = (ema_score + macd_score) / 2
        raw_score = max(-1.0, min(1.0, raw_score))
        signal    = score_to_signal(raw_score, buy_thresh=0.15, sell_thresh=-0.15)

        return StrategyResult(
            score=raw_score,
            signal=signal,
            reasons=reasons,
            strategy_name=self.name,
            sub_scores={"ema": round(ema_score, 3), "macd": round(macd_score, 3)},
        )
