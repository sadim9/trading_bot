"""
server/main.py — FastAPI application entry point.

Run with:
    uvicorn server.main:app --host 0.0.0.0 --port 8000 --workers 2

The app is intentionally security-hardened:
  - CORS restricted to configured origins
  - Rate limiting via slowapi
  - Security headers injected on every response
  - Request ID tracking for log correlation
  - Structured startup/shutdown lifecycle
"""

from __future__ import annotations

import time
import uuid
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from server.config import get_settings
from server.db.database import init_db
from server.api import (
    auth_router, trades_router, signals_router, users_router, ws_router,
    settings_router
)

settings = get_settings()
log      = logging.getLogger("uvicorn.error")

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(f"Starting {settings.app_name} v{settings.app_version} [{settings.environment}]")
    await init_db()
    log.info("Database tables verified/created")
    yield
    log.info("Shutting down")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title       = settings.app_name,
    version     = settings.app_version,
    description = "Secure Trading Bot REST API",
    docs_url    = "/docs" if settings.environment != "production" else None,
    redoc_url   = "/redoc" if settings.environment != "production" else None,
    openapi_url = "/openapi.json" if settings.environment != "production" else None,
    lifespan    = lifespan,
)

# ── Middleware stack (order matters — first added = outermost) ────────────────

# 1. Trusted Hosts — allow all internal hosts
# FastAPI runs on an internal Docker network (port 8000 not exposed publicly).
# Nginx is the sole public entry point and handles host validation there.
# Locking this down causes 400 errors when Streamlit calls api:8000 internally.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# 2. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins     = settings.cors_origins_list,
    allow_credentials = True,
    allow_methods     = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers     = ["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers    = ["X-Request-ID"],
)

# 3. Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# ── Security Headers Middleware ───────────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Assign a unique request ID for log correlation
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.perf_counter()

    response: Response = await call_next(request)

    # Inject security headers on every response
    response.headers["X-Request-ID"]            = request_id
    response.headers["X-Content-Type-Options"]  = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["X-XSS-Protection"]        = "1; mode=block"
    response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]      = "geolocation=(), microphone=(), camera=()"
    # CSP is set by Nginx for the frontend; API only sets frame-ancestors
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none';"
    # Timing header (useful for debugging, remove in prod if desired)
    elapsed = (time.perf_counter() - start_time) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed:.1f}"

    return response


# ── Routers ───────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth_router,    prefix=API_PREFIX)
app.include_router(trades_router,  prefix=API_PREFIX)
app.include_router(signals_router, prefix=API_PREFIX)
app.include_router(users_router,   prefix=API_PREFIX)
app.include_router(ws_router)            # WebSocket at /ws (no prefix)
app.include_router(settings_router, prefix=API_PREFIX)


# ── Health / Readiness Probes ─────────────────────────────────────────────────
@app.get("/health", tags=["infra"])
async def health():
    return {"status": "ok", "version": settings.app_version}


@app.get("/ready", tags=["infra"])
async def ready():
    """Check DB connectivity for Kubernetes/Docker health probes."""
    try:
        from server.db.database import engine
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unavailable", "error": str(e)})
