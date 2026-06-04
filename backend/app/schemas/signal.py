from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.decision import SignalDecisionSnapshot
from app.schemas.trade_plan import TradePlan
from app.schemas.market import CandleState


class SignalScoreBreakdown(BaseModel):
    trend_score: int = Field(default=0, ge=0)
    volume_score: int = Field(default=0, ge=0)
    liquidity_score: int = Field(default=0, ge=0)
    orderbook_score: int = Field(default=0, ge=0)
    risk_reward_score: int = Field(default=0, ge=0)
    volatility_score: int = Field(default=0, ge=0)
    overheat_penalty: int = Field(default=0, ge=0)
    news_event_risk_penalty: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0, le=100)


class SignalEdgeSnapshot(BaseModel):
    status: Literal["unknown", "positive", "negative", "insufficient_sample"]
    sample_size: int = Field(default=0, ge=0)
    min_sample_size: int = Field(ge=0)
    winrate: Optional[float] = None
    avg_win_r: Optional[float] = None
    avg_loss_r: Optional[float] = None
    expectancy_r: Optional[float] = None
    expectancy_after_costs_r: Optional[float] = None
    profit_factor: Optional[float] = None
    confidence_score: float = Field(default=0.0, ge=0, le=1)
    source: Literal["outcome", "backtest", "mixed", "none"] = "none"
    score_bucket: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


LayerCheckStatus = Literal["passed", "warning", "failed", "skipped"]
RadarRRStatus = Literal["passed", "warning", "failed", "skipped", "unknown"]
RadarRiskGateStatus = Literal["passed", "warning", "failed"]


class SignalLayerCheck(BaseModel):
    name: str
    status: LayerCheckStatus = "passed"
    score: Optional[float] = None
    reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketQualitySnapshot(BaseModel):
    passed: bool = True
    tier: Literal["major", "mid_alt", "low_liquidity", "unknown"] = "unknown"
    score: int = Field(default=100, ge=0, le=100)
    volume_24h_quote: Optional[float] = None
    spread_bps: Optional[float] = None
    history_ok: bool = True
    rough_chart_score: Optional[float] = None
    checks: List[SignalLayerCheck] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class NoTradeFilterResult(BaseModel):
    enabled: bool = True
    blocked: bool = False
    hard_block: bool = False
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    checks: List[SignalLayerCheck] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketRegimeSnapshot(BaseModel):
    signal_timeframe: str = "stream"
    context_timeframe: Optional[str] = None
    direction: Literal["bullish", "bearish", "range", "unknown"] = "unknown"
    strength: Literal["weak", "normal", "strong", "unknown"] = "unknown"
    alignment: Literal["aligned", "mixed", "against", "unknown"] = "unknown"
    score_adjustment: int = 0
    checks: List[SignalLayerCheck] = Field(default_factory=list)


class StrategySetupSnapshot(BaseModel):
    name: str
    stage: Literal["forming", "ready", "confirmed"] = "ready"
    checks: List[SignalLayerCheck] = Field(default_factory=list)


class SignalConfirmationSnapshot(BaseModel):
    passed: bool = False
    checks: List[SignalLayerCheck] = Field(default_factory=list)


