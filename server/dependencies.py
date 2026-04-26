"""
server/dependencies.py — FastAPI dependency injection helpers.

Provides:
  - get_current_user  — resolves JWT Bearer token → User ORM object
  - require_role      — role-based access control factory
  - get_client_ip     — extracts real client IP (respects Nginx X-Forwarded-For)
  - audit             — writes AuditLog rows
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.jwt_handler import decode_token
from server.db.database import get_db
from server.db.models import AuditLog, User

bearer_scheme = HTTPBearer(auto_error=True)


# ─── CURRENT USER ─────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode the Bearer token and return the active User."""
    payload = decode_token(credentials.credentials, expected_type="access")
    user_id = payload["sub"]

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    # Check account lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account locked until {user.locked_until.isoformat()}",
        )

    return user


# ─── ROLE GUARD ───────────────────────────────────────────────────────────────

def require_role(*roles: str):
    """
    Returns a FastAPI dependency that asserts the current user has one of
    the specified roles.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role("admin"))])
    """
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of: {', '.join(roles)}",
            )
        return user

    return _check


# ─── CLIENT IP ────────────────────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    """Return the real client IP, respecting X-Forwarded-For from Nginx."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ─── AUDIT LOGGING ────────────────────────────────────────────────────────────

async def audit(
    db: AsyncSession,
    action: str,
    user: Optional[User] = None,
    resource: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
):
    """Write a row to audit_logs. Call this from endpoint handlers."""
    log = AuditLog(
        user_id     = user.id if user else None,
        action      = action,
        resource    = resource,
        resource_id = resource_id,
        details     = details,
        ip_address  = ip_address,
        user_agent  = user_agent,
        status      = "success" if success else "failure",
    )
    db.add(log)
    # Caller is responsible for committing the session (get_db auto-commits)
