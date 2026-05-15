# Arrows Not Showing - Troubleshooting Guide

## Why Arrows Might Not Be Visible

The most common reason: **Session filter is blocking signals outside London/NY hours**.

The strategy only shows arrows during specific trading hours by default:
- London: 08:00-16:00 UTC
- New York: 13:00-21:00 UTC

If you're testing **outside these hours**, arrows won't appear.

---

## ✅ QUICK FIX - Enable Testing Mode

### Method 1: Ignore Session Filter (FASTEST)

1. **Open Settings** → Click gear icon
2. **Go to Inputs tab**
3. **Find: BACKTEST SETTINGS section**
4. **Toggle ON:** "TESTING: Ignore session filter (see arrows anytime)"

```
TESTING: Ignore session filter (see arrows anytime) → ON ✅
```

5. **Now arrows will appear on EVERY chart** regardless of time
6. **Leave this ON for testing/demo** until you're ready for live

**Result:** Now you'll see BUY/SELL arrows appear whenever conditions are met, even outside London/NY hours!

---

### Method 2: Adjust Session Times to Match Your Timezone

1. **Open Settings → Inputs**
2. **Go to SESSION SETTINGS section**
3. **Adjust times to match when you're testing:**

**If testing during US market hours (9:30-16:00 EST):**
```
Enable New York Session: ON
NY Start Time: 09:00
NY End Time: 21:00
```

**If testing during European hours (8:00-16:00 GMT):**
```
Enable London Session: ON
London Start Time: 08:00
London End Time: 16:00
```

4. **Save and refresh chart**

---

## Additional Troubleshooting

### Problem: Still No Arrows After Enabling Testing Mode

**Check these conditions are being met:**

1. **Is price above EMA 200?** (for BUY) or below (for SELL)
   - Look at the orange/blue lines on chart
   - Price must cross the EMA 200 (thick blue line)

2. **Is price near EMA 50?** (within 0.5% default)
   - Look at the orange line (EMA 50)
   - Price should be close to this line for pullback entry

3. **Is SuperTrend flipping?**
   - Look for the green/red line changing color
   - Green = bullish (BUY setup), Red = bearish (SELL setup)

4. **Is RSI on correct side?**
   - Look at RSI in bottom pane (purple line)
   - For BUY: RSI should be > 50
   - For SELL: RSI should be < 50

5. **Is ATR sufficient?**
   - Check dashboard: "ATR Filter" should show "OK" (green)
   - If it shows "LOW" (red), volatility is too low

**If all 5 are TRUE, arrow should appear!**

---

## Enable Debug Mode to See What's Happening

### To Debug Entry Conditions:

1. **Open Settings → Inputs**
2. **BACKTEST SETTINGS section:**
   - Toggle ON: "Enable Debug Mode (plots signals)"
   - Toggle ON: "TESTING: Ignore session filter"

3. **Look at chart** - You'll see debug labels showing:
   - ✅ In trading session (or ❌ if not)
   - ✅ ATR OK (or ❌ ATR too low)
   - ✅ ST Flip Bullish (or ❌ no flip)
   - ✅ ST Flip Bearish (or ❌ no flip)

4. **When you see all ✅**, an arrow should appear!

---

## Step-by-Step: To See Your First Arrow

### Step 1: Copy Updated Script
- Copy latest: `trading_strategy_m5_advanced.pine`
- Paste into TradingView Pine Editor

### Step 2: Add to Chart
- Click "Add to Chart"
- Wait for compilation (green checkmark)

### Step 3: Enable Testing Mode
- Settings → Inputs → BACKTEST SETTINGS
- Toggle ON: "TESTING: Ignore session filter (see arrows anytime)"

### Step 4: Enable Debug
- Settings → Inputs → BACKTEST SETTINGS
- Toggle ON: "Enable Debug Mode (plots signals)"

### Step 5: Watch for Arrows
- Now refresh the chart (F5)
- BUY arrows (green ▲) should appear below price bars
- SELL arrows (red ▼) should appear above price bars
- When they do, look at the debug labels to see which conditions triggered

### Step 6: Once Arrows Show
- Verify the conditions that triggered (all 5 should be ✅)
- Disable debug mode (less chart clutter)
- Keep testing mode ON until happy with setup
- Then switch back to normal mode (disable testing)

---

## What Each Arrow Means

### GREEN UP ARROW ▲ (BUY Signal)
```
Appears when ALL of these are true:
✅ Price is above EMA 200 (uptrend)
✅ Price is near EMA 50 (pullback zone)
✅ SuperTrend flips from red to green (bullish)
✅ Close is above SuperTrend line (confirmed bullish)
✅ RSI > 50 (bullish momentum)
✅ ATR is above threshold (enough volatility)
✅ (Optional: Market structure shows higher highs)

ACTION: This is a BUY signal - enter long trade
```

