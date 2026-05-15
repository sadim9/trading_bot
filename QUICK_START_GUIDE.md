# Quick Start Guide: M5 SuperTrend EMA RSI Strategy

## 1️⃣ SETUP IN 5 MINUTES

### Step 1: Copy the Code
- Open the file: `trading_strategy_m5_advanced.pine`
- Select all (Ctrl+A) and copy

### Step 2: Add to TradingView
1. Go to **TradingView.com** → Open a chart
2. Click **Pine Editor** (bottom right panel)
3. Click **New** → Paste code → **Save**
4. Click **Add to Chart**

### Step 3: Configure Inputs
1. Right-click chart → **Settings** (or click the gear icon)
2. Click **Inputs** tab
3. Adjust settings below (or use defaults to start)

### Step 4: Run Backtest
1. In Pine Editor, click **Strategy Tester** (bottom panel)
2. Select date range: 2023-01-01 to today
3. Click **Run** and wait 30–60 seconds
4. Review **Net Profit**, **Win Rate**, **Max Drawdown**

### Step 5: Paper Trade
1. Set chart to **demo account**
2. Let it run for 2–4 weeks live
3. Document every trade in a spreadsheet
4. Only go live if win rate >50% and profits accumulate

---

## 🎯 DEFAULT INPUTS (COPY & PASTE FOR QUICK START)

```
SESSION SETTINGS:
  Enable London Session: ON
  Enable NY Session: ON
  
SUPERTREND:
  Period: 10
  Multiplier: 3.0
  
EMA SETTINGS:
  EMA 200 Length: 200
  EMA 50 Length: 50
  
PULLBACK DETECTION:
  Mode: percent
  Pullback %: 0.5
  Max Distance from EMA 50: 2.0
  
RSI SETTINGS:
  Period: 14
  RSI Long Threshold: 50
  RSI Short Threshold: 50
  
STOP LOSS:
  Mode: swing
  Swing Lookback: 20
  Fixed SL Pips: 12
  Pip Size: 0.0001 (EURUSD) or 0.01 (GOLD)
  
TAKE PROFIT:
  Mode: fixed_rr
  Risk-Reward Ratio: 2.0 (1:2)
  
POSITION SIZING:
  Mode: risk_percent
  Risk per Trade: 2% of equity
  
TRADE LIMITS:
  Max Concurrent: 1
  Max Daily: 5
  One Direction Only: ON
  
VOLATILITY FILTERS:
  Enable ATR Filter: ON
  ATR Period: 14
  ATR Threshold: 0.0015
  Enable Market Structure: ON
  
BACKTEST:
  Commission: 0.001%
  Slippage: 0.5 pips
  Debug Mode: OFF
```

---

## ⚙️ QUICK PARAMETER TUNING

### For More Entry Signals (Aggressive):
```
SuperTrend Period: 7 (was 10)
Pullback %: 1.0 (was 0.5)
Max Distance: 3.0 (was 2.0)
Risk per Trade: 3% (was 2%)
```

### For Fewer, Higher-Quality Signals (Conservative):
```
SuperTrend Period: 15 (was 10)
Pullback %: 0.3 (was 0.5)
Max Distance: 1.5 (was 2.0)
Risk per Trade: 1% (was 2%)
Enable Market Structure: ON
Enable ATR Filter: ON
```

### For Gold (XAUUSD):
```
Pip Size: 0.01 (not 0.0001)
Fixed SL Pips: 15
SuperTrend Period: 12
Pullback %: 1.0
Risk-Reward: 2.5 (higher vol = higher RR)
```

### For Crypto (BTCUSD):
```
SuperTrend Period: 8 (faster trends)
SuperTrend Multiplier: 2.5 (tighter bands)
EMA 50: 30 (faster pullbacks)
Pullback %: 0.8
Risk-Reward: 3.0 (high vol = wider stops)
```

---

## 📊 INTERPRETING BACKTEST RESULTS

After running the backtest, you'll see:

### Green Zone (Strategy is Working):
- **Win Rate:** 55–75% ✅
- **Profit Factor:** >1.5 ✅
- **Max Drawdown:** <20% of initial capital ✅
- **Expectancy:** Positive (>$0 per trade) ✅

### Caution Zone (Review Parameters):
- **Win Rate:** 45–55% ⚠️ (marginal)
- **Profit Factor:** 1.0–1.5 ⚠️ (weak)
- **Max Drawdown:** 20–40% ⚠️ (risky)

### Red Zone (Strategy Needs Rework):
- **Win Rate:** <45% ❌
- **Profit Factor:** <1.0 ❌
- **Consecutive Losses:** >10 in a row ❌

---

## 🚨 MOST COMMON MISTAKES

| Mistake | Fix |
|---------|-----|
| No entry signals | Verify you're in trading hours (London 08:00-16:00 or NY 13:00-21:00 UTC) |
| Too many losses | Increase SuperTrend Period (10→12→15) or decrease pullback % (0.5→0.3) |
| Stops hit too quickly | Switch to swing SL mode; ensure swing lookback is 20+ |
| Missing big moves | Reduce pullback % to catch entries closer to price |
| Position size = 0 | Check pip size matches symbol (EURUSD=0.0001, GOLD=0.01) |
| Alerts not working | Click "Create Alert" in Pine Editor bottom panel for each condition |

