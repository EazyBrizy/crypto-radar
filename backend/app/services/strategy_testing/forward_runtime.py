from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.schemas.market import MarketData
from app.schemas.risk import ResolvedExecutionProfile
from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot, StrategySignal
from app.schemas.trade import ManualConfirmRequest, VirtualTrade
from app.services.pending_entry import pending_entry_service
from app.services.signal_execution_gate import SignalExecutionGateService, signal_execution_gate_service
from app.services.signal_service import signal_service
from app.services.strategy_performance_service import score_bucket_for
from app.services.strategy_testing.runner import strategy_test_user_uuid
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTrade,
)
from app.services.strategy_testing.stores import ClickHouseStrategyTestStore, PostgresStrategyTestRunStore
from app.services.virtual_trading import virtual_trading_service


class ForwardRunStore(Protocol):
    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        ...

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        ...

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        ...


class ForwardTradeStore(Protocol):
    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        ...

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        ...


class ForwardSignalWriter(Protocol):
    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> tuple[RadarSignal, bool]:
        ...


class ForwardVirtualTrading(Protocol):
    def open_virtual_trade(self, signal: RadarSignal, request: ManualConfirmRequest) -> VirtualTrade:
        ...


class ForwardPendingEntryService(Protocol):
    def arm_from_signal(
        self,
        *,
        user_id: str | UUID,
        signal_id: str | UUID,
        mode: str,
        request: ManualConfirmRequest | dict[str, Any],
        execution_profile: ResolvedExecutionProfile,
    ) -> Any:
        ...


class ForwardScanner(Protocol):
    def process_tick(self, tick: MarketData) -> Any:
        ...


@dataclass
class ForwardRuntimeResult:
    ticks_processed: int = 0
    signals_processed: int = 0
    signals_skipped: int = 0
    opened_trades: int = 0
    pending_entries_armed: int = 0
    trades_written: int = 0
    metrics_written: int = 0
    runtime_state_updates: int = 0
    cancelled_runs: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "ForwardRuntimeResult") -> None:
        self.ticks_processed += other.ticks_processed
        self.signals_processed += other.signals_processed
        self.signals_skipped += other.signals_skipped
        self.opened_trades += other.opened_trades
        self.pending_entries_armed += other.pending_entries_armed
        self.trades_written += other.trades_written
        self.metrics_written += other.metrics_written
        self.runtime_state_updates += other.runtime_state_updates
        self.cancelled_runs += other.cancelled_runs
        self.errors.extend(other.errors)


