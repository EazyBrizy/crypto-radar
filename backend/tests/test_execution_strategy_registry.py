import unittest

from app.schemas.signal import SignalEdgeSnapshot
from app.repositories.strategy_execution_eligibility import (
    StrategyExecutionEligibilityProfileKey,
    StrategyExecutionEligibilityProfileRecord,
)
from app.services.execution_strategy_registry import ExecutionStrategyEligibilityService


class ExecutionStrategyEligibilityServiceTest(unittest.TestCase):
    def test_no_edge_data_is_not_eligible(self) -> None:
        eligibility = ExecutionStrategyEligibilityService(require_walk_forward_edge=True).evaluate(
            _edge(status="unknown", source="none", sample_size=0, expectancy=None, profit_factor=None)
        )

        self.assertFalse(eligibility.eligible)
        self.assertEqual(eligibility.reason_code, "strategy_eligibility_missing")
        self.assertEqual(eligibility.source, "none")

    def test_positive_walk_forward_metrics_are_eligible(self) -> None:
        eligibility = ExecutionStrategyEligibilityService(require_walk_forward_edge=True).evaluate(
            _edge(
                status="positive",
                sample_size=80,
                expectancy=0.16,
                profit_factor=1.45,
                metadata={
                    "entry_touch_rate": 0.42,
                    "no_entry_rate": 0.18,
                    "validation_sample_size": 45,
                    "validation_expectancy_r": 0.12,
                    "validation_profit_factor": 1.32,
                    "validation_max_drawdown_r": 4.2,
                },
            )
        )

        self.assertTrue(eligibility.eligible)
        self.assertEqual(eligibility.reason_code, "strategy_eligibility_passed")

    def test_negative_validation_metrics_are_not_eligible(self) -> None:
        eligibility = ExecutionStrategyEligibilityService(require_walk_forward_edge=True).evaluate(
            _edge(
                status="positive",
                sample_size=80,
                expectancy=0.16,
                profit_factor=1.45,
                metadata={
                    "entry_touch_rate": 0.42,
                    "no_entry_rate": 0.18,
                    "validation_sample_size": 45,
                    "validation_expectancy_r": -0.04,
                    "validation_profit_factor": 0.9,
                    "validation_max_drawdown_r": 4.2,
                },
            )
        )

        self.assertFalse(eligibility.eligible)
        self.assertEqual(eligibility.reason_code, "strategy_eligibility_failed")
        self.assertIn("validation_expectancy_r", eligibility.metrics)

    def test_persisted_profile_is_source_of_truth_before_edge_snapshot(self) -> None:
        repository = _FakeEligibilityProfileRepository(
            _profile(eligible=False, reason_code="strategy_eligibility_failed", reason="Persisted profile failed.")
        )

        eligibility = ExecutionStrategyEligibilityService(
            require_walk_forward_edge=False,
            profile_repository=repository,
        ).evaluate(
            _edge(status="positive", sample_size=120, expectancy=0.4, profit_factor=2.0),
            profile_key=_profile_key(),
        )

        self.assertFalse(eligibility.eligible)
        self.assertEqual(eligibility.reason_code, "strategy_eligibility_failed")
        self.assertEqual(eligibility.reason, "Persisted profile failed.")
        self.assertEqual(eligibility.source, "historical_backtest")
        self.assertEqual(eligibility.metrics["sample_size"], 80)
        self.assertEqual(repository.lookups, [_profile_key()])

    def test_missing_persisted_profile_falls_back_to_signal_edge_snapshot(self) -> None:
        repository = _FakeEligibilityProfileRepository(None)

        eligibility = ExecutionStrategyEligibilityService(
            require_walk_forward_edge=False,
            profile_repository=repository,
        ).evaluate(
            _edge(status="positive", sample_size=120, expectancy=0.4, profit_factor=2.0),
            profile_key=_profile_key(),
        )

        self.assertTrue(eligibility.eligible)
        self.assertEqual(eligibility.reason_code, "strategy_eligibility_passed")
        self.assertEqual(eligibility.source, "outcome")

    def test_repository_lookup_failure_logs_warning_and_falls_back_to_edge(self) -> None:
        service = ExecutionStrategyEligibilityService(
            require_walk_forward_edge=False,
            profile_repository=_FailingEligibilityProfileRepository(),
        )

        with self.assertLogs("app.services.execution_strategy_registry", level="WARNING") as logs:
            eligibility = service.evaluate(
                _edge(status="positive", sample_size=120, expectancy=0.4, profit_factor=2.0),
                profile_key=_profile_key(),
            )

        self.assertTrue(eligibility.eligible)
        self.assertEqual(eligibility.reason_code, "strategy_eligibility_passed")
        self.assertIn("trend_pullback_continuation", logs.output[0])
        self.assertIn("bybit", logs.output[0])
        self.assertIn("BTCUSDT", logs.output[0])
        self.assertIn("1h", logs.output[0])
        self.assertIn("db unavailable", logs.output[0])


def _edge(
    *,
    status: str,
    sample_size: int,
    expectancy: float | None,
    profit_factor: float | None,
    source: str = "outcome",
    metadata: dict[str, object] | None = None,
) -> SignalEdgeSnapshot:
    return SignalEdgeSnapshot(
        status=status,
        sample_size=sample_size,
        min_sample_size=50,
        expectancy_after_costs_r=expectancy,
        profit_factor=profit_factor,
        confidence_score=0.8,
        source=source,
        metadata=metadata or {},
    )


def _profile_key() -> StrategyExecutionEligibilityProfileKey:
    return StrategyExecutionEligibilityProfileKey(
        strategy_code="trend_pullback_continuation",
        exchange="bybit",
        symbol_scope="BTCUSDT",
        timeframe="1h",
        market_regime="trend",
        score_bucket="80-89",
        direction="long",
    )


def _profile(
    *,
    eligible: bool,
    reason_code: str,
    reason: str,
) -> StrategyExecutionEligibilityProfileRecord:
    return StrategyExecutionEligibilityProfileRecord(
        id=None,
        strategy_code="trend_pullback_continuation",
        exchange="bybit",
        symbol_scope="BTCUSDT",
        timeframe="1h",
        market_regime="trend",
        score_bucket="80-89",
        direction="long",
        eligible=eligible,
        source="historical_backtest",
        metrics={"sample_size": 80, "profit_factor": 1.6},
        sample_size=80,
        expectancy_after_costs_r=0.18,
        profit_factor=1.6,
        entry_touch_rate=0.4,
        no_entry_rate=0.2,
        max_drawdown_r=3.0,
        run_ids=["run-1"],
        reason_code=reason_code,
        reason=reason,
        created_at=None,
        updated_at=None,
    )


class _FakeEligibilityProfileRepository:
    def __init__(self, profile: StrategyExecutionEligibilityProfileRecord | None) -> None:
        self._profile = profile
        self.lookups: list[StrategyExecutionEligibilityProfileKey] = []

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
        key = StrategyExecutionEligibilityProfileKey(
            strategy_code=strategy_code,
            exchange=exchange,
            symbol_scope=symbol_scope,
            timeframe=timeframe,
            market_regime=market_regime,
            score_bucket=score_bucket,
            direction=direction,
        )
        self.lookups.append(key)
        return self._profile


class _FailingEligibilityProfileRepository:
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
        _ = strategy_code, exchange, symbol_scope, timeframe, market_regime, score_bucket, direction
        raise RuntimeError("db unavailable")


if __name__ == "__main__":
    unittest.main()
