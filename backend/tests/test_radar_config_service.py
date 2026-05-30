import unittest
from unittest.mock import patch

from app.services.radar_config_service import RadarConfigService
from app.services.strategy_config_service import StrategyRuntimeConfig


class RadarConfigServiceTest(unittest.TestCase):
    def test_selected_symbols_include_explicit_strategy_pairs(self) -> None:
        runtime_config = StrategyRuntimeConfig(
            strategy_code="volatility_squeeze_breakout",
            exchanges=("bybit",),
            pairs=(("bybit", "XRPUSDT"),),
            timeframes=("15m",),
            params={},
        )

        with patch("app.services.strategy_config_service.strategy_config_service") as strategy_configs:
            strategy_configs.runtime_configs.return_value = [runtime_config]
            service = RadarConfigService()

            self.assertIn("XRPUSDT", service.selected_symbols())
            self.assertIn("bybit", service.selected_exchanges())


if __name__ == "__main__":
    unittest.main()
