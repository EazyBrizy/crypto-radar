from datetime import datetime
from typing import Any
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic import model_validator

from app.schemas.risk import (
    StopLossMode,
    TakeProfitMode,
    TrailingMode,
    VirtualFeeModel,
    VirtualRiskMode,
    VirtualSlippageModel,
)

VirtualSimulationLevel = Literal["mvp", "advanced", "pro"]
RiskProfileName = Literal["conservative", "balanced", "aggressive", "custom"]


DEFAULT_STRATEGY_RISK_MULTIPLIERS: dict[str, float] = {
    "trend_pullback_continuation": 1.0,
    "volatility_squeeze_breakout": 0.75,
    "liquidity_sweep_reversal": 1.0,
    "trend_following": 1.0,
    "breakout": 0.75,
    "smart_money_setup": 1.0,
    "scalping": 0.5,
    "mean_reversion": 0.75,
    "news_event_trade": 0.25,
}


class RiskManagementSettings(BaseModel):
    risk_profile: RiskProfileName = "balanced"
    risk_per_trade_percent: float = Field(default=1.0, gt=0, le=10)
    min_rr_ratio: float = Field(default=2.0, ge=0, le=10)
    max_daily_loss_percent: float = Field(default=3.0, ge=0, le=50)
    max_weekly_loss_percent: float = Field(default=7.0, ge=0, le=80)
    max_account_drawdown_percent: float = Field(default=10.0, ge=0, le=90)
    max_open_risk_percent: float = Field(default=5.0, ge=0, le=100)
    max_correlated_risk_percent: float = Field(default=3.0, ge=0, le=100)
    max_spread_bps: float = Field(default=50.0, ge=0, le=10_000)
    max_slippage_bps: float = Field(default=150.0, ge=0, le=10_000)
    max_price_deviation_bps: float = Field(default=100.0, ge=0, le=10_000)
    max_orderbook_liquidity_ratio: float = Field(default=1.0, ge=0, le=100)
    include_fees_in_risk: bool = True
    include_slippage_in_risk: bool = True
    stop_loss_required: bool = True
    take_profit_required: bool = True
    stop_loss_mode: StopLossMode = "fixed_percent"
    default_stop_loss_percent: float = Field(default=1.5, gt=0, le=50)
    atr_period: int = Field(default=14, ge=2, le=200)
    atr_multiplier: float = Field(default=2.0, gt=0, le=10)
    take_profit_mode: TakeProfitMode = "risk_multiple"
    tp1_r_multiple: float = Field(default=1.0, gt=0, le=20)
    tp2_r_multiple: float = Field(default=2.0, gt=0, le=20)
    tp3_r_multiple: float = Field(default=3.0, gt=0, le=20)
    partial_take_profit_enabled: bool = True
    tp1_close_percent: float = Field(default=30.0, ge=0, le=100)
    tp2_close_percent: float = Field(default=40.0, ge=0, le=100)
    tp3_close_percent: float = Field(default=30.0, ge=0, le=100)
    move_sl_to_breakeven_after_r: float = Field(default=1.0, gt=0, le=20)
    breakeven_offset_percent: float = Field(default=0.05, ge=0, le=5)
    trailing_stop_enabled: bool = True
    trailing_mode: TrailingMode = "atr"
    trailing_atr_multiplier: float = Field(default=1.5, gt=0, le=10)
    trailing_stop_percent: float = Field(default=0.5, gt=0, le=50)
    max_leverage: int = Field(default=3, ge=1, le=125)
    min_liquidation_buffer_percent: float = Field(default=2.0, ge=0, le=100)
    liquidation_buffer_required: bool = True
    spot_risk_per_trade_percent: float = Field(default=1.0, gt=0, le=10)
    spot_max_position_size_percent: float = Field(default=20.0, ge=0, le=100)
    spot_stop_required: bool = True
    futures_risk_per_trade_percent: float = Field(default=0.5, gt=0, le=10)
    futures_max_leverage: int = Field(default=3, ge=1, le=125)
    futures_max_open_risk_percent: float = Field(default=3.0, ge=0, le=100)
    futures_liquidation_buffer_required: bool = True
    virtual_risk_mode: VirtualRiskMode = "same_as_real"
    virtual_risk_per_trade_percent: float = Field(default=1.0, gt=0, le=10)
    virtual_starting_balance: float = Field(default=10_000.0, gt=0)
    virtual_slippage_model: VirtualSlippageModel = "spread_based"
    virtual_fee_model: VirtualFeeModel = "exchange_based"
    virtual_trading_uses_realistic_execution: bool = True
    real_requires_fresh_market_data: bool = True
    real_requires_positive_edge: bool = True
    edge_min_sample_size: int = Field(default=50, ge=0, le=100_000)
    min_expectancy_after_costs_r: float = Field(default=0.05, ge=-100, le=100)
    strategy_risk_multipliers: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_STRATEGY_RISK_MULTIPLIERS)
    )
    auto_reduce_risk_after_losses: bool = True
    allow_risk_increase_after_profit: bool = False
    increase_risk_after_profit_streak: bool = False
    max_risk_boost: float = Field(default=1.25, ge=1, le=5)

    @model_validator(mode="after")
    def validate_exit_plan(self) -> "RiskManagementSettings":
        if not (self.tp1_r_multiple <= self.tp2_r_multiple <= self.tp3_r_multiple):
            raise ValueError("take-profit R multiples must be ordered from TP1 to TP3")
        if self.partial_take_profit_enabled:
            total_close = self.tp1_close_percent + self.tp2_close_percent + self.tp3_close_percent
            if abs(total_close - 100.0) > 0.000001:
                raise ValueError("partial take-profit close percents must sum to 100")
        return self


