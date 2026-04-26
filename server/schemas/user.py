"""server/schemas/user.py — User Pydantic models."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserOut(BaseModel):
    id:          str
    email:       EmailStr
    username:    str
    role:        str
    is_active:   bool
    is_verified: bool
    created_at:  datetime
    last_login:  Optional[datetime]

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    """Fields the user can update on their own account."""
    email:    Optional[EmailStr] = None
    username: Optional[str]      = Field(None, min_length=3, max_length=50)


class UserAdminUpdate(UserUpdate):
    """Admin-only fields."""
    role:       Optional[str]  = None
    is_active:  Optional[bool] = None
    is_verified: Optional[bool] = None
