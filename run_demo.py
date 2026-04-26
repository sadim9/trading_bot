"""
run_demo.py — Self-contained offline demo (no internet required).

Runs the full bot pipeline on synthetic data:
  1. Generates 800-bar synthetic OHLCV dataset
  2. Runs all 4 strategy agents
  3. Produces an aggregated trade recommendation
  4. Executes a walk-forward backtest
  5. Prints full performance report

Usage:  python run_demo.py
"""
import sys, warnings
sys.path.insert(0, '.')
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd

print("\n" + "█"*62)
print("█  QUANTITATIVE TRADING BOT — OFFLINE DEMO              █")
print("█  ⚠  ANALYSIS ONLY — NO REAL TRADES EXECUTED           █")
print("█"*62)

# ── Generate realistic synthetic dataset ────────────────────────
print("\n[1/4] Generating synthetic market data (alternating regimes)...")
np.random.seed(2024)
n = 900
dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
price = 100.0
closes = [price]
for i in range(n - 1):
    # Regime: bull 200 bars → bear 150 bars → bull → sideways
    bar = i % 600
    if   bar < 200:  drift, vol = 0.0010, 0.012
    elif bar < 350:  drift, vol = -0.0007, 0.014
    elif bar < 530:  drift, vol = 0.0008, 0.011
    else:            drift, vol = 0.0001, 0.008
    # Volume spikes at regime transitions
    spike = 1.0
    if bar in (0, 200, 350, 530):
        spike = 4.0
    price = max(price * (1 + np.random.normal(drift, vol)), 1.0)
    closes.append(price)

closes = np.array(closes)
highs  = closes * (1 + np.abs(np.random.normal(0, 0.006, n)))
lows   = closes * (1 - np.abs(np.random.normal(0, 0.006, n)))
opens  = np.concatenate([[closes[0]], closes[:-1]])
vol_base = np.random.lognormal(13, 0.5, n)
regime_spikes = np.ones(n)
for chg in (0, 200, 350, 530):
    regime_spikes[chg:chg+10] = 4.0
vols = (vol_base * regime_spikes).astype(int)

df = pd.DataFrame({
    'Open': opens, 'High': highs, 'Low': lows,
    'Close': closes, 'Volume': vols, 'Symbol': 'DEMO'
}, index=dates)

from data.ingestion import add_technical_indicators
df = add_technical_indicators(df)
print(f"    ✅ {len(df)} bars loaded | "
      f"Price range: ${df['Close'].min():.2f} – ${df['Close'].max():.2f}")

# ── Live Signal ──────────────────────────────────────────────────
print("\n[2/4] Running strategy analysis on latest bar...")
from signals.aggregator import SignalAggregator
from risk.manager import RiskManager
from config import CONFIG
from utils.logger import TradeLogger

agg    = SignalAggregator(CONFIG)
rec    = agg.analyse(df, 'DEMO')
rm     = RiskManager(CONFIG.risk)
check  = rm.check('DEMO', rec.signal, rec.entry_price,
                  rec.stop_loss, rec.take_profit,
                  rec.position_size_pct, df)
print(rec)
print("  Risk Manager feedback:")
for r in check.reasons:
    print(f"    {r}")

# ── Backtest ─────────────────────────────────────────────────────
print("\n[3/4] Running walk-forward backtest...")
from backtest.engine import BacktestEngine
from analytics.metrics import print_metrics

engine = BacktestEngine(CONFIG)
equity, trades_df, metrics = engine.run(df, 'DEMO', verbose=True)

# ── Trade table ──────────────────────────────────────────────────
if not trades_df.empty:
    print("\n  Individual Trades:")
    print(f"  {'Dir':6} {'Entry':>9} {'Exit':>9} {'Reason':>12} {'PnL%':>8} {'PnL$':>10}")
    print("  " + "─"*58)
    for _, t in trades_df.iterrows():
        pnl_sign = "+" if t.pnl_pct >= 0 else ""
        print(f"  {t.direction:6} {t.entry_price:>9.2f} {t.exit_price:>9.2f} "
              f"{t.exit_reason:>12} {pnl_sign}{t.pnl_pct*100:>7.2f}% "
              f"{'+' if t.pnl_dollar>=0 else ''}{t.pnl_dollar:>9.2f}")

# ── Log signals ──────────────────────────────────────────────────
print("\n[4/4] Logging signal to disk...")
logger = TradeLogger()
logger.log_signal(rec.to_dict())
print(f"    ✅ Signal logged → logs/trades.csv  &  logs/signals.json")

print("\n" + "█"*62)
print("█  DEMO COMPLETE                                         █")
print("█  Launch dashboard: streamlit run dashboard/app.py     █")
print("█"*62 + "\n")
