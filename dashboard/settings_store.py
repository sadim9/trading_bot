"""
dashboard/settings_store.py — Persistent user settings storage.

Saves user preferences (theme, timezone offset, alert credentials,
bot defaults, Discord webhook) to a JSON file on disk so they survive
Streamlit restarts, page refreshes, and Docker container restarts.

Storage location: /app/logs/user_settings.json (inside the shared
trading_logs Docker volume, which persists across restarts).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import streamlit as st

# Storage path — falls back to a local .cache/ directory in development
_SETTINGS_DIR = Path(os.getenv("SETTINGS_DIR", "/app/logs"))
_SETTINGS_FILE = _SETTINGS_DIR / "user_settings.json"

# Keys persisted to disk
_PERSIST_KEYS = [
    "theme",
    "tz_offset_hours",
    "_def_symbol",
    "_def_source",
    "_def_interval",
    "_def_period",
    "_discord_webhook_url",
    "_discord_bot_token",
    "_discord_channel_id",
    "_email_sender",
    "_email_recipient",
    "_telegram_bot_token",
    "_telegram_chat_id",
    "_whatsapp_phone",
    "_whatsapp_api_key",
    "_twelvedata_api_key",
    "refresh_interval",
    "auto_refresh",
    "pinned_tickers",
    "pinned_ticker_settings",
    "strategy_mode",
    "_tv_username",
    "_tv_password",
    "_tv_exchange",
    "_tv_exchange_custom",
    "_tv_exchange_override",
    "planned_trade_amount",
]


def _ensure_dir() -> bool:
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        # Fallback to local .cache/ in dev
        try:
            fallback = Path(".cache")
            fallback.mkdir(exist_ok=True)
            global _SETTINGS_FILE
            _SETTINGS_FILE = fallback / "user_settings.json"
            return True
        except Exception:
            return False


def load_settings() -> Dict[str, Any]:
    """Read persisted settings from disk. Returns empty dict if not found."""
    # Also try fallback path
    for path in [_SETTINGS_FILE, Path(".cache/user_settings.json")]:
        try:
            if path.exists():
                text = path.read_text(encoding="utf-8")
                return json.loads(text)
        except Exception:
            continue
    return {}


def apply_settings_to_session(settings: Dict[str, Any]):
    """Apply settings dict to session_state WITHOUT overwriting existing keys."""
    for key, value in settings.items():
        if key not in st.session_state:
            st.session_state[key] = value


def save_settings():
    """Write relevant session_state keys to disk atomically."""
    _ensure_dir()
    data: Dict[str, Any] = {}
    for key in _PERSIST_KEYS:
        val = st.session_state.get(key)
        if val is not None:
            data[key] = val
    try:
        tmp = _SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        tmp.replace(_SETTINGS_FILE)
    except Exception:
        # Try fallback path
        try:
            fb = Path(".cache/user_settings.json")
            fb.parent.mkdir(exist_ok=True)
            fb.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass


def get_setting(key: str, default: Any = None) -> Any:
    return st.session_state.get(key, default)


def set_setting(key: str, value: Any, persist: bool = True):
    st.session_state[key] = value
    if persist:
        save_settings()


# ── Timezone helpers ──────────────────────────────────────────────────────────

def get_tz_offset() -> float:
    """Return user's UTC offset in hours (default 3.0 = Qatar/UAE)."""
    return float(st.session_state.get("tz_offset_hours", 3.0))


def fmt_local_time(dt_str: str, fmt: str = "%H:%M:%S") -> str:
    """Convert UTC ISO timestamp to local time using user's tz_offset_hours."""
    from datetime import datetime, timezone, timedelta
    try:
        dt_str = dt_str.strip()
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        utc = datetime.fromisoformat(dt_str)
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=timezone.utc)
        offset_hours = get_tz_offset()
        local_tz = timezone(timedelta(hours=offset_hours))
        return utc.astimezone(local_tz).strftime(fmt)
    except Exception:
        return dt_str[11:19] if len(dt_str) > 19 else dt_str


def now_local_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Current UTC time adjusted to user's local offset."""
    from datetime import datetime, timezone, timedelta
    offset_hours = get_tz_offset()
    local_tz = timezone(timedelta(hours=offset_hours))
    return datetime.now(timezone.utc).astimezone(local_tz).strftime(fmt)


def tz_label() -> str:
    """Human-readable timezone label like 'UTC+3'."""
    offset = get_tz_offset()
    if offset == 0:
        return "UTC"
    sign = "+" if offset >= 0 else ""
    return f"UTC{sign}{offset:g}"
