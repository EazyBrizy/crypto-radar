from __future__ import annotations

import asyncio
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Mapping, Sequence, TypeVar
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from app.schemas.backtest import BacktestResultResponse, BacktestRunRequest, BacktestRunResult
from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features
from app.schemas.risk import RiskDecision
from app.schemas.signal import RadarSignal, StrategySignal
from app.schemas.trade import ManualConfirmRequest, VirtualAccount, VirtualExecutionReport, VirtualTrade
from app.schemas.user import RiskManagementSettings
from app.services.feature_engine import FeatureEngine
from app.services.historical_candle_provider import ClickHouseHistoricalCandleProvider, HistoricalCandleProvider
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.virtual_trade_lifecycle import (
    apply_virtual_trade_market_price,
    arm_virtual_trade_time_stop,
    close_virtual_trade_lifecycle,
    initialize_virtual_trade_lifecycle,
)
from app.services.virtual_trading.execution_engine import VirtualExecutionEngine
from app.strategies.engine import StrategyEngine
from app.strategies.pipeline import StrategySignalPipeline

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
    funding_buffer_per_unit: float = 0.0
    bars_in_trade: int = 0
    strategy: str = "unknown"
    regime: str = "unknown"


@dataclass
class _BacktestState:
    cash_equity: float
    open_position: _SimulatedPosition | None = None
    closed_positions: list[_SimulatedPosition] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    signals_seen: int = 0
    risk_rejections: int = 0
    execution_rejections: int = 0


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
        working = trade
        if _stop_touched(working, candle):
            stop_price = working.current_stop_loss or working.stop_loss
            result = apply_virtual_trade_market_price(working, stop_price, now)
            return _replace_position(
                position,
                trade=result.trade,
                bars_in_trade=position.bars_in_trade + 1,
            )

        if working.side == "long":
            working = apply_virtual_trade_market_price(working, candle.low, now).trade
            if working.status == "open":
                working = apply_virtual_trade_market_price(working, candle.high, now).trade
        else:
            working = apply_virtual_trade_market_price(working, candle.high, now).trade
            if working.status == "open":
                working = apply_virtual_trade_market_price(working, candle.low, now).trade
        if working.status == "open":
            working = apply_virtual_trade_market_price(working, candle.close, now).trade
        return _replace_position(
            position,
            trade=working,
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
        return _run_awaitable_sync(self._run_async(request))

    async def _run_async(self, request: BacktestRunRequest) -> BacktestRunResult:
        candles = await self._historical_candle_provider.load_candles(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_at=request.start_at,
            end_at=request.end_at,
        )
        candles = sorted(
            [candle.model_copy(update={"is_closed": True}) for candle in candles],
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
        state = _BacktestState(cash_equity=float(request.initial_capital))
        state.equity_curve.append(
            _equity_point(candles[warmup - 1], float(request.initial_capital), float(request.initial_capital))
        )

        for index in range(warmup, len(candles)):
            candle = candles[index]
            if state.open_position is not None:
                state.open_position = self._execution_simulator.apply_candle(state.open_position, candle)
                if state.open_position.trade.status == "closed":
                    state.cash_equity += _net_pnl(state.open_position)
                    state.closed_positions.append(state.open_position)
                    state.open_position = None

            features = self._feature_engine.process_candles(
                candles[max(0, index - rolling_window + 1) : index + 1]
            )
            if features is not None:
                signals = await self._generate_signals(request, features)
                state.signals_seen += len(signals)
                if state.open_position is None:
                    position = self._try_open_position(
                        request=request,
                        risk_settings=risk_settings,
                        features=features,
                        signal=_first_actionable_signal(signals),
                        candle=candle,
                        index=index,
                        state=state,
                    )
                    if position is not None:
                        state.open_position = position

            state.equity_curve.append(_equity_point(candle, _current_equity(state), float(request.initial_capital)))

        if state.open_position is not None:
            state.open_position = self._execution_simulator.close_at_end(state.open_position, candles[-1])
            state.cash_equity += _net_pnl(state.open_position)
            state.closed_positions.append(state.open_position)
            state.open_position = None
            state.equity_curve.append(
                _equity_point(candles[-1], state.cash_equity, float(request.initial_capital))
            )

        metrics = _metrics_from_state(state)
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
        return BacktestRunResult(status="completed", result=result)

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
        return await self._strategy_engine.generate_signals(
            features,
            strategy_configs={strategy_code: runtime_config},
        )

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
    ) -> _SimulatedPosition | None:
        if signal is None:
            return None
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
        account = VirtualAccount(
            user_id=request.user_id,
            starting_balance=float(request.initial_capital),
            balance=state.cash_equity,
            equity=state.cash_equity,
            realized_pnl=state.cash_equity - float(request.initial_capital),
            unrealized_pnl=0.0,
            risk_per_trade=state.cash_equity * risk_settings.risk_per_trade_percent / 100,
            risk_reward=risk_settings.min_rr_ratio,
            updated_at=_datetime_from_ms(candle.close_time),
        )
        try:
            pre_execution_decision = self._risk_gate_service.evaluate(
                context=self._risk_context_service.build_virtual_context(
                    signal=radar_signal,
                    request=confirm_request,
                    account=account,
                    entry_price=entry_price,
                    open_positions=[],
                    requested_notional=confirm_request.size_usd,
                    stage="pre_execution",
                    signal_stop_loss_price=signal.stop_loss,
                    atr_value=features.atr_14,
                    funding_buffer_per_unit=_float_param(request.params, "funding_buffer_per_unit", 0.0) or 0.0,
                    spread_percent=_float_param(request.params, "spread_percent", None),
                    spread_bps=_float_param(request.params, "spread_bps", None),
                    orderbook_depth_usd=_float_param(request.params, "orderbook_depth_usd", None),
                    market_data_status=str(request.params.get("market_data_status") or "unknown"),
                ),
                risk_settings=risk_settings,
            )
        except ValueError:
            state.risk_rejections += 1
            return None
        if not pre_execution_decision.can_enter:
            state.risk_rejections += 1
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
                    open_positions=[],
                    requested_notional=filled_size_usd,
                    stage="post_execution",
                    signal_stop_loss_price=signal.stop_loss,
                    atr_value=features.atr_14,
                    funding_buffer_per_unit=_float_param(request.params, "funding_buffer_per_unit", 0.0) or 0.0,
                    spread_percent=_float_param(request.params, "spread_percent", None),
                    spread_bps=_float_param(request.params, "spread_bps", None),
                    orderbook_depth_usd=_float_param(request.params, "orderbook_depth_usd", None),
                    market_data_status=str(request.params.get("market_data_status") or "unknown"),
                ),
                risk_settings=risk_settings,
            )
        except ValueError:
            state.risk_rejections += 1
            return None
        if not post_execution_decision.can_enter:
            state.risk_rejections += 1
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
        )


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


