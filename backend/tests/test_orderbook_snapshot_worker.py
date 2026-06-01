import asyncio
import unittest

from app.exchanges.bybit import BybitOrderBookSnapshot
from app.workers.orderbook_snapshot_worker import (
    OrderbookSnapshotWorker,
    build_orderbook_snapshot,
)


class FakePersistence:
    def __init__(self) -> None:
        self.snapshots: list[tuple[object, int]] = []

    def persist_orderbook_snapshot(self, snapshot, *, ttl_seconds: int) -> None:
        self.snapshots.append((snapshot, ttl_seconds))


class OrderbookSnapshotWorkerTest(unittest.TestCase):
    def test_depth_calculation_uses_best_price_bands(self) -> None:
        snapshot = build_orderbook_snapshot(
            BybitOrderBookSnapshot(
                category="linear",
                symbol="BTCUSDT",
                bids=[(100.0, 1.0), (99.95, 2.0), (99.4, 3.0), (98.0, 4.0)],
                asks=[(100.1, 1.0), (100.15, 2.0), (100.8, 3.0), (102.0, 4.0)],
                raw_payload={},
                timestamp_ms=1_779_796_800_123,
            )
        )

        self.assertEqual([level.price for level in snapshot.bids], [100.0, 99.95, 99.4, 98.0])
        self.assertEqual([level.price for level in snapshot.asks], [100.1, 100.15, 100.8, 102.0])
        self.assertAlmostEqual(snapshot.spread_bps or 0, (100.1 - 100.0) / 100.05 * 10_000)
        self.assertAlmostEqual(snapshot.bid_depth_usd_0_1_pct, 100.0 * 1.0 + 99.95 * 2.0)
        self.assertAlmostEqual(snapshot.ask_depth_usd_0_1_pct, 100.1 * 1.0 + 100.15 * 2.0)
        self.assertAlmostEqual(snapshot.bid_depth_usd_0_5_pct, 100.0 * 1.0 + 99.95 * 2.0)
        self.assertAlmostEqual(snapshot.ask_depth_usd_0_5_pct, 100.1 * 1.0 + 100.15 * 2.0)
        self.assertAlmostEqual(snapshot.bid_depth_usd_1_pct, 100.0 * 1.0 + 99.95 * 2.0 + 99.4 * 3.0)
        self.assertAlmostEqual(snapshot.ask_depth_usd_1_pct, 100.1 * 1.0 + 100.15 * 2.0 + 100.8 * 3.0)

    def test_sync_once_fetches_watchlist_and_persists_hot_snapshot(self) -> None:
        persistence = FakePersistence()

        def fake_fetcher(**kwargs):
            self.assertEqual(kwargs["category"], "linear")
            self.assertEqual(kwargs["symbol"], "BTCUSDT")
            self.assertEqual(kwargs["limit"], 25)
            return BybitOrderBookSnapshot(
                category="linear",
                symbol="BTCUSDT",
                bids=[(100.0, 1.0)],
                asks=[(100.1, 2.0)],
                raw_payload={},
                timestamp_ms=1_779_796_800_123,
            )

        worker = OrderbookSnapshotWorker(
            orderbook_fetcher=fake_fetcher,
            persistence=persistence,  # type: ignore[arg-type]
            symbols_provider=lambda: ["btcusdt"],
            categories_provider=lambda: ["linear"],
            interval_seconds=1,
            ttl_seconds=15,
            limit=25,
        )

        result = asyncio.run(worker.sync_once())

        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(persistence.snapshots), 1)
        snapshot, ttl = persistence.snapshots[0]
        self.assertEqual(ttl, 15)
        self.assertEqual(snapshot.source, "bybit_v5_orderbook")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.ask_depth_usd_0_5_pct, 100.1 * 2.0)


if __name__ == "__main__":
    unittest.main()
