from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, Sequence, cast
from uuid import UUID

from app.services.strategy_testing.metrics import MetricRegistry, MetricResult, build_base_metric_registry
from app.services.strategy_testing.schemas import (
    StrategyTestCandidateAdjustment,
    StrategyTestFunnelResponse,
    StrategyTestMetricRow,
    StrategyTestMode,
    StrategyTestReport,
    StrategyTestReportSection,
    StrategyTestRunDetailResponse,
    StrategyTestRunStatus,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)


MATRIX_METRIC_GROUPINGS: tuple[tuple[str, ...], ...] = (
    (),
    ("strategy",),
    ("strategy", "symbol", "timeframe"),
    ("strategy", "regime"),
    ("strategy", "score_bucket"),
    ("strategy", "direction"),
    ("strategy", "exchange", "symbol", "timeframe", "regime", "score_bucket", "direction"),
)

REPORT_EXTRA_GROUPINGS: tuple[tuple[str, ...], ...] = (
    ("strategy", "timeframe"),
    ("strategy", "score_bucket", "timeframe"),
    ("strategy", "regime", "direction"),
)

SECTION_NAMES: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("signal_funnel", "Signal funnel"),
    ("strategy_comparison", "Strategy comparison"),
    ("pair_timeframe_breakdown", "Pair/timeframe breakdown"),
    ("regime_breakdown", "Regime breakdown"),
    ("score_bucket_breakdown", "Score bucket breakdown"),
    ("entry_quality", "Entry quality"),
    ("exit_quality", "Exit quality"),
    ("mfe_mae_distribution", "MFE/MAE distribution"),
    ("rejection_analysis", "Rejection analysis"),
    ("trade_list", "Trade list"),
    ("recommended_strategy_adjustments", "Recommended strategy adjustments"),
)

SUMMARY_METRIC_CODES = (
    "signals_count",
    "trades_count",
    "entry_touch_rate",
    "no_entry_rate",
    "winrate",
    "expectancy_r",
    "expectancy_after_costs_r",
    "profit_factor",
    "max_drawdown_r",
    "max_drawdown_pct",
    "fees_total",
    "slippage_total",
)

SIGNAL_FUNNEL_CODES = (
    "signals_count",
    "entry_touch_rate",
    "no_entry_rate",
    "risk_rejection_rate",
    "execution_rejection_rate",
    "false_signal_rate",
)

STRATEGY_COMPARISON_CODES = (
    "trades_count",
    "winrate",
    "expectancy_r",
    "expectancy_after_costs_r",
    "profit_factor",
    "max_drawdown_r",
    "fees_total",
    "slippage_total",
)

ENTRY_QUALITY_CODES = (
    "entry_touch_rate",
    "median_bars_to_entry",
    "false_signal_rate",
    "avg_mfe_r",
)

EXIT_QUALITY_CODES = (
    "tp1_rate",
    "tp2_rate",
    "stop_rate",
    "time_stop_rate",
    "avg_mfe_r",
    "avg_mae_r",
)

REJECTION_CODES = (
    "risk_rejection_rate",
    "execution_rejection_rate",
)


class ReportRunStore(Protocol):
    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        ...

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        ...


class ReportAnalyticsStore(Protocol):
    def list_trades(self, run_id: UUID) -> list[StrategyTestTrade]:
        ...

    def list_signal_events(self, run_id: UUID, limit: int = 1000, offset: int = 0) -> list[StrategyTestSignalEvent]:
        ...


class StrategyTestReportBuilder:
    def __init__(
        self,
        run_store: ReportRunStore,
        analytics_store: ReportAnalyticsStore,
        metric_registry: MetricRegistry | None = None,
    ) -> None:
        self._run_store = run_store
        self._analytics_store = analytics_store
        self._metric_registry = metric_registry or build_base_metric_registry()

    def build_report(self, run_id: UUID) -> StrategyTestReport:
        run_detail = self._run_store.get_run(run_id)
        if run_detail is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        return self._build_report(run_detail)

    def list_reports(self, user_id: str = "demo_user", limit: int = 50) -> list[StrategyTestReport]:
        return [
            self._build_report(run_detail)
            for run_detail in self._run_store.list_runs(user_id=user_id, limit=limit, status=None)
        ]

    def _build_report(self, run_detail: StrategyTestRunDetailResponse) -> StrategyTestReport:
        run = run_detail.run
        analytics_warnings: list[str] = []
        trades = _list_trades_or_empty(self._analytics_store, run.run_id, analytics_warnings)
        signal_events = _list_signal_events_or_empty(self._analytics_store, run.run_id, analytics_warnings)
        source_summary = _run_summary_source(run_detail)
        metric_results = build_report_metric_results(
            trades,
            signal_events=signal_events,
            registry=self._metric_registry,
        )
        if not trades and not signal_events and source_summary:
            metric_results = _merge_metric_results(
                _summary_metric_results(source_summary),
                metric_results,
            )
        metric_sections = metric_results_to_summary_sections(metric_results)
        summary_metrics = metric_sections["summary_metrics"]
        grouped_metrics = metric_sections["grouped_metrics"]
        candidate_adjustments = build_candidate_adjustments(
            trades=trades,
            metrics=metric_results,
            mode=_run_mode(run.requested_matrix),
        )
        warnings = _report_warnings(metric_results, trades)
        warnings = _dedupe_strings([*warnings, *analytics_warnings, *_summary_warning_codes(source_summary)])
        rejections = _report_rejections(trades)
        summary = _build_summary(
            run_detail,
            trades,
            metric_results,
            signal_events,
            source_summary=source_summary,
            analytics_warnings=analytics_warnings,
        )
        sections = _build_sections(
            trades=trades,
            signal_events=signal_events,
            metrics=metric_results,
            summary=summary,
            candidate_adjustments=candidate_adjustments,
            warnings=warnings,
            rejections=rejections,
        )

        return StrategyTestReport(
            run_id=run.run_id,
            status=run.status,
            mode=_run_mode(run.requested_matrix),
            requested_matrix=dict(run.requested_matrix),
            assumptions=_assumptions_from_run(run_detail),
            summary=summary,
            sections=sections,
            metrics=[metric_result_to_dict(result) for result in metric_results],
            candidate_adjustments=candidate_adjustments,
            generated_at=datetime.now(timezone.utc),
            summary_metrics=summary_metrics,
            grouped_metrics=grouped_metrics,
            trades_count=_summary_int(summary, "trades_count", len(trades)),
            warnings=warnings,
            rejections=rejections,
        )


