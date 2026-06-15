from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Sequence
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.v1.strategy_tests import get_strategy_testing_service
from app.main import app
from app.schemas.market import MarketData
from app.schemas.signal import SignalExecutionGateSnapshot, StrategySignal
from app.services.radar_config_service import ScannerUniverse
from app.services.strategy_testing.forward_runtime import ForwardStrategyTestRuntime
from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)
from app.services.strategy_testing.service import StrategyTestingService
from app.workers.strategy_test_worker import StrategyTestWorker


NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


class ForwardStrategyTestAppIntegrationTest(unittest.TestCase):
    def test_strategy_worker_forward_virtual_pending_chain_uses_shared_stores(self) -> None:
        run_store = _SharedRunStore()
        trade_store = _RecordingTradeStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=trade_store,
            matrix_runner=_FailingStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )

        app.dependency_overrides[get_strategy_testing_service] = lambda: service

        try:
            with _patched_lifespan(run_store, trade_store), TestClient(app) as client:
                response = client.post(
                    "/api/v1/strategy-tests/runs",
                    json=_run_payload(),
                )
                self.assertEqual(response.status_code, 202)
                run_id = UUID(response.json()["run_id"])
                self.assertEqual(response.json()["status"], "queued")

                runner = app.state.scanner_runner
                self.assertIsNone(app.state.forward_strategy_test_worker)
                self.assertIsNone(runner._forward_strategy_tests)  # type: ignore[attr-defined]

                strategy_worker = StrategyTestWorker(
                    service=service,
                    run_store=run_store,
                    worker_id="test-worker",
                    heartbeat_interval_seconds=0.01,
                )
                worker_result = asyncio.run(strategy_worker.run_once())
                runtime = ForwardStrategyTestRuntime(run_store=run_store, trade_store=trade_store)

                asyncio.run(
                    runtime.process_market_tick(
                        MarketData(
                            exchange="bybit",
                            symbol="BTCUSDT",
                            price=105.0,
                            volume=1.0,
                            timestamp=1_781_000_000,
                        )
                    )
                )
                asyncio.run(
                    runtime.process_strategy_signal(
                        _strategy_signal(execution_gate=_gate(can_arm_pending=True))
                    )
                )
                asyncio.run(
                    runtime.process_market_tick(
                        MarketData(
                            exchange="bybit",
                            symbol="BTCUSDT",
                            price=100.5,
                            volume=1.0,
                            timestamp=1_781_000_060,
                        )
                    )
                )

                detail_response = client.get(f"/api/v1/strategy-tests/runs/{run_id}")
                self.assertEqual(detail_response.status_code, 200)
                runtime_state = detail_response.json()["run"]["runtime_state"]

                self.assertEqual(runtime_state["status"], "processing")
                self.assertEqual(runtime_state["processed_ticks"], 2)
                self.assertEqual(runtime_state["processed_signals"], 1)
                self.assertEqual(runtime_state["pending_entries_armed"], 1)
                self.assertEqual(runtime_state["pending_entries_count"], 0)
                self.assertEqual(runtime_state["pending_entries"][0]["status"], "filled")
                self.assertEqual(runtime_state["opened_trades"], 1)
                self.assertEqual(runtime_state["trades_written"], 1)
                self.assertEqual(runtime_state["signal_events_written"], 2)
                self.assertEqual(runtime_state["metrics_written"], 1)
                self.assertGreaterEqual(len(run_store.runtime_state_writes), 4)
                self.assertEqual(len(trade_store.trades), 1)
                self.assertEqual(len(trade_store.signal_events), 2)
                self.assertEqual(len(trade_store.metrics), 1)
                self.assertIn("write_signal_events", trade_store.calls)
                self.assertIn("write_trades", trade_store.calls)
                self.assertIn("write_metrics", trade_store.calls)
                self.assertEqual(worker_result.started_forward_runs, 1)
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

    def test_scanner_disabled_forward_run_waits_for_market_data_and_exposes_health_reason(self) -> None:
        run_store = _SharedRunStore()
        trade_store = _RecordingTradeStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=trade_store,
            matrix_runner=_FailingStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )

        app.dependency_overrides[get_strategy_testing_service] = lambda: service

        try:
            with _patched_lifespan(run_store, trade_store), TestClient(app) as client:
                response = client.post(
                    "/api/v1/strategy-tests/runs",
                    json=_run_payload(),
                )
                self.assertEqual(response.status_code, 202)
                run_id = UUID(response.json()["run_id"])
                strategy_worker = StrategyTestWorker(
                    service=service,
                    run_store=run_store,
                    worker_id="test-worker",
                    heartbeat_interval_seconds=0.01,
                )

                asyncio.run(strategy_worker.run_once())
                worker_heartbeat = asyncio.run(strategy_worker.run_once())

                detail_response = client.get(f"/api/v1/strategy-tests/runs/{run_id}")
                health_response = client.get("/health")
                self.assertEqual(detail_response.status_code, 200)
                self.assertEqual(health_response.status_code, 200)

                run = detail_response.json()["run"]
                runtime_state = run["runtime_state"]
                health = health_response.json()

                self.assertEqual(run["status"], "running")
                self.assertEqual(runtime_state["status"], "waiting_for_market_data")
                self.assertEqual(runtime_state["last_heartbeat_reason"], "waiting_for_market_data")
                self.assertEqual(runtime_state["processed_ticks"], 0)
                self.assertFalse(health["scanner_running"])
                self.assertEqual(health["market_data_status"], "offline")
                self.assertFalse(health["forward_strategy_test_running"])
                self.assertEqual(health["forward_strategy_test_last_result"], {})
                self.assertEqual(worker_heartbeat.forward_heartbeat_updates, 1)
                self.assertEqual(
                    detail_response.json()["run"]["runtime_state"]["last_heartbeat_reason"],
                    "waiting_for_market_data",
                )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)


