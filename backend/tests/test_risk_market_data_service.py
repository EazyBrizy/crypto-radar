import unittest

from app.exchanges.bybit import BybitOrderBookSnapshot, BybitPositionInfo, BybitTicker
from app.services.risk_market_data import RiskMarketDataService


class _PositionProvider:
    def get_bybit_positions(self, **_kwargs):
        return [
            BybitPositionInfo(
                category="linear",
                symbol="BTCUSDT",
                side="Buy",
                size=0.25,
                liquidation_price=45_000,
                raw_payload={},
            )
        ]


class RiskMarketDataServiceTest(unittest.TestCase):
    def test_bybit_snapshot_uses_ask_spread_funding_depth_and_live_liq_price(self) -> None:
        service = RiskMarketDataService(
            ticker_fetcher=lambda **_kwargs: [
                BybitTicker(
                    category="linear",
                    symbol="BTCUSDT",
                    bid1_price=50_000,
                    ask1_price=50_010,
                    mark_price=50_005,
                    funding_rate=0.0001,
                    volume_24h=None,
                    turnover_24h=None,
                    raw_payload={},
                )
            ],
            orderbook_fetcher=lambda **_kwargs: BybitOrderBookSnapshot(
                category="linear",
                symbol="BTCUSDT",
                bids=[(50_000, 1.0), (49_990, 1.0)],
                asks=[(50_010, 0.5), (50_020, 0.5)],
                raw_payload={},
            ),
            position_provider=_PositionProvider(),
        )

        snapshot = service.build_snapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            side="long",
            mode="real",
            instrument_type="futures",
            fallback_entry_price=50_000,
            manual_slippage_bps=5,
            user_id="demo_user",
        )

        self.assertEqual(snapshot.entry_price, 50_010)
        self.assertEqual(snapshot.best_bid, 50_000)
        self.assertEqual(snapshot.best_ask, 50_010)
        self.assertEqual(snapshot.mark_price, 50_005)
        self.assertEqual(snapshot.funding_rate, 0.0001)
        self.assertAlmostEqual(snapshot.funding_buffer_per_unit, 5.001)
        self.assertAlmostEqual(snapshot.spread_percent or 0, 10 / 50_005 * 100)
        self.assertAlmostEqual(snapshot.slippage_bps, 5 + (snapshot.spread_bps or 0))
        self.assertAlmostEqual(snapshot.orderbook_depth_usd or 0, 50_010 * 0.5 + 50_020 * 0.5)
        self.assertEqual(snapshot.liquidation_price, 45_000)
        self.assertEqual(snapshot.market_data_status, "fresh")

    def test_short_snapshot_uses_bid_and_bid_depth(self) -> None:
        service = RiskMarketDataService(
            ticker_fetcher=lambda **_kwargs: [
                BybitTicker(
                    category="linear",
                    symbol="BTCUSDT",
                    bid1_price=49_990,
                    ask1_price=50_000,
                    mark_price=49_995,
                    funding_rate=None,
                    volume_24h=None,
                    turnover_24h=None,
                    raw_payload={},
                )
            ],
            orderbook_fetcher=lambda **_kwargs: BybitOrderBookSnapshot(
                category="linear",
                symbol="BTCUSDT",
                bids=[(49_990, 2.0)],
                asks=[(50_000, 1.0)],
                raw_payload={},
            ),
            position_provider=None,
        )

        snapshot = service.build_snapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            side="short",
            mode="virtual",
            instrument_type="virtual",
            fallback_entry_price=50_000,
        )

        self.assertEqual(snapshot.entry_price, 49_990)
        self.assertEqual(snapshot.orderbook_depth_usd, 49_990 * 2)


if __name__ == "__main__":
    unittest.main()
