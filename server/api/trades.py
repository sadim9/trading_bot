"""
server/api/trades.py — Trade management endpoints.

GET    /trades              — list trades (paginated, filterable)
POST   /trades              — log a new trade
GET    /trades/{id}         — get a single trade
PATCH  /trades/{id}         — update a trade (close, add notes, etc.)
DELETE /trades/{id}         — soft-delete (admin only)
GET    /trades/stats/summary — aggregated P&L and win-rate summary
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.database import get_db
from server.db.models import Trade, User
from server.dependencies import audit, get_current_user, require_role
from server.schemas.trade import TradeCreate, TradeListResponse, TradeOut, TradeUpdate

router = APIRouter(prefix="/trades", tags=["trades"])


# ── List Trades ───────────────────────────────────────────────────────────────

@router.get("", response_model=TradeListResponse)
async def list_trades(
    symbol:   Optional[str] = Query(None),
    side:     Optional[str] = Query(None, pattern=r"^(buy|sell)$"),
    status_:  Optional[str] = Query(None, alias="status"),
    strategy: Optional[str] = Query(None),
    broker:   Optional[str] = Query(None),
    is_paper: Optional[bool]= Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date:   Optional[datetime] = Query(None),
    page: int  = Query(1, ge=1),
    size: int  = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Trade).where(Trade.user_id == current_user.id)

    if symbol:   q = q.where(Trade.symbol   == symbol.upper())
    if side:     q = q.where(Trade.side     == side)
    if status_:  q = q.where(Trade.status   == status_)
    if strategy: q = q.where(Trade.strategy == strategy)
    if broker:   q = q.where(Trade.broker   == broker)
    if is_paper is not None: q = q.where(Trade.is_paper == is_paper)
    if from_date: q = q.where(Trade.opened_at >= from_date)
    if to_date:   q = q.where(Trade.opened_at <= to_date)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    q = q.order_by(Trade.opened_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    trades = result.scalars().all()

    return TradeListResponse(trades=trades, total=total, page=page, size=size)


# ── Create Trade ──────────────────────────────────────────────────────────────

@router.post("", response_model=TradeOut, status_code=status.HTTP_201_CREATED)
async def create_trade(
    payload: TradeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "trader")),
):
    trade = Trade(
        user_id      = current_user.id,
        symbol       = payload.symbol.upper(),
        side         = payload.side,
        order_type   = payload.order_type,
        quantity     = payload.quantity,
        entry_price  = payload.entry_price,
        stop_loss    = payload.stop_loss,
        take_profit  = payload.take_profit,
        limit_price  = payload.limit_price,
        strategy     = payload.strategy,
        broker       = payload.broker or "paper",
        is_paper     = payload.is_paper,
        signal_id    = payload.signal_id,
        notes        = payload.notes,
        status       = "open",
    )
    db.add(trade)
    await db.flush()
    await audit(db, "trade.created", user=current_user,
                resource="trade", resource_id=trade.id,
                details={"symbol": trade.symbol, "side": trade.side, "qty": trade.quantity})
    return trade


# ── Get Trade ─────────────────────────────────────────────────────────────────

@router.get("/stats/summary")
async def trade_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate P&L statistics for the current user."""
    result = await db.execute(
        select(
            func.count(Trade.id).label("total_trades"),
            func.sum(Trade.pnl).label("total_pnl"),
            func.avg(Trade.pnl_pct).label("avg_pnl_pct"),
            func.count(Trade.id).filter(Trade.pnl > 0).label("winning_trades"),
            func.count(Trade.id).filter(Trade.pnl < 0).label("losing_trades"),
            func.max(Trade.pnl_pct).label("best_trade_pct"),
            func.min(Trade.pnl_pct).label("worst_trade_pct"),
        ).where(
            Trade.user_id == current_user.id,
            Trade.status  == "closed",
        )
    )
    row = result.one()
    total  = row.total_trades or 0
    wins   = row.winning_trades or 0
    return {
        "total_trades":   total,
        "closed_trades":  total,
        "total_pnl":      round(row.total_pnl or 0, 4),
        "avg_pnl_pct":    round((row.avg_pnl_pct or 0) * 100, 2),
        "win_rate_pct":   round(wins / total * 100, 2) if total > 0 else 0,
        "winning_trades": wins,
        "losing_trades":  row.losing_trades or 0,
        "best_trade_pct": round((row.best_trade_pct or 0) * 100, 2),
        "worst_trade_pct":round((row.worst_trade_pct or 0) * 100, 2),
    }


@router.get("/{trade_id}", response_model=TradeOut)
async def get_trade(
    trade_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Trade).where(Trade.id == trade_id, Trade.user_id == current_user.id)
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


# ── Update Trade ──────────────────────────────────────────────────────────────

@router.patch("/{trade_id}", response_model=TradeOut)
async def update_trade(
    trade_id: str,
    payload: TradeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "trader")),
):
    result = await db.execute(
        select(Trade).where(Trade.id == trade_id, Trade.user_id == current_user.id)
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(trade, field, value)

    if payload.status == "closed" and trade.closed_at is None:
        from datetime import timezone
        trade.closed_at = datetime.now(timezone.utc)

    await audit(db, "trade.updated", user=current_user,
                resource="trade", resource_id=trade_id, details=update_data)
    return trade


# ── Delete Trade (admin only) ─────────────────────────────────────────────────

@router.delete("/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trade(
    trade_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade  = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    await db.delete(trade)
    await audit(db, "trade.deleted", user=current_user,
                resource="trade", resource_id=trade_id)
