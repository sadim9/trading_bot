"""
brokers/interactive_brokers.py — Interactive Brokers Integration

Python 3.12+ / Streamlit asyncio fix:
  ib_insync calls asyncio.get_event_loop() during its OWN IMPORT in newer
  Python versions, before any user code runs. This means the error occurs
  the moment `from ib_insync import IB` executes in Streamlit's script
  thread — no amount of event loop setup around connect() can help.

Solution: lazy import + ThreadPoolExecutor with initializer
  - ib_insync is imported ONLY inside the executor's worker thread
    (where _executor_initializer has already set up a fresh event loop)
  - The Streamlit script thread never touches ib_insync at all
  - Connection test uses a raw TCP socket — zero asyncio dependency

This is the only approach guaranteed to work in Python 3.10–3.14.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import socket
import threading
import time
from typing import Optional, Any, Callable

from brokers.base import BaseBroker, OrderRequest, OrderResult


# ── Shared single-worker executor — owns its own event loop forever ──────────
_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
_EXECUTOR_LOCK = threading.Lock()


def _executor_initializer():
    """
    Runs ONCE inside the worker thread.
    Imports ib_insync HERE (not at module level) so the import happens
    in a thread that already has an event loop — never in Streamlit's thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # Import ib_insync now — inside the worker thread with a live event loop
    try:
        import ib_insync  # noqa: F401  (populates sys.modules for worker thread)
    except ImportError:
        pass


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None or _EXECUTOR._broken:
            _EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=1,
                initializer=_executor_initializer,
                thread_name_prefix="ibkr-worker",
            )
    return _EXECUTOR


def _run(func: Callable, *args, timeout: float = 30, **kwargs) -> Any:
    """Submit func to the IBKR worker thread (which has asyncio set up)."""
    future = _get_executor().submit(func, *args, **kwargs)
    return future.result(timeout=timeout)


def test_tws_reachable(host: str, port: int, timeout: float = 5) -> bool:
    """
    Test whether TWS/IB Gateway is listening using a raw TCP socket.
    Zero asyncio — safe to call from any thread including Streamlit's.
    """
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


