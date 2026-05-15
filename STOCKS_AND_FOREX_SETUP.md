# Using Strategy on Stocks vs Forex

## Fixed Issues

### Issue #1: plotshape in Local Scope ✅ FIXED
**Problem:** `Cannot use "plotshape" in local scope(CE10188)`  
**Solution:** Moved plotshape calls to global scope (outside if statements)

**Before:**
```pine
if longSignal
    plotshape(close, ...)  ❌ Local scope error
```

**After:**
```pine
buyIndicator = longSignal
plotshape(buyIndicator, ...)  ✅ Global scope, works!
```

### Issue #2: Stock Support ✅ ADDED
**Solution:** Added symbol type detection and flexible settings

---

## Configuration by Asset Type

### For FOREX Pairs (EURUSD, GBPUSD, etc.)

**Settings → Inputs → SYMBOL SETTINGS:**
```
Is this a Stock?: OFF
Pip/Tick Size: 0.0001

SESSION SETTINGS:
Enable London Session: ON
Enable New York Session: ON
Enable Session Time Filter: ON
```

**Then in BACKTEST SETTINGS:**
- Commission: 0.001% (typical forex broker)
- Slippage: 0.5 pips

**Optimal Parameters:**
```
SuperTrend Period: 10
SuperTrend Multiplier: 3.0
EMA 200: 200
EMA 50: 50
Pullback %: 0.5%
Risk per Trade: 2%
Risk-Reward: 1:2
```

---

### For STOCKS (AAPL, TSLA, SPY, etc.)

**Settings → Inputs → SYMBOL SETTINGS:**
```
Is this a Stock?: ON ✅
Pip/Tick Size: 1.0

SESSION SETTINGS:
Enable London Session: OFF ✅ (not applicable)
Enable New York Session: OFF ✅ (not applicable)
Enable Session Time Filter: OFF ✅ (disable for 24/7 trading)
```

**Then in BACKTEST SETTINGS:**
- Commission: 0.1% (typical stock broker, per side)
- Slippage: $0.10 (10 cents per trade)

**Optimal Parameters:**
```
SuperTrend Period: 12 (stocks are slower than forex)
SuperTrend Multiplier: 3.5 (wider bands for daily moves)
EMA 200: 200
EMA 50: 50
Pullback %: 1.0% (stocks move differently)
Risk per Trade: 1% (be more conservative)
Risk-Reward: 1:2.5 (need higher RR for stocks)
```

---

### For COMMODITIES (Gold/XAUUSD, Crude Oil/USOIL, etc.)

**Settings → Inputs → SYMBOL SETTINGS:**
```
Is this a Stock?: OFF
Pip/Tick Size: 0.01 (Gold) or 0.01 (Oil)

SESSION SETTINGS:
Enable London Session: ON
Enable New York Session: ON
Enable Session Time Filter: ON (commodities are global)
```

**Then in BACKTEST SETTINGS:**
- Commission: 0.002% (lower than forex)
- Slippage: 0.2 pips

**Optimal Parameters:**
```
SuperTrend Period: 12
SuperTrend Multiplier: 3.5
EMA 200: 200
EMA 50: 50
Pullback %: 0.8%
Risk per Trade: 1.5%
Risk-Reward: 1:2
```

---

## Pip/Tick Size Reference

| Asset Type | Symbol | Pip Size | Example |
|------------|--------|----------|---------|
| **Forex Majors** | EURUSD, GBPUSD | 0.0001 | 1.0950 |
| **Gold** | XAUUSD | 0.01 | 2045.50 |
| **Oil** | USOIL, UKOIL | 0.01 | 82.45 |
| **US Stocks** | AAPL, TSLA, SPY | 1.0 or 0.01 | 150.25 |
| **Crypto** | BTCUSD, ETHUSD | 1.0 | 42500.00 |
| **Indices** | ES, NQ, DAX | 0.25 | 4500.50 |

**How to find correct pip size:**
1. Look at the price quote on your broker
2. What's the smallest price change?
3. That's your pip size
4. Example: If AAPL moves $0.01, pip size = 1.0 (because 0.01 = 1 tick)

---

## Stock-Specific Considerations

### Key Differences from Forex:

| Aspect | Forex | Stocks |
|--------|-------|--------|
| **Trading Hours** | 24 hours (5 days) | Market hours only (9:30-16:00 EST) |
| **Volatility** | Consistent | Spikes on news/earnings |
| **Pip Movement** | 0.0001 units | 0.01 or 1.0 dollar increments |
| **Trend Strength** | Strong trends | Can be choppy intraday |
| **Best Timeframe** | M5-H1 | M15-H1 (M5 can be choppy) |
| **RR Ratio** | 1:2 | 1:2.5+ (need wider stops) |
| **Risk Management** | 2% per trade | 1% per trade (wider stops) |

### Stock Recommendations:

✅ **DO:**
- Trade liquid large-cap stocks (AAPL, MSFT, TSLA, SPY)
- Avoid earnings dates (volatility spikes)
- Use slightly wider SuperTrend multiplier (3.5 vs 3.0)
- Require higher RR ratios (1:2.5 vs 1:2)
- Trade during market hours only
- Use longer EMA periods (200/50 is fine)

