from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, Sequence, cast
from uuid import UUID

from app.services.strategy_testing.metrics import MetricRegistry, MetricResult, build_base_metric_registry
from app.services.strategy_testing.schemas import (
    StrategyTestCandidateAdjustment,
    StrategyTestMetricRow,
    StrategyTestMode,
    StrategyTestReport,
    StrategyTestReportSection,
    StrategyTestRunDetailResponse,
    StrategyTestRunStatus,
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
    "trades_count",
    "winrate",
    "expectancy_r",
    "expectancy_after_costs_r",
    "profit_factor",
    "max_drawdown_r",
    "max_drawdown_pct",
    "fees_total",
    "slippage_total",
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
        trades = self._analytics_store.list_trades(run.run_id)
        metric_results = build_report_metric_results(
            trades,
            registry=self._metric_registry,
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
        rejections = _report_rejections(trades)
        summary = _build_summary(run_detail, trades, metric_results)
        sections = _build_sections(
            trades=trades,
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
            trades_count=len(trades),
            warnings=warnings,
            rejections=rejections,
        )


def build_matrix_metric_results(
    trades: Sequence[StrategyTestTrade],
    *,
    metric_set: Sequence[str] | None = None,
    registry: MetricRegistry | None = None,
) -> list[MetricResult]:
    metric_registry = registry or build_base_metric_registry()
    results: list[MetricResult] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    for grouping in MATRIX_METRIC_GROUPINGS:
        computed = metric_registry.compute(
            trades,
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
    registry: MetricRegistry | None = None,
) -> list[MetricResult]:
    metric_registry = registry or build_base_metric_registry()
    results = build_matrix_metric_results(trades, registry=metric_registry)
    seen = {(result.code, tuple(sorted(result.group.items()))) for result in results}

    for grouping in REPORT_EXTRA_GROUPINGS:
        for result in metric_registry.compute(trades, group_by=list(grouping)):
            if result.group == {"all": "all"}:
                continue
            key = (result.code, tuple(sorted(result.group.items())))
            if key in seen:
                continue
            seen.add(key)
            results.append(result)
    return results


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


def _build_summary(
    run_detail: StrategyTestRunDetailResponse,
    trades: Sequence[StrategyTestTrade],
    metrics: Sequence[MetricResult],
) -> dict[str, Any]:
    run = run_detail.run
    requested = run.requested_matrix
    all_metrics = _metric_map_for_group(metrics, {"all": "all"})
    return {
        "run_id": str(run.run_id),
        "status": run.status,
        "mode": _run_mode(requested),
        "scenario_count": requested.get("scenario_count"),
        "strategies": list(_list_value(requested.get("strategies"))),
        "pairs": list(_list_value(requested.get("pairs"))),
        "timeframes": list(_list_value(requested.get("timeframes"))),
        "start_at": requested.get("start_at"),
        "end_at": requested.get("end_at"),
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "total_trades": len(trades),
        "trades_count": _metric_value(all_metrics, "trades_count"),
        "winrate": _metric_value(all_metrics, "winrate"),
        "expectancy_r": _metric_value(all_metrics, "expectancy_r"),
        "expectancy_after_costs_r": _metric_value(all_metrics, "expectancy_after_costs_r"),
        "profit_factor": _metric_value(all_metrics, "profit_factor"),
        "max_drawdown_r": _metric_value(all_metrics, "max_drawdown_r"),
        "max_drawdown_pct": _metric_value(all_metrics, "max_drawdown_pct"),
        "fees_total": _metric_value(all_metrics, "fees_total"),
        "slippage_total": _metric_value(all_metrics, "slippage_total"),
        "risk_rejections": sum(1 for trade in trades if trade.risk_rejected),
        "execution_rejections": sum(1 for trade in trades if trade.execution_rejected),
    }


def _build_sections(
    *,
    trades: Sequence[StrategyTestTrade],
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
                "risk_rejections": sum(1 for trade in trades if trade.risk_rejected),
                "execution_rejections": sum(1 for trade in trades if trade.execution_rejected),
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


def _run_mode(requested_matrix: dict[str, Any]) -> StrategyTestMode:
    value = requested_matrix.get("mode")
    if value in {"discovery", "research_virtual", "production_like"}:
        return cast(StrategyTestMode, value)
    return "research_virtual"


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


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
