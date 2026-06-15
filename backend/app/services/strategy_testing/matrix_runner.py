from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import UUID

from app.services.strategy_testing.metrics import MetricResult
from app.services.strategy_testing.report_builder import (
    build_matrix_metric_results,
    metric_results_to_summary_sections,
)
from app.services.strategy_testing.runner import (
    StrategyTestRunCancelled,
    StrategyTestScenarioProgressCallback,
    StrategyTestScenarioResult,
    StrategyTestScenarioRunner,
)
from app.services.strategy_testing.schemas import (
    StrategyTestPair,
    StrategyTestRunRequest,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)


class ScenarioRunner(Protocol):
    def count_scenario_bars(
        self,
        *,
        request: StrategyTestRunRequest,
        pair: StrategyTestPair,
        timeframe: str,
    ) -> int:
        ...

    def run_scenario(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        request: StrategyTestRunRequest,
        strategy: str,
        pair: StrategyTestPair,
        timeframe: str,
        is_cancelled: Callable[[], bool] | None = None,
        on_progress: StrategyTestScenarioProgressCallback | None = None,
        candle_cache: dict[str, Any] | None = None,
        feature_cache: dict[str, Any] | None = None,
    ) -> StrategyTestScenarioResult:
        ...


class ScenarioResultSink(Protocol):
    def write_result(
        self,
        context: "StrategyTestScenarioContext",
        result: StrategyTestScenarioResult,
        partial_summary: dict[str, Any],
    ) -> None:
        ...


@dataclass(frozen=True)
class StrategyTestScenarioContext:
    index: int
    total: int
    strategy: str
    pair: StrategyTestPair
    timeframe: str

    @property
    def exchange(self) -> str:
        return self.pair.exchange

    @property
    def symbol(self) -> str:
        return self.pair.symbol


