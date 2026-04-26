"""server/schemas/signal.py — Signal Pydantic models."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class SignalOut(BaseModel):
    id:                   str
    user_id:              str
    symbol:               str
    signal_type:          str
    composite_score:      float
    entry_price:          Optional[float]
    stop_loss:            Optional[float]
    take_profit:          Optional[float]
    position_size_pct:    Optional[float]
    trend_score:          Optional[float]
    momentum_score:       Optional[float]
    mean_reversion_score: Optional[float]
    ai_model_score:       Optional[float]
    markov_score:         Optional[float]
    strategy_breakdown:   Optional[Dict[str, Any]]
    risk_check_passed:    Optional[bool]
    risk_reasons:         Optional[List[str]]
    data_source:          Optional[str]
    interval:             Optional[str]
    created_at:           datetime

    model_config = {"from_attributes": True}


class SignalListResponse(BaseModel):
    signals: List[SignalOut]
    total:   int
    page:    int
    size:    int
