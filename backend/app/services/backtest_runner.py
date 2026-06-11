from __future__ import annotations

import asyncio
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping, Sequence, TypeVar
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

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
from app.services.feature_engine import FeatureEngine
from app.services.historical_candle_provider import ClickHouseHistoricalCandleProvider, HistoricalCandleProvider
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.risk_reward_assessment import RiskRewardAssessmentService
from app.services.trade_plan_completeness import trade_plan_completeness_service
from app.services.trade_plan_enrichment import TradePlanEnrichmentService
from app.services.virtual_trade_lifecycle import (
    apply_virtual_trade_candle,
    arm_virtual_trade_time_stop,
    close_virtual_trade_lifecycle,
    initialize_virtual_trade_lifecycle,
)
from app.services.virtual_trading.execution_engine import VirtualExecutionEngine
from app.strategies.engine import StrategyEngine
from app.strategies.pipeline import (
    ExitManagementLayer,
    InvalidationLayer,
    StrategyEvaluationContext,
    StrategySignalPipeline,
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
    risk_rejections: int = 0
    execution_rejections: int = 0
    trade_plan_completion_warnings: list[str] = field(default_factory=list)
    risk_gate_blockers: list[str] = field(default_factory=list)
    backtest_trade_plan_assumptions: list[str] = field(default_factory=list)

    @property
    def open_position(self) -> _SimulatedPosition | None:
        return self.open_positions[0] if self.open_positions else None

    @open_position.setter
    def open_position(self, position: _SimulatedPosition | None) -> None:
        self.open_positions = [] if position is None else [position]


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
    preserve_legacy_backtest: bool = False


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
class BacktestDetailedRunResult:
    run_result: BacktestRunResult
    trades: list[BacktestSimulatedTrade]
    signals_seen: int
    risk_rejections: int
    execution_rejections: int
    assumptions: dict[str, Any]


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
        result = apply_virtual_trade_candle(
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
        result = close_virtual_trade_lifecycle(
            position.trade,
            candle.close,
            "time_stop",
            _datetime_from_ms(candle.close_time),
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
        self._historical_candle_provider = historical_candle_provider or ClickHouseHistoricalCandleProvider()
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
    ) -> BacktestDetailedRunResult:
        return _run_awaitable_sync(self._run_detailed_async(request, mode=mode, options=options))

    async def _run_async(self, request: BacktestRunRequest) -> BacktestRunResult:
        return (
            await self._run_detailed_async(
                request,
                mode="production_like",
                options={"preserve_legacy_backtest": True},
            )
        ).run_result

    async def _run_detailed_async(
        self,
        request: BacktestRunRequest,
        *,
        mode: str,
        options: dict[str, Any] | None,
    ) -> BacktestDetailedRunResult:
        normalized_mode = _normalize_backtest_mode(mode)
        assumptions = _assumptions_for_backtest(request, normalized_mode, options)
        execution_policy = _execution_policy_for_backtest(normalized_mode, assumptions)
        request = _request_with_mode_options(request, normalized_mode, assumptions)
        loaded_candles = await self._historical_candle_provider.load_candles(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_at=request.start_at,
            end_at=request.end_at,
        )
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

        for index in range(warmup, len(candles)):
            candle = candles[index]
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

            features = self._feature_engine.process_candles(
                candles[max(0, index - rolling_window + 1) : index + 1]
            )
            if features is not None and features.candle_state != "closed":
                raise AssertionError("backtest_open_candle_detected: feature window produced an open candle")
            if features is not None and len(state.open_positions) < constraints.max_concurrent_positions:
                signals = await self._generate_signals(request, features)
                state.signals_seen += len(signals)
                selected_signals = _select_signals(
                    signals,
                    policy=constraints.signal_selection_policy,
                    open_positions=state.open_positions,
                    recently_closed=state.closed_positions,
                    max_positions_per_symbol=constraints.max_positions_per_symbol,
                    allow_opposite_signal_flip=constraints.allow_opposite_signal_flip,
                    cooldown_bars_after_close=constraints.cooldown_bars_after_close,
                    current_index=index,
                )
                for signal in selected_signals:
                    if len(state.open_positions) >= constraints.max_concurrent_positions:
                        break
                    if not _can_open_position_for_signal(
                        signal,
                        policy=constraints.signal_selection_policy,
                        open_positions=state.open_positions,
                        recently_closed=state.closed_positions,
                        max_positions_per_symbol=constraints.max_positions_per_symbol,
                        allow_opposite_signal_flip=constraints.allow_opposite_signal_flip,
                        cooldown_bars_after_close=constraints.cooldown_bars_after_close,
                        current_index=index,
                    ):
                        state.risk_rejections += 1
                        continue
                    position = self._try_open_position(
                        request=request,
                        risk_settings=risk_settings,
                        features=features,
                        signal=signal,
                        candle=candle,
                        index=index,
                        state=state,
                        execution_policy=execution_policy,
                    )
                    if position is not None:
                        state.open_positions.append(position)

            state.equity_curve.append(_equity_point(candle, _current_equity(state), float(request.initial_capital)))

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

        metrics = _metrics_from_state(state)
        assumptions = _assumptions_with_runtime_diagnostics(assumptions, state)
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
        )

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

    def _try_open_position(
        self,
        *,
        request: BacktestRunRequest,
        risk_settings: RiskManagementSettings,
        features: Features,
        signal: StrategySignal | None,
        candle: OHLCVCandle,
        index: int,
        state: _BacktestState,
        execution_policy: BacktestExecutionPolicy,
    ) -> _SimulatedPosition | None:
        if signal is None:
            return None
        signal = _normalize_signal_for_backtest(
            signal=signal,
            features=features,
            request=request,
            execution_policy=execution_policy,
            state=state,
        )
        radar_signal = _radar_signal_from_strategy_signal(signal, candle)
        entry_price = _entry_price(signal) or features.close
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
            updated_at=_datetime_from_ms(candle.close_time),
        )
        try:
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
            state.risk_rejections += 1
            state.risk_gate_blockers.append(str(exc))
            return None
        pre_execution_decision = _decision_for_mode(pre_execution_decision, execution_policy.mode)
        if not pre_execution_decision.can_enter:
            state.risk_rejections += 1
            state.risk_gate_blockers.extend(pre_execution_decision.blockers)
            return None

        execution = self._execution_simulator.simulate_entry(
            signal=radar_signal,
            request=confirm_request,
            risk_decision=pre_execution_decision,
            reference_price=entry_price,
        )
        if execution.status == "rejected_virtual_execution" or execution.average_price is None:
            state.execution_rejections += 1
            return None

        filled_size_usd = execution.filled_size_usd
        if filled_size_usd <= 0:
            state.execution_rejections += 1
            return None
        filled_entry = execution.average_price
        try:
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
            state.risk_rejections += 1
            state.risk_gate_blockers.append(str(exc))
            return None
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
            opened_at=_datetime_from_ms(candle.close_time),
        )
        trade = arm_virtual_trade_time_stop(
            initialize_virtual_trade_lifecycle(trade),
            _trade_plan_time_stop_metadata(radar_signal),
            _datetime_from_ms(candle.close_time),
        )
        return _SimulatedPosition(
            trade=trade,
            signal=radar_signal,
            entry_index=index,
            reference_entry_price=entry_price,
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
        preserve_legacy_backtest=bool(assumptions.get("preserve_legacy_backtest")),
    )


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
    context = StrategyEvaluationContext(
        signal_features=features,
        strategy_params=strategy_params,
        pipeline_settings=pipeline_settings,
        rr_guard_context="backtest",
    )
    risk_reward = RiskRewardAssessmentService().assess(
        signal,
        pipeline_settings,
        rr_guard_context="backtest",
    )
    invalidation = InvalidationLayer().build(signal, context)
    exit_plan = ExitManagementLayer().build(signal, context)
    trade_plan = trade_plan_enrichment.enrich(
        signal=signal,
        exit_plan=exit_plan,
        invalidation=invalidation,
        risk_reward=risk_reward,
    )
    trade_plan = _trade_plan_with_executable_backtest_rr_target(trade_plan)
    trade_plan = _trade_plan_with_explicit_backtest_targets(trade_plan, state=state)
    trade_plan = _trade_plan_with_backtest_assumption_metadata(
        trade_plan,
        state=state,
        execution_policy=execution_policy,
    )
    completeness = trade_plan_completeness_service.assess(
        signal,
        trade_plan,
        settings=pipeline_settings,
        context={"backtest_features": features, "backtest_request": request},
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


def _assumptions_with_runtime_diagnostics(
    assumptions: Mapping[str, Any],
    state: _BacktestState,
) -> dict[str, Any]:
    values = dict(assumptions)
    values["trade_plan_completion_warnings"] = _dedupe_strings(state.trade_plan_completion_warnings)
    values["risk_gate_blockers"] = _dedupe_strings(state.risk_gate_blockers)
    values["backtest_trade_plan_assumptions"] = _dedupe_strings(state.backtest_trade_plan_assumptions)
    return values


def _assumptions_for_backtest(
    request: BacktestRunRequest,
    mode: str,
    options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    values = dict(options or {})
    values.setdefault("mode", mode)
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
        preserve_legacy = bool(values.get("preserve_legacy_backtest"))
        values.setdefault("risk_gate_enabled", True)
        values.setdefault("rr_hard_gate_enabled", False if preserve_legacy else True)
        values.setdefault("virtual_execution_enabled", True)
        values.setdefault("lifecycle_enabled", True)
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
        bars_to_entry=0,
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
    open_positions: Sequence[_SimulatedPosition],
    recently_closed: Sequence[_SimulatedPosition],
    max_positions_per_symbol: int,
    allow_opposite_signal_flip: bool,
    cooldown_bars_after_close: int,
    current_index: int | None,
) -> bool:
    if signal.status != "actionable":
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