def build_matrix_metric_results(
    trades: Sequence[StrategyTestTrade],
    *,
    signal_events: Sequence[StrategyTestSignalEvent] = (),
    metric_set: Sequence[str] | None = None,
    registry: MetricRegistry | None = None,
) -> list[MetricResult]:
    metric_registry = registry or build_base_metric_registry()
    results: list[MetricResult] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    for grouping in MATRIX_METRIC_GROUPINGS:
        computed = _compute_metric_results(
            metric_registry,
            trades,
            signal_events=signal_events,
            metric_set=metric_set,
            group_by=list(grouping) if grouping else None,
        )
        for result in computed:
            if grouping and result.group == {"all": "all"}:
                continue
            key = (result.code, tuple(sorted(result.group.items())))
            if key in seen:
                continue
            seen.add(key)
            results.append(result)
    return results


def build_report_metric_results(
    trades: Sequence[StrategyTestTrade],
    *,
    signal_events: Sequence[StrategyTestSignalEvent] = (),
    registry: MetricRegistry | None = None,
) -> list[MetricResult]:
    metric_registry = registry or build_base_metric_registry()
    results = build_matrix_metric_results(trades, signal_events=signal_events, registry=metric_registry)
    seen = {(result.code, tuple(sorted(result.group.items()))) for result in results}

    for grouping in REPORT_EXTRA_GROUPINGS:
        for result in _compute_metric_results(
            metric_registry,
            trades,
            signal_events=signal_events,
            group_by=list(grouping),
        ):
            if result.group == {"all": "all"}:
                continue
            key = (result.code, tuple(sorted(result.group.items())))
            if key in seen:
                continue
            seen.add(key)
            results.append(result)
    return results


def _compute_metric_results(
    metric_registry: MetricRegistry,
    trades: Sequence[StrategyTestTrade],
    *,
    signal_events: Sequence[StrategyTestSignalEvent],
    metric_set: Sequence[str] | None = None,
    group_by: Sequence[str] | None = None,
) -> list[MetricResult]:
    compute_with_signals = getattr(metric_registry, "compute_with_signals", None)
    if callable(compute_with_signals):
        return compute_with_signals(
            trades,
            signal_events=signal_events,
            metric_set=metric_set,
            group_by=group_by,
        )
    return metric_registry.compute(
        trades,
        metric_set=metric_set,
        group_by=group_by,
    )


def build_signal_funnel_response(
    run_id: UUID,
    signal_events: Sequence[StrategyTestSignalEvent],
) -> StrategyTestFunnelResponse:
    signals_count = len(signal_events)
    execution_candidates = sum(1 for event in signal_events if event.execution_candidate)
    entry_touched = sum(1 for event in signal_events if event.entry_touched)
    filled = sum(1 for event in signal_events if event.filled)
    closed = sum(1 for event in signal_events if event.closed)
    wins = sum(1 for event in signal_events if _normalized_outcome(event.outcome) == "win")
    losses = sum(1 for event in signal_events if _normalized_outcome(event.outcome) == "loss")
    no_entry = sum(1 for event in signal_events if event.no_entry)
    risk_rejected = sum(1 for event in signal_events if event.risk_rejected)
    execution_rejected = sum(1 for event in signal_events if event.execution_rejected)
    false_signals = sum(
        1
        for event in signal_events
        if event.no_entry or _normalized_outcome(event.outcome) in {"no_entry", "invalidated"}
    )
    stage_counts: Counter[str] = Counter()
    for event in signal_events:
        stages = event.metadata.get("funnel_stages") if isinstance(event.metadata, dict) else None
        if isinstance(stages, list) and stages:
            stage_counts.update(str(stage).strip() or "signal" for stage in stages)
        else:
            stage_counts[(event.funnel_stage or "signal").strip() or "signal"] += 1

    return StrategyTestFunnelResponse(
        run_id=run_id,
        signals_count=signals_count,
        execution_candidates=execution_candidates,
        entry_touched=entry_touched,
        filled=filled,
        closed=closed,
        wins=wins,
        losses=losses,
        no_entry=no_entry,
        risk_rejected=risk_rejected,
        execution_rejected=execution_rejected,
        entry_touch_rate=_safe_rate(entry_touched, signals_count),
        no_entry_rate=_safe_rate(no_entry, signals_count),
        risk_rejection_rate=_safe_rate(risk_rejected, signals_count),
        execution_rejection_rate=_safe_rate(execution_rejected, execution_candidates),
        false_signal_rate=_safe_rate(false_signals, signals_count),
        stages=[
            {
                "stage": stage,
                "count": count,
                "rate": _safe_rate(count, signals_count),
            }
            for stage, count in sorted(stage_counts.items())
        ],
    )


