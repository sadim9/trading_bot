"""
brokers/order_manager.py — Trade Execution Orchestrator

Full lifecycle:
  1. Receive signal (symbol, side, qty, price levels, reason)
  2. Send Discord confirmation embed with Confirm / Cancel buttons
  3. Wait up to timeout_seconds for user response
  4. If confirmed → place order via selected broker
  5. Send Discord notification with fill details
  6. Log to trade log

Supports:
  - BitOasis (crypto, AED/USD pairs)
  - Interactive Brokers (stocks, crypto, forex)
  - Both in paper or live mode
  - MA Cross crossover interval configuration

Usage:
    mgr = OrderManager(
        broker=BitOasisBroker(api_key=..., paper_trading=True),
        discord=DiscordConfirmBot(bot_token=..., channel_id=...),
    )
    mgr.handle_signal(
        symbol="BTC-AED", side="buy", quantity=0.01,
        entry_price=250000, stop_loss=245000, take_profit=260000,
        reason="MA9 crossed above MA21 (Golden Cross)", kelly_pct=8.5,
    )
"""

from __future__ import annotations

import csv
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from brokers.base import BaseBroker, OrderRequest, OrderResult
from utils.logger import setup_logger

log = setup_logger("order_manager")

try:
    from brokers.discord_confirm import DiscordConfirmBot
    DISCORD_BOT_OK = True
except ImportError:
    DISCORD_BOT_OK = False


@dataclass
class CrossoverConfig:
    """
    MA Cross interval settings — configurable per broker session.
    These mirror the Pine Script shortlen / longlen inputs.
    """
    short_period: int   = 9        # Fast MA period
    long_period:  int   = 21       # Slow MA period
    interval:     str   = "1h"     # Bar interval: "5m","15m","1h","4h","1d"
    symbol:       str   = "AAPL"   # Ticker
    broker_name:  str   = "bitoasis"  # "bitoasis" | "ibkr"
    enabled:      bool  = True

    def summary(self) -> str:
        return (
            f"SMA{self.short_period}/SMA{self.long_period} "
            f"on {self.symbol} [{self.interval}] "
            f"via {self.broker_name.upper()}"
        )


@dataclass
class TradeRecord:
    timestamp:    str
    symbol:       str
    side:         str
    quantity:     float
    entry_price:  Optional[float]
    stop_loss:    Optional[float]
    take_profit:  Optional[float]
    broker:       str
    order_id:     str
    status:       str
    fill_price:   Optional[float]
    kelly_pct:    float
    reason:       str
    confirmed_by: str
    error:        str = ""


