from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from app.services.strategy_testing.metrics import MetricRegistry, MetricResult, build_base_metric_registry
from app.services.strategy_testing.schemas import StrategyTestMetricRow, StrategyTestMode, StrategyTestTrade


MATRIX_METRIC_GROUPINGS: tuple[tuple[str, ...], ...] = (
    (),
    ("strategy",),
    ("strategy", "symbol", "timeframe"),
    ("strategy", "regime"),
    ("strategy", "score_bucket"),
    ("strategy", "direction"),
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


def _dimension(group: dict[str, str], key: str) -> str:
    return group.get(key) or "all"


def _metric_value_to_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)
