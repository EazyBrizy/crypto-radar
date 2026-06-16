from __future__ import annotations

import asyncio
import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID, uuid4

from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestPair,
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


class StrategyTestWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_claims_queued_historical_run_and_executes_without_request(self) -> None:
        run_store = _WorkerRunStore([_run(status="queued", test_type="historical_backtest")])
        service = _RecordingWorkerService(run_store)
        worker = StrategyTestWorker(
            service=service,  # type: ignore[arg-type]
            run_store=run_store,
            worker_id="worker-a",
            lease_seconds=30,
            heartbeat_interval_seconds=0.01,
        )

        result = await worker.run_once()

        self.assertEqual(result.claimed_runs, 1)
        self.assertEqual(result.completed_runs, 1)
        self.assertEqual(service.execute_calls, [(RUN_ID, None)])
        self.assertGreaterEqual(run_store.renew_lease_calls, 1)
        self.assertEqual(run_store.get_run(RUN_ID).run.status, "completed")  # type: ignore[union-attr]

    async def test_historical_execution_renews_lease_while_sync_job_is_alive(self) -> None:
        run_store = _WorkerRunStore([_run(status="queued", test_type="historical_backtest")])
        service = _SlowWorkerService(run_store, minimum_renewals=2)
        worker = StrategyTestWorker(
            service=service,  # type: ignore[arg-type]
            run_store=run_store,
            worker_id="worker-a",
            lease_seconds=30,
            heartbeat_interval_seconds=0.01,
        )

        result = await worker.run_once()

        self.assertEqual(result.completed_runs, 1)
        self.assertGreaterEqual(run_store.renew_lease_calls, 2)
        self.assertIsNotNone(run_store.get_run(RUN_ID).run.last_heartbeat_at)  # type: ignore[union-attr]

    async def test_run_once_claims_queued_forward_run_and_starts_runtime_listening(self) -> None:
        run_store = _WorkerRunStore([_run(status="queued", test_type="forward_virtual")])
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=_FailingForwardMatrixRunner(),  # type: ignore[arg-type]
            eligibility_profile_updater=_NoopEligibilityUpdater(),
        )
        worker = StrategyTestWorker(
            service=service,
            run_store=run_store,
            worker_id="worker-a",
            lease_seconds=30,
            heartbeat_interval_seconds=0.01,
        )

        result = await worker.run_once()

        detail = run_store.get_run(RUN_ID)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(result.claimed_runs, 1)
        self.assertEqual(result.started_forward_runs, 1)
        self.assertEqual(result.completed_runs, 0)
        self.assertEqual(detail.run.status, "running")
        self.assertEqual(detail.run.runtime_state["status"], "listening")
        self.assertEqual(detail.run.runtime_state["test_type"], "forward_virtual")
        self.assertEqual(detail.run.runtime_state["processed_ticks"], 0)
        self.assertEqual(detail.run.runtime_state["processed_signals"], 0)
        self.assertEqual(detail.run.runtime_state["forward_account"]["initial_capital"], "1000")
        self.assertGreaterEqual(run_store.renew_lease_calls, 1)

    async def test_run_once_recovers_expired_running_and_stopping_leases(self) -> None:
        running = _run(
            run_id=RUN_ID,
            status="running",
            test_type="historical_backtest",
            lease_expires_at=NOW - timedelta(seconds=1),
        )
        stopping = _run(
            run_id=UUID("22222222-2222-4222-8222-222222222222"),
            status="stopping",
            test_type="historical_backtest",
            lease_expires_at=NOW - timedelta(seconds=1),
        )
        run_store = _WorkerRunStore([running, stopping])
        worker = StrategyTestWorker(
            service=_RecordingWorkerService(run_store),  # type: ignore[arg-type]
            run_store=run_store,
            worker_id="worker-a",
            lease_seconds=30,
            heartbeat_interval_seconds=0.01,
        )

        result = await worker.run_once()

        self.assertEqual(result.recovered_failed_runs, 1)
        self.assertEqual(result.recovered_cancelled_runs, 1)
        self.assertEqual(run_store.get_run(running.run_id).run.status, "failed")  # type: ignore[union-attr]
        self.assertEqual(run_store.get_run(stopping.run_id).run.status, "cancelled")  # type: ignore[union-attr]

    async def test_cancelled_historical_run_finishes_when_worker_sees_stopping_status(self) -> None:
        run_store = _WorkerRunStore([_run(status="queued", test_type="historical_backtest")])
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=_CancellingMatrixRunner(run_store),  # type: ignore[arg-type]
            eligibility_profile_updater=_NoopEligibilityUpdater(),
        )
        worker = StrategyTestWorker(
            service=service,
            run_store=run_store,
            worker_id="worker-a",
            lease_seconds=30,
            heartbeat_interval_seconds=0.01,
        )

        result = await worker.run_once()

        self.assertEqual(result.cancelled_runs, 1)
        self.assertEqual(run_store.get_run(RUN_ID).run.status, "cancelled")  # type: ignore[union-attr]


RUN_ID = UUID("11111111-2222-4333-8444-555555555555")


def _run(
    *,
    run_id: UUID = RUN_ID,
    status: StrategyTestRunStatus,
    test_type: str,
    lease_expires_at: datetime | None = None,
) -> StrategyTestRunResponse:
    request = _request(test_type=test_type)
    return StrategyTestRunResponse(
        run_id=run_id,
        status=status,
        test_type=request.test_type,
        requested_matrix=_requested_matrix(request),
        runtime_state={},
        created_at=NOW,
        started_at=NOW if status in {"running", "stopping"} else None,
        last_heartbeat_at=NOW if status in {"running", "stopping"} else None,
    ).model_copy(
        update={
            "lease_expires_at": lease_expires_at,
        }
    )