def _signal_funnel_from_summary(
    run_id: UUID,
    summary: dict[str, Any],
) -> StrategyTestFunnelResponse:
    nested = summary.get("signal_funnel")
    nested_summary = nested if isinstance(nested, dict) else {}
    signals_count = _summary_int(nested_summary, "signals_count", _summary_int(summary, "signals_count", _summary_int(summary, "signals_seen", 0)))
    execution_candidates = _summary_int(
        nested_summary,
        "execution_candidates",
        _summary_int(summary, "execution_candidates", 0),
    )
    entry_touched = _summary_int(
        nested_summary,
        "entry_touched",
        _summary_int(summary, "entry_touched", _summary_int(summary, "touched", 0)),
    )
    filled = _summary_int(nested_summary, "filled", _summary_int(summary, "filled", 0))
    closed = _summary_int(nested_summary, "closed", _summary_int(summary, "closed", 0))
    wins = _summary_int(nested_summary, "wins", _summary_int(summary, "wins", 0))
    losses = _summary_int(nested_summary, "losses", _summary_int(summary, "losses", 0))
    no_entry = _summary_int(nested_summary, "no_entry", _summary_int(summary, "no_entry", 0))
    risk_rejected = _summary_int(nested_summary, "risk_rejected", _summary_int(summary, "risk_rejections", 0))
    execution_rejected = _summary_int(
        nested_summary,
        "execution_rejected",
        _summary_int(summary, "execution_rejections", 0),
    )
    stages = _summary_stages(summary, nested_summary, signals_count=signals_count)
    return StrategyTestFunnelResponse(
        run_id=run_id,
        signals_count=signals_count,
        execution_candidates=execution_candidates,
        entry_touched=entry_touched,
        filled=filled,
        closed=closed,
        wins=wins,
        losses=losses,
        no_entry=no_entry,
        risk_rejected=risk_rejected,
        execution_rejected=execution_rejected,
        entry_touch_rate=_summary_float(nested_summary, "entry_touch_rate", _safe_rate(entry_touched, signals_count)),
        no_entry_rate=_summary_float(nested_summary, "no_entry_rate", _safe_rate(no_entry, signals_count)),
        risk_rejection_rate=_summary_float(nested_summary, "risk_rejection_rate", _safe_rate(risk_rejected, signals_count)),
        execution_rejection_rate=_summary_float(
            nested_summary,
            "execution_rejection_rate",
            _safe_rate(execution_rejected, execution_candidates),
        ),
        false_signal_rate=_summary_float(nested_summary, "false_signal_rate", _safe_rate(no_entry, signals_count)),
        stages=stages,
    )


def _list_trades_or_empty(
    analytics_store: ReportAnalyticsStore,
    run_id: UUID,
    warnings: list[str],
) -> list[StrategyTestTrade]:
    try:
        return analytics_store.list_trades(run_id)
    except Exception as exc:
        warnings.append(f"analytics_trades_unavailable:{exc}")
        return []


def _list_signal_events_or_empty(
    analytics_store: ReportAnalyticsStore,
    run_id: UUID,
    warnings: list[str],
) -> list[StrategyTestSignalEvent]:
    list_events = getattr(analytics_store, "list_signal_events", None)
    if not callable(list_events):
        return []
    try:
        return list_events(run_id, limit=10000, offset=0)
    except Exception as exc:
        warnings.append(f"analytics_signal_events_unavailable:{exc}")
        return []


def build_candidate_adjustments(
    *,
    trades: Sequence[StrategyTestTrade],
    metrics: Sequence[MetricResult],
    mode: object,
) -> list[StrategyTestCandidateAdjustment]:
    adjustments: list[StrategyTestCandidateAdjustment] = []
    adjustments.extend(_negative_score_bucket_adjustments(metrics))
    adjustments.extend(_raise_score_threshold_adjustments(metrics))
    adjustments.extend(_bullish_regime_short_adjustments(metrics))
    adjustments.extend(_mae_mfe_adjustments(metrics))
    adjustments.extend(_time_stop_adjustments(metrics))
    adjustments.extend(_execution_rejection_adjustments(metrics, mode=mode))
    return _dedupe_adjustments(adjustments)


def metric_results_to_rows(
    *,
    run_id: UUID,
    user_id: UUID,
    mode: StrategyTestMode,
    results: Sequence[MetricResult],
    created_at: datetime | None = None,
) -> list[StrategyTestMetricRow]:
    row_created_at = created_at or datetime.now(timezone.utc)
    return [
        StrategyTestMetricRow(
            run_id=run_id,
            user_id=user_id,
            mode=mode,
            strategy_code=_dimension(result.group, "strategy"),
            exchange=_dimension(result.group, "exchange"),
            symbol=_dimension(result.group, "symbol"),
            timeframe=_dimension(result.group, "timeframe"),
            market_regime=_dimension(result.group, "regime"),
            score_bucket=_dimension(result.group, "score_bucket"),
            direction=_dimension(result.group, "direction"),
            metric_code=result.code,
            metric_value=_metric_value_to_float(result.value),
            sample_size=result.sample_size,
            metadata={
                "source": "metric_registry",
                "label": result.label,
                "group": dict(result.group),
                "warnings": list(result.warnings),
            },
            created_at=row_created_at,
        )
        for result in results
    ]


def metric_results_to_summary_sections(results: Sequence[MetricResult]) -> dict[str, list[dict[str, Any]]]:
    summary_metrics: list[dict[str, Any]] = []
    grouped_metrics: list[dict[str, Any]] = []
    for result in results:
        item = metric_result_to_dict(result)
        if result.group == {"all": "all"}:
            summary_metrics.append(item)
        else:
            grouped_metrics.append(item)
    return {
        "summary_metrics": summary_metrics,
        "grouped_metrics": grouped_metrics,
    }


def metric_result_to_dict(result: MetricResult) -> dict[str, Any]:
    return {
        "code": result.code,
        "label": result.label,
        "value": result.value,
        "sample_size": result.sample_size,
        "group": dict(result.group),
        "warnings": list(result.warnings),
    }


def _summary_metric_results(summary: dict[str, Any]) -> list[MetricResult]:
    if not summary:
        return []
    signals_count = _summary_int(summary, "signals_count", _summary_int(summary, "signals_seen", 0))
    trades_count = _summary_int(summary, "trades_count", 0)
    execution_candidates = _summary_int(summary, "execution_candidates", 0)
    touched = _summary_int(summary, "entry_touched", _summary_int(summary, "touched", 0))
    no_entry = _summary_int(summary, "no_entry", 0)
    risk_rejections = _summary_int(summary, "risk_rejections", 0)
    execution_rejections = _summary_int(summary, "execution_rejections", 0)
    metric_values: list[tuple[str, str, float | int | None, int]] = [
        ("signals_count", "Signals Count", signals_count, signals_count),
        ("trades_count", "Trades Count", trades_count, trades_count),
        ("entry_touch_rate", "Entry Touch Rate", _summary_float(summary, "entry_touch_rate", _safe_rate(touched, signals_count)), signals_count),
        ("no_entry_rate", "No Entry Rate", _summary_float(summary, "no_entry_rate", _safe_rate(no_entry, signals_count)), signals_count),
        ("risk_rejection_rate", "Risk Rejection Rate", _safe_rate(risk_rejections, signals_count), signals_count),
        (
            "execution_rejection_rate",
            "Execution Rejection Rate",
            _safe_rate(execution_rejections, execution_candidates),
            execution_candidates,
        ),
    ]
    return [
        MetricResult(
            code=code,
            label=label,
            value=value,
            sample_size=max(0, sample_size),
            group={"all": "all"},
            warnings=[],
        )
        for code, label, value, sample_size in metric_values
    ]


