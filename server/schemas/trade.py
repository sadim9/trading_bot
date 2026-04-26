"""server/schemas/trade.py — Trade Pydantic models."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class TradeCreate(BaseModel):
    symbol:       str   = Field(..., min_length=1, max_length=30)
    side:         str   = Field(..., pattern=r"^(buy|sell)$")
    order_type:   str   = Field("market", pattern=r"^(market|limit)$")
    quantity:     float = Field(..., gt=0)
    entry_price:  float = Field(..., gt=0)
    stop_loss:    Optional[float] = Field(None, gt=0)
    take_profit:  Optional[float] = Field(None, gt=0)
    limit_price:  Optional[float] = Field(None, gt=0)
    strategy:     Optional[str]   = None
    broker:       Optional[str]   = None
    is_paper:     bool  = True
    signal_id:    Optional[str]   = None
    notes:        Optional[str]   = Field(None, max_length=1000)


class TradeUpdate(BaseModel):
    exit_price:   Optional[float] = Field(None, gt=0)
    status:       Optional[str]   = Field(None, pattern=r"^(open|closed|cancelled|rejected)$")
    pnl:          Optional[float] = None
    pnl_pct:      Optional[float] = None
    notes:        Optional[str]   = Field(None, max_length=1000)
    broker_order_id: Optional[str] = None
    discord_confirmed: Optional[bool] = None


class TradeOut(BaseModel):
    id:           str
    user_id:      str
    symbol:       str
    side:         str
    order_type:   str
    quantity:     float
    entry_price:  float
    exit_price:   Optional[float]
    stop_loss:    Optional[float]
    take_profit:  Optional[float]
    status:       str
    pnl:          Optional[float]
    pnl_pct:      Optional[float]
    commission:   Optional[float]
    strategy:     Optional[str]
    broker:       Optional[str]
    is_paper:     bool
    notes:        Optional[str]
    opened_at:    datetime
    closed_at:    Optional[datetime]

    model_config = {"from_attributes": True}


class TradeListResponse(BaseModel):
    trades: List[TradeOut]
    total:  int
    page:   int
    size:   int
