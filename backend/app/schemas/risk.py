from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.lifecycle import LifecycleTrace
from app.schemas.market import OrderBookSnapshot
from app.schemas.signal import NoTradeFilterResult, SignalEdgeSnapshot
from app.schemas.trade_plan import TradePlan

StopLossMode = Literal["fixed_percent", "atr", "structure"]
TakeProfitMode = Literal["risk_multiple"]
TrailingMode = Literal["atr", "percent", "structure"]
VirtualRiskMode = Literal["same_as_real", "custom"]
VirtualSlippageModel = Literal["none", "fixed_percent", "spread_based", "orderbook_based", "volatility_based"]
VirtualFeeModel = Literal["manual", "exchange_based"]
VirtualExecutionProfile = Literal["realistic", "relaxed_paper", "deterministic_test"]
VirtualFillPolicy = Literal["strict_orderbook", "relaxed_market_fallback", "deterministic_market_fill"]
RiskCheckStatus = Literal["passed", "warning", "failed"]
RiskExecutionMode = Literal["virtual", "real"]
ExecutionMode = Literal["virtual", "real"]
InstrumentType = Literal["spot", "futures"]
TradeInstrumentType = InstrumentType
LegacyTradeInstrumentType = Literal["spot", "futures", "virtual"]
RiskAmountMode = Literal["percent", "fixed"]
RadarDisplayMode = Literal["all_market_opportunities", "execution_ready"]
RRGuardMode = Literal["off", "soft", "hard"]
RRTarget = Literal["nearest", "final"]
RiskDecisionStage = Literal["preview", "pre_execution", "post_execution", "confirm"]
RiskProtectionMode = Literal["normal", "reduced", "virtual_only", "blocked"]
ExchangeRuleStatus = Literal["fresh", "missing", "stale", "unknown"]
MarketDataStatus = Literal["fresh", "partial", "missing", "stale", "unknown"]
FuturesRiskStatus = Literal["passed", "blocked", "unknown"]
AccountRiskSnapshotStatus = Literal["fresh", "stale", "missing"]
AccountRiskSnapshotSource = Literal["exchange", "request", "virtual", "dry_run", "demo"]
TakeProfitTargetLabel = Literal["TP1", "TP2", "TP3"]
TakeProfitAction = Literal[
    "move_stop_to_breakeven",
    "trailing_stop",
    "full_close",
    "observe",
]

LEGACY_VIRTUAL_INSTRUMENT_WARNING = (
    "instrument_type=virtual is deprecated; use mode=virtual with "
    "instrument_type=spot or instrument_type=futures."
)


def normalize_instrument_type(
    value: LegacyTradeInstrumentType | str | None,
    *,
    leverage: int | Decimal | float | str | None = None,
    default: InstrumentType = "spot",
) -> tuple[InstrumentType, list[str]]:
    normalized = str(value or default).strip().lower()
    if normalized == "futures":
        return "futures", []
    if normalized == "virtual":
        leverage_value = _numeric_leverage(leverage)
        derived: InstrumentType = "futures" if leverage_value > 1 else default
        return derived, [LEGACY_VIRTUAL_INSTRUMENT_WARNING]
    return "spot", []


def _numeric_leverage(value: int | Decimal | float | str | None) -> Decimal:
    if value is None:
        return Decimal("1")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("1")


class PositionRiskSummary(BaseModel):
    symbol: str | None = None
    side: Literal["long", "short", "unknown"] = "unknown"
    quantity: Decimal | None = Field(default=None, ge=0)
    notional: Decimal | None = Field(default=None, ge=0)
    entry_price: Decimal | None = Field(default=None, gt=0)
    mark_price: Decimal | None = Field(default=None, gt=0)
    unrealized_pnl: Decimal | None = None
    risk_amount: Decimal | None = Field(default=None, ge=0)
    initial_margin: Decimal | None = Field(default=None, ge=0)
    maintenance_margin: Decimal | None = Field(default=None, ge=0)
    margin_mode: str | None = None


