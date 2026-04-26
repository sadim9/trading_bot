"""
server/api/ws.py — WebSocket endpoint for real-time signal and trade updates.

ws://host/ws?token=<access_token>

Clients connect with their JWT access token as a query param.
The server broadcasts:
  - new signals as they are generated
  - trade status updates
  - heartbeat pings every 30 seconds
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from server.auth.jwt_handler import decode_token
from server.config import get_settings

router    = APIRouter(tags=["websocket"])
settings  = get_settings()

# In-memory connection registry: user_id -> set of active WebSocket connections
_connections: Dict[str, Set[WebSocket]] = {}


class ConnectionManager:
    def connect(self, user_id: str, ws: WebSocket):
        _connections.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: str, ws: WebSocket):
        if user_id in _connections:
            _connections[user_id].discard(ws)
            if not _connections[user_id]:
                del _connections[user_id]

    async def send_to_user(self, user_id: str, message: dict):
        dead = set()
        for ws in _connections.get(user_id, set()):
            try:
                await ws.send_text(json.dumps(message, default=str))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    async def broadcast(self, message: dict):
        for uid in list(_connections.keys()):
            await self.send_to_user(uid, message)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    # Authenticate before accepting the connection
    try:
        payload = decode_token(token, expected_type="access")
        user_id = payload["sub"]
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    manager.connect(user_id, websocket)

    try:
        # Send welcome message
        await websocket.send_text(json.dumps({
            "type":    "connected",
            "user_id": user_id,
            "ts":      datetime.now(timezone.utc).isoformat(),
        }))

        # Heartbeat loop — keep connection alive
        while True:
            try:
                # Wait for a message or timeout (heartbeat interval)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=settings.ws_heartbeat_seconds,
                )
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

            except asyncio.TimeoutError:
                # Send server-side heartbeat
                await websocket.send_text(json.dumps({
                    "type": "heartbeat",
                    "ts":   datetime.now(timezone.utc).isoformat(),
                }))

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, websocket)


# ── Helper for other parts of the app to push events ─────────────────────────

async def push_signal(user_id: str, signal_dict: dict):
    await manager.send_to_user(user_id, {"type": "signal", "data": signal_dict})


async def push_trade_update(user_id: str, trade_dict: dict):
    await manager.send_to_user(user_id, {"type": "trade_update", "data": trade_dict})