def _request(*, test_type: str = "historical_backtest") -> StrategyTestRunRequest:
    return StrategyTestRunRequest(
        user_id="worker_user",
        test_type=test_type,
        strategies=["trend_pullback_continuation"],
        pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
        timeframes=["15m"],
        start_at=NOW - timedelta(days=1),
        end_at=NOW,
        mode="research_virtual",
        initial_capital=Decimal("1000"),
        tags=["worker"],
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


class _WorkerRunStore:
    def __init__(self, runs: Sequence[StrategyTestRunResponse]) -> None:
        self._runs = {run.run_id: StrategyTestRunDetailResponse(run=run) for run in runs}
        self.renew_lease_calls = 0

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        run = _run(status="queued", test_type=request.test_type, run_id=uuid4())
        self._runs[run.run_id] = StrategyTestRunDetailResponse(run=run)
        return self._runs[run.run_id]

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
        self.renew_lease_calls += 1
        detail = self._runs[run_id]
        updated = detail.run.model_copy(update={"last_heartbeat_at": NOW + timedelta(seconds=self.renew_lease_calls)})
        self._runs[run_id] = StrategyTestRunDetailResponse(run=updated)
        return self._runs[run_id]

    def recover_expired_leases(self, *, worker_id: str) -> dict[str, int]:
        _ = worker_id
        recovered = {"failed": 0, "cancelled": 0, "requeued": 0}
        for detail in list(self._runs.values()):
            lease_expires_at = getattr(detail.run, "lease_expires_at", None)
            if not isinstance(lease_expires_at, datetime) or lease_expires_at >= NOW:
                continue
            if detail.run.status == "running":
                self.mark_failed(detail.run.run_id, "Strategy test worker lease expired")
                recovered["failed"] += 1
            elif detail.run.status == "stopping":
                self.mark_cancelled(detail.run.run_id)
                recovered["cancelled"] += 1
        return recovered

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        _ = user_id
        runs = list(self._runs.values())
        if status is not None:
            runs = [detail for detail in runs if detail.run.status == status]
        return runs[:limit]

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        return self._runs.get(run_id)

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "running", started_at=NOW, last_heartbeat_at=NOW)

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "completed", summary=dict(summary or {}), finished_at=NOW)

    def mark_failed(
        self,
        run_id: UUID,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "failed", error=error, summary=dict(summary or {}), finished_at=NOW)

    def mark_stopping(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "stopping", last_heartbeat_at=NOW)

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "cancelled", finished_at=NOW, last_heartbeat_at=NOW)

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        update: dict[str, Any] = {
            "runtime_state": {**detail.run.runtime_state, **runtime_state},
        }
        if heartbeat:
            update["last_heartbeat_at"] = NOW
        self._runs[run_id] = StrategyTestRunDetailResponse(run=detail.run.model_copy(update=update))
        return self._runs[run_id]

    def _mark(self, run_id: UUID, status: StrategyTestRunStatus, **updates: Any) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        self._runs[run_id] = StrategyTestRunDetailResponse(run=detail.run.model_copy(update={"status": status, **updates}))
        return self._runs[run_id]


class _RecordingWorkerService:
    def __init__(self, run_store: _WorkerRunStore) -> None:
        self._run_store = run_store
        self.execute_calls: list[tuple[UUID, StrategyTestRunRequest | None]] = []

    def execute_run(
        self,
        run_id: UUID,
        request: StrategyTestRunRequest | None = None,
    ) -> StrategyTestRunResponse:
        self.execute_calls.append((run_id, request))
        self._run_store.mark_running(run_id)
        return self._run_store.mark_completed(run_id, summary={"scenario_count": 1}).run


class _SlowWorkerService(_RecordingWorkerService):
    def __init__(self, run_store: _WorkerRunStore, *, minimum_renewals: int) -> None:
        super().__init__(run_store)
        self._minimum_renewals = minimum_renewals

    def execute_run(
        self,
        run_id: UUID,
        request: StrategyTestRunRequest | None = None,
    ) -> StrategyTestRunResponse:
        self.execute_calls.append((run_id, request))
        self._run_store.mark_running(run_id)
        while self._run_store.renew_lease_calls < self._minimum_renewals:
            time.sleep(0.005)
        return self._run_store.mark_completed(run_id, summary={"scenario_count": 1}).run


class _CancellingMatrixRunner:
    def __init__(self, run_store: _WorkerRunStore) -> None:
        self._run_store = run_store

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = request, user_uuid
        is_cancelled = kwargs["is_cancelled"]
        self._run_store.mark_stopping(run_id)
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=1,
            completed_scenarios=0,
            failed_scenarios=0,
            cancelled=bool(is_cancelled()),
        )


class _FailingForwardMatrixRunner:
    def run_matrix(self, **kwargs: Any) -> StrategyTestMatrixResult:
        _ = kwargs
        raise AssertionError("forward_virtual must be started by the forward runtime, not the matrix runner")


class _RecordingTradeStore:
    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        _ = trades

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        _ = signal_events

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        _ = rows

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        _ = run_id, limit, offset
        return []

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        _ = run_id, limit, offset
        return []


class _NoopEligibilityUpdater:
    def update_from_metric_results(self, **kwargs: Any) -> list[Any]:
        _ = kwargs
        return []


if __name__ == "__main__":
    unittest.main()
