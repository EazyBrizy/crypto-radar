from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from app.schemas.market import MarketData
from app.schemas.signal import RadarSignal, SignalExecutionGateReason, SignalExecutionGateSnapshot, StrategySignal
from app.schemas.trade import ManualConfirmRequest, VirtualTrade, VirtualTradeTargetState
from app.schemas.user import RiskManagementSettings
from app.services.execution_policy import (
    ExecutionPolicyContext,
    ExecutionPolicyDecision,
    execution_policy_resolver,
)
from app.services.portfolio_risk import (
    PortfolioRiskContext,
    PortfolioRiskDecision,
    PortfolioRiskLimits,
    portfolio_risk_service,
)
from app.services.position_management import position_management_engine
from app.services.signal_execution_gate import SignalExecutionGateService, signal_execution_gate_service
from app.services.strategy_performance_service import score_bucket_for
from app.services.strategy_testing.runner import strategy_test_user_uuid
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)
from app.services.strategy_testing.stores import ClickHouseStrategyTestStore, PostgresStrategyTestRunStore
from app.services.trade_plan_fingerprint import fingerprint_signal_trade_plan


FORWARD_PENDING_TERMINAL_RETENTION_LIMIT = 200
FORWARD_PROCESSED_SIGNAL_RETENTION_LIMIT = 500
_FORWARD_PENDING_TERMINAL_STATUSES = {
    "blocked",
    "cancelled",
    "canceled",
    "expired",
    "failed",
    "filled",
}


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

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
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


class ForwardScanner(Protocol):
    def process_tick(self, tick: MarketData) -> Any:
        ...


@dataclass
class ForwardRuntimeResult:
    ticks_processed: int = 0
    signals_processed: int = 0
    signals_skipped: int = 0
    opened_trades: int = 0
    closed_trades: int = 0
    pending_entries_armed: int = 0
    trades_written: int = 0
    signal_events_written: int = 0
    metrics_written: int = 0
    runtime_state_updates: int = 0
    cancelled_runs: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "ForwardRuntimeResult") -> None:
        self.ticks_processed += other.ticks_processed
        self.signals_processed += other.signals_processed
        self.signals_skipped += other.signals_skipped
        self.opened_trades += other.opened_trades
        self.closed_trades += other.closed_trades
        self.pending_entries_armed += other.pending_entries_armed
        self.trades_written += other.trades_written
        self.signal_events_written += other.signal_events_written
        self.metrics_written += other.metrics_written
        self.runtime_state_updates += other.runtime_state_updates
        self.cancelled_runs += other.cancelled_runs
        self.errors.extend(other.errors)


@dataclass
class ForwardMarkToMarketResult:
    runtime_state: dict[str, Any] = field(default_factory=dict)
    updated_trades: list[VirtualTrade] = field(default_factory=list)
    closed_trades: list[VirtualTrade] = field(default_factory=list)


@dataclass(frozen=True)
class _ForwardPendingEntryTouch:
    price: Decimal
    source: Literal["ask", "bid", "last", "price"]


