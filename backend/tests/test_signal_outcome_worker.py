import unittest

from app.schemas.candle import OHLCVCandle
from app.workers.signal_outcome_worker import SignalOutcomeWorker


class _FakeOutcomeService:
    def __init__(self) -> None:
        self.candles: list[OHLCVCandle] = []

    def update_open_outcomes_for_candle(self, candle: OHLCVCandle) -> list[str]:
        self.candles.append(candle)
        return ["updated"]


class SignalOutcomeWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_closed_candle_updates_open_outcomes(self) -> None:
        service = _FakeOutcomeService()
        worker = SignalOutcomeWorker(outcomes=service)
        candle = _candle(is_closed=True)

        result = await worker.process_closed_candle(candle)

        self.assertEqual(result, ["updated"])
        self.assertEqual(service.candles, [candle])

    async def test_open_candle_is_ignored(self) -> None:
        service = _FakeOutcomeService()
        worker = SignalOutcomeWorker(outcomes=service)

        result = await worker.process_closed_candle(_candle(is_closed=False))

        self.assertEqual(result, [])
        self.assertEqual(service.candles, [])


def _candle(*, is_closed: bool) -> OHLCVCandle:
    return OHLCVCandle(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=1_779_795_900_000,
        close_time=1_779_796_800_000,
        open=100,
        high=101,
        low=99,
        close=100.5,
        volume=100,
        trades=10,
        is_closed=is_closed,
    )


if __name__ == "__main__":
    unittest.main()