@contextmanager
def _patched_lifespan(
    run_store: _SharedRunStore,
    trade_store: _RecordingTradeStore,
) -> Iterator[None]:
    events: list[str] = []

    with ExitStack() as stack:
        stack.enter_context(patch("app.main.ExchangeInstrumentRuleSyncRunner", _worker_factory("instrument", events)))
        stack.enter_context(patch("app.main.DerivativeSnapshotSyncRunner", _worker_factory("derivative", events)))
        stack.enter_context(patch("app.main.OrderbookSnapshotWorker", _worker_factory("orderbook", events)))
        stack.enter_context(patch("app.main.SignalExpiryWorker", _worker_factory("expiry", events)))
        stack.enter_context(patch("app.main.RealPositionSyncWorker", _worker_factory("positions", events)))
        stack.enter_context(patch("app.main.BybitRealPositionSyncClient", object))
        stack.enter_context(patch("app.main._scanner_enabled", return_value=False))
        stack.enter_context(patch("app.main._instrument_rule_sync_enabled", return_value=False))
        stack.enter_context(patch("app.main._derivative_snapshot_sync_enabled", return_value=False))
        stack.enter_context(patch("app.main._orderbook_snapshot_sync_enabled", return_value=False))
        stack.enter_context(patch("app.main._real_position_sync_enabled", return_value=False))
        stack.enter_context(patch("app.main.warn_if_migrations_outdated", return_value=None))
        stack.enter_context(patch("app.main.realtime_gateway", _FakeRealtimeGateway()))
        stack.enter_context(patch("app.main.close_clickhouse_client", return_value=None))
        stack.enter_context(patch("app.main.close_redis_client", return_value=None))
        stack.enter_context(patch("app.main.dispose_database_engine", return_value=None))
        stack.enter_context(patch("app.main.get_storage_health", return_value={"status": "ok"}))
        stack.enter_context(patch("app.workers.signal_worker.radar_config_service", _FakeRadarConfigService()))
        yield


def _run_payload() -> dict[str, object]:
    return {
        "user_id": "forward_app_user",
        "test_type": "forward_virtual",
        "strategies": ["trend_pullback_continuation"],
        "pairs": [{"exchange": "bybit", "symbol": "BTCUSDT"}],
        "timeframes": ["15m"],
        "start_at": (NOW - timedelta(hours=1)).isoformat(),
        "end_at": (NOW + timedelta(hours=1)).isoformat(),
        "mode": "research_virtual",
        "initial_capital": "1000",
        "fee_rate": "0.001",
        "slippage_bps": "0",
        "tags": ["forward"],
    }


def _strategy_signal(
    *,
    execution_gate: SignalExecutionGateSnapshot,
) -> StrategySignal:
    return StrategySignal(
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        direction="LONG",
        confidence=0.82,
        timestamp=1_781_000_030,
        score=82,
        timeframe="15m",
        status="actionable",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=115.0,
        risk_reward=2.0,
        execution_gate=execution_gate,
    )


def _gate(*, can_arm_pending: bool = False, can_enter_now: bool = False) -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed",
        feed_kind="execution_signal" if can_enter_now else "watchlist",
        can_notify=can_enter_now,
        can_enter_now=can_enter_now,
        can_arm_pending=can_arm_pending,
        can_show_in_execution_feed=can_enter_now,
    )


