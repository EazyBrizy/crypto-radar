import unittest
from unittest.mock import patch

from app.schemas.candle import RadarConfigUpdate
from app.services.radar_config_service import RadarConfigService
from app.services.strategy_config_service import StrategyRuntimeConfig


class RadarConfigServiceTest(unittest.TestCase):
    def test_selected_symbols_include_explicit_strategy_pairs(self) -> None:
        runtime_config = StrategyRuntimeConfig(
            strategy_code="volatility_squeeze_breakout",
            exchanges=(),
            pairs=(("bybit", "XRPUSDT"),),
            timeframes=("15m",),
            params={},
        )

        with patch("app.services.strategy_config_service.strategy_config_service") as strategy_configs:
            strategy_configs.runtime_configs.return_value = [runtime_config]
            service = RadarConfigService()

            self.assertIn("XRPUSDT", service.selected_symbols())
            self.assertIn("bybit", service.selected_exchanges())

    def test_selected_timeframes_include_strategy_timeframes(self) -> None:
        runtime_config = StrategyRuntimeConfig(
            strategy_code="trend_pullback_continuation",
            exchanges=("bybit",),
            pairs=(),
            timeframes=("4h",),
            params={},
        )

        with patch("app.services.strategy_config_service.strategy_config_service") as strategy_configs:
            strategy_configs.runtime_configs.return_value = [runtime_config]
            service = RadarConfigService()

            self.assertIn("4h", service.selected_timeframes())
            self.assertRegex(service.scanner_subscription_hash(), r"^[a-f0-9]{16}$")

    def test_selected_timeframes_include_strategy_context_overrides(self) -> None:
        runtime_config = StrategyRuntimeConfig(
            strategy_code="volatility_squeeze_breakout",
            exchanges=("bybit",),
            pairs=(),
            timeframes=("15m",),
            params={"context_timeframe_map": {"15m": "4h"}},
        )

        with patch("app.services.strategy_config_service.strategy_config_service") as strategy_configs:
            strategy_configs.runtime_configs.return_value = [runtime_config]
            service = RadarConfigService()

            self.assertIn("4h", service.selected_timeframes())

    def test_manual_pair_scope_matches_even_without_exchange_scope(self) -> None:
        runtime_config = StrategyRuntimeConfig(
            strategy_code="liquidity_sweep_reversal",
            exchanges=(),
            pairs=(("bybit", "SOLUSDT"),),
            timeframes=("15m",),
            params={},
        )

        self.assertTrue(runtime_config.matches(exchange="bybit", symbol="SOLUSDT", timeframe="15m"))
        self.assertFalse(runtime_config.matches(exchange="bybit", symbol="BTCUSDT", timeframe="15m"))

    def test_scanner_universe_uses_only_explicit_pairs_when_all_strategies_are_scoped(self) -> None:
        service = RadarConfigService()
        service.update_config(RadarConfigUpdate(symbols=["BTCUSDT", "ETHUSDT"]))
        runtime_config = StrategyRuntimeConfig(
            strategy_code="volatility_squeeze_breakout",
            exchanges=(),
            pairs=(("bybit", "XRPUSDT"),),
            timeframes=("15m",),
            params={},
        )

        universe = service.scanner_universe(
            runtime_configs=[runtime_config],
            watchlist_pairs=[],
        )

        self.assertEqual(universe.pairs, (("bybit", "XRPUSDT"),))
        self.assertEqual(universe.source, "explicit pairs")
        self.assertEqual(universe.estimated_strategy_checks, 1)

    def test_scanner_universe_preserves_default_for_unscoped_strategy(self) -> None:
        service = RadarConfigService()
        runtime_config = StrategyRuntimeConfig(
            strategy_code="trend_pullback_continuation",
            exchanges=("bybit",),
            pairs=(),
            timeframes=("15m",),
            params={},
        )

        universe = service.scanner_universe(
            runtime_configs=[runtime_config],
            watchlist_pairs=[],
        )

        self.assertEqual(
            universe.pairs,
            tuple(("bybit", symbol) for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "1000PEPEUSDT"]),
        )
        self.assertEqual(universe.source, "default")

    def test_scanner_universe_mixes_explicit_pairs_with_unscoped_base(self) -> None:
        service = RadarConfigService()
        service.update_config(RadarConfigUpdate(symbols=["BTCUSDT", "ETHUSDT"]))
        scoped_config = StrategyRuntimeConfig(
            strategy_code="volatility_squeeze_breakout",
            exchanges=(),
            pairs=(("bybit", "XRPUSDT"),),
            timeframes=("15m",),
            params={},
        )
        unscoped_config = StrategyRuntimeConfig(
            strategy_code="trend_pullback_continuation",
            exchanges=("bybit",),
            pairs=(),
            timeframes=("15m",),
            params={},
        )

        universe = service.scanner_universe(
            runtime_configs=[scoped_config, unscoped_config],
            watchlist_pairs=[],
        )

        self.assertEqual(
            universe.pairs,
            (("bybit", "XRPUSDT"), ("bybit", "BTCUSDT"), ("bybit", "ETHUSDT")),
        )
        self.assertEqual(universe.source, "explicit pairs + scanner config")
        self.assertEqual(universe.estimated_strategy_checks, 4)

    def test_scanner_universe_pair_guard_loads_all_or_truncates(self) -> None:
        service = RadarConfigService()
        service.update_config(RadarConfigUpdate(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"]))
        runtime_config = StrategyRuntimeConfig(
            strategy_code="trend_pullback_continuation",
            exchanges=("bybit",),
            pairs=(),
            timeframes=("15m",),
            params={},
        )

        full_universe = service.scanner_universe(
            runtime_configs=[runtime_config],
            watchlist_pairs=[],
            max_pairs=2,
            truncate_over_limit=False,
        )

        self.assertFalse(full_universe.truncated)
        self.assertEqual(
            full_universe.pairs,
            (("bybit", "BTCUSDT"), ("bybit", "ETHUSDT"), ("bybit", "SOLUSDT")),
        )
        self.assertIsNone(full_universe.warning)

        universe = service.scanner_universe(
            runtime_configs=[runtime_config],
            watchlist_pairs=[],
            max_pairs=2,
            truncate_over_limit=True,
        )

        self.assertTrue(universe.truncated)
        self.assertEqual(universe.pairs, (("bybit", "BTCUSDT"), ("bybit", "ETHUSDT")))
        self.assertIn("truncated", universe.warning or "")

    def test_strategy_runtime_matches_filters_pair_exchange_and_timeframe(self) -> None:
        scoped_config = StrategyRuntimeConfig(
            strategy_code="liquidity_sweep_reversal",
            exchanges=("bybit",),
            pairs=(("bybit", "SOLUSDT"),),
            timeframes=("15m",),
            params={},
        )
        unscoped_config = StrategyRuntimeConfig(
            strategy_code="trend_pullback_continuation",
            exchanges=("bybit",),
            pairs=(),
            timeframes=("15m",),
            params={},
        )

        self.assertTrue(scoped_config.matches(exchange="BYBIT", symbol="solusdt", timeframe="15m"))
        self.assertFalse(scoped_config.matches(exchange="bybit", symbol="SOLUSDT", timeframe="1h"))
        self.assertFalse(scoped_config.matches(exchange="bybit", symbol="ETHUSDT", timeframe="15m"))
        self.assertTrue(unscoped_config.matches(exchange="bybit", symbol="ETHUSDT", timeframe="15m"))
        self.assertFalse(unscoped_config.matches(exchange="binance", symbol="ETHUSDT", timeframe="15m"))


if __name__ == "__main__":
    unittest.main()
