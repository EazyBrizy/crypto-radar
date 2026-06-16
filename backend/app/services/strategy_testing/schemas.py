from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


StrategyTestMode = Literal["discovery", "research_virtual", "production_like"]
StrategyTestType = Literal["historical_backtest", "forward_virtual"]
StrategyTestRunStatus = Literal["queued", "running", "completed", "failed", "cancelled", "stopping"]
StrategyTestScenarioStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
StrategyTestCalibrationDecision = Literal["positive", "negative", "insufficient_sample"]
StrategyTestEstimateLevel = Literal["small", "medium", "large"]
StrategyTestEstimateWarningCode = Literal[
    "estimating_failed",
    "market_data_missing",
    "market_data_duplicates",
    "market_data_below_warmup",
]
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
    test_type: StrategyTestType = "historical_backtest"
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
    test_type: StrategyTestType = "historical_backtest"
    requested_matrix: dict[str, Any]
    summary: dict[str, Any] = Field(default_factory=dict)
    runtime_state: dict[str, Any] | StrategyTestRuntimeState = Field(default_factory=dict)
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    error: str | None = None


class StrategyTestRunDetailResponse(BaseModel):
    run: StrategyTestRunResponse
    trades_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    rejections: list[str] = Field(default_factory=list)


class StrategyTestScenarioCheckpoint(BaseModel):
    id: UUID | None = None
    run_id: UUID
    scenario_key: str
    scenario_index: int = Field(ge=0)
    strategy_code: str
    exchange: str
    symbol: str
    timeframe: str
    status: StrategyTestScenarioStatus
    bars_total: int = Field(default=0, ge=0)
    bars_processed: int = Field(default=0, ge=0)
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    result_written_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StrategyTestRuntimeCounters(BaseModel):
    signals: int = Field(default=0, ge=0)
    execution_candidates: int = Field(default=0, ge=0)
    pending_armed: int = Field(default=0, ge=0)
    pending_entries: int = Field(default=0, ge=0)
    no_entry: int = Field(default=0, ge=0)
    filled: int = Field(default=0, ge=0)
    closed: int = Field(default=0, ge=0)
    risk_rejections: int = Field(default=0, ge=0)
    execution_rejections: int = Field(default=0, ge=0)


