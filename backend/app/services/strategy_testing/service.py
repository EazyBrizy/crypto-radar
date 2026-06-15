from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.core.config import settings
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
    StrategyTestFunnelResponse,
    StrategyTestMetricRow,
    StrategyTestReport,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
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
        created = self._run_store.create_run(request)
        if request.test_type == "historical_backtest":
            return self._run_store.update_runtime_state(
                created.run.run_id,
                _initial_historical_runtime_state(request, phase="queued"),
                heartbeat=False,
            ).run
        return created.run

    def execute_run(self, run_id: UUID, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        if request.test_type == "forward_virtual":
            return self._forward_runtime.start_run(run_id, request).run
        last_summary = _empty_partial_summary(_scenario_total(request))
        existing = self._run_store.get_run(run_id)
        if existing is not None and existing.run.status in {"cancelled", "stopping"}:
            last_summary = _summary_from_run(existing.run) or last_summary
            self._run_store.update_runtime_state(
                run_id,
                _terminal_runtime_state(
                    request=request,
                    phase="cancelled",
                    partial_summary=last_summary,
                ),
            )
            return self._run_store.mark_cancelled(run_id).run
        self._run_store.mark_running(run_id)
        self._run_store.update_runtime_state(
            run_id,
            _initial_historical_runtime_state(request, phase="running"),
        )
        try:
            user_uuid = strategy_test_user_uuid(request.user_id)

            def is_cancelled() -> bool:
                detail = self._run_store.get_run(run_id)
                return bool(detail is not None and detail.run.status in {"cancelled", "stopping"})

            def on_started(context: StrategyTestScenarioContext) -> None:
                self._run_store.update_runtime_state(
                    run_id,
                    _scenario_runtime_state(
                        context=context,
                        request=request,
                        phase="loading_candles",
                        partial_summary=None,
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
                    ),
                )

            def on_completed(
                context: StrategyTestScenarioContext,
                _result: Any,
                partial_summary: dict[str, Any],
            ) -> None:
                self._run_store.update_runtime_state(
                    run_id,
                    _scenario_runtime_state(
                        context=context,
                        request=request,
                        phase="running_scenario",
                        partial_summary=partial_summary,
                    ),
                )

            def on_failed(
                context: StrategyTestScenarioContext,
                exc: Exception,
                partial_summary: dict[str, Any],
            ) -> None:
                self._run_store.update_runtime_state(
                    run_id,
                    _scenario_runtime_state(
                        context=context,
                        request=request,
                        phase="running_scenario",
                        partial_summary=partial_summary,
                        last_error=str(exc),
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
            _write_trades(self._trade_store, matrix_result.trades)
            _write_signal_events(self._trade_store, matrix_result.signal_events)
            _write_metrics(
                self._trade_store,
                metric_results_to_rows(
                    run_id=run_id,
                    user_id=user_uuid,
                    mode=request.mode,
                    results=metric_results,
                )
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

    def publish_calibration(self, run_id: UUID) -> StrategyTestCalibrationResponse:
        detail = self._run_store.get_run(run_id)
        if detail is None:
            raise LookupError(f"Strategy test run is not found: {run_id}")
        run = detail.run
        if run.status != "completed":
            raise ValueError("Strategy test run must be completed before calibration can be published.")

        request = _request_from_completed_run(run)
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

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        if self._run_store.get_run(run_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        return self._trade_store.list_trades(run_id, limit=limit, offset=offset)

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        if self._run_store.get_run(run_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        list_events = getattr(self._trade_store, "list_signal_events", None)
        if not callable(list_events):
            return []
        return list_events(run_id, limit=limit, offset=offset)

    def get_funnel(self, run_id: UUID) -> StrategyTestFunnelResponse:
        if self._run_store.get_run(run_id) is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        return build_signal_funnel_response(
            run_id,
            self.list_signal_events(run_id, limit=10000, offset=0),
        )

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


_HISTORICAL_RUNTIME_PHASES = {
    "queued",
    "running",
    "loading_candles",
    "running_scenario",
    "writing_results",
    "completed",
    "failed",
    "cancelled",
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
        }
    )
    if progress:
        state["bars_processed"] = _int_value(progress.get("bars_processed"))
        state["bars_total"] = _int_value(progress.get("bars_total"))
        state["pending_entries_count"] = _int_value(progress.get("pending_entries_count"))
        for key in ("bars_pct", "elapsed_ms", "bars_per_second", "eta_seconds"):
            state[key] = _float_value(progress.get(key), default=None)
    return state


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
        }
    )
    return state


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
    return {
        "phase": normalized_phase,
        "scenario_total": scenario_total,
        "scenario_completed": _summary_int(partial_summary, "completed_scenarios", 0),
        "scenario_failed": _summary_int(partial_summary, "failed_scenarios", 0),
        "current_strategy": None,
        "current_exchange": None,
        "current_symbol": None,
        "current_timeframe": None,
        "signals_seen": _summary_int(partial_summary, "signals_seen", 0),
        "execution_candidates": _summary_int(partial_summary, "execution_candidates", 0),
        "pending_armed": _summary_int(partial_summary, "pending_armed", 0),
        "touched": _summary_int(partial_summary, "touched", 0),
        "entry_touched": _summary_int(partial_summary, "entry_touched", 0),
        "filled": _summary_int(partial_summary, "filled", 0),
        "closed": _summary_int(partial_summary, "closed", 0),
        "no_entry": _summary_int(partial_summary, "no_entry", 0),
        "not_selected": _summary_int(partial_summary, "not_selected", 0),
        "trades_count": _summary_int(partial_summary, "trades_count", 0),
        "risk_rejections": _summary_int(partial_summary, "risk_rejections", 0),
        "execution_rejections": _summary_int(partial_summary, "execution_rejections", 0),
        "last_progress_at": _now_iso(),
        "last_error": last_error,
        "partial_summary": dict(partial_summary),
    }


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


def _float_value(value: object, *, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_signal_events(
    trade_store: StrategyTestTradeStore,
    signal_events: Sequence[StrategyTestSignalEvent],
) -> None:
    if not signal_events:
        return
    _ensure_trade_store_schema(trade_store)
    write_events = getattr(trade_store, "write_signal_events", None)
    if not callable(write_events):
        raise RuntimeError("strategy_test_signal_event_store_not_available")
    write_events(signal_events)


def _write_trades(
    trade_store: StrategyTestTradeStore,
    trades: Sequence[StrategyTestTrade],
) -> None:
    _ensure_trade_store_schema(trade_store)
    trade_store.write_trades(trades)


def _write_metrics(
    trade_store: StrategyTestTradeStore,
    rows: Sequence[StrategyTestMetricRow],
) -> None:
    _ensure_trade_store_schema(trade_store)
    trade_store.write_metrics(rows)


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


def _request_from_completed_run(run: StrategyTestRunResponse) -> StrategyTestRunRequest:
    return StrategyTestRunRequest(**dict(run.requested_matrix))


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
    heartbeat_at = _stale_reference_time(run)
    if heartbeat_at is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - heartbeat_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds > STRATEGY_TEST_STALE_THRESHOLD_SECONDS


def _stale_reference_time(run: StrategyTestRunResponse) -> datetime | None:
    if run.status == "stopping" and not _has_worker_runtime_phase(run):
        return run.started_at or run.created_at
    return run.last_heartbeat_at or run.started_at or run.created_at


def _has_worker_runtime_phase(run: StrategyTestRunResponse) -> bool:
    phase = run.runtime_state.get("phase")
    return isinstance(phase, str) and bool(phase.strip())