class AccountRiskSnapshot(BaseModel):
    status: AccountRiskSnapshotStatus
    fetched_at: datetime | None = None
    account_equity: Decimal | None = Field(default=None, gt=0)
    available_balance: Decimal | None = Field(default=None, ge=0)
    wallet_balance: Decimal | None = Field(default=None, ge=0)
    margin_mode: str | None = None
    total_initial_margin: Decimal | None = Field(default=None, ge=0)
    total_maintenance_margin: Decimal | None = Field(default=None, ge=0)
    maintenance_margin_rate: Decimal | None = Field(default=None, ge=0)
    positions: list[PositionRiskSummary] = Field(default_factory=list)
    open_risk_amount: Decimal = Field(default=Decimal("0"), ge=0)
    source: AccountRiskSnapshotSource
    warnings: list[str] = Field(default_factory=list)


class PositionSizingResult(BaseModel):
    side: Literal["long", "short"]
    account_equity: float = Field(..., gt=0)
    risk_mode: RiskAmountMode = "percent"
    fixed_risk_amount: float | None = Field(default=None, ge=0)
    requested_risk_amount: float | None = Field(default=None, ge=0)
    effective_risk_amount: float | None = Field(default=None, ge=0)
    risk_amount_capped: bool = False
    risk_cap_amount: float | None = Field(default=None, ge=0)
    risk_per_trade_percent: float = Field(..., ge=0)
    risk_amount: float = Field(..., ge=0)
    entry_price: float = Field(..., gt=0)
    stop_loss_price: float = Field(..., gt=0)
    stop_distance_per_unit: float = Field(..., gt=0)
    estimated_entry_fee_per_unit: float = Field(default=0.0, ge=0)
    estimated_exit_fee_per_unit: float = Field(default=0.0, ge=0)
    slippage_buffer_per_unit: float = Field(default=0.0, ge=0)
    funding_buffer_per_unit: float = Field(default=0.0, ge=0)
    effective_risk_per_unit: float = Field(..., gt=0)
    position_size_base: float = Field(..., ge=0)
    notional: float = Field(..., ge=0)
    leverage: int = Field(..., ge=1)
    required_margin: float = Field(..., ge=0)
    fee_rate: float = Field(default=0.0, ge=0)
    slippage_bps: float = Field(default=0.0, ge=0)
    include_fees_in_risk: bool = True
    include_slippage_in_risk: bool = True


class StrategyExecutionSettings(BaseModel):
    """Typed execution profile stored over legacy JSON risk settings."""

    model_config = ConfigDict(extra="allow")

    risk_mode: RiskAmountMode = "percent"
    risk_percent: Decimal | None = Field(default=None, gt=0, le=100)
    fixed_risk_amount: Decimal | None = Field(default=None, gt=0)
    fixed_risk_currency: str = Field(default="USDT", min_length=1, max_length=16)
    leverage: Decimal | None = Field(default=None, ge=1, le=125)
    instrument_type: InstrumentType | None = None
    rr_guard_mode: RRGuardMode | None = None
    min_rr_ratio: Decimal | None = Field(default=None, ge=0, le=100)
    rr_target: RRTarget | None = None
    radar_display_mode: RadarDisplayMode | None = None

    # Legacy percent fields remain accepted for JSONB/API backward compatibility.
    risk_per_trade_percent: Decimal | None = Field(default=None, gt=0, le=100)
    futures_risk_per_trade_percent: Decimal | None = Field(default=None, gt=0, le=100)
    spot_risk_per_trade_percent: Decimal | None = Field(default=None, gt=0, le=100)
    virtual_risk_per_trade_percent: Decimal | None = Field(default=None, gt=0, le=100)

    legacy_instrument_type: str | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_instrument_type(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_instrument_type = data.get("instrument_type")
        if isinstance(raw_instrument_type, str) and raw_instrument_type.strip().lower() == "virtual":
            values = dict(data)
            values["instrument_type"], _ = normalize_instrument_type(
                raw_instrument_type,
                leverage=values.get("leverage"),
            )
            values["legacy_instrument_type"] = "virtual"
            return values
        return data

    @model_validator(mode="after")
    def validate_execution_profile(self) -> "StrategyExecutionSettings":
        self.fixed_risk_currency = self.fixed_risk_currency.strip().upper() or "USDT"
        if self.risk_mode == "fixed" and self.fixed_risk_amount is None:
            raise ValueError("fixed_risk_amount is required when risk_mode is fixed")
        return self

    def to_legacy_dict(self, *, exclude_unset: bool = False) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, exclude_unset=exclude_unset)