---

## 💰 POSITION SIZING QUICK CALCULATOR

**If risk per trade = 2%, SL distance = 20 pips, account = $10,000:**

For EURUSD (0.0001 pip size):
- Risk = $10,000 × 2% = $200
- Pip value = $200 ÷ 20 pips = $10 per pip
- **Position size = 0.1 micro lots (10,000 units)**

For XAUUSD (0.01 pip size):
- Risk = $200
- Pip value = $200 ÷ 20 = $10 per pip
- **Position size = 1 micro contract**

---

## 📱 ALERTS SETUP

Once strategy is added to chart:

1. Click the **🔔 Alert Icon** (top right of chart)
2. Select your strategy from the dropdown
3. Choose which condition to alert on:
   - 🟢 Long Entry
   - 🔴 Short Entry
   - ⚡ SuperTrend Bullish Flip
   - ⚡ SuperTrend Bearish Flip
4. Set notification: Email, Mobile Push, or Browser Popup
5. Click **Create Alert**

Recommend alerting on:
- Long Entry / Short Entry (for manual confirmation)
- Stop Loss Hit / Take Profit Hit (for trade management)

---

## 📈 FIRST 100 TRADES BENCHMARK

| Metric | Target | Your Result |
|--------|--------|-------------|
| Total Trades | 20–50 | _____ |
| Win Rate | >50% | ___% |
| Largest Win | + | $_____ |
| Largest Loss | - | -$_____ |
| Avg Win / Avg Loss Ratio | >1.5 | _____ |
| Max Consecutive Losses | <10 | _____ |
| Total Profit | +$200–500 | $_____ |
| Worst Drawdown | <$2,000 | -$_____ |

**If all ✅, move to small real account (0.01 contracts max).** If ❌, adjust parameters and retry.

---

## 🔄 WEEKLY REVIEW ROUTINE

Every **Monday morning:**
1. Check past week's backtest results (run fresh backtest)
2. Log all trades: entry price, exit price, P&L, reason
3. Calculate win rate: (wins / total trades) × 100
4. If win rate <50%: **Pause live trading** and adjust inputs
5. If win rate >60%: **Document settings**, scale up slightly (0.1→0.2 contracts)
6. Note which session (London/NY) had better results

---

## ✅ CHECKLIST BEFORE GOING LIVE

```
Backtest:
☐ 2+ years of data tested
☐ Win rate >50%
☐ Profit factor >1.5
☐ Consecutive losses <10

Paper Trading:
☐ Run for 4–6 weeks
☐ Win rate >50% in live market
☐ Slippage reasonable (<1 pip average)
☐ Alerts firing correctly

Account:
☐ Minimum $1,000 balance
☐ Leverage ≤ 1:50
☐ Demo account fully tested first

Documentation:
☐ Strategy parameters saved to .txt
☐ Trade journal template created
☐ Risk management rules documented
☐ Mentor/experienced trader briefed

Go Live (Small):
☐ Start with 0.01 contracts (0.1% risk)
☐ Set maximum daily loss alert (-$50 on $10k account)
☐ Monitor first trade manually
☐ Only scale up after 2–4 weeks of consistent profit
```

---

## 🆘 TROUBLESHOOTING IN 60 SECONDS

**Problem:** Strategy isn't showing any entries

**Solution:**
1. Right-click chart → Settings → Inputs
2. Set `Enable London Session: ON` and `Enable NY Session: ON`
3. Check if current bar time is within trading hours (08:00-21:00 UTC)
4. If before 08:00 UTC, wait until London opens
5. If backtest: ensure date range includes London/NY hours for that symbol

---

**Problem:** Win rate is below 50%

**Solution:**
1. Increase `SuperTrend Period` from 10 to 12–15
2. Decrease `Pullback %` from 0.5 to 0.3
3. Enable `Market Structure Filter`
4. Re-run backtest
5. If still <50%, symbol may not suit this strategy—try another

---

**Problem:** Position size is 0 or very small

**Solution:**
1. Verify `Risk per Trade` is set to 1% minimum
2. Check `Pip Size` matches your symbol:
   - EURUSD, GBPUSD: 0.0001
   - GOLD (XAUUSD): 0.01
   - Bitcoin (BTCUSD): 1.0
3. Ensure account balance >$1,000 to avoid rounding errors

---

## 📞 NEXT STEPS

1. **Read Full Docs:** Open `STRATEGY_DOCUMENTATION.md` for deep dive
2. **Backtest:** Run on your target symbol for 2+ years
3. **Paper Trade:** 4–6 weeks on demo before real money
4. **Join Community:** TradingView Pine Script forums for tips
5. **Track Results:** Use the trade journal template to log every trade

---

**Good luck, and always remember: Small account, small position size, and consistent entries = the path to consistent profits.**

*This is educational material. Not financial advice. Always use stops and risk management.*
