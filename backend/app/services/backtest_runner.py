from __future__ import annotations

import asyncio
import math
import time
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping, MutableMapping, Sequence, TypeVar
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from app.domain.signal_status import is_execution_candidate_status, is_waiting_entry_status
from app.domain.virtual_trade_status import is_terminal_virtual_trade_status
from app.schemas.backtest import BacktestResultResponse, BacktestRunRequest, BacktestRunResult
from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features
from app.schemas.risk import RiskDecision
from app.schemas.signal import RadarSignal, StrategySignal
from app.schemas.trade_plan import TradePlan
from app.schemas.trade import ManualConfirmRequest, VirtualAccount, VirtualExecutionReport, VirtualTrade
from app.schemas.user import RiskManagementSettings
from app.services.execution_ambiguity import normalize_virtual_execution_ambiguity_policy
from app.services.execution_policy import ExecutionPolicyContext, execution_policy_resolver
from app.services.feature_engine import FeatureEngine
from app.services.historical_candle_provider import BackfillingHistoricalCandleProvider, HistoricalCandleProvider
from app.services.market_context import MarketContextService, MarketContextSnapshot
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.trade_plan_completeness import trade_plan_completeness_service
from app.services.trade_plan_enrichment import TradePlanEnrichmentService
from app.services.virtual_trade_lifecycle import (
    arm_virtual_trade_time_stop,
    initialize_virtual_trade_lifecycle,
)
from app.services.position_management import position_management_engine
from app.services.virtual_trading.execution_engine import VirtualExecutionEngine
from app.strategies.engine import StrategyEngine
from app.strategies.pipeline import (
    ExitManagementLayer,
    InvalidationLayer,
    StrategyEvaluationContext,
    StrategySignalPipeline,
    _enrich_trade_plan_with_final_risk_reward,
)

DEFAULT_WARMUP_CANDLES = 200
DEFAULT_ROLLING_WINDOW_CANDLES = 200
MIN_REQUIRED_CANDLES = 2

_T = TypeVar("_T")

_RESERVED_PARAM_KEYS = {
    "warmup_candles",
    "rolling_window_candles",
    "leverage",
    "risk_settings",
    "strategy_params",
    "execution_policy",
    "size_usd",
    "simulation_mode",
    "funding_buffer_per_unit",
    "market_data_status",
    "spread_bps",
    "spread_percent",
    "orderbook_depth_usd",
    "max_virtual_slippage_bps",
    "same_candle_policy",
    "strategy_test_mode",
    "strategy_test_assumptions",
    "rr_hard_gate_enabled",
    "risk_gate_enabled",
    "virtual_execution_enabled",
    "lifecycle_enabled",
    "historical_pending_entries_enabled",
    "signal_selection_policy",
    "max_concurrent_positions",
    "max_positions_per_symbol",
    "cooldown_bars_after_close",
    "allow_opposite_signal_flip",
}

_SIGNAL_SELECTION_POLICIES = {
    "first_actionable",
    "highest_score",
    "all_non_overlapping",
    "all_signals",
}

_STRATEGY_ALIASES = {
    "trend_following": "trend_pullback_continuation",
    "trend_pullback": "trend_pullback_continuation",
    "trend_pullback_continuation": "trend_pullback_continuation",
    "breakout": "volatility_squeeze_breakout",
    "volatility_squeeze_breakout": "volatility_squeeze_breakout",
    "smart_money_setup": "liquidity_sweep_reversal",
    "liquidity_sweep": "liquidity_sweep_reversal",
    "liquidity_sweep_reversal": "liquidity_sweep_reversal",
}

_LIQUIDITY_SWEEP_THRESHOLD_PARAM_KEYS = {
    "min_absorption_score",
    "min_cvd_divergence_score",
    "min_target_distance_r",
}

_BREAKOUT_EXPERIMENT_PARAM_KEYS = {
    "allow_aggressive_entry",
    "require_retest_after_large_candle",
    "require_delta_expansion",
    "require_oi_expansion",
    "min_delta_expansion_score",
    "min_oi_expansion_score",
    "accepted_breakout_min_score",
    "fakeout_risk_max_score",
}

_TREND_PULLBACK_EXPERIMENT_PARAM_KEYS = {
    "require_structural_zone",
    "require_delta_confirmation",
    "max_exhaustion_score",
    "crowded_oi_penalty",
    "min_htf_target_distance_r",
}

_EXIT_POLICY_PARAM_KEYS = {
    "exit_policy",
    "target_sources_enabled",
    "partial_exit_policy",
    "allow_r_multiple_fallback",
}

_STOP_REASONS = {"stop_loss", "breakeven_stop", "trailing_stop"}


@dataclass(frozen=True)
class _StrategyRuntimeConfig:
    params: dict[str, Any] = field(default_factory=dict)
    risk_settings: dict[str, Any] = field(default_factory=dict)
    pair_scope_configured: bool = False


@dataclass(frozen=True)
class _SimulatedPosition:
    trade: VirtualTrade
    signal: RadarSignal
    entry_index: int
    reference_entry_price: float
    bars_to_entry: int = 0
    exit_index: int | None = None
    funding_buffer_per_unit: float = 0.0
    bars_in_trade: int = 0
    strategy: str = "unknown"
    regime: str = "unknown"
    features_snapshot: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _BacktestState:
    cash_equity: float
    open_positions: list[_SimulatedPosition] = field(default_factory=list)
    closed_positions: list[_SimulatedPosition] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    signals_seen: int = 0
    execution_candidates: int = 0
    pending_armed: int = 0
    entry_touched: int = 0
    filled: int = 0
    no_entry: int = 0
    not_selected: int = 0
    risk_rejections: int = 0
    execution_rejections: int = 0
    trade_plan_completion_warnings: list[str] = field(default_factory=list)
    risk_gate_blockers: list[str] = field(default_factory=list)
    execution_policy_no_entries: list[str] = field(default_factory=list)
    execution_policy_rejections: list[str] = field(default_factory=list)
    backtest_trade_plan_assumptions: list[str] = field(default_factory=list)
    signal_events: list[BacktestSignalEvent] = field(default_factory=list)

    @property
    def open_position(self) -> _SimulatedPosition | None:
        return self.open_positions[0] if self.open_positions else None

    @open_position.setter
    def open_position(self, position: _SimulatedPosition | None) -> None:
        self.open_positions = [] if position is None else [position]


@dataclass
class _BacktestTimingDiagnostics:
    candle_load_ms: float = 0.0
    feature_ms: float = 0.0
    strategy_ms: float = 0.0
    gate_ms: float = 0.0
    execution_ms: float = 0.0
    bars_total: int = 0
    total_ms: float = 0.0

    def summary(self) -> dict[str, Any]:
        elapsed_seconds = self.total_ms / 1000 if self.total_ms > 0 else 0.0
        bars_per_second = self.bars_total / elapsed_seconds if elapsed_seconds > 0 else 0.0
        return {
            "candle_load_ms": _round_ms(self.candle_load_ms),
            "feature_ms": _round_ms(self.feature_ms),
            "strategy_ms": _round_ms(self.strategy_ms),
            "gate_ms": _round_ms(self.gate_ms),
            "execution_ms": _round_ms(self.execution_ms),
            "total_ms": _round_ms(self.total_ms),
            "bars_total": self.bars_total,
            "bars_per_second": round(bars_per_second, 8),
        }


@dataclass(frozen=True)
class _PendingSignalEntry:
    signal: StrategySignal
    signal_event: BacktestSignalEvent
    features: Features
    signal_candle: OHLCVCandle
    armed_index: int
    max_wait_bars: int = 1
    wait_for_entry_zone: bool = False


@dataclass(frozen=True)
class _PositionConstraints:
    signal_selection_policy: str
    max_concurrent_positions: int = 1
    max_positions_per_symbol: int = 1
    cooldown_bars_after_close: int = 0
    allow_opposite_signal_flip: bool = False


@dataclass(frozen=True)
class BacktestExecutionPolicy:
    mode: str
    production_mode: bool
    virtual_execution_enabled: bool = True
    historical_pending_entries_enabled: bool = False
    preserve_legacy_backtest: bool = False
    entry_timing: str = "same_candle_close"


@dataclass(frozen=True)
class BacktestSimulatedTrade:
    trade_id: str
    strategy_code: str
    strategy_version: str
    exchange: str
    symbol: str
    timeframe: str
    direction: str
    signal_score: float | None
    market_regime: str
    score_bucket: str
    entry_time: datetime
    exit_time: datetime | None
    entry_price: Decimal
    exit_price: Decimal | None
    stop_loss: Decimal | None
    targets: list[dict[str, Any]]
    selected_rr: float | None
    realized_r: float | None
    pnl: Decimal
    pnl_pct: float
    fees: Decimal
    slippage: Decimal
    mfe_r: float | None
    mae_r: float | None
    bars_to_entry: int | None
    bars_in_trade: int | None
    close_reason: str
    outcome: str
    risk_rejected: bool
    execution_rejected: bool
    warnings: list[str]
    features_snapshot: dict[str, Any]
    trade_plan: dict[str, Any]
    tags: list[str]
    created_at: datetime


@dataclass(frozen=True)
class BacktestSignalEvent:
    strategy_code: str
    strategy_version: str
    exchange: str
    symbol: str
    timeframe: str
    direction: str
    signal_id: str | None
    synthetic_signal_id: str
    signal_key: str
    event_time: datetime
    candle_time: datetime
    signal_score: float | None
    market_regime: str
    score_bucket: str
    status: str
    gate_status: str
    feed_kind: str
    trigger_passed: bool
    trigger_reason_code: str | None
    execution_candidate: bool
    entry_touched: bool
    filled: bool
    closed: bool
    outcome: str | None
    funnel_stage: str
    risk_rejected: bool
    execution_rejected: bool
    no_entry: bool
    rejection_reason_code: str | None
    blocked_reason_code: str | None
    selected_rr: float | None
    entry_min: Decimal | None
    entry_max: Decimal | None
    stop_loss: Decimal | None
    features_snapshot: dict[str, Any]
    trade_plan: dict[str, Any]
    metadata: dict[str, Any]
    tags: list[str]
    created_at: datetime


@dataclass(frozen=True)
class BacktestDetailedRunResult:
    run_result: BacktestRunResult
    trades: list[BacktestSimulatedTrade]
    signals_seen: int
    risk_rejections: int
    execution_rejections: int
    assumptions: dict[str, Any]
    signal_events: list[BacktestSignalEvent] = field(default_factory=list)


class BacktestRunCancelled(Exception):
    """Raised when a backtest cancellation predicate becomes true."""


def _append_signal_event(state: _BacktestState, event: BacktestSignalEvent) -> None:
    state.signal_events.append(event)
    if event.filled:
        state.filled += 1
    if event.no_entry:
        state.no_entry += 1
    if event.blocked_reason_code == "not_selected":
        state.not_selected += 1


class BacktestExecutionSimulator:
    def __init__(self, execution_engine: VirtualExecutionEngine | None = None) -> None:
        self._execution_engine = execution_engine or VirtualExecutionEngine()

    def simulate_entry(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        risk_decision: RiskDecision,
        reference_price: float,
    ) -> VirtualExecutionReport:
        requested_size_usd = request.size_usd or risk_decision.position_sizing.notional
        execution = self._execution_engine.simulate_entry(
            signal=signal,
            request=request,
            reference_price=reference_price,
            requested_size_usd=requested_size_usd,
        )
        return _execution_with_risk_decision(execution, risk_decision)

    def apply_candle(self, position: _SimulatedPosition, candle: OHLCVCandle) -> _SimulatedPosition:
        trade = position.trade
        if trade.status != "open":
            return position

        now = _datetime_from_ms(candle.close_time)
        assumptions = position.features_snapshot.get("strategy_test_assumptions")
        policy = (
            assumptions.get("same_candle_policy")
            if isinstance(assumptions, Mapping)
            else None
        )
        result = position_management_engine.apply_candle(
            trade,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            now=now,
            ambiguity_policy=policy,
            candle_open_time=candle.open_time,
            candle_close_time=candle.close_time,
        )
        return _replace_position(
            position,
            trade=result.trade,
            bars_in_trade=position.bars_in_trade + 1,
        )

    def close_at_end(self, position: _SimulatedPosition, candle: OHLCVCandle) -> _SimulatedPosition:
        result = position_management_engine.close(
            position.trade,
            exit_price=candle.close,
            reason="time_stop",
            now=_datetime_from_ms(candle.close_time),
        )
        return _replace_position(position, trade=result.trade)


