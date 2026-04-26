"""
server/api/signals.py — Signal endpoints.

POST /signals/generate  — trigger a live signal from the bot engine
GET  /signals           — list historical signals
GET  /signals/{id}      — get a single signal
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.database import get_db
from server.db.models import Signal, User
from server.dependencies import get_current_user, require_role
from server.schemas.signal import SignalListResponse, SignalOut

router = APIRouter(prefix="/signals", tags=["signals"])


# ── Generate Signal ───────────────────────────────────────────────────────────

@router.post("/generate", response_model=SignalOut)
async def generate_signal(
    symbol:   str = Query(..., min_length=1, max_length=30),
    interval: str = Query("1h"),
    period:   str = Query("6mo"),
    source:   str = Query("yfinance"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "trader")),
):
    """Run the bot's signal aggregator and persist the result."""
    try:
        from config import CONFIG
        from data.ingestion import load_data
        from signals.aggregator import SignalAggregator
        from risk.manager import RiskManager

        df  = load_data(symbol.upper(), interval=interval, period=period, source=source)
        agg = SignalAggregator(CONFIG)
        rec = agg.analyse(df, symbol.upper())

        risk_mgr = RiskManager(CONFIG.risk)
        check    = risk_mgr.check(
            symbol=symbol.upper(),
            signal=rec.signal,
            entry=rec.entry_price,
            stop_loss=rec.stop_loss,
            take_profit=rec.take_profit,
            size_pct=rec.position_size_pct,
            df=df,
        )

        # Build per-strategy breakdown
        breakdown = {}
        if hasattr(rec, "strategy_scores"):
            breakdown = rec.strategy_scores

        sig = Signal(
            user_id             = current_user.id,
            symbol              = symbol.upper(),
            signal_type         = rec.signal,
            composite_score     = rec.composite_score,
            entry_price         = rec.entry_price,
            stop_loss           = rec.stop_loss,
            take_profit         = rec.take_profit,
            position_size_pct   = rec.position_size_pct,
            strategy_breakdown  = breakdown,
            risk_check_passed   = check.approved,
            risk_reasons        = check.reasons,
            data_source         = source,
            interval            = interval,
        )
        db.add(sig)
        await db.flush()
        return sig

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Signal generation failed: {str(e)}")


# ── List Signals ──────────────────────────────────────────────────────────────

@router.get("", response_model=SignalListResponse)
async def list_signals(
    symbol:      Optional[str] = Query(None),
    signal_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Signal).where(Signal.user_id == current_user.id)
    if symbol:      q = q.where(Signal.symbol      == symbol.upper())
    if signal_type: q = q.where(Signal.signal_type == signal_type.upper())

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    q     = q.order_by(Signal.created_at.desc()).offset((page - 1) * size).limit(size)
    sigs  = (await db.execute(q)).scalars().all()

    return SignalListResponse(signals=sigs, total=total, page=page, size=size)


# ── Get Signal ────────────────────────────────────────────────────────────────

@router.get("/{signal_id}", response_model=SignalOut)
async def get_signal(
    signal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Signal).where(Signal.id == signal_id, Signal.user_id == current_user.id)
    )
    sig = result.scalar_one_or_none()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    return sig
