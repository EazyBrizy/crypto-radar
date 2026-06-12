from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.services.strategy_testing.metrics import MetricResult
from app.services.strategy_testing.report_builder import (
    build_matrix_metric_results,
    metric_results_to_summary_sections,
)
from app.services.strategy_testing.runner import StrategyTestScenarioResult, StrategyTestScenarioRunner
from app.services.strategy_testing.schemas import (
    StrategyTestPair,
    StrategyTestRunRequest,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)


class ScenarioRunner(Protocol):
    def run_scenario(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        request: StrategyTestRunRequest,
        strategy: str,
        pair: StrategyTestPair,
        timeframe: str,
    ) -> StrategyTestScenarioResult:
        ...


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

    @property
    def all_failed(self) -> bool:
        return self.scenario_count > 0 and self.completed_scenarios == 0

    def summary(self, metrics: Sequence[MetricResult] | None = None) -> dict[str, Any]:
        summary_signals_seen = sum(_int_from_summary(item, "signals_seen") for item in self.scenario_summaries)
        signals_count = len(self.signal_events) or summary_signals_seen
        signals_seen = signals_count
        execution_candidates = sum(1 for event in self.signal_events if event.execution_candidate)
        entry_touched = sum(1 for event in self.signal_events if event.entry_touched)
        filled = sum(1 for event in self.signal_events if event.filled)
        closed = sum(1 for event in self.signal_events if event.closed)
        wins = sum(1 for event in self.signal_events if _normalized_outcome(event.outcome) == "win")
        losses = sum(1 for event in self.signal_events if _normalized_outcome(event.outcome) == "loss")
        no_entry = sum(1 for event in self.signal_events if event.no_entry)
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
            "trades_count": len(self.trades),
            "signals_seen": signals_seen,
            "signals_count": signals_count,
            "execution_candidates": execution_candidates,
            "entry_touched": entry_touched,
            "filled": filled,
            "closed": closed,
            "wins": wins,
            "losses": losses,
            "no_entry": no_entry,
            "risk_rejections": risk_rejections,
            "execution_rejections": execution_rejections,
            "errors": list(self.errors),
            "scenarios": list(self.scenario_summaries),
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
    ) -> StrategyTestMatrixResult:
        scenario_count = len(request.strategies) * len(request.pairs) * len(request.timeframes)
        completed = 0
        failed = 0
        scenario_summaries: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        trades: list[StrategyTestTrade] = []
        signal_events: list[StrategyTestSignalEvent] = []

        for strategy in request.strategies:
            for pair in request.pairs:
                for timeframe in request.timeframes:
                    try:
                        result = self._scenario_runner.run_scenario(
                            run_id=run_id,
                            user_id=user_uuid,
                            request=request,
                            strategy=strategy,
                            pair=pair,
                            timeframe=timeframe,
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
                        continue

                    completed += 1
                    scenario_summaries.append(result.summary)
                    trades.extend(result.trades)
                    signal_events.extend(result.signal_events)

        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=scenario_count,
            completed_scenarios=completed,
            failed_scenarios=failed,
            scenario_summaries=scenario_summaries,
            errors=errors,
            trades=trades,
            signal_events=signal_events,
            metrics=build_matrix_metric_results(
                trades,
                signal_events=signal_events,
                metric_set=request.metric_set,
            ),
        )


def _int_from_summary(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _normalized_outcome(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
