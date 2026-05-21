"""
server/auth/jwt_handler.py — JWT access and refresh token management.

Access token:  short-lived (15 min), carries user identity + role.
Refresh token: long-lived (7 days), used to obtain new access tokens.
Both are RS256-signed when SECRET_KEY is a proper RSA key, or HS256 with
a long random secret for simpler deployments.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from fastapi import HTTPException, status

from server.config import get_settings as _get_settings

_INSECURE_PLACEHOLDERS = {"", "CHANGE_ME_USE_SECRETS_TOKEN_HEX_64", "REPLACE_WITH_64_CHAR_HEX_STRING"}

def _load_secret() -> str:
    """Load SECRET_KEY from Settings (which reads .env).
    Deferred to a function so the RuntimeError fires at request time with a
    clear 500 traceback rather than killing the import chain silently."""
    key = _get_settings().secret_key
    if key in _INSECURE_PLACEHOLDERS:
        raise RuntimeError(
            "SECRET_KEY is not set or is still the placeholder value. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(64))\" "
            "and add it to your .env file."
        )
    return key

ALGORITHM       = "HS256"

def _settings():
    return _get_settings()

def _secret() -> str:
    return _load_secret()

def _access_expire() -> int:
    return _settings().access_token_expire_minutes

def _refresh_expire() -> int:
    return _settings().refresh_token_expire_days


# ─── TOKEN CREATION ───────────────────────────────────────────────────────────

def create_access_token(user_id: str, role: str, username: str) -> str:
    """Create a short-lived JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=_access_expire())
    payload = {
        "sub":      user_id,
        "role":     role,
        "username": username,
        "type":     "access",
        "exp":      expire,
        "iat":      datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(days=_refresh_expire())
    payload = {
        "sub":  user_id,
        "type": "refresh",
        "exp":  expire,
        "iat":  datetime.now(timezone.utc),
        "jti":  secrets.token_hex(16),   # unique token ID for revocation
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


# ─── TOKEN VERIFICATION ───────────────────────────────────────────────────────

def decode_token(token: str, expected_type: str = "access") -> dict:
    """
    Decode and validate a JWT.
    Raises HTTP 401 on any validation failure.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError:
        raise credentials_exception

    if payload.get("type") != expected_type:
        raise credentials_exception

    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    return payload


def get_user_id_from_token(token: str) -> str:
    payload = decode_token(token, expected_type="access")
    return payload["sub"]
