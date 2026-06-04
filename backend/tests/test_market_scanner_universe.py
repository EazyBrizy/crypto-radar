import unittest

from app.schemas.market import MarketData
from app.services.candle_service import CandleService
from app.services.market_scanner import MarketScanner


class MarketScannerUniverseTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_tick_skips_pairs_outside_scan_universe(self) -> None:
        scanner = MarketScanner(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            scan_pairs=(("bybit", "XRPUSDT"),),
            candle_store=CandleService(timeframes=["1m"]),
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=None,
            pending_entry_trigger=None,
            derivative_market=None,
            alpha_market_context=None,
        )

        signals = await scanner.process_tick(
            MarketData(
                exchange="bybit",
                symbol="BTCUSDT",
                price=100.0,
                volume=1.0,
                timestamp=1_779_796_800_000,
            )
        )

        self.assertEqual(signals, [])
        self.assertEqual(scanner.symbols, ["XRPUSDT"])
        self.assertEqual(scanner.stats["scanner_pairs_count"], 1)
        self.assertEqual(scanner.stats["scan_pairs"], ["bybit:XRPUSDT"])
        self.assertEqual(scanner.stats["ticks_processed"], 0)

    async def test_empty_scan_pairs_keeps_scanner_blocked(self) -> None:
        scanner = MarketScanner(
            symbols=[],
            exchanges=[],
            scan_pairs=[],
            candle_store=CandleService(timeframes=["1m"]),
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=None,
            pending_entry_trigger=None,
            derivative_market=None,
            alpha_market_context=None,
            universe_source="blocked",
            universe_warning="Scanner start is blocked.",
        )

        self.assertEqual(scanner.symbols, [])
        self.assertEqual(scanner.exchanges, [])
        self.assertEqual(scanner.stats["scanner_pairs_count"], 0)
        self.assertEqual(scanner.stats["scanner_universe_source"], "blocked")


if __name__ == "__main__":
    unittest.main()
