import unittest
from datetime import datetime, timezone

from app.schemas.candle import OHLCVCandle
from app.services.feature_engine import FeatureEngine


class FeatureEngineTest(unittest.TestCase):
    def test_intraday_candle_features_include_session_vwap(self) -> None:
        engine = FeatureEngine()
        day = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        previous_day = day - 24 * 60 * 60 * 1000
        candles = [
            _candle(previous_day, high=120, low=90, close=100, volume=100),
            _candle(day, high=102, low=98, close=100, volume=10),
            _candle(day + 60_000, high=112, low=108, close=110, volume=30),
        ]

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertAlmostEqual(features.vwap or 0.0, 107.5)

    def test_daily_candle_features_skip_intraday_vwap(self) -> None:
        engine = FeatureEngine()
        day = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        features = engine.process_candles([
            _candle(day, timeframe="1d", high=102, low=98, close=100, volume=10),
        ])

        self.assertIsNotNone(features)
        self.assertIsNone(features.vwap)


def _candle(
    open_time: int,
    *,
    timeframe: str = "1m",
    high: float,
    low: float,
    close: float,
    volume: float,
) -> OHLCVCandle:
    return OHLCVCandle(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + 59_999,
        open=(high + low) / 2,
        high=high,
        low=low,
        close=close,
        volume=volume,
        trades=10,
        is_closed=True,
    )


if __name__ == "__main__":
    unittest.main()
