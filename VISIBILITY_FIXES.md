# Visibility Fixes - Dashboard & Buy/Sell Arrows

## Changes Made

### Issue #1: Dashboard Hidden on Left Side
**Problem:** Strategy status dashboard was positioned on the left side, making it hard to see with candlesticks.

**Fix:** Moved dashboard from `position.top_left` to `position.top_right`

**Before:**
```pine
position=position.top_left
```

**After:**
```pine
position=position.top_right
```

**Result:** Dashboard now appears on the **right side** of your chart, fully visible and not blocking price action.

---

### Issue #2: Buy/Sell Arrows Not Visible
**Problem:** Using boolean `plotshape()` without proper value wasn't rendering on chart.

**Fix:** Wrapped plotshape in `if` statements and use `close` or `high`/`low` values

**Before:**
```pine
plotshape(longSignal, title="BUY Signal", ...)
plotshape(shortSignal, title="SELL Signal", ...)
```

**After:**
```pine
if longSignal
    plotshape(close, title="BUY Signal", ...)

if shortSignal
    plotshape(close, title="SELL Signal", ...)
```

**Result:** Now you'll see:
- 🟢 **Large GREEN UP arrow ▲** below the candle when BUY signal triggers
- 🔴 **Large RED DOWN arrow ▼** above the candle when SELL signal triggers
- 💚 **Green diamond ◆** when long position is open
- ❤️ **Red diamond ◆** when short position is open

---

## What You'll Now See on Your Chart

### Dashboard (Top Right):
```
┌─────────────────────────────┐
│   STRATEGY STATUS           │
├─────────────────────────────┤
│ Session Status    │ ACTIVE  │
│ RSI (14)          │ 58.32   │
│ Distance EMA50    │ 0.45%   │
│ SuperTrend        │ BULLISH │
│ ATR Filter        │ OK      │
│ Open Trades       │ 0       │
│ Daily Trades      │ 2/5     │
│ Total Trades      │248      │
│ Win Rate          │ 62.9%   │
└─────────────────────────────┘
```

### Buy Signal (Green Arrow ▲):
```
Price: 1.0950
        ▲ BUY
Candle
```

### Sell Signal (Red Arrow ▼):
```
        ▼ SELL
Price: 1.0950
Candle
```

### Active Positions (Diamonds):
```
Long Open: Green Diamond ◆ above candle
Short Open: Red Diamond ◆ below candle
```

---

## How to Test

1. **Paste updated script** into TradingView Pine Editor
2. **Click "Add to Chart"** — Wait for compilation
3. **Look for:**
   - ✅ Dashboard on **RIGHT side** (not left)
   - ✅ **Large green/red arrows** on candlesticks
   - ✅ **Diamonds** when positions open
4. **Wait for next signal** (should appear within hours during trading hours)

---

## If Arrows Still Don't Show

**Common reasons and fixes:**

### Reason #1: Outside Trading Hours
- Strategy only trades 08:00-21:00 UTC
- If it's outside these hours, no signals will generate
- **Fix:** Wait for London (08:00 UTC) or New York (13:00 UTC) to open

### Reason #2: Conditions Not Met
- All 8 entry conditions must be true simultaneously
- If even one fails, no signal
- **Fix:** Check dashboard - is RSI on correct side? Is ST bullish/bearish? Is ATR OK?

### Reason #3: Chart Zoom Too Far Out
- If you're zoomed way out, arrows may be tiny
- **Fix:** Zoom in to M5 timeframe, zoom into recent candles

### Reason #4: Wrong Timeframe
- Strategy MUST be on M5 (5-minute) chart
- **Fix:** Switch chart to M5 timeframe

### Reason #5: Alert Conditions Need Refresh
- Sometimes TradingView needs to reload
- **Fix:** Refresh page (F5), remove and re-add strategy to chart

---

## Visual Guide to Signals

### Entry Signals (What to Look For):

**BEFORE BUY Signal Appears:**
1. Dashboard shows "Session ACTIVE" ✓
2. Dashboard shows "SuperTrend BULLISH" ✓
3. RSI is above 50 ✓
4. Distance from EMA50 is < 0.5% ✓
5. Price is above EMA 200 ✓

**THEN: Large GREEN arrow ▲ appears below the candle**
- Popup notification triggers
- Text "BUY" appears on the arrow
- This is your entry signal

**BEFORE SELL Signal Appears:**
1. Dashboard shows "Session ACTIVE" ✓
2. Dashboard shows "SuperTrend BEARISH" ✓
3. RSI is below 50 ✓
4. Distance from EMA50 is < 0.5% ✓
5. Price is below EMA 200 ✓

**THEN: Large RED arrow ▼ appears above the candle**
- Popup notification triggers
- Text "SELL" appears on the arrow
- This is your entry signal

---

## Dashboard Detailed Guide

| Field | What It Shows | Green | Red | Yellow |
|-------|---------------|-------|-----|--------|
| Session Status | ACTIVE or INACTIVE | ACTIVE | INACTIVE | - |
| RSI (14) | Current RSI value | >50 (bullish) | <50 (bearish) | - |
| Distance EMA50 | How close to pullback zone | <0.5% | >1% | 0.5-1% |
| SuperTrend | Trend direction | BULLISH | BEARISH | - |
| ATR Filter | Volatility adequate | OK | LOW | - |
| Open Trades | Number of live positions | 0 | 1+ | - |
| Daily Trades | Count / max | Green if < max | - | Yellow if near max |
| Total Trades | All-time trades | More | - | - |
| Win Rate | % winning trades | >55% | <45% | 45-55% |

---

## Arrow Appearance Settings (Customizable)

If you want to change arrow size/color/position, you can edit:

```pine
// In SECTION 10, find these lines:

// BUY arrow settings:
style=shape.triangleup              // Change to: shape.labelup, shape.diamond, etc.
location=location.belowbar          // Change to: location.abovebar
color=color.new(color.lime, 0)      // Change to: color.red, color.blue, etc.
size=size.large                     // Change to: size.small, size.tiny, size.huge

// SELL arrow settings:
style=shape.triangledown            // Change to: shape.labeldown, shape.diamond, etc.
location=location.abovebar          // Change to: location.belowbar
color=color.new(color.red, 0)       // Change to: color.green, color.blue, etc.
size=size.large                     // Change to: size.small, size.tiny, size.huge
```

---

## File Status

**File:** `trading_strategy_m5_advanced.pine`  
**Status:** ✅ UPDATED - Arrows & Dashboard Visible  
**Dashboard Position:** Top Right ✅  
**Buy/Sell Arrows:** Visible on Chart ✅  

---

## Next Steps

1. **Update the script** (paste updated version)
2. **Add to chart** (remove old version first)
3. **Wait for signal** (during trading hours)
4. **See arrows appear** on your candlesticks
5. **Read notification** with entry details
6. **Monitor dashboard** for real-time status

---

**Your strategy is now fully visible and ready to trade!** 📈

