# Alerts & Notifications Setup Guide
## M5 Multi-Session Trading Strategy

---

## 🔔 WHAT'S NEW IN UPDATED STRATEGY

### Visual Improvements:
✅ **Large BUY/SELL arrows** on the chart (lime green UP arrow for buys, red DOWN arrow for sells)  
✅ **Real-time status dashboard** showing strategy conditions (top-left of chart)  
✅ **Diamond markers** for open long/short positions  
✅ **Color-coded labels** for all signals and exits  

### Alert Improvements:
✅ **Detailed BUY/SELL notifications** with entry price, SL, TP, R:R ratio  
✅ **Exit notifications** with P&L in pips (profit/loss on each trade)  
✅ **SuperTrend flip alerts** for trend changes  
✅ **ATR/volatility alerts** when market is too choppy  
✅ **Session alerts** when trading hours end  

---

## 📱 HOW TO SET UP ALERTS IN TRADINGVIEW

### Step 1: Add Strategy to Chart
1. Paste the script into Pine Editor
2. Click **"Add to Chart"**
3. Confirm it appears on your M5 chart

### Step 2: Create Alerts (5 Easy Steps)

#### Alert #1: BUY Signal
1. Click the **🔔 Alert Icon** (top right of chart)
2. From dropdown, select your strategy: **"M5 STRA"**
3. Select condition: **"BUY - Long Entry Signal"**
4. Set alert frequency: **"Once Per Bar Close"** (recommended)
5. Notification settings:
   - ☑️ **Show popup** (desktop notification)
   - ☑️ **Send email** (to sadi.mohammed@gmail.com)
   - ☑️ **Send to SMS** (if available on your plan)
   - ☑️ **Webhook URL** (if integrating with Discord/Telegram)
6. Click **"Create Alert"**

#### Alert #2: SELL Signal
1. Click **🔔 Alert Icon** again
2. Select condition: **"SELL - Short Entry Signal"**
3. Repeat notification settings above
4. Click **"Create Alert"**

#### Alert #3: Stop Loss Hit
1. Click **🔔 Alert Icon**
2. Select condition: **"Stop Loss Hit"** (when alert is triggered in code)
3. Set to **"Once Per Bar Close"**
4. Enable: Popup + Email
5. Click **"Create Alert"**

#### Alert #4: Take Profit Hit
1. Click **🔔 Alert Icon**
2. Select condition: **"Take Profit Hit"**
3. Set to **"Once Per Bar Close"**
4. Enable: Popup + Email
5. Click **"Create Alert"**

#### Alert #5: SuperTrend Flip (Trend Change)
1. Click **🔔 Alert Icon**
2. Select: **"SuperTrend Bullish Flip"** OR **"SuperTrend Bearish Flip"**
3. Set to **"Once Per Bar Close"**
4. Enable: Popup only (optional, for trend monitoring)
5. Create both alerts

---

## 📊 REAL-TIME STATUS DASHBOARD

