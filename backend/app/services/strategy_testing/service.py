from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.core.config import settings
from app.services.backtest_runner import DEFAULT_WARMUP_CANDLES, _run_awaitable_sync
from app.services.historical_candle_provider import ClickHouseHistoricalCandleProvider, HistoricalCandleProvider
from app.services.strategy_testing.eligibility_profiles import StrategyExecutionEligibilityProfileUpdater
from app.services.strategy_testing.forward_runtime import ForwardStrategyTestRuntime
from app.services.strategy_testing.matrix_runner import (
    StrategyTestMatrixResult,
    StrategyTestMatrixRunner,
    StrategyTestScenarioContext,
)
from app.services.strategy_testing.metrics import MetricResult
from app.services.strategy_testing.report_builder import (
    StrategyTestReportBuilder,
    build_matrix_metric_results,
    build_signal_funnel_response,
    metric_results_to_rows,
)
from app.services.strategy_testing.runner import StrategyTestRunCancelled, strategy_test_user_uuid
from app.services.strategy_testing.schemas import (
    StrategyTestCalibrationDecision,
    StrategyTestCalibrationProfile,
    StrategyTestCalibrationResponse,
    StrategyTestActiveRunResponse,
    StrategyTestEstimateResponse,
    StrategyTestEstimateWarning,
    StrategyTestEstimateWarningCode,
    StrategyTestScenarioEstimate,
    StrategyTestFunnelResponse,
    StrategyTestMetricRow,
    StrategyTestReport,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestRuntimeState,
    StrategyTestSignalEvent,
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

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        ...

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        ...

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        ...

    def list_signal_events(self, run_id: UUID, limit: int = 1000, offset: int = 0) -> list[StrategyTestSignalEvent]:
        ...


class StrategyExecutionEligibilityProfileUpdateService(Protocol):
    def update_from_metric_results(
        self,
        *,
        run_id: UUID,
        request: StrategyTestRunRequest,
        metrics: Sequence[MetricResult],
    ) -> Sequence[Any] | None:
        ...


class StrategyTestingService:
    def __init__(
        self,
        run_store: StrategyTestRunStore | None = None,
        trade_store: StrategyTestTradeStore | None = None,
        matrix_runner: StrategyTestMatrixRunner | None = None,
        forward_runtime: ForwardStrategyTestRuntime | None = None,
        eligibility_profile_updater: StrategyExecutionEligibilityProfileUpdateService | None = None,
        historical_candle_provider: HistoricalCandleProvider | None = None,
    ) -> None:
        self._run_store = run_store or PostgresStrategyTestRunStore()
        self._trade_store = trade_store or ClickHouseStrategyTestStore()
        self._matrix_runner = matrix_runner or StrategyTestMatrixRunner()
        self._forward_runtime = forward_runtime or ForwardStrategyTestRuntime(
            run_store=self._run_store,
            trade_store=self._trade_store,
        )
        self._eligibility_profile_updater = eligibility_profile_updater or StrategyExecutionEligibilityProfileUpdater()
        self._historical_candle_provider = historical_candle_provider or ClickHouseHistoricalCandleProvider()

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        self._validate_synchronous_run_request(request)
        created = self._run_store.create_run(request)
        return self.execute_run(created.run.run_id, request)

    def enqueue_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        self._validate_enqueued_run_request(request)
        created = self._run_store.create_run(request)
        if request.test_type == "historical_backtest":
            return self._run_store.update_runtime_state(
                created.run.run_id,
                _initial_historical_runtime_state(request, phase="queued"),
                heartbeat=False,
            ).run
        return created.run

    def execute_run(
        self,
        run_id: UUID,
        request: StrategyTestRunRequest | None = None,
    ) -> StrategyTestRunResponse:
        existing = self._run_store.get_run(run_id)
        if request is None:
            if existing is None:
                raise LookupError(f"Strategy test run is not found: {run_id}")
            request = _request_from_run(existing.run)
        if request.test_type == "forward_virtual":
            return self._forward_runtime.start_run(run_id, request).run
        last_summary = _empty_partial_summary(_scenario_total(request))
        if existing is not None:
            last_summary = _summary_from_run(existing.run) or last_summary
        if existing is not None and existing.run.status in {"cancelled", "stopping"}:
            self._run_store.update_runtime_state(
                run_id,
                _terminal_runtime_state(
                    request=request,
                    phase="cancelled",
                    partial_summary=last_summary,
                ),
            )
            return self._run_store.mark_cancelled(run_id).run
        resource_warnings = self._validate_worker_resource_limits(run_id, request, last_summary)
        if isinstance(resource_warnings, StrategyTestRunResponse):
            return resource_warnings
        self._run_store.mark_running(run_id)
        initial_runtime_state = _initial_historical_runtime_state(request, phase="running")
        if resource_warnings:
            initial_runtime_state["warnings"] = resource_warnings
            initial_runtime_state["matrix_bars_estimate_status"] = "unavailable"
        self._run_store.update_runtime_state(
            run_id,
            initial_runtime_state,
        )
        try:
            user_uuid = strategy_test_user_uuid(request.user_id)
            completed_scenario_summaries = _completed_scenario_summaries_by_key(self._run_store, run_id)
            if completed_scenario_summaries:
                last_summary = _normalize_summary(
                    StrategyTestMatrixResult(
                        run_id=run_id,
                        scenario_count=_scenario_total(request),
                        completed_scenarios=len(completed_scenario_summaries),
                        failed_scenarios=0,
                        scenario_summaries=list(completed_scenario_summaries.values()),
                    ).summary()
                )
            scenario_result_sink = _ScenarioResultPersistenceSink(
                trade_store=self._trade_store,
                run_store=self._run_store,
                run_id=run_id,
                user_id=user_uuid,
                request=request,
            )

            def is_cancelled() -> bool:
                detail = self._run_store.get_run(run_id)
                return bool(detail is not None and detail.run.status in {"cancelled", "stopping"})

            def on_started(context: StrategyTestScenarioContext) -> None:
                _mark_scenario_running(self._run_store, run_id, context)
                self._run_store.update_runtime_state(
                    run_id,
                    _scenario_runtime_state(
                        context=context,
                        request=request,
                        phase="loading_candles",
                        partial_summary=None,
                        scenario_status="started",
                        scenario_summary=_scenario_status_summary(context, status="started"),
                    ),
                )

            def on_progress(
                context: StrategyTestScenarioContext,
                progress: dict[str, Any],
                partial_summary: dict[str, Any],
            ) -> None:
                self._run_store.update_runtime_state(
                    run_id,
                    _scenario_runtime_state(
                        context=context,
                        request=request,
                        phase=_runtime_phase(progress.get("phase"), fallback="running_scenario"),
                        partial_summary=_partial_summary_with_progress(partial_summary, progress),
                        progress=progress,
                        scenario_status="running",
                    ),
                )

            def on_completed(
                context: StrategyTestScenarioContext,
                result: Any,
                partial_summary: dict[str, Any],
            ) -> None:
                nonlocal last_summary
                last_summary = _normalize_summary(partial_summary)
                self._run_store.update_runtime_state(
                    run_id,
                    _scenario_runtime_state(
                        context=context,
                        request=request,
                        phase="running_scenario",
                        partial_summary=last_summary,
                        scenario_status="completed",
                        scenario_summary=_completed_scenario_summary(context, result),
                    ),
                )

            def on_failed(
                context: StrategyTestScenarioContext,
                exc: Exception,
                partial_summary: dict[str, Any],
            ) -> None:
                nonlocal last_summary
                last_summary = _normalize_summary(partial_summary)
                _mark_scenario_failed(self._run_store, run_id, context, exc, last_summary)
                self._run_store.update_runtime_state(
                    run_id,
                    _scenario_runtime_state(
                        context=context,
                        request=request,
                        phase="running_scenario",
                        partial_summary=last_summary,
                        last_error=str(exc),
                        scenario_status="failed",
                        scenario_summary=_failed_scenario_summary(context, exc, last_summary),
                    ),
                )

            matrix_result = self._matrix_runner.run_matrix(
                request=request,
                run_id=run_id,
                user_uuid=user_uuid,
                on_scenario_started=on_started,
                on_scenario_completed=on_completed,
                on_scenario_failed=on_failed,
                on_scenario_progress=on_progress,
                scenario_result_sink=scenario_result_sink,
                completed_scenario_summaries=completed_scenario_summaries,
                is_cancelled=is_cancelled,
            )
            if matrix_result.cancelled or is_cancelled():
                last_summary = _normalize_summary(matrix_result.summary())
                self._run_store.update_runtime_state(
                    run_id,
                    _terminal_runtime_state(
                        request=request,
                        phase="cancelled",
                        partial_summary=last_summary,
                    ),
                )
                return self._run_store.mark_cancelled(run_id).run
            if matrix_result.all_failed:
                message = _failure_message(matrix_result)
                last_summary = _normalize_summary(matrix_result.summary())
                self._run_store.update_runtime_state(
                    run_id,
                    _terminal_runtime_state(
                        request=request,
                        phase="failed",
                        partial_summary=last_summary,
                        last_error=message,
                    ),
                )
                return self._run_store.mark_failed(run_id, message, summary=last_summary).run
            metric_results = matrix_result.metrics or build_matrix_metric_results(
                matrix_result.trades,
                signal_events=matrix_result.signal_events,
                metric_set=request.metric_set,
            )
            summary = _normalize_summary(matrix_result.summary(metrics=metric_results))
            last_summary = summary
            self._run_store.update_runtime_state(
                run_id,
                _terminal_runtime_state(
                    request=request,
                    phase="writing_results",
                    partial_summary=summary,
                ),
            )
            if scenario_result_sink.results_written == 0:
                _write_trades_once(
                    self._trade_store,
                    matrix_result.trades,
                    written_trade_keys=set(),
                )
                _write_signal_events_once(
                    self._trade_store,
                    matrix_result.signal_events,
                    written_signal_event_keys=set(),
                )
            _write_metrics_once(
                self._trade_store,
                metric_results_to_rows(
                    run_id=run_id,
                    user_id=user_uuid,
                    mode=request.mode,
                    results=metric_results,
                ),
                written_metric_keys=set(),
            )
            if _auto_publish_calibration(request):
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
            self._run_store.update_runtime_state(
                run_id,
                _terminal_runtime_state(
                    request=request,
                    phase="completed",
                    partial_summary=summary,
                ),
            )
            return self._run_store.mark_completed(run_id, summary=summary).run
        except StrategyTestRunCancelled:
            self._run_store.update_runtime_state(
                run_id,
                _terminal_runtime_state(
                    request=request,
                    phase="cancelled",
                    partial_summary=last_summary,
                ),
            )
            return self._run_store.mark_cancelled(run_id).run
        except Exception as exc:
            last_summary = _normalize_summary(last_summary)
            self._run_store.update_runtime_state(
                run_id,
                _terminal_runtime_state(
                    request=request,
                    phase="failed",
                    partial_summary=last_summary,
                    last_error=str(exc),
                ),
            )
            return self._run_store.mark_failed(run_id, str(exc), summary=last_summary).run

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
                stale_threshold_seconds=_strategy_test_stale_threshold_seconds(),
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
                stale_threshold_seconds=_strategy_test_stale_threshold_seconds(),
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
            stale_threshold_seconds=_strategy_test_stale_threshold_seconds(),
            allowed_actions=["refresh", "cancel"],
        )

    def estimate_run(self, request: StrategyTestRunRequest) -> StrategyTestEstimateResponse:
        return _estimate_historical_run(request, self._historical_candle_provider)

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        return self._run_store.get_run(run_id)

    def get_run_for_user(self, run_id: UUID, *, user_id: str) -> StrategyTestRunDetailResponse | None:
        detail = self._run_store.get_run(run_id)
        if detail is None:
            return None
        self._ensure_run_belongs_to_user(detail, user_id=user_id)
        return detail

    def cancel_run(self, run_id: UUID, *, user_id: str | None = None) -> StrategyTestRunResponse:
        detail = self._run_detail(run_id, user_id=user_id)
        if detail is None:
            raise LookupError(f"Strategy test run is not found: {run_id}")
        if detail.run.status == "cancelled":
            return detail.run
        if detail.run.status not in {"queued", "running", "stopping"}:
            raise ValueError(f"Strategy test run cannot be cancelled from status {detail.run.status}")
        if detail.run.status == "running":
            if _is_stale_run(detail.run):
                self._run_store.update_runtime_state(
                    run_id,
                    {
                        "phase": "cancelled",
                        "last_progress_at": _now_iso(),
                        "last_error": None,
                    },
                )
                return self._run_store.mark_cancelled(run_id).run
            self._run_store.update_runtime_state(
                run_id,
                {
                    "phase": "stopping",
                    "cancel_requested_at": _now_iso(),
                    "last_progress_at": _now_iso(),
                    "last_error": None,
                },
            )
            return self._run_store.mark_stopping(run_id).run
        if detail.run.status == "stopping":
            if _is_stale_run(detail.run):
                self._run_store.update_runtime_state(
                    run_id,
                    {
                        "phase": "cancelled",
                        "last_progress_at": _now_iso(),
                        "last_error": None,
                    },
                )
                return self._run_store.mark_cancelled(run_id).run
            return detail.run
        self._run_store.update_runtime_state(
            run_id,
            {
                "phase": "cancelled",
                "last_progress_at": _now_iso(),
                "last_error": None,
            },
        )
        return self._run_store.mark_cancelled(run_id).run

    def heartbeat_forward_runs(self) -> Any:
        return self._forward_runtime.heartbeat_active_runs()

    def _validate_synchronous_run_request(self, request: StrategyTestRunRequest) -> None:
        _validate_strategy_test_resource_limits(request, self._historical_candle_provider)

    def _validate_enqueued_run_request(self, request: StrategyTestRunRequest) -> None:
        _validate_enqueued_strategy_test_resource_limits(request)

    def _validate_worker_resource_limits(
        self,
        run_id: UUID,
        request: StrategyTestRunRequest,
        last_summary: dict[str, Any],
    ) -> StrategyTestRunResponse | list[str]:
        try:
            return _validate_worker_strategy_test_resource_limits(request, self._historical_candle_provider)
        except ValueError as exc:
            message = str(exc)
            summary = _normalize_summary(last_summary)
            self._run_store.update_runtime_state(
                run_id,
                _terminal_runtime_state(
                    request=request,
                    phase="failed",
                    partial_summary=summary,
                    last_error=message,
                ),
            )
            return self._run_store.mark_failed(run_id, message, summary=summary).run

    def publish_calibration(self, run_id: UUID, *, user_id: str | None = None) -> StrategyTestCalibrationResponse:
        detail = self._run_detail(run_id, user_id=user_id)
        if detail is None:
            raise LookupError(f"Strategy test run is not found: {run_id}")
        run = detail.run
        if run.status != "completed":
            raise ValueError("Strategy test run must be completed before calibration can be published.")

        request = _request_from_run(run)
        metrics = _metric_results_from_run_summary(run.summary)
        if not metrics:
            raise ValueError("Strategy test run has no grouped metrics suitable for calibration.")

        published = self._eligibility_profile_updater.update_from_metric_results(
            run_id=run_id,
            request=request,
            metrics=metrics,
        )
        profiles = list(published or [])
        if not profiles:
            raise ValueError("Strategy test run has no eligibility profiles suitable for calibration.")
        return _calibration_response(run_id=run_id, profiles=profiles)

    def list_trades(
        self,
        run_id: UUID,
        limit: int = 500,
        offset: int = 0,
        *,
        user_id: str | None = None,
    ) -> list[StrategyTestTrade]:
        if self._run_detail(run_id, user_id=user_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        return self._trade_store.list_trades(run_id, limit=limit, offset=offset)

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
        *,
        user_id: str | None = None,
    ) -> list[StrategyTestSignalEvent]:
        if self._run_detail(run_id, user_id=user_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        list_events = getattr(self._trade_store, "list_signal_events", None)
        if not callable(list_events):
            return []
        return list_events(run_id, limit=limit, offset=offset)

    def get_funnel(self, run_id: UUID, *, user_id: str | None = None) -> StrategyTestFunnelResponse:
        if self._run_detail(run_id, user_id=user_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        aggregate_funnel = getattr(self._trade_store, "aggregate_signal_funnel", None)
        if callable(aggregate_funnel):
            return aggregate_funnel(run_id)
        return build_signal_funnel_response(
            run_id,
            self.list_signal_events(run_id, limit=10000, offset=0, user_id=user_id),
        )

    def build_report(self, run_id: UUID, *, user_id: str | None = None) -> StrategyTestReport:
        if user_id is not None:
            detail = self._run_detail(run_id, user_id=user_id)
            if detail is None:
                raise ValueError(f"Strategy test run is not found: {run_id}")
        return self._report_builder().build_report(run_id)

    def list_reports(self, user_id: str = "demo_user", limit: int = 50) -> list[StrategyTestReport]:
        return self._report_builder().list_reports(user_id=user_id, limit=limit)

    def _report_builder(self) -> StrategyTestReportBuilder:
        return StrategyTestReportBuilder(
            run_store=self._run_store,
            analytics_store=self._trade_store,
        )

    def _run_detail(self, run_id: UUID, *, user_id: str | None = None) -> StrategyTestRunDetailResponse | None:
        detail = self._run_store.get_run(run_id)
        if detail is None or user_id is None:
            return detail
        self._ensure_run_belongs_to_user(detail, user_id=user_id)
        return detail

    def _ensure_run_belongs_to_user(self, detail: StrategyTestRunDetailResponse, *, user_id: str) -> None:
        requested_user_id = _run_requested_user_id(detail.run)
        if requested_user_id == user_id:
            return
        get_run_for_user = getattr(self._run_store, "get_run_for_user", None)
        if callable(get_run_for_user) and get_run_for_user(detail.run.run_id, user_id=user_id) is not None:
            return
        for owned_detail in self._run_store.list_runs(user_id=user_id, limit=500, status=None):
            if owned_detail.run.run_id == detail.run.run_id:
                return
        raise PermissionError("Cannot access strategy test run for another user.")


def _failure_message(matrix_result: StrategyTestMatrixResult) -> str:
    if matrix_result.errors:
        return f"All strategy test scenarios failed: {matrix_result.errors[0]['error']}"
    return "All strategy test scenarios failed"


_HISTORICAL_RUNTIME_PHASES = {
    "queued",
    "running",
    "estimating_failed",
    "prefetching_market_data",
    "loading_candles",
    "building_features",
    "running_scenario",
    "writing_results",
    "building_report",
    "completed",
    "failed",
    "cancelled",
    "stopping",
}


def _initial_historical_runtime_state(
    request: StrategyTestRunRequest,
    *,
    phase: str,
) -> dict[str, Any]:
    partial_summary = _empty_partial_summary(_scenario_total(request))
    return _runtime_state_base(
        request=request,
        phase=phase,
        partial_summary=partial_summary,
        last_error=None,
    )


def _scenario_runtime_state(
    *,
    context: StrategyTestScenarioContext,
    request: StrategyTestRunRequest,
    phase: str,
    partial_summary: dict[str, Any] | None,
    progress: dict[str, Any] | None = None,
    last_error: str | None = None,
    scenario_status: str | None = None,
    scenario_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = partial_summary or _empty_partial_summary(_scenario_total(request))
    state = _runtime_state_base(
        request=request,
        phase=phase,
        partial_summary=summary,
        last_error=last_error,
    )
    state.update(
        {
            "current_strategy": context.strategy,
            "current_exchange": context.exchange,
            "current_symbol": context.symbol,
            "current_timeframe": context.timeframe,
            "current_scenario_key": _scenario_key(context),
            "current_scenario_index": _int_value(getattr(context, "index", 0), default=0) or None,
            "scenario_status": scenario_status,
        }
    )
    if scenario_summary is not None:
        state["current_scenario_summary"] = dict(scenario_summary)
    if progress:
        current_bars_processed = _int_value(
            progress.get("current_scenario_bars_processed", progress.get("scenario_bars_processed"))
        )
        current_bars_total = _optional_int_value(
            progress.get("current_scenario_bars_total", progress.get("scenario_bars_total"))
        )
        matrix_bars_processed = _int_value(progress.get("matrix_bars_processed", progress.get("bars_processed")))
        matrix_bars_total = _optional_int_value(progress.get("matrix_bars_total", progress.get("bars_total")))
        state["current_scenario_bars_processed"] = current_bars_processed
        state["current_scenario_bars_total"] = current_bars_total
        state["matrix_bars_processed"] = matrix_bars_processed
        state["matrix_bars_total"] = matrix_bars_total
        state["bars_processed"] = matrix_bars_processed
        state["bars_total"] = matrix_bars_total
        state["scenario_bars_processed"] = current_bars_processed
        state["scenario_bars_total"] = current_bars_total
        state["pending_entries_count"] = _int_value(progress.get("pending_entries_count"))
        state["bars_pct"] = _non_negative_float(progress.get("bars_pct"), default=0.0)
        elapsed_seconds = progress.get("elapsed_seconds")
        if elapsed_seconds is None and progress.get("elapsed_ms") is not None:
            elapsed_seconds = _non_negative_float(progress.get("elapsed_ms"), default=0.0) / 1000
        state["elapsed_seconds"] = _non_negative_float(elapsed_seconds, default=0.0)
        state["elapsed_ms"] = round(state["elapsed_seconds"] * 1000, 3)
        state["bars_per_second"] = _non_negative_float(progress.get("bars_per_second"), default=0.0)
        state["eta_seconds"] = _non_negative_float(progress.get("eta_seconds"), default=0.0)
        if progress.get("matrix_bars_estimate_status") is not None:
            state["matrix_bars_estimate_status"] = str(progress["matrix_bars_estimate_status"])
        warnings = progress.get("warnings")
        if isinstance(warnings, list):
            state["warnings"] = list(warnings)
        for key in (
            "current_pair",
            "market_data_prefetch_total",
            "market_data_prefetch_completed",
            "market_data_prefetch_failed",
            "current_scenario",
            "scenario_count",
            "completed_scenarios",
            "failed_scenarios",
        ):
            if key in progress:
                state[key] = progress[key]
    return _validated_runtime_state(state)


def _terminal_runtime_state(
    *,
    request: StrategyTestRunRequest,
    phase: str,
    partial_summary: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    summary = partial_summary or _empty_partial_summary(_scenario_total(request))
    state = _runtime_state_base(
        request=request,
        phase=phase,
        partial_summary=summary,
        last_error=last_error,
    )
    state.update(
        {
            "current_strategy": None,
            "current_exchange": None,
            "current_symbol": None,
            "current_timeframe": None,
            "current_scenario_key": None,
            "current_scenario_index": None,
            "current_scenario_bars_processed": 0,
            "current_scenario_bars_total": None,
            "scenario_bars_processed": 0,
            "scenario_bars_total": None,
            "scenario_status": None,
            "current_scenario_summary": None,
        }
    )
    return _validated_runtime_state(state)


def _runtime_state_base(
    *,
    request: StrategyTestRunRequest,
    phase: str,
    partial_summary: dict[str, Any],
    last_error: str | None,
) -> dict[str, Any]:
    normalized_phase = _runtime_phase(phase, fallback="running")
    partial_summary = _normalize_summary(partial_summary)
    scenario_total = _summary_int(partial_summary, "scenario_count", _scenario_total(request))
    counters = _runtime_counters(partial_summary)
    return _validated_runtime_state({
        "phase": normalized_phase,
        "scenarios_total": scenario_total,
        "scenarios_completed": _summary_int(partial_summary, "completed_scenarios", 0),
        "scenarios_failed": _summary_int(partial_summary, "failed_scenarios", 0),
        "scenario_total": scenario_total,
        "scenario_completed": _summary_int(partial_summary, "completed_scenarios", 0),
        "scenario_failed": _summary_int(partial_summary, "failed_scenarios", 0),
        "current_strategy": None,
        "current_exchange": None,
        "current_symbol": None,
        "current_timeframe": None,
        "current_scenario_key": None,
        "current_scenario_index": None,
        "current_scenario_bars_processed": 0,
        "current_scenario_bars_total": None,
        "matrix_bars_processed": 0,
        "matrix_bars_total": None,
        "bars_processed": 0,
        "bars_total": None,
        "bars_pct": 0.0,
        "elapsed_seconds": 0.0,
        "elapsed_ms": 0.0,
        "bars_per_second": 0.0,
        "eta_seconds": None,
        "scenario_status": None,
        "current_scenario_summary": None,
        "signals_seen": counters["signals"],
        "signals_count": counters["signals"],
        "execution_candidates": counters["execution_candidates"],
        "pending_armed": counters["pending_armed"],
        "touched": _summary_int(partial_summary, "touched", 0),
        "entry_touched": _summary_int(partial_summary, "entry_touched", 0),
        "filled": counters["filled"],
        "closed": counters["closed"],
        "no_entry": counters["no_entry"],
        "not_selected": _summary_int(partial_summary, "not_selected", 0),
        "trades_count": _summary_int(partial_summary, "trades_count", 0),
        "risk_rejections": counters["risk_rejections"],
        "execution_rejections": counters["execution_rejections"],
        "pending_entries_count": counters["pending_entries"],
        "counters": counters,
        "last_progress_at": _now_iso(),
        "last_heartbeat_at": None,
        "stale_threshold_seconds": _strategy_test_stale_threshold_seconds(),
        "last_error": last_error,
        "partial_summary": dict(partial_summary),
    })


def _partial_summary_with_progress(
    partial_summary: dict[str, Any],
    progress: dict[str, Any],
) -> dict[str, Any]:
    combined = dict(partial_summary)
    counter_keys = (
        "signals_seen",
        "signals_count",
        "execution_candidates",
        "pending_armed",
        "touched",
        "entry_touched",
        "filled",
        "closed",
        "no_entry",
        "not_selected",
        "trades_count",
        "risk_rejections",
        "execution_rejections",
    )
    for key in counter_keys:
        progress_value = _int_value(progress.get(key))
        if progress_value:
            combined[key] = _summary_int(combined, key, 0) + progress_value
    if "signals_count" not in combined and "signals_seen" in combined:
        combined["signals_count"] = combined["signals_seen"]
    return _normalize_summary(combined)


def _empty_partial_summary(scenario_total: int) -> dict[str, Any]:
    return {
        "scenario_count": scenario_total,
        "completed_scenarios": 0,
        "failed_scenarios": 0,
        "trades_count": 0,
        "signals_seen": 0,
        "signals_count": 0,
        "execution_candidates": 0,
        "pending_armed": 0,
        "touched": 0,
        "entry_touched": 0,
        "filled": 0,
        "closed": 0,
        "no_entry": 0,
        "not_selected": 0,
        "risk_rejections": 0,
        "execution_rejections": 0,
        "errors": [],
        "scenarios": [],
    }


def _normalize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(summary)
    for key in (
        "scenario_count",
        "completed_scenarios",
        "failed_scenarios",
        "trades_count",
        "signals_seen",
        "signals_count",
        "execution_candidates",
        "pending_armed",
        "touched",
        "entry_touched",
        "filled",
        "closed",
        "no_entry",
        "not_selected",
        "risk_rejections",
        "execution_rejections",
    ):
        normalized[key] = _summary_int(normalized, key, 0)
    if normalized["signals_count"] == 0 and normalized["signals_seen"]:
        normalized["signals_count"] = normalized["signals_seen"]
    if normalized["signals_seen"] == 0 and normalized["signals_count"]:
        normalized["signals_seen"] = normalized["signals_count"]
    if normalized["touched"] == 0 and normalized["entry_touched"]:
        normalized["touched"] = normalized["entry_touched"]
    if normalized["entry_touched"] == 0 and normalized["touched"]:
        normalized["entry_touched"] = normalized["touched"]
    errors = normalized.get("errors")
    normalized["errors"] = list(errors) if isinstance(errors, list) else []
    scenarios = normalized.get("scenarios")
    normalized["scenarios"] = list(scenarios) if isinstance(scenarios, list) else []
    return normalized


def _summary_from_run(run: StrategyTestRunResponse) -> dict[str, Any] | None:
    if run.summary:
        return _normalize_summary(run.summary)
    partial_summary = run.runtime_state.get("partial_summary")
    if isinstance(partial_summary, dict):
        return _normalize_summary(partial_summary)
    return None


def _scenario_total(request: StrategyTestRunRequest) -> int:
    return len(request.strategies) * len(request.pairs) * len(request.timeframes)


def _validate_strategy_test_resource_limits(
    request: StrategyTestRunRequest,
    provider: HistoricalCandleProvider,
) -> None:
    _validate_scenario_count(
        request,
        max_scenarios=settings.strategy_test_max_scenarios_per_run,
        setting_name="strategy_test_max_scenarios_per_run",
    )
    if request.test_type != "historical_backtest":
        return
    estimate = _estimate_historical_run(request, provider)
    failed_warnings = [warning for warning in estimate.warnings if warning.code == "estimating_failed"]
    if failed_warnings:
        return
    max_bars = max(1, int(settings.strategy_test_max_bars_per_run))
    if estimate.total_bars > max_bars:
        raise ValueError(
            "strategy_test_max_bars_per_run exceeded: "
            f"{estimate.total_bars} bars requested, max is {max_bars}."
        )


def _validate_enqueued_strategy_test_resource_limits(request: StrategyTestRunRequest) -> None:
    if request.test_type == "historical_backtest":
        _validate_scenario_count(
            request,
            max_scenarios=settings.strategy_test_max_enqueued_historical_scenarios_per_run,
            setting_name="strategy_test_max_enqueued_historical_scenarios_per_run",
        )
        return
    _validate_scenario_count(
        request,
        max_scenarios=settings.strategy_test_max_scenarios_per_run,
        setting_name="strategy_test_max_scenarios_per_run",
    )


def _validate_worker_strategy_test_resource_limits(
    request: StrategyTestRunRequest,
    provider: HistoricalCandleProvider,
) -> list[str]:
    if request.test_type != "historical_backtest":
        return []
    _validate_scenario_count(
        request,
        max_scenarios=settings.strategy_test_max_enqueued_historical_scenarios_per_run,
        setting_name="strategy_test_max_enqueued_historical_scenarios_per_run",
    )
    estimate = _estimate_historical_run(request, provider)
    failed_warnings = [warning for warning in estimate.warnings if warning.code == "estimating_failed"]
    if failed_warnings:
        return [warning.message for warning in failed_warnings]
    max_bars = max(1, int(settings.strategy_test_max_bars_per_run))
    if estimate.total_bars > max_bars:
        raise ValueError(
            "strategy_test_max_bars_per_run exceeded: "
            f"{estimate.total_bars} bars requested, max is {max_bars}."
        )
    return []


def _validate_scenario_count(
    request: StrategyTestRunRequest,
    *,
    max_scenarios: int,
    setting_name: str,
) -> None:
    scenario_count = _scenario_total(request)
    limit = max(1, int(max_scenarios))
    if scenario_count > limit:
        raise ValueError(
            f"{setting_name} exceeded: "
            f"{scenario_count} scenarios requested, max is {limit}."
        )


def _estimate_historical_run(
    request: StrategyTestRunRequest,
    provider: HistoricalCandleProvider,
) -> StrategyTestEstimateResponse:
    scenario_count = _scenario_total(request)
    if request.test_type != "historical_backtest":
        return StrategyTestEstimateResponse(
            scenario_count=scenario_count,
            total_bars=0,
            average_bars_per_scenario=0 if scenario_count else None,
            size_level=_estimate_level(scenario_count, 0),
            scenarios=[],
            warnings=[],
        )

    warmup_bars = _estimate_warmup_bars(request)
    counts_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    warnings: list[StrategyTestEstimateWarning] = []
    for pair in request.pairs:
        for timeframe in request.timeframes:
            key = (pair.exchange, pair.symbol, timeframe)
            if key in counts_by_key:
                continue
            try:
                deduped_candles = _run_awaitable_sync(
                    provider.count_candles(
                        exchange=pair.exchange,
                        symbol=pair.symbol,
                        timeframe=timeframe,
                        start_at=request.start_at,
                        end_at=request.end_at,
                    )
                )
            except Exception as exc:
                warnings.append(
                    StrategyTestEstimateWarning(
                        code="estimating_failed",
                        exchange=pair.exchange,
                        symbol=pair.symbol,
                        timeframe=timeframe,
                        message=(
                            "Unable to count deduped historical candles for "
                            f"{pair.exchange}:{pair.symbol}:{timeframe}: {exc}"
                        ),
                    )
                )
                counts_by_key[key] = {
                    "deduped_candles": 0,
                    "raw_rows": 0,
                    "warning_codes": ["estimating_failed"],
                }
                continue
            raw_rows = _raw_candle_count(
                provider,
                exchange=pair.exchange,
                symbol=pair.symbol,
                timeframe=timeframe,
                start_at=request.start_at,
                end_at=request.end_at,
                fallback=deduped_candles,
            )
            warning_codes, key_warnings = _estimate_count_warnings(
                exchange=pair.exchange,
                symbol=pair.symbol,
                timeframe=timeframe,
                deduped_candles=deduped_candles,
                raw_rows=raw_rows,
                warmup_bars=warmup_bars,
            )
            warnings.extend(key_warnings)
            counts_by_key[key] = {
                "deduped_candles": deduped_candles,
                "raw_rows": raw_rows,
                "warning_codes": warning_codes,
            }

    scenarios: list[StrategyTestScenarioEstimate] = []
    for strategy in request.strategies:
        for pair in request.pairs:
            for timeframe in request.timeframes:
                counts = counts_by_key[(pair.exchange, pair.symbol, timeframe)]
                deduped_candles = int(counts["deduped_candles"])
                raw_rows = int(counts["raw_rows"])
                scenarios.append(
                    StrategyTestScenarioEstimate(
                        strategy=strategy,
                        exchange=pair.exchange,
                        symbol=pair.symbol,
                        timeframe=timeframe,
                        candles_count=deduped_candles,
                        raw_rows=raw_rows,
                        duplicate_rows=max(0, raw_rows - deduped_candles),
                        warmup_bars=warmup_bars,
                        bars_total=max(0, deduped_candles - warmup_bars),
                        warning_codes=list(counts["warning_codes"]),
                    )
                )

    total_bars = sum(scenario.bars_total for scenario in scenarios)
    average = round(total_bars / scenario_count) if scenario_count else None
    return StrategyTestEstimateResponse(
        scenario_count=scenario_count,
        total_bars=total_bars,
        average_bars_per_scenario=average,
        size_level=_estimate_level(scenario_count, total_bars),
        scenarios=scenarios,
        warnings=warnings,
    )


def _raw_candle_count(
    provider: HistoricalCandleProvider,
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    start_at: datetime,
    end_at: datetime,
    fallback: int,
) -> int:
    count_raw = getattr(provider, "count_raw_candles", None)
    if not callable(count_raw):
        return fallback
    return int(
        _run_awaitable_sync(
            count_raw(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                start_at=start_at,
                end_at=end_at,
            )
        )
    )


def _estimate_count_warnings(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    deduped_candles: int,
    raw_rows: int,
    warmup_bars: int,
) -> tuple[list[StrategyTestEstimateWarningCode], list[StrategyTestEstimateWarning]]:
    codes: list[StrategyTestEstimateWarningCode] = []
    warnings: list[StrategyTestEstimateWarning] = []
    if deduped_candles == 0:
        codes.append("market_data_missing")
        warnings.append(
            StrategyTestEstimateWarning(
                code="market_data_missing",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                message=f"No closed candles found for {exchange}:{symbol}:{timeframe}.",
                raw_rows=raw_rows,
                deduped_candles=deduped_candles,
            )
        )
        return codes, warnings

    if deduped_candles <= warmup_bars:
        codes.append("market_data_below_warmup")
        warnings.append(
            StrategyTestEstimateWarning(
                code="market_data_below_warmup",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                message=(
                    f"{exchange}:{symbol}:{timeframe} has {deduped_candles} deduped candles, "
                    f"which does not exceed the {warmup_bars} warmup bars."
                ),
                raw_rows=raw_rows,
                deduped_candles=deduped_candles,
            )
        )

    duplicate_ratio = raw_rows / deduped_candles if deduped_candles else 0.0
    if raw_rows > deduped_candles and duplicate_ratio >= STRATEGY_TEST_DUPLICATE_WARNING_RATIO:
        codes.append("market_data_duplicates")
        warnings.append(
            StrategyTestEstimateWarning(
                code="market_data_duplicates",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                message=(
                    f"{exchange}:{symbol}:{timeframe} has {raw_rows} raw candle rows for "
                    f"{deduped_candles} deduped candles."
                ),
                raw_rows=raw_rows,
                deduped_candles=deduped_candles,
                duplicate_ratio=round(duplicate_ratio, 4),
            )
        )
    return codes, warnings


def _estimate_warmup_bars(request: StrategyTestRunRequest) -> int:
    value = request.params.get("warmup_candles")
    if value is None:
        return DEFAULT_WARMUP_CANDLES
    return max(1, _int_value(value, default=DEFAULT_WARMUP_CANDLES))


def _estimate_level(scenario_count: int, total_bars: int) -> str:
    if total_bars >= STRATEGY_TEST_LARGE_ESTIMATE_BARS or scenario_count >= STRATEGY_TEST_LARGE_ESTIMATE_SCENARIOS:
        return "large"
    if total_bars >= STRATEGY_TEST_MEDIUM_ESTIMATE_BARS or scenario_count >= STRATEGY_TEST_MEDIUM_ESTIMATE_SCENARIOS:
        return "medium"
    return "small"


def _runtime_phase(value: object, *, fallback: str) -> str:
    phase = str(value or "").strip()
    if phase in _HISTORICAL_RUNTIME_PHASES:
        return phase
    return fallback


def _summary_int(summary: dict[str, Any], key: str, default: int = 0) -> int:
    if key not in summary:
        return default
    return _int_value(summary.get(key), default=default)


def _int_value(value: object, *, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _optional_int_value(value: object) -> int | None:
    if value is None:
        return None
    return max(0, _int_value(value, default=0))


def _float_value(value: object, *, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _non_negative_float(value: object, *, default: float) -> float:
    parsed = _float_value(value, default=default)
    if parsed is None:
        return default
    return max(0.0, parsed)


def _runtime_counters(summary: dict[str, Any]) -> dict[str, int]:
    signals = _summary_int(summary, "signals_count", 0) or _summary_int(summary, "signals_seen", 0)
    return {
        "signals": signals,
        "execution_candidates": _summary_int(summary, "execution_candidates", 0),
        "pending_armed": _summary_int(summary, "pending_armed", 0),
        "pending_entries": _summary_int(summary, "pending_entries_count", 0),
        "no_entry": _summary_int(summary, "no_entry", 0),
        "filled": _summary_int(summary, "filled", 0),
        "closed": _summary_int(summary, "closed", 0),
        "risk_rejections": _summary_int(summary, "risk_rejections", 0),
        "execution_rejections": _summary_int(summary, "execution_rejections", 0),
    }


def _validated_runtime_state(state: dict[str, Any]) -> dict[str, Any]:
    return StrategyTestRuntimeState.model_validate(state).model_dump(mode="json")


def _strategy_test_stale_threshold_seconds() -> int:
    return max(1, int(settings.strategy_test_lease_seconds))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _ScenarioResultPersistenceSink:
    def __init__(
        self,
        *,
        trade_store: StrategyTestTradeStore,
        run_store: StrategyTestRunStore,
        run_id: UUID,
        user_id: UUID,
        request: StrategyTestRunRequest,
    ) -> None:
        self._trade_store = trade_store
        self._run_store = run_store
        self._run_id = run_id
        self._user_id = user_id
        self._request = request
        self.results_written = 0

    def write_result(
        self,
        context: StrategyTestScenarioContext,
        result: Any,
        partial_summary: dict[str, Any],
    ) -> None:
        _ = partial_summary
        _write_scenario_result_once(
            self._trade_store,
            run_id=self._run_id,
            user_id=self._user_id,
            request=self._request,
            context=context,
            result=result,
            written_trade_keys=set(),
            written_signal_event_keys=set(),
            written_metric_keys=set(),
        )
        _mark_scenario_completed(
            self._run_store,
            self._run_id,
            context,
            result,
        )
        self.results_written += 1


def _completed_scenario_summaries_by_key(
    run_store: StrategyTestRunStore,
    run_id: UUID,
) -> dict[str, dict[str, Any]]:
    list_scenarios = getattr(run_store, "list_scenarios", None)
    if not callable(list_scenarios):
        return {}
    scenarios = list_scenarios(run_id)
    summaries: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        if _checkpoint_attr(scenario, "status") != "completed":
            continue
        scenario_key = _text(_checkpoint_attr(scenario, "scenario_key"))
        if not scenario_key:
            continue
        summary = dict(_checkpoint_attr(scenario, "summary", {}) or {})
        summary.setdefault("scenario_key", scenario_key)
        summary.setdefault("strategy", _checkpoint_attr(scenario, "strategy_code"))
        summary.setdefault("exchange", _checkpoint_attr(scenario, "exchange"))
        summary.setdefault("symbol", _checkpoint_attr(scenario, "symbol"))
        summary.setdefault("timeframe", _checkpoint_attr(scenario, "timeframe"))
        summaries[scenario_key] = summary
    return summaries


def _mark_scenario_running(
    run_store: StrategyTestRunStore,
    run_id: UUID,
    context: StrategyTestScenarioContext,
) -> None:
    mark_running = getattr(run_store, "mark_scenario_running", None)
    if not callable(mark_running):
        return
    mark_running(
        run_id,
        scenario_key=_scenario_key(context),
        scenario_index=_int_value(getattr(context, "index", 0), default=0),
        strategy_code=context.strategy,
        exchange=context.exchange,
        symbol=context.symbol,
        timeframe=context.timeframe,
    )


def _mark_scenario_completed(
    run_store: StrategyTestRunStore,
    run_id: UUID,
    context: StrategyTestScenarioContext,
    result: Any,
) -> None:
    mark_completed = getattr(run_store, "mark_scenario_completed", None)
    if not callable(mark_completed):
        return
    mark_completed(
        run_id,
        scenario_key=_scenario_key(context),
        summary=_completed_scenario_summary(context, result),
        bars_processed=_result_bars_processed(result),
        result_written_at=datetime.now(timezone.utc),
    )


def _mark_scenario_failed(
    run_store: StrategyTestRunStore,
    run_id: UUID,
    context: StrategyTestScenarioContext,
    exc: Exception,
    partial_summary: dict[str, Any],
) -> None:
    mark_failed = getattr(run_store, "mark_scenario_failed", None)
    if not callable(mark_failed):
        return
    mark_failed(
        run_id,
        scenario_key=_scenario_key(context),
        error=str(exc),
        summary=_failed_scenario_summary(context, exc, partial_summary),
    )


def _checkpoint_attr(checkpoint: Any, name: str, default: Any = None) -> Any:
    if isinstance(checkpoint, dict):
        return checkpoint.get(name, default)
    return getattr(checkpoint, name, default)


def _result_bars_processed(result: Any) -> int | None:
    summary = dict(getattr(result, "summary", {}) or {})
    timings = summary.get("timings")
    if isinstance(timings, dict):
        bars_total = _summary_int(timings, "bars_total", 0)
        if bars_total > 0:
            return bars_total
    bars_processed = _summary_int(summary, "bars_processed", 0)
    if bars_processed > 0:
        return bars_processed
    bars_total = _summary_int(summary, "bars_total", 0)
    return bars_total if bars_total > 0 else None


def _write_scenario_result_once(
    trade_store: StrategyTestTradeStore,
    *,
    run_id: UUID,
    user_id: UUID,
    request: StrategyTestRunRequest,
    context: StrategyTestScenarioContext,
    result: Any,
    written_trade_keys: set[tuple[str, str, str]],
    written_signal_event_keys: set[tuple[str, str, str]],
    written_metric_keys: set[tuple[str, ...]],
) -> None:
    if result is None:
        return
    trades = list(getattr(result, "trades", []) or [])
    signal_events = list(getattr(result, "signal_events", []) or [])
    summary = dict(getattr(result, "summary", {}) or {})
    scenario_key = _scenario_key(context)

    _write_trades_once(
        trade_store,
        trades,
        scenario_key=scenario_key,
        written_trade_keys=written_trade_keys,
    )
    _write_signal_events_once(
        trade_store,
        signal_events,
        scenario_key=scenario_key,
        written_signal_event_keys=written_signal_event_keys,
    )
    _write_metrics_once(
        trade_store,
        _scenario_metric_rows(
            run_id=run_id,
            user_id=user_id,
            request=request,
            context=context,
            trades=trades,
            signal_events=signal_events,
            summary=summary,
        ),
        written_metric_keys=written_metric_keys,
    )


def _write_trades_once(
    trade_store: StrategyTestTradeStore,
    trades: Sequence[StrategyTestTrade],
    *,
    written_trade_keys: set[tuple[str, str, str]],
    scenario_key: str | None = None,
) -> None:
    if not trades:
        return
    _ensure_trade_store_schema(trade_store)
    new_trades: list[StrategyTestTrade] = []
    new_keys: set[tuple[str, str, str]] = set()
    for trade in trades:
        key = _trade_idempotency_key(trade, scenario_key=scenario_key)
        if key in written_trade_keys or key in new_keys:
            continue
        new_trades.append(trade)
        new_keys.add(key)
    if new_trades:
        trade_store.write_trades(new_trades)
    written_trade_keys.update(new_keys)


def _write_signal_events_once(
    trade_store: StrategyTestTradeStore,
    signal_events: Sequence[StrategyTestSignalEvent],
    *,
    written_signal_event_keys: set[tuple[str, str, str]],
    scenario_key: str | None = None,
) -> None:
    if not signal_events:
        return
    _ensure_trade_store_schema(trade_store)
    new_events: list[StrategyTestSignalEvent] = []
    new_keys: set[tuple[str, str, str]] = set()
    for event in signal_events:
        key = _signal_event_idempotency_key(event, scenario_key=scenario_key)
        if key in written_signal_event_keys or key in new_keys:
            continue
        new_events.append(event)
        new_keys.add(key)
    if new_events:
        write_events = getattr(trade_store, "write_signal_events", None)
        if not callable(write_events):
            raise RuntimeError("strategy_test_signal_event_store_not_available")
        write_events(new_events)
    written_signal_event_keys.update(new_keys)


def _write_metrics_once(
    trade_store: StrategyTestTradeStore,
    rows: Sequence[StrategyTestMetricRow],
    *,
    written_metric_keys: set[tuple[str, ...]],
) -> None:
    if not rows:
        return
    _ensure_trade_store_schema(trade_store)
    new_rows: list[StrategyTestMetricRow] = []
    new_keys: set[tuple[str, ...]] = set()
    for row in rows:
        key = _metric_idempotency_key(row)
        if key in written_metric_keys or key in new_keys:
            continue
        new_rows.append(row)
        new_keys.add(key)
    if new_rows:
        trade_store.write_metrics(new_rows)
    written_metric_keys.update(new_keys)


def _scenario_metric_rows(
    *,
    run_id: UUID,
    user_id: UUID,
    request: StrategyTestRunRequest,
    context: StrategyTestScenarioContext,
    trades: Sequence[StrategyTestTrade],
    signal_events: Sequence[StrategyTestSignalEvent],
    summary: dict[str, Any],
) -> list[StrategyTestMetricRow]:
    scenario_key = _scenario_key(context)
    created_at = datetime.now(timezone.utc)
    metric_results = build_matrix_metric_results(
        trades,
        signal_events=signal_events,
        metric_set=request.metric_set,
    )
    rows = metric_results_to_rows(
        run_id=run_id,
        user_id=user_id,
        mode=request.mode,
        results=metric_results,
        created_at=created_at,
    )
    enriched = [
        _with_scenario_metric_metadata(
            row,
            context=context,
            scenario_key=scenario_key,
            summary=summary,
        )
        for row in rows
    ]
    enriched.append(
        StrategyTestMetricRow(
            run_id=run_id,
            user_id=user_id,
            mode=request.mode,
            strategy_code=context.strategy,
            exchange=context.exchange,
            symbol=context.symbol,
            timeframe=context.timeframe,
            market_regime="all",
            score_bucket="all",
            direction="all",
            metric_code="scenario_summary",
            metric_value=None,
            sample_size=_summary_int(summary, "signals_seen", len(signal_events)),
            metadata={
                "source": "scenario_completed",
                "scenario_key": scenario_key,
                "scenario_index": _int_value(getattr(context, "index", 0), default=0) or None,
                "scenario_total": _int_value(getattr(context, "total", 0), default=0) or None,
                "summary": dict(summary),
            },
            created_at=created_at,
        )
    )
    return enriched


def _with_scenario_metric_metadata(
    row: StrategyTestMetricRow,
    *,
    context: StrategyTestScenarioContext,
    scenario_key: str,
    summary: dict[str, Any],
) -> StrategyTestMetricRow:
    metadata = dict(row.metadata)
    metadata.update(
        {
            "source": "scenario_completed",
            "scenario_key": scenario_key,
            "scenario_index": _int_value(getattr(context, "index", 0), default=0) or None,
            "scenario_total": _int_value(getattr(context, "total", 0), default=0) or None,
            "scenario_summary": dict(summary),
        }
    )
    return row.model_copy(
        update={
            "strategy_code": row.strategy_code if row.strategy_code != "all" else context.strategy,
            "exchange": row.exchange if row.exchange != "all" else context.exchange,
            "symbol": row.symbol if row.symbol != "all" else context.symbol,
            "timeframe": row.timeframe if row.timeframe != "all" else context.timeframe,
            "metadata": metadata,
        }
    )


def _trade_idempotency_key(
    trade: StrategyTestTrade,
    *,
    scenario_key: str | None = None,
) -> tuple[str, str, str]:
    return (
        str(trade.run_id),
        scenario_key or _scenario_key_from_values(
            trade.strategy_code,
            trade.exchange,
            trade.symbol,
            trade.timeframe,
        ),
        str(trade.trade_id),
    )


def _signal_event_idempotency_key(
    event: StrategyTestSignalEvent,
    *,
    scenario_key: str | None = None,
) -> tuple[str, str, str]:
    event_id = event.signal_id or event.synthetic_signal_id or event.signal_key
    return (
        str(event.run_id),
        scenario_key or _scenario_key_from_values(
            event.strategy_code,
            event.exchange,
            event.symbol,
            event.timeframe,
        ),
        str(event_id),
    )


def _metric_idempotency_key(row: StrategyTestMetricRow) -> tuple[str, ...]:
    return (
        str(row.run_id),
        str(row.metadata.get("scenario_key") or ""),
        row.strategy_code,
        row.exchange,
        row.symbol,
        row.timeframe,
        row.market_regime,
        row.score_bucket,
        row.direction,
        row.metric_code,
    )


def _scenario_key(context: StrategyTestScenarioContext) -> str:
    return _scenario_key_from_values(
        context.strategy,
        context.exchange,
        context.symbol,
        context.timeframe,
    )


def _scenario_key_from_values(
    strategy: object,
    exchange: object,
    symbol: object,
    timeframe: object,
) -> str:
    return "::".join(_key_text(value) for value in (strategy, exchange, symbol, timeframe))


def _scenario_status_summary(
    context: StrategyTestScenarioContext,
    *,
    status: str,
) -> dict[str, Any]:
    return {
        "scenario_key": _scenario_key(context),
        "scenario_index": _int_value(getattr(context, "index", 0), default=0) or None,
        "scenario_total": _int_value(getattr(context, "total", 0), default=0) or None,
        "status": status,
        "strategy": context.strategy,
        "exchange": context.exchange,
        "symbol": context.symbol,
        "timeframe": context.timeframe,
    }


def _completed_scenario_summary(
    context: StrategyTestScenarioContext,
    result: Any,
) -> dict[str, Any]:
    summary = dict(getattr(result, "summary", {}) or {})
    return {
        **_scenario_status_summary(context, status="completed"),
        **summary,
    }


def _failed_scenario_summary(
    context: StrategyTestScenarioContext,
    exc: Exception,
    partial_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        **_scenario_status_summary(context, status="failed"),
        "error": str(exc),
        "partial_summary": dict(partial_summary),
    }


def _key_text(value: object) -> str:
    return str(value or "unknown").strip() or "unknown"


def _ensure_trade_store_schema(trade_store: StrategyTestTradeStore) -> None:
    ensure_schema = getattr(trade_store, "ensure_schema", None)
    if callable(ensure_schema):
        ensure_schema()


def _append_summary_warning(summary: dict[str, object], code: str, message: str) -> None:
    warnings = summary.setdefault("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        summary["warnings"] = warnings
    warnings.append({"code": code, "message": message})


def _auto_publish_calibration(request: StrategyTestRunRequest) -> bool:
    return request.params.get("auto_publish_calibration") is True


def _request_from_run(run: StrategyTestRunResponse) -> StrategyTestRunRequest:
    return StrategyTestRunRequest(**dict(run.requested_matrix))


def _run_requested_user_id(run: StrategyTestRunResponse) -> str | None:
    value = run.requested_matrix.get("user_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _metric_results_from_run_summary(summary: dict[str, Any]) -> list[MetricResult]:
    grouped_metrics = summary.get("grouped_metrics")
    if not isinstance(grouped_metrics, list):
        return []
    results: list[MetricResult] = []
    for item in grouped_metrics:
        if not isinstance(item, dict):
            continue
        code = _text(item.get("code"))
        if not code:
            continue
        group = item.get("group")
        if not isinstance(group, dict):
            continue
        results.append(
            MetricResult(
                code=code,
                label=_text(item.get("label")) or code,
                value=_metric_value(item.get("value")),
                sample_size=_sample_size(item.get("sample_size")),
                group={str(key): str(value) for key, value in group.items()},
                warnings=[str(warning) for warning in item.get("warnings", []) if warning is not None]
                if isinstance(item.get("warnings"), list)
                else [],
            )
        )
    return results


def _calibration_response(
    *,
    run_id: UUID,
    profiles: Sequence[Any],
) -> StrategyTestCalibrationResponse:
    profile_responses = [_calibration_profile(run_id=run_id, profile=profile) for profile in profiles]
    decision = _aggregate_calibration_decision(profile_responses)
    return StrategyTestCalibrationResponse(
        run_id=run_id,
        decision=decision,
        profiles_count=len(profile_responses),
        profiles=profile_responses,
        reason=_calibration_reason(profile_responses),
        generated_at=datetime.now(timezone.utc),
    )


def _calibration_profile(
    *,
    run_id: UUID,
    profile: Any,
) -> StrategyTestCalibrationProfile:
    decision = _profile_decision(profile)
    run_ids = [str(item) for item in (_profile_attr(profile, "run_ids", []) or []) if str(item)]
    return StrategyTestCalibrationProfile(
        strategy_code=str(_profile_attr(profile, "strategy_code", "unknown")),
        exchange=str(_profile_attr(profile, "exchange", "unknown")),
        symbol_scope=str(_profile_attr(profile, "symbol_scope", "unknown")),
        timeframe=str(_profile_attr(profile, "timeframe", "unknown")),
        market_regime=str(_profile_attr(profile, "market_regime", "unknown")),
        score_bucket=str(_profile_attr(profile, "score_bucket", "unknown")),
        direction=str(_profile_attr(profile, "direction", "long")),
        decision=decision,
        eligible=bool(_profile_attr(profile, "eligible", False)),
        source=str(_profile_attr(profile, "source", "historical_backtest")),
        source_run_id=run_id,
        sample_size=_sample_size(_profile_attr(profile, "sample_size", 0)),
        expectancy_after_costs_r=_optional_float(_profile_attr(profile, "expectancy_after_costs_r", None)),
        profit_factor=_optional_float(_profile_attr(profile, "profit_factor", None)),
        entry_touch_rate=_optional_float(_profile_attr(profile, "entry_touch_rate", None)),
        no_entry_rate=_optional_float(_profile_attr(profile, "no_entry_rate", None)),
        max_drawdown_r=_optional_float(_profile_attr(profile, "max_drawdown_r", None)),
        run_ids=run_ids,
        reason_code=str(_profile_attr(profile, "reason_code", "strategy_eligibility_missing")),
        reason=str(_profile_attr(profile, "reason", "No execution edge profile is available for this strategy.")),
        metrics=dict(_profile_attr(profile, "metrics", {}) or {}),
    )


def _aggregate_calibration_decision(
    profiles: Sequence[StrategyTestCalibrationProfile],
) -> StrategyTestCalibrationDecision:
    decisions = {profile.decision for profile in profiles}
    if "negative" in decisions:
        return "negative"
    if "insufficient_sample" in decisions:
        return "insufficient_sample"
    return "positive"


def _profile_decision(profile: Any) -> StrategyTestCalibrationDecision:
    if bool(_profile_attr(profile, "eligible", False)):
        return "positive"
    reason_code = str(_profile_attr(profile, "reason_code", ""))
    sample_size = _sample_size(_profile_attr(profile, "sample_size", 0))
    if reason_code == "strategy_eligibility_insufficient_sample" or sample_size < settings.execution_edge_min_sample_size:
        return "insufficient_sample"
    return "negative"


def _calibration_reason(profiles: Sequence[StrategyTestCalibrationProfile]) -> str:
    if not profiles:
        return "No profiles were published."
    negative = sum(1 for profile in profiles if profile.decision == "negative")
    insufficient = sum(1 for profile in profiles if profile.decision == "insufficient_sample")
    if negative:
        return f"{negative} profile{'s' if negative != 1 else ''} failed edge thresholds."
    if insufficient:
        return f"{insufficient} profile{'s' if insufficient != 1 else ''} needs more samples."
    count = len(profiles)
    return f"{count} profile{'s' if count != 1 else ''} published for execution calibration."


def _profile_attr(profile: Any, name: str, default: Any) -> Any:
    if isinstance(profile, dict):
        return profile.get(name, default)
    return getattr(profile, name, default)


def _sample_size(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _metric_value(value: object) -> float | int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (float, int)):
        return value
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str:
    return str(value or "").strip()


STRATEGY_TEST_ACTIVE_STATUSES: tuple[StrategyTestRunStatus, ...] = ("queued", "running", "stopping")
STRATEGY_TEST_DUPLICATE_WARNING_RATIO = 1.2
STRATEGY_TEST_MEDIUM_ESTIMATE_BARS = 50_000
STRATEGY_TEST_LARGE_ESTIMATE_BARS = 250_000
STRATEGY_TEST_MEDIUM_ESTIMATE_SCENARIOS = 8
STRATEGY_TEST_LARGE_ESTIMATE_SCENARIOS = 24


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
    heartbeat_at = _stale_reference_time(run)
    if heartbeat_at is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - heartbeat_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds > _strategy_test_stale_threshold_seconds()


def _stale_reference_time(run: StrategyTestRunResponse) -> datetime | None:
    if run.status == "stopping" and not _has_worker_runtime_phase(run):
        return run.started_at or run.created_at
    return run.last_heartbeat_at or run.started_at or run.created_at


def _has_worker_runtime_phase(run: StrategyTestRunResponse) -> bool:
    phase = run.runtime_state.get("phase")
    return isinstance(phase, str) and bool(phase.strip())
