from __future__ import annotations

import asyncio
import contextlib
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Sequence
from uuid import UUID, uuid4

from app.schemas.market import MarketData
from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot, StrategySignal
from app.schemas.trade import ManualConfirmRequest, VirtualTrade
from app.services.strategy_testing.forward_runtime import ForwardRuntimeResult, ForwardStrategyTestRuntime
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTrade,
)
from app.workers.forward_strategy_test_worker import ForwardStrategyTestWorker


RUN_ID = UUID("11111111-2222-4333-8444-555555555555")
USER_ID = "forward_user"
NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


class ForwardStrategyTestRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_strategy_signal_opens_virtual_trade_and_records_runtime_state(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        signal_writer = _SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True)))
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=trade_store,
            signal_writer=signal_writer,
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal())

        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(result.opened_trades, 1)
        self.assertEqual(result.metrics_written, 1)
        self.assertEqual(len(virtual_trading.open_calls), 1)
        self.assertIsInstance(virtual_trading.open_calls[0][1], ManualConfirmRequest)
        self.assertEqual(virtual_trading.open_calls[0][1].mode, "virtual")
        self.assertEqual(virtual_trading.open_calls[0][1].user_id, USER_ID)
        self.assertEqual(len(trade_store.trades), 1)
        self.assertEqual(len(trade_store.metrics), 1)
        self.assertEqual(trade_store.trades[0].run_id, RUN_ID)
        self.assertEqual(trade_store.trades[0].trade_id, "trade_1")
        self.assertEqual(trade_store.metrics[0].metric_code, "forward_opened_trades")
        runtime_state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        self.assertEqual(runtime_state["processed_signals"], 1)
        self.assertEqual(runtime_state["opened_trades"], 1)
        self.assertEqual(runtime_state["metrics_written"], 1)
        self.assertEqual(runtime_state["last_signal_id"], "sig_1")
        self.assertIsNotNone(run_store.get_run(RUN_ID).run.last_heartbeat_at)  # type: ignore[union-attr]

    async def test_process_strategy_signal_filters_by_requested_matrix(self) -> None:
        run_store = _ForwardRunStore([_run(pairs=[StrategyTestPair(exchange="bybit", symbol="ETHUSDT")])])
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal(symbol="BTCUSDT"))

        self.assertEqual(result.signals_processed, 0)
        self.assertEqual(result.signals_skipped, 1)
        self.assertEqual(virtual_trading.open_calls, [])

    async def test_process_market_tick_delegates_to_scanner_and_processes_returned_signals(self) -> None:
        scanner = _Scanner([_strategy_signal()])
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=_ForwardRunStore([_run()]),
            trade_store=_RecordingTradeStore(),
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
            scanner=scanner,
        )
        tick = MarketData(exchange="bybit", symbol="BTCUSDT", price=100.0, volume=1.0, timestamp=1_780_000_000)

        result = await runtime.process_market_tick(tick)

        self.assertEqual(scanner.ticks, [tick])
        self.assertEqual(result.ticks_processed, 1)
        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(result.opened_trades, 1)

    async def test_stopping_run_is_cancelled_after_current_iteration_and_cancelled_runs_are_ignored(self) -> None:
        stopping = _run(status="stopping")
        cancelled = _run(run_id=uuid4(), status="cancelled")
        run_store = _ForwardRunStore([stopping, cancelled])
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal())

        self.assertEqual(result.cancelled_runs, 1)
        self.assertEqual(run_store.get_run(stopping.run_id).run.status, "cancelled")  # type: ignore[union-attr]
        self.assertEqual(run_store.get_run(cancelled.run_id).run.status, "cancelled")  # type: ignore[union-attr]
        self.assertEqual(virtual_trading.open_calls, [])


class ForwardStrategyTestWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_strategy_signal_delegates_to_runtime_and_updates_last_result(self) -> None:
        runtime = _WorkerSignalRuntime()
        worker = ForwardStrategyTestWorker(runtime=runtime)  # type: ignore[arg-type]
        signal = _strategy_signal()

        result = await worker.process_strategy_signal(signal)

        self.assertIs(result, worker.last_result)
        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(runtime.signals, [signal])

    async def test_heartbeat_exception_sets_last_result_errors_and_keeps_loop_running(self) -> None:
        runtime = _FailingHeartbeatRuntime()
        worker = ForwardStrategyTestWorker(runtime=runtime)  # type: ignore[arg-type]
        worker._interval_seconds = 0.01
        task = asyncio.create_task(worker._run())

        try:
            await _wait_until(lambda: runtime.heartbeat_calls >= 2 or task.done())

            self.assertFalse(task.done())
            self.assertGreaterEqual(runtime.heartbeat_calls, 2)
            self.assertEqual(worker.last_result.errors, ["heartbeat failed"])
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await task


