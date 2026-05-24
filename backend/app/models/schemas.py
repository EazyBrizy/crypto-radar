from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List, Literal


# =========================
# 1. РЫНОЧНЫЕ ДАННЫЕ
# =========================

class MarketData(BaseModel):
    symbol: str
    price: float
    volume: float
    timestamp: int


# =========================
# 2. ПРИЗНАКИ
# =========================

class Features(BaseModel):
    symbol: str
    timestamp: int

    price: float
    price_change_1m: float

    volume: float
    volume_spike: float

    volatility: float

    oi_change: Optional[float] = None
    funding_rate: Optional[float] = None


# =========================
# 3. СТРАТЕГИЧЕСКИЙ СИГНАЛ
# =========================

class StrategySignal(BaseModel):
    symbol: str
    strategy: str
    direction: Literal["LONG", "SHORT"]
    confidence: float = Field(..., ge=0, le=1)
    timestamp: int


# =========================
# 3.1. СИГНАЛ RADAR
# =========================

SignalDirection = Literal["long", "short"]
SignalUrgency = Literal["low", "medium", "high"]
SignalStatus = Literal["active", "confirmed", "rejected", "expired"]


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

    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None

    explanation: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None


class RadarResponse(BaseModel):
    signals: List[RadarSignal]


# =========================
# 4. СИГНАЛ С ОЦЕНКОЙ
# =========================

class ScoredSignal(BaseModel):
    symbol: str
    strategy: str
    direction: Literal["LONG", "SHORT"]

    confidence: float = Field(..., ge=0, le=1)
    score: float = Field(..., ge=0, le=1)

    timestamp: int


# =========================
# 5. КОНФИГУРАЦИЯ ИСПОЛНЕНИЯ
# =========================

class ExecutionConfig(BaseModel):
    risk_per_trade: float
    leverage: int
    account_balance: float


# =========================
# 6. РЕЗУЛЬТАТ ИСПОЛНЕНИЯ
# =========================

class ExecutionResult(BaseModel):
    status: Literal["FILLED", "REJECTED"]

    symbol: str
    direction: Literal["LONG", "SHORT"]

    entry_price: float
    position_size: float
    timestamp: int


# =========================
# 7. СДЕЛКА
# =========================

class Trade(BaseModel):
    symbol: str

    entry_price: float
    exit_price: Optional[float] = None

    leverage: int
    position_size: float

    pnl: Optional[float] = None
    timestamp: int


# =========================
# 8. АНАЛИЗ СДЕЛКИ
# =========================

class TradeAnalysis(BaseModel):
    trade_score: int = Field(..., ge=0, le=100)
    mistakes: List[str]
    insights: List[str]


# =========================
# 9. API-ОТВЕТЫ
# =========================

class SignalResponse(BaseModel):
    symbol: str
    direction: Literal["LONG", "SHORT"]
    strategy: str
    score: float


class TradeRequest(BaseModel):
    symbol: str
    direction: Literal["LONG", "SHORT"]


class ErrorResponse(BaseModel):
    status: Literal["error"]
    message: str
