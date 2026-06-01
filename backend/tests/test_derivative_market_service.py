import unittest
from datetime import datetime, timezone
from typing import Any

from app.exchanges.bybit import BybitTicker
from app.services.derivative_market import (
    DerivativeMarketSnapshot,
    DerivativeMarketSnapshotService,
    hot_snapshot_key,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, tuple[int, str]] = {}

    def setex(self, name: str, time: int, value: str) -> None:
        self.values[name] = (time, value)

    def get(self, name: str):
        item = self.values.get(name)
        return None if item is None else item[1]


class DerivativeMarketSnapshotServiceTest(unittest.TestCase):
    def test_hot_snapshot_roundtrip_uses_normalized_symbol_key(self) -> None:
        redis = FakeRedis()
        service = DerivativeMarketSnapshotService(
            redis_client_factory=lambda: redis,  # type: ignore[arg-type]
            ttl_seconds=120,
        )
        snapshot = DerivativeMarketSnapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            category="linear",
            funding_rate=0.001,
            mark_price=100.0,
            open_interest=1000.0,
            open_interest_value=100_000.0,
            oi_change=0.1,
            source="bybit_v5_tickers",
            fetched_at=datetime.now(timezone.utc),
        )

        service._write_hot_snapshot(snapshot)  # noqa: SLF001
        loaded = service.hot_snapshot(exchange="bybit", symbol="BTC/USDT:PERP")

        self.assertIn(hot_snapshot_key(exchange="bybit", symbol="BTCUSDT"), redis.values)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.symbol if loaded else None, "BTCUSDT")
        self.assertEqual(loaded.funding_rate if loaded else None, 0.001)
        self.assertEqual(loaded.open_interest if loaded else None, 1000.0)
        self.assertEqual(loaded.open_interest_value if loaded else None, 100_000.0)
        self.assertEqual(loaded.oi_change if loaded else None, 0.1)

    def test_refresh_bybit_symbol_calculates_oi_change_from_previous_hot_snapshot(self) -> None:
        redis = FakeRedis()
        service = _NoopPersistDerivativeMarketSnapshotService(
            ticker_fetcher=lambda **_: [
                BybitTicker(
                    category="linear",
                    symbol="BTCUSDT",
                    bid1_price=None,
                    ask1_price=None,
                    mark_price=120.0,
                    funding_rate=0.0002,
                    volume_24h=None,
                    turnover_24h=None,
                    raw_payload={"openInterest": "120"},
                    open_interest=120.0,
                    open_interest_value=14_400.0,
                )
            ],
            redis_client_factory=lambda: redis,  # type: ignore[arg-type]
            ttl_seconds=120,
        )
        previous = DerivativeMarketSnapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            category="linear",
            open_interest=100.0,
            fetched_at=datetime.now(timezone.utc),
        )
        service._write_hot_snapshot(previous)  # noqa: SLF001

        snapshot = service.refresh_bybit_symbol(symbol="BTCUSDT")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.open_interest if snapshot else None, 120.0)
        self.assertEqual(snapshot.open_interest_value if snapshot else None, 14_400.0)
        self.assertAlmostEqual(snapshot.oi_change if snapshot else 0.0, 0.2)
        loaded = service.hot_snapshot(exchange="bybit", symbol="BTCUSDT")
        self.assertAlmostEqual(loaded.oi_change if loaded else 0.0, 0.2)


class _NoopPersistDerivativeMarketSnapshotService(DerivativeMarketSnapshotService):
    def _persist_snapshot(self, snapshot: DerivativeMarketSnapshot, *, raw_payload: dict[str, Any]) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
