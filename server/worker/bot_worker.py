"""
server/worker/bot_worker.py — Background bot worker process.

Runs continuously, polling configured symbols at the configured interval,
writing signals to the database, and optionally placing paper trades.

Run standalone:
    python -m server.worker.bot_worker

Or via Docker Compose (see docker-compose.yml `worker` service).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import signal
from datetime import datetime, timezone

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

log = logging.getLogger("bot_worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

POLL_INTERVAL = int(os.getenv("BOT_POLL_INTERVAL_SECONDS", "60"))
DATA_SOURCE   = os.getenv("BOT_DEFAULT_SOURCE", "yfinance")
WORKER_USER_ID = os.getenv("BOT_WORKER_USER_ID", "")   # admin user ID for DB writes

_running = True


def _handle_shutdown(signum, frame):
    global _running
    log.info(f"Received signal {signum}, shutting down worker gracefully...")
    _running = False


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT,  _handle_shutdown)


async def run_signal_cycle(symbols: list[str]):
    """Generate signals for all configured symbols and persist to DB."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from server.db.database import AsyncSessionLocal
    from server.db.models import Signal, Trade

    try:
        from config import CONFIG
        from data.ingestion import load_data
        from signals.aggregator import SignalAggregator
        from risk.manager import RiskManager
    except ImportError as e:
        log.error(f"Failed to import bot modules: {e}")
        return

    agg      = SignalAggregator(CONFIG)
    risk_mgr = RiskManager(CONFIG.risk)

    async with AsyncSessionLocal() as db:
        for symbol in symbols:
            try:
                log.info(f"Processing {symbol}...")
                df  = load_data(symbol, interval=CONFIG.data.default_interval,
                                period=CONFIG.data.default_period, source=DATA_SOURCE)
                rec = agg.analyse(df, symbol)
                check = risk_mgr.check(
                    symbol=symbol, signal=rec.signal,
                    entry=rec.entry_price, stop_loss=rec.stop_loss,
                    take_profit=rec.take_profit, size_pct=rec.position_size_pct, df=df,
                )

                sig = Signal(
                    user_id            = WORKER_USER_ID or None,
                    symbol             = symbol,
                    signal_type        = rec.signal,
                    composite_score    = rec.composite_score,
                    entry_price        = rec.entry_price,
                    stop_loss          = rec.stop_loss,
                    take_profit        = rec.take_profit,
                    position_size_pct  = rec.position_size_pct,
                    risk_check_passed  = check.approved,
                    risk_reasons       = check.reasons,
                    data_source        = DATA_SOURCE,
                    interval           = CONFIG.data.default_interval,
                )
                db.add(sig)
                log.info(f"  {symbol}: {rec.signal} (score={rec.composite_score:.3f})")

                # Auto paper-trade on strong signals
                if (
                    check.approved
                    and rec.signal in ("BUY", "SELL")
                    and WORKER_USER_ID
                    and os.getenv("BOT_AUTO_PAPER_TRADE", "false").lower() == "true"
                ):
                    trade = Trade(
                        user_id     = WORKER_USER_ID,
                        signal_id   = sig.id,
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
                    log.info(f"  Auto paper trade created: {trade}")

            except Exception as e:
                log.warning(f"  Failed to process {symbol}: {e}")

        await db.commit()


async def main():
    from config import CONFIG
    symbols = CONFIG.data.default_symbols

    log.info(f"Bot worker starting | symbols={symbols} | interval={POLL_INTERVAL}s")

    while _running:
        cycle_start = datetime.now(timezone.utc)
        log.info(f"--- Cycle start: {cycle_start.isoformat()} ---")
        await run_signal_cycle(symbols)
        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        sleep_for = max(0, POLL_INTERVAL - elapsed)
        log.info(f"--- Cycle done in {elapsed:.1f}s, sleeping {sleep_for:.0f}s ---")
        await asyncio.sleep(sleep_for)

    log.info("Bot worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