def _merge_metric_results(
    preferred: Sequence[MetricResult],
    fallback: Sequence[MetricResult],
) -> list[MetricResult]:
    merged: list[MetricResult] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    for result in [*preferred, *fallback]:
        key = (result.code, tuple(sorted(result.group.items())))
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
    return merged


def _build_summary(
    run_detail: StrategyTestRunDetailResponse,
    trades: Sequence[StrategyTestTrade],
    metrics: Sequence[MetricResult],
    signal_events: Sequence[StrategyTestSignalEvent],
    *,
    source_summary: dict[str, Any] | None = None,
    analytics_warnings: Sequence[str] = (),
) -> dict[str, Any]:
    run = run_detail.run
    requested = run.requested_matrix
    all_metrics = _metric_map_for_group(metrics, {"all": "all"})
    source = source_summary or {}
    funnel = (
        build_signal_funnel_response(run.run_id, signal_events)
        if signal_events
        else _signal_funnel_from_summary(run.run_id, source)
    )
    trades_count = _metric_value(all_metrics, "trades_count")
    signals_seen = (
        _summary_int(source, "signals_seen", funnel.signals_count)
        if not signal_events
        else funnel.signals_count
    )
    signals_count = (
        _summary_int(source, "signals_count", funnel.signals_count)
        if not signal_events
        else funnel.signals_count
    )
    summary = {
        "run_id": str(run.run_id),
        "status": run.status,
        "mode": _run_mode(requested),
        "scenario_count": _summary_value(source, "scenario_count", requested.get("scenario_count")),
        "completed_scenarios": _summary_int(source, "completed_scenarios", 0),
        "failed_scenarios": _summary_int(source, "failed_scenarios", 0),
        "strategies": list(_list_value(requested.get("strategies"))),
        "pairs": list(_list_value(requested.get("pairs"))),
        "timeframes": list(_list_value(requested.get("timeframes"))),
        "start_at": requested.get("start_at"),
        "end_at": requested.get("end_at"),
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "signals_seen": signals_seen,
        "signals_count": signals_count,
        "execution_candidates": funnel.execution_candidates,
        "pending_armed": _summary_int(source, "pending_armed", 0),
        "touched": funnel.entry_touched,
        "entry_touched": funnel.entry_touched,
        "filled": funnel.filled,
        "closed": funnel.closed,
        "wins": funnel.wins,
        "losses": funnel.losses,
        "no_entry": funnel.no_entry,
        "entry_touch_rate": funnel.entry_touch_rate,
        "no_entry_rate": funnel.no_entry_rate,
        "false_signal_rate": funnel.false_signal_rate,
        "signal_funnel": funnel.model_dump(mode="json"),
        "total_trades": len(trades),
        "trades_count": trades_count if trades_count is not None else _summary_int(source, "trades_count", len(trades)),
        "winrate": _metric_value(all_metrics, "winrate"),
        "expectancy_r": _metric_value(all_metrics, "expectancy_r"),
        "expectancy_after_costs_r": _metric_value(all_metrics, "expectancy_after_costs_r"),
        "profit_factor": _metric_value(all_metrics, "profit_factor"),
        "max_drawdown_r": _metric_value(all_metrics, "max_drawdown_r"),
        "max_drawdown_pct": _metric_value(all_metrics, "max_drawdown_pct"),
        "fees_total": _metric_value(all_metrics, "fees_total"),
        "slippage_total": _metric_value(all_metrics, "slippage_total"),
        "risk_rejections": funnel.risk_rejected if signal_events else sum(1 for trade in trades if trade.risk_rejected),
        "execution_rejections": (
            funnel.execution_rejected if signal_events else sum(1 for trade in trades if trade.execution_rejected)
        ),
    }
    if not signal_events and source:
        summary["risk_rejections"] = _summary_int(source, "risk_rejections", summary["risk_rejections"])
        summary["execution_rejections"] = _summary_int(
            source,
            "execution_rejections",
            summary["execution_rejections"],
        )
    if run.error:
        summary["error"] = run.error
    elif isinstance(run.runtime_state.get("last_error"), str) and run.runtime_state["last_error"]:
        summary["error"] = run.runtime_state["last_error"]
    if source and run.status in {"failed", "cancelled", "running", "stopping"}:
        summary["partial_summary"] = dict(source)
    if analytics_warnings:
        summary["analytics_warnings"] = list(analytics_warnings)
    return summary