class RiskOverride(BaseModel):
    """Explicit per-request risk override for preview/confirm flows."""

    model_config = ConfigDict(extra="forbid")

    risk_mode: RiskAmountMode
    risk_percent: Decimal | None = Field(default=None, gt=0, le=100)
    fixed_risk_amount: Decimal | None = Field(default=None, gt=0)
    leverage: Decimal | None = Field(default=None, ge=1, le=125)

    @model_validator(mode="after")
    def validate_risk_override(self) -> "RiskOverride":
        if self.risk_mode == "percent" and self.risk_percent is None:
            raise ValueError("risk_percent is required when risk_mode is percent")
        if self.risk_mode == "fixed" and self.fixed_risk_amount is None:
            raise ValueError("fixed_risk_amount is required when risk_mode is fixed")
        return self

    def to_execution_settings(self) -> StrategyExecutionSettings:
        return StrategyExecutionSettings.model_validate(
            self.model_dump(mode="json", exclude_none=True)
        )


class ResolvedExecutionProfile(BaseModel):
    execution_mode: ExecutionMode
    instrument_type: InstrumentType
    risk_mode: RiskAmountMode
    risk_percent: Decimal | None = Field(default=None, gt=0, le=100)
    fixed_risk_amount: Decimal | None = Field(default=None, gt=0)
    fixed_risk_currency: str = Field(default="USDT", min_length=1, max_length=16)
    leverage: Decimal = Field(default=Decimal("1"), ge=1, le=125)
    rr_guard_mode: RRGuardMode = "soft"
    min_rr_ratio: Decimal = Field(default=Decimal("2.0"), ge=0, le=100)
    rr_target: RRTarget = "final"
    radar_display_mode: RadarDisplayMode = "all_market_opportunities"
    sources: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resolved_profile(self) -> "ResolvedExecutionProfile":
        self.fixed_risk_currency = self.fixed_risk_currency.strip().upper() or "USDT"
        if self.risk_mode == "fixed" and self.fixed_risk_amount is None:
            raise ValueError("fixed_risk_amount is required when risk_mode is fixed")
        if self.risk_mode == "percent" and self.risk_percent is None:
            raise ValueError("risk_percent is required when risk_mode is percent")
        return self


class RiskAdjustmentPlan(BaseModel):
    instrument_type: TradeInstrumentType
    strategy: str
    signal_score: float = Field(..., ge=0, le=100)
    account_equity: float = Field(..., gt=0)
    risk_mode: RiskAmountMode = "percent"
    fixed_risk_amount: float | None = Field(default=None, ge=0)
    requested_risk_amount: float = Field(default=0.0, ge=0)
    effective_risk_amount: float = Field(default=0.0, ge=0)
    risk_amount_capped: bool = False
    risk_cap_amount: float | None = Field(default=None, ge=0)
    risk_cap_percent: float | None = Field(default=None, ge=0)
    base_risk_percent: float = Field(..., gt=0)
    base_risk_amount: float = Field(..., ge=0)
    strategy_risk_multiplier: float = Field(..., ge=0)
    signal_score_multiplier: float = Field(..., ge=0)
    volatility_multiplier: float = Field(default=1.0, ge=0)
    user_mode_multiplier: float = Field(default=1.0, ge=0)
    adjusted_risk_percent: float = Field(..., ge=0)
    adjusted_risk_amount: float = Field(..., ge=0)
    signal_trade_allowed: bool
    signal_virtual_only: bool = False
    warnings: list[str] = Field(default_factory=list)


