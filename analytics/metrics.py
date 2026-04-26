"""
analytics/metrics.py — Performance Analytics

Computes all standard quantitative trading metrics:
  - Sharpe Ratio (annualised)
  - Sortino Ratio
  - Max Drawdown
  - Win Rate
  - Profit Factor
  - Calmar Ratio
  - CAGR
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def compute_metrics(
    equity_curve: pd.Series,
    trades: pd.DataFrame,
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
) -> Dict[str, float]:
    """
    Compute comprehensive performance metrics from equity curve and trade log.

    Args:
        equity_curve:     Series of portfolio values indexed by date
        trades:           DataFrame with columns: entry_price, exit_price,
                          direction ('long'/'short'), entry_date, exit_date
        risk_free_rate:   Annual risk-free rate (default 5%)
        periods_per_year: 252 for daily, 52 for weekly, 12 for monthly

    Returns:
        Dict of metric names → float values
    """
    metrics: Dict[str, float] = {}

    # ── Returns ───────────────────────────────────────────────────────────────
    returns = equity_curve.pct_change().dropna()

    if len(returns) < 2:
        return {"error": "Insufficient data for metrics"}

    # ── CAGR ─────────────────────────────────────────────────────────────────
    n_years = len(equity_curve) / periods_per_year
    if n_years > 0 and equity_curve.iloc[0] > 0:
        cagr = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / n_years) - 1
    else:
        cagr = 0.0
    metrics["cagr_pct"] = round(cagr * 100, 2)
    metrics["total_return_pct"] = round(
        (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100, 2
    )

    # ── Sharpe Ratio ──────────────────────────────────────────────────────────
    excess    = returns - risk_free_rate / periods_per_year
    mean_exc  = excess.mean()
    std_ret   = returns.std()
    sharpe    = (mean_exc / std_ret * np.sqrt(periods_per_year)) if std_ret > 0 else 0.0
    metrics["sharpe_ratio"] = round(sharpe, 3)

    # ── Sortino Ratio ─────────────────────────────────────────────────────────
    downside_returns = returns[returns < 0]
    downside_std     = downside_returns.std()
    sortino = (
        mean_exc / downside_std * np.sqrt(periods_per_year)
        if downside_std > 0 else 0.0
    )
    metrics["sortino_ratio"] = round(sortino, 3)

    # ── Max Drawdown ─────────────────────────────────────────────────────────
    rolling_max  = equity_curve.cummax()
    drawdown     = (equity_curve - rolling_max) / rolling_max
    max_dd       = drawdown.min()
    metrics["max_drawdown_pct"] = round(max_dd * 100, 2)

    # Drawdown duration
    in_dd        = drawdown < -0.01
    dd_starts    = in_dd & ~in_dd.shift(fill_value=False)
    metrics["max_dd_duration_days"] = int(in_dd.sum())

    # ── Calmar Ratio ──────────────────────────────────────────────────────────
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0
    metrics["calmar_ratio"] = round(calmar, 3)

    # ── Volatility ────────────────────────────────────────────────────────────
    metrics["annual_volatility_pct"] = round(std_ret * np.sqrt(periods_per_year) * 100, 2)
    metrics["daily_var_95_pct"]      = round(float(np.percentile(returns, 5)) * 100, 3)

    # ── Trade-Level Metrics ────────────────────────────────────────────────────
    if trades is not None and not trades.empty and "pnl_pct" in trades.columns:
        pnl = trades["pnl_pct"].dropna()

        wins   = pnl[pnl > 0]
        losses = pnl[pnl <= 0]

        metrics["total_trades"]    = len(pnl)
        metrics["win_rate_pct"]    = round(len(wins) / len(pnl) * 100, 2) if len(pnl) > 0 else 0.0
        metrics["avg_win_pct"]     = round(wins.mean() * 100, 3)    if len(wins)   > 0 else 0.0
        metrics["avg_loss_pct"]    = round(losses.mean() * 100, 3)  if len(losses) > 0 else 0.0
        metrics["avg_trade_pct"]   = round(pnl.mean() * 100, 3)

        gross_profit = wins.sum()
        gross_loss   = abs(losses.sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
        metrics["profit_factor"]   = round(profit_factor, 3)

        # Expectancy = (WinRate × AvgWin) − (LossRate × AvgLoss)
        win_rate  = len(wins) / len(pnl) if len(pnl) > 0 else 0
        loss_rate = 1 - win_rate
        expectancy = (win_rate * wins.mean()) - (loss_rate * abs(losses.mean())) if len(losses) > 0 else 0
        metrics["expectancy_pct"]  = round(expectancy * 100, 3)

        # Consecutive wins / losses
        if len(pnl) > 0:
            win_streak = loss_streak = cur = 0
            for p in pnl:
                if p > 0:
                    cur = max(cur + 1, 1)
                    win_streak = max(win_streak, cur)
                else:
                    cur = min(cur - 1, -1)
                    loss_streak = max(loss_streak, -cur)
            metrics["max_win_streak"]  = win_streak
            metrics["max_loss_streak"] = loss_streak

    return metrics


def print_metrics(metrics: Dict[str, float], title: str = "Performance Report"):
    """Pretty-print the metrics dictionary."""
    lines = [
        f"\n{'═'*55}",
        f"  {title}",
        f"{'═'*55}",
        f"  {'RETURNS':─<45}",
        f"  Total Return      : {metrics.get('total_return_pct', 0):>8.2f}%",
        f"  CAGR              : {metrics.get('cagr_pct', 0):>8.2f}%",
        f"  Annual Volatility : {metrics.get('annual_volatility_pct', 0):>8.2f}%",
        f"  {'RISK METRICS':─<45}",
        f"  Sharpe Ratio      : {metrics.get('sharpe_ratio', 0):>8.3f}",
        f"  Sortino Ratio     : {metrics.get('sortino_ratio', 0):>8.3f}",
        f"  Calmar Ratio      : {metrics.get('calmar_ratio', 0):>8.3f}",
        f"  Max Drawdown      : {metrics.get('max_drawdown_pct', 0):>8.2f}%",
        f"  Daily VaR (95%)   : {metrics.get('daily_var_95_pct', 0):>8.3f}%",
        f"  {'TRADE STATISTICS':─<45}",
        f"  Total Trades      : {metrics.get('total_trades', 0):>8}",
        f"  Win Rate          : {metrics.get('win_rate_pct', 0):>8.2f}%",
        f"  Avg Win           : {metrics.get('avg_win_pct', 0):>8.3f}%",
        f"  Avg Loss          : {metrics.get('avg_loss_pct', 0):>8.3f}%",
        f"  Avg Trade         : {metrics.get('avg_trade_pct', 0):>8.3f}%",
        f"  Profit Factor     : {metrics.get('profit_factor', 0):>8.3f}",
        f"  Expectancy        : {metrics.get('expectancy_pct', 0):>8.3f}%",
        f"  Max Win Streak    : {metrics.get('max_win_streak', 0):>8}",
        f"  Max Loss Streak   : {metrics.get('max_loss_streak', 0):>8}",
        f"{'═'*55}\n",
    ]
    print("\n".join(lines))


def equity_curve_stats(equity_curve: pd.Series) -> pd.DataFrame:
    """Return a DataFrame with monthly returns for display."""
    monthly = equity_curve.resample("ME").last().pct_change().dropna()
    monthly.name = "monthly_return"
    return monthly.to_frame()
