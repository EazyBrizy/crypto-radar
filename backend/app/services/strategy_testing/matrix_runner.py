from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.services.strategy_testing.runner import StrategyTestScenarioResult, StrategyTestScenarioRunner
from app.services.strategy_testing.schemas import StrategyTestPair, StrategyTestRunRequest, StrategyTestTrade


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

    @property
    def all_failed(self) -> bool:
        return self.scenario_count > 0 and self.completed_scenarios == 0

    def summary(self) -> dict[str, Any]:
        signals_seen = sum(_int_from_summary(item, "signals_seen") for item in self.scenario_summaries)
        risk_rejections = sum(_int_from_summary(item, "risk_rejections") for item in self.scenario_summaries)
        execution_rejections = sum(
            _int_from_summary(item, "execution_rejections") for item in self.scenario_summaries
        )
        return {
            "scenario_count": self.scenario_count,
            "completed_scenarios": self.completed_scenarios,
            "failed_scenarios": self.failed_scenarios,
            "trades_count": len(self.trades),
            "signals_seen": signals_seen,
            "risk_rejections": risk_rejections,
            "execution_rejections": execution_rejections,
            "errors": list(self.errors),
            "scenarios": list(self.scenario_summaries),
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

        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=scenario_count,
            completed_scenarios=completed,
            failed_scenarios=failed,
            scenario_summaries=scenario_summaries,
            errors=errors,
            trades=trades,
        )


def _int_from_summary(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0