class RiskCheckResult(BaseModel):
    status: RiskCheckStatus
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason_code: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    technical_message: str | None = None
    technical_messages: list[str] = Field(default_factory=list)
    rr: float | None = Field(default=None, ge=0)
    min_rr_ratio: float = Field(..., ge=0)
    risk_reward_guard_mode: RRGuardMode = "soft"
    risk_reward_warning: bool = False
    risk_reward_warning_reason: str | None = None
    risk_reward_blocked: bool = False
    risk_reward_block_reason: str | None = None
    account_equity: float = Field(..., gt=0)
    adjusted_risk_amount: float = Field(..., ge=0)
    adjusted_risk_percent: float = Field(..., ge=0)
    effective_risk_amount: float = Field(default=0.0, ge=0)
    position_notional: float = Field(..., ge=0)
    position_size_base: float = Field(..., ge=0)
    required_margin: float = Field(..., ge=0)
    available_balance: float | None = Field(default=None, ge=0)
    close_only: bool = False
    real_entries_allowed: bool = True
    virtual_entries_allowed: bool = True
    reduce_only_allowed: bool = True
    protective_orders_allowed: bool = True
    daily_risk_used_percent: float | None = Field(default=None, ge=0)
    max_daily_loss_percent: float = Field(..., ge=0)
    account_drawdown_percent: float | None = Field(default=None, ge=0)
    max_account_drawdown_percent: float = Field(..., ge=0)
    open_risk_used_percent: float | None = Field(default=None, ge=0)
    max_open_risk_percent: float = Field(..., ge=0)
    correlated_risk_used_percent: float | None = Field(default=None, ge=0)
    max_correlated_risk_percent: float = Field(..., ge=0)
    protection_state: RiskProtectionMode = "normal"
    exchange_rule_status: ExchangeRuleStatus = "unknown"
    exchange_rule_age_seconds: float | None = Field(default=None, ge=0)
    exchange_rule_ttl_seconds: int | None = Field(default=None, ge=0)
    market_data_status: MarketDataStatus = "unknown"
    best_bid: float | None = Field(default=None, gt=0)
    best_ask: float | None = Field(default=None, gt=0)
    mark_price: float | None = Field(default=None, gt=0)
    funding_rate: float | None = None
    funding_buffer_amount: float = Field(default=0.0, ge=0)
    fee_rate_source: str | None = None
    maker_fee_rate: float | None = Field(default=None, ge=0)
    taker_fee_rate: float | None = Field(default=None, ge=0)
    spread_percent: float | None = Field(default=None, ge=0)
    spread_bps: float | None = Field(default=None, ge=0)
    max_spread_bps: float = Field(default=0.0, ge=0)
    slippage_bps: float = Field(default=0.0, ge=0)
    max_slippage_bps: float = Field(default=0.0, ge=0)
    price_deviation_bps: float | None = Field(default=None, ge=0)
    max_price_deviation_bps: float = Field(default=0.0, ge=0)
    orderbook_depth_usd: float | None = Field(default=None, ge=0)
    orderbook_can_fill: bool | None = None
    orderbook_liquidity_ratio: float | None = Field(default=None, ge=0)
    max_orderbook_liquidity_ratio: float = Field(default=1.0, ge=0)
    orderbook_source: str | None = None
    orderbook_freshness_status: MarketDataStatus = "unknown"
    orderbook_fetched_at: datetime | None = None
    orderbook_age_seconds: float | None = Field(default=None, ge=0)
    orderbook_depth_levels: int = Field(default=0, ge=0)
    orderbook_vwap_price: float | None = Field(default=None, gt=0)
    orderbook_vwap_impact_bps: float | None = Field(default=None, ge=0)
    orderbook_slippage_bps: float | None = Field(default=None, ge=0)
    orderbook_fillable_notional_usd: float | None = Field(default=None, ge=0)


class StopLossPlan(BaseModel):
    side: Literal["long", "short"]
    mode: StopLossMode
    entry_price: float = Field(..., gt=0)
    stop_loss_price: float = Field(..., gt=0)
    risk_per_unit: float = Field(..., gt=0)
    source: str
    default_stop_loss_percent: float = Field(..., gt=0)
    atr_period: int = Field(..., ge=2)
    atr_multiplier: float = Field(..., gt=0)
    atr_value: float | None = Field(default=None, gt=0)
    warnings: list[str] = Field(default_factory=list)