def _build_sections(
    *,
    trades: Sequence[StrategyTestTrade],
    signal_events: Sequence[StrategyTestSignalEvent],
    metrics: Sequence[MetricResult],
    summary: dict[str, Any],
    candidate_adjustments: Sequence[StrategyTestCandidateAdjustment],
    warnings: Sequence[str],
    rejections: Sequence[str],
) -> list[StrategyTestReportSection]:
    section_map = {
        "summary": StrategyTestReportSection(
            code="summary",
            name="Summary",
            summary=summary,
            metrics=_metrics_for_group(metrics, {"all": "all"}, SUMMARY_METRIC_CODES),
            warnings=list(warnings),
        ),
        "signal_funnel": StrategyTestReportSection(
            code="signal_funnel",
            name="Signal funnel",
            summary=summary.get("signal_funnel") if isinstance(summary.get("signal_funnel"), dict) else {},
            metrics=_metrics_for_group(metrics, {"all": "all"}, SIGNAL_FUNNEL_CODES),
            rows=[_compact_signal_event_row(event) for event in signal_events if event.no_entry],
            metadata={
                "rows_returned": sum(1 for event in signal_events if event.no_entry),
                "row_filter": "no_entry",
                "stages": (summary.get("signal_funnel") or {}).get("stages")
                if isinstance(summary.get("signal_funnel"), dict)
                else [],
            },
        ),
        "strategy_comparison": StrategyTestReportSection(
            code="strategy_comparison",
            name="Strategy comparison",
            rows=_metric_rows(metrics, ("strategy",), STRATEGY_COMPARISON_CODES),
        ),
        "pair_timeframe_breakdown": StrategyTestReportSection(
            code="pair_timeframe_breakdown",
            name="Pair/timeframe breakdown",
            rows=_metric_rows(metrics, ("strategy", "symbol", "timeframe"), STRATEGY_COMPARISON_CODES),
        ),
        "regime_breakdown": StrategyTestReportSection(
            code="regime_breakdown",
            name="Regime breakdown",
            rows=_metric_rows(metrics, ("strategy", "regime"), STRATEGY_COMPARISON_CODES),
        ),
        "score_bucket_breakdown": StrategyTestReportSection(
            code="score_bucket_breakdown",
            name="Score bucket breakdown",
            rows=_metric_rows(metrics, ("strategy", "score_bucket"), STRATEGY_COMPARISON_CODES),
        ),
        "entry_quality": StrategyTestReportSection(
            code="entry_quality",
            name="Entry quality",
            metrics=_metrics_for_group(metrics, {"all": "all"}, ENTRY_QUALITY_CODES),
            rows=_metric_rows(metrics, ("strategy", "timeframe"), ENTRY_QUALITY_CODES),
        ),
        "exit_quality": StrategyTestReportSection(
            code="exit_quality",
            name="Exit quality",
            metrics=_metrics_for_group(metrics, {"all": "all"}, EXIT_QUALITY_CODES),
            rows=_metric_rows(metrics, ("strategy", "timeframe"), EXIT_QUALITY_CODES),
        ),
        "mfe_mae_distribution": StrategyTestReportSection(
            code="mfe_mae_distribution",
            name="MFE/MAE distribution",
            rows=_mfe_mae_distribution_rows(trades),
        ),
        "rejection_analysis": StrategyTestReportSection(
            code="rejection_analysis",
            name="Rejection analysis",
            summary={
                "risk_rejections": _summary_int(
                    summary,
                    "risk_rejections",
                    sum(1 for trade in trades if trade.risk_rejected),
                ),
                "execution_rejections": _summary_int(
                    summary,
                    "execution_rejections",
                    sum(1 for trade in trades if trade.execution_rejected),
                ),
                "warning_counts": _warning_count_rows(trades),
                "rejections": list(rejections),
            },
            metrics=_metrics_for_group(metrics, {"all": "all"}, REJECTION_CODES),
            rows=_metric_rows(metrics, ("strategy",), REJECTION_CODES),
        ),
        "trade_list": StrategyTestReportSection(
            code="trade_list",
            name="Trade list",
            rows=[_compact_trade_row(trade) for trade in trades],
            metadata={"rows_returned": len(trades)},
        ),
        "recommended_strategy_adjustments": StrategyTestReportSection(
            code="recommended_strategy_adjustments",
            name="Recommended strategy adjustments",
            rows=[adjustment.model_dump(mode="json") for adjustment in candidate_adjustments],
        ),
    }
    return [section_map[code] for code, _name in SECTION_NAMES]


def _negative_score_bucket_adjustments(
    metrics: Sequence[MetricResult],
) -> list[StrategyTestCandidateAdjustment]:
    adjustments: list[StrategyTestCandidateAdjustment] = []
    for group, metric_map in _metric_maps_by_exact_group(metrics, ("strategy", "score_bucket", "timeframe")):
        value, metric_code, sample_size = _expectancy_signal(metric_map)
        if value is None or value >= 0 or sample_size < 5:
            continue
        strategy = group["strategy"]
        bucket = group["score_bucket"]
        timeframe = group["timeframe"]
        after_costs = _metric_value(metric_map, "expectancy_after_costs_r")
        reason = (
            f"Expectancy after costs is negative for {bucket} on {timeframe}."
            if after_costs is not None
            else f"Expectancy is negative for {bucket} on {timeframe}; expectancy after costs is unavailable."
        )
        adjustments.append(
            StrategyTestCandidateAdjustment(
                strategy_code=strategy,
                scope=f"score_bucket={bucket}; timeframe={timeframe}",
                reason=reason,
                evidence={
                    "metric": metric_code,
                    "value": value,
                    "expectancy_after_costs_r": after_costs if after_costs is not None else "unavailable",
                    "sample_size": sample_size,
                },
                suggested_change=(
                    f"Reduce or disable {strategy} for score_bucket {bucket} on {timeframe}; "
                    "expectancy after costs is negative."
                    if after_costs is not None
                    else f"Review or reduce {strategy} for score_bucket {bucket} on {timeframe}; after-cost data is unavailable."
                ),
                confidence=_confidence(sample_size),
            )
        )
    return adjustments


def _raise_score_threshold_adjustments(
    metrics: Sequence[MetricResult],
) -> list[StrategyTestCandidateAdjustment]:
    adjustments: list[StrategyTestCandidateAdjustment] = []
    by_strategy: dict[str, dict[str, tuple[float, str, int]]] = {}
    for group, metric_map in _metric_maps_by_exact_group(metrics, ("strategy", "score_bucket")):
        value, metric_code, sample_size = _expectancy_signal(metric_map)
        if value is None or sample_size < 5:
            continue
        by_strategy.setdefault(group["strategy"], {})[group["score_bucket"]] = (
            value,
            metric_code,
            sample_size,
        )

    for strategy, buckets in sorted(by_strategy.items()):
        negative_70 = [
            (bucket, value, metric_code, sample_size)
            for bucket, (value, metric_code, sample_size) in buckets.items()
            if _score_bucket_floor(bucket) == 70 and value < 0
        ]
        positive_high = [
            (bucket, value, metric_code, sample_size)
            for bucket, (value, metric_code, sample_size) in buckets.items()
            if _score_bucket_floor(bucket) is not None and (_score_bucket_floor(bucket) or 0) >= 80 and value > 0
        ]
        if not negative_70 or not positive_high:
            continue
        low_bucket, low_value, low_metric, low_sample = negative_70[0]
        high_bucket, high_value, high_metric, high_sample = positive_high[0]
        sample_size = min(low_sample, high_sample)
        adjustments.append(
            StrategyTestCandidateAdjustment(
                strategy_code=strategy,
                scope=f"score_bucket={low_bucket}",
                reason=f"High-score bucket {high_bucket} is positive while {low_bucket} is negative.",
                evidence={
                    "negative_bucket": low_bucket,
                    "negative_metric": low_metric,
                    "negative_value": low_value,
                    "positive_bucket": high_bucket,
                    "positive_metric": high_metric,
                    "positive_value": high_value,
                    "sample_size": sample_size,
                },
                suggested_change=f"Raise minimum score threshold toward 80 for {strategy}.",
                confidence=_confidence(sample_size),
            )
        )
    return adjustments