def _first_actionable_signal(signals: Sequence[StrategySignal]) -> StrategySignal | None:
    for signal in signals:
        if signal.status == "actionable":
            return signal
    return None


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
        "signals_seen": state.signals_seen,
        "risk_rejections": state.risk_rejections,
        "execution_rejections": state.execution_rejections,
    }
    return _round_metrics(metrics)


def _group_metrics(positions: Sequence[_SimulatedPosition], attribute: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[_SimulatedPosition]] = {}
    for position in positions:
        groups.setdefault(str(getattr(position, attribute)), []).append(position)
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
    if state.open_position is None:
        return state.cash_equity
    trade = state.open_position.trade
    return state.cash_equity + trade.realized_pnl + trade.unrealized_pnl - _funding_cost(state.open_position)


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


def _stop_touched(trade: VirtualTrade, candle: OHLCVCandle) -> bool:
    stop = trade.current_stop_loss or trade.stop_loss
    if trade.side == "long":
        return candle.low <= stop
    return candle.high >= stop


def _replace_position(
    position: _SimulatedPosition,
    *,
    trade: VirtualTrade | None = None,
    bars_in_trade: int | None = None,
) -> _SimulatedPosition:
    return _SimulatedPosition(
        trade=trade or position.trade,
        signal=position.signal,
        entry_index=position.entry_index,
        reference_entry_price=position.reference_entry_price,
        funding_buffer_per_unit=position.funding_buffer_per_unit,
        bars_in_trade=position.bars_in_trade if bars_in_trade is None else bars_in_trade,
        strategy=position.strategy,
        regime=position.regime,
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
