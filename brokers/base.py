"""
brokers/base.py — Abstract broker interface.

All broker implementations must inherit from BaseBroker and implement:
  - connect()
  - get_balance()
  - get_price()
  - place_order()
  - get_order_status()
  - cancel_order()
  - disconnect()

This keeps the order manager broker-agnostic — swapping BitOasis for IBKR
requires zero changes in the confirmation or notification layers.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class OrderRequest:
    """Structured trade request passed to any broker."""
    symbol:      str
    side:        str          # "buy" | "sell"
    quantity:    float
    order_type:  str = "market"   # "market" | "limit"
    limit_price: Optional[float] = None
    stop_loss:   Optional[float] = None
    take_profit: Optional[float] = None
    comment:     str = ""
    timestamp:   str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def is_buy(self) -> bool:
        return self.side.lower() == "buy"

    def summary(self) -> str:
        price_str = f" @ {self.limit_price:.6f}" if self.limit_price else " @ MARKET"
        sl_str    = f" | SL {self.stop_loss:.6f}" if self.stop_loss else ""
        tp_str    = f" | TP {self.take_profit:.6f}" if self.take_profit else ""
        return (
            f"{self.side.upper()} {self.quantity:.6f} {self.symbol}"
            f"{price_str}{sl_str}{tp_str}"
        )


@dataclass
class OrderResult:
    """Standardised response from broker after order placement."""
    success:      bool
    order_id:     str = ""
    broker:       str = ""
    symbol:       str = ""
    side:         str = ""
    quantity:     float = 0.0
    filled_price: Optional[float] = None
    status:       str = ""         # "filled" | "pending" | "rejected" | "cancelled"
    error:        str = ""
    timestamp:    str = field(default_factory=lambda: datetime.now().isoformat())

    def summary(self) -> str:
        if self.success:
            price_str = f" @ {self.filled_price:.6f}" if self.filled_price else ""
            return f"[{self.broker}] {self.side.upper()} {self.quantity} {self.symbol}{price_str} — {self.status}"
        return f"[{self.broker}] FAILED: {self.error}"


class BaseBroker(ABC):
    """Abstract base for all broker integrations."""

    def __init__(self, name: str, paper_trading: bool = True):
        self.name         = name
        self.paper_trading = paper_trading
        self._connected   = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection. Returns True on success."""

    @abstractmethod
    def disconnect(self):
        """Close connection cleanly."""

    @abstractmethod
    def get_balance(self) -> dict:
        """Return dict of {currency: amount} balances."""

    @abstractmethod
    def get_price(self, symbol: str) -> Optional[float]:
        """Return latest mid-price for symbol, or None on error."""

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        """
        Submit an order to the broker.
        In paper_trading mode: simulate execution, never hit real API.
        """

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderResult:
        """Fetch current status of an order by ID."""

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        return False   # optional — override in brokers that support it

    def __repr__(self) -> str:
        mode = "PAPER" if self.paper_trading else "LIVE"
        status = "connected" if self._connected else "disconnected"
        return f"{self.name}[{mode}] ({status})"
