from __future__ import annotations

from typing import Protocol, Sequence
from uuid import UUID

from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult, StrategyTestMatrixRunner
from app.services.strategy_testing.report_builder import (
    StrategyTestReportBuilder,
    build_matrix_metric_results,
    metric_results_to_rows,
)
from app.services.strategy_testing.runner import strategy_test_user_uuid
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestReport,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignal,
    StrategyTestTrade,
)
from app.services.strategy_testing.stores import (
    ClickHouseStrategyTestStore,
    PostgresStrategyTestRunStore,
    StrategyTestRunStore,
)


class StrategyTestTradeStore(Protocol):
    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        ...

    def write_signals(self, signals: Sequence[StrategyTestSignal]) -> None:
        ...

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        ...

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        ...

    def list_signals(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestSignal]:
        ...

    def list_metrics(self, run_id: UUID) -> list[StrategyTestMetricRow]:
        ...


class StrategyTestingService:
    def __init__(
        self,
        run_store: StrategyTestRunStore | None = None,
        trade_store: StrategyTestTradeStore | None = None,
        matrix_runner: StrategyTestMatrixRunner | None = None,
    ) -> None:
        self._run_store = run_store or PostgresStrategyTestRunStore()
        self._trade_store = trade_store or ClickHouseStrategyTestStore()
        self._matrix_runner = matrix_runner or StrategyTestMatrixRunner()

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        created = self._run_store.create_run(request)
        return self.execute_run(created.run.run_id, request)

    def enqueue_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        return self._run_store.create_run(request).run

    def execute_run(self, run_id: UUID, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        self._run_store.mark_running(run_id)
        try:
            user_uuid = strategy_test_user_uuid(request.user_id)
            matrix_result = self._matrix_runner.run_matrix(
                request=request,
                run_id=run_id,
                user_uuid=user_uuid,
            )
            if matrix_result.all_failed:
                return self._run_store.mark_failed(run_id, _failure_message(matrix_result)).run
            metric_results = matrix_result.metrics or build_matrix_metric_results(
                matrix_result.trades,
                signals=matrix_result.signals,
                metric_set=request.metric_set,
            )
            self._trade_store.write_signals(matrix_result.signals)
            self._trade_store.write_trades(matrix_result.trades)
            self._trade_store.write_metrics(
                metric_results_to_rows(
                    run_id=run_id,
                    user_id=user_uuid,
                    mode=request.mode,
                    results=metric_results,
                )
            )
            return self._run_store.mark_completed(run_id, summary=matrix_result.summary(metrics=metric_results)).run
        except Exception as exc:
            return self._run_store.mark_failed(run_id, str(exc)).run

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

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        if self._run_store.get_run(run_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        return self._trade_store.list_trades(run_id, limit=limit, offset=offset)

    def list_signals(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestSignal]:
        if self._run_store.get_run(run_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        return self._trade_store.list_signals(run_id, limit=limit, offset=offset)

    def build_report(self, run_id: UUID) -> StrategyTestReport:
        return self._report_builder().build_report(run_id)

    def list_reports(self, user_id: str = "demo_user", limit: int = 50) -> list[StrategyTestReport]:
        return self._report_builder().list_reports(user_id=user_id, limit=limit)

    def _report_builder(self) -> StrategyTestReportBuilder:
        return StrategyTestReportBuilder(
            run_store=self._run_store,
            analytics_store=self._trade_store,
        )


def _failure_message(matrix_result: StrategyTestMatrixResult) -> str:
    if matrix_result.errors:
        return f"All strategy test scenarios failed: {matrix_result.errors[0]['error']}"
    return "All strategy test scenarios failed"