@dataclass(frozen=True)
class StrategyTestMatrixResult:
    run_id: UUID
    scenario_count: int
    completed_scenarios: int
    failed_scenarios: int
    scenario_summaries: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    trades: list[StrategyTestTrade] = field(default_factory=list)
    signal_events: list[StrategyTestSignalEvent] = field(default_factory=list)
    metrics: list[MetricResult] = field(default_factory=list)
    cancelled: bool = False

    @property
    def all_failed(self) -> bool:
        return self.scenario_count > 0 and self.completed_scenarios == 0

    def summary(self, metrics: Sequence[MetricResult] | None = None) -> dict[str, Any]:
        summary_signals_seen = sum(_int_from_summary(item, "signals_seen") for item in self.scenario_summaries)
        summary_signals_count = sum(_int_from_summary(item, "signals_count") for item in self.scenario_summaries)
        signals_count = len(self.signal_events) or summary_signals_count or summary_signals_seen
        signals_seen = summary_signals_seen or signals_count
        summary_trades_count = sum(_int_from_summary(item, "trades_count") for item in self.scenario_summaries)
        trades_count = len(self.trades) or summary_trades_count
        execution_candidates = (
            sum(1 for event in self.signal_events if event.execution_candidate)
            if self.signal_events
            else sum(_int_from_summary(item, "execution_candidates") for item in self.scenario_summaries)
        )
        pending_armed = (
            sum(1 for event in self.signal_events if _event_has_stage(event, "pending_armed"))
            if self.signal_events
            else sum(_int_from_summary(item, "pending_armed") for item in self.scenario_summaries)
        )
        entry_touched = (
            sum(1 for event in self.signal_events if event.entry_touched)
            if self.signal_events
            else sum(_summary_touched(item) for item in self.scenario_summaries)
        )
        filled = (
            sum(1 for event in self.signal_events if event.filled)
            if self.signal_events
            else sum(_int_from_summary(item, "filled") for item in self.scenario_summaries)
        )
        closed = (
            sum(1 for event in self.signal_events if event.closed)
            if self.signal_events
            else sum(_int_from_summary(item, "closed") for item in self.scenario_summaries)
        )
        wins = (
            sum(1 for event in self.signal_events if _normalized_outcome(event.outcome) == "win")
            if self.signal_events
            else sum(_int_from_summary(item, "wins") for item in self.scenario_summaries)
        )
        losses = (
            sum(1 for event in self.signal_events if _normalized_outcome(event.outcome) == "loss")
            if self.signal_events
            else sum(_int_from_summary(item, "losses") for item in self.scenario_summaries)
        )
        no_entry = (
            sum(1 for event in self.signal_events if event.no_entry)
            if self.signal_events
            else sum(_int_from_summary(item, "no_entry") for item in self.scenario_summaries)
        )
        not_selected = (
            sum(1 for event in self.signal_events if event.blocked_reason_code == "not_selected")
            if self.signal_events
            else sum(_int_from_summary(item, "not_selected") for item in self.scenario_summaries)
        )
        risk_rejections = (
            sum(1 for event in self.signal_events if event.risk_rejected)
            if self.signal_events
            else sum(_int_from_summary(item, "risk_rejections") for item in self.scenario_summaries)
        )
        execution_rejections = (
            sum(1 for event in self.signal_events if event.execution_rejected)
            if self.signal_events
            else sum(_int_from_summary(item, "execution_rejections") for item in self.scenario_summaries)
        )
        metric_sections = metric_results_to_summary_sections(self.metrics if metrics is None else metrics)
        return {
            "scenario_count": self.scenario_count,
            "completed_scenarios": self.completed_scenarios,
            "failed_scenarios": self.failed_scenarios,
            "trades_count": trades_count,
            "signals_seen": signals_seen,
            "signals_count": signals_count,
            "execution_candidates": execution_candidates,
            "pending_armed": pending_armed,
            "touched": entry_touched,
            "entry_touched": entry_touched,
            "filled": filled,
            "closed": closed,
            "wins": wins,
            "losses": losses,
            "no_entry": no_entry,
            "not_selected": not_selected,
            "risk_rejections": risk_rejections,
            "execution_rejections": execution_rejections,
            "errors": list(self.errors),
            "scenarios": list(self.scenario_summaries),
            "slowest_scenarios": _slowest_scenarios(self.scenario_summaries),
            **metric_sections,
        }


