"""
dashboard/account_panel.py — Account Settings Panel

Single place for the user to:
  1. Enter BitOasis API credentials (data feed + auto-trading)
  2. Enter Interactive Brokers connection details
  3. Enter Discord confirmation bot settings
  4. Test each connection live
  5. See connection status for all services

Credentials are stored in st.session_state only (never written to disk
or logs). Set environment variables for persistence across restarts:
  BITOASIS_API_KEY, BITOASIS_API_SECRET
  DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID

HOW TO GET BITOASIS API CREDENTIALS:
  1. Log in at bitoasis.net
  2. Profile → API Management → Create API Key
  3. Enable: View Market Data + Place Orders + View Balance
  4. Copy Key and Secret immediately (secret shown only once)
  5. Paste below — then click "Connect & Test"
"""

from __future__ import annotations
import os
import time
import streamlit as st
from datetime import datetime
from dashboard.settings_store import save_settings, set_setting, get_tz_offset, tz_label


# ── CSS for the account panel ─────────────────────────────────────────────────
PANEL_CSS = """
<style>
.acct-section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.acct-title {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-pri);
  margin-bottom: 4px;
}
.acct-sub {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--text-mute);
  margin-bottom: 14px;
  line-height: 1.6;
}
.acct-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 11px;
  margin-top: 8px;
}
.acct-ok   { background: rgba(0,201,167,0.10); border: 1px solid rgba(0,201,167,0.3); color: var(--green); }
.acct-fail { background: rgba(255,69,96,0.10);  border: 1px solid rgba(255,69,96,0.3);  color: var(--red); }
.acct-info { background: rgba(75,159,255,0.10); border: 1px solid rgba(75,159,255,0.3); color: var(--blue); }
.acct-how {
  background: var(--bg-surface);
  border-left: 3px solid var(--blue);
  padding: 10px 14px;
  border-radius: 0 4px 4px 0;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-sec);
  line-height: 1.7;
  margin-bottom: 12px;
}
</style>
"""


def _env(key: str, fallback: str = "") -> str:
    """Read from session state first, then environment variable."""
    return st.session_state.get(key, os.getenv(key, fallback))


def _status_badge(ok: bool, ok_text: str, fail_text: str) -> str:
    css = "acct-ok" if ok else "acct-fail"
    icon = "●" if ok else "●"
    text = ok_text if ok else fail_text
    return f'<div class="acct-status {css}">{icon} {text}</div>'


