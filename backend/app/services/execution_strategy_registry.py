from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings
from app.repositories.strategy_execution_eligibility import (
    StrategyExecutionEligibilityProfileKey,
    StrategyExecutionEligibilityProfileRecord,
    StrategyExecutionEligibilityProfileRepository,
)
from app.schemas.signal import SignalEdgeSnapshot


@dataclass(frozen=True)
class ExecutionStrategyEligibility:
    eligible: bool
    reason_code: str
    reason: str
    source: str
    metrics: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "source": self.source,
            "metrics": self.metrics,
        }


class StrategyExecutionEligibilityProfileReader(Protocol):
    def get_profile(
        self,
        *,
        strategy_code: str,
        exchange: str,
        symbol_scope: str,
        timeframe: str,
        market_regime: str,
        score_bucket: str,
        direction: str,
    ) -> StrategyExecutionEligibilityProfileRecord | None:
        ...


class ExecutionStrategyEligibilityService:
    def __init__(
        self,
        *,
        require_walk_forward_edge: bool | None = None,
        profile_repository: StrategyExecutionEligibilityProfileReader | None = None,
    ) -> None:
        self._require_walk_forward_edge = (
            bool(settings.execution_require_walk_forward_edge)
            if require_walk_forward_edge is None
            else bool(require_walk_forward_edge)
        )
        self._profile_repository = profile_repository or StrategyExecutionEligibilityProfileRepository()

    def evaluate(
        self,
        edge: SignalEdgeSnapshot | None,
        *,
        profile_key: StrategyExecutionEligibilityProfileKey | None = None,
    ) -> ExecutionStrategyEligibility:
        if profile_key is not None:
            persisted = self._profile_repository.get_profile(
                strategy_code=profile_key.strategy_code,
                exchange=profile_key.exchange,
                symbol_scope=profile_key.symbol_scope,
                timeframe=profile_key.timeframe,
                market_regime=profile_key.market_regime,
                score_bucket=profile_key.score_bucket,
                direction=profile_key.direction,
            )
            if persisted is not None:
                return _persisted_profile_eligibility(persisted)

        if edge is None or edge.source == "none" or edge.sample_size <= 0:
            return ExecutionStrategyEligibility(
                eligible=False,
                reason_code="strategy_eligibility_missing",
                reason="No execution edge profile is available for this strategy.",
                source="none",
                metrics={},
            )

        metrics = _metrics(edge)
        blockers = _base_blockers(metrics)
        if self._require_walk_forward_edge:
            blockers.extend(_validation_blockers(metrics))
        if blockers:
            return ExecutionStrategyEligibility(
                eligible=False,
                reason_code="strategy_eligibility_failed",
                reason=blockers[0],
                source=str(edge.metadata.get("profile_source") or edge.source),
                metrics=metrics,
            )

        return ExecutionStrategyEligibility(
            eligible=True,
            reason_code="strategy_eligibility_passed",
            reason="Strategy edge metrics pass execution eligibility thresholds.",
            source=str(edge.metadata.get("profile_source") or edge.source),
            metrics=metrics,
        )


def _persisted_profile_eligibility(
    profile: StrategyExecutionEligibilityProfileRecord,
) -> ExecutionStrategyEligibility:
    metrics = {
        **dict(profile.metrics),
        "sample_size": profile.sample_size,
        "expectancy_after_costs_r": profile.expectancy_after_costs_r,
        "profit_factor": profile.profit_factor,
        "entry_touch_rate": profile.entry_touch_rate,
        "no_entry_rate": profile.no_entry_rate,
        "max_drawdown_r": profile.max_drawdown_r,
        "run_ids": list(profile.run_ids),
    }
    return ExecutionStrategyEligibility(
        eligible=profile.eligible,
        reason_code=profile.reason_code,
        reason=profile.reason,
        source=profile.source,
        metrics=metrics,
    )


def _metrics(edge: SignalEdgeSnapshot) -> dict[str, float | int | None]:
    metadata = edge.metadata
    return {
        "sample_size": edge.sample_size,
        "expectancy_after_costs_r": edge.expectancy_after_costs_r,
        "profit_factor": edge.profit_factor,
        "entry_touch_rate": _float_metadata(metadata, "entry_touch_rate"),
        "no_entry_rate": _float_metadata(metadata, "no_entry_rate"),
        "validation_sample_size": _int_metadata(metadata, "validation_sample_size"),
        "validation_expectancy_r": _float_metadata(metadata, "validation_expectancy_r"),
        "validation_profit_factor": _float_metadata(metadata, "validation_profit_factor"),
        "validation_max_drawdown_r": _float_metadata(metadata, "validation_max_drawdown_r"),
    }


def _base_blockers(metrics: dict[str, float | int | None]) -> list[str]:
    blockers: list[str] = []
    if int(metrics["sample_size"] or 0) < settings.execution_edge_min_sample_size:
        blockers.append("Strategy edge sample size is below the execution threshold.")
    expectancy = _float(metrics["expectancy_after_costs_r"])
    if expectancy is None or expectancy < settings.execution_edge_min_expectancy_after_costs_r:
        blockers.append("Strategy expectancy after costs is below the execution threshold.")
    profit_factor = _float(metrics["profit_factor"])
    if profit_factor is None or profit_factor < settings.execution_edge_min_profit_factor:
        blockers.append("Strategy profit factor is below the execution threshold.")
    entry_touch_rate = _float(metrics["entry_touch_rate"])
    if entry_touch_rate is not None and entry_touch_rate < settings.execution_min_entry_touch_rate:
        blockers.append("Strategy entry touch rate is below the execution threshold.")
    no_entry_rate = _float(metrics["no_entry_rate"])
    if no_entry_rate is not None and no_entry_rate > settings.execution_max_no_entry_rate:
        blockers.append("Strategy no-entry rate is above the execution threshold.")
    return blockers


def _validation_blockers(metrics: dict[str, float | int | None]) -> list[str]:
    blockers: list[str] = []
    if int(metrics["validation_sample_size"] or 0) < settings.execution_min_validation_sample_size:
        blockers.append("Strategy validation sample size is below the execution threshold.")
    validation_expectancy = _float(metrics["validation_expectancy_r"])
    if validation_expectancy is None or validation_expectancy < settings.execution_min_validation_expectancy_r:
        blockers.append("Strategy validation expectancy is below the execution threshold.")
    validation_profit_factor = _float(metrics["validation_profit_factor"])
    if validation_profit_factor is None or validation_profit_factor < settings.execution_min_validation_profit_factor:
        blockers.append("Strategy validation profit factor is below the execution threshold.")
    validation_drawdown = _float(metrics["validation_max_drawdown_r"])
    if validation_drawdown is None or validation_drawdown > settings.execution_max_validation_drawdown_r:
        blockers.append("Strategy validation drawdown is above the execution threshold.")
    return blockers


def _float_metadata(metadata: dict[str, Any], key: str) -> float | None:
    return _float(metadata.get(key))


def _int_metadata(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


execution_strategy_eligibility_service = ExecutionStrategyEligibilityService()