class ForwardStrategyTestRuntime:
    def __init__(
        self,
        *,
        run_store: ForwardRunStore | None = None,
        trade_store: ForwardTradeStore | None = None,
        signal_writer: ForwardSignalWriter | None = None,
        virtual_trading: ForwardVirtualTrading | None = None,
        pending_entries: ForwardPendingEntryService | None = None,
        execution_gate: SignalExecutionGateService | None = None,
        scanner: ForwardScanner | None = None,
    ) -> None:
        self._run_store = run_store or PostgresStrategyTestRunStore()
        self._trade_store = trade_store or ClickHouseStrategyTestStore()
        self._signal_writer = signal_writer or signal_service
        self._virtual_trading = virtual_trading or virtual_trading_service
        self._pending_entries = pending_entries or pending_entry_service
        self._execution_gate = execution_gate or signal_execution_gate_service
        self._scanner = scanner

    def start_run(
        self,
        run_id: UUID,
        request: StrategyTestRunRequest,
    ) -> StrategyTestRunDetailResponse:
        detail = self._run_store.mark_running(run_id)
        return self._run_store.update_runtime_state(
            run_id,
            {
                "status": "listening",
                "test_type": request.test_type,
                "processed_ticks": _counter(detail.run.runtime_state, "processed_ticks"),
                "processed_signals": _counter(detail.run.runtime_state, "processed_signals"),
                "opened_trades": _counter(detail.run.runtime_state, "opened_trades"),
                "pending_entries_armed": _counter(detail.run.runtime_state, "pending_entries_armed"),
                "trades_written": _counter(detail.run.runtime_state, "trades_written"),
                "metrics_written": _counter(detail.run.runtime_state, "metrics_written"),
                "last_error": None,
            },
        )

    def heartbeat_active_runs(self) -> ForwardRuntimeResult:
        result = ForwardRuntimeResult()
        result.cancelled_runs += self._cancel_stopping_runs()
        for run in self._running_forward_runs():
            self._run_store.update_runtime_state(
                run.run_id,
                {
                    "status": "listening",
                    "last_heartbeat_reason": "forward_runtime_worker",
                    "last_processed_at": _now_iso(),
                },
            )
            result.runtime_state_updates += 1
        return result

    async def process_market_tick(self, tick: MarketData) -> ForwardRuntimeResult:
        result = ForwardRuntimeResult(ticks_processed=1)
        result.cancelled_runs += self._cancel_stopping_runs()
        for run in self._running_forward_runs():
            if not _run_matches_market(run, tick.exchange, tick.symbol):
                continue
            self._increment_runtime_state(
                run,
                {
                    "processed_ticks": 1,
                    "last_exchange": tick.exchange.lower(),
                    "last_symbol": tick.symbol.upper(),
                    "last_price": tick.price,
                    "last_tick_timestamp": tick.timestamp,
                },
            )
            result.runtime_state_updates += 1

        if self._scanner is None:
            return result
        signals = self._scanner.process_tick(tick)
        if inspect.isawaitable(signals):
            signals = await signals
        for signal in list(signals or []):
            result.merge(await self.process_strategy_signal(signal))
        return result

    async def process_strategy_signal(self, signal: StrategySignal) -> ForwardRuntimeResult:
        result = ForwardRuntimeResult()
        result.cancelled_runs += self._cancel_stopping_runs()
        runs = [run for run in self._running_forward_runs() if _run_matches_signal(run, signal)]
        if not runs:
            result.signals_skipped = 1
            return result

        for run in runs:
            try:
                radar_signal, _ = self._signal_writer.upsert_strategy_signal(
                    signal,
                    exchange=signal.exchange,
                    explanation=list(signal.explanation),
                )
                gate = radar_signal.execution_gate or self._execution_gate.evaluate(radar_signal)
                result.signals_processed += 1
                if gate.can_enter_now:
                    opened = self._open_virtual_trade(run, radar_signal)
                    result.opened_trades += 1
                    result.trades_written += self._write_trade(run, radar_signal, opened)
                    result.metrics_written += self._write_metric(run, radar_signal, opened)
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "opened_trades": 1,
                            "trades_written": 1,
                            "metrics_written": 1,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                            "last_trade_id": opened.id,
                        },
                    )
                elif gate.can_arm_pending:
                    self._arm_pending_entry(run, radar_signal, gate)
                    result.pending_entries_armed += 1
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "pending_entries_armed": 1,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                        },
                    )
                else:
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                        },
                    )
                result.runtime_state_updates += 1
            except Exception as exc:
                message = str(exc)
                result.errors.append(message)
                self._run_store.update_runtime_state(
                    run.run_id,
                    {
                        "status": "degraded",
                        "last_error": message,
                        "last_processed_at": _now_iso(),
                    },
                )
                result.runtime_state_updates += 1
        return result

    def _running_forward_runs(self) -> list[StrategyTestRunResponse]:
        return _forward_runs(self._run_store.list_runs(user_id=None, limit=500, status="running"))

    def _cancel_stopping_runs(self) -> int:
        cancelled = 0
        for run in _forward_runs(self._run_store.list_runs(user_id=None, limit=500, status="stopping")):
            self._run_store.update_runtime_state(
                run.run_id,
                {
                    "status": "cancelled",
                    "cancelled_reason": "forward_runtime_stopping",
                    "last_processed_at": _now_iso(),
                },
            )
            self._run_store.mark_cancelled(run.run_id)
            cancelled += 1
        return cancelled

    def _open_virtual_trade(self, run: StrategyTestRunResponse, signal: RadarSignal) -> VirtualTrade:
        return self._virtual_trading.open_virtual_trade(
            signal,
            _manual_confirm_request(run),
        )

    def _arm_pending_entry(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        gate: SignalExecutionGateSnapshot,
    ) -> Any:
        return self._pending_entries.arm_from_signal(
            user_id=_matrix_user_id(run),
            signal_id=signal.id,
            mode="virtual",
            request=_manual_confirm_request(run, auto_enter_on_confirmation=True),
            execution_profile=_execution_profile_from_run(run, gate),
        )

    def _write_trade(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        trade: VirtualTrade,
    ) -> int:
        row = _strategy_test_trade_from_virtual_trade(run=run, signal=signal, trade=trade)
        self._trade_store.write_trades([row])
        return 1

    def _write_metric(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        trade: VirtualTrade,
    ) -> int:
        self._trade_store.write_metrics(
            [_strategy_test_metric_from_virtual_trade(run=run, signal=signal, trade=trade)]
        )
        return 1

    def _increment_runtime_state(
        self,
        run: StrategyTestRunResponse,
        increments: dict[str, Any],
    ) -> StrategyTestRunDetailResponse:
        state = dict(run.runtime_state)
        patch: dict[str, Any] = {
            "status": "processing",
            "last_processed_at": _now_iso(),
        }
        for key, value in increments.items():
            if key in {
                "processed_ticks",
                "processed_signals",
                "opened_trades",
                "pending_entries_armed",
                "trades_written",
                "metrics_written",
            }:
                patch[key] = _counter(state, key) + int(value or 0)
            else:
                patch[key] = value
        return self._run_store.update_runtime_state(run.run_id, patch)