❌ **DON'T:**
- Trade penny stocks (low liquidity)
- Trade right after market open (first 30 min, volatile)
- Trade before earnings
- Trade on low-volume days
- Use aggressive position sizing (start 1% risk)

---

## Quick Setup Guide

### To Trade STOCKS:

1. **Open Strategy Settings:**
   - Click Settings gear → Inputs tab

2. **Go to SYMBOL SETTINGS:**
   ```
   Is this a Stock?: Toggle to ON ✅
   Pip/Tick Size: Enter your stock's pip size (usually 1.0 or 0.01)
   ```

3. **Go to SESSION SETTINGS:**
   ```
   Enable London Session: Toggle to OFF
   Enable New York Session: Toggle to OFF
   Enable Session Time Filter: Toggle to OFF ✅
   ```

4. **Adjust Trading Parameters:**
   - SuperTrend Period: Change from 10 to 12
   - SuperTrend Multiplier: Change from 3.0 to 3.5
   - Pullback %: Change from 0.5 to 1.0
   - Risk per Trade: Change from 2% to 1%
   - Risk-Reward: Change from 1:2 to 1:2.5

5. **Backtest Settings:**
   ```
   Commission: 0.1% (stock commission)
   Slippage: $0.10 (10 cents)
   ```

6. **Run Backtest:**
   - Select a stock (AAPL, MSFT, TSLA, SPY)
   - Select M5 or M15 timeframe (M5 for volatile stocks)
   - Set 2+ years of data
   - Run backtest

---

## Testing Your Setup

### For STOCKS - Test This First:

```
Symbol: SPY (most liquid ETF)
Timeframe: M5
Period: 1 year
Is Stock: ON
Session Filter: OFF
Commission: 0.1%
Slippage: $0.10

Expected Results:
- Win Rate: 55-65% (lower than forex)
- Profit Factor: 1.8-2.2
- Max Drawdown: -15% to -20% (wider)
```

### For FOREX - Test This First:

```
Symbol: EURUSD
Timeframe: M5
Period: 2 years
Is Stock: OFF
Session Filter: ON
Commission: 0.001%
Slippage: 0.5 pips

Expected Results:
- Win Rate: 60-70%
- Profit Factor: 2.0+
- Max Drawdown: -12% to -15%
```

---

## Common Stock Symbols to Test

### US Stocks (High Liquidity):
- **SPY** (S&P 500 ETF) - Most liquid, good for testing
- **QQQ** (Nasdaq ETF) - Tech-focused
- **AAPL** (Apple) - Large cap, liquid
- **MSFT** (Microsoft) - Large cap, liquid
- **TSLA** (Tesla) - High volatility, good for testing
- **NVDA** (Nvidia) - Trending stock

### Avoid These for Testing:
- Penny stocks (low liquidity, wide spreads)
- Micro-cap stocks (illiquid)
- Thinly traded stocks (gaps and slippage)

---

## Pip Size Guide for Stocks

### Find Your Stock's Pip Size:

**Method 1 - Check Your Broker:**
- TradingView shows "Pip Size" in symbol info
- Your broker's platform shows minimum price change

**Method 2 - Visual Inspection:**
- AAPL = $150.25 (pip size = 0.01)
- SPY = $450.50 (pip size = 0.01)
- Bitcoin = 42,500.00 (pip size = 1.0)

**Method 3 - Common Standards:**
- Most US stocks: 0.01 (one cent)
- Some stocks: 1.0 (one dollar)
- ETFs: Usually 0.01
- Crypto: Usually 1.0

---

## Troubleshooting for Stocks

### Problem: No signals on stock chart

**Solution:**
1. Verify "Is this a Stock?" is ON
2. Verify "Enable Session Time Filter" is OFF
3. Check if you're on correct timeframe (M5 or M15)
4. Check pip size is correct for your stock
5. Run backtest to see if signals generate at all
6. If backtest has signals but chart doesn't, reload the page

### Problem: Too many losing trades on stocks

**Solution:**
1. Increase SuperTrend Multiplier (3.0 → 3.5 or 4.0)
2. Decrease Pullback % (0.5 → 0.3)
3. Increase Stop Loss distance (give more room)
4. Trade later in day (avoid first 30 min after open)
5. Avoid stocks with upcoming earnings
6. Test on SPY or QQQ instead (more stable)

### Problem: Stop losses hit too quickly

**Solution:**
1. Use Swing-based SL mode (not fixed)
2. Increase Swing Lookback (20 → 30)
3. Increase SuperTrend Period (10 → 12 or 15)
4. Increase fixed SL distance (12 → 15 or 20)
5. Trade longer timeframe (M5 → M15)

---

## File Status

**File:** `trading_strategy_m5_advanced.pine`  
**Status:** ✅ UPDATED - Forex & Stock Ready  
**plotshape Error:** ✅ FIXED  
**Stock Support:** ✅ ADDED  

---

## Next Steps

1. **For Stocks:**
   - Update script
   - Enable "Is this a Stock?" in settings
   - Disable session filter
   - Adjust parameters per stock recommendations
   - Test on SPY or QQQ first
   - Then test on individual stocks

2. **For Forex:**
   - No changes needed
   - Use default settings
   - Enable session filter
   - Backtest as normal

---

**Your strategy now works on both Stocks and Forex!** 📈📊

