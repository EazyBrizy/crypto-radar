import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