def _bullish_regime_short_adjustments(
    metrics: Sequence[MetricResult],
) -> list[StrategyTestCandidateAdjustment]:
    adjustments: list[StrategyTestCandidateAdjustment] = []
    for group, metric_map in _metric_maps_by_exact_group(metrics, ("strategy", "regime", "direction")):
        if group["direction"].lower() != "short" or "bull" not in group["regime"].lower():
            continue
        stop_rate = _metric_value(metric_map, "stop_rate")
        sample_size = _metric_sample_size(metric_map, "stop_rate")
        if stop_rate is None or stop_rate <= 0.6 or sample_size < 5:
            continue
        strategy = group["strategy"]
        adjustments.append(
            StrategyTestCandidateAdjustment(
                strategy_code=strategy,
                scope=f"regime={group['regime']}; direction=short",
                reason=f"Short signals under bullish regime stop out at {stop_rate:.2%}.",
                evidence={
                    "stop_rate": stop_rate,
                    "sample_size": sample_size,
                    "market_regime": group["regime"],
                    "direction": "short",
                },
                suggested_change=f"Avoid short signals for {strategy} under bullish HTF regime.",
                confidence=_confidence(sample_size),
            )
        )
    return adjustments


def _mae_mfe_adjustments(metrics: Sequence[MetricResult]) -> list[StrategyTestCandidateAdjustment]:
    adjustments: list[StrategyTestCandidateAdjustment] = []
    for group, metric_map in _metric_maps_by_exact_group(metrics, ("strategy", "timeframe")):
        avg_mae = _metric_value(metric_map, "avg_mae_r")
        avg_mfe = _metric_value(metric_map, "avg_mfe_r")
        sample_size = min(
            _metric_sample_size(metric_map, "avg_mae_r"),
            _metric_sample_size(metric_map, "avg_mfe_r"),
        )
        if avg_mae is None or avg_mfe is None or sample_size < 5:
            continue
        if abs(avg_mae) < 0.75 or avg_mfe < 1.0:
            continue
        strategy = group["strategy"]
        adjustments.append(
            StrategyTestCandidateAdjustment(
                strategy_code=strategy,
                scope=f"timeframe={group['timeframe']}",
                reason="Trades show high adverse and favorable excursion.",
                evidence={
                    "avg_mae_r": avg_mae,
                    "avg_mfe_r": avg_mfe,
                    "sample_size": sample_size,
                },
                suggested_change="Review stop placement or entry timing; trades move both against and in favor.",
                confidence=_confidence(sample_size),
            )
        )
    return adjustments


def _time_stop_adjustments(metrics: Sequence[MetricResult]) -> list[StrategyTestCandidateAdjustment]:
    adjustments: list[StrategyTestCandidateAdjustment] = []
    for group, metric_map in _metric_maps_by_exact_group(metrics, ("strategy", "timeframe")):
        time_stop_rate = _metric_value(metric_map, "time_stop_rate")
        sample_size = _metric_sample_size(metric_map, "time_stop_rate")
        if time_stop_rate is None or time_stop_rate <= 0.4 or sample_size < 5:
            continue
        strategy = group["strategy"]
        adjustments.append(
            StrategyTestCandidateAdjustment(
                strategy_code=strategy,
                scope=f"timeframe={group['timeframe']}",
                reason=f"Time-stop rate is {time_stop_rate:.2%}.",
                evidence={
                    "time_stop_rate": time_stop_rate,
                    "sample_size": sample_size,
                },
                suggested_change="Shorten signal expiry or improve entry trigger; many trades fail by time stop.",
                confidence=_confidence(sample_size),
            )
        )
    return adjustments


def _execution_rejection_adjustments(
    metrics: Sequence[MetricResult],
    *,
    mode: object,
) -> list[StrategyTestCandidateAdjustment]:
    if str(mode or "") != "production_like":
        return []

    adjustments: list[StrategyTestCandidateAdjustment] = []
    for group, metric_map in _metric_maps_by_exact_group(metrics, ("strategy",)):
        rejection_rate = _metric_value(metric_map, "execution_rejection_rate")
        sample_size = _metric_sample_size(metric_map, "execution_rejection_rate")
        if rejection_rate is None or rejection_rate <= 0.25 or sample_size < 5:
            continue
        strategy = group["strategy"]
        adjustments.append(
            StrategyTestCandidateAdjustment(
                strategy_code=strategy,
                scope="mode=production_like",
                reason=f"Execution rejection rate is {rejection_rate:.2%} in production-like mode.",
                evidence={
                    "execution_rejection_rate": rejection_rate,
                    "sample_size": sample_size,
                },
                suggested_change=(
                    "Execution assumptions/liquidity filters are rejecting many trades; "
                    "review slippage and size assumptions."
                ),
                confidence=_confidence(sample_size),
            )
        )
    return adjustments


