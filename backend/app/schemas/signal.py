from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class StrategySignal(BaseModel):
    exchange: str = "bybit"
    symbol: str
    strategy: str
    direction: Literal["LONG", "SHORT"]
    confidence: float = Field(..., ge=0, le=1)
    timestamp: int
    score: int = Field(default=0, ge=0, le=100)
    timeframe: str = "stream"

    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    risk_reward: Optional[float] = Field(default=None, ge=0)
    urgency: Literal["low", "medium", "high"] = "medium"
    explanation: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)


SignalDirection = Literal["long", "short"]
SignalUrgency = Literal["low", "medium", "high"]
SignalStatus = Literal["active", "watchlist", "confirmed", "rejected", "expired", "invalidated"]


class RadarSignal(BaseModel):
    id: str
    symbol: str
    exchange: str
    strategy: str
    direction: SignalDirection
    confidence: float = Field(..., ge=0, le=1)
    risk_reward: Optional[float] = Field(default=None, ge=0)
    urgency: SignalUrgency = "medium"
    status: SignalStatus = "active"
    score: int = Field(default=0, ge=0, le=100)
    timeframe: str = "stream"

    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None

    explanation: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    decision_mode: Optional[Literal["virtual", "real"]] = None
    decision_note: Optional[str] = None
    confirmed_trade_id: Optional[str] = None


class RadarResponse(BaseModel):
    signals: List[RadarSignal]


class ScoredSignal(BaseModel):
    symbol: str
    strategy: str
    direction: Literal["LONG", "SHORT"]

    confidence: float = Field(..., ge=0, le=1)
    score: float = Field(..., ge=0, le=1)

    timestamp: int


class SignalResponse(BaseModel):
    symbol: str
    direction: Literal["LONG", "SHORT"]
    strategy: str
    score: float


class ErrorResponse(BaseModel):
    status: Literal["error"]
    message: str
