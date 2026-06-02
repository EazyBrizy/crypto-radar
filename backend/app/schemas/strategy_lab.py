from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


StrategyLabMode = Literal["baseline", "experiment"]
StrategyLabRunStatus = Literal["completed", "no_data", "insufficient_data", "failed"]


class _StrategyLabRequestBase(BaseModel):
    user_id: str = "demo_user"
    exchange: str = "bybit"
    strategies: list[str]
    symbols: list[str]
    timeframes: list[str]
    start_time: datetime
    end_time: datetime
    initial_equity: Decimal = Field(default=Decimal("1000"), gt=0)
    fees_bps: Decimal = Field(default=Decimal("10"), ge=0)
    slippage_bps: Decimal = Field(default=Decimal("0"), ge=0)
    max_bars_in_trade: int | None = Field(default=None, ge=1)
    warmup_bars: int = Field(default=200, ge=1)
    mode: StrategyLabMode
    label: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    strategy_version: str | None = None

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("exchange must be non-empty")
        return normalized

    @field_validator("strategies", "timeframes")
    @classmethod
    def normalize_unique_values(cls, value: list[str]) -> list[str]:
        return _normalize_unique_strings(value)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return _normalize_unique_strings([item.upper() for item in value])

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, item in value.items():
            tag_key = str(key).strip()
            tag_value = str(item).strip()
            if not tag_key or not tag_value:
                raise ValueError("tags must contain non-empty string keys and values")
            normalized[tag_key] = tag_value
        return normalized

    @model_validator(mode="after")
    def validate_period(self) -> "_StrategyLabRequestBase":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self


class StrategyLabRunRequest(_StrategyLabRequestBase):
    @model_validator(mode="after")
    def validate_single_scenario(self) -> "StrategyLabRunRequest":
        if len(self.strategies) != 1 or len(self.symbols) != 1 or len(self.timeframes) != 1:
            raise ValueError("/strategy-lab/run expects exactly one strategy, symbol, and timeframe")
        return self


class StrategyLabMatrixRequest(_StrategyLabRequestBase):
    pass


class StrategyLabRunSummary(BaseModel):
    status: StrategyLabRunStatus
    total_trades: int | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    expectancy_r: float | None = None
    avg_r: float | None = None
    max_drawdown: float | None = None
    avg_bars_in_trade: float | None = None
    stop_rate: float | None = None
    tp1_rate: float | None = None
    final_target_rate: float | None = None
    fees_paid: Decimal | None = None
    slippage_paid: Decimal | None = None
    risk_rejections: int | None = None
    execution_rejections: int | None = None
    fallback_used_count: int | None = None
    incomplete_trade_plan_count: int | None = None
    signals_seen: int | None = None


class StrategyLabRunItem(BaseModel):
    lab_run_id: UUID
    scenario_id: str
    status: StrategyLabRunStatus
    strategy: str
    exchange: str
    symbol: str
    timeframe: str
    mode: StrategyLabMode
    label: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    summary: StrategyLabRunSummary
    metrics: dict[str, Any] = Field(default_factory=dict)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    backtest_run_id: UUID | None = None
    error: str | None = None
    created_at: datetime


class StrategyLabComparisonResult(BaseModel):
    lab_run_id: UUID
    mode: StrategyLabMode
    label: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    scenario_count: int
    completed_runs: int
    no_data_runs: int
    insufficient_data_runs: int
    failed_runs: int
    overall_summary: StrategyLabRunSummary
    metrics_by_strategy: dict[str, StrategyLabRunSummary] = Field(default_factory=dict)
    metrics_by_symbol: dict[str, StrategyLabRunSummary] = Field(default_factory=dict)
    metrics_by_timeframe: dict[str, StrategyLabRunSummary] = Field(default_factory=dict)
    runs: list[StrategyLabRunItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _normalize_unique_strings(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not item:
            raise ValueError("matrix values must be non-empty")
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    if not normalized:
        raise ValueError("matrix values must be non-empty")
    return normalized
