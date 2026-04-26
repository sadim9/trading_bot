# 🤖 Quantitative Trading Bot

> **Analysis only — no real trades are ever executed.**

A modular, production-ready algorithmic trading signal engine combining four independent strategy agents with weighted signal aggregation, risk management, walk-forward backtesting, and a Streamlit dashboard.

---

## 🏗️ Architecture

```
trading_bot/
├── main.py                  ← CLI entry point
├── config.py                ← All parameters (single source of truth)
├── requirements.txt
├── data/
│   └── ingestion.py         ← Yahoo Finance / CSV / synthetic data
├── strategies/
│   ├── base.py              ← Abstract base class
│   ├── trend.py             ← EMA 50/200 crossover + MACD  (30%)
│   ├── mean_reversion.py    ← RSI + Bollinger Bands         (25%)
│   ├── momentum.py          ← Breakout + Volume spike        (25%)
│   └── ai_model.py          ← Gradient Boosting classifier  (20%)
├── signals/
│   └── aggregator.py        ← Weighted multi-strategy fusion
├── risk/
│   └── manager.py           ← Stop-loss, TP, Kelly sizing
├── backtest/
│   └── engine.py            ← Walk-forward historical sim
├── analytics/
│   └── metrics.py           ← Sharpe, Sortino, MDD, Win Rate…
├── dashboard/
│   └── app.py               ← Streamlit interactive UI
├── utils/
│   └── logger.py            ← CSV + JSON trade/signal logger
└── logs/                    ← Auto-created at runtime
```

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Generate a live signal (no internet required)

```bash
# Use synthetic sample data
python main.py --symbol SAMPLE --source sample

# Real data via Yahoo Finance
python main.py --symbol AAPL

# Crypto
python main.py --symbol BTC-USD --interval 1h --period 1y
```

### 3. Run a backtest

```bash
# Single symbol
python main.py --mode backtest --symbol AAPL

# Multi-symbol comparison
python main.py --mode backtest --symbols AAPL GOOGL AMZN MSFT

# Disable AI agent for speed
python main.py --mode backtest --symbol AAPL --no-ai
```

### 4. Launch the Streamlit dashboard

```bash
streamlit run dashboard/app.py
```

---

## 📊 Strategy Logic

### Signal Scoring

Each strategy returns a score ∈ [-1.0, +1.0]:
- **+1.0** = maximum bullish conviction
- **-1.0** = maximum bearish conviction
- **0.0**  = neutral

### Weighted Aggregation

```
Composite = Trend×0.30 + Momentum×0.25 + MeanRev×0.25 + AI×0.20
```

| Score Range | Decision |
|---|---|
| ≥ 0.60 | **BUY** |
| ≤ 0.40 | **SELL** |
| 0.40–0.60 | **HOLD** |

### Strategy Details

#### 1. Trend Strategy (30%)
- **EMA50/200 crossover**: Golden Cross (+0.65), Death Cross (-0.65)
- **MACD**: Line vs signal, histogram momentum confirmation
- Fresh crossovers get a bonus score

#### 2. Mean Reversion Strategy (25%)
- **RSI**: Oversold <30 (+0.70), extremely <25 (+1.0); Overbought >70 (-0.70)
- **Bollinger Bands**: BB% position (0=lower band, 1=upper band)
- **Divergence detection**: Price/RSI divergence over 10-bar window

#### 3. Momentum Strategy (25%)
- **Breakout**: Close above N-bar rolling high/low
- **Volume spike**: Volume > 2× 20-bar average confirms breakout
- **Multi-timeframe momentum**: 1d, 5d, 20d returns via tanh squashing

#### 4. AI Model Strategy (20%)
- **Model**: Gradient Boosting Classifier (CalibratedClassifierCV)
- **Features**: RSI, MACD, BB%, EMA cross, returns, volatility, volume ratio + 3 lags each
- **Task**: P(next bar close > current close)
- **Split**: 75% train / 25% test (walk-forward, no lookahead bias)
- **Output**: Probability → mapped to [-1, +1] score

---

## 🛡️ Risk Management

- **Stop-Loss**: Default 2% (configurable)
- **Take-Profit**: Default 4% (2:1 R:R)
- **Position Sizing**: Fractional Kelly (0.25× Kelly) or fixed %
- **R:R Gate**: Trade rejected if R:R < 1.5:1 (TP auto-adjusted)
- **Volatility Gate**: Size halved during extreme volatility (>2× avg)
- **Max Open Positions**: 5 (configurable)

---

## 📈 Backtest Metrics

| Metric | Description |
|---|---|
| Total Return % | Absolute portfolio gain |
| CAGR % | Annualised compound growth |
| Sharpe Ratio | Risk-adjusted return (annualised, rf=5%) |
| Sortino Ratio | Downside-risk adjusted return |
| Max Drawdown % | Worst peak-to-trough decline |
| Calmar Ratio | CAGR / Max Drawdown |
| Win Rate % | % of trades closed in profit |
| Profit Factor | Gross profit / Gross loss |
| Expectancy % | Expected return per trade |

---

## ⚙️ Configuration

All parameters live in `config.py`. Key settings:

```python
CONFIG.strategy.ema_fast = 50        # Fast EMA period
CONFIG.strategy.ema_slow = 200       # Slow EMA period
CONFIG.strategy.rsi_overbought = 70  # RSI sell threshold
CONFIG.strategy.rsi_oversold = 30    # RSI buy threshold
CONFIG.risk.stop_loss_pct = 0.02     # 2% stop-loss
CONFIG.risk.take_profit_pct = 0.04   # 4% take-profit
CONFIG.risk.sizing_method = "kelly"  # kelly | fixed
CONFIG.signal.buy_threshold = 0.60   # Score threshold for BUY
CONFIG.signal.sell_threshold = 0.40  # Score threshold for SELL
```

---

## 🔌 Extending the Bot

### Add a new strategy

```python
# strategies/my_strategy.py
from strategies.base import BaseStrategy, StrategyResult

class MyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("My Custom Strategy")

    def score(self, df) -> StrategyResult:
        # Your logic here
        return StrategyResult(score=0.5, signal="BUY",
                              reasons=["Reason 1"], strategy_name=self.name)
```

Then register it in `signals/aggregator.py`.

### Connect to live data

Replace `fetch_yahoo()` in `data/ingestion.py` with your broker's API.
The rest of the pipeline is unchanged.

---

## ⚠️ Disclaimer

This software is for educational and research purposes only.  
**It does not constitute financial advice.**  
Past backtest performance does not guarantee future results.  
Always conduct your own due diligence before trading.
