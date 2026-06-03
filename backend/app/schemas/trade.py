from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.risk import (
    BreakevenPlan,
    FuturesRiskPlan,
    PositionSizingResult,
    RiskAdjustmentPlan,
    RiskCheckResult,
    RiskDecision,
    RiskOverride,
    StopLossPlan,
    StrategyExecutionSettings,
    TakeProfitPlan,
    TrailingStopPlan,
)
from app.schemas.signal import RadarSignal

ExecutionMode = Literal["virtual", "real"]
TradeSource = Literal["virtual", "real", "backtest"]
TradeSide = Literal["long", "short"]
TradeStatus = Literal["open", "closed", "cancelled"]
TradeResult = Literal["win", "loss", "breakeven"]
CloseReason = Literal[
    "take_profit",
    "stop_loss",
    "manual_close",
    "invalidation",
    "cancelled",
    "partial_take_profit",
    "breakeven_stop",
    "trailing_stop",
    "time_stop",
]
CloseMarketTradeStatus = Literal["closed", "not_implemented"]
TradeInvalidationStatus = Literal["valid", "invalidated", "unavailable"]
TradeInvalidationAction = Literal["none", "close_market_or_wait_stop"]
TradeInvalidationUserAction = Literal["close_market", "keep_stop_loss", "dismissed"]
SimulationMode = Literal["auto", "passive", "impact_aware"]
VirtualSimulationMode = Literal["passive", "impact_aware"]
VirtualSimulationTier = Literal["mvp", "advanced", "pro"]
VirtualSimulationCapabilityStatus = Literal["active", "planned", "stub"]
VirtualExecutionStatus = Literal["filled", "partially_filled", "rejected_virtual_execution"]
ImpactRisk = Literal["low", "medium", "high"]
ExecutionGateStatus = Literal["passed", "warning", "blocked"]
ExecutionOrderRole = Literal["entry", "protective_stop", "take_profit"]
ExecutionOrderSide = Literal["buy", "sell"]
ExecutionOrderType = Literal["market", "limit", "stop", "take_profit"]
ExecutionOrderStatus = Literal[
    "planned",
    "new",
    "dry_run",
    "submitted",
    "partially_filled",
    "filled",
    "canceled",
    "cancelled",
    "rejected",
    "expired",
    "unknown",
]
RealExecutionStatus = Literal[
    "risk_failed",
    "readiness_failed",
    "not_implemented",
    "dry_run",
    "submitted",
    "partially_filled",
    "failed",
]


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


class ExecutionPlannedOrder(BaseModel):
    role: ExecutionOrderRole
    exchange: str
    symbol: str
    side: ExecutionOrderSide
    order_type: ExecutionOrderType
    quantity: float = Field(..., gt=0)
    price: Optional[float] = Field(default=None, gt=0)
    stop_price: Optional[float] = Field(default=None, gt=0)
    reduce_only: bool = False
    close_percent: Optional[float] = Field(default=None, ge=0, le=100)
    time_in_force: Optional[str] = None
    client_order_id: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    status: ExecutionOrderStatus = "planned"
    exchange_order_id: Optional[str] = None
    filled_qty: Optional[float] = Field(default=None, ge=0)
    avg_fill_price: Optional[float] = Field(default=None, gt=0)
    remaining_qty: Optional[float] = Field(default=None, ge=0)
    fees: Optional[float] = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RealExecutionPlan(BaseModel):
    exchange: str
    symbol: str
    side: TradeSide
    entry_price: float = Field(..., gt=0)
    quantity: float = Field(..., gt=0)
    notional: float = Field(..., gt=0)
    leverage: int = Field(..., ge=1)
    idempotency_key: str = Field(..., min_length=1)
    client_order_id: str = Field(..., min_length=1)
    planned_orders: list[ExecutionPlannedOrder] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VirtualSimulationCapability(BaseModel):
    code: str
    name: str
    tier: VirtualSimulationTier
    status: VirtualSimulationCapabilityStatus
    description: str


class VirtualSimulationModelInfo(BaseModel):
    current_tier: VirtualSimulationTier = "advanced"
    active_capabilities: list[VirtualSimulationCapability] = Field(default_factory=list)
    planned_capabilities: list[VirtualSimulationCapability] = Field(default_factory=list)
    data_boundary: str
    notes: list[str] = Field(default_factory=list)


class VirtualImpactPathPoint(BaseModel):
    offset_seconds: float = Field(..., ge=0)
    real_price: float = Field(..., gt=0)
    impact_delta: float
    effective_price: float = Field(..., gt=0)
    impact_remaining_percent: float = Field(..., ge=0, le=100)