class StrategyTestMatrixRunner:
    def __init__(self, scenario_runner: ScenarioRunner | None = None) -> None:
        self._scenario_runner = scenario_runner or StrategyTestScenarioRunner()

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        on_scenario_started: Callable[[StrategyTestScenarioContext], None] | None = None,
        on_scenario_completed: Callable[
            [StrategyTestScenarioContext, StrategyTestScenarioResult, dict[str, Any]],
            None,
        ]
        | None = None,
        on_scenario_failed: Callable[
            [StrategyTestScenarioContext, Exception, dict[str, Any]],
            None,
        ]
        | None = None,
        on_scenario_progress: Callable[
            [StrategyTestScenarioContext, dict[str, Any], dict[str, Any]],
            None,
        ]
        | None = None,
        scenario_result_sink: ScenarioResultSink | None = None,
        completed_scenario_summaries: Mapping[str, dict[str, Any]] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> StrategyTestMatrixResult:
        scenario_count = len(request.strategies) * len(request.pairs) * len(request.timeframes)
        completed = 0
        failed = 0
        scenario_summaries: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        trades: list[StrategyTestTrade] = []
        signal_events: list[StrategyTestSignalEvent] = []
        metrics: list[MetricResult] = []
        completed_summary_by_key = dict(completed_scenario_summaries or {})
        scenario_index = 0
        candle_cache: dict[str, Any] = {}
        feature_cache: dict[str, Any] = {}
        bars_by_pair_timeframe, matrix_bars_total, matrix_bars_warning = self._estimate_matrix_bars(request)
        bars_completed_before = 0

        for strategy in request.strategies:
            for pair in request.pairs:
                for timeframe in request.timeframes:
                    scenario_index += 1
                    scenario_bars_total = bars_by_pair_timeframe.get(_bar_count_key(pair, timeframe))
                    context = StrategyTestScenarioContext(
                        index=scenario_index,
                        total=scenario_count,
                        strategy=strategy,
                        pair=pair,
                        timeframe=timeframe,
                    )
                    if is_cancelled is not None and is_cancelled():
                        return _matrix_result(
                            run_id=run_id,
                            scenario_count=scenario_count,
                            completed=completed,
                            failed=failed,
                            scenario_summaries=scenario_summaries,
                            errors=errors,
                            trades=trades,
                            signal_events=signal_events,
                            metrics=metrics,
                            cancelled=True,
                            metric_set=request.metric_set,
                        )
                    scenario_key = _scenario_key(context)
                    if scenario_key in completed_summary_by_key:
                        summary = _checkpoint_summary_for_context(
                            completed_summary_by_key[scenario_key],
                            context=context,
                        )
                        completed += 1
                        scenario_summaries.append(summary)
                        bars_completed_before += _scenario_bars_completed(
                            summary,
                            scenario_bars_total=scenario_bars_total,
                        )
                        continue
                    if on_scenario_started is not None:
                        on_scenario_started(context)

                    def handle_progress(progress: dict[str, Any]) -> None:
                        if on_scenario_progress is None:
                            return
                        progress = _matrix_progress(
                            progress,
                            bars_completed_before=bars_completed_before,
                            scenario_bars_total=scenario_bars_total,
                            matrix_bars_total=matrix_bars_total,
                            matrix_bars_warning=matrix_bars_warning,
                        )
                        partial_summary = _progress_partial_summary(
                            scenario_count=scenario_count,
                            completed=completed,
                            failed=failed,
                            scenario_summaries=scenario_summaries,
                            errors=errors,
                        )
                        on_scenario_progress(context, progress, partial_summary)

                    try:
                        result = self._scenario_runner.run_scenario(
                            run_id=run_id,
                            user_id=user_uuid,
                            request=request,
                            strategy=strategy,
                            pair=pair,
                            timeframe=timeframe,
                            is_cancelled=is_cancelled,
                            on_progress=handle_progress,
                            candle_cache=candle_cache,
                            feature_cache=feature_cache,
                        )
                    except StrategyTestRunCancelled:
                        return _matrix_result(
                            run_id=run_id,
                            scenario_count=scenario_count,
                            completed=completed,
                            failed=failed,
                            scenario_summaries=scenario_summaries,
                            errors=errors,
                            trades=trades,
                            signal_events=signal_events,
                            metrics=metrics,
                            cancelled=True,
                            metric_set=request.metric_set,
                        )
                    except Exception as exc:
                        failed += 1
                        errors.append(
                            {
                                "strategy": strategy,
                                "exchange": pair.exchange,
                                "symbol": pair.symbol,
                                "timeframe": timeframe,
                                "error": str(exc),
                            }
                        )
                        partial_summary = _partial_summary(
                            run_id=run_id,
                            scenario_count=scenario_count,
                            completed=completed,
                            failed=failed,
                            scenario_summaries=scenario_summaries,
                            errors=errors,
                            trades=trades,
                            signal_events=signal_events,
                            metrics=metrics,
                            metric_set=request.metric_set,
                        )
                        if on_scenario_failed is not None:
                            on_scenario_failed(context, exc, partial_summary)
                        continue

                    completed += 1
                    scenario_summary = _scenario_result_summary(result, context=context)
                    scenario_summaries.append(scenario_summary)
                    metrics.extend(
                        build_matrix_metric_results(
                            result.trades,
                            signal_events=result.signal_events,
                            metric_set=request.metric_set,
                        )
                    )
                    bars_completed_before += _scenario_bars_completed(
                        scenario_summary,
                        scenario_bars_total=scenario_bars_total,
                    )
                    partial_summary = _partial_summary(
                        run_id=run_id,
                        scenario_count=scenario_count,
                        completed=completed,
                        failed=failed,
                        scenario_summaries=scenario_summaries,
                        errors=errors,
                        trades=trades,
                        signal_events=signal_events,
                        metrics=metrics,
                        metric_set=request.metric_set,
                    )
                    if scenario_result_sink is not None:
                        scenario_result_sink.write_result(context, result, partial_summary)
                    if on_scenario_completed is not None:
                        on_scenario_completed(context, result, partial_summary)

        return _matrix_result(
            run_id=run_id,
            scenario_count=scenario_count,
            completed=completed,
            failed=failed,
            scenario_summaries=scenario_summaries,
            errors=errors,
            trades=trades,
            signal_events=signal_events,
            metrics=metrics,
            metric_set=request.metric_set,
        )

    def _estimate_matrix_bars(
        self,
        request: StrategyTestRunRequest,
    ) -> tuple[dict[tuple[str, str, str], int], int | None, dict[str, Any] | None]:
        count_bars = getattr(self._scenario_runner, "count_scenario_bars", None)
        if not callable(count_bars):
            return {}, None, {
                "code": "estimating_failed",
                "message": "Scenario runner cannot count historical bars before execution.",
            }

        bars_by_pair_timeframe: dict[tuple[str, str, str], int] = {}
        for pair in request.pairs:
            for timeframe in request.timeframes:
                key = _bar_count_key(pair, timeframe)
                if key in bars_by_pair_timeframe:
                    continue
                try:
                    bars_by_pair_timeframe[key] = max(
                        0,
                        int(
                            count_bars(
                                request=request,
                                pair=pair,
                                timeframe=timeframe,
                            )
                        ),
                    )
                except Exception as exc:
                    return {}, None, {
                        "code": "estimating_failed",
                        "message": (
                            "Unable to count deduped historical bars before execution for "
                            f"{pair.exchange}:{pair.symbol}:{timeframe}: {exc}"
                        ),
                        "exchange": pair.exchange,
                        "symbol": pair.symbol,
                        "timeframe": timeframe,
                    }

        total_bars = 0
        for _strategy in request.strategies:
            for pair in request.pairs:
                for timeframe in request.timeframes:
                    total_bars += bars_by_pair_timeframe.get(_bar_count_key(pair, timeframe), 0)
        return bars_by_pair_timeframe, total_bars, None


