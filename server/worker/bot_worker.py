"""
server/worker/bot_worker.py -- Background bot worker process.

Runs continuously, polling configured symbols at the configured interval,
writing signals to the database, and dispatching Discord/Telegram/WhatsApp
notifications independently of the dashboard UI being open.

Notification credentials are read from the shared user_settings.json file
(written by the Streamlit dashboard, stored in the trading_logs volume).
Watchlist per-symbol settings are read from watchlist_settings.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

log = logging.getLogger("bot_worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

POLL_INTERVAL  = int(os.getenv("BOT_POLL_INTERVAL_SECONDS", "60"))
DATA_SOURCE    = os.getenv("BOT_DEFAULT_SOURCE", "yfinance")
WORKER_USER_ID = os.getenv("BOT_WORKER_USER_ID", "")
STRATEGY_MODE  = os.getenv("BOT_STRATEGY_MODE", "markov_multi")

_SETTINGS_DIR   = Path(os.getenv("SETTINGS_DIR", "/app/logs"))
_SETTINGS_FILE  = _SETTINGS_DIR / "user_settings.json"
_WATCHLIST_FILE = _SETTINGS_DIR / "watchlist_settings.json"

_running = True
_last_signal: dict = {}
COOLDOWN = 300


def _handle_shutdown(signum, frame):
    global _running
    log.info(f"Received signal {signum}, shutting down worker gracefully...")
    _running = False


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT,  _handle_shutdown)


def _load_json(path: Path) -> dict:
    for p in [path, Path(".cache") / path.name]:
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _build_alert_engine(settings: dict):
    from dashboard.alerts import (
        AlertEngine, EmailConfig, DiscordConfig, WhatsAppConfig, TelegramConfig,
    )
    return AlertEngine(
        email_cfg    = EmailConfig(
            sender_email    = settings.get("_email_sender", ""),
            sender_password = settings.get("_email_password", ""),
            recipient_email = settings.get("_email_recipient", ""),
        ),
        discord_cfg  = DiscordConfig(webhook_url=settings.get("_discord_webhook_url", "")),
        whatsapp_cfg = WhatsAppConfig(
            phone   = settings.get("_whatsapp_phone", ""),
            api_key = settings.get("_whatsapp_api_key", ""),
        ),
        telegram_cfg = TelegramConfig(
            bot_token = settings.get("_telegram_bot_token", ""),
            chat_id   = settings.get("_telegram_chat_id", ""),
        ),
    )


def _should_notify(symbol: str, sig: str) -> bool:
    last_sig, last_ts = _last_signal.get(symbol, ("", 0.0))
    return not (last_sig == sig and (time.time() - last_ts) < COOLDOWN)


def _record_notify(symbol: str, sig: str):
    _last_signal[symbol] = (sig, time.time())


async def run_signal_cycle(symbols: list, watchlist_cfg: dict, engine, settings: dict = None):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from server.db.database import AsyncSessionLocal
    from server.db.models import Signal, Trade, OHLCVBar

    try:
        from config import CONFIG
        from data.ingestion import load_data
        from signals.aggregator import SignalAggregator
        from risk.manager import RiskManager
    except ImportError as e:
        log.error(f"Import error: {e}")
        return

    risk_mgr = RiskManager(CONFIG.risk)

    async with AsyncSessionLocal() as db:
        for symbol in symbols:
            try:
                sym_cfg   = watchlist_cfg.get(symbol, {})
                sym_mode  = sym_cfg.get("strategy", STRATEGY_MODE)
                _src_ov   = sym_cfg.get("source_override", "(default)")
                sym_src   = _src_ov if _src_ov != "(default)" else sym_cfg.get("source", DATA_SOURCE)
                _ivl_ov   = sym_cfg.get("interval_override", "(default)")
                sym_ivl   = _ivl_ov if _ivl_ov != "(default)" else CONFIG.data.default_interval
                do_notify = sym_cfg.get("notify", True)

                log.info(f"Processing {symbol} [mode={sym_mode}, src={sym_src}]")
                df  = load_data(symbol, interval=sym_ivl,
                                period=CONFIG.data.default_period, source=sym_src)
                agg = SignalAggregator(CONFIG, strategy_mode=sym_mode)
                rec = agg.analyse(df, symbol)
                check = risk_mgr.check(
                    symbol=symbol, signal=rec.signal,
                    entry=rec.entry_price, stop_loss=rec.stop_loss,
                    take_profit=rec.take_profit, size_pct=rec.position_size_pct, df=df,
                )

                # Upsert OHLCV bars
                try:
                    import uuid as _uuid
                    _ivl  = CONFIG.data.default_interval
                    _rows = []
                    for _ts, _row in df.tail(500).iterrows():
                        _dt = _ts.to_pydatetime() if hasattr(_ts, "to_pydatetime") else _ts
                        _dt = _dt.replace(tzinfo=None)
                        _rows.append({
                            "id":       str(_uuid.uuid4()),
                            "symbol":   symbol,
                            "interval": _ivl,
                            "source":   sym_src,
                            "ts":       _dt,
                            "open":     float(_row.get("Open",   _row.get("open",   0))),
                            "high":     float(_row.get("High",   _row.get("high",   0))),
                            "low":      float(_row.get("Low",    _row.get("low",    0))),
                            "close":    float(_row.get("Close",  _row.get("close",  0))),
                            "volume":   float(_row.get("Volume", _row.get("volume", 0)) or 0),
                        })
                    if _rows:
                        stmt = pg_insert(OHLCVBar).values(_rows)
                        stmt = stmt.on_conflict_do_update(
                            constraint="uq_ohlcv_bar",
                            set_={
                                "open":   stmt.excluded.open,
                                "high":   stmt.excluded.high,
                                "low":    stmt.excluded.low,
                                "close":  stmt.excluded.close,
                                "volume": stmt.excluded.volume,
                            },
                        )
                        await db.execute(stmt)
                        log.info(f"  {symbol}: upserted {len(_rows)} OHLCV bars")
                except Exception as _e:
                    log.warning(f"  {symbol}: OHLCV save failed: {_e}")

                # Persist signal record
                sig_rec = Signal(
                    user_id           = WORKER_USER_ID or None,
                    symbol            = symbol,
                    signal_type       = rec.signal,
                    composite_score   = rec.composite_score,
                    entry_price       = rec.entry_price,
                    stop_loss         = rec.stop_loss,
                    take_profit       = rec.take_profit,
                    position_size_pct = rec.position_size_pct,
                    risk_check_passed = check.approved,
                    risk_reasons      = check.reasons,
                    data_source       = sym_src,
                    interval          = CONFIG.data.default_interval,
                )
                db.add(sig_rec)
                log.info(f"  {symbol}: {rec.signal} score={rec.composite_score:.3f}")

                # Persist to Signal Alert Log CSV (read by dashboard alert log tab)
                if rec.signal in ("BUY", "SELL"):
                    try:
                        from dashboard.alert_log import log_alert
                        _planned = float((settings or {}).get("planned_trade_amount", 0.0))
                        log_alert(
                            symbol         = symbol,
                            signal         = rec.signal,
                            price          = rec.entry_price,
                            strategy_mode  = sym_mode,
                            score          = rec.composite_score,
                            confidence     = rec.confidence_pct,
                            planned_amount = _planned,
                            entry_price    = rec.entry_price,
                            stop_loss      = rec.stop_loss,
                            take_profit    = rec.take_profit,
                        )
                        log.info(f"  {symbol}: alert logged to CSV")
                    except Exception as _le:
                        log.warning(f"  {symbol}: alert log write failed: {_le}")

                # Send notifications
                if (do_notify and engine is not None
                        and rec.signal in ("BUY", "SELL")
                        and _should_notify(symbol, rec.signal)):
                    close_px = float(df["Close"].iloc[-1]) if len(df) > 0 else rec.entry_price
                    reason = (
                        f"Score: {rec.composite_score:+.3f} | "
                        f"Conf: {rec.confidence_pct:.0f}% | "
                        f"Mode: {sym_mode} | "
                        f"Entry: {rec.entry_price:.4f} | "
                        f"SL: {rec.stop_loss:.4f} | "
                        f"TP: {rec.take_profit:.4f}"
                    )
                    try:
                        alert = engine.fire(
                            symbol=symbol, signal=rec.signal,
                            price=close_px, reason=reason,
                            confidence=rec.confidence_pct,
                        )
                        if alert:
                            _record_notify(symbol, rec.signal)
                            log.info(f"  {symbol}: notified via {engine.active_channels}")
                    except Exception as _ne:
                        log.warning(f"  {symbol}: notification failed: {_ne}")

                # Auto paper-trade
                if (check.approved and rec.signal in ("BUY", "SELL")
                        and WORKER_USER_ID
                        and os.getenv("BOT_AUTO_PAPER_TRADE", "false").lower() == "true"):
                    trade = Trade(
                        user_id     = WORKER_USER_ID,
                        signal_id   = sig_rec.id,
                        symbol      = symbol,
                        side        = rec.signal.lower(),
                        order_type  = "market",
                        quantity    = 1.0,
                        entry_price = rec.entry_price,
                        stop_loss   = rec.stop_loss,
                        take_profit = rec.take_profit,
                        strategy    = "aggregated",
                        broker      = "paper",
                        is_paper    = True,
                        status      = "open",
                    )
                    db.add(trade)
                    log.info(f"  {symbol}: auto paper trade created")

                    # Also write to CSV so the trade journal fallback log stays current
                    try:
                        from brokers.order_manager import OrderManager
                        _mgr = OrderManager(paper_trading=True)
                        _mgr.log_manual_trade(
                            symbol      = symbol,
                            side        = rec.signal.lower(),
                            quantity    = 1.0,
                            entry_price = rec.entry_price,
                            stop_loss   = rec.stop_loss,
                            take_profit = rec.take_profit,
                            broker      = "paper",
                            reason      = (
                                f"Auto paper trade | score={rec.composite_score:+.3f} | "
                                f"conf={rec.confidence_pct:.0f}% | mode={sym_mode}"
                            ),
                        )
                    except Exception as _csv_err:
                        log.warning(f"  {symbol}: CSV log write failed: {_csv_err}")

                # Auto-close open paper trades in the CSV when SL or TP is reached
                if os.getenv("BOT_AUTO_PAPER_TRADE", "false").lower() == "true":
                    try:
                        from brokers.order_manager import OrderManager
                        _mgr = OrderManager(paper_trading=True)
                        _cur_px = float(df["Close"].iloc[-1])
                        _history = _mgr.get_trade_history()
                        for _t in _history:
                            if (
                                _t.get("status") == "open"
                                and _t.get("symbol", "").upper() == symbol.upper()
                            ):
                                _oid  = _t.get("order_id", "")
                                _side = _t.get("side", "buy").lower()
                                _ep   = float(_t.get("fill_price") or _t.get("entry_price") or 0)
                                _sl   = float(_t.get("stop_loss") or 0)
                                _tp   = float(_t.get("take_profit") or 0)
                                if not (_ep and _oid):
                                    continue
                                _exit_reason = None
                                _exit_px     = None
                                if _side == "buy":
                                    if _sl and _cur_px <= _sl:
                                        _exit_reason, _exit_px = "stop_loss", _sl
                                    elif _tp and _cur_px >= _tp:
                                        _exit_reason, _exit_px = "take_profit", _tp
                                else:
                                    if _sl and _cur_px >= _sl:
                                        _exit_reason, _exit_px = "stop_loss", _sl
                                    elif _tp and _cur_px <= _tp:
                                        _exit_reason, _exit_px = "take_profit", _tp
                                if _exit_reason and _exit_px:
                                    _closed = _mgr.close_trade(_oid, _exit_px, _exit_reason)
                                    if _closed:
                                        _side_up = _side.upper()
                                        _pnl_dir = (_exit_px - _ep) if _side == "buy" else (_ep - _exit_px)
                                        log.info(
                                            f"  {symbol}: auto-closed paper trade {_oid} "
                                            f"[{_side_up}] at {_exit_px:.4f} via {_exit_reason} "
                                            f"| P&L: {_pnl_dir:+.4f}"
                                        )
                    except Exception as _ac_err:
                        log.warning(f"  {symbol}: auto-close check failed: {_ac_err}")

            except Exception as e:
                log.warning(f"  Failed {symbol}: {e}")

        await db.commit()


async def main():
    from config import CONFIG
    log.info(f"Bot worker starting | poll={POLL_INTERVAL}s | default_mode={STRATEGY_MODE}")

    while _running:
        cycle_start = datetime.now(timezone.utc)
        log.info(f"--- Cycle start: {cycle_start.isoformat()} ---")

        settings      = _load_json(_SETTINGS_FILE)
        watchlist_cfg = _load_json(_WATCHLIST_FILE)

        wl_symbols  = list(watchlist_cfg.keys())
        cfg_symbols = CONFIG.data.default_symbols
        all_symbols = wl_symbols + [s for s in cfg_symbols if s not in wl_symbols]
        if not all_symbols:
            all_symbols = cfg_symbols

        engine = None
        try:
            engine = _build_alert_engine(settings)
            channels = engine.active_channels
            if channels == ["screen"]:
                log.info("No push notification channels configured")
            else:
                log.info(f"Push channels active: {channels}")
        except Exception as _ae:
            log.warning(f"Alert engine init failed: {_ae}")

        log.info(f"Symbols this cycle: {all_symbols}")
        await run_signal_cycle(all_symbols, watchlist_cfg, engine, settings)

        elapsed   = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        sleep_for = max(0, POLL_INTERVAL - elapsed)
        log.info(f"--- Done in {elapsed:.1f}s, sleeping {sleep_for:.0f}s ---")
        await asyncio.sleep(sleep_for)

    log.info("Bot worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
