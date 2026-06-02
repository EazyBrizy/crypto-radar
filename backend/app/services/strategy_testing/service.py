from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.services.strategy_testing.schemas import (
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
)


class StrategyTestingService:
    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        # Temporary until BT-03 persists runs and schedules execution workers.
        return StrategyTestRunResponse(
            run_id=uuid4(),
            status="queued",
            requested_matrix=_build_requested_matrix(request),
        )

    def list_runs(
        self,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[StrategyTestRunResponse]:
        _ = (user_id, limit)
        # Temporary until BT-03 adds persistence for Strategy Test Lab runs.
        return []

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        _ = run_id
        # Temporary until BT-03 adds persistence for Strategy Test Lab runs.
        return None


def _build_requested_matrix(request: StrategyTestRunRequest) -> dict[str, Any]:
    pairs = [pair.model_dump() for pair in request.pairs]
    return {
        "user_id": request.user_id,
        "mode": request.mode,
        "strategies": request.strategies,
        "pairs": pairs,
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