class TakeProfitTarget(BaseModel):
    label: TakeProfitTargetLabel
    r_multiple: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    close_percent: float = Field(..., ge=0, le=100)
    action: TakeProfitAction


class TakeProfitPlan(BaseModel):
    mode: TakeProfitMode
    side: Literal["long", "short"]
    entry_price: float = Field(..., gt=0)
    stop_loss_price: float = Field(..., gt=0)
    risk_per_unit: float = Field(..., gt=0)
    partial_take_profit_enabled: bool
    targets: list[TakeProfitTarget] = Field(default_factory=list)
    source: str = "risk_settings"
    selected_rr: float | None = Field(default=None, ge=0)
    selected_rr_target: str | None = None
    notes: list[str] = Field(default_factory=list)


class BreakevenPlan(BaseModel):
    side: Literal["long", "short"]
    entry_price: float = Field(..., gt=0)
    stop_loss_price: float = Field(..., gt=0)
    risk_per_unit: float = Field(..., gt=0)
    move_after_r: float = Field(..., gt=0)
    trigger_price: float = Field(..., gt=0)
    breakeven_stop_price: float = Field(..., gt=0)
    offset_percent: float = Field(default=0.0, ge=0)


class TrailingStopPlan(BaseModel):
    side: Literal["long", "short"]
    enabled: bool
    mode: TrailingMode
    entry_price: float = Field(..., gt=0)
    current_price: float = Field(..., gt=0)
    trailing_distance: float | None = Field(default=None, gt=0)
    trailing_stop_price: float | None = Field(default=None, gt=0)
    trailing_percent: float = Field(default=0.0, ge=0)
    atr_multiplier: float = Field(..., gt=0)
    atr_value: float | None = Field(default=None, gt=0)
    structure_stop_price: float | None = Field(default=None, gt=0)
    source: str
    warnings: list[str] = Field(default_factory=list)


