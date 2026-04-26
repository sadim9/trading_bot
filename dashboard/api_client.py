"""
dashboard/api_client.py — Thin HTTP client for the FastAPI backend.

All dashboard modules should call these functions instead of directly
importing bot internals. This keeps the UI fully decoupled from the engine.
"""

from __future__ import annotations

import os
import requests
from typing import Optional

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")


class APIClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.session.headers.update({"Content-Type": "application/json"})

    def _url(self, path: str) -> str:
        return f"{API_BASE}{path}"

    def _raise(self, resp: requests.Response):
        if not resp.ok:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RuntimeError(f"API error {resp.status_code}: {detail}")

    # ── Auth ──────────────────────────────────────────────────

    def login(self, username: str, password: str) -> dict:
        resp = self.session.post(self._url("/auth/login"),
                                 json={"username": username, "password": password})
        self._raise(resp)
        return resp.json()

    def register(self, email: str, username: str, password: str) -> dict:
        resp = self.session.post(self._url("/auth/register"),
                                 json={"email": email, "username": username, "password": password})
        self._raise(resp)
        return resp.json()

    def me(self) -> dict:
        resp = self.session.get(self._url("/auth/me"))
        self._raise(resp)
        return resp.json()

    # ── Signals ───────────────────────────────────────────────

    def generate_signal(self, symbol: str, interval: str = "1h",
                        period: str = "6mo", source: str = "yfinance") -> dict:
        resp = self.session.post(self._url("/signals/generate"), params={
            "symbol": symbol, "interval": interval, "period": period, "source": source
        })
        self._raise(resp)
        return resp.json()

    def list_signals(self, symbol: Optional[str] = None, page: int = 1, size: int = 50) -> dict:
        params = {"page": page, "size": size}
        if symbol:
            params["symbol"] = symbol
        resp = self.session.get(self._url("/signals"), params=params)
        self._raise(resp)
        return resp.json()

    # ── Trades ────────────────────────────────────────────────

    def list_trades(self, symbol: Optional[str] = None, status: Optional[str] = None,
                    page: int = 1, size: int = 50) -> dict:
        params = {"page": page, "size": size}
        if symbol: params["symbol"] = symbol
        if status: params["status"] = status
        resp = self.session.get(self._url("/trades"), params=params)
        self._raise(resp)
        return resp.json()

    def trade_summary(self) -> dict:
        resp = self.session.get(self._url("/trades/stats/summary"))
        self._raise(resp)
        return resp.json()

    def create_trade(self, trade: dict) -> dict:
        resp = self.session.post(self._url("/trades"), json=trade)
        self._raise(resp)
        return resp.json()

    def close_trade(self, trade_id: str, exit_price: float, pnl: float, pnl_pct: float) -> dict:
        resp = self.session.patch(self._url(f"/trades/{trade_id}"), json={
            "status":     "closed",
            "exit_price": exit_price,
            "pnl":        pnl,
            "pnl_pct":    pnl_pct,
        })
        self._raise(resp)
        return resp.json()
