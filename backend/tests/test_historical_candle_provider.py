from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.historical_candle_provider import ClickHouseHistoricalCandleProvider


class _QueryResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def named_results(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _FakeClickHouseClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []
        self.parameters: list[dict[str, Any] | None] = []
        self.closed = False

    def query(self, query: str, parameters: dict[str, Any] | None = None) -> _QueryResult:
        self.queries.append(query)
        self.parameters.append(parameters)
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
        self.assertIn("GROUP BY", query)
        self.assertIn("exchange, symbol, ts", query)
        self.assertIn("ORDER BY ts ASC", query)


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


if __name__ == "__main__":
    unittest.main()
