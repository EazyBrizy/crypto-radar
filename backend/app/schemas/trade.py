from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.signal import RadarSignal

ExecutionMode = Literal["virtual", "real"]
TradeSide = Literal["long", "short"]
TradeStatus = Literal["open", "closed", "cancelled"]
TradeResult = Literal["win", "loss", "breakeven"]
CloseReason = Literal["take_profit", "stop_loss", "manual_close", "cancelled"]
SimulationMode = Literal["auto", "passive", "impact_aware"]
VirtualSimulationMode = Literal["passive", "impact_aware"]
VirtualExecutionStatus = Literal["filled", "partially_filled", "rejected_virtual_execution"]
ImpactRisk = Literal["low", "medium", "high"]
ExecutionGateStatus = Literal["passed", "warning", "blocked"]


class OrderBookLevel(BaseModel):
    price: float = Field(..., gt=0)
    quantity: Optional[float] = Field(default=None, gt=0)
    notional_usd: Optional[float] = Field(default=None, gt=0)


class RecentTradePrint(BaseModel):
    price: float = Field(..., gt=0)
    quantity: Optional[float] = Field(default=None, gt=0)
    notional_usd: Optional[float] = Field(default=None, gt=0)
    timestamp: Optional[int] = None


class VirtualMarketSnapshot(BaseModel):
    best_bid: Optional[float] = Field(default=None, gt=0)
    best_ask: Optional[float] = Field(default=None, gt=0)
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    recent_trades: list[RecentTradePrint] = Field(default_factory=list)
    volume_1m_usd: Optional[float] = Field(default=None, ge=0)
    volume_5m_usd: Optional[float] = Field(default=None, ge=0)
    volume_15m_usd: Optional[float] = Field(default=None, ge=0)
    average_trade_size_usd: Optional[float] = Field(default=None, ge=0)
    volatility_1m_percent: Optional[float] = Field(default=None, ge=0)


class LiquidityMetrics(BaseModel):
    spread_percent: float = Field(default=0.0, ge=0)
    orderbook_depth_0_1_percent_usd: float = Field(default=0.0, ge=0)
    orderbook_depth_0_5_percent_usd: float = Field(default=0.0, ge=0)
    orderbook_depth_1_percent_usd: float = Field(default=0.0, ge=0)
    volume_1m_usd: float = Field(default=0.0, ge=0)
    volume_5m_usd: float = Field(default=0.0, ge=0)
    volume_15m_usd: float = Field(default=0.0, ge=0)
    average_trade_size_usd: float = Field(default=0.0, ge=0)
    volatility_1m_percent: float = Field(default=0.0, ge=0)
    liquidity_score: int = Field(default=0, ge=0, le=100)
    impact_score: int = Field(default=0, ge=0, le=100)
    impact_risk: ImpactRisk = "low"


class ExecutionQualityGate(BaseModel):
    status: ExecutionGateStatus = "passed"
    warnings: list[str] = Field(default_factory=list)
    high_impact_reasons: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    suggested_max_size_usd: Optional[float] = Field(default=None, ge=0)
    message: Optional[str] = None


class VirtualExecutionReport(BaseModel):
    mode: VirtualSimulationMode = "passive"
    status: VirtualExecutionStatus = "filled"
    requested_size_usd: float = Field(default=0.0, ge=0)
    filled_size_usd: float = Field(default=0.0, ge=0)
    unfilled_size_usd: float = Field(default=0.0, ge=0)
    fill_ratio: float = Field(default=1.0, ge=0, le=1)
    reference_price: float = Field(default=0.0, ge=0)
    average_price: Optional[float] = Field(default=None, gt=0)
    entry_slippage_bps: float = Field(default=0.0, ge=0)
    exit_slippage_bps: float = Field(default=0.0, ge=0)
    market_impact_percent: float = Field(default=0.0, ge=0)
    best_bid_before: Optional[float] = Field(default=None, gt=0)
    best_ask_before: Optional[float] = Field(default=None, gt=0)
    book_price_after: Optional[float] = Field(default=None, gt=0)
    liquidity: LiquidityMetrics = Field(default_factory=LiquidityMetrics)
    quality_gate: ExecutionQualityGate = Field(default_factory=ExecutionQualityGate)
    rejected_reason: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class ManualConfirmRequest(BaseModel):
    mode: ExecutionMode = "virtual"
    user_id: str = "demo_user"
    account_balance: float = Field(default=100.0, gt=0)
    risk_percent: float = Field(default=10.0, gt=0, le=100)
    leverage: int = Field(default=1, ge=1, le=100)
    size_usd: Optional[float] = Field(default=None, gt=0)
    fee_rate: float = Field(default=0.0, ge=0, le=0.01)
    slippage_bps: float = Field(default=0.0, ge=0, le=100)
    simulation_mode: SimulationMode = "auto"
    max_virtual_slippage_bps: float = Field(default=150.0, ge=0, le=2_000)
    allow_partial_fill: bool = True
    min_fill_ratio: float = Field(default=0.25, ge=0, le=1)
    market_snapshot: Optional[VirtualMarketSnapshot] = None
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
    risk_amount: float = 0.0
    risk_reward: float = 3.0

    stop_loss: float
    take_profit: list[float] = Field(default_factory=list)
    fees: float = 0.0
    slippage_bps: float = 0.0
    simulation_mode: VirtualSimulationMode = "passive"
    execution_status: VirtualExecutionStatus = "filled"
    requested_size_usd: Optional[float] = Field(default=None, ge=0)
    filled_size_usd: Optional[float] = Field(default=None, ge=0)
    unfilled_size_usd: float = Field(default=0.0, ge=0)
    execution: Optional[VirtualExecutionReport] = None

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


class TradeJournalEntry(BaseModel):
    id: str
    user_id: str
    signal_id: Optional[str] = None
    mode: ExecutionMode

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
    risk_amount: float = 0.0
    risk_reward: float = 3.0

    stop_loss: float
    take_profit: list[float] = Field(default_factory=list)
    fees: float = 0.0
    slippage_bps: float = 0.0
    simulation_mode: VirtualSimulationMode = "passive"
    execution_status: VirtualExecutionStatus = "filled"
    requested_size_usd: Optional[float] = Field(default=None, ge=0)
    filled_size_usd: Optional[float] = Field(default=None, ge=0)
    unfilled_size_usd: float = Field(default=0.0, ge=0)
    execution: Optional[VirtualExecutionReport] = None

    status: TradeStatus
    result: Optional[TradeResult] = None
    close_reason: Optional[CloseReason] = None
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    mfe: float = 0.0
    mae: float = 0.0

    screenshots: list[str] = Field(default_factory=list)
    ai_review: Optional[str] = None

    opened_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None


class RealTrade(TradeJournalEntry):
    mode: Literal["real"] = "real"
    exchange_order_id: Optional[str] = None


class VirtualAccount(BaseModel):
    user_id: str = "demo_user"
    starting_balance: float = 100.0
    balance: float = 100.0
    equity: float = 100.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    risk_per_trade: float = 10.0
    risk_reward: float = 3.0
    open_positions: int = 0
    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    updated_at: datetime


class TradeJournalResponse(BaseModel):
    trades: list[TradeJournalEntry]
    account: Optional[VirtualAccount] = None


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
