from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import unittest

from app.schemas.ai import AIExplanationNotReadyResponse
from app.schemas.backtest import BacktestRunRequest
from app.schemas.billing import BillingProviderNotReadyResponse
from app.services.backtest_service import BacktestService
from app.services.strategy_testing.schemas import (
    StrategyTestReport,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
)


class AIBacktestBillingContractTest(unittest.TestCase):
    def test_ai_not_ready_response_points_to_postgres_table(self) -> None:
        response = AIExplanationNotReadyResponse(
            message="AI is stubbed",
            model_provider="stub",
            model_name="not-configured",
        )

        self.assertEqual(response.status, "not_implemented")
        self.assertEqual(response.storage_target, "signal_ai_explanations")
        self.assertTrue(response.orchestrator_required)

    def test_backtest_compatibility_uses_strategy_testing_contract(self) -> None:
        now = datetime.now(timezone.utc)
        strategy_service = FakeStrategyTestingService()
        service = BacktestService(strategy_testing_service=strategy_service)

        request = BacktestRunRequest(
            strategy_code="breakout",
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            start_at=now - timedelta(days=7),
            end_at=now,
            initial_capital=Decimal("1000"),
        )

        result = service.run_backtest(request)
        reports = service.list_results(user_id="demo_user", limit=1)

        self.assertEqual(result.status, "queued")
        self.assertEqual(result.run_id, strategy_service.run_id)
        self.assertEqual(result.report_endpoint, f"/api/v1/strategy-tests/reports/{strategy_service.run_id}")
        self.assertEqual(strategy_service.enqueued[0].test_type, "historical_backtest")
        self.assertEqual(reports, strategy_service.reports)

    def test_billing_not_ready_response_points_to_postgres_tables(self) -> None:
        response = BillingProviderNotReadyResponse(
            message="Billing provider is stubbed",
            provider="stub",
        )

        self.assertEqual(response.status, "not_implemented")
        self.assertIn("subscription_plans", response.storage_targets)
        self.assertIn("user_subscriptions", response.storage_targets)
        self.assertTrue(response.provider_integration_required)


class FakeStrategyTestingService:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.enqueued: list[StrategyTestRunRequest] = []
        self.reports = [
            StrategyTestReport(
                run_id=self.run_id,
                status="queued",
                mode="research_virtual",
                requested_matrix={"test_type": "historical_backtest"},
                generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        ]

    def enqueue_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        self.enqueued.append(request)
        return StrategyTestRunResponse(
            run_id=self.run_id,
            status="queued",
            test_type=request.test_type,
            requested_matrix={"test_type": request.test_type},
        )

    def list_reports(self, user_id: str, limit: int) -> list[StrategyTestReport]:
        _ = user_id, limit
        return self.reports


if __name__ == "__main__":
    unittest.main()