class OrderManager:
    """
    Orchestrates the full trade lifecycle:
    Discord confirm → broker execute → Discord notify → log.
    """

    TRADE_LOG = "logs/executed_trades.csv"
    LOG_COLS  = [
        "timestamp","symbol","side","quantity","entry_price",
        "stop_loss","take_profit","broker","order_id","status",
        "fill_price","kelly_pct","reason","confirmed_by","error",
    ]

    def __init__(
        self,
        broker:          Optional[BaseBroker]       = None,
        discord:         Optional["DiscordConfirmBot"] = None,
        require_confirm: bool = True,
        confirm_timeout: int  = 120,    # seconds
        paper_trading:   bool = True,
    ):
        self.broker          = broker
        self.discord         = discord
        self.require_confirm = require_confirm
        self.confirm_timeout = confirm_timeout
        self.paper_trading   = paper_trading
        self._lock           = threading.Lock()

        Path("logs").mkdir(parents=True, exist_ok=True)
        self._init_log()

        if broker and not broker.is_connected:
            try:
                broker.connect()
            except Exception as e:
                log.warning(f"Broker connect failed: {e}")

    # ── Main entry point ───────────────────────────────────────────────────
    def handle_signal(
        self,
        symbol:       str,
        side:         str,
        quantity:     float,
        entry_price:  Optional[float] = None,
        stop_loss:    Optional[float] = None,
        take_profit:  Optional[float] = None,
        order_type:   str             = "market",
        reason:       str             = "",
        kelly_pct:    float           = 0.0,
        crossover_cfg: Optional[CrossoverConfig] = None,
    ) -> Optional[OrderResult]:
        """
        Process a trade signal end-to-end.

        Args:
            symbol:      Ticker symbol ("AAPL", "BTC-AED")
            side:        "buy" | "sell"
            quantity:    Units to trade
            entry_price: Suggested entry (used for limit orders)
            stop_loss:   SL price level
            take_profit: TP price level
            order_type:  "market" | "limit"
            reason:      Human-readable signal explanation
            kelly_pct:   Kelly-sized position as % of equity
            crossover_cfg: MA crossover settings if this was a cross signal

        Returns:
            OrderResult on execution, None if cancelled/skipped
        """
        if crossover_cfg:
            reason = f"[{crossover_cfg.summary()}] {reason}"

        request = OrderRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=entry_price if order_type == "limit" else None,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=reason[:100],
        )

        log.info(f"Signal received: {request.summary()} | {reason}")

        # ── Discord confirmation ────────────────────────────────────────
        confirmed  = True
        responder  = "auto"

        if self.require_confirm and self.discord:
            try:
                confirmed = self.discord.ask(
                    request=request,
                    signal_reason=reason,
                    kelly_pct=kelly_pct,
                )
                responder = "Discord user"
                if not confirmed:
                    log.info(f"Trade CANCELLED by Discord user: {request.summary()}")
                    self._notify_cancel(request, "User cancelled via Discord")
                    return None
                log.info(f"Trade CONFIRMED via Discord: {request.summary()}")
            except Exception as e:
                log.error(f"Discord confirmation error: {e}. Auto-cancelling for safety.")
                return None
        elif self.require_confirm and not self.discord:
            log.warning(
                "require_confirm=True but no Discord bot configured. "
                "Trade skipped. Configure DiscordConfirmBot or set require_confirm=False."
            )
            return None

        # ── Execute ────────────────────────────────────────────────────
        result = self._execute(request, kelly_pct)

        # ── Notify ────────────────────────────────────────────────────
        if self.discord:
            try:
                self.discord.notify(result, confirmed=True, responder=responder)
            except Exception as e:
                log.warning(f"Discord notify error: {e}")

        # ── Log ────────────────────────────────────────────────────────
        self._log_trade(request, result, kelly_pct, reason, responder)

        return result

    def get_trade_history(self) -> List[TradeRecord]:
        """Read all logged trades from CSV."""
        records = []
        if not os.path.exists(self.TRADE_LOG):
            return records
        with open(self.TRADE_LOG, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                records.append(TradeRecord(**{k: row.get(k, "") for k in self.LOG_COLS if k != "error"}, error=row.get("error", "")))
        return records

    # ── Internal ───────────────────────────────────────────────────────
    def _execute(self, request: OrderRequest, kelly_pct: float) -> OrderResult:
        # Input validation — symbol must not contain path separators or shell chars
        bad_chars = {"/", "\\", ";", "|", "&", "$", "`", "<", ">", "'", chr(34), "{", "}", "[", "]"}
        if any(c in request.symbol for c in bad_chars):
            return OrderResult(
                success=False, broker="validation",
                symbol=request.symbol, side=request.side, quantity=request.quantity,
                error=f"Symbol contains invalid characters: {request.symbol!r}",
                status="rejected",
            )
        if not self.broker:
            log.warning("No broker configured — simulating fill")
            return OrderResult(
                success=True,
                order_id=f"NO-BROKER-{int(time.time())}",
                broker="none",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                filled_price=request.limit_price,
                status="simulated",
            )

        with self._lock:
            try:
                result = self.broker.place_order(request)
                if result.success:
                    log.info(f"Order placed: {result.summary()}")
                else:
                    log.error(f"Order failed: {result.error}")
                return result
            except Exception as e:
                log.error(f"Broker exception: {e}")
                return OrderResult(
                    success=False,
                    broker=getattr(self.broker, "name", "unknown"),
                    symbol=request.symbol,
                    side=request.side,
                    quantity=request.quantity,
                    error=str(e),
                    status="error",
                )

    def _notify_cancel(self, request: OrderRequest, reason: str):
        if self.discord:
            result = OrderResult(
                success=False,
                broker=getattr(self.broker, "name", "none") if self.broker else "none",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                error=reason,
                status="cancelled",
            )
            try:
                self.discord.notify(result, confirmed=False, responder="auto-cancel")
            except Exception:
                pass

    def _init_log(self):
        if not os.path.exists(self.TRADE_LOG):
            with open(self.TRADE_LOG, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=self.LOG_COLS).writeheader()

    def _log_trade(
        self,
        request:   OrderRequest,
        result:    OrderResult,
        kelly_pct: float,
        reason:    str,
        confirmed_by: str,
    ):
        row = {
            "timestamp":    datetime.now().isoformat(),
            "symbol":       request.symbol,
            "side":         request.side,
            "quantity":     request.quantity,
            "entry_price":  request.limit_price or "",
            "stop_loss":    request.stop_loss or "",
            "take_profit":  request.take_profit or "",
            "broker":       result.broker,
            "order_id":     result.order_id,
            "status":       result.status,
            "fill_price":   result.filled_price or "",
            "kelly_pct":    round(kelly_pct, 2),
            "reason":       reason[:200],
            "confirmed_by": confirmed_by,
            "error":        result.error,
        }
        with open(self.TRADE_LOG, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=self.LOG_COLS, extrasaction="ignore").writerow(row)
        log.info(f"Trade logged: {result.order_id} | {result.status}")