class ForwardStrategyTestRuntime:
    def __init__(
        self,
        *,
        run_store: ForwardRunStore | None = None,
        trade_store: ForwardTradeStore | None = None,
        signal_writer: ForwardSignalWriter | None = None,
        virtual_trading: ForwardVirtualTrading | None = None,
        execution_gate: SignalExecutionGateService | None = None,
        scanner: ForwardScanner | None = None,
    ) -> None:
        self._run_store = run_store or PostgresStrategyTestRunStore()
        self._trade_store = trade_store or ClickHouseStrategyTestStore()
        self._signal_writer = signal_writer
        self._virtual_trading = virtual_trading or ForwardIsolatedVirtualTrading()
        self._execution_gate = execution_gate or signal_execution_gate_service
        self._scanner = scanner
        self._trade_store_schema_ensured = False

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
                "closed_trades": _counter(detail.run.runtime_state, "closed_trades"),
                "pending_entries_armed": _counter(detail.run.runtime_state, "pending_entries_armed"),
                "trades_written": _counter(detail.run.runtime_state, "trades_written"),
                "signal_events_written": _counter(detail.run.runtime_state, "signal_events_written"),
                "metrics_written": _counter(detail.run.runtime_state, "metrics_written"),
                "forward_account": _initial_forward_account(request),
                "forward_positions": list(detail.run.runtime_state.get("forward_positions") or []),
                **_forward_pending_entries_runtime_patch(_forward_pending_entries(detail.run)),
                "last_error": None,
            },
        )

    def heartbeat_active_runs(self) -> ForwardRuntimeResult:
        result = ForwardRuntimeResult()
        result.cancelled_runs += self._cancel_stopping_runs()
        for run in self._running_forward_runs():
            processed_ticks = _counter(run.runtime_state, "processed_ticks")
            waiting_for_first_tick = processed_ticks == 0
            self._run_store.update_runtime_state(
                run.run_id,
                {
                    "status": "waiting_for_market_data" if waiting_for_first_tick else "listening",
                    "last_heartbeat_reason": (
                        "waiting_for_market_data" if waiting_for_first_tick else "forward_runtime_worker"
                    ),
                    "processed_ticks": processed_ticks,
                    "last_processed_at": _now_iso(),
                },
            )
            result.runtime_state_updates += 1
        return result

    async def process_market_tick(self, tick: MarketData) -> ForwardRuntimeResult:
        result = ForwardRuntimeResult(ticks_processed=1)
        result.cancelled_runs += self._cancel_stopping_runs()
        runs = self._running_forward_runs()
        matched_runs = 0
        for run in runs:
            if not _run_matches_market(run, tick.exchange, tick.symbol):
                continue
            matched_runs += 1
            marked = _mark_to_market_forward_account(run, tick)
            trades_written, signal_events_written, metrics_written = self._write_forward_close_records(
                run,
                marked.closed_trades,
            )
            result.closed_trades += len(marked.closed_trades)
            result.trades_written += trades_written
            result.signal_events_written += signal_events_written
            result.metrics_written += metrics_written
            persistence_counters: dict[str, Any] = {}
            if marked.closed_trades:
                persistence_counters = {
                    "closed_trades": len(marked.closed_trades),
                    "trades_written": trades_written,
                    "signal_events_written": signal_events_written,
                    "metrics_written": metrics_written,
                    "last_closed_trade_id": marked.closed_trades[-1].id,
                    "last_close_reason": marked.closed_trades[-1].close_reason,
                }
            updated_detail = self._increment_runtime_state(
                run,
                {
                    "processed_ticks": 1,
                    "last_exchange": tick.exchange.lower(),
                    "last_symbol": tick.symbol.upper(),
                    "last_price": tick.price,
                    "last_tick_at": tick.timestamp,
                    "last_tick_timestamp": tick.timestamp,
                    "last_heartbeat_reason": "market_data_received",
                    "pending_entries_count": _forward_pending_entries_count(
                        _forward_pending_entries(run)
                    ),
                    "last_forward_event": "trade_closed" if marked.closed_trades else "market_tick",
                    **marked.runtime_state,
                    **persistence_counters,
                },
            )
            result.runtime_state_updates += 1
            result.merge(self._process_pending_entries_for_tick(updated_detail.run, tick))
        if matched_runs == 0 and runs:
            result.signals_skipped += 1
            for run in runs:
                if _counter(run.runtime_state, "processed_ticks") != 0:
                    continue
                self._run_store.update_runtime_state(
                    run.run_id,
                    {
                        "status": "waiting_for_market_data",
                        "last_heartbeat_reason": "no_matching_market_data",
                        "processed_ticks": 0,
                        "last_forward_event": "market_tick_no_match",
                        "last_processed_at": _now_iso(),
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
                radar_signal = self._radar_signal_for_forward_run(run, signal)
                processing_key = _forward_signal_processing_key(run, radar_signal)
                if _forward_signal_was_processed(run, processing_key):
                    result.signals_skipped += 1
                    self._run_store.update_runtime_state(
                        run.run_id,
                        {
                            "last_signal_id": radar_signal.id,
                            "last_forward_event": "duplicate_signal_ignored",
                            "last_heartbeat_reason": "duplicate_forward_signal",
                            "last_processed_at": _now_iso(),
                        },
                    )
                    result.runtime_state_updates += 1
                    continue
                processed_signal_patch = _forward_processed_signal_runtime_patch(run, processing_key)
                gate = radar_signal.execution_gate or self._execution_gate.evaluate(radar_signal)
                result.signals_processed += 1
                if gate.can_enter_now:
                    gate_request = _manual_confirm_request(run)
                    policy_reference_price = _forward_policy_price(run, radar_signal)
                    execution_policy_decision = _forward_execution_policy_decision(
                        run,
                        radar_signal,
                        gate_request,
                        reference_price=policy_reference_price,
                    )
                    if not execution_policy_decision.can_execute:
                        if execution_policy_decision.should_wait:
                            gate = _gate_waiting_for_execution_policy(gate, execution_policy_decision)
                            radar_signal = radar_signal.model_copy(update={"execution_gate": gate})
                            event = _strategy_test_signal_event_from_forward_signal(
                                run=run,
                                signal=radar_signal,
                                gate=gate,
                                funnel_stage="pending",
                                outcome="pending",
                            )
                            result.pending_entries_armed += 1
                            result.signal_events_written += self._write_signal_event(event)
                            self._increment_runtime_state(
                                run,
                                {
                                    "processed_signals": 1,
                                    "pending_entries_armed": 1,
                                    **_forward_pending_entries_runtime_patch(
                                        _upsert_forward_pending_entry(
                                            _forward_pending_entries(run),
                                            _forward_pending_entry_snapshot(radar_signal, gate),
                                        )
                                    ),
                                    "signal_events_written": 1,
                                    **processed_signal_patch,
                                    "last_signal_id": radar_signal.id,
                                    "last_gate_status": gate.status,
                                    "last_feed_kind": gate.feed_kind,
                                    "last_forward_event": "signal_pending",
                                    "last_execution_policy_mode": execution_policy_decision.mode,
                                    "last_execution_policy_reason_code": execution_policy_decision.reason_code,
                                },
                            )
                            result.runtime_state_updates += 1
                            continue
                        gate = _gate_blocked_by_execution_policy(gate, execution_policy_decision)
                        radar_signal = radar_signal.model_copy(update={"execution_gate": gate})
                        event = _strategy_test_signal_event_from_forward_signal(
                            run=run,
                            signal=radar_signal,
                            gate=gate,
                            funnel_stage="blocked",
                            outcome="blocked",
                        )
                        result.signal_events_written += self._write_signal_event(event)
                        self._increment_runtime_state(
                            run,
                            {
                                "processed_signals": 1,
                                "signal_events_written": 1,
                                **processed_signal_patch,
                                "last_signal_id": radar_signal.id,
                                "last_gate_status": gate.status,
                                "last_feed_kind": gate.feed_kind,
                                "last_forward_event": "signal_blocked",
                                "last_execution_policy_mode": execution_policy_decision.mode,
                                "last_execution_policy_reason_code": execution_policy_decision.reason_code,
                            },
                        )
                        result.runtime_state_updates += 1
                        continue
                    gate_request = _request_with_execution_policy_reference(
                        gate_request,
                        execution_policy_decision,
                        reference_price=policy_reference_price,
                    )
                    portfolio_decision = _forward_portfolio_decision(run, radar_signal, gate_request)
                    if not portfolio_decision.can_enter:
                        gate = _gate_blocked_by_portfolio(gate, portfolio_decision)
                        radar_signal = radar_signal.model_copy(update={"execution_gate": gate})
                        event = _strategy_test_signal_event_from_forward_signal(
                            run=run,
                            signal=radar_signal,
                            gate=gate,
                            funnel_stage="blocked",
                            outcome="blocked",
                        )
                        result.signal_events_written += self._write_signal_event(event)
                        self._increment_runtime_state(
                            run,
                            {
                                "processed_signals": 1,
                                "signal_events_written": 1,
                                **processed_signal_patch,
                                "last_signal_id": radar_signal.id,
                                "last_gate_status": gate.status,
                                "last_feed_kind": gate.feed_kind,
                                "last_forward_event": "signal_blocked",
                                "last_portfolio_risk_action": portfolio_decision.action,
                                "last_portfolio_risk_reason_code": portfolio_decision.reason_code,
                            },
                        )
                        result.runtime_state_updates += 1
                        continue
                    if portfolio_decision.action == "reduce_size":
                        gate_request = _request_with_portfolio_size(gate_request, portfolio_decision)
                        gate = _gate_with_portfolio_warning(gate, portfolio_decision)
                        radar_signal = radar_signal.model_copy(update={"execution_gate": gate})
                    opened = self._open_virtual_trade(run, radar_signal, request=gate_request)
                    event = _strategy_test_signal_event_from_forward_signal(
                        run=run,
                        signal=radar_signal,
                        gate=gate,
                        trade=opened,
                    )
                    result.opened_trades += 1
                    result.trades_written += self._write_trade(run, radar_signal, opened)
                    result.signal_events_written += self._write_signal_event(event)
                    result.metrics_written += self._write_metric(run, radar_signal, opened)
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "opened_trades": 1,
                            "trades_written": 1,
                            "signal_events_written": 1,
                            "metrics_written": 1,
                            **processed_signal_patch,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                            "last_trade_id": opened.id,
                            "last_forward_event": "trade_opened",
                            **_apply_forward_trade_open(run, opened),
                        },
                    )
                elif gate.can_arm_pending:
                    event = _strategy_test_signal_event_from_forward_signal(
                        run=run,
                        signal=radar_signal,
                        gate=gate,
                        funnel_stage="pending",
                        outcome="pending",
                    )
                    result.pending_entries_armed += 1
                    result.signal_events_written += self._write_signal_event(event)
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "pending_entries_armed": 1,
                            **_forward_pending_entries_runtime_patch(
                                _upsert_forward_pending_entry(
                                    _forward_pending_entries(run),
                                    _forward_pending_entry_snapshot(radar_signal, gate),
                                )
                            ),
                            "signal_events_written": 1,
                            **processed_signal_patch,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                            "last_forward_event": "signal_pending",
                        },
                    )
                else:
                    event = _strategy_test_signal_event_from_forward_signal(
                        run=run,
                        signal=radar_signal,
                        gate=gate,
                        funnel_stage="blocked" if gate.status == "blocked" else "no_entry",
                        outcome="blocked" if gate.status == "blocked" else "no_entry",
                    )
                    result.signal_events_written += self._write_signal_event(event)
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "signal_events_written": 1,
                            **processed_signal_patch,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                            "last_forward_event": (
                                "signal_blocked" if gate.status == "blocked" else "signal_no_entry"
                            ),
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

    def _radar_signal_for_forward_run(
        self,
        run: StrategyTestRunResponse,
        signal: StrategySignal,
    ) -> RadarSignal:
        if self._signal_writer is not None:
            radar_signal, _ = self._signal_writer.upsert_strategy_signal(
                signal,
                exchange=signal.exchange,
                explanation=list(signal.explanation),
            )
            return radar_signal
        return _forward_radar_signal_from_strategy_signal(run, signal)

    def _process_pending_entries_for_tick(
        self,
        run: StrategyTestRunResponse,
        tick: MarketData,
    ) -> ForwardRuntimeResult:
        entries = _forward_pending_entries(run)
        if not entries:
            return ForwardRuntimeResult()

        result = ForwardRuntimeResult()
        updated_entries: list[dict[str, Any]] = []
        current_run = run
        state_patch: dict[str, Any] = {}
        counter_patch: dict[str, int] = {}
        last_patch: dict[str, Any] = {}
        changed = False
        now = _signal_timestamp_to_utc(tick.timestamp)
        for entry in entries:
            pending = dict(entry)
            if (
                _forward_pending_entry_status(pending) != "pending"
                or not _forward_pending_entry_matches_market(pending, tick.exchange, tick.symbol)
            ):
                updated_entries.append(pending)
                continue

            if _forward_pending_entry_is_expired(pending, now):
                updated_entries.append(
                    _terminal_forward_pending_entry(
                        pending,
                        status="expired",
                        now=now,
                        reason_code="pending_entry_expired_before_touch",
                        reason="Pending forward entry expired before entry touch.",
                    )
                )
                last_patch["last_forward_event"] = "pending_entry_expired"
                changed = True
                continue

            try:
                touch = _forward_pending_entry_touch(pending, tick)
            except ValueError as exc:
                updated_entries.append(
                    _terminal_forward_pending_entry(
                        pending,
                        status="blocked",
                        now=now,
                        reason_code="pending_entry_execution_invalid",
                        reason=str(exc),
                    )
                )
                last_patch["last_forward_event"] = "pending_entry_blocked"
                changed = True
                continue
            if touch is None:
                updated_entries.append(pending)
                continue

            try:
                signal = _forward_radar_signal_from_pending_entry(pending, tick)
                gate = signal.execution_gate or _forward_pending_entry_fill_gate(pending)
                request = _pending_entry_manual_confirm_request(current_run, pending, touch)
                portfolio_decision = _forward_portfolio_decision(current_run, signal, request)
                if not portfolio_decision.can_enter:
                    blocked_gate = _gate_blocked_by_portfolio(gate, portfolio_decision)
                    signal = signal.model_copy(update={"execution_gate": blocked_gate})
                    event = _strategy_test_signal_event_from_forward_signal(
                        run=current_run,
                        signal=signal,
                        gate=blocked_gate,
                        funnel_stage="blocked",
                        outcome="blocked",
                    )
                    result.signal_events_written += self._write_signal_event(event)
                    counter_patch["signal_events_written"] = counter_patch.get("signal_events_written", 0) + 1
                    updated_entries.append(
                        _terminal_forward_pending_entry(
                            pending,
                            status="blocked",
                            now=now,
                            reason_code=portfolio_decision.reason_code,
                            reason=portfolio_decision.message,
                            touch=touch,
                        )
                    )
                    last_patch.update(
                        {
                            "last_signal_id": signal.id,
                            "last_gate_status": blocked_gate.status,
                            "last_feed_kind": blocked_gate.feed_kind,
                            "last_forward_event": "pending_entry_blocked",
                            "last_portfolio_risk_action": portfolio_decision.action,
                            "last_portfolio_risk_reason_code": portfolio_decision.reason_code,
                        }
                    )
                    changed = True
                    continue
                if portfolio_decision.action == "reduce_size":
                    request = _request_with_portfolio_size(request, portfolio_decision)
                    gate = _gate_with_portfolio_warning(gate, portfolio_decision)
                    signal = signal.model_copy(update={"execution_gate": gate})
                opened = self._open_virtual_trade(current_run, signal, request=request)
            except (TypeError, ValueError) as exc:
                updated_entries.append(
                    _terminal_forward_pending_entry(
                        pending,
                        status="blocked",
                        now=now,
                        reason_code="pending_entry_execution_invalid",
                        reason=str(exc),
                        touch=touch,
                    )
                )
                last_patch["last_forward_event"] = "pending_entry_blocked"
                changed = True
                continue

            event = _strategy_test_signal_event_from_forward_signal(
                run=current_run,
                signal=signal,
                gate=gate,
                trade=opened,
                funnel_stage="filled",
                outcome="filled",
            )
            trade_writes = self._write_trade(current_run, signal, opened)
            event_writes = self._write_signal_event(event)
            metric_writes = self._write_metric(current_run, signal, opened)
            result.opened_trades += 1
            result.trades_written += trade_writes
            result.signal_events_written += event_writes
            result.metrics_written += metric_writes
            counter_patch["opened_trades"] = counter_patch.get("opened_trades", 0) + 1
            counter_patch["trades_written"] = counter_patch.get("trades_written", 0) + trade_writes
            counter_patch["signal_events_written"] = counter_patch.get("signal_events_written", 0) + event_writes
            counter_patch["metrics_written"] = counter_patch.get("metrics_written", 0) + metric_writes
            trade_state = _apply_forward_trade_open(current_run, opened)
            state_patch.update(trade_state)
            current_run = current_run.model_copy(
                update={"runtime_state": {**current_run.runtime_state, **trade_state}}
            )
            updated_entries.append(
                _terminal_forward_pending_entry(
                    pending,
                    status="filled",
                    now=now,
                    trade_id=opened.id,
                    touch=touch,
                )
            )
            last_patch.update(
                {
                    "last_signal_id": signal.id,
                    "last_gate_status": gate.status,
                    "last_feed_kind": gate.feed_kind,
                    "last_trade_id": opened.id,
                    "last_forward_event": "trade_opened",
                }
            )
            changed = True

        if changed:
            pending_entries_patch = _forward_pending_entries_runtime_patch(updated_entries)
            self._increment_runtime_state(
                run,
                {
                    **counter_patch,
                    **state_patch,
                    **last_patch,
                    **pending_entries_patch,
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

    def _open_virtual_trade(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        *,
        request: ManualConfirmRequest | None = None,
    ) -> VirtualTrade:
        return self._virtual_trading.open_virtual_trade(
            signal,
            request or _manual_confirm_request(run),
        )

    def _write_trade(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        trade: VirtualTrade,
    ) -> int:
        self._ensure_trade_store_schema()
        row = _strategy_test_trade_from_virtual_trade(run=run, signal=signal, trade=trade)
        self._trade_store.write_trades([row])
        return 1

    def _write_signal_event(self, event: StrategyTestSignalEvent) -> int:
        self._ensure_trade_store_schema()
        self._trade_store.write_signal_events([event])
        return 1

    def _write_metric(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        trade: VirtualTrade,
    ) -> int:
        self._ensure_trade_store_schema()
        self._trade_store.write_metrics(
            [_strategy_test_metric_from_virtual_trade(run=run, signal=signal, trade=trade)]
        )
        return 1

    def _write_forward_close_records(
        self,
        run: StrategyTestRunResponse,
        trades: Sequence[VirtualTrade],
    ) -> tuple[int, int, int]:
        if not trades:
            return 0, 0, 0

        self._ensure_trade_store_schema()
        trade_rows: list[StrategyTestTrade] = []
        signal_events: list[StrategyTestSignalEvent] = []
        metric_rows: list[StrategyTestMetricRow] = []
        gate = _forward_close_gate()
        for trade in trades:
            signal = _forward_radar_signal_from_virtual_trade(trade)
            trade_rows.append(
                _strategy_test_trade_from_virtual_trade(run=run, signal=signal, trade=trade)
            )
            signal_events.append(
                _strategy_test_signal_event_from_forward_signal(
                    run=run,
                    signal=signal,
                    gate=gate,
                    trade=trade,
                    funnel_stage="closed",
                    outcome=_forward_close_outcome(trade),
                )
            )
            metric_rows.extend(
                _strategy_test_close_metrics_from_virtual_trade(run=run, signal=signal, trade=trade)
            )

        self._trade_store.write_trades(trade_rows)
        self._trade_store.write_signal_events(signal_events)
        self._trade_store.write_metrics(metric_rows)
        return len(trade_rows), len(signal_events), len(metric_rows)

    def _ensure_trade_store_schema(self) -> None:
        if self._trade_store_schema_ensured:
            return
        ensure_schema = getattr(self._trade_store, "ensure_schema", None)
        if ensure_schema is not None:
            ensure_schema()
        self._trade_store_schema_ensured = True

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
                "closed_trades",
                "pending_entries_armed",
                "trades_written",
                "signal_events_written",
                "metrics_written",
            }:
                patch[key] = _counter(state, key) + int(value or 0)
            else:
                patch[key] = value
        return self._run_store.update_runtime_state(run.run_id, patch)


class ForwardIsolatedVirtualTrading:
    def open_virtual_trade(self, signal: RadarSignal, request: ManualConfirmRequest) -> VirtualTrade:
        entry_price = _entry_price(signal, request=request)
        size_usd = _virtual_size_usd(request)
        quantity = size_usd / entry_price if entry_price > 0 else 0.0
        opened_at = signal.created_at.astimezone(timezone.utc)
        return VirtualTrade(
            id=_forward_trade_id(signal.id),
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
            initial_quantity=quantity,
            remaining_quantity=quantity,
            initial_size_usd=size_usd,
            remaining_size_usd=size_usd,
            leverage=request.leverage,
            risk_percent=float(request.risk_percent or 1.0),
            risk_amount=size_usd * float(request.risk_percent or 1.0) / 100,
            risk_reward=float(signal.selected_rr or signal.risk_reward or 0.0),
            stop_loss=float(signal.stop_loss or entry_price),
            take_profit=[price for price in [signal.take_profit_1, signal.take_profit_2] if price is not None],
            fees=size_usd * request.fee_rate,
            slippage_bps=request.slippage_bps,
            requested_size_usd=size_usd,
            filled_size_usd=size_usd,
            opened_at=opened_at,
            updated_at=opened_at,
        )


def _forward_radar_signal_from_strategy_signal(
    run: StrategyTestRunResponse,
    signal: StrategySignal,
) -> RadarSignal:
    created_at = _signal_timestamp_to_utc(signal.timestamp)
    return RadarSignal(
        id=_forward_signal_id(run, signal),
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
        explanation=list(signal.explanation),
        risks=list(signal.risks),
        score_breakdown=signal.score_breakdown,
        status_reason=signal.status_reason,
        quality=signal.quality,
        regime=signal.regime,
        setup=signal.setup,
        confirmation=signal.confirmation,
        trigger=signal.trigger,
        invalidation=signal.invalidation,
        exit_plan=signal.exit_plan,
        trade_plan=signal.trade_plan,
        edge=signal.edge,
        no_trade_filter=signal.no_trade_filter,
        decision=signal.decision,
        execution_gate=signal.execution_gate,
        created_at=created_at,
        updated_at=created_at,
    )


def _forward_radar_signal_from_virtual_trade(trade: VirtualTrade) -> RadarSignal:
    take_profit = list(trade.take_profit)
    created_at = trade.opened_at.astimezone(timezone.utc)
    return RadarSignal(
        id=trade.signal_id,
        symbol=trade.symbol,
        exchange=trade.exchange,
        strategy=trade.strategy,
        direction=trade.side,
        confidence=0.0,
        risk_reward=trade.risk_reward,
        selected_rr=trade.risk_reward,
        status="actionable",
        score=0,
        timeframe=trade.timeframe,
        entry_min=trade.entry_price,
        entry_max=trade.entry_price,
        stop_loss=trade.stop_loss,
        take_profit_1=take_profit[0] if len(take_profit) >= 1 else None,
        take_profit_2=take_profit[1] if len(take_profit) >= 2 else None,
        created_at=created_at,
        updated_at=(trade.updated_at or created_at).astimezone(timezone.utc),
    )


def _forward_close_gate() -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed",
        feed_kind="watchlist",
        metadata={
            "runtime": "forward_strategy_test",
            "event": "position_closed",
        },
    )


