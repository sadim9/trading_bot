"""
server/api/users.py — User management (admin-only endpoints).

GET    /users          — list all users
GET    /users/{id}     — get user details
PATCH  /users/{id}     — update role / active status
DELETE /users/{id}     — deactivate account
GET    /users/{id}/audit-logs — view a user's audit trail
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.database import get_db
from server.db.models import AuditLog, User
from server.dependencies import audit, get_current_user, require_role
from server.schemas.user import UserAdminUpdate, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
        .offset((page - 1) * size).limit(size)
    )
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Users can view their own profile; admins can view anyone's
    if current_user.id != user_id and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    payload: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    await audit(db, "user.admin_update", user=admin,
                resource="user", resource_id=user_id, details=update_data)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await audit(db, "user.deactivated", user=admin,
                resource="user", resource_id=user_id)


@router.get("/{user_id}/audit-logs")
async def get_audit_logs(
    user_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Own logs or admin
    if current_user.id != user_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    total_q = select(func.count(AuditLog.id)).where(AuditLog.user_id == user_id)
    total   = (await db.execute(total_q)).scalar_one()

    logs_q  = (
        select(AuditLog)
        .where(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * size).limit(size)
    )
    logs = (await db.execute(logs_q)).scalars().all()

    return {
        "total": total,
        "page":  page,
        "size":  size,
        "logs": [
            {
                "id":          l.id,
                "action":      l.action,
                "resource":    l.resource,
                "resource_id": l.resource_id,
                "status":      l.status,
                "ip_address":  l.ip_address,
                "created_at":  l.created_at.isoformat(),
            }
            for l in logs
        ],
    }