def _partial_summary(
    *,
    run_id: UUID,
    scenario_count: int,
    completed: int,
    failed: int,
    scenario_summaries: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    trades: list[StrategyTestTrade],
    signal_events: list[StrategyTestSignalEvent],
    metrics: list[MetricResult],
    metric_set: Sequence[str],
) -> dict[str, Any]:
    return _matrix_result(
        run_id=run_id,
        scenario_count=scenario_count,
        completed=completed,
        failed=failed,
        scenario_summaries=scenario_summaries,
        errors=errors,
        trades=trades,
        signal_events=signal_events,
        metrics=metrics,
        metric_set=metric_set,
    ).summary()


def _progress_partial_summary(
    *,
    scenario_count: int,
    completed: int,
    failed: int,
    scenario_summaries: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    summary_signals_seen = sum(_int_from_summary(item, "signals_seen") for item in scenario_summaries)
    summary_signals_count = sum(_int_from_summary(item, "signals_count") for item in scenario_summaries)
    entry_touched = sum(_summary_touched(item) for item in scenario_summaries)
    return {
        "scenario_count": scenario_count,
        "completed_scenarios": completed,
        "failed_scenarios": failed,
        "trades_count": sum(_int_from_summary(item, "trades_count") for item in scenario_summaries),
        "signals_seen": summary_signals_seen or summary_signals_count,
        "signals_count": summary_signals_count or summary_signals_seen,
        "execution_candidates": sum(_int_from_summary(item, "execution_candidates") for item in scenario_summaries),
        "pending_armed": sum(_int_from_summary(item, "pending_armed") for item in scenario_summaries),
        "touched": entry_touched,
        "entry_touched": entry_touched,
        "filled": sum(_int_from_summary(item, "filled") for item in scenario_summaries),
        "closed": sum(_int_from_summary(item, "closed") for item in scenario_summaries),
        "wins": sum(_int_from_summary(item, "wins") for item in scenario_summaries),
        "losses": sum(_int_from_summary(item, "losses") for item in scenario_summaries),
        "no_entry": sum(_int_from_summary(item, "no_entry") for item in scenario_summaries),
        "not_selected": sum(_int_from_summary(item, "not_selected") for item in scenario_summaries),
        "risk_rejections": sum(_int_from_summary(item, "risk_rejections") for item in scenario_summaries),
        "execution_rejections": sum(_int_from_summary(item, "execution_rejections") for item in scenario_summaries),
        "errors": list(errors),
        "scenarios": list(scenario_summaries),
    }


def _bar_count_key(pair: StrategyTestPair, timeframe: str) -> tuple[str, str, str]:
    return (pair.exchange, pair.symbol, timeframe)


def _scenario_key(context: StrategyTestScenarioContext) -> str:
    return "::".join(_key_text(value) for value in (context.strategy, context.exchange, context.symbol, context.timeframe))


def _checkpoint_summary_for_context(
    summary: Mapping[str, Any],
    *,
    context: StrategyTestScenarioContext,
) -> dict[str, Any]:
    updated = _scenario_identity_summary(context)
    updated.update(dict(summary))
    updated.setdefault("scenario_key", _scenario_key(context))
    return updated


def _scenario_result_summary(
    result: StrategyTestScenarioResult,
    *,
    context: StrategyTestScenarioContext,
) -> dict[str, Any]:
    summary = _checkpoint_summary_for_context(result.summary, context=context)
    signal_events = result.signal_events
    if signal_events:
        summary["signals_seen"] = len(signal_events)
        summary["signals_count"] = len(signal_events)
        summary["execution_candidates"] = sum(1 for event in signal_events if event.execution_candidate)
        summary["pending_armed"] = sum(1 for event in signal_events if _event_has_stage(event, "pending_armed"))
        summary["entry_touched"] = sum(1 for event in signal_events if event.entry_touched)
        summary["touched"] = summary["entry_touched"]
        summary["filled"] = sum(1 for event in signal_events if event.filled)
        summary["closed"] = sum(1 for event in signal_events if event.closed)
        summary["wins"] = sum(1 for event in signal_events if _normalized_outcome(event.outcome) == "win")
        summary["losses"] = sum(1 for event in signal_events if _normalized_outcome(event.outcome) == "loss")
        summary["no_entry"] = sum(1 for event in signal_events if event.no_entry)
        summary["not_selected"] = sum(1 for event in signal_events if event.blocked_reason_code == "not_selected")
        summary["risk_rejections"] = sum(1 for event in signal_events if event.risk_rejected)
        summary["execution_rejections"] = sum(1 for event in signal_events if event.execution_rejected)
    if result.trades:
        summary["trades_count"] = len(result.trades)
    else:
        summary.setdefault("trades_count", 0)
    return summary


def _scenario_identity_summary(context: StrategyTestScenarioContext) -> dict[str, Any]:
    return {
        "strategy": context.strategy,
        "exchange": context.exchange,
        "symbol": context.symbol,
        "timeframe": context.timeframe,
    }


def _matrix_progress(
    progress: dict[str, Any],
    *,
    bars_completed_before: int,
    scenario_bars_total: int | None,
    matrix_bars_total: int | None,
    matrix_bars_warning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = dict(progress)
    scenario_bars_processed = _int_from_summary(updated, "bars_processed")
    existing_scenario_total = _int_from_summary(updated, "bars_total")
    scenario_total = scenario_bars_total if scenario_bars_total is not None else existing_scenario_total
    matrix_bars_processed = bars_completed_before + scenario_bars_processed
    updated["scenario_bars_processed"] = scenario_bars_processed
    updated["scenario_bars_total"] = scenario_total
    updated["current_scenario_bars_processed"] = scenario_bars_processed
    updated["current_scenario_bars_total"] = scenario_total
    updated["matrix_bars_processed"] = matrix_bars_processed
    updated["matrix_bars_total"] = matrix_bars_total
    if matrix_bars_warning is not None:
        updated["matrix_bars_estimate_status"] = "estimating_failed"
        updated["warnings"] = [*list(updated.get("warnings") or []), dict(matrix_bars_warning)]
    if matrix_bars_total is not None:
        updated["matrix_bars_processed"] = min(matrix_bars_total, matrix_bars_processed)
        updated["bars_processed"] = updated["matrix_bars_processed"]
        updated["bars_total"] = matrix_bars_total
        updated["bars_pct"] = (
            round((updated["bars_processed"] / matrix_bars_total) * 100, 2)
            if matrix_bars_total > 0
            else 0.0
        )
    else:
        updated["bars_processed"] = matrix_bars_processed
        updated["bars_total"] = None
        updated["bars_pct"] = None
    return updated


def _scenario_bars_completed(
    summary: dict[str, Any],
    *,
    scenario_bars_total: int | None,
) -> int:
    if scenario_bars_total is not None:
        return scenario_bars_total
    timings = summary.get("timings")
    if isinstance(timings, dict):
        return _int_from_summary(timings, "bars_total")
    return _int_from_summary(summary, "bars_total")


def _matrix_result(
    *,
    run_id: UUID,
    scenario_count: int,
    completed: int,
    failed: int,
    scenario_summaries: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    trades: list[StrategyTestTrade],
    signal_events: list[StrategyTestSignalEvent],
    metric_set: Sequence[str],
    metrics: list[MetricResult] | None = None,
    cancelled: bool = False,
) -> StrategyTestMatrixResult:
    return StrategyTestMatrixResult(
        run_id=run_id,
        scenario_count=scenario_count,
        completed_scenarios=completed,
        failed_scenarios=failed,
        scenario_summaries=list(scenario_summaries),
        errors=list(errors),
        trades=list(trades),
        signal_events=list(signal_events),
        metrics=list(metrics)
        if metrics is not None
        else build_matrix_metric_results(
            trades,
            signal_events=signal_events,
            metric_set=metric_set,
        ),
        cancelled=cancelled,
    )


def _int_from_summary(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _summary_touched(summary: dict[str, Any]) -> int:
    touched = _int_from_summary(summary, "touched")
    if touched:
        return touched
    return _int_from_summary(summary, "entry_touched")


def _event_has_stage(event: StrategyTestSignalEvent, stage: str) -> bool:
    stages = event.metadata.get("funnel_stages") if isinstance(event.metadata, dict) else None
    if isinstance(stages, list):
        return stage in {str(item) for item in stages}
    return event.funnel_stage == stage


def _slowest_scenarios(scenario_summaries: Sequence[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in scenario_summaries:
        timings = summary.get("timings")
        if not isinstance(timings, dict):
            timings = {}
        total_ms = _float_from_summary(timings, "total_ms")
        bars_per_second = _float_from_summary(timings, "bars_per_second")
        if total_ms <= 0 and bars_per_second <= 0:
            continue
        rows.append(
            {
                "strategy": summary.get("strategy"),
                "exchange": summary.get("exchange"),
                "symbol": summary.get("symbol"),
                "timeframe": summary.get("timeframe"),
                "total_ms": total_ms,
                "bars_total": _int_from_summary(timings, "bars_total"),
                "bars_per_second": bars_per_second,
                "timings": dict(timings),
            }
        )
    return sorted(rows, key=lambda item: item["total_ms"], reverse=True)[:limit]


def _float_from_summary(summary: dict[str, Any], key: str) -> float:
    try:
        return float(summary.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _key_text(value: object) -> str:
    return str(value or "unknown").strip() or "unknown"


def _normalized_outcome(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
