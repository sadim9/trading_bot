"""
server/config.py — All server settings loaded from environment variables.
Copy .env.example to .env and fill in your values before running.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────────
    app_name: str    = "TradingBot API"
    app_version: str = "1.0.0"
    environment: str = "production"          # development | production
    debug: bool      = False

    # ── Security ──────────────────────────────────────────────────
    secret_key: str              = "CHANGE_ME_USE_SECRETS_TOKEN_HEX_64"
    access_token_expire_minutes: int  = 15
    refresh_token_expire_days: int    = 7
    bcrypt_rounds: int           = 12
    max_login_attempts: int      = 5
    lockout_minutes: int         = 15

    # ── CORS ──────────────────────────────────────────────────────
    # Comma-separated list of allowed origins
    cors_origins: str = "http://localhost:8501,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    # ── Database ──────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading_bot"

    # ── Redis (sessions / rate-limit / caching) ───────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Rate Limiting ─────────────────────────────────────────────
    rate_limit_per_minute: int = 60       # default per IP
    rate_limit_auth_per_minute: int = 10  # stricter for /auth endpoints

    # ── WebSocket ─────────────────────────────────────────────────
    ws_heartbeat_seconds: int = 30

    # ── Bot Worker ────────────────────────────────────────────────
    bot_poll_interval_seconds: int = 60
    bot_default_source: str        = "kraken"

    # ── Trusted Hosts (for TrustedHostMiddleware) ─────────────────
    # Comma-separated list. Must include your domain in production.
    allowed_hosts: str = "localhost,127.0.0.1"

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",")]

    # ── Trusted proxy IPs (for X-Forwarded-For behind Nginx) ──────
    trusted_proxies: str = "127.0.0.1,::1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