def _run(
    *,
    run_id: UUID = RUN_ID,
    status: StrategyTestRunStatus = "running",
    pairs: list[StrategyTestPair] | None = None,
) -> StrategyTestRunResponse:
    request = StrategyTestRunRequest(
        user_id=USER_ID,
        test_type="forward_virtual",
        strategies=["trend_pullback_continuation"],
        pairs=pairs or [StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
        timeframes=["15m"],
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
        mode="research_virtual",
        initial_capital=Decimal("1000"),
        tags=["forward"],
    )
    return StrategyTestRunResponse(
        run_id=run_id,
        status=status,
        test_type="forward_virtual",
        requested_matrix=_requested_matrix(request),
        runtime_state={},
        created_at=NOW,
        started_at=NOW if status in {"running", "stopping"} else None,
        last_heartbeat_at=NOW if status in {"running", "stopping"} else None,
    )


def _strategy_signal(*, symbol: str = "BTCUSDT") -> StrategySignal:
    return StrategySignal(
        exchange="bybit",
        symbol=symbol,
        strategy="trend_pullback_continuation",
        direction="LONG",
        confidence=0.82,
        timestamp=1_780_000_000,
        score=82,
        timeframe="15m",
        status="actionable",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=115.0,
        risk_reward=2.0,
    )


def _radar_signal(*, execution_gate: SignalExecutionGateSnapshot) -> RadarSignal:
    return RadarSignal(
        id="sig_1",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        risk_reward=2.0,
        status="actionable",
        score=82,
        timeframe="15m",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=115.0,
        created_at=NOW,
        updated_at=NOW,
        execution_gate=execution_gate,
    )


def _gate(*, can_enter_now: bool = False, can_arm_pending: bool = False) -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed",
        feed_kind="execution_signal" if can_enter_now else "watchlist",
        can_notify=can_enter_now,
        can_enter_now=can_enter_now,
        can_arm_pending=can_arm_pending,
        can_show_in_execution_feed=can_enter_now,
    )


def _trade(signal_id: str = "sig_1") -> VirtualTrade:
    return VirtualTrade(
        id="trade_1",
        user_id=USER_ID,
        signal_id=signal_id,
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        timeframe="15m",
        side="long",
        entry_price=100.5,
        current_price=100.5,
        size_usd=100.0,
        quantity=1.0,
        leverage=1,
        risk_percent=1.0,
        stop_loss=95.0,
        take_profit=[110.0, 115.0],
        opened_at=NOW,
        updated_at=NOW,
    )


def _requested_matrix(request: StrategyTestRunRequest) -> dict[str, Any]:
    return {
        "user_id": request.user_id,
        "test_type": request.test_type,
        "mode": request.mode,
        "strategies": request.strategies,
        "pairs": [pair.model_dump(mode="json") for pair in request.pairs],
        "timeframes": request.timeframes,
        "start_at": request.start_at,
        "end_at": request.end_at,
        "initial_capital": request.initial_capital,
        "fee_rate": request.fee_rate,
        "slippage_bps": request.slippage_bps,
        "same_candle_policy": request.same_candle_policy,
        "params": request.params,
        "metric_set": request.metric_set,
        "tags": request.tags,
        "scenario_count": len(request.strategies) * len(request.pairs) * len(request.timeframes),
    }


class _ForwardRunStore:
    def __init__(self, runs: Sequence[StrategyTestRunResponse]) -> None:
        self._runs = {run.run_id: StrategyTestRunDetailResponse(run=run) for run in runs}

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        runs = list(self._runs.values())
        if user_id is not None:
            runs = [detail for detail in runs if detail.run.requested_matrix["user_id"] == user_id]
        if status is not None:
            runs = [detail for detail in runs if detail.run.status == status]
        return runs[:limit]

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        return self._runs.get(run_id)

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated = detail.run.model_copy(update={"status": "cancelled", "last_heartbeat_at": NOW})
        self._runs[run_id] = StrategyTestRunDetailResponse(run=updated)
        return self._runs[run_id]

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated_state = {**detail.run.runtime_state, **runtime_state}
        update: dict[str, Any] = {"runtime_state": updated_state}
        if heartbeat:
            update["last_heartbeat_at"] = NOW
        self._runs[run_id] = StrategyTestRunDetailResponse(run=detail.run.model_copy(update=update))
        return self._runs[run_id]


class _RecordingTradeStore:
    def __init__(self) -> None:
        self.trades: list[StrategyTestTrade] = []
        self.metrics: list[StrategyTestMetricRow] = []

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.trades.extend(trades)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.metrics.extend(rows)


class _SignalWriter:
    def __init__(self, signal: RadarSignal) -> None:
        self.signal = signal
        self.calls: list[StrategySignal] = []

    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> tuple[RadarSignal, bool]:
        _ = exchange, explanation
        self.calls.append(signal)
        return self.signal, True


class _VirtualTrading:
    def __init__(self) -> None:
        self.open_calls: list[tuple[RadarSignal, ManualConfirmRequest]] = []

    def open_virtual_trade(self, signal: RadarSignal, request: ManualConfirmRequest) -> VirtualTrade:
        self.open_calls.append((signal, request))
        return _trade(signal.id)


class _Scanner:
    def __init__(self, signals: list[StrategySignal]) -> None:
        self._signals = signals
        self.ticks: list[MarketData] = []

    async def process_tick(self, tick: MarketData) -> list[StrategySignal]:
        self.ticks.append(tick)
        return list(self._signals)


class _WorkerSignalRuntime:
    def __init__(self) -> None:
        self.signals: list[StrategySignal] = []

    async def process_strategy_signal(self, signal: StrategySignal) -> ForwardRuntimeResult:
        self.signals.append(signal)
        return ForwardRuntimeResult(signals_processed=1)


class _FailingHeartbeatRuntime:
    def __init__(self) -> None:
        self.heartbeat_calls = 0

    def heartbeat_active_runs(self) -> ForwardRuntimeResult:
        self.heartbeat_calls += 1
        raise RuntimeError("heartbeat failed")


async def _wait_until(predicate: Callable[[], bool], *, attempts: int = 30) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
