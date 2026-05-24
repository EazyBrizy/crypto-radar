from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.signal import RadarSignal

ExecutionMode = Literal["virtual", "real"]
TradeSide = Literal["long", "short"]
TradeStatus = Literal["open", "closed", "cancelled"]
TradeResult = Literal["win", "loss", "breakeven"]
CloseReason = Literal["take_profit", "stop_loss", "manual_close", "cancelled"]


class ManualConfirmRequest(BaseModel):
    mode: ExecutionMode = "virtual"
    user_id: str = "demo_user"
    account_balance: float = Field(default=10_000.0, gt=0)
    risk_percent: float = Field(default=1.0, gt=0, le=10)
    leverage: int = Field(default=1, ge=1, le=100)
    size_usd: Optional[float] = Field(default=None, gt=0)
    fee_rate: float = Field(default=0.0006, ge=0, le=0.01)
    slippage_bps: float = Field(default=2.0, ge=0, le=100)
    max_open_positions: int = Field(default=3, ge=1, le=100)


class ManualRejectRequest(BaseModel):
    reason: Optional[str] = None


class CloseVirtualTradeRequest(BaseModel):
    exit_price: Optional[float] = Field(default=None, gt=0)
    reason: CloseReason = "manual_close"


class VirtualTrade(BaseModel):
    id: str
    user_id: str
    signal_id: str
    mode: Literal["virtual"] = "virtual"

    exchange: str
    symbol: str
    strategy: str
    timeframe: str
    side: TradeSide

    entry_price: float
    current_price: float
    exit_price: Optional[float] = None
    size_usd: float
    quantity: float
    leverage: int
    risk_percent: float

    stop_loss: float
    take_profit: list[float] = Field(default_factory=list)
    fees: float = 0.0
    slippage_bps: float = 0.0

    status: TradeStatus = "open"
    result: Optional[TradeResult] = None
    close_reason: Optional[CloseReason] = None
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    mfe: float = 0.0
    mae: float = 0.0

    opened_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    ai_review: Optional[str] = None
    screenshots: list[str] = Field(default_factory=list)


class RealExecutionResult(BaseModel):
    mode: Literal["real"] = "real"
    status: Literal["not_implemented"] = "not_implemented"
    exchange: str
    symbol: str
    message: str


class ManualDecisionResponse(BaseModel):
    signal: RadarSignal
    virtual_trade: Optional[VirtualTrade] = None
    real_execution: Optional[RealExecutionResult] = None
    message: str


class VirtualTradeResponse(BaseModel):
    trades: list[VirtualTrade]


class ExecutionConfig(BaseModel):
    risk_per_trade: float
    leverage: int
    account_balance: float


class ExecutionResult(BaseModel):
    status: Literal["FILLED", "REJECTED"]

    symbol: str
    direction: Literal["LONG", "SHORT"]

    entry_price: float
    position_size: float
    timestamp: int


class Trade(BaseModel):
    symbol: str

    entry_price: float
    exit_price: Optional[float] = None

    leverage: int
    position_size: float

    pnl: Optional[float] = None
    timestamp: int


class TradeAnalysis(BaseModel):
    trade_score: int = Field(..., ge=0, le=100)
    mistakes: list[str]
    insights: list[str]


class TradeRequest(BaseModel):
    symbol: str
    direction: Literal["LONG", "SHORT"]