def _forward_runs(details: Sequence[StrategyTestRunDetailResponse]) -> list[StrategyTestRunResponse]:
    return [detail.run for detail in details if detail.run.test_type == "forward_virtual"]


def _run_matches_signal(run: StrategyTestRunResponse, signal: StrategySignal) -> bool:
    matrix = run.requested_matrix
    if str(signal.strategy) not in {str(item) for item in matrix.get("strategies", [])}:
        return False
    if str(signal.timeframe) not in {str(item) for item in matrix.get("timeframes", [])}:
        return False
    return _run_matches_market(run, signal.exchange, signal.symbol)


def _run_matches_market(run: StrategyTestRunResponse, exchange: str, symbol: str) -> bool:
    exchange_key = exchange.strip().lower()
    symbol_key = symbol.strip().upper()
    pairs = run.requested_matrix.get("pairs", [])
    for pair in pairs if isinstance(pairs, list) else []:
        if not isinstance(pair, dict):
            continue
        if str(pair.get("exchange", "")).strip().lower() == exchange_key and str(pair.get("symbol", "")).strip().upper() == symbol_key:
            return True
    return False


def _manual_confirm_request(
    run: StrategyTestRunResponse,
    *,
    auto_enter_on_confirmation: bool = False,
) -> ManualConfirmRequest:
    matrix = run.requested_matrix
    return ManualConfirmRequest(
        mode="virtual",
        user_id=_matrix_user_id(run),
        auto_enter_on_confirmation=auto_enter_on_confirmation,
        account_balance=float(_decimal(matrix.get("initial_capital"), Decimal("1000"))),
        fee_rate=float(_decimal(matrix.get("fee_rate"), Decimal("0"))),
        slippage_bps=float(_decimal(matrix.get("slippage_bps"), Decimal("0"))),
        metadata={
            "strategy_test_run_id": str(run.run_id),
            "test_type": "forward_virtual",
        },
    )


def _execution_profile_from_run(
    run: StrategyTestRunResponse,
    gate: SignalExecutionGateSnapshot,
) -> ResolvedExecutionProfile:
    params = run.requested_matrix.get("params")
    params = params if isinstance(params, dict) else {}
    return ResolvedExecutionProfile(
        execution_mode="virtual",
        instrument_type=str(params.get("instrument_type") or "spot"),
        risk_mode=str(params.get("risk_mode") or "percent"),
        risk_percent=_decimal(params.get("risk_percent"), Decimal("1")),
        fixed_risk_amount=_optional_decimal(params.get("fixed_risk_amount")),
        fixed_risk_currency=str(params.get("fixed_risk_currency") or "USDT"),
        leverage=_decimal(params.get("leverage"), Decimal("1")),
        rr_guard_mode=str(params.get("rr_guard_mode") or "soft"),
        min_rr_ratio=_decimal(params.get("min_rr_ratio"), Decimal("2.0")),
        rr_target=str(params.get("rr_target") or "final"),
        radar_display_mode=str(params.get("radar_display_mode") or "all_market_opportunities"),
        sources={"forward_runtime": "strategy_test_run.requested_matrix"},
        warnings=[
            reason.message
            for reason in [*gate.reasons, *gate.warnings]
            if reason.severity != "blocker"
        ],
    )