class StrategyTestRuntimeState(BaseModel):
    model_config = ConfigDict(extra="allow")

    scenarios_total: int = Field(default=0, ge=0)
    scenarios_completed: int = Field(default=0, ge=0)
    scenarios_failed: int = Field(default=0, ge=0)
    current_scenario_index: int | None = Field(default=None, ge=0)
    current_scenario_key: str | None = None
    current_scenario_bars_processed: int = Field(default=0, ge=0)
    current_scenario_bars_total: int | None = Field(default=None, ge=0)
    matrix_bars_processed: int = Field(default=0, ge=0)
    matrix_bars_total: int | None = Field(default=None, ge=0)
    bars_pct: float = Field(default=0.0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0)
    bars_per_second: float = Field(default=0.0, ge=0)
    eta_seconds: float | None = Field(default=None, ge=0)
    phase: str = "queued"
    last_progress_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    stale_threshold_seconds: int = Field(default=0, ge=0)
    counters: StrategyTestRuntimeCounters = Field(default_factory=StrategyTestRuntimeCounters)

    @field_validator("bars_pct", "elapsed_seconds", "bars_per_second", mode="before")
    @classmethod
    def sanitize_non_negative_float(cls, value: Any) -> float:
        return _non_negative_finite_float(value, default=0.0)

    @field_validator("eta_seconds", mode="before")
    @classmethod
    def sanitize_optional_non_negative_float(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _non_negative_finite_float(value, default=0.0)


class StrategyTestFunnelResponse(BaseModel):
    run_id: UUID
    signals_count: int = 0
    execution_candidates: int = 0
    entry_touched: int = 0
    filled: int = 0
    closed: int = 0
    wins: int = 0
    losses: int = 0
    no_entry: int = 0
    risk_rejected: int = 0
    execution_rejected: int = 0
    entry_touch_rate: float | None = None
    no_entry_rate: float | None = None
    risk_rejection_rate: float | None = None
    execution_rejection_rate: float | None = None
    false_signal_rate: float | None = None
    stages: list[dict[str, Any]] = Field(default_factory=list)


class StrategyTestSignalEventsSummary(BaseModel):
    run_id: UUID
    signals_count: int = Field(default=0, ge=0)
    execution_candidates: int = Field(default=0, ge=0)
    entry_touched: int = Field(default=0, ge=0)
    filled: int = Field(default=0, ge=0)
    closed: int = Field(default=0, ge=0)
    wins: int = Field(default=0, ge=0)
    losses: int = Field(default=0, ge=0)
    no_entry: int = Field(default=0, ge=0)
    risk_rejected: int = Field(default=0, ge=0)
    execution_rejected: int = Field(default=0, ge=0)
    false_signals: int = Field(default=0, ge=0)
    groups: list[dict[str, Any]] = Field(default_factory=list)


class StrategyTestTradesSummary(BaseModel):
    run_id: UUID
    trades_count: int = Field(default=0, ge=0)
    executed_trades_count: int = Field(default=0, ge=0)
    wins: int = Field(default=0, ge=0)
    losses: int = Field(default=0, ge=0)
    risk_rejected: int = Field(default=0, ge=0)
    execution_rejected: int = Field(default=0, ge=0)
    realized_r_sum: float = 0.0
    realized_r_count: int = Field(default=0, ge=0)
    pnl_total: float = 0.0
    fees_total: float = 0.0
    slippage_total: float = 0.0
    groups: list[dict[str, Any]] = Field(default_factory=list)


class StrategyTestActiveRunResponse(BaseModel):
    active_run: StrategyTestRunResponse | None = None
    can_run: bool
    disabled_reason_code: str | None = None
    disabled_reason: str | None = None
    is_stale: bool = False
    stale_threshold_seconds: int
    allowed_actions: list[str] = Field(default_factory=list)


class StrategyTestEstimateWarning(BaseModel):
    code: StrategyTestEstimateWarningCode
    message: str
    exchange: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    raw_rows: int | None = Field(default=None, ge=0)
    deduped_candles: int | None = Field(default=None, ge=0)
    duplicate_ratio: float | None = Field(default=None, ge=0)


class StrategyTestScenarioEstimate(BaseModel):
    strategy: str
    exchange: str
    symbol: str
    timeframe: str
    candles_count: int = Field(ge=0)
    raw_rows: int = Field(ge=0)
    duplicate_rows: int = Field(ge=0)
    warmup_bars: int = Field(ge=0)
    bars_total: int = Field(ge=0)
    warning_codes: list[StrategyTestEstimateWarningCode] = Field(default_factory=list)


class StrategyTestEstimateResponse(BaseModel):
    scenario_count: int = Field(ge=0)
    total_bars: int = Field(ge=0)
    average_bars_per_scenario: int | None = Field(default=None, ge=0)
    size_level: StrategyTestEstimateLevel
    scenarios: list[StrategyTestScenarioEstimate] = Field(default_factory=list)
    warnings: list[StrategyTestEstimateWarning] = Field(default_factory=list)


class StrategyTestCalibrationProfile(BaseModel):
    strategy_code: str
    exchange: str
    symbol_scope: str
    timeframe: str
    market_regime: str
    score_bucket: str
    direction: str
    decision: StrategyTestCalibrationDecision
    eligible: bool
    source: str
    source_run_id: UUID | None = None
    sample_size: int = Field(ge=0)
    expectancy_after_costs_r: float | None = None
    profit_factor: float | None = None
    entry_touch_rate: float | None = None
    no_entry_rate: float | None = None
    max_drawdown_r: float | None = None
    run_ids: list[str] = Field(default_factory=list)
    reason_code: str
    reason: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class StrategyTestCalibrationResponse(BaseModel):
    run_id: UUID
    decision: StrategyTestCalibrationDecision
    profiles_count: int = Field(ge=0)
    profiles: list[StrategyTestCalibrationProfile] = Field(default_factory=list)
    reason: str
    generated_at: datetime


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


class StrategyTestSignalEvent(BaseModel):
    run_id: UUID
    user_id: UUID
    mode: StrategyTestMode
    test_type: StrategyTestType = "historical_backtest"
    strategy_code: str
    strategy_version: str
    exchange: str
    symbol: str
    timeframe: str
    direction: str
    signal_id: str | None = None
    synthetic_signal_id: str
    signal_key: str
    event_time: datetime
    candle_time: datetime
    signal_score: float | None = None
    market_regime: str = "unknown"
    score_bucket: str = "unknown"
    status: str
    gate_status: str = "unknown"
    feed_kind: str = "unknown"
    trigger_passed: bool = False
    trigger_reason_code: str | None = None
    execution_candidate: bool = False
    entry_touched: bool = False
    filled: bool = False
    closed: bool = False
    outcome: str | None = None
    funnel_stage: str = "signal"
    risk_rejected: bool = False
    execution_rejected: bool = False
    no_entry: bool = False
    rejection_reason_code: str | None = None
    blocked_reason_code: str | None = None
    selected_rr: float | None = None
    entry_min: Decimal | None = None
    entry_max: Decimal | None = None
    stop_loss: Decimal | None = None
    features_snapshot: dict[str, Any] = Field(default_factory=dict)
    trade_plan: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("signal_id", "synthetic_signal_id", "signal_key", mode="before")
    @classmethod
    def stringify_signal_identifiers(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)


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


def _non_negative_finite_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, parsed)
