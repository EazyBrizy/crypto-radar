from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from app.schemas.backtest import BacktestRunRequest
from app.services.backtest_service import BacktestService
from app.services.strategy_testing.schemas import (
    StrategyTestPair,
    StrategyTestReport,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
)


USER_ID = "usr_backtest_owner"


class BacktestServiceTest(unittest.TestCase):
    def test_run_backtest_enqueues_single_strategy_test_run(self) -> None:
        strategy_service = FakeStrategyTestingService()
        service = BacktestService(strategy_testing_service=strategy_service)
        request = _request()

        result = service.run_backtest(request)

        self.assertEqual(result.status, "queued")
        self.assertEqual(result.run_id, strategy_service.run_id)
        self.assertIsNone(result.result)
        self.assertEqual(result.test_type, "historical_backtest")
        self.assertEqual(result.canonical_endpoint, f"/api/v1/strategy-tests/runs/{strategy_service.run_id}")
        self.assertEqual(result.report_endpoint, f"/api/v1/strategy-tests/reports/{strategy_service.run_id}")
        self.assertEqual(len(strategy_service.enqueued), 1)
        enqueued = strategy_service.enqueued[0]
        self.assertEqual(enqueued.user_id, USER_ID)
        self.assertEqual(enqueued.test_type, "historical_backtest")
        self.assertEqual(enqueued.strategies, ["breakout"])
        self.assertEqual(enqueued.pairs, [StrategyTestPair(exchange="bybit", symbol="BTCUSDT")])
        self.assertEqual(enqueued.timeframes, ["1h"])
        self.assertEqual(enqueued.start_at, request.start_at)
        self.assertEqual(enqueued.end_at, request.end_at)
        self.assertEqual(enqueued.initial_capital, request.initial_capital)
        self.assertEqual(enqueued.fee_rate, request.fee_rate)
        self.assertEqual(enqueued.slippage_bps, request.slippage_bps)
        self.assertEqual(enqueued.mode, "research_virtual")
        self.assertEqual(enqueued.params["strategy_version"], "v2")
        self.assertEqual(enqueued.params["risk"], "standard")
        self.assertIn("legacy_backtests", enqueued.tags)

    def test_list_results_reads_strategy_testing_reports(self) -> None:
        strategy_service = FakeStrategyTestingService()
        service = BacktestService(strategy_testing_service=strategy_service)

        reports = service.list_results(user_id=USER_ID, limit=10)

        self.assertEqual(reports, strategy_service.reports)
        self.assertEqual(strategy_service.list_report_calls, [{"user_id": USER_ID, "limit": 10}])

    def test_invalid_period_is_rejected_before_runner(self) -> None:
        request = _request()
        strategy_service = FakeStrategyTestingService()
        service = BacktestService(strategy_testing_service=strategy_service)

        with self.assertRaisesRegex(ValueError, "end_at must be later"):
            service.run_backtest(request.model_copy(update={"end_at": request.start_at}))
        self.assertEqual(strategy_service.enqueued, [])


def _request() -> BacktestRunRequest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return BacktestRunRequest(
        user_id=USER_ID,
        strategy_code="breakout",
        strategy_version="v2",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        start_at=now,
        end_at=now + timedelta(days=7),
        initial_capital=Decimal("1000"),
        params={"risk": "standard"},
    )


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
        self.list_report_calls: list[dict[str, object]] = []

    def enqueue_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        self.enqueued.append(request)
        return StrategyTestRunResponse(
            run_id=self.run_id,
            status="queued",
            test_type=request.test_type,
            requested_matrix={
                **request.model_dump(mode="json"),
                "scenario_count": len(request.strategies) * len(request.pairs) * len(request.timeframes),
            },
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def list_reports(self, user_id: str, limit: int) -> list[StrategyTestReport]:
        self.list_report_calls.append({"user_id": user_id, "limit": limit})
        return self.reports


if __name__ == "__main__":
    unittest.main()