def render_account_panel():
    """Render the full Account Settings page."""
    st.markdown(PANEL_CSS, unsafe_allow_html=True)

    st.markdown("""
    <div style="margin-bottom:20px">
      <div style="font-family:var(--mono);font-size:20px;font-weight:700;color:var(--text-pri);letter-spacing:0.06em">
        ACCOUNT SETTINGS
      </div>
      <div style="font-family:var(--mono);font-size:11px;color:var(--text-mute);margin-top:4px">
        Connect your exchange and notification accounts. Credentials held in memory only.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    #  BOT DEFAULTS — Saved between tab switches (session-level persistence)
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">⚙ BOT DEFAULTS — Chart Toolbar Defaults</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="acct-sub">
      Set your preferred trading pair, data source, interval, and period.
      These are applied automatically the next time the dashboard loads.
      Click <b>Save Defaults</b> to apply.
    </div>
    """, unsafe_allow_html=True)

    from config import CONFIG
    _src_opts = ["kraken", "kucoin", "yfinance", "twelvedata", "bitoasis", "binance", "coingecko", "tradingview", "sample"]

    d1, d2, d3, d4 = st.columns(4)
    def_sym = d1.text_input(
        "Default Ticker",
        value=st.session_state.get("_def_symbol", CONFIG.data.ui_default_symbol),
        key="def_sym_input",
        placeholder="e.g. XBTUSD",
        help="Symbol shown in toolbar on startup",
    )
    def_src_idx = _src_opts.index(
        st.session_state.get("_def_source", CONFIG.data.ui_default_source)
        if st.session_state.get("_def_source", CONFIG.data.ui_default_source) in _src_opts
        else "kraken"
    )
    def_src = d2.selectbox(
        "Default Source",
        _src_opts,
        index=def_src_idx,
        key="def_src_input",
    )
    _ivl_opts = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk"]
    _def_ivl   = st.session_state.get("_def_interval", CONFIG.data.ui_default_interval)
    def_ivl = d3.selectbox(
        "Default Interval",
        _ivl_opts,
        index=_ivl_opts.index(_def_ivl) if _def_ivl in _ivl_opts else 4,
        key="def_ivl_input",
    )
    _per_opts = ["7d", "30d", "60d", "6mo", "1y", "2y", "5y"]
    _def_per  = st.session_state.get("_def_period", CONFIG.data.ui_default_period)
    def_per = d4.selectbox(
        "Default Period",
        _per_opts,
        index=_per_opts.index(_def_per) if _def_per in _per_opts else 3,
        key="def_per_input",
    )

    sb1, sb2 = st.columns(2)
    if sb1.button("💾 Save Defaults", type="primary", use_container_width=True, key="save_defaults"):
        st.session_state["_def_symbol"]   = def_sym
        st.session_state["_def_source"]   = def_src
        st.session_state["_def_interval"] = def_ivl
        st.session_state["_def_period"]   = def_per
        # Persist to CONFIG so aggregator + other modules see them
        CONFIG.data.ui_default_symbol   = def_sym
        CONFIG.data.ui_default_source   = def_src
        CONFIG.data.ui_default_interval = def_ivl
        CONFIG.data.ui_default_period   = def_per
        save_settings()  # persist to disk
        st.success(
            f"✅ Defaults saved: {def_sym} · {def_src} · {def_ivl} · {def_per}  "
            f"(click ⟳ LOAD on the chart to apply immediately)"
        )

    if sb2.button("↩ Apply Now (Reload Chart)", use_container_width=True, key="apply_defaults"):
        st.session_state["symbol"]   = def_sym
        st.session_state["source"]   = def_src
        st.session_state["interval"] = def_ivl
        st.session_state["period"]   = def_per
        st.session_state["df"]       = None   # force data reload
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    #  FREE API KEYS — Twelve Data (commodities)
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">🔑 FREE API KEYS — Commodities & Market Data</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="acct-sub">
      Connect free-tier APIs to unlock real-time spot commodity prices
      (XAUUSD, XAGUSD, WTI, Brent). No Exness account needed.
    </div>
    """, unsafe_allow_html=True)

    # ── Twelve Data ──────────────────────────────────────────────────────
    st.markdown("""
    <div style="background:rgba(155,109,255,0.07);border:1px solid rgba(155,109,255,0.25);
      border-left:3px solid var(--purple);border-radius:4px;
      padding:10px 14px;margin-bottom:12px;
      font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--text-sec);line-height:1.7">
      <b style="color:var(--text-pri)">◈ Twelve Data</b> — Free tier: 800 API credits/day<br>
      Provides real-time spot prices for <b style="color:var(--purple)">XAUUSD (Gold), XAGUSD (Silver),
      WTI/USD, BRENT/USD</b> and 5,000+ instruments.<br>
      ① Go to <b>twelvedata.com/pricing</b> &nbsp;②&nbsp; Sign up free
      &nbsp;③&nbsp; Copy your API key from the dashboard &nbsp;④&nbsp; Paste below<br>
      <b style="color:var(--amber)">Select source → "Twelve Data"</b> in the toolbar to use it.
    </div>
    """, unsafe_allow_html=True)

    _saved_td_key = st.session_state.get("_twelvedata_api_key", CONFIG.data.twelvedata_api_key or "")
    td_key = st.text_input(
        "Twelve Data API Key",
        value=_saved_td_key,
        placeholder="abc1234defxxxxxxxxxxxxxxxxxxxxxx",
        type="password",
        key="td_api_key_input",
        help="Get a free key at https://twelvedata.com/pricing (800 credits/day)"
    )
    td_c1, td_c2 = st.columns(2)
    if td_c1.button("💾 Save API Key", key="save_td_key", use_container_width=True, type="primary"):
        st.session_state["_twelvedata_api_key"] = td_key
        CONFIG.data.twelvedata_api_key = td_key
        if td_key:
            st.success("✅ Twelve Data API key saved — select 'Twelve Data' as source in the toolbar.")
        else:
            st.info("API key cleared — will fall back to yfinance futures data.")
    if td_c2.button("🧪 Test Connection", key="test_td_key", use_container_width=True):
        if not td_key:
            st.error("Enter an API key first.")
        else:
            try:
                from data.commodity_feeds import fetch_twelvedata
                df_test = fetch_twelvedata("XAU/USD", interval="1d", period="7d", api_key=td_key)
                last_px = float(df_test["Close"].iloc[-1])
                st.success(f"✅ Connected — Gold (XAU/USD) last price: ${last_px:,.2f}")
            except Exception as e:
                st.error(f"❌ {e}")

    st.markdown('</div>', unsafe_allow_html=True)

    # Real-time data sources banner
    st.markdown("""
    <div style="background:rgba(0,201,167,0.08);border:1px solid rgba(0,201,167,0.3);border-radius:6px;padding:14px 18px;margin-bottom:16px">
      <div style="font-family:var(--mono);font-size:11px;font-weight:600;color:var(--green);margin-bottom:8px">
        RECOMMENDED REAL-TIME DATA SOURCES FOR QATAR
      </div>
      <div style="font-family:var(--mono);font-size:10px;color:var(--text-sec);line-height:1.8">
        <b style="color:var(--text-pri)">Kraken</b> — Select source: <code>kraken</code> · Symbol: <code>XBTUSD</code> or <code>ETHUSD</code> · No account needed · Real-time · Accessible from Qatar<br>
        <b style="color:var(--text-pri)">KuCoin</b> — Select source: <code>kucoin</code> · Symbol: <code>BTC-USDT</code> or <code>ETH-USDT</code> · No account needed · Real-time · Accessible from Qatar<br>
        <b style="color:var(--text-sec)">Yahoo Finance</b> — source: <code>yfinance</code> · Symbol: <code>BTC-USD</code> · 15-min delay · No account needed<br>
        <b style="color:var(--text-mute)">Binance</b> — ⚠️ Geo-blocked in Qatar without VPN<br>
        <b style="color:var(--text-pri)">BitOasis</b> — source: <code>bitoasis</code> · AED prices · Requires API credentials (set up below)
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    #  BITOASIS
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">BITOASIS — Live Data + Auto-Trading</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="acct-how">
      <b>How to get your API credentials:</b><br>
      1. Go to <b>bitoasis.net</b> → log in → click your profile photo (top right)<br>
      2. Select <b>API Management</b> from the dropdown<br>
      3. Click <b>Create API Key</b> — give it a name like "Trading Bot"<br>
      4. Enable permissions: ✅ View Balance &nbsp; ✅ Place Orders &nbsp; ✅ Market Data<br>
      5. Copy the <b>API Key</b> and <b>API Secret</b> immediately (secret shown once)<br>
      6. Paste both below then click <b>Connect & Test</b>
    </div>
    """, unsafe_allow_html=True)

    bo_mode = st.radio("Trading Mode", ["Paper (simulate — no real orders)", "Live (real orders)"],
                       horizontal=True, key="bo_mode_radio")
    is_live = "Live" in bo_mode

    c1, c2 = st.columns(2)
    bo_key    = c1.text_input("API Key",    value=_env("BITOASIS_API_KEY"),
                               type="password", key="BITOASIS_API_KEY",
                               placeholder="Paste your BitOasis API Key here")
    bo_secret = c2.text_input("API Secret", value=_env("BITOASIS_API_SECRET"),
                               type="password", key="BITOASIS_API_SECRET",
                               placeholder="Paste your BitOasis API Secret here")

    b1, b2, b3 = st.columns([2, 2, 3])
    connected = st.session_state.get("bitoasis_connected", False)
    broker_obj = st.session_state.get("broker_obj")
    is_bitoasis = broker_obj and getattr(broker_obj, "name", "") == "BitOasis"

    if b1.button("Connect & Test", type="primary", use_container_width=True, key="bo_connect"):
        if not bo_key or not bo_secret:
            st.error("Enter both API Key and API Secret before connecting.")
        else:
            with st.spinner("Connecting to BitOasis..."):
                try:
                    from brokers.bitoasis import BitOasisBroker
                    broker = BitOasisBroker(
                        api_key=bo_key,
                        api_secret=bo_secret,
                        paper_trading=not is_live,
                    )
                    broker.connect()
                    bal = broker.get_balance()
                    px  = broker.get_price("BTC-AED")

                    st.session_state["broker_obj"]         = broker
                    st.session_state["bitoasis_connected"] = True
                    st.session_state["bitoasis_balance"]   = bal
                    st.session_state["bitoasis_btc_price"] = px
                    connected = True
                    broker_obj = broker
                    st.success(f"✅ Connected to BitOasis ({'LIVE' if is_live else 'PAPER'} mode)")
                except Exception as e:
                    st.session_state["bitoasis_connected"] = False
                    connected = False
                    st.error(f"Connection failed: {e}")

    if b2.button("Use for Data Feed", use_container_width=True, key="bo_use_feed",
                 help="Switch the chart data source to BitOasis"):
        st.session_state["source"]         = "bitoasis"
        st.session_state["symbol"]         = "BTC-AED"
        st.session_state["bitoasis_as_feed"] = True
        st.success("✅ Chart will now use BitOasis data. Click ⟳ LOAD on the main chart.")

    if connected and is_bitoasis:
        bal = st.session_state.get("bitoasis_balance", {})
        px  = st.session_state.get("bitoasis_btc_price", 0)
        st.markdown(_status_badge(True,
            f"Connected {'LIVE' if is_live else 'PAPER'} | BTC-AED: {px:,.2f} AED" if px else
            f"Connected {'LIVE' if is_live else 'PAPER'}",
            "Disconnected"
        ), unsafe_allow_html=True)
        if bal:
            bal_str = "   ".join(f"{k}: {v:,.4f}" for k, v in bal.items() if float(v) > 0)
            if bal_str:
                st.markdown(f'<div style="font-family:var(--mono);font-size:10px;color:var(--text-sec);margin-top:6px">Balance: {bal_str}</div>', unsafe_allow_html=True)
    else:
        st.markdown(_status_badge(False, "", "Not connected"), unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    #  INTERACTIVE BROKERS
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">INTERACTIVE BROKERS — Stocks + Global Markets</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="acct-how">
      <b>Prerequisites:</b><br>
      1. Install <b>TWS or IB Gateway</b> from interactivebrokers.com/en/trading/tws.php<br>
      2. Open TWS → Edit → Global Configuration → API → Settings<br>
      3. Enable "ActiveX and Socket Clients" → set port → click OK<br>
      4. Ports: Paper TWS = <b>7497</b> · Live TWS = <b>7496</b> · Paper Gateway = <b>4002</b> · Live Gateway = <b>4001</b>
    </div>
    """, unsafe_allow_html=True)

    ib_mode = st.radio("IBKR Mode", ["Paper (port 7497)", "Live (port 7496)"],
                       horizontal=True, key="ib_mode_radio")
    ib_paper = "Paper" in ib_mode
    # Port is auto-set from mode — user can override with custom port
    _default_port = 7497 if ib_paper else 7496

    c1, c2, c3 = st.columns(3)
    ib_host   = c1.text_input("TWS Host", value="127.0.0.1", key="ib_host_acct")
    # Reset port when mode changes so it always matches the selected mode
    _port_key = f"ib_port_{_default_port}"
    ib_port_v = c2.number_input("Port (auto-set by mode above)",
                                 value=_default_port, key=_port_key,
                                 help="7497=TWS Paper  7496=TWS Live  4002=GW Paper  4001=GW Live")
    ib_cid    = c3.number_input("Client ID", value=1, key="ib_cid_acct",
                                 help="Change to 2 if you get 'duplicate clientId' error")

    ib_connected = st.session_state.get("ibkr_connected", False)
    if st.button("Connect IBKR", use_container_width=True, key="ib_connect"):
        with st.spinner("Connecting to TWS..."):
            try:
                from brokers.interactive_brokers import InteractiveBrokersBroker
                broker = InteractiveBrokersBroker(
                    host=ib_host, port=int(ib_port_v),
                    client_id=int(ib_cid), paper_trading=ib_paper,
                )
                broker.connect()
                st.session_state["broker_obj"]    = broker
                st.session_state["ibkr_connected"] = True
                ib_connected = True
                st.success(f"✅ IBKR connected ({'PAPER' if ib_paper else 'LIVE'} port {ib_port_v})")
            except Exception as e:
                st.session_state["ibkr_connected"] = False
                err_msg = str(e)
                # Strip the "IBKR connection failed:" prefix for cleaner display
                if err_msg.startswith("IBKR connection failed:"):
                    err_msg = err_msg[len("IBKR connection failed:"):].strip()
                st.error(err_msg)

    st.markdown(_status_badge(ib_connected,
        f"Connected {'PAPER' if ib_paper else 'LIVE'} port {ib_port_v}",
        "Not connected — open TWS and enable API first"
    ), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    #  DISCORD
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">DISCORD — Trade Confirmation + Notifications</div>', unsafe_allow_html=True)

    # ── Read persisted credentials (separate from widget keys to avoid
    # Streamlit widget-state vs session-state collision on reruns)
    _saved_dc_token   = st.session_state.get("_discord_bot_token",   os.getenv("DISCORD_BOT_TOKEN",   ""))
    _saved_dc_channel = st.session_state.get("_discord_channel_id",  os.getenv("DISCORD_CHANNEL_ID",  ""))
    _saved_dc_webhook = st.session_state.get("_discord_webhook_url",  "")

    # ── Auto-reconnect on page refresh (once per session) ─────────────────
    _bot_alive = st.session_state.get("discord_confirm_bot") is not None
    _reconnect_done = st.session_state.get("_dc_reconnect_attempted", False)
    if _saved_dc_token and _saved_dc_channel and not _bot_alive and not _reconnect_done:
        st.session_state["_dc_reconnect_attempted"] = True
        try:
            import discord as _dc_chk  # noqa: F401
            from brokers.discord_confirm import DiscordConfirmBot
            _bot = DiscordConfirmBot(
                bot_token=_saved_dc_token,
                channel_id=int(_saved_dc_channel),
                timeout_seconds=int(st.session_state.get("dc_timeout", 120)),
            )
            st.session_state["discord_confirm_bot"] = _bot
            st.session_state["discord_connected"]   = True
        except Exception:
            st.session_state["discord_connected"] = False

    st.markdown("""
    <div class="acct-how">
      <b>Step 1 — Create the bot</b><br>
      &nbsp;&nbsp;a. Go to <b>discord.com/developers/applications</b> → <b>New Application</b><br>
      &nbsp;&nbsp;b. Name it "APEX Bot" → Create → click <b>Bot</b> in sidebar<br>
      &nbsp;&nbsp;c. Click <b>Reset Token</b> → copy token immediately (shown only once)<br>
      &nbsp;&nbsp;d. Scroll down → enable <b>Message Content Intent</b><br><br>
      <b>Step 2 — Invite bot to your server</b><br>
      &nbsp;&nbsp;a. OAuth2 → URL Generator → Scopes: <b>bot</b> + <b>applications.commands</b><br>
      &nbsp;&nbsp;b. Bot Permissions: <b>Send Messages, Embed Links, Read Message History</b><br>
      &nbsp;&nbsp;c. Open the generated URL → select your server → Authorize<br><br>
      <b>Step 3 — Get Channel ID</b><br>
      &nbsp;&nbsp;a. Discord → User Settings (⚙) → Advanced → enable <b>Developer Mode</b><br>
      &nbsp;&nbsp;b. Right-click the alert channel → <b>Copy Channel ID</b> (long number)<br><br>
      <b>Step 4 — Webhook URL for signal alerts (separate, no bot needed)</b><br>
      &nbsp;&nbsp;a. Right-click channel → Edit Channel → Integrations → Webhooks → New Webhook<br>
      &nbsp;&nbsp;b. Copy the Webhook URL and paste below — then click 💾 Save
    </div>
    """, unsafe_allow_html=True)

    require = st.toggle("Require Discord confirmation before placing orders",
                        value=st.session_state.get("dc_require", True), key="dc_require")
    timeout = st.slider("Confirmation timeout (seconds)", 30, 300,
                        value=int(st.session_state.get("dc_timeout", 120)), step=30, key="dc_timeout")

    # ── Bot credentials — widget keys are distinct from persist keys ───────
    st.markdown("**Trade Confirmation Bot** (interactive ✅/❌ buttons)")
    c1, c2 = st.columns(2)
    dc_token = c1.text_input(
        "Bot Token", value=_saved_dc_token,
        type="password", key="_dc_token_input",
        placeholder="123456789012345678:ABCDefgh...",
        help="From discord.com/developers/applications → Bot → Reset Token",
    )
    dc_channel = c2.text_input(
        "Channel ID", value=_saved_dc_channel,
        key="_dc_channel_input",
        placeholder="1234567890123456789",
        help="Right-click channel in Discord (Developer Mode on) → Copy Channel ID",
    )

    # ── Webhook URL (signal alert notifications) ──────────────────────────
    st.markdown("**Signal Alert Webhook** (automatic BUY/SELL/RSI notifications)")
    dc_webhook = st.text_input(
        "Webhook URL", value=_saved_dc_webhook,
        key="_dc_webhook_input",
        placeholder="https://discord.com/api/webhooks/...",
        help="Channel → Edit → Integrations → Webhooks → New Webhook → Copy URL",
    )

    # ── Buttons ───────────────────────────────────────────────────────────
    dc_connected = st.session_state.get("discord_connected", False)
    b1, b2, b3 = st.columns(3)

    if b1.button("💾 Save Discord Settings", type="primary",
                 use_container_width=True, key="dc_save"):
        # Store under underscore-prefixed keys (not widget keys) so
        # apply_settings_to_session can restore them reliably on next load.
        st.session_state["_discord_bot_token"]   = dc_token
        st.session_state["_discord_channel_id"]  = dc_channel
        st.session_state["_discord_webhook_url"] = dc_webhook
        # dc_require / dc_timeout are widget-bound keys — Streamlit updates them
        # automatically; writing to them after render raises an error.
        save_settings()
        _rebuild_alerts(dc_url=dc_webhook)
        st.success("✅ Discord settings saved — credentials will persist after restart.")

    if b2.button("▶ Connect Bot", use_container_width=True, key="dc_connect"):
        if not dc_token or not dc_channel:
            st.error("Enter both Bot Token and Channel ID first.")
        elif not dc_channel.strip().isdigit():
            st.error("Channel ID must be numeric (right-click channel → Copy ID).")
        else:
            # Always save before connecting so credentials survive a restart
            st.session_state["_discord_bot_token"]  = dc_token
            st.session_state["_discord_channel_id"] = dc_channel
            # dc_require / dc_timeout managed by widgets — don't set after render
            save_settings()
            with st.spinner("Connecting Discord bot (up to 20s) …"):
                try:
                    import discord as _discord_check  # noqa: F401
                except ImportError:
                    st.error("discord.py not installed. Run: pip install discord.py")
                    st.session_state["discord_connected"] = False
                else:
                    try:
                        from brokers.discord_confirm import DiscordConfirmBot
                        _old = st.session_state.get("discord_confirm_bot")
                        if _old:
                            try: _old.close()
                            except Exception: pass
                        bot = DiscordConfirmBot(
                            bot_token=dc_token,
                            channel_id=int(dc_channel),
                            timeout_seconds=timeout,
                        )
                        st.session_state["discord_confirm_bot"]     = bot
                        st.session_state["discord_connected"]       = True
                        st.session_state["dc_require_saved"]        = require
                        st.session_state["_dc_reconnect_attempted"] = True
                        dc_connected = True
                        st.success("✅ Discord bot connected! Use **📨 Send Test** to verify.")
                    except Exception as e:
                        st.session_state["discord_connected"] = False
                        err = str(e)
                        if "401" in err or "Improper token" in err or "token" in err.lower():
                            st.error("❌ Invalid Bot Token — copy it from the Discord Developer Portal → Bot → Reset Token.")
                        elif "403" in err or "Missing Access" in err:
                            st.error("❌ Bot lacks permissions — re-invite with Send Messages + Embed Links + Read Message History.")
                        elif "channel" in err.lower() or "404" in err:
                            st.error("❌ Channel ID not found — enable Developer Mode in Discord, right-click channel → Copy Channel ID.")
                        elif "timeout" in err.lower() or "20" in err:
                            st.error("❌ Bot timed out — verify the token is correct and the bot is in your server.")
                        else:
                            st.error(f"❌ Connection failed: {e}")

    if b3.button("📨 Send Test", use_container_width=True, key="dc_test"):
        bot = st.session_state.get("discord_confirm_bot")
        if bot:
            ok = bot.test()
            (st.success("✅ Test message delivered! Check your Discord channel.")
             if ok else st.error("❌ Delivery failed — check bot permissions."))
        else:
            _wh = st.session_state.get("_discord_webhook_url", "")
            if _wh and _wh.startswith("https://discord.com/api/webhooks/"):
                try:
                    import requests as _req
                    r = _req.post(_wh, json={"content": "🤖 **APEX Terminal** — webhook test"}, timeout=10)
                    if r.status_code in (200, 204):
                        st.success("✅ Webhook test delivered!")
                    else:
                        st.error(f"❌ Webhook returned HTTP {r.status_code}")
                except Exception as _we:
                    st.error(f"❌ Webhook test failed: {_we}")
            else:
                st.warning("Connect the bot first, or enter a valid Webhook URL and click 💾 Save.")

    # ── Status badges ─────────────────────────────────────────────────────
    _bot_now = st.session_state.get("discord_connected", False)
    _wh_now  = bool(st.session_state.get("_discord_webhook_url", ""))
    st.markdown(_status_badge(_bot_now,
        f"Bot connected · Confirmation required: {require} · Timeout: {timeout}s",
        "Bot not connected — enter credentials and click ▶ Connect Bot"
    ), unsafe_allow_html=True)
    st.markdown(_status_badge(_wh_now,
        "Webhook URL saved — signal alerts active",
        "No webhook URL — Discord signal alerts disabled"
    ), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    #  TRADINGVIEW DATA CONNECTION
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">📈 TRADINGVIEW — Data Connection</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="acct-how">
      TradingView provides free historical OHLCV data (stocks, crypto, forex, commodities).<br>
      <b>Anonymous access works without any login</b> — just select <code>tradingview</code> as
      your source and click LOAD. Logging in gives higher rate limits and premium symbol access.<br><br>
      &#9888; <b>Important:</b> Enter your TradingView <b>username</b> (not your email address).
      Find it at <b>tradingview.com &rarr; Profile &rarr; @username</b>.<br>
      Leave both fields blank to use anonymous (unauthenticated) access.
    </div>
    """, unsafe_allow_html=True)

    _tv_user = st.session_state.get("_tv_username", "")
    _tv_pass = st.session_state.get("_tv_password", "")
    tv_col1, tv_col2 = st.columns(2)
    tv_username = tv_col1.text_input(
        "TradingView Username (not email)", value=_tv_user,
        placeholder="e.g. john_trader  (NOT email)", key="tv_username_input",
        help="Your TradingView @username. Do NOT use your email address.",
    )
    tv_password = tv_col2.text_input(
        "TradingView Password", value=_tv_pass,
        placeholder="password", type="password", key="tv_password_input",
    )

    if tv_username and "@" in tv_username:
        st.warning("That looks like an email address. TradingView requires your username (e.g. john_trader), not your email. Find it at tradingview.com / Profile.")

    tv_col_a, tv_col_b = st.columns(2)
    if tv_col_a.button("Save TradingView Credentials", type="primary",
                        use_container_width=True, key="tv_save_btn"):
        st.session_state["_tv_username"] = tv_username
        st.session_state["_tv_password"] = tv_password
        save_settings()
        if tv_username:
            st.success(f"TradingView credentials saved for: {tv_username}")
        else:
            st.info("Credentials cleared - using anonymous TradingView access.")

    if tv_col_b.button("Test Connection", use_container_width=True, key="tv_test_btn"):
        with st.spinner("Testing TradingView connection..."):
            try:
                from tvDatafeed import TvDatafeed, Interval as TvInterval
                _use_anon = not tv_username
                _tv = TvDatafeed(
                    username=tv_username or None,
                    password=tv_password or None,
                )
                _test = _tv.get_hist("BTCUSD", "BINANCE", interval=TvInterval.in_1_hour, n_bars=5)
                if _test is not None and not _test.empty:
                    _mode = "anonymous" if _use_anon else f"authenticated as @{tv_username}"
                    st.success(f"TradingView connected ({_mode}) - {len(_test)} bars received.")
                else:
                    st.warning("Connected but no data for BTCUSD/BINANCE. The feed is working - try a different symbol.")
            except ImportError:
                st.error("tvdatafeed-enhanced not installed. Run: docker compose build frontend")
            except Exception as e:
                _err = str(e)
                if any(x in _err.lower() for x in ["login", "credentials", "password"]):
                    st.error(
                        "TradingView login failed. Common causes:\n"
                        "1. You used your email instead of your username - use @username from tradingview.com/profile\n"
                        "2. Wrong password\n"
                        "3. 2FA is enabled (not supported by this library)\n\n"
                        "Fix: clear both fields and Save to use anonymous mode."
                    )
                else:
                    st.error(f"TradingView connection failed: {_err}. Try clearing credentials to use anonymous access.")

    _tv_status = bool(st.session_state.get("_tv_username", ""))
    st.markdown(_status_badge(_tv_status,
        f"Authenticated as @{st.session_state.get('_tv_username', '')}",
        "Anonymous access (no login) - works for most symbols"
    ), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    #  ALERT CHANNELS
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">ALERT CHANNELS — Push Notifications</div>', unsafe_allow_html=True)

    at1, at2, at3 = st.tabs(["WhatsApp (Free)", "Email (Gmail)", "Telegram"])

    with at1:
        st.markdown("""
        <div class="acct-how">
          Free via CallMeBot — one-time setup:<br>
          1. Save <b>+34 644 69 87 99</b> as a contact named "CallMeBot" in WhatsApp<br>
          2. Send this exact message to that number: <b>I allow callmebot to send me messages</b><br>
          3. You receive your <b>API Key</b> via WhatsApp within seconds<br>
          4. Enter your phone number and the key below (limit: ~50 messages/day free)
        </div>
        """, unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        wa_phone = c1.text_input("Phone (international, no +)", placeholder="9715XXXXXXXX", key="wa_ph_acct")
        wa_key   = c2.text_input("CallMeBot API Key",           placeholder="1234567",      key="wa_key_acct")
        if st.button("Save WhatsApp", key="wa_save_acct"):
            st.session_state["_whatsapp_phone"] = wa_phone
            st.session_state["_whatsapp_api_key"] = wa_key
            _rebuild_alerts(wa_phone=wa_phone, wa_key=wa_key)
            save_settings()
            st.success("WhatsApp saved! Alerts will be sent to your number.")

    with at2:
        st.markdown("""
        <div class="acct-how">
          Gmail setup: enable 2-Factor Authentication → Google Account → Security<br>
          → App Passwords → generate a password for "Mail" → paste below<br>
          (uses your regular Gmail address, the App Password replaces your login password)
        </div>
        """, unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        em_from = c1.text_input("From (Gmail)",    placeholder="you@gmail.com",    key="em_from_acct")
        em_pass = c2.text_input("App Password",    placeholder="xxxx xxxx xxxx xxxx", type="password", key="em_pass_acct")
        em_to   = c3.text_input("To (recipient)",  placeholder="alerts@example.com", key="em_to_acct")
        if st.button("Save Email", key="em_save_acct"):
            st.session_state["_email_sender"] = em_from
            st.session_state["_email_recipient"] = em_to
            _rebuild_alerts(em_s=em_from, em_p=em_pass, em_r=em_to)
            save_settings()
            st.success("Email alerts saved!")

    with at3:
        st.markdown(
            '<div class="acct-how">'             '1. Message @BotFather on Telegram, run /newbot, follow steps, copy Token.<br>'             '2. Start your bot (search by username, click Start).<br>'             '3. Message @userinfobot to get your Chat ID.'             '</div>',
            unsafe_allow_html=True
        )
        c1, c2 = st.columns(2)
        tg_tok = c1.text_input("Bot Token",  placeholder="1234567:AABBcc...", key="tg_tok_acct")
        tg_cid = c2.text_input("Chat ID",    placeholder="-100123456",        key="tg_cid_acct")
        if st.button("Save Telegram", key="tg_save_acct"):
            st.session_state["_telegram_bot_token"] = tg_tok
            st.session_state["_telegram_chat_id"] = tg_cid
            _rebuild_alerts(tg_t=tg_tok, tg_c=tg_cid)
            save_settings()
            st.success("Telegram alerts saved!")

    st.markdown('</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    #  DISPLAY SETTINGS — Theme
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">🎨 DISPLAY SETTINGS</div>', unsafe_allow_html=True)
    st.markdown(
        '''<div class="acct-sub">
        Choose your preferred colour theme. <b>Light</b> is the default — high-contrast
        for bright environments. <b>Dark</b> is the classic terminal look. The toggle
        in the top-right corner also switches themes instantly.
        </div>''',
        unsafe_allow_html=True,
    )

    _cur_theme = st.session_state.get("theme", "light")
    _theme_col1, _theme_col2 = st.columns(2)

    with _theme_col1:
        _light_active = _cur_theme == "light"
        _light_border = "var(--blue)" if _light_active else "var(--border)"
        _light_bg     = "var(--blue-dim)" if _light_active else "var(--bg-card)"
        _light_clr    = "var(--blue)" if _light_active else "var(--text-sec)"
        _light_sub    = "✓ ACTIVE" if _light_active else "High contrast · Bright environments"
        st.markdown(
            f'''<div style="padding:14px 18px;border-radius:6px;background:{_light_bg};
              border:2px solid {_light_border};font-family:var(--mono);text-align:center">
              <div style="font-size:22px;margin-bottom:4px">&#9728;</div>
              <div style="font-size:11px;font-weight:600;color:{_light_clr};
                letter-spacing:.1em">LIGHT MODE</div>
              <div style="font-size:9px;color:var(--text-mute);margin-top:3px;
                letter-spacing:.06em">{_light_sub}</div>
            </div>''',
            unsafe_allow_html=True,
        )
        if st.button("Switch to Light", key="_acct_light_btn",
                     type="secondary" if _light_active else "primary",
                     use_container_width=True, disabled=_light_active):
            set_setting("theme", "light")  # persist + set session state
            st.rerun()

    with _theme_col2:
        _dark_active = _cur_theme == "dark"
        _dark_border = "var(--blue)" if _dark_active else "var(--border)"
        _dark_bg     = "var(--blue-dim)" if _dark_active else "var(--bg-card)"
        _dark_clr    = "var(--blue)" if _dark_active else "var(--text-sec)"
        _dark_sub    = "✓ ACTIVE" if _dark_active else "Terminal style · Low-light"
        st.markdown(
            f'''<div style="padding:14px 18px;border-radius:6px;background:{_dark_bg};
              border:2px solid {_dark_border};font-family:var(--mono);text-align:center">
              <div style="font-size:22px;margin-bottom:4px">&#9790;</div>
              <div style="font-size:11px;font-weight:600;color:{_dark_clr};
                letter-spacing:.1em">DARK MODE</div>
              <div style="font-size:9px;color:var(--text-mute);margin-top:3px;
                letter-spacing:.06em">{_dark_sub}</div>
            </div>''',
            unsafe_allow_html=True,
        )
        if st.button("Switch to Dark", key="_acct_dark_btn",
                     type="secondary" if _dark_active else "primary",
                     use_container_width=True, disabled=_dark_active):
            set_setting("theme", "dark")  # persist + set session state
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


    # ══════════════════════════════════════════════════════════════════════
    #  TIMEZONE SETTINGS
    # ══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="acct-section">', unsafe_allow_html=True)
    st.markdown('<div class="acct-title">🕐 TIMEZONE SETTINGS</div>', unsafe_allow_html=True)
    st.markdown(
        f'''<div class="acct-sub">
        Your DigitalOcean server is in Germany (UTC+1/+2 CET/CEST).
        Set your local UTC offset so all timestamps show in your local time.
        Current setting: <b style="color:var(--amber)">{tz_label()}</b>
        </div>''',
        unsafe_allow_html=True,
    )

    _tz_presets = {
        "UTC+0 (London, Dublin)": 0,
        "UTC+1 (West Africa, Lagos)": 1,
        "UTC+2 (Germany, Cairo)": 2,
        "UTC+3 (Qatar, Saudi Arabia, UAE, Kuwait, Moscow)": 3,
        "UTC+4 (UAE, Baku)": 4,
        "UTC+5 (Pakistan)": 5,
        "UTC+5.5 (India)": 5.5,
        "UTC+6 (Bangladesh)": 6,
        "UTC+7 (Bangkok, Jakarta)": 7,
        "UTC+8 (Singapore, China, HK)": 8,
        "UTC+9 (Japan, Korea)": 9,
        "UTC+10 (Sydney, AEST)": 10,
        "UTC-5 (US Eastern)": -5,
        "UTC-6 (US Central)": -6,
        "UTC-7 (US Mountain)": -7,
        "UTC-8 (US Pacific)": -8,
    }
    _cur_offset = get_tz_offset()
    _preset_labels = list(_tz_presets.keys())
    _preset_values = list(_tz_presets.values())
    # Find closest preset
    _closest_idx = min(range(len(_preset_values)), key=lambda i: abs(_preset_values[i] - _cur_offset))

    _tz_col1, _tz_col2 = st.columns([3, 1])
    _selected_tz = _tz_col1.selectbox(
        "Local Timezone",
        _preset_labels,
        index=_closest_idx,
        key="tz_preset_select",
        help="Select your local timezone. All timestamps in the dashboard will use this offset.",
    )
    _custom_offset = _tz_col2.number_input(
        "Custom offset (h)",
        min_value=-12.0, max_value=14.0,
        value=float(_cur_offset),
        step=0.5, format="%.1f",
        key="tz_custom_offset",
        help="Fine-tune with a custom decimal offset (e.g. 5.5 for India UTC+5:30)",
    )

    if st.button("💾 Save Timezone", type="primary", key="save_tz", use_container_width=False):
        # Custom offset takes priority if it differs from the preset
        _chosen_offset = _tz_presets[_selected_tz]
        if abs(_custom_offset - _chosen_offset) > 0.1:
            _chosen_offset = _custom_offset
        set_setting("tz_offset_hours", _chosen_offset)
        from dashboard.settings_store import tz_label as _tz_label_fn
        st.success(f"✅ Timezone set to {_tz_label_fn()} — all timestamps now show your local time.")
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    # CONNECTION SUMMARY
    st.markdown("---")
    st.markdown("**Connection Summary**")
    cols = st.columns(4)
    services = [
        ("BitOasis",  st.session_state.get("bitoasis_connected", False)),
        ("IBKR",      st.session_state.get("ibkr_connected",     False)),
        ("Discord",   st.session_state.get("discord_connected",  False)),
        ("Alerts",    bool(st.session_state.get("alert_engine") and
                          len(getattr(st.session_state.get("alert_engine"), "active_channels", [])) > 1)),
    ]
    for col, (name, ok) in zip(cols, services):
        col.markdown(
            f'<div style="text-align:center;padding:10px;background:{"rgba(0,201,167,0.1)" if ok else "rgba(30,34,45,1)"};border:1px solid {"rgba(0,201,167,0.3)" if ok else "var(--border)"};border-radius:4px">' +
            f'<div style="font-family:var(--mono);font-size:9px;color:var(--text-mute)">{name}</div>' +
            f'<div style="font-family:var(--mono);font-size:18px;color:{"var(--green)" if ok else "var(--text-mute)"}">{"bullet" if ok else "circ"}</div>' +
            f'<div style="font-family:var(--mono);font-size:9px;color:{"var(--green)" if ok else "var(--red)"}">{"LIVE" if ok else "OFF"}</div>' +
            '</div>',
            unsafe_allow_html=True,
        )


def _rebuild_alerts(em_s="", em_p="", em_r="", dc_url="", wa_phone="", wa_key="", tg_t="", tg_c=""):
    """Rebuild AlertEngine preserving existing settings for unchanged channels."""
    from dashboard.alerts import AlertEngine, EmailConfig, WhatsAppConfig, TelegramConfig, DiscordConfig
    old = st.session_state.get("alert_engine")
    def _g(new, obj, *attrs):
        if new: return new
        if obj:
            v = obj
            for a in attrs:
                v = getattr(v, a, "")
            return v or ""
        return ""
    # Webhook URL: prefer explicit arg, then session state, then existing engine value
    _wh = dc_url or st.session_state.get("_discord_webhook_url", "") or _g("", old, "discord_cfg", "webhook_url")
    st.session_state["alert_engine"] = AlertEngine(
        email_cfg    = EmailConfig(
            _g(em_s, old, "email_cfg", "sender_email"),
            _g(em_p, old, "email_cfg", "sender_password"),
            _g(em_r, old, "email_cfg", "recipient_email"),
        ),
        discord_cfg  = DiscordConfig(_wh),
        whatsapp_cfg = WhatsAppConfig(
            _g(wa_phone, old, "whatsapp_cfg", "phone"),
            _g(wa_key,   old, "whatsapp_cfg", "api_key"),
        ),
        telegram_cfg = TelegramConfig(
            _g(tg_t, old, "telegram_cfg", "bot_token"),
            _g(tg_c, old, "telegram_cfg", "chat_id"),
        ),
    )
