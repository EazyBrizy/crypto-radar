import unittest

from app.schemas.candle import OHLCVCandle
from app.schemas.market import MarketData
from app.services.candle_service import CandleService


class CandleServiceContractTest(unittest.TestCase):
    def test_list_candles_deduplicates_seeded_history_and_open_candle(self) -> None:
        service = CandleService(timeframes=["1m"])
        open_time = 1_779_796_800_000

        service.seed_history(
            [
                OHLCVCandle(
                    exchange="bybit",
                    symbol="ETHUSDT",
                    timeframe="1m",
                    open_time=open_time,
                    close_time=open_time + 59_999,
                    open=2_100,
                    high=2_120,
                    low=2_090,
                    close=2_110,
                    volume=100,
                    trades=10,
                    is_closed=True,
                )
            ]
        )
        service.update_from_tick(
            MarketData(
                exchange="bybit",
                symbol="ETHUSDT",
                timestamp=open_time + 1_000,
                price=2_115,
                volume=1,
            )
        )

        candles = service.list_candles(
            exchange="bybit",
            symbol="ETHUSDT",
            timeframe="1m",
            include_open=True,
        )

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].open_time, open_time)
        self.assertFalse(candles[0].is_closed)
        self.assertEqual(candles[0].close, 2_115)


if __name__ == "__main__":
    unittest.main()
