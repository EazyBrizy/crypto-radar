from __future__ import annotations

from uuid import UUID

from app.services.strategy_testing.schemas import (
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
)
from app.services.strategy_testing.stores import PostgresStrategyTestRunStore, StrategyTestRunStore


class StrategyTestingService:
    def __init__(self, run_store: StrategyTestRunStore | None = None) -> None:
        self._run_store = run_store or PostgresStrategyTestRunStore()

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        return self._run_store.create_run(request).run

    def list_runs(
        self,
        user_id: str | None = None,
        limit: int = 50,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunResponse]:
        return [
            detail.run
            for detail in self._run_store.list_runs(user_id=user_id, limit=limit, status=status)
        ]

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        return self._run_store.get_run(run_id)
