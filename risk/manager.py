"""
risk/manager.py — Risk Management Module

Responsibilities:
  - Validate that a trade meets risk criteria before execution
  - Enforce max open positions
  - Calculate ATR-based dynamic stop-losses
  - Track portfolio-level exposure
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import CONFIG, RiskConfig


@dataclass
class PositionCheck:
    approved: bool
    reasons: List[str] = field(default_factory=list)
    adjusted_sl: Optional[float] = None
    adjusted_tp: Optional[float] = None
    adjusted_size: Optional[float] = None


class RiskManager:
    """
    Stateful risk manager that tracks open positions and
    validates each proposed trade recommendation.
    """

    def __init__(self, config: RiskConfig = None):
        self.cfg           = config or CONFIG.risk
        self._open_positions: Dict[str, dict] = {}   # symbol → position info
        self._portfolio_value: float          = CONFIG.backtest.initial_capital

    # ── Core Validation ───────────────────────────────────────────────────────
    def check(
        self,
        symbol: str,
        signal: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        size_pct: float,
        df: pd.DataFrame,
    ) -> PositionCheck:
        """
        Validate a trade proposal against all risk rules.

        Returns PositionCheck with approved=True/False and reasons.
        """
        reasons = []

        # ── Rule 1: Max open positions ────────────────────────────────
        if signal in ("BUY", "SELL") and len(self._open_positions) >= self.cfg.max_open_positions:
            return PositionCheck(
                approved=False,
                reasons=[f"❌ Max open positions ({self.cfg.max_open_positions}) reached"]
            )

        # ── Rule 2: Risk:Reward must be ≥ 1.5:1 ──────────────────────
        risk    = abs(entry - stop_loss)
        reward  = abs(take_profit - entry)
        rr      = reward / risk if risk > 0 else 0

        if rr < 1.5 and signal != "HOLD":
            reasons.append(f"⚠️ R:R ratio {rr:.2f}:1 is below 1.5:1 minimum — adjusting TP")
            # Adjust TP to achieve minimum 1.5:1
            if signal == "BUY":
                take_profit = entry + risk * 2.0
            else:
                take_profit = entry - risk * 2.0
            reward = abs(take_profit - entry)
            rr     = reward / risk
            reasons.append(f"✅ TP adjusted to achieve {rr:.1f}:1 R:R")

        # ── Rule 3: SL must respect max drawdown per trade ────────────
        sl_pct = abs(entry - stop_loss) / entry
        if sl_pct > self.cfg.stop_loss_pct * 2:
            reasons.append(f"⚠️ SL distance {sl_pct:.1%} exceeds 2× max — using ATR-based SL")
            atr = self._get_atr(df)
            if signal == "BUY":
                stop_loss = entry - atr * 1.5
            else:
                stop_loss = entry + atr * 1.5
            reasons.append(f"✅ SL adjusted to ATR-based level: {stop_loss:.4f}")

        # ── Rule 4: Cap position size ─────────────────────────────────
        size_pct = min(size_pct, self.cfg.max_position_pct * 100)

        # ── Rule 5: Volatility gate — skip during extreme volatility ──
        vol_flag = self._check_volatility(df)
        if vol_flag:
            reasons.append(f"⚠️ High volatility environment detected — reducing size by 50%")
            size_pct = size_pct * 0.5

        reasons.append(
            f"✅ Risk check passed | SL: {abs(entry-stop_loss)/entry:.1%} "
            f"| R:R {rr:.1f}:1 | Size: {size_pct:.1f}%"
        )

        return PositionCheck(
            approved=True,
            reasons=reasons,
            adjusted_sl=stop_loss,
            adjusted_tp=take_profit,
            adjusted_size=size_pct,
        )

    # ── Position Tracking ─────────────────────────────────────────────────────
    def open_position(self, symbol: str, signal: str, entry: float, size_pct: float):
        self._open_positions[symbol] = {
            "signal": signal,
            "entry": entry,
            "size_pct": size_pct,
        }

    def close_position(self, symbol: str):
        self._open_positions.pop(symbol, None)

    def is_in_position(self, symbol: str) -> bool:
        return symbol in self._open_positions

    @property
    def open_positions(self) -> Dict[str, dict]:
        return dict(self._open_positions)

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _get_atr(df: pd.DataFrame) -> float:
        if "atr" in df.columns:
            return float(df["atr"].iloc[-1])
        close = df["Close"].iloc[-1]
        return close * 0.015   # fallback: 1.5% of price

    @staticmethod
    def _check_volatility(df: pd.DataFrame) -> bool:
        """True if current volatility is > 2× the 90-day average."""
        if "volatility" not in df.columns or len(df) < 20:
            return False
        vol_current = float(df["volatility"].iloc[-1])
        vol_avg     = float(df["volatility"].iloc[-90:].mean())
        return vol_current > vol_avg * 2.0

    @staticmethod
    def portfolio_heat(positions: Dict[str, dict]) -> float:
        """Total % of portfolio at risk across all open positions."""
        return sum(p.get("size_pct", 0) for p in positions.values())
