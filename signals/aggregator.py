"""
signals/aggregator.py — Signal Aggregation Engine

Combines individual strategy scores using configurable weights.

Strategy modes
──────────────
  "multi"         — 4 classic strategies weighted by WeightConfig (default)
                    Trend × 0.30 + Momentum × 0.25 + MeanRev × 0.25 + AI × 0.20

  "markov"        — Markov Chains only (weight = 1.0)
                    Uses state persistence + arbitrage gap conditions from PDF.

  "markov_multi"  — Markov Chains (40%) + 4 classic strategies (60%)
                    Provides blended conviction signal.

  "custom"        — weights read directly from WeightConfig at runtime

Threshold:
  composite > +0.20  → BUY
  composite < -0.20  → SELL
  else               → HOLD
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from config import CONFIG, BotConfig
from strategies.base import StrategyResult
from strategies.trend import TrendStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.ai_model import AIModelStrategy

try:
    from strategies.markov_chains import MarkovChainsStrategy
    MARKOV_OK = True
except ImportError:
    MARKOV_OK = False


@dataclass
class TradeRecommendation:
    """Final aggregated trade recommendation output."""
    symbol: str
    timestamp: str
    signal: str                         # BUY | SELL | HOLD
    composite_score: float              # [-1, +1]
    confidence_pct: float               # [0, 100]
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_pct: float
    strategy_mode: str = "multi"
    reasoning: List[str] = field(default_factory=list)
    strategy_breakdown: Dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "signal": self.signal,
            "score": round(self.composite_score, 4),
            "confidence_pct": round(self.confidence_pct, 1),
            "entry_price": round(self.entry_price, 4),
            "stop_loss": round(self.stop_loss, 4),
            "take_profit": round(self.take_profit, 4),
            "position_size_pct": round(self.position_size_pct, 2),
            "strategy_mode": self.strategy_mode,
            "trend_score": round(self.strategy_breakdown.get("trend", {}).get("score", 0), 4),
            "momentum_score": round(self.strategy_breakdown.get("momentum", {}).get("score", 0), 4),
            "reversion_score": round(self.strategy_breakdown.get("mean_reversion", {}).get("score", 0), 4),
            "ai_score": round(self.strategy_breakdown.get("ai_model", {}).get("score", 0), 4),
            "markov_score": round(self.strategy_breakdown.get("markov_chains", {}).get("score", 0), 4),
            "reasoning": " | ".join(self.reasoning),
        }

    def __str__(self) -> str:
        lines = [
            f"\n{'═'*60}",
            f"  TRADE RECOMMENDATION — {self.symbol}  [{self.strategy_mode.upper()}]",
            f"{'═'*60}",
            f"  Signal     : {self.signal}",
            f"  Confidence : {self.confidence_pct:.1f}%",
            f"  Entry      : {self.entry_price:.4f}",
            f"  Stop-Loss  : {self.stop_loss:.4f}",
            f"  Take-Profit: {self.take_profit:.4f}",
            f"  Position   : {self.position_size_pct:.1f}% of portfolio",
            f"{'─'*60}",
            f"  Strategy Scores:",
        ]
        for name, data in self.strategy_breakdown.items():
            lines.append(f"    {name:20s}: {data.get('score', 0):+.3f}  [{data.get('signal','?')}]")
        lines.append(f"    {'COMPOSITE':20s}: {self.composite_score:+.3f}")
        lines.append(f"{'─'*60}")
        lines.append("  Reasoning:")
        for r in self.reasoning:
            lines.append(f"    • {r}")
        lines.append(f"{'═'*60}\n")
        return "\n".join(lines)


class SignalAggregator:
    """
    Orchestrates all strategies and aggregates their outputs
    into a single TradeRecommendation.

    Parameters
    ----------
    config       : BotConfig — settings object
    strategy_mode: "multi" | "markov" | "markov_multi" | "custom"
    """

    MODE_MULTI        = "multi"
    MODE_MARKOV       = "markov"
    MODE_MARKOV_MULTI = "markov_multi"
    MODE_CUSTOM       = "custom"

    def __init__(
        self,
        config: BotConfig = None,
        strategy_mode: str = "multi",
    ):
        self.cfg           = config or CONFIG
        self.strategy_mode = strategy_mode
        w                  = self.cfg.weights

        self._strategies: Dict[str, object] = {}
        self._weights:    Dict[str, float]  = {}

        # ── Build strategy set based on mode ──────────────────────────────────
        if strategy_mode == self.MODE_MARKOV:
            # Pure Markov Chains — only this strategy with full weight
            if MARKOV_OK:
                self._strategies["markov_chains"] = MarkovChainsStrategy(
                    n_states = self.cfg.strategy.markov_n_states,
                    tau      = self.cfg.strategy.markov_tau,
                    eps      = self.cfg.strategy.markov_eps,
                    lookback = self.cfg.strategy.markov_lookback,
                )
                self._weights["markov_chains"] = 1.0
            else:
                # Fallback if import failed
                self._add_classic_strategies(w)

        elif strategy_mode == self.MODE_MARKOV_MULTI:
            # Markov 40% + classic strategies 60% (renormalised)
            if MARKOV_OK:
                self._strategies["markov_chains"] = MarkovChainsStrategy(
                    n_states = self.cfg.strategy.markov_n_states,
                    tau      = self.cfg.strategy.markov_tau,
                    eps      = self.cfg.strategy.markov_eps,
                    lookback = self.cfg.strategy.markov_lookback,
                )
                self._weights["markov_chains"] = 0.40
                # Classic strategies share the remaining 60%
                self._add_classic_strategies(w, scale=0.60)
            else:
                self._add_classic_strategies(w)

        else:
            # "multi" or "custom": classic 4-strategy aggregator
            self._add_classic_strategies(w)

        # ── Renormalise weights ────────────────────────────────────────────────
        total_w = sum(self._weights.values())
        if total_w > 0:
            self._weights = {k: v / total_w for k, v in self._weights.items()}

    # ── Core ──────────────────────────────────────────────────────────────────
    def analyse(self, df: pd.DataFrame, symbol: str) -> TradeRecommendation:
        """
        Run all active strategies on df and produce a TradeRecommendation.
        """
        sc = self.cfg.signal
        rc = self.cfg.risk

        results: Dict[str, StrategyResult] = {}
        all_reasons: List[str] = []

        # Run each strategy
        for name, strategy in self._strategies.items():
            try:
                result = strategy.score(df)
                results[name] = result
            except Exception as e:
                from utils.logger import setup_logger
                log = setup_logger("aggregator")
                log.warning(f"Strategy '{name}' raised: {e}")
                results[name] = StrategyResult(
                    score=0.0, signal="HOLD",
                    reasons=[f"Error: {e}"],
                    strategy_name=name,
                )

        # Weighted composite
        composite = sum(
            results[k].score * self._weights.get(k, 0)
            for k in results
        )
        composite = max(-1.0, min(1.0, composite))

        # Confidence [0, 100]
        confidence_pct = min(abs(composite) / 1.0 * 100.0, 100.0)

        # Signal decision
        if composite >= sc.buy_threshold:
            signal = "BUY"
        elif composite <= sc.sell_threshold:
            signal = "SELL"
        else:
            signal = "HOLD"

        # Price levels
        entry_price = float(df["Close"].iloc[-1])
        atr         = float(df["atr"].iloc[-1]) if "atr" in df.columns else entry_price * 0.01

        if signal == "BUY":
            stop_loss   = entry_price * (1 - rc.stop_loss_pct)
            take_profit = entry_price * (1 + rc.take_profit_pct)
        elif signal == "SELL":
            stop_loss   = entry_price * (1 + rc.stop_loss_pct)
            take_profit = entry_price * (1 - rc.take_profit_pct)
        else:
            stop_loss   = entry_price * (1 - rc.stop_loss_pct)
            take_profit = entry_price * (1 + rc.take_profit_pct)

        # Position sizing
        position_pct = self._position_size(composite, entry_price, stop_loss)

        # Build reasoning
        all_reasons.append(
            f"Composite score: {composite:+.3f} → {signal} "
            f"(confidence: {confidence_pct:.1f}%) "
            f"[mode: {self.strategy_mode}]"
        )
        for name, result in results.items():
            weight = self._weights.get(name, 0)
            all_reasons.append(
                f"[{name.upper()} | w={weight:.0%} | {result.score:+.3f}]"
            )
            all_reasons.extend(result.reasons)

        # Strategy breakdown dict
        breakdown = {
            name: {
                "score":      r.score,
                "signal":     r.signal,
                "sub_scores": r.sub_scores,
            }
            for name, r in results.items()
        }

        return TradeRecommendation(
            symbol=symbol,
            timestamp=datetime.utcnow().isoformat(),
            signal=signal,
            composite_score=composite,
            confidence_pct=confidence_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=position_pct,
            strategy_mode=self.strategy_mode,
            reasoning=all_reasons,
            strategy_breakdown=breakdown,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _add_classic_strategies(self, w, scale: float = 1.0):
        """Add the 4 classic strategies at weights scaled by `scale`."""
        if self.cfg.strategy.use_trend:
            self._strategies["trend"]          = TrendStrategy()
            self._weights["trend"]             = w.trend * scale

        if self.cfg.strategy.use_momentum:
            self._strategies["momentum"]       = MomentumStrategy(
                volume_spike_mult=self.cfg.strategy.volume_spike_mult
            )
            self._weights["momentum"]          = w.momentum * scale

        if self.cfg.strategy.use_mean_reversion:
            self._strategies["mean_reversion"] = MeanReversionStrategy()
            self._weights["mean_reversion"]    = w.mean_reversion * scale

        if self.cfg.strategy.use_ai_model:
            self._strategies["ai_model"]       = AIModelStrategy(
                train_size   = self.cfg.strategy.ai_train_size,
                n_estimators = self.cfg.strategy.ai_n_estimators,
            )
            self._weights["ai_model"]          = w.ai_model * scale

    def _position_size(self, score: float, entry: float, stop: float) -> float:
        """Kelly or fixed position sizing. Returns % of portfolio."""
        rc     = self.cfg.risk
        method = rc.sizing_method

        if method == "fixed":
            return rc.fixed_position_pct * 100

        # Kelly: f* = (bp - q) / b
        prob_win  = (abs(score) + 1.0) / 2.0
        prob_lose = 1.0 - prob_win
        risk_pct  = abs(entry - stop) / entry if entry else 0.02
        b         = rc.take_profit_pct / risk_pct if risk_pct > 0 else 1.0

        kelly_f   = (b * prob_win - prob_lose) / b
        kelly_f   = max(0.0, kelly_f)
        kelly_f  *= rc.kelly_fraction
        kelly_f   = min(kelly_f, rc.max_position_pct)

        return round(kelly_f * 100, 2)
