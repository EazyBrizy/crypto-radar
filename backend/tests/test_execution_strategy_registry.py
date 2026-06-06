import unittest

from app.schemas.signal import SignalEdgeSnapshot
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


if __name__ == "__main__":
    unittest.main()
