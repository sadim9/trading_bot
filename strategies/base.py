"""
strategies/base.py — Abstract base class for all strategies.

Every strategy must implement `score()`, which returns a float in [-1, +1]:
  +1.0  = maximum bullish conviction
  -1.0  = maximum bearish conviction
   0.0  = neutral / no signal
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class StrategyResult:
    """Structured output from a strategy's score() call."""
    score: float                    # -1.0 to +1.0
    signal: str                     # "BUY" | "SELL" | "HOLD"
    reasons: List[str]              # human-readable explanations
    strategy_name: str
    sub_scores: dict = None         # optional breakdown of component scores

    def __post_init__(self):
        self.score = max(-1.0, min(1.0, self.score))   # clamp
        if self.sub_scores is None:
            self.sub_scores = {}


def score_to_signal(score: float, buy_thresh: float = 0.2, sell_thresh: float = -0.2) -> str:
    """Convert a raw [-1, +1] score to a BUY / SELL / HOLD label."""
    if score >= buy_thresh:
        return "BUY"
    elif score <= sell_thresh:
        return "SELL"
    return "HOLD"


class BaseStrategy(ABC):
    """All strategies inherit from this class."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def score(self, df: pd.DataFrame) -> StrategyResult:
        """
        Analyse the most recent market state and return a StrategyResult.

        Args:
            df: DataFrame with OHLCV + technical indicators (from data.ingestion)

        Returns:
            StrategyResult with score ∈ [-1, +1], signal, and reasons list
        """

    def _last(self, df: pd.DataFrame, col: str, n: int = 1):
        """Safely get the nth-to-last value of a column."""
        try:
            return df[col].iloc[-n]
        except (KeyError, IndexError):
            return None
