"""
brokers/bitoasis.py — BitOasis Exchange Broker Integration

BitOasis REST API v3
Docs: https://developers.bitoasis.net/

Authentication: HMAC-SHA256 signed headers
  X-API-Key: your API key
  X-API-Sign: HMAC signature of (timestamp + method + path + body)
  X-API-Timestamp: Unix timestamp in milliseconds

Supported:
  - Spot crypto trading (BTC, ETH, XRP, etc.)
  - Market and Limit orders
  - Paper trading mode (no real API calls)

Setup:
  1. Log in to BitOasis → Account → API Management
  2. Create API key with Trade permission
  3. Set BITOASIS_API_KEY and BITOASIS_API_SECRET in environment
     (or pass directly to BitOasisBroker constructor)

Symbol format:  "BTC-AED", "ETH-AED", "BTC-USD"
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Optional
from datetime import datetime

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

from brokers.base import BaseBroker, OrderRequest, OrderResult


class BitOasisBroker(BaseBroker):

    BASE_URL = "https://api.bitoasis.net/v3"

    def __init__(
        self,
        api_key:     str = "",
        api_secret:  str = "",
        paper_trading: bool = True,
    ):
        super().__init__("BitOasis", paper_trading=paper_trading)
        self.api_key    = api_key    or os.getenv("BITOASIS_API_KEY",    "")
        self.api_secret = api_secret or os.getenv("BITOASIS_API_SECRET", "")
        self._session   = None
        self._paper_balance = {"AED": 100000.0, "BTC": 0.0, "ETH": 0.0}

    # ── Connection ─────────────────────────────────────────────────────
    def connect(self) -> bool:
        if not REQUESTS_OK:
            raise ImportError("pip install requests")
        if self.paper_trading:
            self._connected = True
            print(f"[BitOasis] PAPER mode — no real orders will be placed")
            return True
        if not self.api_key or not self.api_secret:
            raise ValueError(
                "BitOasis API credentials missing.\n"
                "Set BITOASIS_API_KEY and BITOASIS_API_SECRET env vars, "
                "or pass them to BitOasisBroker(api_key=..., api_secret=...)"
            )
        self._session = requests.Session()
        try:
            resp = self._signed_request("GET", "/account/balances")
            if resp.status_code == 200:
                self._connected = True
                print(f"[BitOasis] Connected — LIVE trading enabled")
                return True
            raise ConnectionError(f"Auth failed: HTTP {resp.status_code} — {resp.text[:200]}")
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"[BitOasis] connect() failed: {e}")

    def disconnect(self):
        self._connected = False
        if self._session:
            self._session.close()
            self._session = None

    # ── Account ────────────────────────────────────────────────────────
    def get_balance(self) -> dict:
        if self.paper_trading:
            return dict(self._paper_balance)
        resp = self._signed_request("GET", "/account/balances")
        resp.raise_for_status()
        data = resp.json()
        return {item["currency"]: float(item["available"]) for item in data.get("balances", [])}

    def get_price(self, symbol: str) -> Optional[float]:
        """Fetch latest ticker mid-price. symbol = 'BTC-AED', 'ETH-USD', etc."""
        if not REQUESTS_OK:
            return None
        try:
            # Validate symbol to prevent SSRF via symbol injection
            clean_symbol = symbol.upper().replace("/", "-")
            if not all(c.isalnum() or c == "-" for c in clean_symbol):
                return None
            # Public endpoint — no auth needed; URL is controlled (not user-provided)
            url  = f"{self.BASE_URL}/market/ticker/{clean_symbol}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                bid  = float(data.get("bid", 0))
                ask  = float(data.get("ask", 0))
                return (bid + ask) / 2 if bid and ask else float(data.get("last", 0))
            return None
        except Exception:
            return None

    # ── Orders ─────────────────────────────────────────────────────────
    def place_order(self, request: OrderRequest) -> OrderResult:
        if self.paper_trading:
            return self._paper_execute(request)

        payload = {
            "symbol":    request.symbol.upper(),
            "side":      request.side.lower(),
            "type":      request.order_type.lower(),
            "quantity":  str(request.quantity),
        }
        if request.order_type == "limit" and request.limit_price:
            payload["price"] = str(request.limit_price)

        resp = self._signed_request("POST", "/order", body=payload)

        if resp.status_code in (200, 201):
            data = resp.json()
            return OrderResult(
                success=True,
                order_id=str(data.get("id", "")),
                broker=self.name,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                filled_price=float(data.get("price", 0)) or None,
                status=data.get("status", "pending"),
            )
        return OrderResult(
            success=False,
            broker=self.name,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            error=f"HTTP {resp.status_code}: {resp.text[:300]}",
            status="rejected",
        )

    def get_order_status(self, order_id: str) -> OrderResult:
        if self.paper_trading:
            return OrderResult(
                success=True, order_id=order_id,
                broker=self.name, status="filled",
            )
        resp = self._signed_request("GET", f"/order/{order_id}")
        if resp.status_code == 200:
            data = resp.json()
            return OrderResult(
                success=True,
                order_id=order_id,
                broker=self.name,
                symbol=data.get("symbol", ""),
                side=data.get("side", ""),
                quantity=float(data.get("quantity", 0)),
                filled_price=float(data.get("price", 0)) or None,
                status=data.get("status", "unknown"),
            )
        return OrderResult(
            success=False, order_id=order_id, broker=self.name,
            error=f"HTTP {resp.status_code}", status="unknown",
        )

    # ── Internal ───────────────────────────────────────────────────────
    def _signed_request(self, method: str, path: str, body: dict = None):
        """Build HMAC-signed request for BitOasis API."""
        ts        = str(int(time.time() * 1000))
        body_str  = json.dumps(body) if body else ""
        msg       = ts + method.upper() + path + body_str
        # Security: use constant-time hmac.new to prevent timing attacks
        # Key and message must be bytes; encode explicitly
        key_bytes = self.api_secret.encode("utf-8")
        msg_bytes = msg.encode("utf-8")
        signature = hmac.new(key_bytes, msg_bytes, hashlib.sha256).hexdigest()
        # Zero out key reference (best-effort in Python)
        key_bytes = b""

        headers = {
            "Content-Type":    "application/json",
            "X-API-Key":       self.api_key,
            "X-API-Sign":      signature,
            "X-API-Timestamp": ts,
        }
        url = self.BASE_URL + path
        if method.upper() == "GET":
            return self._session.get(url, headers=headers, timeout=10)
        return self._session.post(url, headers=headers, data=body_str, timeout=10)

    def _paper_execute(self, request: OrderRequest) -> OrderResult:
        """Simulate order execution for paper trading."""
        price = self.get_price(request.symbol) or request.limit_price or 0.0
        # Update paper balances
        base, quote = request.symbol.split("-") if "-" in request.symbol else (request.symbol, "USD")
        if request.is_buy:
            cost = price * request.quantity
            if self._paper_balance.get(quote, 0) >= cost:
                self._paper_balance[quote] = self._paper_balance.get(quote, 0) - cost
                self._paper_balance[base]  = self._paper_balance.get(base, 0) + request.quantity
        else:
            if self._paper_balance.get(base, 0) >= request.quantity:
                self._paper_balance[base]  = self._paper_balance.get(base, 0) - request.quantity
                self._paper_balance[quote] = self._paper_balance.get(quote, 0) + price * request.quantity

        order_id = f"PAPER-{int(time.time())}"
        print(f"[BitOasis PAPER] {request.summary()} @ {price:.4f}")
        return OrderResult(
            success=True,
            order_id=order_id,
            broker=f"{self.name}[PAPER]",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            filled_price=price,
            status="filled",
        )