class InteractiveBrokersBroker(BaseBroker):

    def __init__(
        self,
        host:          str  = "127.0.0.1",
        port:          int  = 7497,
        client_id:     int  = 1,
        paper_trading: bool = True,
        timeout:       int  = 15,
    ):
        super().__init__("InteractiveBrokers", paper_trading=paper_trading)
        self.host         = host
        self.port         = int(port)
        self.client_id    = int(client_id)
        self.timeout      = timeout
        self._ib          = None          # lives only inside the worker thread
        self._sim_mode    = False
        self._paper_balance = {"USD": 100_000.0}

    # ── Connection ─────────────────────────────────────────────────────────────
    def connect(self) -> bool:
        # Step 1: test port reachability WITHOUT asyncio (safe in any thread)
        if not test_tws_reachable(self.host, self.port, timeout=5):
            if self.paper_trading:
                self._connected = True
                self._sim_mode  = True
                print(f"[IBKR] Port {self.port} unreachable — SIMULATION mode")
                return True
            raise ConnectionError(
                f"TWS/IB Gateway is not listening on {self.host}:{self.port}.\n\n"
                f"Checklist:\n"
                f"  1. TWS is fully open (trading interface, not just login)\n"
                f"  2. Edit → Global Config → API → Settings\n"
                f"     ✅ Enable ActiveX and Socket Clients\n"
                f"     ✅ Socket port = {self.port}\n"
                f"     ✅ 127.0.0.1 in Trusted IP Addresses\n"
                f"  3. Click OK then RESTART TWS\n"
                f"  4. Ports: Paper TWS=7497  Live TWS=7496  "
                f"Paper GW=4002  Live GW=4001"
            )

        # Step 2: do the real ib_insync connect inside the worker thread
        # (ib_insync was imported there during _executor_initializer)
        try:
            ib = _run(self._worker_connect, timeout=self.timeout + 10)
            if ib is not None:
                self._ib        = ib
                self._connected = True
                self._sim_mode  = False
                mode = "PAPER" if self.port in (7497, 4002) else "LIVE"
                print(f"[IBKR] Connected {mode} — {self.host}:{self.port}")
                return True
            raise ConnectionError("ib_insync connect returned None")

        except concurrent.futures.TimeoutError:
            if self.paper_trading:
                self._connected = True
                self._sim_mode  = True
                return True
            raise ConnectionError(
                f"ib_insync timed out after {self.timeout}s.\n"
                "TWS is reachable but not responding to the API handshake.\n"
                "Try increasing the timeout or restarting TWS."
            )
        except Exception as e:
            err = str(e)
            if self.paper_trading:
                self._connected = True
                self._sim_mode  = True
                print(f"[IBKR] {err[:60]} — SIMULATION mode")
                return True
            if "clientid" in err.lower() or "duplicate" in err.lower():
                hint = f"\n\nChange Client ID to {self.client_id + 1} and retry."
            elif "read-only" in err.lower():
                hint = "\n\nUncheck 'Read-Only API' in TWS API Settings."
            else:
                hint = ""
            raise ConnectionError(f"{err}{hint}")

    def _worker_connect(self):
        """Runs in executor thread — ib_insync available, event loop set."""
        from ib_insync import IB          # already in sys.modules for this thread
        loop = asyncio.get_event_loop()
        ib   = IB()
        loop.run_until_complete(
            ib.connectAsync(
                self.host, self.port,
                clientId=self.client_id,
                timeout=self.timeout,
            )
        )
        return ib

    def disconnect(self):
        self._connected = False
        self._sim_mode  = False
        if self._ib:
            try:
                _run(self._ib.disconnect, timeout=5)
            except Exception:
                pass
        self._ib = None

    # ── Account ────────────────────────────────────────────────────────────────
    def get_balance(self) -> dict:
        if self._sim_mode or not self._ib:
            return dict(self._paper_balance)
        try:
            return _run(self._worker_get_balance, timeout=10)
        except Exception:
            return dict(self._paper_balance)

    def _worker_get_balance(self) -> dict:
        vals = self._ib.accountValues()
        return {
            av.tag: float(av.value)
            for av in vals
            if av.tag in ("TotalCashValue", "NetLiquidation", "BuyingPower")
            and av.value not in ("", "-")
        }

    def get_price(self, symbol: str) -> Optional[float]:
        if self._sim_mode or not self._ib:
            return None
        try:
            return _run(self._worker_get_price, symbol, timeout=10)
        except Exception:
            return None

    def _worker_get_price(self, symbol: str) -> Optional[float]:
        loop     = asyncio.get_event_loop()
        contract = self._make_contract(symbol)
        ticker   = self._ib.reqMktData(contract, "", False, False)
        loop.run_until_complete(asyncio.sleep(1.5))
        mid = ticker.midpoint()
        if mid and mid == mid:
            return float(mid)
        last = ticker.last
        return float(last) if last and last == last else None

    # ── Orders ─────────────────────────────────────────────────────────────────
    def place_order(self, request: OrderRequest) -> OrderResult:
        if self._sim_mode:
            return self._simulate(request)
        if not self._ib:
            return OrderResult(success=False, broker=self.name,
                               symbol=request.symbol, side=request.side,
                               quantity=request.quantity,
                               error="Not connected", status="rejected")
        try:
            return _run(self._worker_place_order, request, timeout=30)
        except Exception as e:
            return OrderResult(success=False, broker=self.name,
                               symbol=request.symbol, side=request.side,
                               quantity=request.quantity,
                               error=str(e), status="rejected")

    def _worker_place_order(self, request: OrderRequest) -> OrderResult:
        from ib_insync import MarketOrder, LimitOrder
        loop     = asyncio.get_event_loop()
        contract = self._make_contract(request.symbol)
        order = (
            LimitOrder(request.side.upper(), request.quantity,
                       round(float(request.limit_price), 2))
            if request.order_type == "limit" and request.limit_price
            else MarketOrder(request.side.upper(), request.quantity)
        )
        trade = self._ib.placeOrder(contract, order)
        loop.run_until_complete(asyncio.sleep(2))
        return OrderResult(
            success=True,
            order_id=str(trade.order.orderId),
            broker=self.name,
            symbol=request.symbol, side=request.side,
            quantity=request.quantity,
            filled_price=float(trade.orderStatus.avgFillPrice) or None,
            status=trade.orderStatus.status.lower(),
        )

    def get_order_status(self, order_id: str) -> OrderResult:
        if self._sim_mode or not self._ib:
            return OrderResult(success=True, order_id=order_id,
                               broker=self.name, status="simulated")
        try:
            return _run(self._worker_order_status, order_id, timeout=10)
        except Exception as e:
            return OrderResult(success=False, order_id=order_id,
                               broker=self.name, error=str(e), status="unknown")

    def _worker_order_status(self, order_id: str) -> OrderResult:
        for t in self._ib.trades():
            if str(t.order.orderId) == order_id:
                return OrderResult(
                    success=True, order_id=order_id, broker=self.name,
                    status=t.orderStatus.status.lower(),
                    filled_price=float(t.orderStatus.avgFillPrice) or None,
                )
        return OrderResult(success=False, order_id=order_id,
                           broker=self.name, error="Not found", status="unknown")

    def cancel_order(self, order_id: str) -> bool:
        if self._sim_mode or not self._ib:
            return False
        try:
            _run(self._worker_cancel, order_id, timeout=10)
            return True
        except Exception:
            return False

    def _worker_cancel(self, order_id: str):
        for t in self._ib.trades():
            if str(t.order.orderId) == order_id:
                self._ib.cancelOrder(t.order)
                return

    # ── Internal ───────────────────────────────────────────────────────────────
    def _make_contract(self, symbol: str):
        from ib_insync import Stock, Crypto, Forex
        s = symbol.upper().strip()
        if s in {"BTC","ETH","LTC","BCH","XRP"}:
            return Crypto(s, "PAXOS", "USD")
        if s in {"EUR","GBP","JPY","CHF","AUD","CAD","NZD"}:
            return Forex(f"{s}USD")
        return Stock(s, "SMART", "USD")

    def _simulate(self, request: OrderRequest) -> OrderResult:
        price = request.limit_price or 100.0
        oid   = f"SIM-{int(time.time())}"
        return OrderResult(
            success=True, order_id=oid,
            broker=f"{self.name}[SIM]",
            symbol=request.symbol, side=request.side,
            quantity=request.quantity, filled_price=price, status="filled",
        )

    def __repr__(self) -> str:
        if self._sim_mode:
            return f"{self.name}[SIMULATION]"
        mode  = "PAPER" if self.paper_trading else "LIVE"
        state = "connected" if self._connected else "disconnected"
        return f"{self.name}[{mode}] ({state}) {self.host}:{self.port}"