def _strategy_test_trade_from_virtual_trade(
    *,
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    trade: VirtualTrade,
) -> StrategyTestTrade:
    entry_time = trade.opened_at.astimezone(timezone.utc)
    exit_time = trade.closed_at.astimezone(timezone.utc) if trade.closed_at else None
    pnl = _decimal(trade.pnl if trade.pnl is not None else trade.realized_pnl, Decimal("0"))
    fees = _decimal(trade.fees, Decimal("0")) + _decimal(trade.exit_fees, Decimal("0"))
    return StrategyTestTrade(
        run_id=run.run_id,
        trade_id=trade.id,
        user_id=strategy_test_user_uuid(_matrix_user_id(run)),
        mode=_matrix_mode(run),
        strategy_code=signal.strategy,
        strategy_version=str(signal.trade_plan.metadata.get("strategy_version", "")) if signal.trade_plan else "",
        exchange=signal.exchange,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        direction=signal.direction,
        signal_score=float(signal.score),
        market_regime=_market_regime(signal),
        score_bucket=_score_bucket(signal.score),
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=_decimal(trade.entry_price, Decimal("0")),
        exit_price=_optional_decimal(trade.exit_price),
        stop_loss=_optional_decimal(trade.stop_loss),
        targets=[{"price": price} for price in trade.take_profit],
        selected_rr=signal.selected_rr or signal.risk_reward,
        realized_r=None,
        pnl=pnl,
        pnl_pct=float(trade.pnl_percent or 0.0),
        fees=fees,
        slippage=_decimal(trade.slippage_bps, Decimal("0")),
        close_reason=trade.close_reason or ("open" if exit_time is None else "closed"),
        outcome=trade.result or trade.status,
        risk_rejected=False,
        execution_rejected=False,
        warnings=[],
        features_snapshot=signal.model_dump(mode="json", exclude={"card_view", "details_view"}),
        trade_plan=signal.trade_plan.model_dump(mode="json") if signal.trade_plan else {},
        tags=_run_tags(run),
        created_at=entry_time,
    )


def _strategy_test_metric_from_virtual_trade(
    *,
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    trade: VirtualTrade,
) -> StrategyTestMetricRow:
    return StrategyTestMetricRow(
        run_id=run.run_id,
        user_id=strategy_test_user_uuid(_matrix_user_id(run)),
        mode=_matrix_mode(run),
        strategy_code=signal.strategy,
        exchange=signal.exchange,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        market_regime=_market_regime(signal),
        score_bucket=_score_bucket(signal.score),
        direction=signal.direction,
        metric_code="forward_opened_trades",
        metric_value=1.0,
        sample_size=1,
        metadata={
            "signal_id": signal.id,
            "trade_id": trade.id,
            "test_type": "forward_virtual",
        },
        created_at=trade.opened_at.astimezone(timezone.utc),
    )


def _matrix_user_id(run: StrategyTestRunResponse) -> str:
    return str(run.requested_matrix.get("user_id") or "demo_user")


def _matrix_mode(run: StrategyTestRunResponse) -> str:
    value = str(run.requested_matrix.get("mode") or "research_virtual")
    if value in {"discovery", "research_virtual", "production_like"}:
        return value
    return "research_virtual"


def _run_tags(run: StrategyTestRunResponse) -> list[str]:
    tags = run.requested_matrix.get("tags")
    result = [str(tag) for tag in tags] if isinstance(tags, list) else []
    for tag in ("forward_virtual", "strategy_test"):
        if tag not in result:
            result.append(tag)
    return result


def _market_regime(signal: RadarSignal) -> str:
    if signal.regime is not None:
        return signal.regime.primary_label
    return "unknown"


def _score_bucket(score: int | float | None) -> str:
    return score_bucket_for(score)


def _counter(state: dict[str, Any], key: str) -> int:
    try:
        return int(state.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _decimal(value: Any, default: Decimal) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, Decimal("0"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
