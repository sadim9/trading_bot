"""
dashboard/broker_panel.py — Broker + MA Cross sidebar panel for Streamlit.

Renders the full broker configuration UI:
  - Broker selector (BitOasis / Interactive Brokers)
  - API credentials (stored in session_state only, never logged)
  - MA Cross crossover settings (short/long period + interval)
  - Paper vs Live toggle
  - Discord confirmation toggle + timeout
  - Auto-trade on crossover toggle
  - Trade history table
"""

import streamlit as st
from brokers.order_manager import OrderManager, CrossoverConfig


def render_broker_panel(df, rec, ma_cross_result=None):
    """
    Render the full broker panel in the Streamlit sidebar.
    Returns an OrderManager instance (may be None if not configured).
    """
    st.sidebar.markdown("---")
    st.sidebar.markdown("## 🔌 Auto-Trade")
    st.sidebar.caption("⚠️ Live trading: real money at risk. Test in paper mode first.")

    # ── Broker selector ───────────────────────────────────────────────
    broker_name = st.sidebar.selectbox(
        "Broker", ["Paper (no broker)", "BitOasis", "Interactive Brokers"],
        key="broker_sel"
    )

    paper = broker_name == "Paper (no broker)"
    broker_obj = None

    if broker_name == "BitOasis":
        with st.sidebar.expander("BitOasis Credentials", expanded=False):
            bo_key    = st.text_input("API Key",    type="password", key="bo_key")
            bo_secret = st.text_input("API Secret", type="password", key="bo_secret")
            bo_paper  = st.toggle("Paper Trading", value=True, key="bo_paper")
            if st.button("Connect BitOasis", use_container_width=True):
                try:
                    from brokers.bitoasis import BitOasisBroker
                    b = BitOasisBroker(api_key=bo_key, api_secret=bo_secret, paper_trading=bo_paper)
                    b.connect()
                    st.session_state["broker_obj"] = b
                    st.success(f"BitOasis connected ({'PAPER' if bo_paper else 'LIVE'})")
                except Exception as e:
                    st.error(f"Connection failed: {e}")

    elif broker_name == "Interactive Brokers":
        with st.sidebar.expander("IBKR Connection", expanded=False):
            ib_host   = st.text_input("TWS Host",  value="127.0.0.1", key="ib_host")
            ib_port   = st.number_input("Port", value=7497,
                                        help="Paper=7497, Live=7496, GW Paper=4002, GW Live=4001",
                                        key="ib_port")
            ib_client = st.number_input("Client ID", value=1, key="ib_cid")
            ib_paper  = st.toggle("Paper Mode", value=True, key="ib_paper")
            if st.button("Connect IBKR", use_container_width=True):
                try:
                    from brokers.interactive_brokers import InteractiveBrokersBroker
                    b = InteractiveBrokersBroker(
                        host=ib_host, port=int(ib_port),
                        client_id=int(ib_client), paper_trading=ib_paper
                    )
                    b.connect()
                    st.session_state["broker_obj"] = b
                    st.success(f"IBKR connected ({'PAPER' if ib_paper else 'LIVE'})")
                except Exception as e:
                    st.error(f"Connection failed: {e}")

    broker_obj = st.session_state.get("broker_obj")
    if broker_obj:
        st.sidebar.success(f"✅ {broker_obj}")

    # ── MA Cross crossover settings ───────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📈 MA Crossover Config")

    short_p   = st.sidebar.number_input("Short MA Period", value=9,  min_value=2, max_value=200, key="ma_short")
    long_p    = st.sidebar.number_input("Long MA Period",  value=21, min_value=3, max_value=500, key="ma_long")
    ma_ivl    = st.sidebar.selectbox(
        "Crossover Interval",
        ["1m","5m","15m","30m","1h","4h","1d","1wk"],
        index=4, key="ma_ivl",
        help="Which bar interval to watch for the cross"
    )
    auto_trade_cross = st.sidebar.toggle(
        "Auto-trade on MA Cross", value=False, key="auto_cross",
        help="Fire a trade order each time a golden/death cross is detected"
    )

    cross_cfg = CrossoverConfig(
        short_period=int(short_p),
        long_period=int(long_p),
        interval=ma_ivl,
        symbol=st.session_state.get("symbol", "AAPL"),
        broker_name=broker_name.lower().replace(" ", "_"),
        enabled=auto_trade_cross,
    )

    # Show current MA values
    if ma_cross_result:
        sub = ma_cross_result.sub_scores or {}
        sma_s = sub.get("short_ma", 0)
        sma_l = sub.get("long_ma",  0)
        cup   = bool(sub.get("cross_up",   0))
        cdn   = bool(sub.get("cross_down", 0))
        cross_status = "🟡 No cross" if not cup and not cdn else ("🟢 GOLDEN CROSS" if cup else "🔴 DEATH CROSS")
        st.sidebar.metric(f"SMA{int(short_p)}", f"{sma_s:.4f}")
        st.sidebar.metric(f"SMA{int(long_p)}",  f"{sma_l:.4f}")
        st.sidebar.info(cross_status)

    # ── Discord confirmation ──────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💬 Discord Confirmation")
    require_confirm = st.sidebar.toggle("Require Discord confirm", value=True, key="req_confirm")
    confirm_timeout = st.sidebar.slider("Timeout (seconds)", 30, 300, 120, 30, key="conf_timeout")

    dc_token    = st.sidebar.text_input("Bot Token",   type="password", key="dc_tok", placeholder="Discord bot token")
    dc_channel  = st.sidebar.text_input("Channel ID",  key="dc_chan",   placeholder="Discord channel ID")

    discord_bot = st.session_state.get("discord_confirm_bot")
    if st.sidebar.button("Connect Discord Bot", use_container_width=True):
        try:
            from brokers.discord_confirm import DiscordConfirmBot
            bot = DiscordConfirmBot(
                bot_token=dc_token,
                channel_id=int(dc_channel),
                timeout_seconds=confirm_timeout,
            )
            st.session_state["discord_confirm_bot"] = bot
            discord_bot = bot
            st.sidebar.success("Discord bot connected!")
        except Exception as e:
            st.sidebar.error(f"Discord error: {e}")

    # ── Build OrderManager ────────────────────────────────────────────
    order_mgr = None
    if broker_obj or not require_confirm:
        order_mgr = OrderManager(
            broker=broker_obj,
            discord=discord_bot,
            require_confirm=require_confirm,
            confirm_timeout=confirm_timeout,
            paper_trading=paper,
        )

    # ── Fire MA cross trade if auto-trade enabled ─────────────────────
    if (
        auto_trade_cross
        and order_mgr
        and ma_cross_result
        and ma_cross_result.signal in ("BUY", "SELL")
        and (ma_cross_result.sub_scores or {}).get("cross_up" if ma_cross_result.signal == "BUY" else "cross_down", 0)
    ):
        symbol   = cross_cfg.symbol
        side     = "buy" if ma_cross_result.signal == "BUY" else "sell"
        close_px = float(df["Close"].iloc[-1]) if df is not None else 0.0
        sl_pct   = 0.02
        tp_pct   = 0.04
        sl_price = close_px * (1 - sl_pct) if side == "buy" else close_px * (1 + sl_pct)
        tp_price = close_px * (1 + tp_pct) if side == "buy" else close_px * (1 - tp_pct)
        qty      = 1.0   # default; override with Kelly in production

        cross_type = "Golden Cross" if side == "buy" else "Death Cross"
        reason = (
            f"{cross_type}: SMA{cross_cfg.short_period} crossed {'above' if side == 'buy' else 'below'} "
            f"SMA{cross_cfg.long_period} on {ma_ivl} chart"
        )

        st.sidebar.warning(f"🔔 {cross_type} detected on {symbol}!")

        if require_confirm and not discord_bot:
            st.sidebar.error(
                "Auto-trade requires Discord bot for confirmation. "
                "Configure and connect the Discord bot above."
            )
        else:
            if st.sidebar.button(f"🚀 Send to Discord & Execute", type="primary"):
                with st.spinner("Sending confirmation to Discord..."):
                    result = order_mgr.handle_signal(
                        symbol=symbol,
                        side=side,
                        quantity=qty,
                        entry_price=close_px,
                        stop_loss=sl_price,
                        take_profit=tp_price,
                        reason=reason,
                        crossover_cfg=cross_cfg,
                    )
                if result and result.success:
                    st.sidebar.success(f"Trade executed: {result.summary()}")
                elif result:
                    st.sidebar.error(f"Trade failed: {result.error}")
                else:
                    st.sidebar.info("Trade cancelled or pending confirmation.")

    # ── Trade history ─────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📋 Executed Trades")
    import os, pandas as pd
    trade_log = "logs/executed_trades.csv"
    if os.path.exists(trade_log):
        tdf = pd.read_csv(trade_log, encoding="utf-8-sig")
        if not tdf.empty:
            st.sidebar.dataframe(
                tdf[["timestamp","symbol","side","quantity","fill_price","status","broker"]].tail(10).iloc[::-1],
                use_container_width=True, hide_index=True
            )
        else:
            st.sidebar.caption("No executed trades yet.")
    else:
        st.sidebar.caption("No trade log found.")

    return order_mgr, cross_cfg
