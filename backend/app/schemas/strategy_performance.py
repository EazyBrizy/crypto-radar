from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ScoreBucket = Literal["0-49", "50-59", "60-69", "70-79", "80-89", "90-100"]
EdgeProfileConfidence = Literal["high", "medium", "low", "insufficient_sample"]
EdgeProfileSource = Literal["exact", "strategy_timeframe_regime", "strategy_global", "none"]


class StrategyPerformanceDaily(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    exchange: str
    symbol: str
    timeframe: str
    strategy: str
    strategy_version: str
    market_regime: str
    score_bucket: ScoreBucket
    direction: Literal["long", "short"]

    sample_size: int = Field(ge=0)
    trades_count: int = Field(ge=0)
    signals_count: int = Field(ge=0)
    wins_count: int = Field(ge=0)
    losses_count: int = Field(ge=0)
    entry_touch_rate: float = Field(ge=0)
    winrate: float = Field(ge=0)
    tp1_rate: float = Field(ge=0)
    tp2_rate: float = Field(ge=0)
    stop_rate: float = Field(ge=0)
    invalidation_rate: float = Field(ge=0)
    avg_win_r: float
    avg_loss_r: float
    expectancy_r: float
    profit_factor: float | None = None
    max_drawdown_r: float = Field(ge=0)
    median_bars_to_entry: float | None = None
    median_bars_to_outcome: float | None = None
    avg_mfe_r: float
    avg_mae_r: float
    fees_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    updated_at: datetime | None = None


class StrategyEdgeProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    strategy: str
    exchange: str
    symbol: str
    timeframe: str
    market_regime: str | None = None
    score_bucket: ScoreBucket | None = None
    source: EdgeProfileSource
    confidence: EdgeProfileConfidence

    sample_size: int = Field(ge=0)
    trades_count: int = Field(ge=0)
    signals_count: int = Field(ge=0)
    wins_count: int = Field(ge=0)
    losses_count: int = Field(ge=0)
    entry_touch_rate: float = Field(ge=0)
    winrate: float = Field(ge=0)
    tp1_rate: float = Field(ge=0)
    tp2_rate: float = Field(ge=0)
    stop_rate: float = Field(ge=0)
    invalidation_rate: float = Field(ge=0)
    avg_win_r: float
    avg_loss_r: float
    expectancy_r: float
    profit_factor: float | None = None
    max_drawdown_r: float = Field(ge=0)
    median_bars_to_entry: float | None = None
    median_bars_to_outcome: float | None = None
    avg_mfe_r: float
    avg_mae_r: float
    fees_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
