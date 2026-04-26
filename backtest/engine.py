"""
backtest/engine.py — Historical Simulation Engine

Walk-forward backtesting:
  - Iterates bar-by-bar (no lookahead bias)
  - Applies all strategies at each bar using only past data
  - Tracks portfolio value, open positions, and trade log
  - Returns equity curve + full trade log for metrics calculation

Commission and slippage are applied on every fill.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import CONFIG, BacktestConfig, BotConfig
from analytics.metrics import compute_metrics, print_metrics


@dataclass
class Trade:
    symbol: str
    direction: str          # "long" | "short"
    entry_date: str
    entry_price: float
    stop_loss: float
    take_profit: float
    size_pct: float         # % of equity allocated
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""   # "tp" | "sl" | "signal_flip" | "end"
    pnl_pct: float = 0.0
    pnl_dollar: float = 0.0

    def close(self, exit_date: str, exit_price: float, reason: str, portfolio_val: float):
        self.exit_date   = exit_date
        self.exit_price  = exit_price
        self.exit_reason = reason
        if self.direction == "long":
            self.pnl_pct = (exit_price - self.entry_price) / self.entry_price
        else:
            self.pnl_pct = (self.entry_price - exit_price) / self.entry_price
        notional         = portfolio_val * self.size_pct / 100
        self.pnl_dollar  = notional * self.pnl_pct


class BacktestEngine:
    """
    Event-driven walk-forward backtester.
    """

    def __init__(self, config: BotConfig = None):
        self.cfg       = config or CONFIG
        self.bc        = self.cfg.backtest
        self._reset()

    def _reset(self):
        self.portfolio_value  = self.bc.initial_capital
        self.equity_curve_d   = {}          # date → portfolio value
        self.open_trade: Optional[Trade] = None
        self.closed_trades: List[Trade]  = []

    # ── Public API ────────────────────────────────────────────────────────────
    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        warmup_bars: int = 220,
        verbose: bool = True,
    ) -> Tuple[pd.Series, pd.DataFrame, dict]:
        """
        Run a full backtest on df.

        Args:
            df:           DataFrame with OHLCV + indicators (from data.ingestion)
            symbol:       Ticker name for logging
            warmup_bars:  Skip first N bars for indicator warmup
            verbose:      Print progress

        Returns:
            (equity_curve, trades_df, metrics_dict)
        """
        from signals.aggregator import SignalAggregator

        self._reset()
        aggregator = SignalAggregator(self.cfg)

        if verbose:
            print(f"\n{'─'*55}")
            print(f"  Backtesting {symbol} | {len(df)} bars | Capital: ${self.bc.initial_capital:,.0f}")
            print(f"{'─'*55}")

        # Pre-train AI model once on warmup data (no lookahead bias)
        # This avoids re-fitting on every bar which is slow and inconsistent
        if "ai_model" in aggregator._strategies:
            warmup_df = df.iloc[:warmup_bars]
            try:
                m = aggregator._strategies["ai_model"].fit(warmup_df)
                if verbose:
                    print(f"  AI pre-trained | Accuracy: {m.get('accuracy',0):.1%} | AUC: {m.get('auc_roc',0):.3f}")
            except Exception as e:
                if verbose:
                    print(f"  AI pre-training skipped: {e}")

        for i in range(warmup_bars, len(df)):
            bar    = df.iloc[:i + 1]
            date   = str(df.index[i])
            high   = float(df["High"].iloc[i])
            low    = float(df["Low"].iloc[i])
            close  = float(df["Close"].iloc[i])

            # ── Check SL / TP on open trade ──────────────────────────
            if self.open_trade:
                ot = self.open_trade
                closed = False

                if ot.direction == "long":
                    if low <= ot.stop_loss:
                        self._close_trade(ot, date, ot.stop_loss, "sl")
                        closed = True
                    elif high >= ot.take_profit:
                        self._close_trade(ot, date, ot.take_profit, "tp")
                        closed = True
                else:   # short
                    if high >= ot.stop_loss:
                        self._close_trade(ot, date, ot.stop_loss, "sl")
                        closed = True
                    elif low <= ot.take_profit:
                        self._close_trade(ot, date, ot.take_profit, "tp")
                        closed = True

                if not closed:
                    # Mark-to-market
                    self._update_equity(date, close, ot)

            # ── Generate signal ───────────────────────────────────────
            try:
                rec = aggregator.analyse(bar, symbol)
            except Exception as e:
                self.equity_curve_d[date] = self.portfolio_value
                continue

            # ── Enter new trade if no open position ──────────────────
            if self.open_trade is None and rec.signal in ("BUY", "SELL"):
                self._open_trade(rec, date)

            # ── Signal flip — close existing trade ───────────────────
            elif self.open_trade is not None:
                ot = self.open_trade
                if (ot.direction == "long" and rec.signal == "SELL") or \
                   (ot.direction == "short" and rec.signal == "BUY"):
                    self._close_trade(ot, date, close, "signal_flip")

            self.equity_curve_d[date] = self.portfolio_value

        # ── Close any open trade at end ───────────────────────────────
        if self.open_trade:
            last_date  = str(df.index[-1])
            last_close = float(df["Close"].iloc[-1])
            self._close_trade(self.open_trade, last_date, last_close, "end")

        # ── Assemble results ──────────────────────────────────────────
        equity_series = pd.Series(self.equity_curve_d)
        equity_series.index = pd.to_datetime(equity_series.index)
        equity_series = equity_series.sort_index()

        trades_df = pd.DataFrame([vars(t) for t in self.closed_trades]) \
            if self.closed_trades else pd.DataFrame()

        metrics = compute_metrics(equity_series, trades_df)

        if verbose:
            print_metrics(metrics, title=f"Backtest Results — {symbol}")

        return equity_series, trades_df, metrics

    # ── Internal ──────────────────────────────────────────────────────────────
    def _open_trade(self, rec, date: str):
        direction  = "long" if rec.signal == "BUY" else "short"
        fill_price = self._apply_slippage(rec.entry_price, direction)
        commission = fill_price * rec.position_size_pct / 100 * self.portfolio_value * self.bc.commission_pct

        notional = self.portfolio_value * rec.position_size_pct / 100
        self.open_trade = Trade(
            symbol      = rec.symbol,
            direction   = direction,
            entry_date  = date,
            entry_price = fill_price,
            stop_loss   = rec.stop_loss,
            take_profit = rec.take_profit,
            size_pct    = rec.position_size_pct,
        )
        self.open_trade._notional = notional   # snapshot at entry
        self.portfolio_value -= commission

    def _close_trade(self, trade: Trade, date: str, price: float, reason: str):
        fill_price   = self._apply_slippage(price, trade.direction, closing=True)
        commission   = fill_price * trade.size_pct / 100 * self.portfolio_value * self.bc.commission_pct

        # Use notional snapshotted at entry time for accurate PnL
        entry_notional = getattr(trade, "_notional", self.portfolio_value * trade.size_pct / 100)
        if trade.direction == "long":
            trade.pnl_pct = (fill_price - trade.entry_price) / trade.entry_price
        else:
            trade.pnl_pct = (trade.entry_price - fill_price) / trade.entry_price
        trade.pnl_dollar  = entry_notional * trade.pnl_pct
        trade.exit_date   = date
        trade.exit_price  = fill_price
        trade.exit_reason = reason
        self.portfolio_value += trade.pnl_dollar - commission
        self.portfolio_value  = max(self.portfolio_value, 0.01)

        self.closed_trades.append(trade)
        self.open_trade       = None
        self.equity_curve_d[date] = self.portfolio_value

    def _update_equity(self, date: str, close: float, trade: Trade):
        if trade.direction == "long":
            pnl_pct = (close - trade.entry_price) / trade.entry_price
        else:
            pnl_pct = (trade.entry_price - close) / trade.entry_price
        # Mark-to-market: portfolio cash + unrealized position value
        notional = self.portfolio_value * trade.size_pct / 100
        self.equity_curve_d[date] = self.portfolio_value + notional * pnl_pct

    def _apply_slippage(self, price: float, direction: str, closing: bool = False) -> float:
        slip = self.bc.slippage_pct
        if direction == "long":
            return price * (1 + slip) if not closing else price * (1 - slip)
        else:
            return price * (1 - slip) if not closing else price * (1 + slip)