### RED DOWN ARROW ▼ (SELL Signal)
```
Appears when ALL of these are true:
✅ Price is below EMA 200 (downtrend)
✅ Price is near EMA 50 (pullback zone)
✅ SuperTrend flips from green to red (bearish)
✅ Close is below SuperTrend line (confirmed bearish)
✅ RSI < 50 (bearish momentum)
✅ ATR is above threshold (enough volatility)
✅ (Optional: Market structure shows lower lows)

ACTION: This is a SELL signal - enter short trade
```

---

## Common Scenarios

### Scenario 1: Testing at 2 PM Your Local Time
**Problem:** It's not 13:00-21:00 UTC, so no arrows  
**Solution:** Enable "TESTING: Ignore session filter"  
**Result:** Arrows will appear when conditions are met

### Scenario 2: Testing on a Stock Chart
**Problem:** Stock market closed, but strategy still checks session times  
**Solution:** 
- Enable "Is this a Stock?" in SYMBOL SETTINGS
- Enable "TESTING: Ignore session filter"  
**Result:** Arrows will appear whenever conditions align

### Scenario 3: Testing on Weekend or Holiday
**Problem:** No live candles forming, so no new signals  
**Solution:** Load historical data and scroll right to where candles exist  
**Result:** You'll see arrows on past candles that met conditions

### Scenario 4: See Arrows on Past Candles Only
**Problem:** Strategy shows arrows on old candles but not current ones  
**Solution:** This is normal! Current candle conditions haven't been met yet  
**Action:** Wait for next candle to close. Arrow might appear then.

---

## Chart Setup Checklist

```
Before testing, verify:

Chart Setup:
☐ M5 timeframe selected
☐ Chart is showing recent data (last 100 candles visible)
☐ Price has space to move up and down
☐ Strategy added to chart (shows in bottom right)

Settings:
☐ "TESTING: Ignore session filter" is ON ✅
☐ "Enable Debug Mode" is ON ✅ (optional, for diagnostics)
☐ "Enable London Session" or "Enable NY Session" has ON at least one

Indicators Visible:
☐ Blue line (EMA 200) visible on chart ✅
☐ Orange line (EMA 50) visible on chart ✅
☐ Green/Red line (SuperTrend) visible on chart ✅
☐ Purple line (RSI) visible in bottom pane ✅
☐ Dashboard table visible on top-right ✅

Ready:
☐ Chart refreshed (F5)
☐ All settings confirmed
☐ Waiting to see arrows...
```

---

## If Arrows STILL Don't Show

### Last Resort Troubleshooting:

1. **Remove and re-add strategy**
   - Click ⓧ on strategy in bottom right
   - Paste code again
   - Click "Add to Chart"

2. **Refresh page**
   - Press F5 on keyboard
   - Wait for chart to reload

3. **Check alerts in Pine Editor**
   - Switch to Pine Editor tab
   - Click "Alerts" in bottom panel
   - You should see your strategy listed
   - If not, it didn't compile correctly

4. **Check compilation**
   - In Pine Editor, look for green checkmark or red X
   - If red X, there's still a syntax error
   - Check console for error messages

5. **Try a different symbol**
   - Switch to SPY or EURUSD
   - Sometimes one symbol behaves differently
   - See if arrows appear on different pair

6. **Verify strategy is doing something**
   - Open Strategy Tester (bottom panel)
   - Run a quick backtest
   - If backtest shows trades, strategy IS working
   - If no trades in backtest, conditions aren't being met

---

## Reference: When Arrows Should Appear

| Time | For Forex | For Stocks | For Commodities |
|------|-----------|-----------|-----------------|
| 08:00-13:00 UTC | ✅ London | ❌ Need testing mode | ✅ Yes |
| 13:00-16:00 UTC | ✅✅ Overlap | ❌ Need testing mode | ✅ Peak |
| 16:00-21:00 UTC | ✅ NY only | ❌ Need testing mode | ✅ Yes |
| 21:00-08:00 UTC | ❌ No session | ❌ Need testing mode | ❌ Low volume |

**Solution for outside hours:** Always use "TESTING: Ignore session filter"

---

## File Status

**File:** `trading_strategy_m5_advanced.pine`  
**Status:** ✅ UPDATED - Testing mode added, debug labels added  
**New Features:**
- ✅ "TESTING: Ignore session filter" toggle
- ✅ "Enable Debug Mode" shows why signals appear/don't appear
- ✅ plotshape calls now in global scope

---

## Next Steps

1. **Update** script from `trading_strategy_m5_advanced.pine`
2. **Add to chart** in TradingView
3. **Enable testing mode** in Settings
4. **Refresh chart** (F5)
5. **Watch for arrows** (should appear within a few candles)
6. **Once you see them**, disable testing mode and adjust session times
7. **Paper trade** with real session times

---

**Your arrows should now be visible!** 📈

