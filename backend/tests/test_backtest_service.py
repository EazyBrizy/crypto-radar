from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from uuid import UUID, uuid4

from app.schemas.backtest import BacktestResultResponse, BacktestRunRequest, BacktestRunResult
from app.services.backtest_service import BacktestNotReadyError, BacktestService


USER_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd524")


class FakeResultStore:
    def __init__(self) -> None:
        self.results: list[BacktestResultResponse] = []

    def ensure_schema(self) -> None:
        return None

    def write_result(self, result: BacktestResultResponse) -> None:
        self.results.append(result)

    def list_results(self, *, user_id: UUID | None = None, limit: int = 50) -> list[BacktestResultResponse]:
        values = self.results
        if user_id is not None:
            values = [result for result in values if result.user_id == user_id]
        return values[:limit]


class FakeRunner:
    def __init__(self, result: BacktestRunResult | None = None) -> None:
        self.result = result
        self.requests: list[BacktestRunRequest] = []

    def run(self, request: BacktestRunRequest) -> BacktestRunResult:
        self.requests.append(request)
        return self.result or BacktestRunResult(status="completed", result=_result(request))


class FailingRunner:
    def run(self, request: BacktestRunRequest) -> BacktestRunResult:
        raise ValueError("no_historical_data: no closed candles were found")


class BacktestServiceTest(unittest.TestCase):
    def test_configured_runner_runs_and_persists_completed_result(self) -> None:
        store = FakeResultStore()
        runner = FakeRunner()
        service = BacktestService(result_store=store, runner=runner)  # type: ignore[arg-type]
        request = _request()

        result = service.run_backtest(request)

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(runner.requests), 1)
        self.assertEqual(len(store.results), 1)
        self.assertEqual(store.results[0].strategy_code, "breakout")

    def test_without_runner_keeps_not_ready_contract(self) -> None:
        service = BacktestService(result_store=FakeResultStore())  # type: ignore[arg-type]

        with self.assertRaises(BacktestNotReadyError):
            service.run_backtest(_request())

    def test_runner_data_errors_are_explicit_value_errors(self) -> None:
        service = BacktestService(
            result_store=FakeResultStore(),  # type: ignore[arg-type]
            runner=FailingRunner(),  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(ValueError, "no_historical_data"):
            service.run_backtest(_request())

    def test_invalid_period_is_rejected_before_runner(self) -> None:
        request = _request()
        service = BacktestService(
            result_store=FakeResultStore(),  # type: ignore[arg-type]
            runner=FakeRunner(),  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(ValueError, "end_at must be later"):
            service.run_backtest(request.model_copy(update={"end_at": request.start_at}))


def _request() -> BacktestRunRequest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return BacktestRunRequest(
        user_id=str(USER_ID),
        strategy_code="breakout",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        start_at=now,
        end_at=now + timedelta(days=7),
        initial_capital=Decimal("1000"),
    )


def _result(request: BacktestRunRequest) -> BacktestResultResponse:
    return BacktestResultResponse(
        run_id=uuid4(),
        user_id=UUID(request.user_id),
        strategy_code=request.strategy_code,
        strategy_version=request.strategy_version or "test",
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_at=request.start_at,
        end_at=request.end_at,
        initial_capital=request.initial_capital,
        final_equity=request.initial_capital,
        pnl=Decimal("0"),
        pnl_pct=0.0,
        max_drawdown_pct=0.0,
        trades_count=0,
        wins_count=0,
        losses_count=0,
        metrics={"trades_count": 0},
        equity_curve=[],
        created_at=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    unittest.main()
