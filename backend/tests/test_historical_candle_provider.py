from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.schemas.candle import OHLCVCandle
from app.services.historical_candle_provider import (
    ClickHouseHistoricalCandleProvider,
    InMemoryHistoricalCandleProvider,
)


class _QueryResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def named_results(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _GeneratorQueryResult(_QueryResult):
    def named_results(self) -> Any:
        return (row for row in self._rows)


class _FakeClickHouseClient:
    def __init__(self, rows: list[dict[str, Any]], *, generator_results: bool = False) -> None:
        self.rows = rows
        self.generator_results = generator_results
        self.queries: list[str] = []
        self.parameters: list[dict[str, Any] | None] = []
        self.closed = False

    def query(self, query: str, parameters: dict[str, Any] | None = None) -> _QueryResult:
        self.queries.append(query)
        self.parameters.append(parameters)
        if self.generator_results:
            return _GeneratorQueryResult(self.rows)
        return _QueryResult(self.rows)

    def close(self) -> None:
        self.closed = True


class ClickHouseHistoricalCandleProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_load_candles_dedupes_duplicate_timestamp_rows(self) -> None:
        ts = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        first_created = datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc)
        second_created = datetime(2026, 6, 1, 12, 2, tzinfo=timezone.utc)
        client = _FakeClickHouseClient(
            [
                _row(ts=ts, close="101", created_at=first_created, trades_count=10),
                _row(ts=ts, close="102", created_at=second_created, trades_count=11),
                _row(
                    ts=datetime(2026, 6, 1, 12, 15, tzinfo=timezone.utc),
                    close="103",
                    created_at=first_created,
                    trades_count=12,
                ),
            ]
        )
        provider = ClickHouseHistoricalCandleProvider(lambda: client)

        candles = await provider.load_candles(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="15m",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 12, 45, tzinfo=timezone.utc),
        )

        self.assertEqual([candle.open_time for candle in candles], [1780315200000, 1780316100000])
        self.assertEqual(candles[0].close, 102.0)
        self.assertEqual(candles[0].trades, 11)
        self.assertTrue(all(candle.is_closed for candle in candles))
        self.assertTrue(client.closed)

    async def test_load_candles_query_uses_clickhouse_argmax_grouping(self) -> None:
        client = _FakeClickHouseClient([])
        provider = ClickHouseHistoricalCandleProvider(lambda: client)

        await provider.load_candles(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="15m",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
        )

        query = client.queries[0]
        self.assertIn("argMax(open", query)
        self.assertIn("argMax(high", query)
        self.assertIn("argMax(low", query)
        self.assertIn("argMax(close", query)
        self.assertIn("argMax(volume_base", query)
        self.assertIn("argMax(trades_count", query)
        self.assertIn("tuple(created_at", query)
        self.assertIn("max(created_at) AS latest_created_at", query)
        self.assertNotIn("AS created_at", query)
        self.assertIn("GROUP BY", query)
        self.assertIn("exchange, symbol, ts", query)
        self.assertIn("ORDER BY ts ASC", query)

    async def test_count_candles_uses_deduped_timestamp_count_query(self) -> None:
        client = _FakeClickHouseClient([{"candles_count": 2}])
        provider = ClickHouseHistoricalCandleProvider(lambda: client)

        count = await provider.count_candles(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="15m",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
        )

        query = client.queries[0]
        self.assertEqual(count, 2)
        self.assertIn("SELECT count()", query)
        self.assertIn("FROM (", query)
        self.assertIn("SELECT ts", query)
        self.assertIn("GROUP BY ts", query)

    async def test_count_candles_accepts_generator_named_results(self) -> None:
        client = _FakeClickHouseClient([{"candles_count": 2}], generator_results=True)
        provider = ClickHouseHistoricalCandleProvider(lambda: client)

        count = await provider.count_candles(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="15m",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(count, 2)

    async def test_in_memory_count_candles_counts_unique_closed_timestamps(self) -> None:
        first = _candle(open_time=1780315200000, close=101.0)
        duplicate = _candle(open_time=1780315200000, close=102.0)
        second = _candle(open_time=1780316100000, close=103.0)
        open_preview = _candle(open_time=1780317000000, close=104.0, is_closed=False)
        provider = InMemoryHistoricalCandleProvider([first, duplicate, second, open_preview])

        count = await provider.count_candles(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="15m",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 12, 45, tzinfo=timezone.utc),
        )

        self.assertEqual(count, 2)


def _row(
    *,
    ts: datetime,
    close: str,
    created_at: datetime,
    trades_count: int,
) -> dict[str, Any]:
    return {
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "ts": ts,
        "open": Decimal("100"),
        "high": Decimal("105"),
        "low": Decimal("95"),
        "close": Decimal(close),
        "volume_base": Decimal("123.45"),
        "trades_count": trades_count,
        "created_at": created_at,
    }


def _candle(
    *,
    open_time: int,
    close: float,
    is_closed: bool = True,
) -> OHLCVCandle:
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
        is_closed=is_closed,
    )


if __name__ == "__main__":
    unittest.main()
