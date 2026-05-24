from typing import List, Literal, Optional

from pydantic import BaseModel, Field


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
    mistakes: List[str]
    insights: List[str]


class TradeRequest(BaseModel):
    symbol: str
    direction: Literal["LONG", "SHORT"]