class LiquidationProjectionResult(BaseModel):
    projected_liquidation_price: float | None = Field(default=None, gt=0)
    distance_to_liquidation: float | None = Field(default=None, ge=0)
    distance_to_liquidation_percent: float | None = Field(default=None, ge=0)
    margin_mode: str | None = None
    maintenance_margin_rate: float | None = Field(default=None, ge=0)
    maintenance_margin_amount: float | None = Field(default=None, ge=0)
    liquidation_price_source: str = "unavailable"
    formula: str | None = None
    formula_source: str | None = None
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class FuturesRiskPlan(BaseModel):
    side: Literal["long", "short"]
    status: FuturesRiskStatus
    entry_price: float = Field(..., gt=0)
    stop_loss_price: float = Field(..., gt=0)
    leverage: int = Field(..., ge=1)
    max_leverage: int = Field(..., ge=1)
    leverage_allowed: bool
    liquidation_price: float | None = Field(default=None, gt=0)
    liquidation_buffer_percent: float | None = Field(default=None, ge=0)
    projected_liquidation_price: float | None = Field(default=None, gt=0)
    distance_to_liquidation: float | None = Field(default=None, ge=0)
    distance_to_liquidation_percent: float | None = Field(default=None, ge=0)
    liquidation_price_source: str = "unavailable"
    margin_mode: str | None = None
    maintenance_margin_rate: float | None = Field(default=None, ge=0)
    maintenance_margin_amount: float | None = Field(default=None, ge=0)
    liquidation_projection: LiquidationProjectionResult | None = None
    min_liquidation_buffer_percent: float = Field(..., ge=0)
    liquidation_before_stop: bool | None = None
    message: str
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class RiskContext(BaseModel):
    mode: RiskExecutionMode
    rr_guard_context: str | None = None
    stage: RiskDecisionStage = "preview"
    user_id: str = "demo_user"
    signal_id: str | None = None
    pending_entry_intent_id: str | None = None
    lifecycle_trace: LifecycleTrace = Field(default_factory=LifecycleTrace)
    risk_profile_source: str = "unknown"
    execution_profile_sources: dict[str, str] = Field(default_factory=dict)
    execution_profile: ResolvedExecutionProfile | None = None
    normalization_warnings: list[str] = Field(default_factory=list)
    exchange: str
    symbol: str
    instrument_type: TradeInstrumentType
    side: Literal["long", "short"]
    strategy: str
    signal_score: float = Field(..., ge=0, le=100)
    account_equity: float = Field(..., gt=0)
    available_balance: float | None = Field(default=None, ge=0)
    account_snapshot_status: AccountRiskSnapshotStatus | None = None
    account_snapshot_source: AccountRiskSnapshotSource | None = None
    account_snapshot_fetched_at: datetime | None = None
    account_margin_mode: str | None = None
    account_snapshot: AccountRiskSnapshot | None = None
    account_snapshot_warnings: list[str] = Field(default_factory=list)
    entry_price: float = Field(..., gt=0)
    signal_entry_price: float | None = Field(default=None, gt=0)
    signal_stop_loss_price: float | None = Field(default=None, gt=0)
    atr_value: float | None = Field(default=None, gt=0)
    structure_stop_loss_price: float | None = Field(default=None, gt=0)
    current_price: float | None = Field(default=None, gt=0)
    leverage: int = Field(default=1, ge=1)
    liquidation_price: float | None = Field(default=None, gt=0)
    fee_rate: float = Field(default=0.0, ge=0)
    fee_rate_source: str | None = None
    maker_fee_rate: float | None = Field(default=None, ge=0)
    taker_fee_rate: float | None = Field(default=None, ge=0)
    fee_rate_warnings: list[str] = Field(default_factory=list)
    slippage_bps: float = Field(default=0.0, ge=0)
    funding_buffer_per_unit: float = Field(default=0.0, ge=0)
    best_bid: float | None = Field(default=None, gt=0)
    best_ask: float | None = Field(default=None, gt=0)
    mark_price: float | None = Field(default=None, gt=0)
    funding_rate: float | None = None
    spread_percent: float | None = Field(default=None, ge=0)
    spread_bps: float | None = Field(default=None, ge=0)
    orderbook_depth_usd: float | None = Field(default=None, ge=0)
    orderbook_snapshot: OrderBookSnapshot | None = None
    market_data_status: MarketDataStatus = "unknown"
    market_data_source: str | None = None
    market_data_warnings: list[str] = Field(default_factory=list)
    requested_notional: float | None = Field(default=None, gt=0)
    open_risk_amount: float = Field(default=0.0, ge=0)
    correlated_open_risk_amount: float = Field(default=0.0, ge=0)
    daily_loss_amount: float = Field(default=0.0, ge=0)
    exchange_min_order_size: float | None = Field(default=None, gt=0)
    exchange_max_order_size: float | None = Field(default=None, gt=0)
    exchange_min_notional: float | None = Field(default=None, gt=0)
    exchange_max_leverage: int | None = Field(default=None, ge=1)
    exchange_rule_status: ExchangeRuleStatus = "unknown"
    exchange_rule_age_seconds: float | None = Field(default=None, ge=0)
    exchange_rule_ttl_seconds: int | None = Field(default=None, ge=0)
    instrument_rules: dict[str, Any] | None = None
    correlation_group: str | None = None
    protection_state: RiskProtectionMode = "normal"
    protection_reason: str | None = None
    account_drawdown_percent: float | None = Field(default=None, ge=0)
    max_account_drawdown_percent: float = Field(default=0.0, ge=0)
    volatility_multiplier: float = Field(default=1.0, ge=0)
    user_mode_multiplier: float = Field(default=1.0, ge=0)
    manual_take_profit_price: float | None = Field(default=None, gt=0)
    trade_plan: TradePlan | None = None
    signal_edge: SignalEdgeSnapshot | None = None
    no_trade_filter: NoTradeFilterResult | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_context_instrument(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_instrument_type = data.get("instrument_type")
        if not isinstance(raw_instrument_type, str) or raw_instrument_type.strip().lower() != "virtual":
            return data
        values = dict(data)
        values["mode"] = "virtual"
        values["instrument_type"], warnings = normalize_instrument_type(
            raw_instrument_type,
            leverage=values.get("leverage"),
        )
        values["normalization_warnings"] = [
            *values.get("normalization_warnings", []),
            *warnings,
        ]
        return values


class RiskDecision(BaseModel):
    mode: RiskExecutionMode
    stage: RiskDecisionStage
    status: RiskCheckStatus
    can_enter: bool
    lifecycle_trace: LifecycleTrace = Field(default_factory=LifecycleTrace)
    risk_profile_source: str = "unknown"
    execution_profile_sources: dict[str, str] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason_code: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    technical_message: str | None = None
    technical_messages: list[str] = Field(default_factory=list)
    exchange: str
    symbol: str
    instrument_type: TradeInstrumentType
    requested_notional: float | None = Field(default=None, ge=0)
    risk_adjustment_plan: RiskAdjustmentPlan
    position_sizing: PositionSizingResult
    checked_position_sizing: PositionSizingResult
    risk_check: RiskCheckResult
    stop_loss_plan: StopLossPlan
    take_profit_plan: TakeProfitPlan
    breakeven_plan: BreakevenPlan
    trailing_stop_plan: TrailingStopPlan
    futures_risk_plan: FuturesRiskPlan | None = None
    notes: list[str] = Field(default_factory=list)


class RiskPreviewRequest(BaseModel):
    signal_id: str = Field(..., min_length=1)
    pending_entry_intent_id: str | None = Field(default=None, min_length=1)
    mode: RiskExecutionMode = "virtual"
    user_id: str = "demo_user"
    instrument_type: LegacyTradeInstrumentType | None = None
    leverage: int = Field(default=1, ge=1, le=125)
    liquidation_price: float | None = Field(default=None, gt=0)
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)
    size_usd: float | None = Field(default=None, gt=0)
    account_balance: float = Field(default=100.0, gt=0)
    risk_percent: float | None = Field(default=None, gt=0, le=100)
    risk_override: RiskOverride | None = None
    execution_profile: StrategyExecutionSettings | None = None
    fee_rate: float = Field(default=0.0, ge=0, le=0.01)
    slippage_bps: float = Field(default=0.0, ge=0, le=2_000)
    atr_value: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def normalize_legacy_preview_mode(self) -> "RiskPreviewRequest":
        if self.instrument_type == "virtual":
            self.mode = "virtual"
        return self


