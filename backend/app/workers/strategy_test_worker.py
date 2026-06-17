from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.core.config import settings
from app.services.strategy_testing.schemas import StrategyTestRunDetailResponse, StrategyTestRunResponse
from app.services.strategy_testing.service import StrategyTestingService
from app.services.strategy_testing.stores import PostgresStrategyTestRunStore, StrategyTestRunStore


logger = logging.getLogger(__name__)
DEFAULT_STRATEGY_TEST_WORKER_INTERVAL_SECONDS = 5.0


class StrategyTestExecutionService(Protocol):
    def execute_run(self, run_id: UUID, request: Any | None = None) -> StrategyTestRunResponse:
        ...


@dataclass
class StrategyTestWorkerResult:
    claimed_runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    cancelled_runs: int = 0
    started_forward_runs: int = 0
    recovered_failed_runs: int = 0
    recovered_cancelled_runs: int = 0
    recovered_requeued_runs: int = 0
    lease_renewals: int = 0
    forward_heartbeat_updates: int = 0
    errors: list[str] | None = None

    def add_error(self, error: str) -> None:
        if self.errors is None:
            self.errors = []
        self.errors.append(error)


class StrategyTestWorker:
    def __init__(
        self,
        *,
        service: StrategyTestExecutionService | None = None,
        run_store: StrategyTestRunStore | None = None,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
        heartbeat_interval_seconds: float | None = None,
        idle_interval_seconds: float = DEFAULT_STRATEGY_TEST_WORKER_INTERVAL_SECONDS,
    ) -> None:
        self._run_store = run_store or PostgresStrategyTestRunStore()
        self._service = service or StrategyTestingService(run_store=self._run_store)
        self._worker_id = worker_id or _default_worker_id()
        self._lease_seconds = max(1, int(lease_seconds or settings.strategy_test_lease_seconds))
        self._heartbeat_interval_seconds = max(
            0.1,
            float(heartbeat_interval_seconds or settings.strategy_test_worker_heartbeat_seconds),
        )
        self._idle_interval_seconds = max(0.1, float(idle_interval_seconds))
        self._stopping = False

    @property
    def worker_id(self) -> str:
        return self._worker_id

    async def run_once(self) -> StrategyTestWorkerResult:
        result = StrategyTestWorkerResult()
        self._heartbeat_forward_runs(result)

        recovered = self._run_store.recover_expired_leases(worker_id=self._worker_id)
        result.recovered_failed_runs += int(recovered.get("failed", 0))
        result.recovered_cancelled_runs += int(recovered.get("cancelled", 0))
        result.recovered_requeued_runs += int(recovered.get("requeued", 0))

        claimed = self._run_store.claim_next_run(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if claimed is None:
            return result

        result.claimed_runs += 1
        try:
            final_run = await self._execute_claimed_run(claimed, result)
        except Exception as exc:
            message = str(exc)
            logger.exception("Strategy test worker failed run_id=%s: %s", claimed.run.run_id, exc)
            self._run_store.mark_failed(claimed.run.run_id, message)
            result.failed_runs += 1
            result.add_error(message)
            return result

        if final_run.status == "completed":
            result.completed_runs += 1
        elif final_run.status == "cancelled":
            result.cancelled_runs += 1
        elif final_run.status == "failed":
            result.failed_runs += 1
        elif final_run.test_type == "forward_virtual" and final_run.status == "running":
            result.started_forward_runs += 1
        return result

    async def run_forever(self) -> None:
        self._stopping = False
        while not self._stopping:
            await self.run_once()
            await asyncio.sleep(self._idle_interval_seconds)

    def stop(self) -> None:
        self._stopping = True

    async def _execute_claimed_run(
        self,
        claimed: StrategyTestRunDetailResponse,
        result: StrategyTestWorkerResult,
    ) -> StrategyTestRunResponse:
        run_id = claimed.run.run_id
        self._renew_lease(run_id, result)
        task = asyncio.create_task(asyncio.to_thread(self._service.execute_run, run_id, None))
        while not task.done():
            self._renew_lease(run_id, result)
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self._heartbeat_interval_seconds,
                )
            except TimeoutError:
                continue
        return await task

    def _renew_lease(self, run_id: UUID, result: StrategyTestWorkerResult) -> None:
        self._run_store.renew_lease(
            run_id,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        result.lease_renewals += 1

    def _heartbeat_forward_runs(self, result: StrategyTestWorkerResult) -> None:
        heartbeat = getattr(self._service, "heartbeat_forward_runs", None)
        if not callable(heartbeat):
            return
        forward_result = heartbeat()
        result.forward_heartbeat_updates += int(getattr(forward_result, "runtime_state_updates", 0) or 0)
        for detail in self._run_store.list_runs(user_id=None, limit=500, status="running"):
            run = detail.run
            if run.test_type != "forward_virtual":
                continue
            self._run_store.renew_lease(
                run.run_id,
                worker_id=self._worker_id,
                lease_seconds=self._lease_seconds,
            )
            result.lease_renewals += 1


def _default_worker_id() -> str:
    hostname = os.getenv("HOSTNAME") or os.getenv("COMPUTERNAME") or "strategy-test-worker"
    return f"{hostname}:{os.getpid()}"


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    worker = StrategyTestWorker()
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
