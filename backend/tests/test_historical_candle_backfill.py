from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from app.schemas.candle import OHLCVCandle
from app.services.historical_candle_provider import (
    BackfillingHistoricalCandleProvider,
    InMemoryHistoricalCandleProvider,
)


class HistoricalCandleBackfillTest(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_fetches_persists_and_reuses_bybit_candles(self) -> None:
        provider = InMemoryHistoricalCandleProvider([])
        fetcher = _RecordingFetcher([
            _candle(open_time=1780315200000, close=101.0),
            _candle(open_time=1780316100000, close=102.0),
        ])
        persistence = _InMemoryPersistence(provider)
        backfilling = BackfillingHistoricalCandleProvider(
            provider,
            range_fetcher=fetcher,
            persistence_service=persistence,
        )
        params = {
            "exchange": "bybit",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "start_at": datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            "end_at": datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
        }

        first = await backfilling.load_candles(**params)
        second = await backfilling.load_candles(**params)

        self.assertEqual([candle.close for candle in first], [101.0, 102.0])
        self.assertEqual([candle.close for candle in second], [101.0, 102.0])
        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual(len(persistence.batches), 1)

    async def test_backfill_logs_cache_miss_and_persisted_rows(self) -> None:
        provider = InMemoryHistoricalCandleProvider([])
        fetcher = _RecordingFetcher([
            _candle(open_time=1780315200000, close=101.0),
            _candle(open_time=1780316100000, close=102.0),
        ])
        backfilling = BackfillingHistoricalCandleProvider(
            provider,
            range_fetcher=fetcher,
            persistence_service=_InMemoryPersistence(provider),
        )

        with self.assertLogs("app.services.historical_candle_provider", level="INFO") as logs:
            candles = await backfilling.load_candles(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="15m",
                start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                end_at=datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
            )

        self.assertEqual(len(candles), 2)
        log_output = "\n".join(logs.output)
        self.assertIn("Historical candle cache miss exchange=bybit symbol=BTCUSDT timeframe=15m", log_output)
        self.assertIn("Historical candle backfill persisted exchange=bybit symbol=BTCUSDT timeframe=15m", log_output)
        self.assertIn("rows_written=2", log_output)

    async def test_backfill_does_not_fetch_unsupported_exchange(self) -> None:
        fetcher = _RecordingFetcher([_candle(open_time=1780315200000, close=101.0)])
        backfilling = BackfillingHistoricalCandleProvider(
            InMemoryHistoricalCandleProvider([]),
            range_fetcher=fetcher,
            persistence_service=_RecordingPersistence(),
        )

        candles = await backfilling.load_candles(
            exchange="okx",
            symbol="BTCUSDT",
            timeframe="15m",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(candles, [])
        self.assertEqual(fetcher.calls, [])


def _candle(*, open_time: int, close: float) -> OHLCVCandle:
    return OHLCVCandle(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=open_time,
        close_time=open_time + 899_999,
        open=100.0,
        high=105.0,
        low=95.0,
        close=close,
        volume=123.45,
        trades=10,
        is_closed=True,
    )


class _RecordingFetcher:
    def __init__(self, candles: list[OHLCVCandle]) -> None:
        self._candles = list(candles)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> list[OHLCVCandle]:
        self.calls.append(dict(kwargs))
        return list(self._candles)


class _RecordingPersistence:
    def __init__(self) -> None:
        self.batches: list[list[OHLCVCandle]] = []

    def persist_candles(self, candles: list[OHLCVCandle]) -> int:
        self.batches.append(list(candles))
        return len(candles)


class _InMemoryPersistence(_RecordingPersistence):
    def __init__(self, provider: InMemoryHistoricalCandleProvider) -> None:
        super().__init__()
        self._provider = provider
        self._candles: list[OHLCVCandle] = []

    def persist_candles(self, candles: list[OHLCVCandle]) -> int:
        rows_written = super().persist_candles(candles)
        self._candles.extend(candles)
        self._provider.set_candles(self._candles)
        return rows_written


if __name__ == "__main__":
    unittest.main()
