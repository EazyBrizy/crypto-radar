from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
import unittest

from app.schemas.ai import AIExplanationNotReadyResponse
from app.schemas.backtest import BacktestRunRequest
from app.schemas.billing import BillingProviderNotReadyResponse
from app.services.backtest_service import (
    BACKTEST_RESULTS_DDL,
    BacktestNotReadyError,
    BacktestService,
    ClickHouseBacktestResultStore,
)


USER_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd524")


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.inserts: list[tuple[str, list[list[object]], list[str]]] = []

    def command(self, command: str) -> None:
        self.commands.append(command)

    def insert(self, table: str, data: list[list[object]], column_names: list[str]) -> None:
        self.inserts.append((table, data, column_names))


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

    def test_backtest_without_runner_returns_clickhouse_target_contract(self) -> None:
        now = datetime.now(timezone.utc)
        service = BacktestService(result_store=ClickHouseBacktestResultStore(lambda: FakeClickHouseClient()))

        request = BacktestRunRequest(
            strategy_code="breakout",
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            start_at=now - timedelta(days=7),
            end_at=now,
            initial_capital=Decimal("1000"),
        )

        with self.assertRaises(BacktestNotReadyError) as ctx:
            service.run_backtest(request)

        response = ctx.exception.response
        self.assertEqual(response.status, "not_implemented")
        self.assertTrue(response.worker_required)
        self.assertIn("analytics.backtest_results", response.analytics_targets)
        self.assertIn("market.ohlcv_1h", response.data_sources)
        self.assertEqual(response.details["strategy_code"], "breakout")

    def test_backtest_result_store_can_ensure_clickhouse_schema(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseBacktestResultStore(lambda: client)

        store.ensure_schema()

        self.assertEqual(client.commands, [BACKTEST_RESULTS_DDL])
        self.assertIn("analytics.backtest_results", client.commands[0])
        self.assertIn("MergeTree", client.commands[0])

    def test_billing_not_ready_response_points_to_postgres_tables(self) -> None:
        response = BillingProviderNotReadyResponse(
            message="Billing provider is stubbed",
            provider="stub",
        )

        self.assertEqual(response.status, "not_implemented")
        self.assertIn("subscription_plans", response.storage_targets)
        self.assertIn("user_subscriptions", response.storage_targets)
        self.assertTrue(response.provider_integration_required)


if __name__ == "__main__":
    unittest.main()
