"""
config.py -- Central configuration for the Trading Bot.
All parameters are tunable here without touching strategy code.
"""

from dataclasses import dataclass, field
from typing import List, Optional


# --- DATA SETTINGS -----------------------------------------------------------
@dataclass
class DataConfig:
    default_symbols: List[str] = field(
        default_factory=lambda: ["AAPL", "GOOGL", "AMZN", "MSFT", "BTC-USD"]
    )
    default_interval: str = "1h"         # 1m, 5m, 15m, 1h, 1d
    default_period: str = "2y"           # lookback for backtest / indicator warmup
    data_source: str = "kraken"          # yfinance | kraken | kucoin | binance | ...

    # UI defaults: shown on first load in the dashboard
    # Change these to set your preferred trading pair and data source.
    ui_default_symbol: str = "XBTUSD"   # default ticker shown in the toolbar
    ui_default_source: str = "kraken"   # default data source in the toolbar
    ui_default_interval: str = "1h"     # default bar interval
    ui_default_period: str = "6mo"      # default lookback period

    cache_dir: str = "data/cache"

    # Third-party API keys (free tiers)
    # Twelve Data -- free tier: 800 credits/day. Sign up at twelvedata.com
    # Required for spot commodity prices (XAUUSD, XAGUSD, WTI/USD, BRENT/USD)
    # Leave blank to fall back to yfinance futures (GC=F, SI=F, CL=F, BZ=F)
    twelvedata_api_key: str = ""


# --- STRATEGY WEIGHTS --------------------------------------------------------
@dataclass
class WeightConfig:
    trend: float          = 0.30   # EMA crossover + MACD
    momentum: float       = 0.25   # Breakout + volume spike
    mean_reversion: float = 0.25   # RSI + Bollinger Bands
    ai_model: float       = 0.20   # ML probability score
    markov: float         = 0.00   # Markov Chains (0 = disabled in multi-mode)

    def validate(self):
        """Weights must sum to 1.0 (markov excluded -- it's an overlay)."""
        core = self.trend + self.momentum + self.mean_reversion + self.ai_model
        if abs(core - 1.0) >= 1e-6:
            raise ValueError(
                f"Core strategy weights must sum to 1.0, got {core:.4f}. "
                f"Adjust trend/momentum/mean_reversion/ai_model."
            )


# --- STRATEGY TOGGLES --------------------------------------------------------
@dataclass
class StrategyConfig:
    use_trend: bool          = True
    use_momentum: bool       = True
    use_mean_reversion: bool = True
    use_ai_model: bool       = True
    use_markov: bool         = False   # enable Markov Chains strategy

    # Trend parameters
    ema_fast: int   = 50
    ema_slow: int   = 200
    macd_fast: int  = 12
    macd_slow: int  = 26
    macd_signal: int = 9

    # Mean reversion parameters
    rsi_period: int          = 14
    rsi_overbought: float    = 70.0
    rsi_oversold: float      = 30.0
    bb_period: int           = 20
    bb_std: float            = 2.0

    # Momentum parameters
    breakout_lookback: int   = 20    # bars to define support/resistance
    volume_spike_mult: float = 2.0   # multiple of avg volume for spike

    # AI model parameters
    ai_lookback_features: int = 10   # rolling window for feature engineering
    ai_train_size: float      = 0.75 # fraction of data used for training
    ai_n_estimators: int      = 200

    # Markov Chains parameters
    # Enhanced framework: core conditions + regime detection + n-step forecasting
    markov_n_states: int          = 8      # discrete price states (N×N matrix)
    markov_tau: float             = 0.87   # state persistence threshold — eq.(2.3)
    markov_eps: float             = 0.05   # arbitrage gap threshold ε — eq.(2.2)
    markov_lookback: int          = 200    # bars used to build the transition matrix
    markov_n_step: int            = 3      # n-step ahead forecast horizon (P^n)
    markov_n_step_weight: float   = 0.35   # blend weight for n-step vs 1-step
    markov_regime_bull: float     = 0.55   # π(upper half) > this → BULL regime
    markov_regime_bear: float     = 0.55   # π(lower half) > this → BEAR regime


# --- SIGNAL THRESHOLDS -------------------------------------------------------
@dataclass
class SignalConfig:
    # Thresholds operate on raw composite score in [-1.0, +1.0]
    # 0.0 = perfectly neutral, +/-1.0 = max conviction
    buy_threshold: float  =  0.20   # composite > +0.20 -> BUY
    sell_threshold: float = -0.20   # composite < -0.20 -> SELL
    # Between -0.20 and +0.20 -> HOLD (neutral zone)


# --- RISK MANAGEMENT ---------------------------------------------------------
@dataclass
class RiskConfig:
    stop_loss_pct: float     = 0.02         # 2% stop-loss
    take_profit_pct: float   = 0.04         # 4% take-profit (2:1 R/R)
    max_position_pct: float  = 0.10         # max 10% of portfolio per position
    sizing_method: str       = "kelly"      # kelly | fixed | volatility
    fixed_position_pct: float = 0.05        # used when sizing_method == "fixed"
    kelly_fraction: float    = 0.25         # fractional Kelly (conservative)
    max_open_positions: int  = 5


# --- BACKTESTING -------------------------------------------------------------
@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    commission_pct: float  = 0.001          # 0.1% per trade
    slippage_pct: float    = 0.0005         # 0.05% slippage


# --- LOGGING -----------------------------------------------------------------
@dataclass
class LogConfig:
    log_dir: str           = "logs"
    trade_log_file: str    = "logs/trades.csv"
    signal_log_file: str   = "logs/signals.json"
    log_level: str         = "INFO"


# --- MASTER CONFIG -----------------------------------------------------------
@dataclass
class BotConfig:
    data:     DataConfig     = field(default_factory=DataConfig)
    weights:  WeightConfig   = field(default_factory=WeightConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    signal:   SignalConfig   = field(default_factory=SignalConfig)
    risk:     RiskConfig     = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    log:      LogConfig      = field(default_factory=LogConfig)

    def __post_init__(self):
        self.weights.validate()


# Default singleton config
CONFIG = BotConfig()
CONFIG = BotConfig()
