from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


StrategyTestMode = Literal["discovery", "research_virtual", "production_like"]
StrategyTestRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
StrategyTestSameCandlePolicy = Literal[
    "conservative_stop_first",
    "target_first",
    "intrabar_unknown",
    "stop_first",
    "ignore_ambiguous",
]
StrategyTestSignalSelectionPolicy = Literal[
    "first_actionable",
    "highest_score",
    "all_non_overlapping",
    "all_signals",
]


class StrategyTestPair(BaseModel):
    exchange: str
    symbol: str

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("exchange must be non-empty")
        return normalized

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol must be non-empty")
        return normalized


class StrategyTestRunRequest(BaseModel):
    user_id: str = "demo_user"
    strategies: list[str]
    pairs: list[StrategyTestPair]
    timeframes: list[str]
    start_at: datetime
    end_at: datetime
    mode: StrategyTestMode = "research_virtual"
    initial_capital: Decimal = Field(default=Decimal("1000"), gt=0)
    fee_rate: Decimal = Field(default=Decimal("0.001"), ge=0)
    slippage_bps: Decimal = Field(default=Decimal("0"), ge=0)
    same_candle_policy: StrategyTestSameCandlePolicy = "conservative_stop_first"
    params: dict[str, Any] = Field(default_factory=dict)
    metric_set: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=lambda: ["backtest"])

    @field_validator("strategies")
    @classmethod
    def normalize_strategies(cls, value: list[str]) -> list[str]:
        return _normalize_unique_strings(value, field_name="strategies")

    @field_validator("timeframes")
    @classmethod
    def normalize_timeframes(cls, value: list[str]) -> list[str]:
        return _normalize_unique_strings(value, field_name="timeframes")

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        tags = _normalize_unique_strings(value, field_name="tags", allow_empty_list=True)
        if "backtest" not in tags:
            tags.append("backtest")
        return tags

    @field_validator("metric_set")
    @classmethod
    def normalize_metric_set(cls, value: list[str]) -> list[str]:
        return _normalize_unique_strings(value, field_name="metric_set", allow_empty_list=True)

    @model_validator(mode="after")
    def validate_matrix(self) -> "StrategyTestRunRequest":
        if not self.pairs:
            raise ValueError("pairs must be non-empty")
        self.pairs = _dedupe_pairs(self.pairs)
        if self.end_at <= self.start_at:
            raise ValueError("start_at must be before end_at")
        return self


class StrategyTestRunResponse(BaseModel):
    run_id: UUID
    status: StrategyTestRunStatus
    requested_matrix: dict[str, Any]
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class StrategyTestRunDetailResponse(BaseModel):
    run: StrategyTestRunResponse
    trades_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    rejections: list[str] = Field(default_factory=list)


class StrategyTestRunListResponse(BaseModel):
    runs: list[StrategyTestRunResponse] = Field(default_factory=list)
    total: int = 0


class StrategyTestTrade(BaseModel):
    run_id: UUID
    trade_id: str
    user_id: UUID
    mode: StrategyTestMode
    strategy_code: str
    strategy_version: str
    exchange: str
    symbol: str
    timeframe: str
    direction: str
    signal_score: float | None = None
    market_regime: str
    score_bucket: str
    entry_time: datetime
    exit_time: datetime | None = None
    entry_price: Decimal
    exit_price: Decimal | None = None
    stop_loss: Decimal | None = None
    targets: list[dict[str, Any]] = Field(default_factory=list)
    selected_rr: float | None = None
    realized_r: float | None = None
    pnl: Decimal
    pnl_pct: float
    fees: Decimal
    slippage: Decimal
    mfe_r: float | None = None
    mae_r: float | None = None
    bars_to_entry: int | None = Field(default=None, ge=0)
    bars_in_trade: int | None = Field(default=None, ge=0)
    close_reason: str
    outcome: str
    risk_rejected: bool = False
    execution_rejected: bool = False
    warnings: list[str] = Field(default_factory=list)
    features_snapshot: dict[str, Any] = Field(default_factory=dict)
    trade_plan: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("trade_id", mode="before")
    @classmethod
    def stringify_trade_id(cls, value: Any) -> str:
        return str(value)