class VirtualImpactCandle(BaseModel):
    start_offset_seconds: float = Field(default=0.0, ge=0)
    end_offset_seconds: float = Field(default=60.0, gt=0)
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)


class VirtualSimulatedPositionPath(BaseModel):
    model: Literal["exponential_decay"] = "exponential_decay"
    reference_price: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    post_trade_price: float = Field(..., gt=0)
    initial_impact_delta: float
    decay_lambda: float = Field(..., gt=0)
    decay_horizon_seconds: float = Field(default=60.0, gt=0)
    points: list[VirtualImpactPathPoint] = Field(default_factory=list)
    simulated_candle: VirtualImpactCandle


class VirtualExecutionReport(BaseModel):
    mode: VirtualSimulationMode = "passive"
    simulation_tier: VirtualSimulationTier = "mvp"
    active_capabilities: list[str] = Field(default_factory=list)
    planned_capabilities: list[str] = Field(default_factory=list)
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
    risk_adjustment_plan: Optional[RiskAdjustmentPlan] = None
    risk_check: Optional[RiskCheckResult] = None
    risk_decision: Optional[RiskDecision] = None
    position_sizing: Optional[PositionSizingResult] = None
    stop_loss_plan: Optional[StopLossPlan] = None
    take_profit_plan: Optional[TakeProfitPlan] = None
    breakeven_plan: Optional[BreakevenPlan] = None
    trailing_stop_plan: Optional[TrailingStopPlan] = None
    futures_risk_plan: Optional[FuturesRiskPlan] = None
    simulated_path: Optional[VirtualSimulatedPositionPath] = None
    rejected_reason: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class ManualConfirmRequest(BaseModel):
    mode: ExecutionMode = "virtual"
    user_id: str = "demo_user"
    auto_enter_on_confirmation: bool = False
    account_balance: float = Field(default=100.0, gt=0)
    risk_percent: float | None = Field(default=None, gt=0, le=100)
    risk_override: RiskOverride | None = None
    execution_profile: StrategyExecutionSettings | None = None
    leverage: int = Field(default=1, ge=1, le=100)
    liquidation_price: Optional[float] = Field(default=None, gt=0)
    size_usd: Optional[float] = Field(default=None, gt=0)
    fee_rate: float = Field(default=0.0, ge=0, le=0.01)
    slippage_bps: float = Field(default=0.0, ge=0, le=100)
    simulation_mode: SimulationMode = "auto"
    max_virtual_slippage_bps: float = Field(default=150.0, ge=0, le=2_000)
    allow_partial_fill: bool = True
    min_fill_ratio: float = Field(default=0.25, ge=0, le=1)
    market_snapshot: Optional[VirtualMarketSnapshot] = None
    max_open_positions: int = Field(default=3, ge=1, le=100)


class RealConfirmRequest(ManualConfirmRequest):
    signal_id: str = Field(..., min_length=1)
    mode: Literal["real"] = "real"


class ManualRejectRequest(BaseModel):
    reason: Optional[str] = None


class CloseVirtualTradeRequest(BaseModel):
    exit_price: Optional[float] = Field(default=None, gt=0)
    reason: CloseReason = "manual_close"


class CloseMarketTradeRequest(BaseModel):
    reason: CloseReason = "manual_close"


class TradeInvalidationAlert(BaseModel):
    trade_id: str
    signal_id: Optional[str] = None
    exchange: str
    symbol: str
    strategy: str
    timeframe: str
    side: TradeSide
    status: TradeInvalidationStatus = "valid"
    invalidated: bool = False
    reason: Optional[str] = None
    triggered_conditions: list[str] = Field(default_factory=list)
    watched_conditions: list[str] = Field(default_factory=list)
    suggested_action: TradeInvalidationAction = "none"
    current_price: float
    stop_loss: float
    invalidation_price: Optional[float] = None
    detected_at: datetime
    fingerprint: Optional[str] = None
    user_action: Optional[TradeInvalidationUserAction] = None
    user_action_at: Optional[datetime] = None
    action_dismissed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradeInvalidationActionRequest(BaseModel):
    action: TradeInvalidationUserAction
    user_id: str = "demo_user"


class TradeInvalidationActionResponse(BaseModel):
    action: TradeInvalidationUserAction
    alert: TradeInvalidationAlert
    message: str