def _forward_close_outcome(trade: VirtualTrade) -> str:
    reason = str(trade.close_reason or "").strip().lower()
    if reason in {"take_profit", "stop_loss", "trailing_stop", "time_stop"}:
        return reason
    if reason == "breakeven_stop":
        return "stop_loss"
    return reason or str(trade.result or trade.status or "closed")


def _strategy_test_signal_event_from_forward_signal(
    *,
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    gate: SignalExecutionGateSnapshot,
    trade: VirtualTrade | None = None,
    funnel_stage: str | None = None,
    outcome: str | None = None,
) -> StrategyTestSignalEvent:
    event_time = (
        trade.closed_at.astimezone(timezone.utc)
        if trade is not None and trade.closed_at is not None
        else signal.created_at.astimezone(timezone.utc)
    )
    filled = trade is not None
    blocked_reason_code = _first_gate_reason_code(gate)
    stage = funnel_stage or ("filled" if filled else "signal")
    event_outcome = outcome or ("open" if filled else None)
    return StrategyTestSignalEvent(
        run_id=run.run_id,
        user_id=strategy_test_user_uuid(_matrix_user_id(run)),
        mode=_matrix_mode(run),
        test_type="forward_virtual",
        strategy_code=signal.strategy,
        strategy_version=str(signal.trade_plan.metadata.get("strategy_version", "")) if signal.trade_plan else "",
        exchange=signal.exchange,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        direction=signal.direction,
        signal_id=signal.id,
        synthetic_signal_id=signal.id,
        signal_key=_forward_signal_key(run, signal),
        event_time=event_time,
        candle_time=event_time,
        signal_score=float(signal.score) if signal.score is not None else None,
        market_regime=_market_regime(signal),
        score_bucket=_score_bucket(signal.score),
        status=signal.status,
        gate_status=gate.status,
        feed_kind=gate.feed_kind,
        trigger_passed=bool(gate.can_enter_now or gate.can_arm_pending or getattr(signal.trigger, "passed", False)),
        trigger_reason_code=blocked_reason_code if gate.status != "passed" else None,
        execution_candidate=bool(gate.can_enter_now or gate.can_arm_pending or gate.feed_kind == "execution_signal"),
        entry_touched=filled,
        filled=filled,
        closed=bool(trade and trade.closed_at is not None),
        outcome=event_outcome,
        funnel_stage=stage,
        risk_rejected=_gate_has_reason_source(gate, {"risk", "rr", "no_trade"}),
        execution_rejected=gate.status == "blocked" and gate.feed_kind == "blocked",
        no_entry=stage in {"blocked", "no_entry"},
        rejection_reason_code=blocked_reason_code if gate.status == "blocked" else None,
        blocked_reason_code=blocked_reason_code if gate.status == "blocked" else None,
        selected_rr=signal.selected_rr or signal.risk_reward,
        entry_min=_optional_decimal(signal.entry_min),
        entry_max=_optional_decimal(signal.entry_max),
        stop_loss=_optional_decimal(signal.stop_loss),
        features_snapshot=signal.model_dump(mode="json", exclude={"card_view", "details_view"}),
        trade_plan=signal.trade_plan.model_dump(mode="json") if signal.trade_plan else {},
        metadata={
            "test_type": "forward_virtual",
            "trade_id": trade.id if trade else None,
            "runtime": "forward_strategy_test",
        },
        tags=_run_tags(run),
        created_at=_now_utc(),
    )


