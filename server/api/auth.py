"""
server/api/auth.py — Authentication endpoints.

POST /auth/register  — create a new account
POST /auth/login     — return access + refresh tokens
POST /auth/refresh   — exchange refresh token for a new access token
POST /auth/logout    — (client-side token discard; server logs the event)
GET  /auth/me        — return current user profile
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.jwt_handler import (
    create_access_token, create_refresh_token, decode_token
)
from server.auth.password import hash_password, verify_password
from server.config import get_settings
from server.db.database import get_db
from server.db.models import User
from server.dependencies import audit, get_client_ip, get_current_user
from server.schemas.auth import LoginRequest, LoginResponse, RefreshRequest, RegisterRequest, TokenPair
from server.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


# ── Register ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Check duplicate email or username
    existing = await db.execute(
        select(User).where(
            (User.email == payload.email) | (User.username == payload.username)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        )

    user = User(
        email         = payload.email,
        username      = payload.username,
        password_hash = hash_password(payload.password),
        role          = "trader",   # default role; admin must be set manually
        is_active     = True,
        is_verified   = False,
    )
    db.add(user)
    await db.flush()   # get user.id before audit

    await audit(
        db, action="user.register", user=user,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        details={"email": payload.email, "username": payload.username},
    )
    return user


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = get_client_ip(request)

    result = await db.execute(
        select(User).where(User.username == payload.username)
    )
    user = result.scalar_one_or_none()

    # Generic error — don't reveal whether it's username or password that's wrong
    def _fail():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if user is None:
        await audit(db, "user.login_failed", ip_address=ip,
                    details={"username": payload.username}, success=False)
        _fail()

    # Account lockout check
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account locked until {user.locked_until.isoformat()}",
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.max_login_attempts:
            from datetime import timedelta
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.lockout_minutes
            )
        await audit(db, "user.login_failed", user=user, ip_address=ip,
                    details={"attempts": user.failed_login_attempts}, success=False)
        _fail()

    # Successful login
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)

    await audit(db, "user.login", user=user, ip_address=ip)

    access  = create_access_token(user.id, user.role, user.username)
    refresh = create_refresh_token(user.id)

    return LoginResponse(
        access_token  = access,
        refresh_token = refresh,
        user_id       = user.id,
        username      = user.username,
        role          = user.role,
    )


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenPair)
async def refresh_token(
    payload: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    data    = decode_token(payload.refresh_token, expected_type="refresh")
    user_id = data["sub"]

    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    await audit(db, "user.token_refresh", user=user, ip_address=get_client_ip(request))

    return TokenPair(
        access_token  = create_access_token(user.id, user.role, user.username),
        refresh_token = create_refresh_token(user.id),   # rotate refresh token
    )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: AsyncSession    = Depends(get_db),
    current_user: User  = Depends(get_current_user),
):
    # Tokens are stateless JWTs — client must discard them.
    # We log the event for audit purposes.
    await audit(db, "user.logout", user=current_user, ip_address=get_client_ip(request))


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