Once strategy is added, you'll see a **live dashboard in top-left corner** showing:

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
│ Total Trades      │ 248     │
│ Win Rate          │ 62.9%   │
└─────────────────────────────┘
```

**What Each Shows:**
- **Session Status:** ACTIVE (trading now) or INACTIVE (outside hours)
- **RSI:** Current RSI value (>50 bullish, <50 bearish)
- **Distance EMA50:** How far price is from EMA 50 (pullback proximity)
- **SuperTrend:** Current trend direction
- **ATR Filter:** OK (enough volatility) or LOW (too choppy)
- **Open Trades:** How many trades are currently open
- **Daily Trades:** Current day trades / max daily limit
- **Total Trades:** All-time trades closed
- **Win Rate:** Percentage of winning trades

---

## 🎯 CHART VISUAL SIGNALS GUIDE

### Buy Signal (BUY Entries):
```
Price Point: Appears below the candle
Symbol: Large GREEN UP arrow (▲)
Text: "BUY"
Meaning: Long entry conditions met - enter a long trade
```

### Sell Signal (SELL Entries):
```
Price Point: Appears above the candle
Symbol: Large RED DOWN arrow (▼)
Text: "SELL"
Meaning: Short entry conditions met - enter a short trade
```

### Active Position Markers:
```
LONG Position Open:  Green Diamond (◆) above the candle
SHORT Position Open: Red Diamond (◆) below the candle
```

### Trend Lines on Chart:
```
Blue Line:     EMA 200 (primary trend)
Orange Line:   EMA 50 (pullback zone)
Green/Red:     SuperTrend (momentum)
```

---

## 📢 NOTIFICATION MESSAGE EXAMPLES

### When BUY Signal Triggers:
```
BUY SIGNAL - LONG ENTRY
Entry Price: 1.0950
Stop Loss: 1.0938
Take Profit: 1.0974
Risk: 12.00 pips
Reward: 24.00 pips
R:R Ratio: 1:2.00
```

### When SELL Signal Triggers:
```
SELL SIGNAL - SHORT ENTRY
Entry Price: 1.0950
Stop Loss: 1.0962
Take Profit: 1.0926
Risk: 12.00 pips
Reward: 24.00 pips
R:R Ratio: 1:2.00
```

### When Position Closes (TP Hit):
```
TAKE PROFIT HIT - LONG CLOSED
Exit Price: 1.0974
P&L: +24.00 pips
```

### When Position Closes (SL Hit):
```
STOP LOSS HIT - LONG CLOSED
Exit Price: 1.0938
P&L: -12.00 pips
```

### When Position Closes (SuperTrend Flip):
```
SUPERTREND FLIP EXIT - LONG CLOSED
Exit Price: 1.0960
P&L: +10.00 pips
```

---

## 🔗 ADVANCED: DISCORD/TELEGRAM INTEGRATION

If you want alerts sent to Discord or Telegram instead of (or in addition to) email:

### Option A: TradingView Alerts → Discord

1. **Create Discord Webhook:**
   - Go to your Discord server
   - Right-click channel → Edit Channel
   - Go to **Webhooks** → Create Webhook
   - Copy the **Webhook URL**

2. **Add to TradingView Alert:**
   - When creating alert, find **"Webhook URL"** field
   - Paste Discord webhook URL
   - Save alert

3. **You'll receive Discord messages like:**
   ```
   🟢 BUY SIGNAL TRIGGERED
   Entry Price: 1.0950
   Stop Loss: 1.0938
   Take Profit: 1.0974
   R:R Ratio: 1:2.00
   ```

### Option B: TradingView Alerts → Telegram

1. **Create Telegram Bot:**
   - Message @BotFather on Telegram
   - Create new bot, get **API Token**
   - Message your bot once
   - Get your **Chat ID**: https://api.telegram.org/botYOUR_TOKEN/getUpdates

2. **Use IFTTT as Bridge:**
   - Go to IFTTT.com
   - Create applet: TradingView alert → Telegram message
   - Connect your Telegram

3. **Alternative: Use Webhook with Telegram directly**
   - URL format: `https://api.telegram.org/botYOUR_TOKEN/sendMessage?chat_id=YOUR_CHAT_ID&text=ALERT_MESSAGE`

---

## ⏰ RECOMMENDED ALERT SETTINGS

### For Active Traders (Responsive):
```
BUY/SELL Signals:     Popup + Email + Webhook (Discord)
Entry Alerts:         Immediate (1-min bar)
Exit Alerts:          Immediate (1-min bar)
SuperTrend Flips:     Popup only
```

### For Part-Time Traders (Monitoring):
```
BUY/SELL Signals:     Email only (check when available)
Exit Alerts:          Email + Popup
SuperTrend Flips:     Disabled (too frequent)
```

### For Systematic/Automated (Set & Forget):
```
BUY/SELL Signals:     Webhook to your trading bot API
Exit Alerts:          Webhook to position management
Other Alerts:         Disabled
```

---

## 🆘 TROUBLESHOOTING ALERTS

### Issue: Alerts not firing
**Solutions:**
1. Verify alert was created (should show in Alerts panel)
2. Check that strategy is added to chart and compiling (no errors)
3. Ensure market is open (M5 candles are forming)
4. Try simple test: Create alert on "Outside Trading Hours" (should fire immediately if outside 08:00-21:00 UTC)
5. If still not working, remove and recreate alert

### Issue: Too many false alerts
**Solutions:**
1. Disable "SuperTrend Flip" alerts (too frequent)
2. Increase pullback % threshold (Settings → 0.5 → 1.0)
3. Increase SuperTrend period (10 → 12 or 15)
4. Enable "Market Structure Filter" for fewer but higher-quality signals

### Issue: Alerts arriving late
**Solutions:**
1. Email alerts are slower (5-10 min delay) — use Popup instead
2. Make sure TradingView app is running (desktop for faster popups)
3. For real-time, use Webhook + Discord (fastest, instant)

