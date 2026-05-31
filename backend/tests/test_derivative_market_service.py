import unittest
from datetime import datetime, timezone

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
            source="bybit_v5_tickers",
            fetched_at=datetime.now(timezone.utc),
        )

        service._write_hot_snapshot(snapshot)  # noqa: SLF001
        loaded = service.hot_snapshot(exchange="bybit", symbol="BTC/USDT:PERP")

        self.assertIn(hot_snapshot_key(exchange="bybit", symbol="BTCUSDT"), redis.values)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.symbol if loaded else None, "BTCUSDT")
        self.assertEqual(loaded.funding_rate if loaded else None, 0.001)


if __name__ == "__main__":
    unittest.main()
