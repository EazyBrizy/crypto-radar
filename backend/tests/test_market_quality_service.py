import unittest

from app.exchanges.bybit import BybitTicker
from app.services.market_quality import MarketQualityService


class MarketQualityServiceTest(unittest.TestCase):
    def test_snapshot_uses_bybit_turnover_and_spread(self) -> None:
        service = MarketQualityService(
            ticker_fetcher=lambda **_: [
                BybitTicker(
                    category="linear",
                    symbol="BTCUSDT",
                    bid1_price=99.0,
                    ask1_price=101.0,
                    mark_price=100.0,
                    funding_rate=None,
                    volume_24h=500.0,
                    turnover_24h=50_000.0,
                    raw_payload={},
                )
            ],
            ttl_seconds=0,
        )

        snapshot = service.snapshot(exchange="bybit", symbol="btcusdt")

        self.assertEqual(snapshot.exchange, "bybit")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.volume_24h_quote, 50_000.0)
        self.assertAlmostEqual(snapshot.spread_bps or 0, 200.0)
        self.assertEqual(snapshot.source, "bybit_v5_tickers")

    def test_snapshot_falls_back_to_base_volume_times_mark_price(self) -> None:
        service = MarketQualityService(
            ticker_fetcher=lambda **_: [
                BybitTicker(
                    category="linear",
                    symbol="SOLUSDT",
                    bid1_price=49.9,
                    ask1_price=50.1,
                    mark_price=50.0,
                    funding_rate=None,
                    volume_24h=1_000.0,
                    turnover_24h=None,
                    raw_payload={},
                )
            ],
            ttl_seconds=0,
        )

        snapshot = service.snapshot(exchange="bybit", symbol="SOLUSDT")

        self.assertEqual(snapshot.volume_24h_quote, 50_000.0)


if __name__ == "__main__":
    unittest.main()
