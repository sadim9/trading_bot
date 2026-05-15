"""API route registry — import all routers here."""
from server.api.auth     import router as auth_router
from server.api.trades   import router as trades_router
from server.api.signals  import router as signals_router
from server.api.users    import router as users_router
from server.api.ws       import router as ws_router
from server.api.settings import router as settings_router

__all__ = [
    "auth_router", "trades_router", "signals_router",
    "users_router", "ws_router", "settings_router",
]