def _metric_rows(
    metrics: Sequence[MetricResult],
    group_keys: tuple[str, ...],
    metric_codes: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group, metric_map in _metric_maps_by_exact_group(metrics, group_keys):
        row: dict[str, Any] = dict(group)
        sample_size = 0
        warnings: list[str] = []
        for code in metric_codes:
            result = metric_map.get(code)
            row[code] = result.value if result is not None else None
            if result is not None:
                sample_size = max(sample_size, result.sample_size)
                warnings.extend(result.warnings)
        row["sample_size"] = sample_size
        row["warnings"] = _dedupe_strings(warnings)
        rows.append(row)
    return sorted(rows, key=lambda item: tuple(str(item.get(key, "")) for key in group_keys))


def _metrics_for_group(
    metrics: Sequence[MetricResult],
    group: dict[str, str],
    metric_codes: Sequence[str],
) -> list[dict[str, Any]]:
    metric_map = _metric_map_for_group(metrics, group)
    return [
        metric_result_to_dict(metric_map[code])
        for code in metric_codes
        if code in metric_map
    ]


def _metric_maps_by_exact_group(
    metrics: Sequence[MetricResult],
    group_keys: tuple[str, ...],
) -> list[tuple[dict[str, str], dict[str, MetricResult]]]:
    groups: dict[tuple[tuple[str, str], ...], dict[str, MetricResult]] = {}
    group_values: dict[tuple[tuple[str, str], ...], dict[str, str]] = {}
    keys = set(group_keys)

    for result in metrics:
        if set(result.group) != keys:
            continue
        group_key = tuple(sorted(result.group.items()))
        groups.setdefault(group_key, {})[result.code] = result
        group_values[group_key] = dict(result.group)

    return [
        (group_values[group_key], groups[group_key])
        for group_key in sorted(groups)
    ]


def _metric_map_for_group(
    metrics: Sequence[MetricResult],
    group: dict[str, str],
) -> dict[str, MetricResult]:
    return {
        result.code: result
        for result in metrics
        if result.group == group
    }


def _metric_value(metric_map: dict[str, MetricResult], code: str) -> float | int | None:
    result = metric_map.get(code)
    value = result.value if result is not None else None
    if isinstance(value, (float, int)):
        return value
    return None


def _metric_sample_size(metric_map: dict[str, MetricResult], code: str) -> int:
    result = metric_map.get(code)
    return result.sample_size if result is not None else 0


def _expectancy_signal(metric_map: dict[str, MetricResult]) -> tuple[float | int | None, str, int]:
    after_costs = _metric_value(metric_map, "expectancy_after_costs_r")
    if after_costs is not None:
        return after_costs, "expectancy_after_costs_r", _metric_sample_size(metric_map, "expectancy_after_costs_r")
    expectancy = _metric_value(metric_map, "expectancy_r")
    return expectancy, "expectancy_r", _metric_sample_size(metric_map, "expectancy_r")


def _mfe_mae_distribution_rows(trades: Sequence[StrategyTestTrade]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric_name, values in (
        ("mfe_r", [trade.mfe_r for trade in trades if trade.mfe_r is not None]),
        ("mae_r", [trade.mae_r for trade in trades if trade.mae_r is not None]),
    ):
        buckets = Counter(_excursion_bucket(float(value)) for value in values)
        total = sum(buckets.values())
        for bucket in ("<=-1", "-1..-0.5", "-0.5..0", "0..0.5", "0.5..1", "1..2", ">2"):
            count = buckets.get(bucket, 0)
            rows.append(
                {
                    "metric": metric_name,
                    "bucket": bucket,
                    "count": count,
                    "rate": count / total if total else None,
                    "sample_size": total,
                }
            )
    return rows


def _excursion_bucket(value: float) -> str:
    if value <= -1:
        return "<=-1"
    if value <= -0.5:
        return "-1..-0.5"
    if value < 0:
        return "-0.5..0"
    if value < 0.5:
        return "0..0.5"
    if value < 1:
        return "0.5..1"
    if value <= 2:
        return "1..2"
    return ">2"


def _compact_trade_row(trade: StrategyTestTrade) -> dict[str, Any]:
    return {
        "run_id": str(trade.run_id),
        "trade_id": trade.trade_id,
        "strategy_code": trade.strategy_code,
        "exchange": trade.exchange,
        "symbol": trade.symbol,
        "timeframe": trade.timeframe,
        "direction": trade.direction,
        "signal_score": trade.signal_score,
        "market_regime": trade.market_regime,
        "score_bucket": trade.score_bucket,
        "entry_time": trade.entry_time,
        "exit_time": trade.exit_time,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "realized_r": trade.realized_r,
        "pnl": trade.pnl,
        "fees": trade.fees,
        "slippage": trade.slippage,
        "mfe_r": trade.mfe_r,
        "mae_r": trade.mae_r,
        "close_reason": trade.close_reason,
        "outcome": trade.outcome,
        "risk_rejected": trade.risk_rejected,
        "execution_rejected": trade.execution_rejected,
        "warnings": list(trade.warnings),
        "tags": list(trade.tags),
    }


def _compact_signal_event_row(event: StrategyTestSignalEvent) -> dict[str, Any]:
    return {
        "run_id": str(event.run_id),
        "signal_id": event.signal_id,
        "synthetic_signal_id": event.synthetic_signal_id,
        "signal_key": event.signal_key,
        "strategy_code": event.strategy_code,
        "exchange": event.exchange,
        "symbol": event.symbol,
        "timeframe": event.timeframe,
        "direction": event.direction,
        "event_time": event.event_time,
        "candle_time": event.candle_time,
        "signal_score": event.signal_score,
        "market_regime": event.market_regime,
        "score_bucket": event.score_bucket,
        "status": event.status,
        "gate_status": event.gate_status,
        "feed_kind": event.feed_kind,
        "trigger_passed": event.trigger_passed,
        "trigger_reason_code": event.trigger_reason_code,
        "execution_candidate": event.execution_candidate,
        "entry_touched": event.entry_touched,
        "filled": event.filled,
        "closed": event.closed,
        "outcome": event.outcome,
        "funnel_stage": event.funnel_stage,
        "risk_rejected": event.risk_rejected,
        "execution_rejected": event.execution_rejected,
        "no_entry": event.no_entry,
        "rejection_reason_code": event.rejection_reason_code,
        "blocked_reason_code": event.blocked_reason_code,
    }


def _warning_count_rows(trades: Sequence[StrategyTestTrade]) -> list[dict[str, Any]]:
    counts = Counter(warning for trade in trades for warning in trade.warnings)
    return [
        {"warning": warning, "count": count}
        for warning, count in sorted(counts.items())
    ]


def _report_warnings(metrics: Sequence[MetricResult], trades: Sequence[StrategyTestTrade]) -> list[str]:
    warnings: list[str] = []
    for result in metrics:
        if result.group == {"all": "all"}:
            warnings.extend(result.warnings)
    for trade in trades:
        warnings.extend(trade.warnings)
    if not trades:
        warnings.append("insufficient_data")
    return _dedupe_strings(warnings)


def _report_rejections(trades: Sequence[StrategyTestTrade]) -> list[str]:
    rejections: list[str] = []
    risk_count = sum(1 for trade in trades if trade.risk_rejected)
    execution_count = sum(1 for trade in trades if trade.execution_rejected)
    if risk_count:
        rejections.append(f"risk_rejections:{risk_count}")
    if execution_count:
        rejections.append(f"execution_rejections:{execution_count}")
    return rejections


def _assumptions_from_run(run_detail: StrategyTestRunDetailResponse) -> dict[str, Any]:
    requested = run_detail.run.requested_matrix
    assumptions = {
        "mode": _run_mode(requested),
        "initial_capital": requested.get("initial_capital"),
        "fee_rate": requested.get("fee_rate"),
        "slippage_bps": requested.get("slippage_bps"),
        "same_candle_policy": requested.get("same_candle_policy"),
    }
    params = requested.get("params")
    if isinstance(params, dict):
        assumptions["params"] = dict(params)
    scenario_assumptions = _scenario_assumptions(run_detail.run.summary)
    if scenario_assumptions:
        assumptions["scenario_assumptions"] = scenario_assumptions
    return assumptions


def _scenario_assumptions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = summary.get("scenarios")
    if not isinstance(scenarios, list):
        return []

    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        assumptions = scenario.get("assumptions")
        if not isinstance(assumptions, dict):
            continue
        key = tuple(sorted((str(item_key), str(item_value)) for item_key, item_value in assumptions.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(assumptions))
    return result


def _run_summary_source(run_detail: StrategyTestRunDetailResponse) -> dict[str, Any]:
    runtime_summary = run_detail.run.runtime_state.get("partial_summary")
    source: dict[str, Any] = dict(runtime_summary) if isinstance(runtime_summary, dict) else {}
    source.update(run_detail.run.summary)
    return _normalize_summary_source(source)


def _normalize_summary_source(summary: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(summary)
    if "signals_count" not in normalized and "signals_seen" in normalized:
        normalized["signals_count"] = normalized["signals_seen"]
    if "signals_seen" not in normalized and "signals_count" in normalized:
        normalized["signals_seen"] = normalized["signals_count"]
    if "touched" not in normalized and "entry_touched" in normalized:
        normalized["touched"] = normalized["entry_touched"]
    if "entry_touched" not in normalized and "touched" in normalized:
        normalized["entry_touched"] = normalized["touched"]
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
        "wins",
        "losses",
        "no_entry",
        "risk_rejections",
        "execution_rejections",
    ):
        if key not in normalized:
            normalized[key] = 0
    errors = normalized.get("errors")
    normalized["errors"] = list(errors) if isinstance(errors, list) else []
    return normalized


def _summary_int(summary: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(summary.get(key, default) or 0)
    except (TypeError, ValueError):
        return default


def _summary_float(summary: dict[str, Any], key: str, default: float | None = None) -> float | None:
    value = summary.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summary_value(summary: dict[str, Any], key: str, default: Any = None) -> Any:
    value = summary.get(key)
    return default if value is None else value


def _summary_stages(
    summary: dict[str, Any],
    nested_summary: dict[str, Any],
    *,
    signals_count: int,
) -> list[dict[str, Any]]:
    nested_stages = nested_summary.get("stages")
    if isinstance(nested_stages, list):
        return [dict(stage) for stage in nested_stages if isinstance(stage, dict)]
    stage_keys = (
        ("signal", "signals_count"),
        ("pending_armed", "pending_armed"),
        ("entry_touched", "entry_touched"),
        ("filled", "filled"),
        ("closed", "closed"),
        ("no_entry", "no_entry"),
    )
    if signals_count <= 0 and all(_summary_int(summary, key, 0) <= 0 for _stage, key in stage_keys):
        return []
    stages: list[dict[str, Any]] = []
    for stage, key in stage_keys:
        count = _summary_int(summary, key, 0)
        if count <= 0 and signals_count > 0:
            continue
        stages.append({"stage": stage, "count": count, "rate": _safe_rate(count, signals_count)})
    return stages


def _summary_warning_codes(summary: dict[str, Any]) -> list[str]:
    warnings = summary.get("warnings")
    if not isinstance(warnings, list):
        return []
    codes: list[str] = []
    for warning in warnings:
        if isinstance(warning, dict) and warning.get("code"):
            codes.append(str(warning["code"]))
        elif isinstance(warning, str):
            codes.append(warning)
    return codes


def _run_mode(requested_matrix: dict[str, Any]) -> StrategyTestMode:
    value = requested_matrix.get("mode")
    if value in {"discovery", "research_virtual", "production_like"}:
        return cast(StrategyTestMode, value)
    return "research_virtual"


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return count / total


def _normalized_outcome(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _score_bucket_floor(bucket: str) -> int | None:
    text = bucket.strip()
    if not text:
        return None
    first = text.split("-", 1)[0]
    try:
        return int(first)
    except ValueError:
        return None


def _confidence(sample_size: int) -> Literal["low", "medium", "high"]:
    if sample_size >= 30:
        return "high"
    if sample_size >= 10:
        return "medium"
    return "low"


def _dedupe_adjustments(
    adjustments: Sequence[StrategyTestCandidateAdjustment],
) -> list[StrategyTestCandidateAdjustment]:
    result: list[StrategyTestCandidateAdjustment] = []
    seen: set[tuple[str, str, str]] = set()
    for adjustment in adjustments:
        key = (adjustment.strategy_code, adjustment.scope, adjustment.suggested_change)
        if key in seen:
            continue
        seen.add(key)
        result.append(adjustment)
    return result


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _dimension(group: dict[str, str], key: str) -> str:
    return group.get(key) or "all"


def _metric_value_to_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)
