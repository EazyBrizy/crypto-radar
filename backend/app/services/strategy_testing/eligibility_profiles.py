from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.core.config import settings
from app.repositories.strategy_execution_eligibility import (
    StrategyExecutionEligibilityProfileRecord,
    StrategyExecutionEligibilityProfileRepository,
    StrategyExecutionEligibilityProfileUpsert,
)
from app.services.strategy_testing.metrics import MetricResult
from app.services.strategy_testing.schemas import StrategyTestRunRequest


PROFILE_GROUP_KEYS = ("strategy", "exchange", "symbol", "timeframe", "regime", "score_bucket", "direction")
PROFILE_METRIC_CODES = (
    "trades_count",
    "expectancy_after_costs_r",
    "profit_factor",
    "entry_touch_rate",
    "no_entry_rate",
    "max_drawdown_r",
)


class StrategyExecutionEligibilityProfileWriter(Protocol):
    def upsert_profile(
        self,
        profile: StrategyExecutionEligibilityProfileUpsert,
    ) -> Any:
        ...


class StrategyExecutionEligibilityProfileUpdater:
    def __init__(
        self,
        repository: StrategyExecutionEligibilityProfileWriter | None = None,
    ) -> None:
        self._repository = repository or StrategyExecutionEligibilityProfileRepository()

    def update_from_metric_results(
        self,
        *,
        run_id: UUID,
        request: StrategyTestRunRequest,
        metrics: Sequence[MetricResult],
    ) -> list[StrategyExecutionEligibilityProfileRecord]:
        published: list[StrategyExecutionEligibilityProfileRecord] = []
        for profile in build_profile_upserts_from_metric_results(
            run_id=run_id,
            request=request,
            metrics=metrics,
        ):
            published.append(self._repository.upsert_profile(profile))
        return published


def build_profile_upserts_from_metric_results(
    *,
    run_id: UUID,
    request: StrategyTestRunRequest,
    metrics: Sequence[MetricResult],
) -> list[StrategyExecutionEligibilityProfileUpsert]:
    return [
        profile
        for group, metric_map in _profile_metric_maps(metrics)
        if (
            profile := _profile_from_metric_map(
                run_id=run_id,
                source=request.test_type,
                group=group,
                metric_map=metric_map,
            )
        )
        is not None
    ]


def _profile_metric_maps(
    metrics: Sequence[MetricResult],
) -> list[tuple[dict[str, str], dict[str, MetricResult]]]:
    groups: dict[tuple[tuple[str, str], ...], dict[str, MetricResult]] = defaultdict(dict)
    group_values: dict[tuple[tuple[str, str], ...], dict[str, str]] = {}
    keys = set(PROFILE_GROUP_KEYS)
    for result in metrics:
        if set(result.group) != keys:
            continue
        if result.code not in PROFILE_METRIC_CODES:
            continue
        group_key = tuple(sorted(result.group.items()))
        group_values[group_key] = dict(result.group)
        groups[group_key][result.code] = result
    return [(group_values[group_key], groups[group_key]) for group_key in sorted(groups)]


def _profile_from_metric_map(
    *,
    run_id: UUID,
    source: str,
    group: dict[str, str],
    metric_map: dict[str, MetricResult],
) -> StrategyExecutionEligibilityProfileUpsert | None:
    if not metric_map:
        return None
    sample_size = _sample_size(metric_map)
    metrics = {
        code: _metric_value(metric_map, code)
        for code in PROFILE_METRIC_CODES
        if code in metric_map
    }
    metrics["sample_size"] = sample_size
    eligible, reason_code, reason = _eligibility_decision(
        sample_size=sample_size,
        expectancy_after_costs_r=_optional_float(metrics.get("expectancy_after_costs_r")),
        profit_factor=_optional_float(metrics.get("profit_factor")),
        entry_touch_rate=_optional_float(metrics.get("entry_touch_rate")),
        no_entry_rate=_optional_float(metrics.get("no_entry_rate")),
    )
    return StrategyExecutionEligibilityProfileUpsert(
        strategy_code=group["strategy"],
        exchange=group["exchange"],
        symbol_scope=group["symbol"],
        timeframe=group["timeframe"],
        market_regime=group["regime"],
        score_bucket=group["score_bucket"],
        direction=group["direction"],
        eligible=eligible,
        source=_source(source),
        metrics=metrics,
        sample_size=sample_size,
        expectancy_after_costs_r=_optional_float(metrics.get("expectancy_after_costs_r")),
        profit_factor=_optional_float(metrics.get("profit_factor")),
        entry_touch_rate=_optional_float(metrics.get("entry_touch_rate")),
        no_entry_rate=_optional_float(metrics.get("no_entry_rate")),
        max_drawdown_r=_optional_float(metrics.get("max_drawdown_r")),
        run_ids=[str(run_id)],
        reason_code=reason_code,
        reason=reason,
    )


def _eligibility_decision(
    *,
    sample_size: int,
    expectancy_after_costs_r: float | None,
    profit_factor: float | None,
    entry_touch_rate: float | None,
    no_entry_rate: float | None,
) -> tuple[bool, str, str]:
    blockers: list[str] = []
    if sample_size < settings.execution_edge_min_sample_size:
        return (
            False,
            "strategy_eligibility_insufficient_sample",
            "Strategy edge sample size is below the execution threshold.",
        )
    if (
        expectancy_after_costs_r is None
        or expectancy_after_costs_r < settings.execution_edge_min_expectancy_after_costs_r
    ):
        blockers.append("Strategy expectancy after costs is below the execution threshold.")
    if profit_factor is None or profit_factor < settings.execution_edge_min_profit_factor:
        blockers.append("Strategy profit factor is below the execution threshold.")
    if entry_touch_rate is not None and entry_touch_rate < settings.execution_min_entry_touch_rate:
        blockers.append("Strategy entry touch rate is below the execution threshold.")
    if no_entry_rate is not None and no_entry_rate > settings.execution_max_no_entry_rate:
        blockers.append("Strategy no-entry rate is above the execution threshold.")

    if blockers:
        return False, "strategy_eligibility_failed", blockers[0]
    return True, "strategy_eligibility_passed", "Strategy edge metrics pass execution eligibility thresholds."


def _sample_size(metric_map: dict[str, MetricResult]) -> int:
    trades_count = _metric_value(metric_map, "trades_count")
    if trades_count is not None:
        try:
            return max(0, int(trades_count))
        except (TypeError, ValueError):
            pass
    return max((result.sample_size for result in metric_map.values()), default=0)


def _metric_value(metric_map: dict[str, MetricResult], code: str) -> float | int | None:
    result = metric_map.get(code)
    value = result.value if result is not None else None
    if isinstance(value, (float, int)):
        return value
    return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source(value: str) -> str:
    if value in {"historical_backtest", "forward_virtual"}:
        return value
    return "historical_backtest"