class _SharedRunStore:
    def __init__(self) -> None:
        self._runs: dict[UUID, StrategyTestRunDetailResponse] = {}
        self.runtime_state_writes: list[dict[str, Any]] = []

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        run = StrategyTestRunResponse(
            run_id=uuid4(),
            status="queued",
            test_type=request.test_type,
            requested_matrix=_requested_matrix(request),
            created_at=NOW,
        )
        detail = StrategyTestRunDetailResponse(run=run)
        self._runs[run.run_id] = detail
        return detail

    def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> StrategyTestRunDetailResponse | None:
        _ = worker_id, lease_seconds
        for detail in self._runs.values():
            if detail.run.status == "queued":
                return detail
        return None

    def renew_lease(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> StrategyTestRunDetailResponse:
        _ = worker_id, lease_seconds
        detail = self._runs[run_id]
        self._runs[run_id] = StrategyTestRunDetailResponse(
            run=detail.run.model_copy(update={"last_heartbeat_at": NOW})
        )
        return self._runs[run_id]

    def recover_expired_leases(self, *, worker_id: str) -> dict[str, int]:
        _ = worker_id
        return {"failed": 0, "cancelled": 0, "requeued": 0}

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

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated = detail.run.model_copy(
            update={
                "status": "running",
                "started_at": NOW,
                "last_heartbeat_at": NOW,
            }
        )
        self._runs[run_id] = StrategyTestRunDetailResponse(run=updated)
        return self._runs[run_id]

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "completed", summary=summary)

    def mark_failed(
        self,
        run_id: UUID,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        _ = error
        return self._mark(run_id, "failed", summary=summary)

    def mark_stopping(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "stopping")

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "cancelled")

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        self.runtime_state_writes.append(dict(runtime_state))
        update: dict[str, Any] = {
            "runtime_state": {**detail.run.runtime_state, **runtime_state},
        }
        if heartbeat:
            update["last_heartbeat_at"] = NOW
        self._runs[run_id] = StrategyTestRunDetailResponse(run=detail.run.model_copy(update=update))
        return self._runs[run_id]

    def _mark(
        self,
        run_id: UUID,
        status: StrategyTestRunStatus,
        *,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        update: dict[str, Any] = {"status": status}
        if summary is not None:
            update["summary"] = summary
        self._runs[run_id] = StrategyTestRunDetailResponse(run=detail.run.model_copy(update=update))
        return self._runs[run_id]


class _RecordingTradeStore:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.trades: list[StrategyTestTrade] = []
        self.signal_events: list[StrategyTestSignalEvent] = []
        self.metrics: list[StrategyTestMetricRow] = []

    def ensure_schema(self) -> None:
        self.calls.append("ensure_schema")

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.calls.append("write_trades")
        self.trades.extend(trades)

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        self.calls.append("write_signal_events")
        self.signal_events.extend(signal_events)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.calls.append("write_metrics")
        self.metrics.extend(rows)

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        return [trade for trade in self.trades if trade.run_id == run_id][offset : offset + limit]

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        return [event for event in self.signal_events if event.run_id == run_id][offset : offset + limit]

    def list_metrics(self, run_id: UUID) -> list[StrategyTestMetricRow]:
        return [row for row in self.metrics if row.run_id == run_id]


class _FailingStrategyTestMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = request, run_id, user_uuid, kwargs
        raise AssertionError("forward_virtual must not use historical matrix runner")


class _FakeRadarConfigService:
    def selected_timeframes(self) -> list[str]:
        return ["15m"]

    def scanner_universe(self, *, truncate_over_limit: bool = False) -> ScannerUniverse:
        _ = truncate_over_limit
        return ScannerUniverse(
            pairs=(("bybit", "BTCUSDT"),),
            source="test",
            max_pairs=1,
            truncated=False,
            warning=None,
            estimated_strategy_checks=1,
        )

    def scanner_subscription_hash(self, universe: ScannerUniverse | None = None) -> str:
        _ = universe
        return "forward-test"

    def strategy_config_hash(self) -> str:
        return "strategy-test"


class _FakeRealtimeGateway:
    def start_broker_bridge(self) -> None:
        return None

    async def stop_broker_bridge(self) -> None:
        return None


class _NoopWorker:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events
        self.started = False
        self.last_result: dict[str, object] = {}

    @property
    def is_running(self) -> bool:
        return self.started

    @property
    def is_stopping(self) -> bool:
        return False

    def start(self) -> None:
        self.started = True
        self._events.append(f"{self._name}.start")

    async def stop(self) -> None:
        self._events.append(f"{self._name}.stop")


def _worker_factory(name: str, events: list[str]) -> type[_NoopWorker]:
    class Worker(_NoopWorker):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(name, events)

    return Worker


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


if __name__ == "__main__":
    unittest.main()