class RiskManagementPatch(BaseModel):
    risk_profile: RiskProfileName | None = None
    risk_per_trade_percent: float | None = Field(default=None, gt=0, le=10)
    min_rr_ratio: float | None = Field(default=None, ge=0, le=10)
    max_daily_loss_percent: float | None = Field(default=None, ge=0, le=50)
    max_weekly_loss_percent: float | None = Field(default=None, ge=0, le=80)
    max_account_drawdown_percent: float | None = Field(default=None, ge=0, le=90)
    max_open_risk_percent: float | None = Field(default=None, ge=0, le=100)
    max_correlated_risk_percent: float | None = Field(default=None, ge=0, le=100)
    max_spread_bps: float | None = Field(default=None, ge=0, le=10_000)
    max_slippage_bps: float | None = Field(default=None, ge=0, le=10_000)
    max_price_deviation_bps: float | None = Field(default=None, ge=0, le=10_000)
    max_orderbook_liquidity_ratio: float | None = Field(default=None, ge=0, le=100)
    stop_loss_required: bool | None = None
    take_profit_required: bool | None = None
    stop_loss_mode: StopLossMode | None = None
    default_stop_loss_percent: float | None = Field(default=None, gt=0, le=50)
    atr_period: int | None = Field(default=None, ge=2, le=200)
    atr_multiplier: float | None = Field(default=None, gt=0, le=10)
    take_profit_mode: TakeProfitMode | None = None
    tp1_r_multiple: float | None = Field(default=None, gt=0, le=20)
    tp2_r_multiple: float | None = Field(default=None, gt=0, le=20)
    tp3_r_multiple: float | None = Field(default=None, gt=0, le=20)
    partial_take_profit_enabled: bool | None = None
    tp1_close_percent: float | None = Field(default=None, ge=0, le=100)
    tp2_close_percent: float | None = Field(default=None, ge=0, le=100)
    tp3_close_percent: float | None = Field(default=None, ge=0, le=100)
    move_sl_to_breakeven_after_r: float | None = Field(default=None, gt=0, le=20)
    breakeven_offset_percent: float | None = Field(default=None, ge=0, le=5)
    trailing_stop_enabled: bool | None = None
    trailing_mode: TrailingMode | None = None
    trailing_atr_multiplier: float | None = Field(default=None, gt=0, le=10)
    trailing_stop_percent: float | None = Field(default=None, gt=0, le=50)
    max_leverage: int | None = Field(default=None, ge=1, le=125)
    min_liquidation_buffer_percent: float | None = Field(default=None, ge=0, le=100)
    liquidation_buffer_required: bool | None = None
    spot_risk_per_trade_percent: float | None = Field(default=None, gt=0, le=10)
    spot_max_position_size_percent: float | None = Field(default=None, ge=0, le=100)
    spot_stop_required: bool | None = None
    futures_risk_per_trade_percent: float | None = Field(default=None, gt=0, le=10)
    futures_max_leverage: int | None = Field(default=None, ge=1, le=125)
    futures_max_open_risk_percent: float | None = Field(default=None, ge=0, le=100)
    futures_liquidation_buffer_required: bool | None = None
    virtual_risk_mode: VirtualRiskMode | None = None
    virtual_risk_per_trade_percent: float | None = Field(default=None, gt=0, le=10)
    virtual_starting_balance: float | None = Field(default=None, gt=0)
    virtual_slippage_model: VirtualSlippageModel | None = None
    virtual_fee_model: VirtualFeeModel | None = None
    virtual_trading_uses_realistic_execution: bool | None = None
    real_requires_fresh_market_data: bool | None = None
    real_requires_positive_edge: bool | None = None
    edge_min_sample_size: int | None = Field(default=None, ge=0, le=100_000)
    min_expectancy_after_costs_r: float | None = Field(default=None, ge=-100, le=100)
    strategy_risk_multipliers: dict[str, float] | None = None
    auto_reduce_risk_after_losses: bool | None = None
    allow_risk_increase_after_profit: bool | None = None
    increase_risk_after_profit_streak: bool | None = None
    max_risk_boost: float | None = Field(default=None, ge=1, le=5)


class UserProfileResponse(BaseModel):
    id: UUID
    email: str
    username: str | None
    name: str | None
    display_name: str | None
    avatar_url: str | None
    status: str
    locale: str
    timezone: str
    risk_profile: str | None
    onboarding_done: bool
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class UserSettingsPatchRequest(BaseModel):
    virtual_simulation_level: VirtualSimulationLevel | None = None
    risk_profile: RiskProfileName | None = None
    risk_management: RiskManagementPatch | None = None