class ProductionBacktestRunner:
    def __init__(
        self,
        *,
        feature_engine: FeatureEngine | None = None,
        strategy_engine: StrategyEngine | None = None,
        signal_pipeline: StrategySignalPipeline | None = None,
        risk_context_service: RiskContextService | None = None,
        risk_gate_service: RiskGateService | None = None,
        historical_candle_provider: HistoricalCandleProvider | None = None,
        execution_simulator: BacktestExecutionSimulator | None = None,
        warmup_candles: int = DEFAULT_WARMUP_CANDLES,
        rolling_window_candles: int = DEFAULT_ROLLING_WINDOW_CANDLES,
    ) -> None:
        self._feature_engine = feature_engine or FeatureEngine()
        self._strategy_engine = strategy_engine or StrategyEngine()
        self._signal_pipeline = signal_pipeline or StrategySignalPipeline()
        self._risk_context_service = risk_context_service or RiskContextService()
        self._risk_gate_service = risk_gate_service or RiskGateService()
        self._historical_candle_provider = historical_candle_provider or BackfillingHistoricalCandleProvider()
        self._execution_simulator = execution_simulator or BacktestExecutionSimulator()
        self._warmup_candles = warmup_candles
        self._rolling_window_candles = rolling_window_candles

    def run(self, request: BacktestRunRequest) -> BacktestRunResult:
        return self.run_detailed(
            request,
            mode="production_like",
            options={"preserve_legacy_backtest": True},
        ).run_result

    def run_detailed(
        self,
        request: BacktestRunRequest,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        progress_interval_bars: int = 250,
        candle_cache: MutableMapping[str, list[OHLCVCandle]] | None = None,
        feature_cache: MutableMapping[str, list[Features | None]] | None = None,
    ) -> BacktestDetailedRunResult:
        return _run_awaitable_sync(
            self._run_detailed_async(
                request,
                mode=mode,
                options=options,
                is_cancelled=is_cancelled,
                on_progress=on_progress,
                progress_interval_bars=progress_interval_bars,
                candle_cache=candle_cache,
                feature_cache=feature_cache,
            )
        )

    def count_scenario_bars(
        self,
        request: BacktestRunRequest,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
    ) -> int:
        return _run_awaitable_sync(
            self._count_scenario_bars_async(
                request,
                mode=mode,
                options=options,
            )
        )

    def prepare_market_data(
        self,
        request: BacktestRunRequest,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return _run_awaitable_sync(
            self._prepare_market_data_async(
                request,
                mode=mode,
                options=options,
                is_cancelled=is_cancelled,
                on_progress=on_progress,
            )
        )

    async def _run_async(self, request: BacktestRunRequest) -> BacktestRunResult:
        return (
            await self._run_detailed_async(
                request,
                mode="production_like",
                options={"preserve_legacy_backtest": True},
            )
        ).run_result

    async def _count_scenario_bars_async(
        self,
        request: BacktestRunRequest,
        *,
        mode: str,
        options: dict[str, Any] | None,
    ) -> int:
        normalized_mode = _normalize_backtest_mode(mode)
        assumptions = _assumptions_for_backtest(request, normalized_mode, options)
        request = _request_with_mode_options(request, normalized_mode, assumptions)
        warmup = max(1, _int_param(request.params, "warmup_candles", self._warmup_candles))
        candles_count = await self._historical_candle_provider.count_candles(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_at=request.start_at,
            end_at=request.end_at,
        )
        return max(0, candles_count - warmup)

    async def _prepare_market_data_async(
        self,
        request: BacktestRunRequest,
        *,
        mode: str,
        options: dict[str, Any] | None,
        is_cancelled: Callable[[], bool] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        normalized_mode = _normalize_backtest_mode(mode)
        assumptions = _assumptions_for_backtest(request, normalized_mode, options)
        request = _request_with_mode_options(request, normalized_mode, assumptions)
        warmup = max(1, _int_param(request.params, "warmup_candles", self._warmup_candles))
        _raise_if_cancelled(is_cancelled)
        _emit_backtest_progress(
            on_progress,
            phase="loading_candles",
            bars_processed=0,
            bars_total=0,
            signals_seen=0,
            trades_count=0,
            risk_rejections=0,
            execution_rejections=0,
            started_at=started_at,
        )
        ensure_candles = getattr(self._historical_candle_provider, "ensure_candles", None)
        if callable(ensure_candles):
            await ensure_candles(
                exchange=request.exchange,
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_at=request.start_at,
                end_at=request.end_at,
            )
        _raise_if_cancelled(is_cancelled)
        candles_count = await self._historical_candle_provider.count_candles(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_at=request.start_at,
            end_at=request.end_at,
        )
        bars_total = max(0, candles_count - warmup)
        _emit_backtest_progress(
            on_progress,
            phase="loading_candles",
            bars_processed=0,
            bars_total=bars_total,
            signals_seen=0,
            trades_count=0,
            risk_rejections=0,
            execution_rejections=0,
            started_at=started_at,
        )
        return {
            "candles_count": candles_count,
            "bars_total": bars_total,
            "warmup_candles": warmup,
        }

    async def _run_detailed_async(
        self,
        request: BacktestRunRequest,
        *,
        mode: str,
        options: dict[str, Any] | None,
        is_cancelled: Callable[[], bool] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        progress_interval_bars: int = 250,
        candle_cache: MutableMapping[str, list[OHLCVCandle]] | None = None,
        feature_cache: MutableMapping[str, list[Features | None]] | None = None,
    ) -> BacktestDetailedRunResult:
        total_started = time.perf_counter()
        timings = _BacktestTimingDiagnostics()
        normalized_mode = _normalize_backtest_mode(mode)
        assumptions = _assumptions_for_backtest(request, normalized_mode, options)
        execution_policy = _execution_policy_for_backtest(normalized_mode, assumptions)
        request = _request_with_mode_options(request, normalized_mode, assumptions)
        _raise_if_cancelled(is_cancelled)
        _emit_backtest_progress(
            on_progress,
            phase="loading_candles",
            bars_processed=0,
            bars_total=0,
            signals_seen=0,
            trades_count=0,
            risk_rejections=0,
            execution_rejections=0,
            started_at=total_started,
        )
        candle_cache_key = _candle_cache_key(request)
        candle_load_started = time.perf_counter()
        cached_candles = candle_cache.get(candle_cache_key) if candle_cache is not None else None
        if cached_candles is not None:
            loaded_candles = list(cached_candles)
        else:
            loaded_candles = await self._historical_candle_provider.load_candles(
                exchange=request.exchange,
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_at=request.start_at,
                end_at=request.end_at,
            )
            if candle_cache is not None:
                candle_cache[candle_cache_key] = list(loaded_candles)
        _add_timing(timings, "candle_load_ms", candle_load_started)
        _raise_if_cancelled(is_cancelled)
        candles = sorted(
            [candle.model_copy(update={"is_closed": True}) for candle in loaded_candles if candle.is_closed],
            key=lambda candle: candle.open_time,
        )
        if not candles:
            raise ValueError(
                "no_historical_data: no closed candles were found for "
                f"{request.exchange}:{request.symbol}:{request.timeframe}"
            )

        warmup = max(1, _int_param(request.params, "warmup_candles", self._warmup_candles))
        rolling_window = max(1, _int_param(request.params, "rolling_window_candles", self._rolling_window_candles))
        if len(candles) < max(MIN_REQUIRED_CANDLES, warmup + 1):
            raise ValueError(
                "not_enough_data: "
                f"{len(candles)} candles loaded, need at least {max(MIN_REQUIRED_CANDLES, warmup + 1)}"
            )

        risk_settings = _risk_settings_from_request(request)
        constraints = _position_constraints_from_request(request)
        state = _BacktestState(cash_equity=float(request.initial_capital))
        state.equity_curve.append(
            _equity_point(candles[warmup - 1], float(request.initial_capital), float(request.initial_capital))
        )

        pending_entries: list[_PendingSignalEntry] = []
        bars_total = max(0, len(candles) - warmup)
        timings.bars_total = bars_total
        feature_cache_key = _feature_cache_key(
            candle_cache_key,
            rolling_window=rolling_window,
            feature_engine=self._feature_engine,
        )
        features_by_index = feature_cache.get(feature_cache_key) if feature_cache is not None else None
        if features_by_index is None:
            features_by_index = [None] * len(candles) if feature_cache is not None else None
            if feature_cache is not None and features_by_index is not None:
                feature_cache[feature_cache_key] = features_by_index
        progress_interval = max(1, progress_interval_bars)
        for index in range(warmup, len(candles)):
            _raise_if_cancelled(is_cancelled)
            bars_processed = index - warmup + 1
            if bars_processed == 1 or bars_processed % progress_interval == 0:
                _emit_backtest_progress(
                    on_progress,
                    phase="running_scenario",
                    bars_processed=bars_processed,
                    bars_total=bars_total,
                    signals_seen=state.signals_seen,
                    trades_count=len(state.closed_positions) + len(state.open_positions),
                    pending_entries_count=len(pending_entries),
                    execution_candidates=state.execution_candidates,
                    pending_armed=state.pending_armed,
                    entry_touched=state.entry_touched,
                    filled=state.filled,
                    closed=len(state.closed_positions),
                    no_entry=state.no_entry,
                    not_selected=state.not_selected,
                    risk_rejections=state.risk_rejections,
                    execution_rejections=state.execution_rejections,
                    started_at=total_started,
                )
            candle = candles[index]
            if pending_entries:
                ready_entries: list[_PendingSignalEntry] = []
                remaining_entries: list[_PendingSignalEntry] = []
                for pending in pending_entries:
                    if not pending.wait_for_entry_zone:
                        ready_entries.append(pending)
                        continue
                    resolved = self._process_historical_pending_entry(
                        request=request,
                        risk_settings=risk_settings,
                        pending=pending,
                        candle=candle,
                        index=index,
                        state=state,
                        constraints=constraints,
                        execution_policy=execution_policy,
                        timings=timings,
                    )
                    if not resolved:
                        remaining_entries.append(pending)
                pending_entries = remaining_entries
                for pending in ready_entries:
                    if (
                        len(state.open_positions) >= constraints.max_concurrent_positions
                        or not _can_open_position_for_signal(
                            pending.signal,
                            policy=constraints.signal_selection_policy,
                            allow_pending_candidates=pending.wait_for_entry_zone,
                            open_positions=state.open_positions,
                            recently_closed=state.closed_positions,
                            max_positions_per_symbol=constraints.max_positions_per_symbol,
                            allow_opposite_signal_flip=constraints.allow_opposite_signal_flip,
                            cooldown_bars_after_close=constraints.cooldown_bars_after_close,
                            current_index=index,
                        )
                    ):
                        state.risk_rejections += 1
                        _append_signal_event(
                            state,
                            _mark_signal_event_rejected(
                                pending.signal_event,
                                risk_rejected=True,
                                reason_code="position_constraints_blocked",
                            ),
                        )
                        continue
                    self._record_open_position_attempt(
                        request=request,
                        risk_settings=risk_settings,
                        features=pending.features,
                        signal=pending.signal,
                        signal_candle=pending.signal_candle,
                        entry_candle=candle,
                        index=index,
                        state=state,
                        execution_policy=execution_policy,
                        signal_event=pending.signal_event,
                        timings=timings,
                    )

            next_open_positions: list[_SimulatedPosition] = []
            for position in state.open_positions:
                updated_position = self._execution_simulator.apply_candle(position, candle)
                if is_terminal_virtual_trade_status(updated_position.trade.status):
                    closed_position = _replace_position(updated_position, exit_index=index)
                    state.cash_equity += _net_pnl(closed_position)
                    state.closed_positions.append(closed_position)
                else:
                    next_open_positions.append(updated_position)
            state.open_positions = next_open_positions

            features = features_by_index[index] if features_by_index is not None else None
            if features is None:
                if bars_processed == 1 or bars_processed % progress_interval == 0:
                    _emit_backtest_progress(
                        on_progress,
                        phase="building_features",
                        bars_processed=bars_processed,
                        bars_total=bars_total,
                        signals_seen=state.signals_seen,
                        trades_count=len(state.closed_positions) + len(state.open_positions),
                        pending_entries_count=len(pending_entries),
                        execution_candidates=state.execution_candidates,
                        pending_armed=state.pending_armed,
                        entry_touched=state.entry_touched,
                        filled=state.filled,
                        closed=len(state.closed_positions),
                        no_entry=state.no_entry,
                        not_selected=state.not_selected,
                        risk_rejections=state.risk_rejections,
                        execution_rejections=state.execution_rejections,
                        started_at=total_started,
                    )
                feature_started = time.perf_counter()
                features = self._feature_engine.process_candles(
                    candles[max(0, index - rolling_window + 1) : index + 1]
                )
                _add_timing(timings, "feature_ms", feature_started)
                if features_by_index is not None:
                    features_by_index[index] = features
            if features is not None and features.candle_state != "closed":
                raise AssertionError("backtest_open_candle_detected: feature window produced an open candle")
            if features is not None and len(state.open_positions) < constraints.max_concurrent_positions:
                strategy_started = time.perf_counter()
                signals = await self._generate_signals(request, features)
                _add_timing(timings, "strategy_ms", strategy_started)
                state.signals_seen += len(signals)
                base_signal_events = {
                    _strategy_signal_key(request, signal): _backtest_signal_event_from_strategy_signal(
                        request=request,
                        features=features,
                        signal=signal,
                        candle=candle,
                    )
                    for signal in signals
                }
                selected_signals = _select_signals(
                    signals,
                    policy=constraints.signal_selection_policy,
                    allow_pending_candidates=_historical_pending_entries_enabled(execution_policy),
                    open_positions=state.open_positions,
                    recently_closed=state.closed_positions,
                    max_positions_per_symbol=constraints.max_positions_per_symbol,
                    allow_opposite_signal_flip=constraints.allow_opposite_signal_flip,
                    cooldown_bars_after_close=constraints.cooldown_bars_after_close,
                    current_index=index,
                )
                attempted_signal_keys: set[str] = set()
                for signal in selected_signals:
                    if len(state.open_positions) >= constraints.max_concurrent_positions:
                        break
                    signal_key = _strategy_signal_key(request, signal)
                    attempted_signal_keys.add(signal_key)
                    signal_event = replace(
                        base_signal_events[signal_key],
                        execution_candidate=True,
                        funnel_stage="execution_candidate",
                    )
                    state.execution_candidates += 1
                    if _should_arm_historical_pending(signal, execution_policy):
                        signal_event = _mark_signal_event_armable(signal_event)
                    if not _can_open_position_for_signal(
                        signal,
                        policy=constraints.signal_selection_policy,
                        allow_pending_candidates=_should_arm_historical_pending(signal, execution_policy),
                        open_positions=state.open_positions,
                        recently_closed=state.closed_positions,
                        max_positions_per_symbol=constraints.max_positions_per_symbol,
                        allow_opposite_signal_flip=constraints.allow_opposite_signal_flip,
                        cooldown_bars_after_close=constraints.cooldown_bars_after_close,
                        current_index=index,
                    ):
                        state.risk_rejections += 1
                        _append_signal_event(
                            state,
                            _mark_signal_event_rejected(
                                signal_event,
                                risk_rejected=True,
                                reason_code="position_constraints_blocked",
                            ),
                        )
                        continue
                    previous_risk_rejections = state.risk_rejections
                    previous_execution_rejections = state.execution_rejections
                    previous_execution_policy_no_entries = len(state.execution_policy_no_entries)
                    previous_execution_policy_rejections = len(state.execution_policy_rejections)
                    if _should_arm_historical_pending(signal, execution_policy):
                        state.pending_armed += 1
                        pending_entries.append(
                            _PendingSignalEntry(
                                signal=signal,
                                signal_event=_mark_signal_event_pending_armed(
                                    signal_event,
                                    armed_index=index,
                                    max_wait_bars=_historical_pending_max_wait_bars(request),
                                ),
                                features=features,
                                signal_candle=candle,
                                armed_index=index,
                                max_wait_bars=_historical_pending_max_wait_bars(request),
                                wait_for_entry_zone=True,
                            )
                        )
                    elif execution_policy.entry_timing == "next_candle_open":
                        pending_entries.append(
                            _PendingSignalEntry(
                                signal=signal,
                                signal_event=signal_event,
                                features=features,
                                signal_candle=candle,
                                armed_index=index,
                            )
                        )
                    else:
                        self._record_open_position_attempt(
                            request=request,
                            risk_settings=risk_settings,
                            features=features,
                            signal=signal,
                            signal_candle=candle,
                            entry_candle=None,
                            index=index,
                            state=state,
                            execution_policy=execution_policy,
                            signal_event=signal_event,
                            previous_risk_rejections=previous_risk_rejections,
                            previous_execution_rejections=previous_execution_rejections,
                            previous_execution_policy_no_entries=previous_execution_policy_no_entries,
                            previous_execution_policy_rejections=previous_execution_policy_rejections,
                            timings=timings,
                        )
                for signal in signals:
                    signal_key = _strategy_signal_key(request, signal)
                    if signal_key in attempted_signal_keys:
                        continue
                    _append_signal_event(
                        state,
                        _mark_signal_event_not_selected(base_signal_events[signal_key]),
                    )

            state.equity_curve.append(_equity_point(candle, _current_equity(state), float(request.initial_capital)))

        for pending in pending_entries:
            reason_code = (
                "pending_entry_expired_before_touch"
                if pending.wait_for_entry_zone
                else "no_next_candle_for_entry"
            )
            _append_signal_event(state, _mark_signal_event_no_entry(pending.signal_event, reason_code))
        pending_entries = []

        if state.open_positions:
            closed_at_end: list[_SimulatedPosition] = []
            for position in state.open_positions:
                closed_position = self._execution_simulator.close_at_end(position, candles[-1])
                closed_position = _replace_position(closed_position, exit_index=len(candles) - 1)
                state.cash_equity += _net_pnl(closed_position)
                closed_at_end.append(closed_position)
            state.closed_positions.extend(closed_at_end)
            state.open_positions = []
            state.equity_curve.append(
                _equity_point(candles[-1], state.cash_equity, float(request.initial_capital))
            )

        _raise_if_cancelled(is_cancelled)
        state.signal_events = _closed_signal_events(state.signal_events, state.closed_positions)
        timings.total_ms = _elapsed_ms(total_started)
        _emit_backtest_progress(
            on_progress,
            phase="running_scenario",
            bars_processed=bars_total,
            bars_total=bars_total,
            signals_seen=state.signals_seen,
            trades_count=len(state.closed_positions),
            pending_entries_count=0,
            execution_candidates=state.execution_candidates,
            pending_armed=state.pending_armed,
            entry_touched=state.entry_touched,
            filled=state.filled,
            closed=len(state.closed_positions),
            no_entry=state.no_entry,
            not_selected=state.not_selected,
            risk_rejections=state.risk_rejections,
            execution_rejections=state.execution_rejections,
            started_at=total_started,
        )
        metrics = _metrics_from_state(state)
        assumptions = _assumptions_with_runtime_diagnostics(assumptions, state, timings=timings)
        final_equity = state.cash_equity
        initial_capital = float(request.initial_capital)
        result = BacktestResultResponse(
            run_id=uuid4(),
            user_id=_result_user_id(request.user_id),
            strategy_code=request.strategy_code,
            strategy_version=request.strategy_version or "v1",
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_at=request.start_at,
            end_at=request.end_at,
            initial_capital=request.initial_capital,
            final_equity=_decimal(final_equity),
            pnl=_decimal(final_equity - initial_capital),
            pnl_pct=((final_equity - initial_capital) / initial_capital * 100) if initial_capital else 0.0,
            max_drawdown_pct=metrics["max_drawdown_pct"],
            trades_count=metrics["trades_count"],
            wins_count=metrics["wins"],
            losses_count=metrics["losses"],
            metrics=metrics,
            equity_curve=state.equity_curve,
            created_at=datetime.now(timezone.utc),
        )
        run_result = BacktestRunResult(status="completed", result=result)
        return BacktestDetailedRunResult(
            run_result=run_result,
            trades=_simulated_trades_from_state(state, request=request),
            signals_seen=state.signals_seen,
            risk_rejections=state.risk_rejections,
            execution_rejections=state.execution_rejections,
            assumptions=assumptions,
            signal_events=state.signal_events,
        )

    def _process_historical_pending_entry(
        self,
        *,
        request: BacktestRunRequest,
        risk_settings: RiskManagementSettings,
        pending: _PendingSignalEntry,
        candle: OHLCVCandle,
        index: int,
        state: _BacktestState,
        constraints: _PositionConstraints,
        execution_policy: BacktestExecutionPolicy,
        timings: _BacktestTimingDiagnostics,
    ) -> bool:
        if _historical_pending_expired(pending, candle, index):
            _append_signal_event(
                state,
                _mark_signal_event_no_entry(
                    pending.signal_event,
                    "pending_entry_expired_before_touch",
                ),
            )
            return True

        touched = _entry_zone_touched(pending.signal, candle)
        if not touched:
            if _pending_invalidated_before_touch(pending.signal, candle):
                _append_signal_event(
                    state,
                    _mark_signal_event_no_entry(
                        pending.signal_event,
                        "pending_entry_invalidated_before_touch",
                    ),
                )
                return True
            return False

        touched_event = _mark_signal_event_entry_zone_touched(
            pending.signal_event,
            candle=candle,
        )
        state.entry_touched += 1
        if (
            len(state.open_positions) >= constraints.max_concurrent_positions
            or not _can_open_position_for_signal(
                pending.signal,
                policy=constraints.signal_selection_policy,
                allow_pending_candidates=True,
                open_positions=state.open_positions,
                recently_closed=state.closed_positions,
                max_positions_per_symbol=constraints.max_positions_per_symbol,
                allow_opposite_signal_flip=constraints.allow_opposite_signal_flip,
                cooldown_bars_after_close=constraints.cooldown_bars_after_close,
                current_index=index,
            )
        ):
            state.risk_rejections += 1
            _append_signal_event(
                state,
                _mark_signal_event_rejected(
                    touched_event,
                    risk_rejected=True,
                    reason_code="position_constraints_blocked",
                ),
            )
            return True

        fill_price = _historical_pending_fill_price(pending.signal, candle)
        fill_signal = _signal_with_historical_pending_touch_gate(pending.signal)
        self._record_open_position_attempt(
            request=request,
            risk_settings=risk_settings,
            features=pending.features,
            signal=fill_signal,
            signal_candle=pending.signal_candle,
            entry_candle=candle,
            index=index,
            state=state,
            execution_policy=execution_policy,
            signal_event=touched_event,
            timings=timings,
            entry_price_override=fill_price,
            bars_to_entry=max(0, index - pending.armed_index),
        )
        return True

    async def _generate_signals(
        self,
        request: BacktestRunRequest,
        features: Features,
    ) -> list[StrategySignal]:
        strategy_code = _resolve_strategy_code(request.strategy_code)
        runtime_config = _StrategyRuntimeConfig(
            params=_strategy_params_from_request(request),
            risk_settings=_risk_settings_params_from_request(request),
        )
        signals = await self._strategy_engine.generate_signals(
            features,
            strategy_configs={strategy_code: runtime_config},
            rr_guard_context="backtest",
        )
        if any(signal.candle_state != "closed" for signal in signals):
            raise AssertionError("backtest_open_candle_detected: strategy signal used an open candle")
        return signals

    def _record_open_position_attempt(
        self,
        *,
        request: BacktestRunRequest,
        risk_settings: RiskManagementSettings,
        features: Features,
        signal: StrategySignal,
        signal_candle: OHLCVCandle,
        entry_candle: OHLCVCandle | None,
        index: int,
        state: _BacktestState,
        execution_policy: BacktestExecutionPolicy,
        signal_event: BacktestSignalEvent,
        previous_risk_rejections: int | None = None,
        previous_execution_rejections: int | None = None,
        previous_execution_policy_no_entries: int | None = None,
        previous_execution_policy_rejections: int | None = None,
        timings: _BacktestTimingDiagnostics | None = None,
        entry_price_override: float | None = None,
        bars_to_entry: int = 0,
    ) -> _SimulatedPosition | None:
        if previous_risk_rejections is None:
            previous_risk_rejections = state.risk_rejections
        if previous_execution_rejections is None:
            previous_execution_rejections = state.execution_rejections
        if previous_execution_policy_no_entries is None:
            previous_execution_policy_no_entries = len(state.execution_policy_no_entries)
        if previous_execution_policy_rejections is None:
            previous_execution_policy_rejections = len(state.execution_policy_rejections)

        position = self._try_open_position(
            request=request,
            risk_settings=risk_settings,
            features=features,
            signal=signal,
            candle=signal_candle,
            entry_candle=entry_candle,
            index=index,
            state=state,
            execution_policy=execution_policy,
            timings=timings,
            entry_price_override=entry_price_override,
            bars_to_entry=bars_to_entry,
        )
        if position is not None:
            state.open_positions.append(position)
            if not signal_event.entry_touched:
                state.entry_touched += 1
            _append_signal_event(state, _mark_signal_event_filled(signal_event, position))
        elif state.risk_rejections > previous_risk_rejections:
            _append_signal_event(
                state,
                _mark_signal_event_rejected(
                    signal_event,
                    risk_rejected=True,
                    reason_code=_last_reason_code(state.risk_gate_blockers, "risk_gate_rejected"),
                ),
            )
        elif state.execution_rejections > previous_execution_rejections:
            _append_signal_event(
                state,
                _mark_signal_event_rejected(
                    signal_event,
                    execution_rejected=True,
                    reason_code=(
                        _last_reason_code(state.execution_policy_rejections, "virtual_execution_rejected")
                        if len(state.execution_policy_rejections) > previous_execution_policy_rejections
                        else "virtual_execution_rejected"
                    ),
                ),
            )
        elif len(state.execution_policy_no_entries) > previous_execution_policy_no_entries:
            _append_signal_event(
                state,
                _mark_signal_event_no_entry(
                    signal_event,
                    _last_reason_code(state.execution_policy_no_entries, "not_filled"),
                ),
            )
        else:
            _append_signal_event(state, _mark_signal_event_no_entry(signal_event, "not_filled"))
        return position

    def _try_open_position(
        self,
        *,
        request: BacktestRunRequest,
        risk_settings: RiskManagementSettings,
        features: Features,
        signal: StrategySignal | None,
        candle: OHLCVCandle,
        entry_candle: OHLCVCandle | None = None,
        index: int,
        state: _BacktestState,
        execution_policy: BacktestExecutionPolicy,
        timings: _BacktestTimingDiagnostics | None = None,
        entry_price_override: float | None = None,
        bars_to_entry: int = 0,
    ) -> _SimulatedPosition | None:
        if signal is None:
            return None
        if not execution_policy.virtual_execution_enabled:
            state.execution_policy_no_entries.append(_execution_disabled_reason(execution_policy))
            return None
        signal = _normalize_signal_for_backtest(
            signal=signal,
            features=features,
            request=request,
            execution_policy=execution_policy,
            state=state,
        )
        radar_signal = _radar_signal_from_strategy_signal(signal, candle)
        opened_at = _datetime_from_ms(entry_candle.open_time if entry_candle is not None else candle.close_time)
        entry_price = (
            entry_price_override
            if entry_price_override is not None
            else float(entry_candle.open)
            if entry_candle is not None
            else (_entry_price(signal) or features.close)
        )
        request_fee_rate = float(request.fee_rate)
        request_slippage_bps = float(request.slippage_bps)
        confirm_request = ManualConfirmRequest(
            user_id=request.user_id,
            account_balance=max(state.cash_equity, 0.000001),
            risk_percent=risk_settings.risk_per_trade_percent,
            leverage=_int_param(request.params, "leverage", 1),
            size_usd=_float_param(request.params, "size_usd", None),
            fee_rate=request_fee_rate,
            slippage_bps=request_slippage_bps,
            simulation_mode=str(request.params.get("simulation_mode") or "passive"),
            max_virtual_slippage_bps=_float_param(
                request.params,
                "max_virtual_slippage_bps",
                risk_settings.max_slippage_bps,
            )
            or risk_settings.max_slippage_bps,
        )
        current_equity = _current_equity(state)
        open_virtual_trades = _open_virtual_trades(state.open_positions)
        account = VirtualAccount(
            user_id=request.user_id,
            starting_balance=float(request.initial_capital),
            balance=state.cash_equity,
            equity=current_equity,
            realized_pnl=state.cash_equity - float(request.initial_capital),
            unrealized_pnl=sum(position.trade.unrealized_pnl for position in state.open_positions),
            risk_per_trade=current_equity * risk_settings.risk_per_trade_percent / 100,
            risk_reward=risk_settings.min_rr_ratio,
            open_positions=len(state.open_positions),
            closed_trades=len(state.closed_positions),
            updated_at=opened_at,
        )
        try:
            gate_started = time.perf_counter()
            pre_execution_decision = self._risk_gate_service.evaluate(
                context=self._risk_context_service.build_virtual_context(
                    signal=radar_signal,
                    request=confirm_request,
                    account=account,
                    entry_price=entry_price,
                    open_positions=open_virtual_trades,
                    requested_notional=confirm_request.size_usd,
                    stage="pre_execution",
                    signal_stop_loss_price=signal.stop_loss,
                    atr_value=features.atr_14,
                    funding_buffer_per_unit=_float_param(request.params, "funding_buffer_per_unit", 0.0) or 0.0,
                    spread_percent=_float_param(request.params, "spread_percent", None),
                    spread_bps=_float_param(request.params, "spread_bps", None),
                    orderbook_depth_usd=_float_param(request.params, "orderbook_depth_usd", None),
                    market_data_status=str(request.params.get("market_data_status") or "unknown"),
                    rr_guard_context="backtest",
                ),
                risk_settings=risk_settings,
            )
        except ValueError as exc:
            _add_timing(timings, "gate_ms", gate_started)
            state.risk_rejections += 1
            state.risk_gate_blockers.append(str(exc))
            return None
        _add_timing(timings, "gate_ms", gate_started)
        pre_execution_decision = _decision_for_mode(pre_execution_decision, execution_policy.mode)
        if not pre_execution_decision.can_enter:
            state.risk_rejections += 1
            state.risk_gate_blockers.extend(pre_execution_decision.blockers)
            return None

        gate_started = time.perf_counter()
        execution_policy_decision = _backtest_execution_policy_decision(
            request=request,
            risk_settings=risk_settings,
            signal=signal,
            features=features,
            current_price=entry_price,
            confirm_request=confirm_request,
            risk_decision=pre_execution_decision,
        )
        _add_timing(timings, "gate_ms", gate_started)
        if not execution_policy_decision.can_execute:
            if execution_policy_decision.should_wait:
                state.execution_policy_no_entries.append(execution_policy_decision.reason_code)
            else:
                state.execution_rejections += 1
                state.execution_policy_rejections.append(execution_policy_decision.reason_code)
            return None

        execution_started = time.perf_counter()
        execution = self._execution_simulator.simulate_entry(
            signal=radar_signal,
            request=confirm_request,
            risk_decision=pre_execution_decision,
            reference_price=entry_price,
        )
        _add_timing(timings, "execution_ms", execution_started)
        if execution.status == "rejected_virtual_execution" or execution.average_price is None:
            state.execution_rejections += 1
            return None

        filled_size_usd = execution.filled_size_usd
        if filled_size_usd <= 0:
            state.execution_rejections += 1
            return None
        filled_entry = execution.average_price
        try:
            gate_started = time.perf_counter()
            post_execution_decision = self._risk_gate_service.evaluate(
                context=self._risk_context_service.build_virtual_context(
                    signal=radar_signal,
                    request=confirm_request,
                    account=account,
                    entry_price=filled_entry,
                    open_positions=open_virtual_trades,
                    requested_notional=filled_size_usd,
                    stage="post_execution",
                    signal_stop_loss_price=signal.stop_loss,
                    atr_value=features.atr_14,
                    funding_buffer_per_unit=_float_param(request.params, "funding_buffer_per_unit", 0.0) or 0.0,
                    spread_percent=_float_param(request.params, "spread_percent", None),
                    spread_bps=_float_param(request.params, "spread_bps", None),
                    orderbook_depth_usd=_float_param(request.params, "orderbook_depth_usd", None),
                    market_data_status=str(request.params.get("market_data_status") or "unknown"),
                    rr_guard_context="backtest",
                ),
                risk_settings=risk_settings,
            )
        except ValueError as exc:
            _add_timing(timings, "gate_ms", gate_started)
            state.risk_rejections += 1
            state.risk_gate_blockers.append(str(exc))
            return None
        _add_timing(timings, "gate_ms", gate_started)
        post_execution_decision = _decision_for_mode(post_execution_decision, execution_policy.mode)
        if not post_execution_decision.can_enter:
            state.risk_rejections += 1
            state.risk_gate_blockers.extend(post_execution_decision.blockers)
            return None

        execution = _execution_with_risk_decision(execution, post_execution_decision)
        trade = _virtual_trade_from_execution(
            request=request,
            signal=radar_signal,
            execution=execution,
            decision=post_execution_decision,
            opened_at=opened_at,
        )
        trade = arm_virtual_trade_time_stop(
            initialize_virtual_trade_lifecycle(trade),
            _trade_plan_time_stop_metadata(radar_signal),
            opened_at,
        )
        return _SimulatedPosition(
            trade=trade,
            signal=radar_signal,
            entry_index=index,
            reference_entry_price=entry_price,
            bars_to_entry=bars_to_entry,
            funding_buffer_per_unit=_float_param(request.params, "funding_buffer_per_unit", 0.0) or 0.0,
            strategy=radar_signal.strategy,
            regime=_regime_key(radar_signal),
            features_snapshot=_features_snapshot(features, radar_signal, request=request),
            warnings=_dedupe_strings([*pre_execution_decision.warnings, *post_execution_decision.warnings]),
        )


def _normalize_backtest_mode(mode: str) -> str:
    normalized = mode.strip().lower().replace("-", "_")
    if normalized in {"discovery", "research_virtual", "production_like"}:
        return normalized
    return "production_like"


def _execution_policy_for_backtest(
    mode: str,
    assumptions: Mapping[str, Any],
) -> BacktestExecutionPolicy:
    return BacktestExecutionPolicy(
        mode=mode,
        production_mode=mode == "production_like",
        virtual_execution_enabled=_bool_param(assumptions, "virtual_execution_enabled", mode != "discovery"),
        historical_pending_entries_enabled=_bool_param(
            assumptions,
            "historical_pending_entries_enabled",
            False,
        ),
        preserve_legacy_backtest=bool(assumptions.get("preserve_legacy_backtest")),
        entry_timing=str(assumptions.get("entry_timing") or _entry_timing_for_backtest(mode, assumptions)),
    )


def _entry_timing_for_backtest(mode: str, assumptions: Mapping[str, Any]) -> str:
    if mode == "production_like" and not bool(assumptions.get("preserve_legacy_backtest")):
        return "next_candle_open"
    return "same_candle_close"


def _resolve_historical_pending_entries_enabled(
    *,
    request: BacktestRunRequest,
    mode: str,
    assumptions: Mapping[str, Any],
) -> bool:
    if mode == "discovery" or bool(assumptions.get("preserve_legacy_backtest")):
        return False
    explicit_request = _optional_bool_param(request.params, "historical_pending_entries_enabled")
    if explicit_request is not None:
        return explicit_request
    explicit_assumption = _optional_bool_param(assumptions, "historical_pending_entries_enabled")
    if explicit_assumption is not None:
        return explicit_assumption
    return mode in {"research_virtual", "production_like"}


def _historical_pending_entries_enabled(execution_policy: BacktestExecutionPolicy) -> bool:
    return (
        execution_policy.historical_pending_entries_enabled
        and execution_policy.virtual_execution_enabled
        and not execution_policy.preserve_legacy_backtest
    )


def _should_arm_historical_pending(
    signal: StrategySignal,
    execution_policy: BacktestExecutionPolicy,
) -> bool:
    if not _historical_pending_entries_enabled(execution_policy):
        return False
    if not is_waiting_entry_status(str(signal.status)):
        return False
    gate = signal.execution_gate
    if gate is None or not gate.can_arm_pending:
        return False
    return _entry_zone(signal) is not None


def _historical_pending_max_wait_bars(request: BacktestRunRequest) -> int:
    for key in ("historical_pending_max_wait_bars", "pending_entry_max_wait_bars", "max_wait_bars"):
        value = _int_param(request.params, key, 0)
        if value > 0:
            return value
    return 12


def _historical_pending_expired(
    pending: _PendingSignalEntry,
    candle: OHLCVCandle,
    index: int,
) -> bool:
    if pending.max_wait_bars > 0 and index - pending.armed_index > pending.max_wait_bars:
        return True
    expires_at = _signal_expires_at(pending.signal)
    if expires_at is None:
        return False
    return _datetime_from_ms(candle.open_time) >= expires_at


def _entry_zone_touched(signal: StrategySignal, candle: OHLCVCandle) -> bool:
    zone = _entry_zone(signal)
    if zone is None:
        return False
    entry_min, entry_max = zone
    return candle.low <= entry_max and candle.high >= entry_min


def _pending_invalidated_before_touch(signal: StrategySignal, candle: OHLCVCandle) -> bool:
    if signal.stop_loss is None:
        return False
    direction = _normalized_direction(signal.direction)
    if direction == "short":
        return candle.high >= signal.stop_loss
    return candle.low <= signal.stop_loss


def _historical_pending_fill_price(signal: StrategySignal, candle: OHLCVCandle) -> float:
    zone = _entry_zone(signal)
    if zone is None:
        return candle.open
    entry_min, entry_max = zone
    if entry_min <= candle.open <= entry_max:
        return candle.open
    direction = _normalized_direction(signal.direction)
    if direction == "short":
        return entry_min if candle.open < entry_min else entry_max
    return entry_max if candle.open > entry_max else entry_min


def _entry_zone(signal: StrategySignal) -> tuple[float, float] | None:
    if signal.entry_min is None or signal.entry_max is None:
        return None
    entry_min = float(signal.entry_min)
    entry_max = float(signal.entry_max)
    if entry_min <= 0 or entry_max <= 0:
        return None
    if entry_max < entry_min:
        return entry_max, entry_min
    return entry_min, entry_max


def _signal_with_historical_pending_touch_gate(signal: StrategySignal) -> StrategySignal:
    gate = signal.execution_gate
    if gate is not None:
        gate_metadata = dict(gate.metadata)
        gate_metadata.update(
            {
                "runtime": "historical_backtest",
                "event": "pending_entry_filled",
            }
        )
        gate = gate.model_copy(
            update={
                "status": "passed",
                "feed_kind": "execution_signal",
                "can_notify": True,
                "can_enter_now": True,
                "can_arm_pending": False,
                "can_show_in_execution_feed": True,
                "metadata": gate_metadata,
            }
        )
    return signal.model_copy(
        update={
            "status": "actionable",
            "execution_gate": gate,
        },
        deep=True,
    )


def _signal_expires_at(signal: StrategySignal) -> datetime | None:
    trade_plan = signal.trade_plan
    if trade_plan is None:
        return None
    raw_value = trade_plan.metadata.get("expires_at") or trade_plan.entry.metadata.get("expires_at")
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.astimezone(timezone.utc)
    if isinstance(raw_value, str):
        try:
            return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _candle_cache_key(request: BacktestRunRequest) -> str:
    return ":".join(
        [
            request.exchange.strip().lower(),
            request.symbol.strip().upper(),
            request.timeframe.strip(),
            _cache_datetime(request.start_at),
            _cache_datetime(request.end_at),
        ]
    )


def _feature_cache_key(
    candle_cache_key: str,
    *,
    rolling_window: int,
    feature_engine: FeatureEngine,
) -> str:
    engine_key = f"{type(feature_engine).__module__}.{type(feature_engine).__qualname__}"
    return f"{candle_cache_key}:rolling_window={rolling_window}:feature_engine={engine_key}"


def _cache_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _add_timing(
    timings: _BacktestTimingDiagnostics | None,
    field_name: str,
    started: float,
) -> None:
    if timings is None:
        return
    setattr(timings, field_name, float(getattr(timings, field_name)) + _elapsed_ms(started))


def _round_ms(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(value, 3)


def _normalize_signal_for_backtest(
    *,
    signal: StrategySignal,
    features: Features,
    request: BacktestRunRequest,
    execution_policy: BacktestExecutionPolicy,
    state: _BacktestState,
) -> StrategySignal:
    trade_plan_enrichment = TradePlanEnrichmentService()
    signal = trade_plan_enrichment.ensure_trade_plan(signal)
    strategy_params = _strategy_params_from_request(request)
    pipeline_settings = _backtest_pipeline_settings(
        request=request,
        strategy_params=strategy_params,
        execution_policy=execution_policy,
    )
    market_context = MarketContextService().build_snapshot(
        features=features,
        direction=signal.direction,
        settings=pipeline_settings,
    )
    context = StrategyEvaluationContext(
        signal_features=features,
        strategy_params=strategy_params,
        pipeline_settings=pipeline_settings,
        market_context=market_context,
        rr_guard_context="backtest",
    )
    invalidation = InvalidationLayer().build(signal, context)
    exit_plan = ExitManagementLayer().build(signal, context)
    trade_plan, risk_reward, signal = _enrich_trade_plan_with_final_risk_reward(
        signal=signal,
        exit_plan=exit_plan,
        invalidation=invalidation,
        params=pipeline_settings,
        rr_guard_context="backtest",
        trade_plan_enrichment=trade_plan_enrichment,
    )
    trade_plan = _trade_plan_with_executable_backtest_rr_target(trade_plan)
    trade_plan = _trade_plan_with_explicit_backtest_targets(trade_plan, state=state)
    trade_plan = _trade_plan_with_backtest_assumption_metadata(
        trade_plan,
        state=state,
        execution_policy=execution_policy,
    )
    trade_plan = _trade_plan_with_backtest_market_context(trade_plan, market_context)
    completeness = trade_plan_completeness_service.assess(
        signal,
        trade_plan,
        settings=pipeline_settings,
        context={
            "backtest_features": features,
            "backtest_request": request,
            "market_context": market_context,
        },
        production_mode=execution_policy.production_mode,
    )
    trade_plan = trade_plan_enrichment.attach_completeness_metadata(
        trade_plan=trade_plan,
        completeness=completeness,
        production_mode=execution_policy.production_mode,
    )
    if completeness.warnings:
        state.trade_plan_completion_warnings.extend(completeness.warnings)
    return signal.model_copy(
        update={
            "invalidation": invalidation,
            "exit_plan": exit_plan,
            "trade_plan": trade_plan,
            "first_target_rr": risk_reward.first_target_rr,
            "final_target_rr": risk_reward.final_target_rr,
            "selected_rr": risk_reward.rr,
            "selected_rr_target": risk_reward.target_key,
            "min_rr_ratio": risk_reward.min_rr,
        },
        deep=True,
    )


def _backtest_pipeline_settings(
    *,
    request: BacktestRunRequest,
    strategy_params: Mapping[str, Any],
    execution_policy: BacktestExecutionPolicy,
) -> dict[str, Any]:
    values = {
        **dict(_risk_settings_params_from_request(request)),
        **dict(strategy_params),
    }
    values["signal_mode"] = "production" if execution_policy.production_mode else execution_policy.mode
    if execution_policy.production_mode:
        values["production_mode"] = True
    values["backtest_mode"] = execution_policy.mode
    values["backtest_execution_policy"] = "production_compatible"
    if execution_policy.preserve_legacy_backtest:
        values["preserve_legacy_backtest"] = True
    return values


def _trade_plan_with_executable_backtest_rr_target(trade_plan: TradePlan) -> TradePlan:
    if trade_plan.risk_rules.selected_rr_target not in {None, "disabled"}:
        return trade_plan
    risk_rules = trade_plan.risk_rules.model_copy(
        update={
            "selected_rr": trade_plan.risk_rules.final_target_rr or trade_plan.risk_rules.first_target_rr,
            "selected_rr_target": "final",
        }
    )
    metadata = dict(trade_plan.metadata)
    assumptions = list(metadata.get("backtest_assumptions") or [])
    assumptions.append("backtest_rr_guard_disabled_uses_final_target_for_execution")
    metadata["backtest_assumptions"] = _dedupe_strings([str(item) for item in assumptions])
    metadata["rr_guard_disabled_for_reporting"] = True
    return trade_plan.model_copy(
        update={
            "metadata": metadata,
            "risk_rules": risk_rules,
        },
        deep=True,
    )


def _trade_plan_with_explicit_backtest_targets(
    trade_plan: TradePlan,
    *,
    state: _BacktestState,
) -> TradePlan:
    targets = []
    changed = False
    for target in trade_plan.targets:
        if target.source != "legacy_fields" or target.thesis is None:
            targets.append(target)
            continue
        if target.thesis.source != "risk_multiple_fallback":
            targets.append(target)
            continue
        metadata = _target_metadata_without_fallback_thesis(target.metadata)
        targets.append(target.model_copy(update={"thesis": None, "metadata": metadata}))
        changed = True
    if not changed:
        return trade_plan
    state.backtest_trade_plan_assumptions.append("backtest_explicit_legacy_targets_preserved")
    metadata = dict(trade_plan.metadata)
    assumptions = list(metadata.get("backtest_assumptions") or [])
    assumptions.append("backtest_explicit_legacy_targets_preserved")
    metadata["backtest_assumptions"] = _dedupe_strings([str(item) for item in assumptions])
    return trade_plan.model_copy(update={"targets": targets, "metadata": metadata}, deep=True)


def _target_metadata_without_fallback_thesis(metadata: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = dict(metadata)
    nested = cleaned.get("metadata")
    if isinstance(nested, Mapping):
        cleaned["metadata"] = _target_metadata_without_fallback_thesis(nested)
    for key in (
        "fallback_target_used",
        "fallback_target_source",
        "market_target_source",
        "target_confidence",
        "target_priority",
        "target_source",
        "target_thesis",
        "target_thesis_source",
    ):
        cleaned.pop(key, None)
    return cleaned


def _trade_plan_with_backtest_assumption_metadata(
    trade_plan: TradePlan,
    *,
    state: _BacktestState,
    execution_policy: BacktestExecutionPolicy,
) -> TradePlan:
    assumption = "backtest_pipeline_invalidation_enrichment"
    if execution_policy.preserve_legacy_backtest:
        assumption = "preserve_legacy_backtest_pipeline_invalidation_enrichment"
    state.backtest_trade_plan_assumptions.append(assumption)
    metadata = dict(trade_plan.metadata)
    assumptions = list(metadata.get("backtest_assumptions") or [])
    assumptions.append(assumption)
    metadata["backtest_assumptions"] = _dedupe_strings([str(item) for item in assumptions])
    metadata["backtest_execution_policy"] = "production_compatible"
    metadata["backtest_mode"] = execution_policy.mode
    if execution_policy.preserve_legacy_backtest:
        metadata["preserve_legacy_backtest"] = True
    return trade_plan.model_copy(update={"metadata": metadata}, deep=True)


def _trade_plan_with_backtest_market_context(
    trade_plan: TradePlan,
    market_context: MarketContextSnapshot,
) -> TradePlan:
    context_payload = market_context.model_dump(mode="json")
    context_updates = {
        "market_context": context_payload,
        "market_context_reason_codes": list(market_context.reason_codes),
        "market_context_risk_off": market_context.risk_off,
    }
    metadata = dict(trade_plan.metadata)
    metadata.update(context_updates)
    risk_metadata = dict(trade_plan.risk_rules.metadata)
    risk_metadata.update(context_updates)
    return trade_plan.model_copy(
        update={
            "metadata": metadata,
            "risk_rules": trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata}),
        },
        deep=True,
    )


def _assumptions_with_runtime_diagnostics(
    assumptions: Mapping[str, Any],
    state: _BacktestState,
    *,
    timings: _BacktestTimingDiagnostics,
) -> dict[str, Any]:
    values = dict(assumptions)
    values["trade_plan_completion_warnings"] = _dedupe_strings(state.trade_plan_completion_warnings)
    values["risk_gate_blockers"] = _dedupe_strings(state.risk_gate_blockers)
    values["backtest_trade_plan_assumptions"] = _dedupe_strings(state.backtest_trade_plan_assumptions)
    values["timings"] = timings.summary()
    return values


def _assumptions_for_backtest(
    request: BacktestRunRequest,
    mode: str,
    options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    values = dict(options or {})
    values.setdefault("mode", mode)
    preserve_legacy = bool(values.get("preserve_legacy_backtest"))
    values["entry_timing"] = _entry_timing_for_backtest(mode, values)
    values.setdefault("bar_level_sequencing_policy", "pending_entries_before_position_management")
    values.setdefault("fee_rate", str(request.fee_rate))
    values.setdefault("slippage_bps", str(request.slippage_bps))
    values.setdefault("initial_capital", str(request.initial_capital))
    requested_same_candle_policy = (
        request.params.get("same_candle_policy")
        or values.get("same_candle_policy")
        or "conservative_stop_first"
    )
    normalized_same_candle_policy = normalize_virtual_execution_ambiguity_policy(
        str(requested_same_candle_policy)
    )
    values["same_candle_policy"] = normalized_same_candle_policy
    if str(requested_same_candle_policy) != normalized_same_candle_policy:
        values["same_candle_policy_requested"] = str(requested_same_candle_policy)
    values.setdefault("candle_state", "closed")
    values.setdefault("alpha_context_available", False)
    values.setdefault(
        "alpha_context_missing_sources",
        ["historical_trades", "historical_l2", "historical_derivative_history"],
    )
    values.setdefault(
        "signal_selection_policy",
        _normalize_signal_selection_policy(
            request.params.get("signal_selection_policy"),
            default=_default_signal_selection_policy(mode, values),
        ),
    )
    values.setdefault("max_concurrent_positions", _int_param(request.params, "max_concurrent_positions", 1))
    values.setdefault("max_positions_per_symbol", _int_param(request.params, "max_positions_per_symbol", 1))
    values.setdefault("cooldown_bars_after_close", _int_param(request.params, "cooldown_bars_after_close", 0))
    values.setdefault(
        "allow_opposite_signal_flip",
        _bool_param(request.params, "allow_opposite_signal_flip", False),
    )
    threshold_params = _liquidity_sweep_threshold_params(request)
    if threshold_params:
        values.setdefault("liquidity_sweep_threshold_experiment_params", threshold_params)
    breakout_params = _breakout_experiment_params(request)
    if breakout_params:
        values.setdefault("breakout_classifier_experiment_params", breakout_params)
    trend_pullback_params = _trend_pullback_experiment_params(request)
    if trend_pullback_params:
        values.setdefault("trend_pullback_experiment_params", trend_pullback_params)
    exit_policy_params = _exit_policy_experiment_params(request)
    if exit_policy_params:
        values.setdefault("exit_policy_experiment_params", exit_policy_params)
    values.setdefault("exit_policy", request.params.get("exit_policy") or "market_targets")
    values.setdefault(
        "target_sources_enabled",
        request.params.get(
            "target_sources_enabled",
            [
                "nearest_liquidity_pool",
                "previous_day_high",
                "previous_day_low",
                "session_high",
                "session_low",
                "range_midpoint",
                "range_opposite_boundary",
                "vwap",
                "vwap_deviation_band",
                "htf_support",
                "htf_resistance",
                "measured_move",
            ],
        ),
    )
    values.setdefault("partial_exit_policy", request.params.get("partial_exit_policy") or "source_default")
    values.setdefault("allow_r_multiple_fallback", _bool_param(request.params, "allow_r_multiple_fallback", False))
    if mode == "discovery":
        values.setdefault("risk_gate_enabled", False)
        values.setdefault("rr_hard_gate_enabled", False)
        values.setdefault("virtual_execution_enabled", False)
        values.setdefault("lifecycle_enabled", False)
    elif mode == "research_virtual":
        values.setdefault("risk_gate_enabled", False)
        values.setdefault("rr_hard_gate_enabled", False)
        values.setdefault("virtual_execution_enabled", True)
        values.setdefault("lifecycle_enabled", True)
    else:
        values.setdefault("risk_gate_enabled", True)
        values.setdefault("rr_hard_gate_enabled", False if preserve_legacy else True)
        values.setdefault("virtual_execution_enabled", True)
        values.setdefault("lifecycle_enabled", True)
    values["historical_pending_entries_enabled"] = _resolve_historical_pending_entries_enabled(
        request=request,
        mode=mode,
        assumptions=values,
    )
    values.setdefault("historical_pending_max_wait_bars", _historical_pending_max_wait_bars(request))
    return values


def _request_with_mode_options(
    request: BacktestRunRequest,
    mode: str,
    assumptions: Mapping[str, Any],
) -> BacktestRunRequest:
    params = dict(request.params)
    params["signal_selection_policy"] = _normalize_signal_selection_policy(
        params.get("signal_selection_policy"),
        default=_normalize_signal_selection_policy(
            assumptions.get("signal_selection_policy"),
            default=_default_signal_selection_policy(mode, assumptions),
        ),
    )
    params["strategy_test_mode"] = mode
    params["strategy_test_assumptions"] = dict(assumptions)
    params["risk_settings"] = _risk_settings_with_mode(
        request=request,
        mode=mode,
        assumptions=assumptions,
    )
    return request.model_copy(update={"params": params})


def _liquidity_sweep_threshold_params(request: BacktestRunRequest) -> dict[str, Any]:
    if _resolve_strategy_code(request.strategy_code) != "liquidity_sweep_reversal":
        return {}
    nested = dict(_mapping_param(request.params.get("strategy_params")))
    result: dict[str, Any] = {}
    for key in _LIQUIDITY_SWEEP_THRESHOLD_PARAM_KEYS:
        if key in request.params:
            result[key] = request.params[key]
        elif key in nested:
            result[key] = nested[key]
    return result


def _breakout_experiment_params(request: BacktestRunRequest) -> dict[str, Any]:
    if _resolve_strategy_code(request.strategy_code) != "volatility_squeeze_breakout":
        return {}
    nested = dict(_mapping_param(request.params.get("strategy_params")))
    result: dict[str, Any] = {}
    for key in _BREAKOUT_EXPERIMENT_PARAM_KEYS:
        if key in request.params:
            result[key] = request.params[key]
        elif key in nested:
            result[key] = nested[key]
    return result


def _trend_pullback_experiment_params(request: BacktestRunRequest) -> dict[str, Any]:
    if _resolve_strategy_code(request.strategy_code) != "trend_pullback_continuation":
        return {}
    nested = dict(_mapping_param(request.params.get("strategy_params")))
    result: dict[str, Any] = {}
    for key in _TREND_PULLBACK_EXPERIMENT_PARAM_KEYS:
        if key in request.params:
            result[key] = request.params[key]
        elif key in nested:
            result[key] = nested[key]
    return result


def _exit_policy_experiment_params(request: BacktestRunRequest) -> dict[str, Any]:
    nested = dict(_mapping_param(request.params.get("strategy_params")))
    result: dict[str, Any] = {}
    for key in _EXIT_POLICY_PARAM_KEYS:
        if key in request.params:
            result[key] = request.params[key]
        elif key in nested:
            result[key] = nested[key]
    return result


def _risk_settings_with_mode(
    *,
    request: BacktestRunRequest,
    mode: str,
    assumptions: Mapping[str, Any],
) -> dict[str, Any]:
    risk_settings = dict(_mapping_param(request.params.get("risk_settings")))
    if bool(assumptions.get("preserve_legacy_backtest")):
        return risk_settings

    strategy_modes = dict(_mapping_param(risk_settings.get("strategy_rr_guard_modes")))
    strategy_keys = {request.strategy_code, _resolve_strategy_code(request.strategy_code)}
    if mode in {"discovery", "research_virtual"}:
        risk_settings["rr_guard_mode"] = "soft"
        risk_settings["backtest_rr_guard_mode"] = "soft"
        for strategy_key in strategy_keys:
            strategy_modes[strategy_key] = "soft"
    elif bool(assumptions.get("rr_hard_gate_enabled", True)):
        risk_settings["backtest_rr_guard_mode"] = "hard"
        for strategy_key in strategy_keys:
            strategy_modes[strategy_key] = "hard"
    if strategy_modes:
        risk_settings["strategy_rr_guard_modes"] = strategy_modes
    return risk_settings


def _decision_for_mode(decision: RiskDecision, mode: str) -> RiskDecision:
    if mode == "production_like" or decision.can_enter:
        return decision

    warning_reason = decision.risk_check.risk_reward_warning_reason
    if warning_reason is None and decision.risk_check.risk_reward_block_reason is not None:
        warning_reason = decision.risk_check.risk_reward_block_reason
    warnings = _dedupe_strings([*decision.warnings, *decision.blockers])
    risk_check = decision.risk_check.model_copy(
        update={
            "status": "warning",
            "blockers": [],
            "warnings": _dedupe_strings([*decision.risk_check.warnings, *decision.risk_check.blockers]),
            "risk_reward_warning": decision.risk_check.risk_reward_warning
            or decision.risk_check.risk_reward_blocked,
            "risk_reward_warning_reason": warning_reason,
            "risk_reward_blocked": False,
            "risk_reward_block_reason": None,
        }
    )
    return decision.model_copy(
        update={
            "status": "warning",
            "can_enter": True,
            "blockers": [],
            "warnings": warnings,
            "risk_check": risk_check,
            "notes": _dedupe_strings([*decision.notes, *warnings]),
        }
    )


def _execution_disabled_reason(execution_policy: BacktestExecutionPolicy) -> str:
    if execution_policy.mode == "discovery":
        return "execution_disabled_for_discovery"
    return "virtual_execution_disabled"


def _backtest_signal_event_from_strategy_signal(
    *,
    request: BacktestRunRequest,
    features: Features,
    signal: StrategySignal,
    candle: OHLCVCandle,
) -> BacktestSignalEvent:
    candle_time = _datetime_from_ms(candle.close_time)
    signal_key = _strategy_signal_key(request, signal)
    synthetic_signal_id = f"bt_sig_{uuid5(NAMESPACE_DNS, signal_key).hex}"
    radar_signal = _radar_signal_from_strategy_signal(signal, candle)
    feed_kind = _signal_feed_kind(signal)
    rejection_reason_code = _signal_rejection_reason_code(signal)
    return BacktestSignalEvent(
        strategy_code=signal.strategy,
        strategy_version=request.strategy_version or "v1",
        exchange=signal.exchange or request.exchange,
        symbol=signal.symbol,
        timeframe=signal.timeframe or request.timeframe,
        direction=_normalized_direction(signal.direction),
        signal_id=None,
        synthetic_signal_id=synthetic_signal_id,
        signal_key=signal_key,
        event_time=candle_time,
        candle_time=candle_time,
        signal_score=float(signal.score) if signal.score is not None else None,
        market_regime=_regime_key(radar_signal),
        score_bucket=_score_bucket(signal.score),
        status=str(signal.status),
        gate_status=_signal_gate_status(signal),
        feed_kind=feed_kind,
        trigger_passed=_signal_trigger_passed(signal),
        trigger_reason_code=_signal_trigger_reason_code(signal),
        execution_candidate=False,
        entry_touched=False,
        filled=False,
        closed=False,
        outcome=None,
        funnel_stage="signal",
        risk_rejected=False,
        execution_rejected=False,
        no_entry=False,
        rejection_reason_code=rejection_reason_code,
        blocked_reason_code=rejection_reason_code if feed_kind == "blocked" else None,
        selected_rr=signal.selected_rr or signal.risk_reward,
        entry_min=_optional_decimal(signal.entry_min),
        entry_max=_optional_decimal(signal.entry_max),
        stop_loss=_optional_decimal(signal.stop_loss),
        features_snapshot=_features_snapshot(features, radar_signal, request=request),
        trade_plan=_trade_plan_snapshot(radar_signal),
        metadata={
            "source": "backtest_runner",
            "status_reason": signal.status_reason,
            "selection_policy": _normalize_signal_selection_policy(
                request.params.get("signal_selection_policy"),
                default="first_actionable",
            ),
            "candle_close_time": candle.close_time,
            "execution_gate": signal.execution_gate.model_dump(mode="json") if signal.execution_gate else None,
            "funnel_stages": ["signal_seen"],
        },
        tags=["backtest", "signal_event", "candle_state=closed"],
        created_at=candle_time,
    )


def _mark_signal_event_armable(event: BacktestSignalEvent) -> BacktestSignalEvent:
    return replace(
        event,
        execution_candidate=True,
        funnel_stage="armable",
        metadata=_event_metadata_with_funnel_stage(event, "armable"),
    )


def _mark_signal_event_pending_armed(
    event: BacktestSignalEvent,
    *,
    armed_index: int,
    max_wait_bars: int,
) -> BacktestSignalEvent:
    return replace(
        event,
        funnel_stage="pending_armed",
        metadata=_event_metadata_with_funnel_stage(
            event,
            "pending_armed",
            {
                "pending_entry": {
                    "armed_index": armed_index,
                    "max_wait_bars": max_wait_bars,
                }
            },
        ),
    )


def _mark_signal_event_entry_zone_touched(
    event: BacktestSignalEvent,
    *,
    candle: OHLCVCandle,
) -> BacktestSignalEvent:
    return replace(
        event,
        entry_touched=True,
        funnel_stage="entry_zone_touched",
        metadata=_event_metadata_with_funnel_stage(
            event,
            "entry_zone_touched",
            {
                "pending_entry_touch": {
                    "candle_open_time": candle.open_time,
                    "candle_close_time": candle.close_time,
                    "high": candle.high,
                    "low": candle.low,
                }
            },
        ),
    )


def _mark_signal_event_filled(
    event: BacktestSignalEvent,
    position: _SimulatedPosition,
) -> BacktestSignalEvent:
    execution = position.trade.execution
    assumptions = position.features_snapshot.get("strategy_test_assumptions")
    entry_timing = assumptions.get("entry_timing") if isinstance(assumptions, Mapping) else None
    metadata = {
        **event.metadata,
        "trade_id": position.trade.id,
        "signal_id": position.signal.id,
        "entry_time": position.trade.opened_at.isoformat(),
        "entry_timing": entry_timing,
        "execution_status": execution.status if execution is not None else position.trade.execution_status,
    }
    metadata = _event_metadata_with_funnel_stage(event, "filled", metadata)
    return replace(
        event,
        signal_id=position.signal.id,
        entry_touched=True,
        filled=True,
        outcome="open",
        funnel_stage="filled",
        features_snapshot=dict(position.features_snapshot),
        trade_plan=_trade_plan_snapshot(position.signal),
        metadata=metadata,
    )


def _mark_signal_event_rejected(
    event: BacktestSignalEvent,
    *,
    risk_rejected: bool = False,
    execution_rejected: bool = False,
    reason_code: str,
) -> BacktestSignalEvent:
    stage = "risk_rejected" if risk_rejected else "execution_rejected" if execution_rejected else "rejected"
    return replace(
        event,
        risk_rejected=risk_rejected,
        execution_rejected=execution_rejected,
        rejection_reason_code=reason_code,
        blocked_reason_code=reason_code,
        outcome="rejected",
        funnel_stage=stage,
        metadata=_event_metadata_with_funnel_stage(event, stage),
    )


def _mark_signal_event_no_entry(event: BacktestSignalEvent, reason_code: str) -> BacktestSignalEvent:
    stage = {
        "pending_entry_expired_before_touch": "expired_before_touch",
        "pending_entry_invalidated_before_touch": "invalidated_before_touch",
    }.get(reason_code, "no_entry")
    return replace(
        event,
        no_entry=True,
        outcome="no_entry",
        funnel_stage=stage,
        blocked_reason_code=reason_code,
        metadata=_event_metadata_with_funnel_stage(event, stage),
    )


def _mark_signal_event_not_selected(event: BacktestSignalEvent) -> BacktestSignalEvent:
    status = str(event.status).strip().lower()
    if status == "rejected":
        reason_code = event.rejection_reason_code or event.blocked_reason_code or "signal_rejected"
        return replace(
            event,
            outcome="rejected",
            funnel_stage="rejected",
            rejection_reason_code=reason_code,
            blocked_reason_code=reason_code,
        )
    if status == "invalidated":
        reason_code = event.blocked_reason_code or event.rejection_reason_code or "signal_invalidated"
        return replace(
            event,
            outcome="invalidated",
            funnel_stage="invalidated",
            blocked_reason_code=reason_code,
        )
    return _mark_signal_event_no_entry(event, "not_selected")


def _closed_signal_events(
    signal_events: Sequence[BacktestSignalEvent],
    closed_positions: Sequence[_SimulatedPosition],
) -> list[BacktestSignalEvent]:
    positions_by_trade_id = {position.trade.id: position for position in closed_positions}
    closed_events: list[BacktestSignalEvent] = []
    for event in signal_events:
        trade_id = event.metadata.get("trade_id")
        position = positions_by_trade_id.get(str(trade_id)) if trade_id is not None else None
        if position is None:
            closed_events.append(event)
            continue
        pnl = _net_pnl(position)
        metadata = {
            **event.metadata,
            "close_reason": position.trade.close_reason,
            "exit_time": position.trade.closed_at.isoformat() if position.trade.closed_at else None,
        }
        metadata = _event_metadata_with_funnel_stage(event, "closed", metadata)
        closed_events.append(
            replace(
                event,
                closed=True,
                outcome=_trade_outcome(position.trade, pnl),
                funnel_stage="closed",
                metadata=metadata,
            )
        )
    return closed_events


def _event_metadata_with_funnel_stage(
    event: BacktestSignalEvent,
    stage: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(event.metadata)
    stages = metadata.get("funnel_stages")
    if not isinstance(stages, list):
        stages = ["signal_seen"]
    else:
        stages = [str(item) for item in stages]
        if not stages:
            stages = ["signal_seen"]
    if not stages or stages[-1] != stage:
        stages.append(stage)
    metadata["funnel_stages"] = stages
    if extra:
        metadata.update(dict(extra))
        metadata["funnel_stages"] = stages
    return metadata


def _simulated_trades_from_state(
    state: _BacktestState,
    *,
    request: BacktestRunRequest,
) -> list[BacktestSimulatedTrade]:
    return [_simulated_trade_from_position(position, request=request) for position in state.closed_positions]


def _simulated_trade_from_position(
    position: _SimulatedPosition,
    *,
    request: BacktestRunRequest,
) -> BacktestSimulatedTrade:
    trade = position.trade
    pnl = _net_pnl(position)
    fees = trade.fees + trade.exit_fees
    return BacktestSimulatedTrade(
        trade_id=trade.id,
        strategy_code=position.strategy,
        strategy_version=request.strategy_version or "v1",
        exchange=trade.exchange,
        symbol=trade.symbol,
        timeframe=trade.timeframe,
        direction=trade.side,
        signal_score=float(position.signal.score) if position.signal.score is not None else None,
        market_regime=position.regime,
        score_bucket=_score_bucket(position.signal.score),
        entry_time=trade.opened_at,
        exit_time=trade.closed_at,
        entry_price=_decimal(trade.entry_price),
        exit_price=_optional_decimal(trade.exit_price),
        stop_loss=_optional_decimal(trade.stop_loss),
        targets=_trade_targets(trade),
        selected_rr=_selected_rr(position),
        realized_r=_realized_r(position),
        pnl=_decimal(pnl),
        pnl_pct=_pnl_pct(trade, pnl),
        fees=_decimal(fees),
        slippage=_decimal(_slippage_cost(position)),
        mfe_r=_mfe_r(position),
        mae_r=_mae_r(position),
        bars_to_entry=position.bars_to_entry,
        bars_in_trade=position.bars_in_trade,
        close_reason=trade.close_reason or "open",
        outcome=_trade_outcome(trade, pnl),
        risk_rejected=False,
        execution_rejected=False,
        warnings=_position_warnings(position),
        features_snapshot=dict(position.features_snapshot),
        trade_plan=_trade_plan_snapshot(position.signal),
        tags=[
            "backtest",
            "candle_state=closed",
            "alpha_context_available=false",
            f"entry_model={_entry_model_key(position)}",
            f"exit_policy={_exit_policy_key(position)}",
            f"first_target_source={_target_source_key(position, first=True)}",
            f"final_target_source={_target_source_key(position, first=False)}",
            f"runner_used={str(_runner_used(position)).lower()}",
            f"fallback_target_used={str(_fallback_target_used(position)).lower()}",
            f"accepted_breakout_score_bucket={_classifier_score_bucket_from_position(position, 'accepted_breakout_score')}",
            f"fakeout_risk_score_bucket={_classifier_score_bucket_from_position(position, 'fakeout_risk_score')}",
        ],
        created_at=trade.closed_at or trade.opened_at,
    )


def _optional_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value)


def _trade_targets(trade: VirtualTrade) -> list[dict[str, Any]]:
    if trade.target_states:
        return [
            {
                "label": target.label,
                "price": target.price,
                "close_percent": target.close_percent,
                "action": target.action,
                "hit": target.hit,
            }
            for target in trade.target_states
        ]
    return [{"label": f"TP{index + 1}", "price": price} for index, price in enumerate(trade.take_profit)]


def _selected_rr(position: _SimulatedPosition) -> float | None:
    execution = position.trade.execution
    if execution is not None and execution.take_profit_plan is not None:
        return execution.take_profit_plan.selected_rr
    return position.signal.selected_rr or position.signal.risk_reward


def _pnl_pct(trade: VirtualTrade, pnl: float) -> float:
    if trade.pnl_percent is not None:
        return trade.pnl_percent
    if trade.size_usd <= 0:
        return 0.0
    return pnl / trade.size_usd * 100


def _trade_outcome(trade: VirtualTrade, pnl: float) -> str:
    if trade.result is not None:
        return trade.result
    if trade.status == "open":
        return "open"
    if pnl > 0:
        return "win"
    if pnl < 0:
        return "loss"
    return "breakeven"


def _position_warnings(position: _SimulatedPosition) -> list[str]:
    execution = position.trade.execution
    execution_warnings: list[str] = []
    if execution is not None:
        execution_warnings.extend(execution.notes)
        execution_warnings.extend(execution.quality_gate.warnings)
        execution_warnings.extend(execution.quality_gate.high_impact_reasons)
        execution_warnings.extend(execution.quality_gate.blockers)
    return _dedupe_strings([*position.warnings, *execution_warnings])


def _features_snapshot(
    features: Features,
    signal: RadarSignal,
    *,
    request: BacktestRunRequest,
) -> dict[str, Any]:
    snapshot = features.model_dump(mode="json")
    snapshot["alpha_context_available"] = False
    snapshot["alpha_context_missing_sources"] = [
        "historical_trades",
        "historical_l2",
        "historical_derivative_history",
    ]
    assumptions = _mapping_param(request.params.get("strategy_test_assumptions"))
    if assumptions:
        snapshot["strategy_test_assumptions"] = dict(assumptions)
    if signal.trade_plan is not None:
        snapshot["trade_plan"] = signal.trade_plan.model_dump(mode="json")
        market_context = signal.trade_plan.metadata.get("market_context")
        if isinstance(market_context, Mapping):
            snapshot["market_context"] = dict(market_context)
    if signal.no_trade_filter is not None:
        snapshot["no_trade_filter"] = signal.no_trade_filter.model_dump(mode="json")
    return snapshot


def _trade_plan_snapshot(signal: RadarSignal) -> dict[str, Any]:
    if signal.trade_plan is None:
        return {}
    return signal.trade_plan.model_dump(mode="json")


def _score_bucket(score: int | float | None) -> str:
    if score is None:
        return "unknown"
    value = max(0, min(100, int(score)))
    if value < 50:
        return "0-49"
    if value >= 90:
        return "90-100"
    lower = value // 10 * 10
    return f"{lower}-{lower + 9}"


def _run_awaitable_sync(awaitable: Awaitable[_T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: dict[str, _T] = {}
    errors: list[BaseException] = []

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            errors.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result["value"]


def _position_constraints_from_request(request: BacktestRunRequest) -> _PositionConstraints:
    return _PositionConstraints(
        signal_selection_policy=_normalize_signal_selection_policy(
            request.params.get("signal_selection_policy"),
            default="first_actionable",
        ),
        max_concurrent_positions=max(1, _int_param(request.params, "max_concurrent_positions", 1)),
        max_positions_per_symbol=max(1, _int_param(request.params, "max_positions_per_symbol", 1)),
        cooldown_bars_after_close=max(0, _int_param(request.params, "cooldown_bars_after_close", 0)),
        allow_opposite_signal_flip=_bool_param(request.params, "allow_opposite_signal_flip", False),
    )


def _default_signal_selection_policy(mode: str, assumptions: Mapping[str, Any] | None = None) -> str:
    if assumptions is not None and bool(assumptions.get("preserve_legacy_backtest")):
        return "first_actionable"
    if mode in {"discovery", "research_virtual"}:
        return "all_non_overlapping"
    return "first_actionable"


def _normalize_signal_selection_policy(value: Any, *, default: str) -> str:
    normalized = str(value or default).strip().lower().replace("-", "_")
    if normalized in _SIGNAL_SELECTION_POLICIES:
        return normalized
    return default


def _select_signals(
    signals: Sequence[StrategySignal],
    *,
    policy: str,
    allow_pending_candidates: bool = False,
    open_positions: Sequence[_SimulatedPosition],
    recently_closed: Sequence[_SimulatedPosition],
    max_positions_per_symbol: int,
    allow_opposite_signal_flip: bool,
    cooldown_bars_after_close: int = 0,
    current_index: int | None = None,
) -> list[StrategySignal]:
    normalized_policy = _normalize_signal_selection_policy(policy, default="first_actionable")
    eligible = [
        signal
        for signal in signals
        if _is_signal_eligible_for_selection(
            signal,
            policy=normalized_policy,
            allow_pending_candidates=allow_pending_candidates,
            open_positions=open_positions,
            recently_closed=recently_closed,
            max_positions_per_symbol=max_positions_per_symbol,
            allow_opposite_signal_flip=allow_opposite_signal_flip,
            cooldown_bars_after_close=cooldown_bars_after_close,
            current_index=current_index,
        )
    ]
    if normalized_policy == "first_actionable":
        return eligible[:1]
    if normalized_policy == "highest_score":
        return [max(eligible, key=_signal_selection_score)] if eligible else []
    return eligible


def _is_signal_eligible_for_selection(
    signal: StrategySignal,
    *,
    policy: str,
    allow_pending_candidates: bool,
    open_positions: Sequence[_SimulatedPosition],
    recently_closed: Sequence[_SimulatedPosition],
    max_positions_per_symbol: int,
    allow_opposite_signal_flip: bool,
    cooldown_bars_after_close: int,
    current_index: int | None,
) -> bool:
    status = str(signal.status).strip().lower()
    pending_candidate = allow_pending_candidates and _signal_can_arm_pending(signal)
    if not is_execution_candidate_status(status) and not pending_candidate:
        return False
    if status == "confirmed":
        return False
    if _open_positions_for_symbol(signal, open_positions) >= max_positions_per_symbol:
        return False
    if policy == "all_non_overlapping" and _has_same_direction_open_position(signal, open_positions):
        return False
    if not allow_opposite_signal_flip and _has_opposite_open_position(signal, open_positions):
        return False
    return not _cooldown_blocks_signal(
        signal,
        recently_closed,
        cooldown_bars_after_close=cooldown_bars_after_close,
        current_index=current_index,
    )


def _can_open_position_for_signal(
    signal: StrategySignal,
    *,
    policy: str,
    allow_pending_candidates: bool = False,
    open_positions: Sequence[_SimulatedPosition],
    recently_closed: Sequence[_SimulatedPosition],
    max_positions_per_symbol: int,
    allow_opposite_signal_flip: bool,
    cooldown_bars_after_close: int,
    current_index: int,
) -> bool:
    return _is_signal_eligible_for_selection(
        signal,
        policy=policy,
        allow_pending_candidates=allow_pending_candidates,
        open_positions=open_positions,
        recently_closed=recently_closed,
        max_positions_per_symbol=max_positions_per_symbol,
        allow_opposite_signal_flip=allow_opposite_signal_flip,
        cooldown_bars_after_close=cooldown_bars_after_close,
        current_index=current_index,
    )


def _signal_selection_score(signal: StrategySignal) -> tuple[float, float]:
    score = float(signal.score) if signal.score is not None else float(signal.confidence or 0.0) * 100.0
    confidence = float(signal.confidence or 0.0)
    return (score, confidence)


def _signal_can_arm_pending(signal: StrategySignal) -> bool:
    gate = signal.execution_gate
    return bool(gate is not None and gate.can_arm_pending and is_waiting_entry_status(str(signal.status)))


def _open_positions_for_symbol(
    signal: StrategySignal,
    open_positions: Sequence[_SimulatedPosition],
) -> int:
    signal_key = _symbol_position_key(signal)
    return sum(1 for position in open_positions if _symbol_position_key(position) == signal_key)


def _has_same_direction_open_position(
    signal: StrategySignal,
    open_positions: Sequence[_SimulatedPosition],
) -> bool:
    signal_key = _directional_position_key(signal)
    return any(_directional_position_key(position) == signal_key for position in open_positions)


def _has_opposite_open_position(
    signal: StrategySignal,
    open_positions: Sequence[_SimulatedPosition],
) -> bool:
    signal_market = _timeframe_position_key(signal)
    signal_direction = _normalized_direction(signal.direction)
    return any(
        _timeframe_position_key(position) == signal_market
        and _normalized_direction(position.trade.side) != signal_direction
        for position in open_positions
    )


def _cooldown_blocks_signal(
    signal: StrategySignal,
    recently_closed: Sequence[_SimulatedPosition],
    *,
    cooldown_bars_after_close: int,
    current_index: int | None,
) -> bool:
    if cooldown_bars_after_close <= 0 or current_index is None:
        return False
    signal_key = _directional_position_key(signal)
    for position in recently_closed:
        if position.exit_index is None:
            continue
        if _directional_position_key(position) != signal_key:
            continue
        if current_index - position.exit_index <= cooldown_bars_after_close:
            return True
    return False


def _symbol_position_key(value: StrategySignal | _SimulatedPosition) -> tuple[str, str]:
    if isinstance(value, _SimulatedPosition):
        return (value.trade.exchange.lower(), value.trade.symbol.upper())
    return (value.exchange.lower(), value.symbol.upper())


def _timeframe_position_key(value: StrategySignal | _SimulatedPosition) -> tuple[str, str, str]:
    if isinstance(value, _SimulatedPosition):
        return (value.trade.exchange.lower(), value.trade.symbol.upper(), value.trade.timeframe)
    return (value.exchange.lower(), value.symbol.upper(), value.timeframe)


def _directional_position_key(value: StrategySignal | _SimulatedPosition) -> tuple[str, str, str, str]:
    if isinstance(value, _SimulatedPosition):
        return (*_timeframe_position_key(value), _normalized_direction(value.trade.side))
    return (*_timeframe_position_key(value), _normalized_direction(value.direction))


def _normalized_direction(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "long":
        return "long"
    if normalized == "short":
        return "short"
    if normalized == "buy":
        return "long"
    if normalized == "sell":
        return "short"
    return normalized


def _strategy_signal_key(request: BacktestRunRequest, signal: StrategySignal) -> str:
    parts = [
        signal.exchange or request.exchange,
        signal.symbol,
        signal.timeframe or request.timeframe,
        signal.strategy,
        _normalized_direction(signal.direction),
        str(signal.timestamp),
        str(signal.entry_min or ""),
        str(signal.entry_max or ""),
        str(signal.stop_loss or ""),
    ]
    return ":".join(str(part) for part in parts)


def _signal_gate_status(signal: StrategySignal) -> str:
    if signal.execution_gate is not None:
        return str(signal.execution_gate.status)
    status = str(signal.status).strip().lower()
    if status == "actionable":
        return "passed"
    if status in {"rejected", "invalidated"}:
        return "blocked"
    return "unknown"


def _signal_feed_kind(signal: StrategySignal) -> str:
    if signal.execution_gate is not None:
        return str(signal.execution_gate.feed_kind)
    status = str(signal.status).strip().lower()
    if status == "actionable":
        return "execution_signal"
    if status in {"rejected", "invalidated"}:
        return "blocked"
    return "watchlist"


def _signal_trigger_passed(signal: StrategySignal) -> bool:
    if signal.execution_gate is not None and (
        signal.execution_gate.can_enter_now or signal.execution_gate.can_arm_pending
    ):
        return True
    if signal.trigger is not None:
        return bool(signal.trigger.passed)
    return str(signal.status).strip().lower() == "actionable"


def _signal_trigger_reason_code(signal: StrategySignal) -> str | None:
    trigger = signal.trigger
    if trigger is None:
        return None
    for key in ("reason_code", "trigger_reason_code"):
        value = trigger.metadata.get(key)
        if value:
            return _reason_code(value)
    if trigger.reason:
        return _reason_code(trigger.reason)
    for check in trigger.checks:
        if check.status != "passed" and check.reason:
            return _reason_code(check.reason)
    return None


def _signal_rejection_reason_code(signal: StrategySignal) -> str | None:
    if signal.execution_gate is not None:
        for reason in [*signal.execution_gate.reasons, *signal.execution_gate.warnings]:
            if reason.code:
                return _reason_code(reason.code)
    if signal.no_trade_filter is not None:
        for blocker in [*signal.no_trade_filter.blockers, *signal.no_trade_filter.warnings]:
            if blocker:
                return _reason_code(blocker)
    if signal.status_reason:
        return _reason_code(signal.status_reason)
    return _signal_trigger_reason_code(signal)


def _last_reason_code(values: Sequence[str], default: str) -> str:
    for value in reversed(values):
        if value:
            return _reason_code(value)
    return default


def _reason_code(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    cleaned = "".join(character for character in text if character.isalnum() or character == "_")
    return cleaned[:80] or "unknown"


def _virtual_trade_from_execution(
    *,
    request: BacktestRunRequest,
    signal: RadarSignal,
    execution: VirtualExecutionReport,
    decision: RiskDecision,
    opened_at: datetime,
) -> VirtualTrade:
    entry_price = execution.average_price or execution.reference_price
    size_usd = execution.filled_size_usd
    quantity = size_usd / entry_price if entry_price > 0 else 0.0
    targets = decision.take_profit_plan.targets
    return VirtualTrade(
        id=f"bt_{uuid4().hex[:12]}",
        user_id=request.user_id,
        signal_id=signal.id,
        exchange=signal.exchange,
        symbol=signal.symbol,
        strategy=signal.strategy,
        timeframe=signal.timeframe,
        side=signal.direction,
        entry_price=entry_price,
        current_price=entry_price,
        size_usd=size_usd,
        quantity=quantity,
        leverage=decision.position_sizing.leverage,
        risk_percent=decision.checked_position_sizing.risk_per_trade_percent,
        risk_amount=decision.checked_position_sizing.risk_amount,
        risk_reward=targets[-1].r_multiple if targets else signal.risk_reward or 0.0,
        stop_loss=decision.stop_loss_plan.stop_loss_price,
        take_profit=[target.price for target in targets],
        fees=size_usd * float(request.fee_rate),
        slippage_bps=execution.entry_slippage_bps,
        simulation_mode=execution.mode,
        execution_status=execution.status,
        requested_size_usd=execution.requested_size_usd,
        filled_size_usd=execution.filled_size_usd,
        unfilled_size_usd=execution.unfilled_size_usd,
        execution=execution,
        opened_at=opened_at,
        updated_at=opened_at,
    )


def _execution_with_risk_decision(
    execution: VirtualExecutionReport,
    decision: RiskDecision,
) -> VirtualExecutionReport:
    return execution.model_copy(
        update={
            "risk_decision": decision,
            "risk_adjustment_plan": decision.risk_adjustment_plan,
            "risk_check": decision.risk_check,
            "position_sizing": decision.position_sizing,
            "stop_loss_plan": decision.stop_loss_plan,
            "take_profit_plan": decision.take_profit_plan,
            "breakeven_plan": decision.breakeven_plan,
            "trailing_stop_plan": decision.trailing_stop_plan,
            "futures_risk_plan": decision.futures_risk_plan,
            "notes": _dedupe_strings([*execution.notes, *decision.notes]),
        }
    )


def _metrics_from_state(state: _BacktestState) -> dict[str, Any]:
    positions = state.closed_positions
    trade_rs = [_realized_r(position) for position in positions]
    wins = [value for value in trade_rs if value > 0]
    losses = [value for value in trade_rs if value < 0]
    trades_count = len(positions)
    profit_sum = sum(max(_net_pnl(position), 0.0) for position in positions)
    loss_sum = abs(sum(min(_net_pnl(position), 0.0) for position in positions))
    metrics = {
        "trades_count": trades_count,
        "wins": len(wins),
        "losses": len(losses),
        "winrate": len(wins) / trades_count if trades_count else 0.0,
        "avg_win_r": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss_r": sum(losses) / len(losses) if losses else 0.0,
        "expectancy_r": sum(trade_rs) / trades_count if trades_count else 0.0,
        "profit_factor": profit_sum / loss_sum if loss_sum > 0 else None,
        "realized_pnl": sum(_net_pnl(position) for position in positions),
        "max_drawdown_pct": _max_drawdown_pct(state.equity_curve),
        "fees_total": sum(position.trade.fees for position in positions),
        "slippage_total": sum(_slippage_cost(position) for position in positions),
        "funding_total": sum(_funding_cost(position) for position in positions),
        "avg_bars_in_trade": sum(position.bars_in_trade for position in positions) / trades_count
        if trades_count
        else 0.0,
        "mfe_r_avg": sum(_mfe_r(position) for position in positions) / trades_count if trades_count else 0.0,
        "mae_r_avg": sum(_mae_r(position) for position in positions) / trades_count if trades_count else 0.0,
        "tp1_rate": _target_hit_rate(positions, "TP1"),
        "stop_rate": sum(1 for position in positions if position.trade.close_reason in _STOP_REASONS) / trades_count
        if trades_count
        else 0.0,
        "by_strategy": _group_metrics(positions, "strategy"),
        "by_regime": _group_metrics(positions, "regime"),
        "by_entry_model": _group_metrics_by_key(positions, _entry_model_key),
        "by_accepted_breakout_score_bucket": _group_metrics_by_key(
            positions,
            lambda position: _classifier_score_bucket_from_position(position, "accepted_breakout_score"),
        ),
        "by_fakeout_risk_score_bucket": _group_metrics_by_key(
            positions,
            lambda position: _classifier_score_bucket_from_position(position, "fakeout_risk_score"),
        ),
        "by_exit_policy": _group_metrics_by_key(positions, _exit_policy_key),
        "by_first_target_source": _group_metrics_by_key(
            positions,
            lambda position: _target_source_key(position, first=True),
        ),
        "by_final_target_source": _group_metrics_by_key(
            positions,
            lambda position: _target_source_key(position, first=False),
        ),
        "by_runner_used": _group_metrics_by_key(
            positions,
            lambda position: str(_runner_used(position)).lower(),
        ),
        "by_fallback_target_used": _group_metrics_by_key(
            positions,
            lambda position: str(_fallback_target_used(position)).lower(),
        ),
        "signals_seen": state.signals_seen,
        "risk_rejections": state.risk_rejections,
        "execution_rejections": state.execution_rejections,
        "trade_plan_completion_warnings": _dedupe_strings(state.trade_plan_completion_warnings),
        "risk_gate_blockers": _dedupe_strings(state.risk_gate_blockers),
        "backtest_trade_plan_assumptions": _dedupe_strings(state.backtest_trade_plan_assumptions),
    }
    return _round_metrics(metrics)


def _group_metrics(positions: Sequence[_SimulatedPosition], attribute: str) -> dict[str, dict[str, Any]]:
    return _group_metrics_by_key(positions, lambda position: str(getattr(position, attribute)))


def _group_metrics_by_key(
    positions: Sequence[_SimulatedPosition],
    key_func: Callable[[_SimulatedPosition], str],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[_SimulatedPosition]] = {}
    for position in positions:
        groups.setdefault(str(key_func(position)), []).append(position)
    result: dict[str, dict[str, Any]] = {}
    for key, group in groups.items():
        rs = [_realized_r(position) for position in group]
        wins = [value for value in rs if value > 0]
        result[key] = {
            "trades_count": len(group),
            "wins": len(wins),
            "losses": sum(1 for value in rs if value < 0),
            "winrate": len(wins) / len(group) if group else 0.0,
            "expectancy_r": sum(rs) / len(group) if group else 0.0,
            "pnl": sum(_net_pnl(position) for position in group),
        }
    return result


def _entry_model_key(position: _SimulatedPosition) -> str:
    value = _trade_plan_metadata_value(position.signal, "entry_model")
    if value is not None:
        return str(value)
    trade_plan = position.signal.trade_plan
    if trade_plan is not None and trade_plan.entry.source:
        return trade_plan.entry.source
    return "unknown"


def _exit_policy_key(position: _SimulatedPosition) -> str:
    value = _trade_plan_metadata_value(position.signal, "exit_policy")
    if value is not None:
        return str(value)
    assumptions = position.features_snapshot.get("strategy_test_assumptions")
    if isinstance(assumptions, Mapping) and assumptions.get("exit_policy") is not None:
        return str(assumptions["exit_policy"])
    if _fallback_target_used(position):
        return "legacy_r_multiple"
    if _runner_used(position):
        return "structure_runner"
    first_source = _target_source_key(position, first=True)
    if first_source == "nearest_liquidity_pool":
        return "liquidity_first"
    return "market_targets"


def _target_source_key(position: _SimulatedPosition, *, first: bool) -> str:
    trade_plan = position.signal.trade_plan
    if trade_plan is None:
        return "unknown"
    targets = [target for target in trade_plan.targets if target.price is not None]
    if not targets:
        return "unknown"
    target = targets[0] if first else targets[-1]
    if target.thesis is not None:
        return target.thesis.source
    for key in ("target_thesis_source", "market_target_source", "target_source"):
        value = target.metadata.get(key)
        if value is not None:
            return str(value)
    return str(target.source or "unknown")


def _runner_used(position: _SimulatedPosition) -> bool:
    trade_plan = position.signal.trade_plan
    if trade_plan is None:
        return False
    for target in trade_plan.targets:
        action = (target.action or "").lower()
        close_percent = str(target.close_percent or "").lower()
        if "runner" in action or close_percent == "runner":
            return True
    return False


def _fallback_target_used(position: _SimulatedPosition) -> bool:
    trade_plan = position.signal.trade_plan
    if trade_plan is None:
        return False
    if bool(trade_plan.metadata.get("fallback_targets_used")):
        return True
    for target in trade_plan.targets:
        if target.thesis is not None and target.thesis.source == "risk_multiple_fallback":
            return True
        source = str(target.source or "").lower()
        metadata_source = str(
            target.metadata.get("fallback_target_source")
            or target.metadata.get("target_source")
            or ""
        ).lower()
        if bool(target.metadata.get("fallback_target_used")):
            return True
        if "fallback" in source or "fallback" in metadata_source or metadata_source == "r_multiple":
            return True
    return False


def _classifier_score_bucket_from_position(position: _SimulatedPosition, key: str) -> str:
    return _classifier_score_bucket(_trade_plan_metadata_value(position.signal, key))


def _classifier_score_bucket(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if score < 0.25:
        return "0.00-0.24"
    if score < 0.50:
        return "0.25-0.49"
    if score < 0.75:
        return "0.50-0.74"
    return "0.75-1.00"


def _trade_plan_metadata_value(signal: RadarSignal, key: str) -> Any:
    trade_plan = signal.trade_plan
    if trade_plan is None:
        return None
    metadata_sources = [
        trade_plan.entry.metadata,
        trade_plan.metadata,
        trade_plan.risk_rules.metadata,
    ]
    if trade_plan.invalidation is not None:
        metadata_sources.append(trade_plan.invalidation.metadata)
    for metadata in metadata_sources:
        if key in metadata:
            return metadata[key]
    return None


def _target_hit_rate(positions: Sequence[_SimulatedPosition], label: str) -> float:
    if not positions:
        return 0.0
    hits = 0
    for position in positions:
        if any(target.label == label and target.hit for target in position.trade.target_states):
            hits += 1
    return hits / len(positions)


def _realized_r(position: _SimulatedPosition) -> float:
    risk_amount = position.trade.risk_amount
    if risk_amount <= 0:
        return 0.0
    return _net_pnl(position) / risk_amount


def _mfe_r(position: _SimulatedPosition) -> float:
    return position.trade.mfe / position.trade.risk_amount if position.trade.risk_amount > 0 else 0.0


def _mae_r(position: _SimulatedPosition) -> float:
    return position.trade.mae / position.trade.risk_amount if position.trade.risk_amount > 0 else 0.0


def _net_pnl(position: _SimulatedPosition) -> float:
    return (position.trade.pnl if position.trade.pnl is not None else position.trade.realized_pnl) - _funding_cost(position)


def _funding_cost(position: _SimulatedPosition) -> float:
    return max(position.funding_buffer_per_unit, 0.0) * position.trade.quantity


def _slippage_cost(position: _SimulatedPosition) -> float:
    trade = position.trade
    entry_cost = 0.0
    if trade.side == "long":
        entry_cost = max(trade.entry_price - position.reference_entry_price, 0.0) * trade.quantity
    else:
        entry_cost = max(position.reference_entry_price - trade.entry_price, 0.0) * trade.quantity
    exit_cost = 0.0
    for event in trade.lifecycle_events:
        trigger = event.metadata.get("trigger_price")
        if trigger is None or event.price is None or event.quantity is None:
            continue
        trigger_price = float(trigger)
        if trade.side == "long":
            exit_cost += max(trigger_price - event.price, 0.0) * event.quantity
        else:
            exit_cost += max(event.price - trigger_price, 0.0) * event.quantity
    return entry_cost + exit_cost


def _current_equity(state: _BacktestState) -> float:
    open_equity = sum(
        position.trade.realized_pnl + position.trade.unrealized_pnl - _funding_cost(position)
        for position in state.open_positions
    )
    return state.cash_equity + open_equity


def _open_virtual_trades(open_positions: Sequence[_SimulatedPosition]) -> list[VirtualTrade]:
    return [position.trade for position in open_positions if position.trade.status == "open"]


def _equity_point(candle: OHLCVCandle, equity: float, initial_capital: float) -> dict[str, Any]:
    return {
        "timestamp": _datetime_from_ms(candle.close_time).isoformat(),
        "equity": round(equity, 8),
        "pnl": round(equity - initial_capital, 8),
        "pnl_pct": round((equity - initial_capital) / initial_capital * 100, 8) if initial_capital else 0.0,
    }


def _max_drawdown_pct(equity_curve: Sequence[dict[str, Any]]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for point in equity_curve:
        equity = float(point.get("equity") or 0.0)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    return max_drawdown


def _round_metrics(value: Any) -> Any:
    if isinstance(value, float):
        if math.isfinite(value):
            return round(value, 8)
        return None
    if isinstance(value, dict):
        return {key: _round_metrics(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_metrics(item) for item in value]
    return value


def _radar_signal_from_strategy_signal(signal: StrategySignal, candle: OHLCVCandle) -> RadarSignal:
    now = _datetime_from_ms(candle.close_time)
    return RadarSignal(
        id=f"bt_sig_{uuid4().hex[:12]}",
        symbol=signal.symbol,
        exchange=signal.exchange,
        strategy=signal.strategy,
        direction=signal.direction.lower(),
        confidence=signal.confidence,
        risk_reward=signal.risk_reward,
        first_target_rr=signal.first_target_rr,
        final_target_rr=signal.final_target_rr,
        selected_rr=signal.selected_rr,
        selected_rr_target=signal.selected_rr_target,
        min_rr_ratio=signal.min_rr_ratio,
        urgency=signal.urgency,
        status=signal.status,
        score=signal.score,
        timeframe=signal.timeframe,
        candle_state=signal.candle_state,
        entry_min=signal.entry_min,
        entry_max=signal.entry_max,
        stop_loss=signal.stop_loss,
        take_profit_1=signal.take_profit_1,
        take_profit_2=signal.take_profit_2,
        explanation=signal.explanation,
        risks=signal.risks,
        score_breakdown=signal.score_breakdown,
        status_reason=signal.status_reason,
        quality=signal.quality,
        regime=signal.regime,
        setup=signal.setup,
        confirmation=signal.confirmation,
        invalidation=signal.invalidation,
        exit_plan=signal.exit_plan,
        trade_plan=signal.trade_plan,
        # TODO(migration-v2.2): remove this legacy signal.auto_entry compatibility
        # projection after backtest execution no longer depends on RadarSignal.
        auto_entry=signal.auto_entry,
        no_trade_filter=signal.no_trade_filter,
        created_at=now,
        updated_at=now,
    )


def _entry_price(signal: StrategySignal) -> float | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    return signal.entry_max


def _backtest_execution_policy_decision(
    *,
    request: BacktestRunRequest,
    risk_settings: RiskManagementSettings,
    signal: StrategySignal,
    features: Features,
    current_price: float | None,
    confirm_request: ManualConfirmRequest,
    risk_decision: RiskDecision,
):
    policy = _mapping_param(request.params.get("execution_policy"))
    return execution_policy_resolver.resolve(
        ExecutionPolicyContext(
            side="short" if signal.direction.lower() == "short" else "long",
            current_price=features.close if current_price is None else current_price,
            entry_min=signal.entry_min,
            entry_max=signal.entry_max,
            stop_loss=signal.stop_loss,
            take_profit=_strategy_signal_take_profit(signal),
            min_rr_ratio=float(signal.min_rr_ratio or risk_settings.min_rr_ratio or 0.0),
            preferred_mode=_execution_policy_mode(policy.get("mode") or policy.get("preferred_mode")),
            allow_pending_retest=_bool_param(policy, "allow_pending_retest", False),
            allow_probe=_bool_param(policy, "allow_probe", False),
            max_late_entry_deviation_bps=_float_param(policy, "max_late_entry_deviation_bps", 100.0) or 100.0,
            max_probe_deviation_bps=_float_param(policy, "max_probe_deviation_bps", 10.0) or 10.0,
            slippage_bps=float(request.slippage_bps),
            max_slippage_bps=confirm_request.max_virtual_slippage_bps,
            spread_bps=_float_param(request.params, "spread_bps", None),
            max_spread_bps=_float_param(policy, "max_spread_bps", risk_settings.max_spread_bps)
            or risk_settings.max_spread_bps,
            orderbook_depth_usd=_float_param(request.params, "orderbook_depth_usd", None),
            requested_size_usd=risk_decision.checked_position_sizing.notional,
            min_depth_to_size_ratio=_float_param(policy, "min_depth_to_size_ratio", 1.0) or 1.0,
        )
    )


def _strategy_signal_take_profit(signal: StrategySignal) -> float | None:
    return signal.take_profit_1 or signal.take_profit_2


def _execution_policy_mode(value: Any) -> Any | None:
    return value if value in {"limit", "market", "pending_retest", "late_entry", "probe", "skip"} else None


def _replace_position(
    position: _SimulatedPosition,
    *,
    trade: VirtualTrade | None = None,
    bars_in_trade: int | None = None,
    exit_index: int | None = None,
) -> _SimulatedPosition:
    return _SimulatedPosition(
        trade=trade or position.trade,
        signal=position.signal,
        entry_index=position.entry_index,
        reference_entry_price=position.reference_entry_price,
        bars_to_entry=position.bars_to_entry,
        exit_index=position.exit_index if exit_index is None else exit_index,
        funding_buffer_per_unit=position.funding_buffer_per_unit,
        bars_in_trade=position.bars_in_trade if bars_in_trade is None else bars_in_trade,
        strategy=position.strategy,
        regime=position.regime,
        features_snapshot=dict(position.features_snapshot),
        warnings=list(position.warnings),
    )


def _resolve_strategy_code(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return _STRATEGY_ALIASES.get(normalized, normalized)


def _strategy_params_from_request(request: BacktestRunRequest) -> dict[str, Any]:
    params = dict(_mapping_param(request.params.get("strategy_params")))
    for key, value in request.params.items():
        if key not in _RESERVED_PARAM_KEYS:
            params.setdefault(key, value)
    return params


def _risk_settings_params_from_request(request: BacktestRunRequest) -> dict[str, Any]:
    values = dict(_mapping_param(request.params.get("risk_settings")))
    for key in RiskManagementSettings.model_fields:
        if key in request.params:
            values[key] = request.params[key]
    return values


def _risk_settings_from_request(request: BacktestRunRequest) -> RiskManagementSettings:
    values = RiskManagementSettings().model_dump()
    updates = _risk_settings_params_from_request(request)
    if updates:
        values["risk_profile"] = updates.get("risk_profile") or "custom"
        values.update(updates)
    return RiskManagementSettings.model_validate(values)


def _mapping_param(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_param(params: Mapping[str, Any], key: str, default: int) -> int:
    try:
        value = params.get(key)
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _bool_param(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _optional_bool_param(params: Mapping[str, Any], key: str) -> bool | None:
    if key not in params or params.get(key) is None:
        return None
    return _bool_param(params, key, False)


def _float_param(params: Mapping[str, Any], key: str, default: float | None) -> float | None:
    try:
        value = params.get(key)
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _result_user_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        return uuid5(NAMESPACE_DNS, f"crypto-radar-backtest:{value}")


def _regime_key(signal: RadarSignal) -> str:
    regime = signal.regime
    if regime is None:
        return "unknown"
    return f"{regime.direction}:{regime.strength}:{regime.alignment}"


def _trade_plan_time_stop_metadata(signal: RadarSignal) -> dict[str, Any] | None:
    trade_plan = signal.trade_plan
    if trade_plan is None:
        return None
    metadata: dict[str, Any] = {}
    sources = [trade_plan.metadata, trade_plan.risk_rules.metadata]
    if trade_plan.invalidation is not None:
        sources.append(trade_plan.invalidation.metadata)
    for source in sources:
        if not source:
            continue
        for key in ("time_stop", "time_stop_at", "expires_at", "at", "max_holding_seconds"):
            if source.get(key) is not None:
                metadata[key] = source[key]
    return metadata or None


def _datetime_from_ms(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def _raise_if_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise BacktestRunCancelled("backtest_run_cancelled")


def _emit_backtest_progress(
    on_progress: Callable[[dict[str, Any]], None] | None,
    *,
    phase: str,
    bars_processed: int,
    bars_total: int,
    signals_seen: int,
    trades_count: int,
    risk_rejections: int,
    execution_rejections: int,
    pending_entries_count: int = 0,
    execution_candidates: int = 0,
    pending_armed: int = 0,
    entry_touched: int = 0,
    filled: int = 0,
    closed: int = 0,
    no_entry: int = 0,
    not_selected: int = 0,
    started_at: float | None = None,
) -> None:
    if on_progress is None:
        return
    elapsed_ms = _round_ms(_elapsed_ms(started_at)) if started_at is not None else 0.0
    elapsed_seconds = elapsed_ms / 1000 if elapsed_ms > 0 else 0.0
    bars_per_second = bars_processed / elapsed_seconds if elapsed_seconds > 0 else 0.0
    remaining_bars = max(0, bars_total - bars_processed)
    eta_seconds = round(remaining_bars / bars_per_second, 3) if bars_per_second > 0 else None
    bars_pct = round((bars_processed / bars_total) * 100, 2) if bars_total > 0 else 0.0
    on_progress(
        {
            "phase": phase,
            "bars_processed": bars_processed,
            "bars_total": bars_total,
            "bars_pct": bars_pct,
            "pending_entries_count": pending_entries_count,
            "signals_seen": signals_seen,
            "signals_count": signals_seen,
            "execution_candidates": execution_candidates,
            "pending_armed": pending_armed,
            "entry_touched": entry_touched,
            "touched": entry_touched,
            "filled": filled,
            "closed": closed,
            "no_entry": no_entry,
            "not_selected": not_selected,
            "trades_count": trades_count,
            "risk_rejections": risk_rejections,
            "execution_rejections": execution_rejections,
            "elapsed_ms": elapsed_ms,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "bars_per_second": round(bars_per_second, 8),
            "eta_seconds": eta_seconds,
        }
    )


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 8)))


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
