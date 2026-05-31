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

    def test_candle_features_use_wilder_adx_stats(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candles = []
        price = 100.0
        for index in range(80):
            if index < 40:
                price += 0.3 if index % 2 == 0 else -0.25
            else:
                price += 0.45 + index * 0.01
            candles.append(_candle(start + index * 60_000, high=price + 0.8, low=price - 0.6, close=price, volume=10))

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertIsNotNone(features.adx)
        self.assertGreaterEqual(features.adx_rising_bars, 0)
        self.assertIsNotNone(features.adx_slope_5)

    def test_candle_features_include_ema200_chop_metrics(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candles = [
            _candle(
                start + index * 60_000,
                high=101.5 if index % 6 < 3 else 100.5,
                low=99.5 if index % 6 < 3 else 98.5,
                close=101.0 if index % 6 < 3 else 99.0,
                volume=10,
            )
            for index in range(260)
        ]

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertGreaterEqual(features.ema_200_cross_count_50, 3)
        self.assertIsNotNone(features.ema_200_near_ratio_50)
        self.assertIsNotNone(features.ema_200_chop_score)

    def test_candle_features_include_squeeze_compression_metrics(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candles = []
        price = 100.0
        for index in range(90):
            width = 3.0 if index < 45 else 1.0
            price += 0.05
            candles.append(
                _candle(
                    start + index * 60_000,
                    high=price + width,
                    low=price - width,
                    close=price,
                    volume=10,
                )
            )

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertIsNotNone(features.atr_sma_50)
        self.assertIsNotNone(features.range_20)
        self.assertIsNotNone(features.range_50_average)
        self.assertIsNotNone(features.range_20_atr)
        self.assertLess(features.range_20 or 0, features.range_50_average or 0)


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
