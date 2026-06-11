from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol, Sequence
from uuid import UUID

from app.services.strategy_testing.eligibility_profiles import StrategyExecutionEligibilityProfileUpdater
from app.services.strategy_testing.forward_runtime import ForwardStrategyTestRuntime
from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult, StrategyTestMatrixRunner
from app.services.strategy_testing.metrics import MetricResult
from app.services.strategy_testing.report_builder import (
    StrategyTestReportBuilder,
    build_matrix_metric_results,
    metric_results_to_rows,
)
from app.services.strategy_testing.runner import strategy_test_user_uuid
from app.services.strategy_testing.schemas import (
    StrategyTestActiveRunResponse,
    StrategyTestMetricRow,
    StrategyTestReport,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTrade,
)
from app.services.strategy_testing.stores import (
    ClickHouseStrategyTestStore,
    PostgresStrategyTestRunStore,
    StrategyTestRunStore,
)

logger = logging.getLogger(__name__)


class StrategyTestTradeStore(Protocol):
    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        ...

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        ...

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        ...


class StrategyExecutionEligibilityProfileUpdateService(Protocol):
    def update_from_metric_results(
        self,
        *,
        run_id: UUID,
        request: StrategyTestRunRequest,
        metrics: Sequence[MetricResult],
    ) -> None:
        ...


class StrategyTestingService:
    def __init__(
        self,
        run_store: StrategyTestRunStore | None = None,
        trade_store: StrategyTestTradeStore | None = None,
        matrix_runner: StrategyTestMatrixRunner | None = None,
        forward_runtime: ForwardStrategyTestRuntime | None = None,
        eligibility_profile_updater: StrategyExecutionEligibilityProfileUpdateService | None = None,
    ) -> None:
        self._run_store = run_store or PostgresStrategyTestRunStore()
        self._trade_store = trade_store or ClickHouseStrategyTestStore()
        self._matrix_runner = matrix_runner or StrategyTestMatrixRunner()
        self._forward_runtime = forward_runtime or ForwardStrategyTestRuntime(
            run_store=self._run_store,
            trade_store=self._trade_store,
        )
        self._eligibility_profile_updater = eligibility_profile_updater or StrategyExecutionEligibilityProfileUpdater()

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        created = self._run_store.create_run(request)
        return self.execute_run(created.run.run_id, request)

    def enqueue_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        return self._run_store.create_run(request).run

    def execute_run(self, run_id: UUID, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        if request.test_type == "forward_virtual":
            return self._forward_runtime.start_run(run_id, request).run
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
                metric_set=request.metric_set,
            )
            summary = matrix_result.summary(metrics=metric_results)
            self._trade_store.write_trades(matrix_result.trades)
            self._trade_store.write_metrics(
                metric_results_to_rows(
                    run_id=run_id,
                    user_id=user_uuid,
                    mode=request.mode,
                    results=metric_results,
                )
            )
            try:
                self._eligibility_profile_updater.update_from_metric_results(
                    run_id=run_id,
                    request=request,
                    metrics=metric_results,
                )
            except Exception as exc:
                message = f"Eligibility profile update failed: {exc}"
                logger.warning(
                    "Strategy test eligibility profile update failed for run_id=%s test_type=%s: %s",
                    run_id,
                    request.test_type,
                    exc,
                )
                _append_summary_warning(
                    summary,
                    "eligibility_profile_update_failed",
                    message,
                )
            return self._run_store.mark_completed(run_id, summary=summary).run
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

    def get_active_run(self, user_id: str = "demo_user") -> StrategyTestActiveRunResponse:
        active_run = _latest_active_run(_active_run_candidates(self._run_store, user_id))
        if active_run is None:
            return StrategyTestActiveRunResponse(
                active_run=None,
                can_run=True,
                stale_threshold_seconds=STRATEGY_TEST_STALE_THRESHOLD_SECONDS,
                allowed_actions=["refresh"],
            )

        stale = _is_stale_run(active_run)
        if stale:
            return StrategyTestActiveRunResponse(
                active_run=active_run,
                can_run=True,
                disabled_reason_code=None,
                disabled_reason=None,
                is_stale=True,
                stale_threshold_seconds=STRATEGY_TEST_STALE_THRESHOLD_SECONDS,
                allowed_actions=["refresh", "cancel"],
            )

        return StrategyTestActiveRunResponse(
            active_run=active_run,
            can_run=False,
            disabled_reason_code="active_strategy_test_run",
            disabled_reason=(
                f"Strategy test run {active_run.run_id} is {active_run.status}; "
                "wait for it to finish or cancel it before starting another run."
            ),
            is_stale=False,
            stale_threshold_seconds=STRATEGY_TEST_STALE_THRESHOLD_SECONDS,
            allowed_actions=["refresh", "cancel"],
        )

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        return self._run_store.get_run(run_id)

    def cancel_run(self, run_id: UUID) -> StrategyTestRunResponse:
        detail = self._run_store.get_run(run_id)
        if detail is None:
            raise LookupError(f"Strategy test run is not found: {run_id}")
        if detail.run.status == "cancelled":
            return detail.run
        if detail.run.status not in {"queued", "running", "stopping"}:
            raise ValueError(f"Strategy test run cannot be cancelled from status {detail.run.status}")
        return self._run_store.mark_cancelled(run_id).run

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        if self._run_store.get_run(run_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        return self._trade_store.list_trades(run_id, limit=limit, offset=offset)

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


def _append_summary_warning(summary: dict[str, object], code: str, message: str) -> None:
    warnings = summary.setdefault("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        summary["warnings"] = warnings
    warnings.append({"code": code, "message": message})


STRATEGY_TEST_ACTIVE_STATUSES: tuple[StrategyTestRunStatus, ...] = ("queued", "running", "stopping")
STRATEGY_TEST_STALE_THRESHOLD_SECONDS = 900


def _active_run_candidates(
    run_store: StrategyTestRunStore,
    user_id: str,
) -> list[StrategyTestRunResponse]:
    candidates: list[StrategyTestRunResponse] = []
    for status in STRATEGY_TEST_ACTIVE_STATUSES:
        candidates.extend(
            detail.run
            for detail in run_store.list_runs(
                user_id=user_id,
                limit=10,
                status=status,
            )
        )
    return candidates


def _latest_active_run(candidates: Sequence[StrategyTestRunResponse]) -> StrategyTestRunResponse | None:
    if not candidates:
        return None
    return max(candidates, key=_run_sort_time)


def _run_sort_time(run: StrategyTestRunResponse) -> datetime:
    return (
        run.last_heartbeat_at
        or run.started_at
        or run.created_at
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def _is_stale_run(run: StrategyTestRunResponse) -> bool:
    if run.status not in STRATEGY_TEST_ACTIVE_STATUSES:
        return False
    heartbeat_at = run.last_heartbeat_at or run.started_at or run.created_at
    if heartbeat_at is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - heartbeat_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds > STRATEGY_TEST_STALE_THRESHOLD_SECONDS