class RiskStateResponse(BaseModel):
    user_id: str
    mode: RiskExecutionMode | None = None
    protection_state: RiskProtectionMode = "normal"
    protection_reason: str | None = None
    close_only: bool = False
    real_entries_allowed: bool = True
    virtual_entries_allowed: bool = True
    reduce_only_allowed: bool = True
    protective_orders_allowed: bool = True
    loss_streak: int = Field(default=0, ge=0)
    daily_loss_amount: float = Field(default=0.0, ge=0)
    weekly_loss_amount: float = Field(default=0.0, ge=0)
    daily_window_start: datetime | None = None
    weekly_window_start: datetime | None = None
    window_timezone: str = "UTC"
    peak_equity: float = Field(default=0.0, ge=0)
    current_equity: float = Field(default=0.0, ge=0)
    adaptive_multiplier: float = Field(default=1.0, ge=0)
    daily_loss_percent: float = Field(default=0.0, ge=0)
    weekly_loss_percent: float = Field(default=0.0, ge=0)
    account_drawdown_percent: float = Field(default=0.0, ge=0)
    max_account_drawdown_percent: float = Field(default=0.0, ge=0)
    open_risk_amount: float = Field(default=0.0, ge=0)
    open_risk_percent: float = Field(default=0.0, ge=0)
    max_open_risk_percent: float = Field(default=0.0, ge=0)
    correlated_risk_amount: float = Field(default=0.0, ge=0)
    correlated_risk_percent: float = Field(default=0.0, ge=0)
    max_correlated_risk_percent: float = Field(default=0.0, ge=0)
    correlation_group: str | None = None
    exchange_rule_status: ExchangeRuleStatus = "unknown"
    exchange_rule_age_seconds: float | None = Field(default=None, ge=0)
    exchange_rule_ttl_seconds: int | None = Field(default=None, ge=0)


class RiskPreviewResponse(BaseModel):
    decision: RiskDecision
    state: RiskStateResponse
    risk_decision_id: str | None = None
