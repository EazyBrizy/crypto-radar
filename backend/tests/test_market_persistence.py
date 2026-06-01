import json
import unittest

from app.schemas.market import OrderBookLevel, OrderBookSnapshot
from app.services.market_persistence import MarketDataPersistenceService


class FakeClickHouseClient:
    def insert(self, table: str, data: list[list[object]], column_names: list[str]) -> None:
        return None


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, tuple[int, str]] = {}

    def setex(self, name: str, time: int, value: str) -> None:
        self.values[name] = (time, value)


class MarketPersistenceOrderbookTest(unittest.TestCase):
    def test_redis_snapshot_serialization_uses_normalized_l2_payload(self) -> None:
        redis = FakeRedisClient()
        service = MarketDataPersistenceService(
            clickhouse_client_factory=FakeClickHouseClient,
            redis_client_factory=lambda: redis,
        )
        snapshot = OrderBookSnapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            category="linear",
            bids=[OrderBookLevel(price=100, quantity=1.5)],
            asks=[OrderBookLevel(price=100.1, quantity=2)],
            timestamp=1_779_796_800_123,
            ts="2026-05-25T12:00:00Z",
            source="bybit_v5_orderbook",
            spread_bps=9.995,
            bid_depth_usd_0_1_pct=150,
            ask_depth_usd_0_1_pct=200.2,
            bid_depth_usd_0_5_pct=150,
            ask_depth_usd_0_5_pct=200.2,
            bid_depth_usd_1_pct=150,
            ask_depth_usd_1_pct=200.2,
        )

        service.persist_orderbook_snapshot(snapshot, ttl_seconds=15)

        ttl, payload_raw = redis.values["orderbook:bybit:BTCUSDT"]
        payload = json.loads(payload_raw)
        self.assertEqual(ttl, 15)
        self.assertEqual(payload["source"], "bybit_v5_orderbook")
        self.assertEqual(payload["bids"], [{"price": 100.0, "quantity": 1.5}])
        self.assertEqual(payload["asks"], [{"price": 100.1, "quantity": 2.0}])
        self.assertEqual(payload["spread_bps"], 9.995)


if __name__ == "__main__":
    unittest.main()