### Issue: Can't find strategy in alert dropdown
**Solutions:**
1. Make sure strategy is "Added to Chart" (not just saved in editor)
2. Click anywhere on the chart to refresh
3. Reload the page (F5)
4. Verify strategy compiles (no red errors in Pine Editor)

---

## 📋 ALERT CHECKLIST

```
Before going live, set up these alerts:

☐ BUY - Long Entry Signal
  ☐ Popup enabled
  ☐ Email enabled
  ☐ Discord/Telegram (optional)

☐ SELL - Short Entry Signal
  ☐ Popup enabled
  ☐ Email enabled
  ☐ Discord/Telegram (optional)

☐ SuperTrend Bullish Flip (optional - for trend monitoring)
  ☐ Popup enabled
  ☐ Email disabled (too noisy)

☐ SuperTrend Bearish Flip (optional)
  ☐ Popup enabled
  ☐ Email disabled

☐ Stop Loss Hit (if manual exits)
  ☐ Popup enabled
  ☐ Email enabled

☐ Take Profit Hit (if manual monitoring)
  ☐ Popup enabled
  ☐ Email enabled

Optional Alerts:
☐ Outside Trading Hours (monitor when strategy inactive)
☐ Low Volatility Alert (know when ATR too low)

Test:
☐ Verify alerts fire during next trading session
☐ Check desktop notifications are enabled
☐ Check email doesn't go to spam
☐ Test Discord/Telegram if using webhook
```

---

## 🎯 ACTIONABLE ALERT WORKFLOW

### When you receive a BUY alert:
```
1. Check dashboard - is session ACTIVE?
2. Look at chart - do you see the green UP arrow?
3. Read notification:
   - Entry Price: Where to enter
   - Stop Loss: Where to protect
   - Take Profit: Target price
   - R:R Ratio: Risk-reward ratio (should be >1:1)
4. Decision:
   - If R:R > 1:2: Consider entering
   - If R:R < 1:1: Skip (bad risk management)
   - If confused: Wait for next signal
5. Execute trade manually OR let strategy execute automatically
```

### When you receive a SELL alert:
```
Same as BUY but opposite direction
Check for RSI < 50 and price below EMA 200
```

### When you receive an EXIT alert (SL/TP):
```
1. Check the P&L pips (+ or -)
2. If TP hit: Congrats! Profit locked in
3. If SL hit: Loss accepted, move to next trade
4. If ST Flip: Trend reversed, position exited early
5. Log the trade in your journal
6. Wait for next BUY/SELL signal
```

---

## 💡 PRO TIPS

1. **Use Dashboard as Pre-Trade Checklist:**
   - Before entering, glance at top-left dashboard
   - Confirm: Session ACTIVE, ATR OK, RSI aligned, SuperTrend direction
   - This 2-second check prevents bad entries

2. **Combine Alerts + Dashboard:**
   - Alert tells you WHAT happened
   - Dashboard shows WHY it happened
   - Together = confident trading decisions

3. **Test First on Demo:**
   - Run alerts on demo account for 1 week
   - Verify they fire at the right times
   - Check P&L matches expectations
   - Only then use on real account

4. **Keep Email Simple:**
   - TradingView email subjects are auto-generated
   - Use Gmail filters to auto-sort into "Trading" folder
   - Quick scan shows: [BUY] [SELL] [SL HIT] [TP HIT]

5. **Mobile Notifications:**
   - Install TradingView mobile app
   - Enable push notifications
   - Get instant alerts on your phone while away from desk

---

## 📞 QUICK REFERENCE

| Alert | When It Fires | Action |
|-------|---------------|--------|
| BUY | Price above EMA200, pullback to EMA50, ST flip up, RSI >50 | Enter long |
| SELL | Price below EMA200, pullback to EMA50, ST flip down, RSI <50 | Enter short |
| ST Bullish Flip | SuperTrend color changes to green | Trend may reverse to up |
| ST Bearish Flip | SuperTrend color changes to red | Trend may reverse to down |
| Outside Hours | Not in 08:00-21:00 UTC | Strategy inactive, no trades |
| Low Volatility | ATR below threshold | Market too choppy, skip entry |

---

**Last Updated:** May 2026  
**Status:** Ready to Use  
**Tested:** TradingView, Pine Script v6  