class SignalInvalidationSnapshot(BaseModel):
    price: Optional[float] = None
    hard_stop: Optional[float] = None
    conditions: List[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignalExitPlanSnapshot(BaseModel):
    targets: List[dict[str, Any]] = Field(default_factory=list)
    breakeven: dict[str, Any] = Field(default_factory=dict)
    trailing: dict[str, Any] = Field(default_factory=dict)


class SignalAutoEntrySnapshot(BaseModel):
    enabled: bool = False
    status: Literal["pending", "triggered", "failed", "cancelled", "requires_reconfirmation"] = "pending"
    mode: Literal["virtual", "real"] = "virtual"
    user_id: str = "demo_user"
    armed_at: Optional[datetime] = None
    triggered_at: Optional[datetime] = None
    message: Optional[str] = None
    request: dict[str, Any] = Field(default_factory=dict)
    trade_id: Optional[str] = None
    real_execution: Optional[dict[str, Any]] = None


SignalDirection = Literal["long", "short"]
SignalUrgency = Literal["low", "medium", "high"]
SignalStatus = Literal[
    "new",
    "active",
    "watchlist",
    "ready",
    "actionable",
    "wait_for_pullback",
    "confirmed",
    "rejected",
    "expired",
    "invalidated",
    "closed",
    "entry_touched",
]


class StrategySignal(BaseModel):
    exchange: str = "bybit"
    symbol: str
    strategy: str
    direction: Literal["LONG", "SHORT"]
    confidence: float = Field(..., ge=0, le=1)
    timestamp: int
    score: int = Field(default=0, ge=0, le=100)
    timeframe: str = "stream"
    candle_state: CandleState = "closed"

    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    risk_reward: Optional[float] = Field(default=None, ge=0)
    first_target_rr: Optional[float] = Field(default=None, ge=0)
    final_target_rr: Optional[float] = Field(default=None, ge=0)
    selected_rr: Optional[float] = Field(default=None, ge=0)
    selected_rr_target: Optional[str] = None
    min_rr_ratio: Optional[float] = Field(default=None, ge=0)
    urgency: Literal["low", "medium", "high"] = "medium"
    explanation: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    score_breakdown: SignalScoreBreakdown = Field(
        default_factory=lambda: SignalScoreBreakdown()
    )
    status: SignalStatus = "active"
    status_reason: Optional[str] = None
    quality: Optional[MarketQualitySnapshot] = None
    regime: Optional[MarketRegimeSnapshot] = None
    setup: Optional[StrategySetupSnapshot] = None
    confirmation: Optional[SignalConfirmationSnapshot] = None
    invalidation: Optional[SignalInvalidationSnapshot] = None
    exit_plan: Optional[SignalExitPlanSnapshot] = None
    trade_plan: Optional[TradePlan] = None
    auto_entry: Optional[SignalAutoEntrySnapshot] = None
    edge: Optional[SignalEdgeSnapshot] = None
    no_trade_filter: Optional[NoTradeFilterResult] = None
    decision: Optional[SignalDecisionSnapshot] = None


class RadarSignal(BaseModel):
    id: str
    symbol: str
    exchange: str
    strategy: str
    direction: SignalDirection
    confidence: float = Field(..., ge=0, le=1)
    risk_reward: Optional[float] = Field(default=None, ge=0)
    first_target_rr: Optional[float] = Field(default=None, ge=0)
    final_target_rr: Optional[float] = Field(default=None, ge=0)
    selected_rr: Optional[float] = Field(default=None, ge=0)
    selected_rr_target: Optional[str] = None
    min_rr_ratio: Optional[float] = Field(default=None, ge=0)
    urgency: SignalUrgency = "medium"
    status: SignalStatus = "active"
    score: int = Field(default=0, ge=0, le=100)
    timeframe: str = "stream"
    candle_state: CandleState = "closed"

    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None

    explanation: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    score_breakdown: SignalScoreBreakdown = Field(default_factory=SignalScoreBreakdown)
    status_reason: Optional[str] = None
    quality: Optional[MarketQualitySnapshot] = None
    regime: Optional[MarketRegimeSnapshot] = None
    setup: Optional[StrategySetupSnapshot] = None
    confirmation: Optional[SignalConfirmationSnapshot] = None
    invalidation: Optional[SignalInvalidationSnapshot] = None
    exit_plan: Optional[SignalExitPlanSnapshot] = None
    trade_plan: Optional[TradePlan] = None
    auto_entry: Optional[SignalAutoEntrySnapshot] = None
    edge: Optional[SignalEdgeSnapshot] = None
    no_trade_filter: Optional[NoTradeFilterResult] = None
    decision: Optional[SignalDecisionSnapshot] = None
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    decision_mode: Optional[Literal["virtual", "real"]] = None
    decision_note: Optional[str] = None
    confirmed_trade_id: Optional[str] = None
    rr_status: Optional[RadarRRStatus] = None
    risk_gate_status: Optional[RadarRiskGateStatus] = None
    can_enter: Optional[bool] = None
    display_reason: Optional[str] = None


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
