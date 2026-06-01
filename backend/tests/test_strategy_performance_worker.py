import unittest
from datetime import date

from app.schemas.strategy_performance import StrategyPerformanceDaily
from app.workers.strategy_performance_worker import StrategyPerformanceWorker


DAY = date(2026, 1, 2)


class FakePerformanceService:
    def __init__(self) -> None:
        self.days: list[date] = []
        self.rows = [_row()]

    def aggregate_daily(self, *, day: date) -> list[StrategyPerformanceDaily]:
        self.days.append(day)
        return self.rows


class FailingPerformanceService:
    def aggregate_daily(self, *, day: date) -> list[StrategyPerformanceDaily]:
        raise RuntimeError("boom")


class StrategyPerformanceWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_aggregate_daily_runs_service_in_worker(self) -> None:
        service = FakePerformanceService()
        worker = StrategyPerformanceWorker(performance=service)  # type: ignore[arg-type]

        result = await worker.aggregate_daily(day=DAY)

        self.assertEqual(result, service.rows)
        self.assertEqual(service.days, [DAY])

    async def test_aggregate_daily_failure_returns_empty_list(self) -> None:
        worker = StrategyPerformanceWorker(performance=FailingPerformanceService())  # type: ignore[arg-type]

        result = await worker.aggregate_daily(day=DAY)

        self.assertEqual(result, [])


def _row() -> StrategyPerformanceDaily:
    return StrategyPerformanceDaily(
        date=DAY,
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        strategy="trend_pullback_continuation",
        strategy_version="v1",
        market_regime="bullish:strong:aligned",
        score_bucket="80-89",
        direction="long",
        sample_size=1,
        trades_count=1,
        signals_count=1,
        wins_count=1,
        losses_count=0,
        entry_touch_rate=1.0,
        winrate=1.0,
        tp1_rate=1.0,
        tp2_rate=0.0,
        stop_rate=0.0,
        invalidation_rate=0.0,
        avg_win_r=1.0,
        avg_loss_r=0.0,
        expectancy_r=1.0,
        profit_factor=None,
        max_drawdown_r=0.0,
        median_bars_to_entry=1.0,
        median_bars_to_outcome=3.0,
        avg_mfe_r=1.2,
        avg_mae_r=-0.2,
        fees_bps=2.0,
        slippage_bps=3.0,
    )


if __name__ == "__main__":
    unittest.main()
