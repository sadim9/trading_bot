"""
server/api/settings.py — User settings persistence endpoints.

GET  /settings       — load current user's settings
PUT  /settings       — save/update current user's settings

Settings are stored as JSON in the user's strategy_configs table
under the special name "__user_settings__" to avoid adding a new table.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Any, Dict, Optional

from server.db.database import get_db
from server.db.models import StrategyConfig, User
from server.dependencies import get_current_user

router = APIRouter(prefix="/settings", tags=["settings"])

_SETTINGS_NAME = "__user_settings__"


class UserSettings(BaseModel):
    settings: Dict[str, Any]


async def _get_or_create_settings_row(db: AsyncSession, user_id: str) -> StrategyConfig:
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.user_id == user_id,
            StrategyConfig.name == _SETTINGS_NAME,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = StrategyConfig(
            user_id=user_id,
            name=_SETTINGS_NAME,
            description="User UI preferences",
            config_json={},
            is_active=False,
            is_default=False,
        )
        db.add(row)
        await db.flush()
    return row


@router.get("", response_model=UserSettings)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's persisted UI settings."""
    row = await _get_or_create_settings_row(db, current_user.id)
    return {"settings": row.config_json or {}}


@router.put("", response_model=UserSettings)
async def save_settings(
    payload: UserSettings,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist the current user's UI settings."""
    row = await _get_or_create_settings_row(db, current_user.id)
    # Merge (don't replace) so partial updates work
    merged = dict(row.config_json or {})
    merged.update(payload.settings)
    row.config_json = merged
    await db.flush()
    return {"settings": merged}
