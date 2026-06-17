from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v1.backtests import get_backtest_service
from app.main import app
from app.schemas.backtest import BacktestRunRequest, BacktestRunResult
from app.services.strategy_testing.schemas import (
    StrategyTestReport,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
)


class BacktestsApiContractTest(unittest.TestCase):
    def test_run_backtest_is_strategy_testing_compatibility_wrapper(self) -> None:
        service = _RecordingBacktestService()
        app.dependency_overrides[get_backtest_service] = lambda: service
        client = TestClient(app)

        try:
            response = client.post(
                "/api/v1/backtests/run",
                json={**_payload(), "user_id": "body_user"},
                headers={"x-auth-user-id": "usr_current"},
            )
        finally:
            app.dependency_overrides.pop(get_backtest_service, None)

        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["run_id"], str(service.run_id))
        self.assertEqual(data["test_type"], "historical_backtest")
        self.assertIsNone(data["result"])
        self.assertEqual(data["report_endpoint"], f"/api/v1/strategy-tests/reports/{service.run_id}")
        self.assertEqual(len(service.run_requests), 1)
        self.assertEqual(service.run_requests[0].user_id, "usr_current")

    def test_list_backtest_results_reads_strategy_testing_reports(self) -> None:
        service = _RecordingBacktestService()
        app.dependency_overrides[get_backtest_service] = lambda: service
        client = TestClient(app)

        try:
            response = client.get(
                "/api/v1/backtests/results?user_id=usr_current&limit=5",
                headers={"x-auth-user-id": "usr_current"},
            )
        finally:
            app.dependency_overrides.pop(get_backtest_service, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["run_id"], str(service.run_id))
        self.assertEqual(response.json()[0]["requested_matrix"]["test_type"], "historical_backtest")
        self.assertEqual(service.list_results_calls, [{"user_id": "usr_current", "limit": 5}])


class _RecordingBacktestService:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.run_requests: list[BacktestRunRequest] = []
        self.list_results_calls: list[dict[str, Any]] = []
        self.report = StrategyTestReport(
            run_id=self.run_id,
            status="queued",
            mode="research_virtual",
            requested_matrix={"test_type": "historical_backtest"},
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def run_backtest(self, request: BacktestRunRequest) -> BacktestRunResult:
        self.run_requests.append(request)
        return BacktestRunResult(
            status="queued",
            run_id=self.run_id,
            test_type="historical_backtest",
            canonical_endpoint=f"/api/v1/strategy-tests/runs/{self.run_id}",
            report_endpoint=f"/api/v1/strategy-tests/reports/{self.run_id}",
            requested_matrix={
                "user_id": request.user_id,
                "test_type": "historical_backtest",
                "strategies": [request.strategy_code],
            },
        )

    def list_results(self, *, user_id: str, limit: int) -> list[StrategyTestReport]:
        self.list_results_calls.append({"user_id": user_id, "limit": limit})
        return [self.report]


def _payload() -> dict[str, object]:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
        "strategy_code": "trend_pullback_continuation",
        "strategy_version": "v1",
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "start_at": now.isoformat(),
        "end_at": (now + timedelta(days=7)).isoformat(),
        "initial_capital": str(Decimal("1000")),
        "fee_rate": str(Decimal("0.001")),
        "slippage_bps": str(Decimal("1.5")),
        "params": {"risk": "standard"},
    }


if __name__ == "__main__":
    unittest.main()
