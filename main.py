"""
main.py — Trading Bot CLI Entry Point

Usage:
    # Live signal for one symbol
    python main.py --symbol AAPL

    # Backtest on multiple symbols
    python main.py --mode backtest --symbols AAPL GOOGL AMZN

    # Use synthetic sample data (no internet required)
    python main.py --symbol SAMPLE --source sample

    # Custom config
    python main.py --symbol BTC-USD --interval 1h --period 1y

This script NEVER executes real trades.
"""

import argparse
import sys
import os
import warnings
warnings.filterwarnings("ignore")

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CONFIG
from data.ingestion import load_data
from signals.aggregator import SignalAggregator
from risk.manager import RiskManager
from backtest.engine import BacktestEngine
from utils.logger import TradeLogger, setup_logger
from analytics.metrics import print_metrics

log = setup_logger("main")


# ─── LIVE SIGNAL MODE ─────────────────────────────────────────────────────────
def run_live_signal(symbol: str, interval: str, period: str, source: str):
    """Generate a single trade recommendation for the given symbol."""
    log.info(f"Loading data for {symbol} ({interval}, {period}) from {source}...")

    try:
        df = load_data(symbol, interval=interval, period=period, source=source)
    except Exception as e:
        log.error(f"Failed to load data: {e}")
        sys.exit(1)

    log.info(f"Loaded {len(df)} bars | Last close: {df['Close'].iloc[-1]:.4f}")

    # ── Analyse ───────────────────────────────────────────────────────────────
    aggregator = SignalAggregator(CONFIG)

    log.info("Running strategy analysis...")
    rec = aggregator.analyse(df, symbol)

    # ── Risk validation ───────────────────────────────────────────────────────
    risk_mgr = RiskManager(CONFIG.risk)
    check    = risk_mgr.check(
        symbol=symbol,
        signal=rec.signal,
        entry=rec.entry_price,
        stop_loss=rec.stop_loss,
        take_profit=rec.take_profit,
        size_pct=rec.position_size_pct,
        df=df,
    )

    # ── Print recommendation ──────────────────────────────────────────────────
    print(rec)

    if check.reasons:
        print("  Risk Manager:")
        for r in check.reasons:
            print(f"    {r}")
        print()

    # ── Log signal ────────────────────────────────────────────────────────────
    logger = TradeLogger(CONFIG.log.trade_log_file, CONFIG.log.signal_log_file)
    logger.log_signal(rec.to_dict())
    log.info(f"Signal logged → {CONFIG.log.trade_log_file}")

    return rec


# ─── BACKTEST MODE ─────────────────────────────────────────────────────────────
def run_backtest(symbols: list, interval: str, period: str, source: str):
    """Backtest all strategies on one or more symbols and compare performance."""
    all_metrics = {}
    engine      = BacktestEngine(CONFIG)

    for symbol in symbols:
        log.info(f"\n{'═'*55}")
        log.info(f"  Backtesting {symbol}...")
        log.info(f"{'═'*55}")

        try:
            df = load_data(symbol, interval=interval, period=period, source=source)
        except Exception as e:
            log.error(f"Failed to load {symbol}: {e}")
            continue

        equity, trades_df, metrics = engine.run(df, symbol, verbose=True)
        all_metrics[symbol] = metrics

        if not trades_df.empty:
            winning = trades_df[trades_df["pnl_pct"] > 0]
            log.info(f"  Best trade : +{trades_df['pnl_pct'].max()*100:.2f}%")
            log.info(f"  Worst trade: {trades_df['pnl_pct'].min()*100:.2f}%")

    # ── Cross-symbol comparison ───────────────────────────────────────────────
    if len(all_metrics) > 1:
        print(f"\n{'═'*70}")
        print(f"  CROSS-SYMBOL COMPARISON")
        print(f"{'═'*70}")
        header = f"{'Symbol':12} {'Total%':>9} {'CAGR%':>8} {'Sharpe':>8} {'MaxDD%':>9} {'WinRate%':>10} {'PF':>7}"
        print(header)
        print("─" * 70)
        for sym, m in all_metrics.items():
            print(
                f"{sym:12} "
                f"{m.get('total_return_pct',0):>9.2f} "
                f"{m.get('cagr_pct',0):>8.2f} "
                f"{m.get('sharpe_ratio',0):>8.3f} "
                f"{m.get('max_drawdown_pct',0):>9.2f} "
                f"{m.get('win_rate_pct',0):>10.2f} "
                f"{m.get('profit_factor',0):>7.3f}"
            )
        print("═" * 70)

    return all_metrics


# ─── CLI ──────────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="Quantitative Trading Bot — Signal Generation & Backtesting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --symbol AAPL
  python main.py --mode backtest --symbols AAPL GOOGL AMZN
  python main.py --symbol SAMPLE --source sample
  python main.py --symbol BTC-USD --interval 1h --period 1y
        """
    )
    parser.add_argument("--mode",     choices=["signal", "backtest"], default="signal")
    parser.add_argument("--symbol",   default="AAPL",  help="Single ticker (signal mode)")
    parser.add_argument("--symbols",  nargs="+",       help="Multiple tickers (backtest mode)")
    parser.add_argument("--interval", default="1d",    help="Bar size: 1d, 1h, 15m, etc.")
    parser.add_argument("--period",   default="2y",    help="Lookback: 1y, 2y, 5y, etc.")
    parser.add_argument("--source",   default="yfinance", choices=["yfinance", "sample", "csv"])
    parser.add_argument("--no-ai",    action="store_true", help="Disable AI model agent")
    return parser.parse_args()


def main():
    args = parse_args()

    # Apply CLI overrides to config
    if args.no_ai:
        CONFIG.strategy.use_ai_model = False
        log.info("AI model agent disabled via --no-ai flag")

    print("\n" + "═"*60)
    print("  🤖 QUANTITATIVE TRADING BOT")
    print("  ⚠️  ANALYSIS ONLY — NO REAL TRADES EXECUTED")
    print("═"*60)

    if args.mode == "backtest":
        symbols = args.symbols or [args.symbol]
        run_backtest(symbols, args.interval, args.period, args.source)
    else:
        run_live_signal(args.symbol, args.interval, args.period, args.source)


if __name__ == "__main__":
    main()