class StrategyTestSignal(BaseModel):
    run_id: UUID
    user_id: UUID
    mode: StrategyTestMode
    scenario_id: str
    strategy_code: str
    strategy_version: str
    exchange: str
    symbol: str
    timeframe: str
    direction: str
    signal_id: str
    signal_time: datetime
    signal_score: float | None = None
    feed_kind: str
    gate_status: str
    status: str
    trigger_passed: bool = False
    edge_status: str
    selected_rr: float | None = None
    entry_min: Decimal | None = None
    entry_max: Decimal | None = None
    stop_loss: Decimal | None = None
    target_1: Decimal | None = None
    outcome: str
    outcome_reason: str
    entry_touched: bool = False
    filled: bool = False
    risk_rejected: bool = False
    execution_rejected: bool = False
    no_entry: bool = False
    bars_to_entry: int | None = Field(default=None, ge=0)
    bars_to_outcome: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("scenario_id", "strategy_code", "exchange", "symbol", "timeframe", "direction", "signal_id")
    @classmethod
    def normalize_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("strategy test signal text fields must be non-empty")
        return text


class StrategyTestMetricRow(BaseModel):
    run_id: UUID
    user_id: UUID
    mode: StrategyTestMode
    strategy_code: str
    exchange: str
    symbol: str
    timeframe: str
    market_regime: str
    score_bucket: str
    direction: str
    metric_code: str
    metric_value: float | None = None
    sample_size: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class StrategyTestMetric(BaseModel):
    run_id: str
    scenario_id: str | None = None
    name: str
    value: int | float | str | bool | None = None
    unit: str | None = None
    group: dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["high", "medium", "low", "insufficient_sample"] = "high"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyTestReportSection(BaseModel):
    code: str
    name: str
    summary: dict[str, Any] = Field(default_factory=dict)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyTestCandidateAdjustment(BaseModel):
    strategy_code: str
    scope: str
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_change: str
    confidence: Literal["low", "medium", "high"] = "low"


class StrategyTestReport(BaseModel):
    run_id: UUID
    status: StrategyTestRunStatus
    mode: StrategyTestMode
    requested_matrix: dict[str, Any] = Field(default_factory=dict)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    sections: list[StrategyTestReportSection] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    candidate_adjustments: list[StrategyTestCandidateAdjustment] = Field(default_factory=list)
    generated_at: datetime
    summary_metrics: list[dict[str, Any]] = Field(default_factory=list)
    grouped_metrics: list[dict[str, Any]] = Field(default_factory=list)
    trades_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    rejections: list[str] = Field(default_factory=list)


class StrategyTestTradeResponse(BaseModel):
    run_id: UUID
    trade_id: UUID
    exchange: str
    symbol: str
    timeframe: str
    strategy_code: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyTestReportResponse(BaseModel):
    run_id: UUID
    status: StrategyTestRunStatus | None = None
    mode: StrategyTestMode | None = None
    requested_matrix: dict[str, Any] = Field(default_factory=dict)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    sections: list[StrategyTestReportSection] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    candidate_adjustments: list[StrategyTestCandidateAdjustment] = Field(default_factory=list)
    generated_at: datetime | None = None
    summary_metrics: list[dict[str, Any]] = Field(default_factory=list)
    grouped_metrics: list[dict[str, Any]] = Field(default_factory=list)
    trades_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    rejections: list[str] = Field(default_factory=list)


def _normalize_unique_strings(
    values: list[str],
    *,
    field_name: str,
    allow_empty_list: bool = False,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not item:
            raise ValueError(f"{field_name} must contain non-empty values")
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    if not normalized and not allow_empty_list:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _dedupe_pairs(pairs: list[StrategyTestPair]) -> list[StrategyTestPair]:
    normalized: list[StrategyTestPair] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        key = (pair.exchange, pair.symbol)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(pair)
    return normalized