class VirtualTradeTargetState(BaseModel):
    label: str
    price: float = Field(..., gt=0)
    close_percent: float = Field(default=0.0, ge=0, le=100)
    action: Optional[str] = None
    hit: bool = False
    hit_at: Optional[datetime] = None
    closed_quantity: float = Field(default=0.0, ge=0)
    closed_size_usd: float = Field(default=0.0, ge=0)
    realized_pnl: float = 0.0
    exit_fee: float = Field(default=0.0, ge=0)


class VirtualTradeLifecycleEvent(BaseModel):
    event_type: str
    reason: Optional[CloseReason] = None
    target_label: Optional[str] = None
    price: Optional[float] = Field(default=None, gt=0)
    quantity: Optional[float] = Field(default=None, ge=0)
    size_usd: Optional[float] = Field(default=None, ge=0)
    realized_pnl: Optional[float] = None
    exit_fee: Optional[float] = Field(default=None, ge=0)
    stop_loss: Optional[float] = Field(default=None, gt=0)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    initial_quantity: Optional[float] = Field(default=None, ge=0)
    remaining_quantity: Optional[float] = Field(default=None, ge=0)
    closed_quantity: float = Field(default=0.0, ge=0)
    initial_size_usd: Optional[float] = Field(default=None, ge=0)
    remaining_size_usd: Optional[float] = Field(default=None, ge=0)
    leverage: int
    risk_percent: float
    risk_amount: float = 0.0
    risk_reward: float = 3.0

    stop_loss: float
    current_stop_loss: Optional[float] = Field(default=None, gt=0)
    stop_moved_to_breakeven: bool = False
    trailing_active: bool = False
    take_profit: list[float] = Field(default_factory=list)
    fees: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    exit_fees: float = Field(default=0.0, ge=0)
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
    target_states: list[VirtualTradeTargetState] = Field(default_factory=list)
    lifecycle_events: list[VirtualTradeLifecycleEvent] = Field(default_factory=list)


class RealExecutionResult(BaseModel):
    mode: Literal["real"] = "real"
    status: RealExecutionStatus = "not_implemented"
    signal_valid: bool = True
    execution_allowed: bool = False
    exchange: str
    symbol: str
    message: str
    risk_decision: Optional[RiskDecision] = None
    risk_decision_id: Optional[str] = None
    execution_plan: Optional[RealExecutionPlan] = None
    planned_orders: list[ExecutionPlannedOrder] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    adapter: Optional[str] = None
    validation_errors: list[str] = Field(default_factory=list)


class ManualDecisionResponse(BaseModel):
    signal: RadarSignal
    virtual_trade: Optional[VirtualTrade] = None
    real_execution: Optional[RealExecutionResult] = None
    real_execution_result: Optional[RealExecutionResult] = None
    message: str

    @model_validator(mode="after")
    def mirror_real_execution_result(self) -> "ManualDecisionResponse":
        if self.real_execution_result is None and self.real_execution is not None:
            self.real_execution_result = self.real_execution
        elif self.real_execution is None and self.real_execution_result is not None:
            self.real_execution = self.real_execution_result
        return self


class VirtualTradeResponse(BaseModel):
    trades: list[VirtualTrade]


class TradeJournalEntry(BaseModel):
    id: str
    user_id: str
    signal_id: Optional[str] = None
    mode: ExecutionMode
    source: TradeSource = "virtual"
    tags: list[str] = Field(default_factory=list)
    run_id: UUID | None = None

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
    initial_quantity: Optional[float] = Field(default=None, ge=0)
    remaining_quantity: Optional[float] = Field(default=None, ge=0)
    closed_quantity: float = Field(default=0.0, ge=0)
    initial_size_usd: Optional[float] = Field(default=None, ge=0)
    remaining_size_usd: Optional[float] = Field(default=None, ge=0)
    leverage: int
    risk_percent: float
    risk_amount: float = 0.0
    risk_reward: float = 3.0

    stop_loss: float
    current_stop_loss: Optional[float] = Field(default=None, gt=0)
    stop_moved_to_breakeven: bool = False
    trailing_active: bool = False
    take_profit: list[float] = Field(default_factory=list)
    fees: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    exit_fees: float = Field(default=0.0, ge=0)
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
    target_states: list[VirtualTradeTargetState] = Field(default_factory=list)
    lifecycle_events: list[VirtualTradeLifecycleEvent] = Field(default_factory=list)


class RealTrade(TradeJournalEntry):
    mode: Literal["real"] = "real"
    source: Literal["real"] = "real"
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


class CloseMarketTradeResponse(BaseModel):
    mode: ExecutionMode
    status: CloseMarketTradeStatus
    message: str
    trade: Optional[TradeJournalEntry] = None


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