def _initial_forward_account(request: StrategyTestRunRequest) -> dict[str, Any]:
    initial_capital = _decimal(request.initial_capital, Decimal("1000"))
    return _serialize_forward_account(
        {
            "initial_capital": initial_capital,
            "balance": initial_capital,
            "equity": initial_capital,
            "realized_pnl": Decimal("0"),
            "unrealized_pnl": Decimal("0"),
            "fees": Decimal("0"),
            "slippage": Decimal("0"),
            "open_positions": 0,
            "closed_positions": 0,
        }
    )


def _forward_pending_entries(run: StrategyTestRunResponse) -> list[dict[str, Any]]:
    raw_entries = run.runtime_state.get("pending_entries")
    if not isinstance(raw_entries, list):
        return []
    return [dict(entry) for entry in raw_entries if isinstance(entry, dict)]


def _forward_pending_entries_runtime_patch(entries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    capped_entries = _cap_forward_pending_entries(entries)
    return {
        "pending_entries": capped_entries,
        "pending_entries_count": _forward_pending_entries_count(capped_entries),
    }


def _forward_pending_entries_count(entries: Sequence[dict[str, Any]]) -> int:
    return sum(1 for entry in entries if _forward_pending_entry_status(entry) == "pending")


def _upsert_forward_pending_entry(
    entries: Sequence[dict[str, Any]],
    pending_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    signal_id = str(pending_entry.get("signal_id") or "")
    updated: list[dict[str, Any]] = []
    replaced = False
    for entry in entries:
        if (
            signal_id
            and str(entry.get("signal_id") or "") == signal_id
            and _forward_pending_entry_status(entry) == "pending"
        ):
            if not replaced:
                updated.append(dict(pending_entry))
                replaced = True
            continue
        updated.append(dict(entry))
    if not replaced:
        updated.append(dict(pending_entry))
    return _cap_forward_pending_entries(updated)


def _cap_forward_pending_entries(entries: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    terminal_seen = 0
    kept_reversed: list[dict[str, Any]] = []
    for entry in reversed(entries):
        snapshot = dict(entry)
        if _forward_pending_entry_is_terminal(snapshot):
            if terminal_seen < FORWARD_PENDING_TERMINAL_RETENTION_LIMIT:
                kept_reversed.append(snapshot)
            terminal_seen += 1
            continue
        kept_reversed.append(snapshot)
    return list(reversed(kept_reversed))


def _forward_pending_entry_snapshot(
    signal: RadarSignal,
    gate: SignalExecutionGateSnapshot,
) -> dict[str, Any]:
    targets = _pending_entry_targets_from_signal(signal)
    base = {
        "status": "pending",
        "signal_id": signal.id,
        "exchange": signal.exchange.strip().lower(),
        "symbol": signal.symbol.strip().upper(),
        "side": "short" if signal.direction == "short" else "long",
        "entry_min": signal.entry_min,
        "entry_max": signal.entry_max,
        "stop_loss": signal.stop_loss,
        "targets": targets,
        "expires_at": signal.expires_at.astimezone(timezone.utc).isoformat()
        if signal.expires_at is not None
        else None,
        "created_at": signal.created_at.astimezone(timezone.utc).isoformat(),
        "strategy": signal.strategy,
        "timeframe": signal.timeframe,
        "confidence": signal.confidence,
        "risk_reward": signal.risk_reward,
        "first_target_rr": signal.first_target_rr,
        "final_target_rr": signal.final_target_rr,
        "selected_rr": signal.selected_rr,
        "selected_rr_target": signal.selected_rr_target,
        "min_rr_ratio": signal.min_rr_ratio,
        "urgency": signal.urgency,
        "score": signal.score,
        "signal_status": signal.status,
        "candle_state": signal.candle_state,
        "trade_plan": signal.trade_plan.model_dump(mode="json") if signal.trade_plan else None,
        "gate": gate.model_dump(mode="json"),
    }
    try:
        base["trade_plan_hash"] = fingerprint_signal_trade_plan(signal).hash
    except ValueError as exc:
        base.update(
            {
                "status": "blocked",
                "trade_plan_hash": None,
                "blocked_reason_code": "pending_entry_execution_invalid",
                "blocked_reason": str(exc),
                "resolved_at": _now_iso(),
            }
        )
    return base


def _pending_entry_targets_from_signal(signal: RadarSignal) -> list[float]:
    return [
        float(price)
        for price in (signal.take_profit_1, signal.take_profit_2)
        if price is not None and _decimal(price, Decimal("0")) > 0
    ]


def _forward_pending_entry_status(entry: dict[str, Any]) -> str:
    return str(entry.get("status") or "pending").strip().lower()


def _forward_pending_entry_is_terminal(entry: dict[str, Any]) -> bool:
    return _forward_pending_entry_status(entry) in _FORWARD_PENDING_TERMINAL_STATUSES


def _forward_pending_entry_matches_market(entry: dict[str, Any], exchange: str, symbol: str) -> bool:
    return (
        str(entry.get("exchange") or "").strip().lower() == exchange.strip().lower()
        and str(entry.get("symbol") or "").strip().upper() == symbol.strip().upper()
    )


def _forward_pending_entry_is_expired(entry: dict[str, Any], now: datetime) -> bool:
    expires_at = _forward_pending_entry_datetime(entry.get("expires_at"))
    return expires_at is not None and expires_at <= now


def _forward_pending_entry_touch(entry: dict[str, Any], tick: MarketData) -> _ForwardPendingEntryTouch | None:
    price, source = _forward_pending_entry_touch_candidate(entry, tick)
    if price <= 0:
        return None
    lower = _decimal(entry.get("entry_min"), Decimal("0"))
    upper = _decimal(entry.get("entry_max"), Decimal("0"))
    if lower <= 0 or upper <= 0:
        raise ValueError("Pending forward entry requires a positive entry zone.")
    if upper < lower:
        lower, upper = upper, lower
    return _ForwardPendingEntryTouch(price=price, source=source) if lower <= price <= upper else None


def _forward_pending_entry_touch_candidate(
    entry: dict[str, Any],
    tick: MarketData,
) -> tuple[Decimal, Literal["ask", "bid", "last", "price"]]:
    side = str(entry.get("side") or "").strip().lower()
    candidates: tuple[tuple[Literal["ask", "bid", "last", "price"], tuple[str, ...]], ...]
    if side == "short":
        candidates = (
            ("bid", ("bid", "best_bid")),
            ("last", ("last",)),
            ("price", ("price",)),
        )
    else:
        candidates = (
            ("ask", ("ask", "best_ask")),
            ("last", ("last",)),
            ("price", ("price",)),
        )
    for source, field_names in candidates:
        for field_name in field_names:
            price = _decimal(getattr(tick, field_name, None), Decimal("0"))
            if price > 0:
                return price, source
    return Decimal("0"), "price"


def _terminal_forward_pending_entry(
    entry: dict[str, Any],
    *,
    status: Literal["blocked", "expired", "filled"],
    now: datetime,
    reason_code: str | None = None,
    reason: str | None = None,
    trade_id: str | None = None,
    touch: _ForwardPendingEntryTouch | None = None,
) -> dict[str, Any]:
    updated = dict(entry)
    updated["status"] = status
    updated["resolved_at"] = now.astimezone(timezone.utc).isoformat()
    if status == "filled":
        updated["filled_at"] = updated["resolved_at"]
    if trade_id is not None:
        updated["trade_id"] = trade_id
    if reason_code is not None:
        updated["reason_code"] = reason_code
    if reason is not None:
        updated["reason"] = reason
    if touch is not None:
        updated["touch_price"] = float(touch.price)
        updated["touch_price_source"] = touch.source
    return updated


def _forward_radar_signal_from_pending_entry(
    entry: dict[str, Any],
    tick: MarketData,
) -> RadarSignal:
    targets = _pending_entry_targets_from_snapshot(entry)
    created_at = _signal_timestamp_to_utc(tick.timestamp)
    gate = _forward_pending_entry_fill_gate(entry)
    return RadarSignal(
        id=str(entry.get("signal_id") or ""),
        symbol=str(entry.get("symbol") or tick.symbol).strip().upper(),
        exchange=str(entry.get("exchange") or tick.exchange).strip().lower(),
        strategy=str(entry.get("strategy") or "unknown"),
        direction="short" if str(entry.get("side") or "").lower() == "short" else "long",
        confidence=float(_decimal(entry.get("confidence"), Decimal("0"))),
        risk_reward=_optional_float(entry.get("risk_reward")),
        first_target_rr=_optional_float(entry.get("first_target_rr")),
        final_target_rr=_optional_float(entry.get("final_target_rr")),
        selected_rr=_optional_float(entry.get("selected_rr")),
        selected_rr_target=str(entry.get("selected_rr_target")) if entry.get("selected_rr_target") else None,
        min_rr_ratio=_optional_float(entry.get("min_rr_ratio")),
        urgency=str(entry.get("urgency") or "medium"),
        status=str(entry.get("signal_status") or "actionable"),
        score=int(_decimal(entry.get("score"), Decimal("0"))),
        timeframe=str(entry.get("timeframe") or "stream"),
        candle_state=str(entry.get("candle_state") or "closed"),
        entry_min=float(_required_pending_decimal(entry.get("entry_min"), "entry_min")),
        entry_max=float(_required_pending_decimal(entry.get("entry_max"), "entry_max")),
        stop_loss=float(_required_pending_decimal(entry.get("stop_loss"), "stop_loss")),
        take_profit_1=targets[0] if len(targets) >= 1 else None,
        take_profit_2=targets[1] if len(targets) >= 2 else None,
        trade_plan=entry.get("trade_plan") if isinstance(entry.get("trade_plan"), dict) else None,
        execution_gate=gate,
        created_at=created_at,
        updated_at=created_at,
        expires_at=_forward_pending_entry_datetime(entry.get("expires_at")),
    )


def _forward_pending_entry_fill_gate(entry: dict[str, Any]) -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed",
        feed_kind="execution_signal",
        can_notify=True,
        can_enter_now=True,
        can_arm_pending=False,
        can_show_in_execution_feed=True,
        metadata={
            "runtime": "forward_strategy_test",
            "event": "pending_entry_filled",
            "pending_signal_id": str(entry.get("signal_id") or ""),
            "trade_plan_hash": entry.get("trade_plan_hash"),
        },
    )


def _pending_entry_manual_confirm_request(
    run: StrategyTestRunResponse,
    entry: dict[str, Any],
    touch: _ForwardPendingEntryTouch,
) -> ManualConfirmRequest:
    request = _manual_confirm_request(run, auto_enter_on_confirmation=True)
    metadata = dict(request.metadata or {})
    metadata.update(
        {
            "trigger_source": "pending_entry",
            "accepted_trade_plan_hash": entry.get("trade_plan_hash"),
            "pending_entry_trigger": {
                "touch_price": str(touch.price),
                "trigger_price": str(touch.price),
                "trigger_reason": "entry_zone_touched",
                "touch_price_source": touch.source,
            },
        }
    )
    return request.model_copy(update={"metadata": metadata})


def _pending_entry_targets_from_snapshot(entry: dict[str, Any]) -> list[float]:
    raw_targets = entry.get("targets")
    if not isinstance(raw_targets, list):
        raw_targets = []
    targets = [
        float(price)
        for price in (_decimal(target, Decimal("0")) for target in raw_targets)
        if price > 0
    ]
    if not targets:
        raise ValueError("Pending forward entry requires at least one target.")
    return targets


def _required_pending_decimal(value: Any, field_name: str) -> Decimal:
    number = _decimal(value, Decimal("0"))
    if number <= 0:
        raise ValueError(f"Pending forward entry requires positive {field_name}.")
    return number


def _forward_pending_entry_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _apply_forward_trade_open(
    run: StrategyTestRunResponse,
    trade: VirtualTrade,
) -> dict[str, Any]:
    account = _forward_account_from_runtime(run)
    fees = _decimal(trade.fees, Decimal("0"))
    slippage = _decimal(trade.slippage_bps, Decimal("0"))
    account["balance"] -= fees
    account["fees"] += fees
    account["slippage"] += slippage
    account["open_positions"] += 1
    account["equity"] = account["balance"] + account["unrealized_pnl"]

    positions = _forward_positions(run)
    positions.append(
        {
            "trade_id": trade.id,
            "signal_id": trade.signal_id,
            "exchange": trade.exchange,
            "symbol": trade.symbol,
            "strategy": trade.strategy,
            "timeframe": trade.timeframe,
            "side": trade.side,
            "entry_price": str(_decimal(trade.entry_price, Decimal("0"))),
            "current_price": str(_decimal(trade.current_price, Decimal("0"))),
            "size_usd": str(_decimal(trade.size_usd, Decimal("0"))),
            "quantity": str(_decimal(trade.quantity, Decimal("0"))),
            "risk_percent": str(_decimal(trade.risk_percent, Decimal("0"))),
            "risk_amount": str(_decimal(trade.risk_amount, Decimal("0"))),
            "stop_loss": str(_decimal(trade.stop_loss, Decimal("0"))),
            "take_profit": [str(_decimal(price, Decimal("0"))) for price in trade.take_profit],
            "unrealized_pnl": "0",
            "fees": str(fees),
            "status": "open",
            "opened_at": trade.opened_at.astimezone(timezone.utc).isoformat(),
        }
    )
    return {
        "forward_account": _serialize_forward_account(account),
        "forward_positions": positions,
    }


def _mark_to_market_forward_account(
    run: StrategyTestRunResponse,
    tick: MarketData,
) -> ForwardMarkToMarketResult:
    positions = _forward_positions(run)
    if not positions:
        return ForwardMarkToMarketResult()

    tick_exchange = tick.exchange.strip().lower()
    tick_symbol = tick.symbol.strip().upper()
    price = _decimal(tick.price, Decimal("0"))
    total_unrealized = Decimal("0")
    realized_delta = Decimal("0")
    closed_count = 0
    now = _signal_timestamp_to_utc(tick.timestamp)
    updated_positions: list[dict[str, Any]] = []
    updated_trades: list[VirtualTrade] = []
    closed_trades: list[VirtualTrade] = []
    for position in positions:
        current = dict(position)
        if (
            str(current.get("exchange", "")).strip().lower() == tick_exchange
            and str(current.get("symbol", "")).strip().upper() == tick_symbol
            and _forward_position_is_active(current)
        ):
            managed = position_management_engine.apply_price(
                _forward_position_to_virtual_trade(current, now),
                price=float(price),
                now=now,
                target_fill_price="mark",
            )
            current = _forward_position_from_virtual_trade(current, managed.trade)
            updated_trades.append(managed.trade)
            realized_delta += _decimal(managed.realized_pnl_delta, Decimal("0"))
            if managed.closed:
                closed_count += 1
                closed_trades.append(managed.trade)
        if _forward_position_is_active(current):
            total_unrealized += _decimal(current.get("unrealized_pnl"), Decimal("0"))
        updated_positions.append(current)

    account = _forward_account_from_runtime(run)
    account["realized_pnl"] += realized_delta
    account["unrealized_pnl"] = total_unrealized
    account["open_positions"] = max(0, account["open_positions"] - closed_count)
    account["closed_positions"] += closed_count
    account["equity"] = account["balance"] + account["realized_pnl"] + total_unrealized
    return ForwardMarkToMarketResult(
        runtime_state={
            "forward_account": _serialize_forward_account(account),
            "forward_positions": updated_positions,
        },
        updated_trades=updated_trades,
        closed_trades=closed_trades,
    )


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
    risk_settings = _forward_risk_settings(run)
    return ManualConfirmRequest(
        mode="virtual",
        user_id=_matrix_user_id(run),
        auto_enter_on_confirmation=auto_enter_on_confirmation,
        account_balance=float(_decimal(matrix.get("initial_capital"), Decimal("1000"))),
        risk_percent=risk_settings.risk_per_trade_percent,
        fee_rate=float(_decimal(matrix.get("fee_rate"), Decimal("0"))),
        slippage_bps=float(_decimal(matrix.get("slippage_bps"), Decimal("0"))),
        max_open_positions=_forward_max_concurrent_positions(run),
        metadata={
            "strategy_test_run_id": str(run.run_id),
            "test_type": "forward_virtual",
        },
    )


def _forward_execution_policy_decision(
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    request: ManualConfirmRequest,
    *,
    reference_price: float | None = None,
) -> ExecutionPolicyDecision:
    policy = _execution_policy_params(run)
    risk_settings = _forward_risk_settings(run)
    return execution_policy_resolver.resolve(
        ExecutionPolicyContext(
            side="short" if signal.direction == "short" else "long",
            current_price=(
                reference_price
                if reference_price is not None and reference_price > 0
                else _forward_policy_price(run, signal)
            ),
            entry_min=signal.entry_min,
            entry_max=signal.entry_max,
            stop_loss=signal.stop_loss,
            take_profit=_forward_policy_take_profit(signal),
            min_rr_ratio=float(signal.min_rr_ratio or risk_settings.min_rr_ratio or 0.0),
            preferred_mode=_execution_policy_mode(policy.get("mode") or policy.get("preferred_mode")),
            allow_pending_retest=_bool_policy_param(policy, "allow_pending_retest", False),
            allow_probe=_bool_policy_param(policy, "allow_probe", False),
            max_late_entry_deviation_bps=_float_policy_param(policy, "max_late_entry_deviation_bps", 100.0),
            max_probe_deviation_bps=_float_policy_param(policy, "max_probe_deviation_bps", 10.0),
            slippage_bps=request.slippage_bps,
            max_slippage_bps=_float_policy_param(policy, "max_slippage_bps", request.max_virtual_slippage_bps),
            spread_bps=_optional_float_policy_param(policy, "spread_bps"),
            max_spread_bps=_float_policy_param(policy, "max_spread_bps", risk_settings.max_spread_bps),
            orderbook_depth_usd=_optional_float_policy_param(policy, "orderbook_depth_usd"),
            requested_size_usd=_virtual_size_usd(request),
            min_depth_to_size_ratio=_float_policy_param(policy, "min_depth_to_size_ratio", 1.0),
        )
    )


def _request_with_execution_policy_reference(
    request: ManualConfirmRequest,
    decision: ExecutionPolicyDecision,
    *,
    reference_price: float,
) -> ManualConfirmRequest:
    decision_metadata = {
        **decision.to_dict(),
        "reference_price": reference_price,
    }
    metadata = {
        **dict(request.metadata or {}),
        "execution_policy_decision": decision_metadata,
        "reference_price": reference_price,
    }
    return request.model_copy(update={"metadata": metadata})


def _gate_waiting_for_execution_policy(
    gate: SignalExecutionGateSnapshot,
    decision: ExecutionPolicyDecision,
) -> SignalExecutionGateSnapshot:
    reason = _execution_policy_gate_reason(decision, severity="warning")
    return gate.model_copy(
        update={
            "status": "warning",
            "feed_kind": "watchlist",
            "can_notify": False,
            "can_enter_now": False,
            "can_arm_pending": True,
            "can_show_in_execution_feed": False,
            "warnings": [*gate.warnings, reason],
            "metadata": {
                **gate.metadata,
                "execution_policy": decision.to_dict(),
            },
        }
    )


def _gate_blocked_by_execution_policy(
    gate: SignalExecutionGateSnapshot,
    decision: ExecutionPolicyDecision,
) -> SignalExecutionGateSnapshot:
    reason = _execution_policy_gate_reason(decision, severity="blocker")
    return gate.model_copy(
        update={
            "status": "blocked",
            "feed_kind": "blocked",
            "can_notify": False,
            "can_enter_now": False,
            "can_arm_pending": False,
            "can_show_in_execution_feed": False,
            "reasons": [*gate.reasons, reason],
            "metadata": {
                **gate.metadata,
                "execution_policy": decision.to_dict(),
            },
        }
    )


def _execution_policy_gate_reason(
    decision: ExecutionPolicyDecision,
    *,
    severity: Literal["blocker", "warning"],
) -> SignalExecutionGateReason:
    return SignalExecutionGateReason(
        code=decision.reason_code,
        severity=severity,
        source="execution_policy",
        message=decision.message,
        metadata=decision.to_dict(),
    )


def _forward_portfolio_decision(
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    request: ManualConfirmRequest,
) -> PortfolioRiskDecision:
    account = _forward_account_from_runtime(run)
    risk_settings = _forward_risk_settings(run)
    open_positions = _open_forward_positions(run)
    equity = float(account["equity"])
    proposed_risk_amount = _virtual_size_usd(request) * float(request.risk_percent or 1.0) / 100
    return portfolio_risk_service.evaluate(
        PortfolioRiskContext(
            account_equity=equity,
            proposed_risk_amount=proposed_risk_amount,
            open_risk_amount=_forward_positions_risk(open_positions),
            symbol_open_risk_amount=_forward_positions_risk(open_positions, symbol=signal.symbol),
            strategy_open_risk_amount=_forward_positions_risk(open_positions, strategy=signal.strategy),
            daily_loss_amount=max(0.0, -float(account["realized_pnl"])),
            account_drawdown_percent=_forward_account_drawdown_percent(account),
            open_position_count=len(open_positions),
            strategy_losses_today=_forward_strategy_losses_today(run, signal.strategy),
        ),
        PortfolioRiskLimits(
            max_open_risk_percent=risk_settings.max_open_risk_percent,
            max_symbol_risk_percent=risk_settings.max_symbol_risk_percent,
            max_strategy_exposure_percent=risk_settings.max_strategy_exposure_percent,
            max_correlated_risk_percent=0.0,
            max_daily_loss_percent=risk_settings.max_daily_loss_percent,
            max_account_drawdown_percent=risk_settings.max_account_drawdown_percent,
            max_concurrent_positions=request.max_open_positions,
            max_strategy_losses_per_day=risk_settings.max_strategy_losses_per_day,
        ),
    )


def _request_with_portfolio_size(
    request: ManualConfirmRequest,
    decision: PortfolioRiskDecision,
) -> ManualConfirmRequest:
    metadata = {
        **request.metadata,
        "portfolio_risk": _portfolio_decision_metadata(decision),
    }
    return request.model_copy(
        update={
            "size_usd": max(0.0, _virtual_size_usd(request) * decision.size_multiplier),
            "metadata": metadata,
        }
    )


def _gate_blocked_by_portfolio(
    gate: SignalExecutionGateSnapshot,
    decision: PortfolioRiskDecision,
) -> SignalExecutionGateSnapshot:
    reason = _portfolio_gate_reason(decision, severity="blocker")
    return gate.model_copy(
        update={
            "status": "blocked",
            "feed_kind": "blocked",
            "can_notify": False,
            "can_enter_now": False,
            "can_arm_pending": False,
            "can_show_in_execution_feed": False,
            "reasons": [*gate.reasons, reason],
            "metadata": {
                **gate.metadata,
                "portfolio_risk": _portfolio_decision_metadata(decision),
            },
        }
    )


def _gate_with_portfolio_warning(
    gate: SignalExecutionGateSnapshot,
    decision: PortfolioRiskDecision,
) -> SignalExecutionGateSnapshot:
    reason = _portfolio_gate_reason(decision, severity="warning")
    return gate.model_copy(
        update={
            "warnings": [*gate.warnings, reason],
            "metadata": {
                **gate.metadata,
                "portfolio_risk": _portfolio_decision_metadata(decision),
            },
        }
    )


def _portfolio_gate_reason(
    decision: PortfolioRiskDecision,
    *,
    severity: Literal["blocker", "warning"],
) -> SignalExecutionGateReason:
    return SignalExecutionGateReason(
        code=decision.reason_code,
        severity=severity,
        source="portfolio_risk",
        message=decision.message,
        metadata=_portfolio_decision_metadata(decision),
    )


def _portfolio_decision_metadata(decision: PortfolioRiskDecision) -> dict[str, Any]:
    return {
        "action": decision.action,
        "reason_code": decision.reason_code,
        "reason_codes": list(decision.reason_codes),
        "proposed_risk_amount": decision.proposed_risk_amount,
        "approved_risk_amount": decision.approved_risk_amount,
        "size_multiplier": decision.size_multiplier,
        "metrics": dict(decision.metrics),
    }


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
        created_at=exit_time or entry_time,
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


def _strategy_test_close_metrics_from_virtual_trade(
    *,
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    trade: VirtualTrade,
) -> list[StrategyTestMetricRow]:
    created_at = (trade.closed_at or trade.updated_at).astimezone(timezone.utc)
    metadata = {
        "signal_id": signal.id,
        "trade_id": trade.id,
        "test_type": "forward_virtual",
        "close_reason": trade.close_reason,
        "outcome": trade.result or trade.status,
    }
    rows = [
        _strategy_test_forward_metric_row(
            run=run,
            signal=signal,
            metric_code="forward_closed_trades",
            metric_value=1.0,
            created_at=created_at,
            metadata=metadata,
        ),
        _strategy_test_forward_metric_row(
            run=run,
            signal=signal,
            metric_code="realized_pnl",
            metric_value=float(trade.realized_pnl),
            created_at=created_at,
            metadata=metadata,
        ),
    ]
    result = str(trade.result or "").strip().lower()
    if result == "win":
        rows.append(
            _strategy_test_forward_metric_row(
                run=run,
                signal=signal,
                metric_code="forward_wins",
                metric_value=1.0,
                created_at=created_at,
                metadata=metadata,
            )
        )
    elif result == "loss":
        rows.append(
            _strategy_test_forward_metric_row(
                run=run,
                signal=signal,
                metric_code="forward_losses",
                metric_value=1.0,
                created_at=created_at,
                metadata=metadata,
            )
        )
    if trade.pnl_percent is not None:
        rows.append(
            _strategy_test_forward_metric_row(
                run=run,
                signal=signal,
                metric_code="pnl_percent",
                metric_value=float(trade.pnl_percent),
                created_at=created_at,
                metadata=metadata,
            )
        )
    return rows


def _strategy_test_forward_metric_row(
    *,
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    metric_code: str,
    metric_value: float,
    created_at: datetime,
    metadata: dict[str, Any],
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
        metric_code=metric_code,
        metric_value=metric_value,
        sample_size=1,
        metadata=dict(metadata),
        created_at=created_at,
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


def _forward_signal_id(run: StrategyTestRunResponse, signal: StrategySignal) -> str:
    suffix = uuid5(
        NAMESPACE_URL,
        "|".join(
            [
                str(run.run_id),
                signal.exchange.strip().lower(),
                signal.symbol.strip().upper(),
                signal.strategy,
                signal.timeframe,
                signal.direction,
                str(signal.timestamp),
            ]
        ),
    ).hex
    return f"forward_sig_{suffix}"


def _forward_signal_key(run: StrategyTestRunResponse, signal: RadarSignal) -> str:
    return "|".join(
        [
            str(run.run_id),
            signal.exchange.strip().lower(),
            signal.symbol.strip().upper(),
            signal.strategy,
            signal.timeframe,
            signal.direction,
            signal.created_at.astimezone(timezone.utc).isoformat(),
        ]
    )


def _forward_signal_processing_key(run: StrategyTestRunResponse, signal: RadarSignal) -> str:
    signal_id = str(signal.id or "").strip()
    if signal_id:
        return signal_id
    return _forward_signal_key(run, signal)


def _forward_signal_was_processed(run: StrategyTestRunResponse, processing_key: str) -> bool:
    return processing_key in set(_forward_processed_signal_keys(run))


def _forward_processed_signal_runtime_patch(
    run: StrategyTestRunResponse,
    processing_key: str,
) -> dict[str, Any]:
    keys = [key for key in _forward_processed_signal_keys(run) if key != processing_key]
    keys.append(processing_key)
    return {"processed_signal_keys": keys[-FORWARD_PROCESSED_SIGNAL_RETENTION_LIMIT:]}


def _forward_processed_signal_keys(run: StrategyTestRunResponse) -> list[str]:
    raw_keys = run.runtime_state.get("processed_signal_keys")
    if not isinstance(raw_keys, list):
        return []
    return [str(key) for key in raw_keys if str(key or "").strip()]


def _forward_trade_id(signal_id: str) -> str:
    if signal_id.startswith("forward_sig_"):
        return f"forward_trade_{signal_id.removeprefix('forward_sig_')}"
    return f"forward_trade_{uuid5(NAMESPACE_URL, signal_id).hex}"


def _forward_position_to_virtual_trade(position: dict[str, Any], now: datetime) -> VirtualTrade:
    take_profit = _forward_take_profit(position)
    entry_price = float(_decimal(position.get("entry_price"), Decimal("0")))
    quantity = float(_decimal(position.get("quantity"), Decimal("0")))
    initial_quantity = float(_decimal(position.get("initial_quantity"), Decimal(str(quantity))))
    remaining_quantity = float(_decimal(position.get("remaining_quantity"), Decimal(str(quantity))))
    opened_at = _forward_position_datetime(position.get("opened_at"), now)
    return VirtualTrade(
        id=str(position.get("trade_id") or position.get("id") or "forward_trade"),
        user_id=str(position.get("user_id") or _matrix_user_id_from_position(position)),
        signal_id=str(position.get("signal_id") or "forward_signal"),
        exchange=str(position.get("exchange") or "bybit"),
        symbol=str(position.get("symbol") or "BTCUSDT"),
        strategy=str(position.get("strategy") or "unknown"),
        timeframe=str(position.get("timeframe") or "15m"),
        side="short" if str(position.get("side") or "long").lower() == "short" else "long",
        entry_price=entry_price,
        current_price=float(_decimal(position.get("current_price"), Decimal(str(entry_price)))),
        size_usd=float(_decimal(position.get("size_usd"), Decimal("0"))),
        quantity=quantity,
        leverage=int(_decimal(position.get("leverage"), Decimal("1"))),
        risk_percent=float(_decimal(position.get("risk_percent"), Decimal("1"))),
        risk_amount=float(_decimal(position.get("risk_amount"), Decimal("0"))),
        stop_loss=float(_decimal(position.get("stop_loss"), Decimal("0"))),
        take_profit=take_profit,
        fees=float(_decimal(position.get("fees"), Decimal("0"))),
        status=str(position.get("status") or "open"),
        close_reason=position.get("close_reason"),
        realized_pnl=float(_decimal(position.get("realized_pnl"), Decimal("0"))),
        unrealized_pnl=float(_decimal(position.get("unrealized_pnl"), Decimal("0"))),
        initial_quantity=initial_quantity,
        remaining_quantity=remaining_quantity,
        closed_quantity=float(
            _decimal(
                position.get("closed_quantity"),
                Decimal(str(initial_quantity - remaining_quantity)),
            )
        ),
        initial_size_usd=float(
            _decimal(
                position.get("initial_size_usd"),
                _decimal(position.get("size_usd"), Decimal("0")),
            )
        ),
        remaining_size_usd=float(_decimal(position.get("remaining_size_usd"), Decimal("0"))),
        current_stop_loss=_optional_float(position.get("current_stop_loss")),
        target_states=_forward_target_states(position, take_profit),
        opened_at=opened_at,
        updated_at=now,
    )


def _forward_position_from_virtual_trade(position: dict[str, Any], trade: VirtualTrade) -> dict[str, Any]:
    updated = dict(position)
    updated.update(
        {
            "status": trade.status,
            "close_reason": trade.close_reason,
            "current_price": _decimal_string(_decimal(trade.current_price, Decimal("0"))),
            "realized_pnl": _decimal_string(_decimal(trade.realized_pnl, Decimal("0"))),
            "unrealized_pnl": _decimal_string(_decimal(trade.unrealized_pnl, Decimal("0"))),
            "initial_quantity": _decimal_string(_decimal(trade.initial_quantity, Decimal("0"))),
            "remaining_quantity": _decimal_string(_decimal(trade.remaining_quantity, Decimal("0"))),
            "closed_quantity": _decimal_string(_decimal(trade.closed_quantity, Decimal("0"))),
            "initial_size_usd": _decimal_string(_decimal(trade.initial_size_usd, Decimal("0"))),
            "remaining_size_usd": _decimal_string(_decimal(trade.remaining_size_usd, Decimal("0"))),
            "current_stop_loss": (
                _decimal_string(_decimal(trade.current_stop_loss, Decimal("0")))
                if trade.current_stop_loss is not None
                else None
            ),
            "target_states": [target.model_dump(mode="json") for target in trade.target_states],
            "lifecycle_events": [event.model_dump(mode="json") for event in trade.lifecycle_events],
        }
    )
    if trade.exit_price is not None:
        updated["exit_price"] = _decimal_string(_decimal(trade.exit_price, Decimal("0")))
    if trade.closed_at is not None:
        updated["closed_at"] = trade.closed_at.astimezone(timezone.utc).isoformat()
    return updated


def _forward_position_is_active(position: dict[str, Any]) -> bool:
    return str(position.get("status") or "open") in {"open", "partially_closed"}


def _forward_take_profit(position: dict[str, Any]) -> list[float]:
    raw_targets = position.get("take_profit")
    values = raw_targets if isinstance(raw_targets, list) else []
    return [float(price) for price in (_decimal(value, Decimal("0")) for value in values) if price > 0]


def _forward_target_states(
    position: dict[str, Any],
    take_profit: list[float],
) -> list[VirtualTradeTargetState]:
    raw_states = position.get("target_states")
    if isinstance(raw_states, list) and raw_states:
        return [VirtualTradeTargetState.model_validate(state) for state in raw_states if isinstance(state, dict)]
    if not take_profit:
        return []
    if len(take_profit) == 1:
        return [
            VirtualTradeTargetState(
                label="TP1",
                price=take_profit[0],
                close_percent=100.0,
                action="full_close",
            )
        ]
    partial_percent = 50.0 if len(take_profit) == 2 else 100.0 / len(take_profit)
    states = [
        VirtualTradeTargetState(
            label=f"TP{index + 1}",
            price=price,
            close_percent=partial_percent,
            action="partial_close",
        )
        for index, price in enumerate(take_profit[:-1])
    ]
    states.append(
        VirtualTradeTargetState(
            label=f"TP{len(take_profit)}",
            price=take_profit[-1],
            close_percent=100.0,
            action="full_close",
        )
    )
    return states


def _forward_position_datetime(value: Any, default: datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return default
    return default


def _matrix_user_id_from_position(position: dict[str, Any]) -> str:
    return str(position.get("user_id") or "forward_user")


def _entry_price(signal: RadarSignal, *, request: ManualConfirmRequest | None = None) -> float:
    lower, upper = _entry_zone_prices(signal)
    explicit = _explicit_entry_price(signal, request=request, lower=lower, upper=upper)
    if explicit is not None:
        return float(explicit)
    if lower is not None and upper is not None:
        return float((lower + upper) / Decimal("2"))
    if lower is not None:
        return float(lower)
    if upper is not None:
        return float(upper)
    for value in (signal.take_profit_1, signal.stop_loss):
        price = _decimal(value, Decimal("0"))
        if price > 0:
            return float(price)
    return 1.0


def _entry_zone_prices(signal: RadarSignal) -> tuple[Decimal | None, Decimal | None]:
    entry_min = _positive_decimal(signal.entry_min)
    entry_max = _positive_decimal(signal.entry_max)
    if entry_min is not None and entry_max is not None and entry_max < entry_min:
        return entry_max, entry_min
    return entry_min, entry_max


def _explicit_entry_price(
    signal: RadarSignal,
    *,
    request: ManualConfirmRequest | None,
    lower: Decimal | None,
    upper: Decimal | None,
) -> Decimal | None:
    metadata_sources: list[dict[str, Any]] = []
    if request is not None and isinstance(request.metadata, dict):
        pending_price = _pending_touch_metadata_price(request.metadata, lower=lower, upper=upper)
        if pending_price is not None:
            return pending_price
        metadata_sources.append(request.metadata)
    gate = signal.execution_gate
    if gate is not None and isinstance(gate.metadata, dict):
        metadata_sources.append(gate.metadata)

    for metadata in metadata_sources:
        price = _metadata_fill_price(metadata)
        if price is not None:
            return price
    return None


def _pending_touch_metadata_price(
    metadata: dict[str, Any],
    *,
    lower: Decimal | None,
    upper: Decimal | None,
) -> Decimal | None:
    trigger = metadata.get("pending_entry_trigger")
    if not isinstance(trigger, dict):
        return None
    price = _first_metadata_price(trigger, ("touch_price", "trigger_price", "current_price", "price"))
    if price is None:
        return None
    return _clamp_price_to_zone(price, lower=lower, upper=upper)


def _metadata_fill_price(metadata: dict[str, Any]) -> Decimal | None:
    direct = _first_metadata_price(
        metadata,
        (
            "fill_price",
            "filled_price",
            "avg_fill_price",
            "average_price",
            "estimated_fill_price",
        ),
    )
    if direct is not None:
        return direct

    for key in (
        "execution_policy_decision",
        "execution_policy",
        "fill",
        "execution_fill",
        "execution",
        "virtual_execution",
        "market_snapshot",
    ):
        nested = metadata.get(key)
        if isinstance(nested, dict):
            price = _metadata_fill_price(nested)
            if price is not None:
                return price
    return _first_metadata_price(metadata, ("reference_price", "execution_price", "current_price"))


def _first_metadata_price(metadata: dict[str, Any], keys: Sequence[str]) -> Decimal | None:
    for key in keys:
        price = _positive_decimal(metadata.get(key))
        if price is not None:
            return price
    return None


def _positive_decimal(value: Any) -> Decimal | None:
    price = _decimal(value, Decimal("0"))
    return price if price > 0 else None


def _clamp_price_to_zone(
    price: Decimal,
    *,
    lower: Decimal | None,
    upper: Decimal | None,
) -> Decimal:
    if lower is not None and price < lower:
        return lower
    if upper is not None and price > upper:
        return upper
    return price


def _virtual_size_usd(request: ManualConfirmRequest) -> float:
    if request.size_usd is not None:
        return float(request.size_usd)
    account_balance = _decimal(request.account_balance, Decimal("100"))
    return float(max(Decimal("1"), min(account_balance, Decimal("100"))))


def _signal_timestamp_to_utc(value: int | float) -> datetime:
    timestamp = float(value)
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _forward_account_from_runtime(run: StrategyTestRunResponse) -> dict[str, Any]:
    account = run.runtime_state.get("forward_account")
    if not isinstance(account, dict):
        initial = _decimal(run.requested_matrix.get("initial_capital"), Decimal("1000"))
        account = _serialize_forward_account(
            {
                "initial_capital": initial,
                "balance": initial,
                "equity": initial,
                "realized_pnl": Decimal("0"),
                "unrealized_pnl": Decimal("0"),
                "fees": Decimal("0"),
                "slippage": Decimal("0"),
                "open_positions": 0,
                "closed_positions": 0,
            }
        )
    return {
        "initial_capital": _decimal(account.get("initial_capital"), Decimal("1000")),
        "balance": _decimal(account.get("balance"), Decimal("1000")),
        "equity": _decimal(account.get("equity"), Decimal("1000")),
        "realized_pnl": _decimal(account.get("realized_pnl"), Decimal("0")),
        "unrealized_pnl": _decimal(account.get("unrealized_pnl"), Decimal("0")),
        "fees": _decimal(account.get("fees"), Decimal("0")),
        "slippage": _decimal(account.get("slippage"), Decimal("0")),
        "open_positions": _counter(account, "open_positions"),
        "closed_positions": _counter(account, "closed_positions"),
    }


def _serialize_forward_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "initial_capital": _decimal_string(_decimal(account.get("initial_capital"), Decimal("1000"))),
        "balance": _decimal_string(_decimal(account.get("balance"), Decimal("1000"))),
        "equity": _decimal_string(_decimal(account.get("equity"), Decimal("1000"))),
        "realized_pnl": _decimal_string(_decimal(account.get("realized_pnl"), Decimal("0"))),
        "unrealized_pnl": _decimal_string(_decimal(account.get("unrealized_pnl"), Decimal("0"))),
        "fees": _decimal_string(_decimal(account.get("fees"), Decimal("0"))),
        "slippage": _decimal_string(_decimal(account.get("slippage"), Decimal("0"))),
        "open_positions": int(account.get("open_positions") or 0),
        "closed_positions": int(account.get("closed_positions") or 0),
    }


def _forward_positions(run: StrategyTestRunResponse) -> list[dict[str, Any]]:
    raw_positions = run.runtime_state.get("forward_positions")
    if not isinstance(raw_positions, list):
        return []
    return [dict(position) for position in raw_positions if isinstance(position, dict)]


def _open_forward_positions(run: StrategyTestRunResponse) -> list[dict[str, Any]]:
    return [
        position
        for position in _forward_positions(run)
        if str(position.get("status") or "open").lower() == "open"
    ]


def _forward_positions_risk(
    positions: Sequence[dict[str, Any]],
    *,
    symbol: str | None = None,
    strategy: str | None = None,
) -> float:
    symbol_key = symbol.strip().upper() if symbol is not None else None
    strategy_key = strategy.strip() if strategy is not None else None
    return float(
        sum(
            _forward_position_risk(position)
            for position in positions
            if (symbol_key is None or str(position.get("symbol") or "").strip().upper() == symbol_key)
            and (strategy_key is None or str(position.get("strategy") or "").strip() == strategy_key)
        )
    )


def _forward_position_risk(position: dict[str, Any]) -> Decimal:
    risk_amount = _decimal(position.get("risk_amount"), Decimal("0"))
    if risk_amount > 0:
        return risk_amount
    size_usd = _decimal(position.get("size_usd"), Decimal("0"))
    risk_percent = _decimal(position.get("risk_percent"), Decimal("0"))
    if size_usd > 0 and risk_percent > 0:
        return size_usd * risk_percent / Decimal("100")
    return Decimal("0")


def _forward_strategy_losses_today(run: StrategyTestRunResponse, strategy: str) -> int:
    strategy_key = strategy.strip()
    losses = 0
    for position in _forward_positions(run):
        if str(position.get("strategy") or "").strip() != strategy_key:
            continue
        if str(position.get("status") or "open").lower() == "open":
            continue
        if _decimal(position.get("realized_pnl"), Decimal("0")) < 0:
            losses += 1
    return losses


def _forward_account_drawdown_percent(account: dict[str, Any]) -> float:
    initial = _decimal(account.get("initial_capital"), Decimal("0"))
    equity = _decimal(account.get("equity"), Decimal("0"))
    if initial <= 0 or equity >= initial:
        return 0.0
    return float((initial - equity) / initial * Decimal("100"))


def _forward_risk_settings(run: StrategyTestRunResponse) -> RiskManagementSettings:
    params = _run_params(run)
    raw_settings = params.get("risk_settings")
    if isinstance(raw_settings, dict):
        return RiskManagementSettings(**raw_settings)
    return RiskManagementSettings()


def _forward_max_concurrent_positions(run: StrategyTestRunResponse) -> int:
    params = _run_params(run)
    for key in ("max_concurrent_positions", "max_open_positions"):
        value = params.get(key)
        if value is None:
            continue
        try:
            return max(1, min(100, int(value)))
        except (TypeError, ValueError):
            continue
    return 3


def _run_params(run: StrategyTestRunResponse) -> dict[str, Any]:
    params = run.requested_matrix.get("params")
    return dict(params) if isinstance(params, dict) else {}


def _execution_policy_params(run: StrategyTestRunResponse) -> dict[str, Any]:
    raw = _run_params(run).get("execution_policy")
    return dict(raw) if isinstance(raw, dict) else {}


def _forward_policy_price(run: StrategyTestRunResponse, signal: RadarSignal) -> float:
    price = _optional_float(run.runtime_state.get("last_price"))
    return price if price is not None and price > 0 else _entry_price(signal)


def _forward_policy_take_profit(signal: RadarSignal) -> float | None:
    return signal.take_profit_1 or signal.take_profit_2


def _execution_policy_mode(value: Any) -> Any | None:
    return value if value in {"limit", "market", "pending_retest", "late_entry", "probe", "skip"} else None


def _bool_policy_param(params: dict[str, Any], key: str, default: bool) -> bool:
    value = params.get(key)
    return default if value is None else bool(value)


def _float_policy_param(params: dict[str, Any], key: str, default: float) -> float:
    value = _optional_float(params.get(key))
    return default if value is None else value


def _optional_float_policy_param(params: dict[str, Any], key: str) -> float | None:
    return _optional_float(params.get(key))


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_gate_reason_code(gate: SignalExecutionGateSnapshot) -> str | None:
    for reason in [*gate.reasons, *gate.warnings]:
        if reason.code:
            return reason.code
    return None


def _gate_has_reason_source(gate: SignalExecutionGateSnapshot, sources: set[str]) -> bool:
    return any(reason.source in sources for reason in [*gate.reasons, *gate.warnings])


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


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, Decimal("0"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
