"""
brokers/order_manager.py — Trade Execution Orchestrator

Full lifecycle:
  1. Receive signal (symbol, side, qty, price levels, reason)
  2. Send Discord confirmation embed with Confirm / Cancel buttons
  3. Wait up to timeout_seconds for user response
  4. If confirmed -> place order via selected broker
  5. Send Discord notification with fill details
  6. Log to trade log

Also provides trade journal helpers:
  - log_manual_trade()  -- record a trade placed outside the bot
  - close_trade()       -- mark an open trade closed with P&L calculation
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
    short_period: int  = 9
    long_period:  int  = 21
    interval:     str  = "1h"
    symbol:       str  = "AAPL"
    broker_name:  str  = "bitoasis"
    enabled:      bool = True

    def summary(self) -> str:
        return (
            f"SMA{self.short_period}/SMA{self.long_period} "
            f"on {self.symbol} [{self.interval}] "
            f"via {self.broker_name.upper()}"
        )


@dataclass
class TradeRecord:
    timestamp:   str
    symbol:      str
    side:        str
    quantity:    float
    entry_price: Optional[float]
    stop_loss:   Optional[float]
    take_profit: Optional[float]
    broker:      str
    order_id:    str
    status:      str
    fill_price:  Optional[float]
    kelly_pct:   float
    reason:      str
    confirmed_by: str
    closed_at:   str = ""
    exit_price:  Optional[float] = None
    pnl:         Optional[float] = None
    pnl_pct:     Optional[float] = None
    exit_reason: str = ""
    error:       str = ""


class OrderManager:
    """
    Orchestrates the full trade lifecycle:
    Discord confirm -> broker execute -> Discord notify -> log.
    """

    TRADE_LOG = "logs/executed_trades.csv"
    LOG_COLS  = [
        "timestamp", "symbol", "side", "quantity", "entry_price",
        "stop_loss", "take_profit", "broker", "order_id", "status",
        "fill_price", "kelly_pct", "reason", "confirmed_by",
        "closed_at", "exit_price", "pnl", "pnl_pct", "exit_reason", "error",
    ]

    def __init__(
        self,
        broker:          Optional[BaseBroker]          = None,
        discord:         Optional["DiscordConfirmBot"] = None,
        require_confirm: bool = True,
        confirm_timeout: int  = 120,
        paper_trading:   bool = True,
        api_client       = None,   # dashboard.api_client.APIClient — optional DB write
    ):
        self.broker          = broker
        self.discord         = discord
        self.require_confirm = require_confirm
        self.confirm_timeout = confirm_timeout
        self.paper_trading   = paper_trading
        self.api_client      = api_client
        self._lock           = threading.Lock()

        Path("logs").mkdir(parents=True, exist_ok=True)
        self._init_log()

        if broker and not broker.is_connected:
            try:
                broker.connect()
            except Exception as e:
                log.warning(f"Broker connect failed: {e}")

    # ------------------------------------------------------------------ #
    #  Main signal handler                                                 #
    # ------------------------------------------------------------------ #
    def handle_signal(
        self,
        symbol:        str,
        side:          str,
        quantity:      float,
        entry_price:   Optional[float] = None,
        stop_loss:     Optional[float] = None,
        take_profit:   Optional[float] = None,
        order_type:    str             = "market",
        reason:        str             = "",
        kelly_pct:     float           = 0.0,
        crossover_cfg: Optional[CrossoverConfig] = None,
    ) -> Optional[OrderResult]:
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

        confirmed = True
        responder = "auto"

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
                "Trade skipped. Set require_confirm=False or connect Discord."
            )
            return None

        result = self._execute(request, kelly_pct)

        if self.discord:
            try:
                self.discord.notify(result, confirmed=True, responder=responder)
            except Exception as e:
                log.warning(f"Discord notify error: {e}")

        self._log_trade(request, result, kelly_pct, reason, responder)
        return result

    # ------------------------------------------------------------------ #
    #  Trade journal helpers                                               #
    # ------------------------------------------------------------------ #
    def get_trade_history(self) -> List[dict]:
        rows = []
        if not os.path.exists(self.TRADE_LOG):
            return rows
        with open(self.TRADE_LOG, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rows.append(dict(row))
        return rows

    def log_manual_trade(
        self,
        symbol:      str,
        side:        str,
        quantity:    float,
        entry_price: float,
        stop_loss:   Optional[float] = None,
        take_profit: Optional[float] = None,
        broker:      str = "manual",
        reason:      str = "Manual entry",
    ) -> str:
        """Log a trade placed outside the bot for journalling. Returns order_id."""
        order_id = f"MANUAL-{int(time.time())}"
        row = {
            "timestamp":    datetime.now().isoformat(),
            "symbol":       symbol.upper(),
            "side":         side.lower(),
            "quantity":     quantity,
            "entry_price":  entry_price,
            "stop_loss":    stop_loss if stop_loss else "",
            "take_profit":  take_profit if take_profit else "",
            "broker":       broker,
            "order_id":     order_id,
            "status":       "open",
            "fill_price":   entry_price,
            "kelly_pct":    0.0,
            "reason":       reason[:200],
            "confirmed_by": "manual",
            "closed_at":    "",
            "exit_price":   "",
            "pnl":          "",
            "pnl_pct":      "",
            "exit_reason":  "",
            "error":        "",
        }
        with open(self.TRADE_LOG, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=self.LOG_COLS, extrasaction="ignore").writerow(row)
        log.info(f"Manual trade logged: {order_id} {side.upper()} {quantity} {symbol.upper()} @ {entry_price}")

        # Dual-write to database (best-effort)
        db_id = self._log_to_db({
            **row,
            "order_type": "market",
            "is_paper":   self.paper_trading,
        })
        return db_id or order_id

    def close_trade(self, order_id: str, exit_price: float, exit_reason: str = "manual") -> bool:
        """Mark an open trade as closed, compute P&L. Returns True if found."""
        if not os.path.exists(self.TRADE_LOG):
            return False

        rows = []
        found = False
        with open(self.TRADE_LOG, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("order_id") == order_id and row.get("status") == "open":
                    try:
                        ep  = float(row.get("fill_price") or row.get("entry_price") or 0)
                        qty = float(row.get("quantity", 1))
                        sd  = row.get("side", "buy").lower()
                        if sd == "buy":
                            pct = (exit_price - ep) / ep if ep else 0
                        else:
                            pct = (ep - exit_price) / ep if ep else 0
                        dollar = pct * ep * qty
                        row["closed_at"]   = datetime.now().isoformat()
                        row["exit_price"]  = round(exit_price, 6)
                        row["pnl"]         = round(dollar, 4)
                        row["pnl_pct"]     = round(pct * 100, 4)
                        row["exit_reason"] = exit_reason
                        row["status"]      = "closed"
                        found = True
                        pct_str = f"{pct * 100:+.2f}"
                        log.info(f"Trade closed: {order_id} | P&L: {dollar:+.4f} ({pct_str}%)")
                    except Exception as e:
                        log.error(f"close_trade P&L calc error: {e}")
                rows.append(row)

        if found:
            with open(self.TRADE_LOG, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=self.LOG_COLS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        return found

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #
    def _execute(self, request: OrderRequest, kelly_pct: float) -> OrderResult:
        bad_chars = set('/\\;|&$`<>\'"{}[]')
        if any(c in request.symbol for c in bad_chars):
            return OrderResult(
                success=False, broker="validation",
                symbol=request.symbol, side=request.side, quantity=request.quantity,
                error=f"Symbol contains invalid characters: {request.symbol!r}",
                status="rejected",
            )
        if not self.broker:
            log.warning("No broker configured -- simulating fill")
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
        else:
            # Migrate old CSVs missing the P&L columns
            with open(self.TRADE_LOG, encoding="utf-8-sig") as f:
                first_line = f.readline()
            if "pnl" not in first_line:
                self._migrate_csv()

    def _migrate_csv(self):
        try:
            rows = []
            with open(self.TRADE_LOG, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    rows.append(row)
            with open(self.TRADE_LOG, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=self.LOG_COLS, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            log.info("Migrated executed_trades.csv to include P&L columns")
        except Exception as e:
            log.warning(f"CSV migration failed: {e}")

    def _log_to_db(self, trade_dict: dict) -> Optional[str]:
        """
        Write a trade to the PostgreSQL database via the FastAPI client.
        Returns the new database ID or None if unavailable / failed.
        Silently swallows errors so CSV logging is never interrupted.
        """
        if not self.api_client:
            return None
        try:
            payload = {
                "symbol":      trade_dict.get("symbol", ""),
                "side":        trade_dict.get("side", "buy"),
                "order_type":  trade_dict.get("order_type", "market"),
                "quantity":    float(trade_dict.get("quantity", 0)),
                "entry_price": float(trade_dict.get("entry_price") or trade_dict.get("fill_price") or 0),
                "stop_loss":   float(trade_dict["stop_loss"])   if trade_dict.get("stop_loss")   else None,
                "take_profit": float(trade_dict["take_profit"]) if trade_dict.get("take_profit") else None,
                "strategy":    trade_dict.get("strategy"),
                "broker":      trade_dict.get("broker", "manual"),
                "is_paper":    bool(trade_dict.get("is_paper", self.paper_trading)),
                "notes":       trade_dict.get("reason") or trade_dict.get("notes"),
            }
            result = self.api_client.create_trade(payload)
            db_id = result.get("id")
            log.info(f"Trade also written to DB: {db_id}")
            return db_id
        except Exception as e:
            log.warning(f"DB write failed (CSV is authoritative): {e}")
            return None

    def _log_trade(
        self,
        request:      OrderRequest,
        result:       OrderResult,
        kelly_pct:    float,
        reason:       str,
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
            "closed_at":    "",
            "exit_price":   "",
            "pnl":          "",
            "pnl_pct":      "",
            "exit_reason":  "",
            "error":        result.error,
        }
        with open(self.TRADE_LOG, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=self.LOG_COLS, extrasaction="ignore").writerow(row)
        log.info(f"Trade logged: {result.order_id} | {result.status}")

        # Dual-write to database (best-effort, non-blocking)
        self._log_to_db({
            **row,
            "order_type": "market",
            "is_paper":   self.paper_trading,
        })
