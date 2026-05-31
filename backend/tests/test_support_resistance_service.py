import unittest

from app.schemas.candle import OHLCVCandle
from app.services.support_resistance import SupportResistanceService


class SupportResistanceServiceTest(unittest.TestCase):
    def test_build_snapshot_clusters_extrema_and_finds_nearest_obstacle(self) -> None:
        candles = [_candle(index) for index in range(40)]
        service = SupportResistanceService()

        snapshot = service.build_snapshot(candles, atr=2.0)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        resistance = snapshot.nearest_obstacle(direction="long", entry=108.0)
        support = snapshot.nearest_obstacle(direction="short", entry=92.0)

        self.assertIsNotNone(resistance)
        self.assertIsNotNone(support)
        assert resistance is not None
        assert support is not None
        self.assertEqual(resistance.kind, "resistance")
        self.assertAlmostEqual(resistance.price, 110.0)
        self.assertGreaterEqual(resistance.retest_count, 3)
        self.assertEqual(support.kind, "support")
        self.assertAlmostEqual(support.price, 90.0)


def _candle(index: int) -> OHLCVCandle:
    high = 101.0
    low = 99.0
    close = 100.0
    volume = 100.0
    if index in {8, 16, 24, 32}:
        high = 110.0
        close = 104.0
        volume = 220.0
    if index in {12, 20, 28}:
        low = 90.0
        close = 96.0
        volume = 180.0
    return OHLCVCandle(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=index * 3_600_000,
        close_time=(index + 1) * 3_600_000 - 1,
        open=100.0,
        high=high,
        low=low,
        close=close,
        volume=volume,
        trades=10,
        is_closed=True,
    )


if __name__ == "__main__":
    unittest.main()
