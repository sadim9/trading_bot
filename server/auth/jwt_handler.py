"""
server/auth/jwt_handler.py — JWT access and refresh token management.

Access token:  short-lived (15 min), carries user identity + role.
Refresh token: long-lived (7 days), used to obtain new access tokens.
Both are RS256-signed when SECRET_KEY is a proper RSA key, or HS256 with
a long random secret for simpler deployments.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from fastapi import HTTPException, status

SECRET_KEY      = os.getenv("SECRET_KEY", secrets.token_hex(64))
ALGORITHM       = "HS256"
ACCESS_EXPIRE   = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_EXPIRE  = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# ─── TOKEN CREATION ───────────────────────────────────────────────────────────

def create_access_token(user_id: str, role: str, username: str) -> str:
    """Create a short-lived JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_EXPIRE)
    payload = {
        "sub":      user_id,
        "role":     role,
        "username": username,
        "type":     "access",
        "exp":      expire,
        "iat":      datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE)
    payload = {
        "sub":  user_id,
        "type": "refresh",
        "exp":  expire,
        "iat":  datetime.now(timezone.utc),
        "jti":  secrets.token_hex(16),   # unique token ID for revocation
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


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
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
