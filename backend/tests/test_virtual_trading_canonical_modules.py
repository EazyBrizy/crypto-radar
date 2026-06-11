import unittest

from app.services.virtual_execution_engine import VirtualExecutionEngine as LegacyVirtualExecutionEngine
from app.services.virtual_simulation_model import (
    get_virtual_simulation_model_info as legacy_simulation_model_info,
)
from app.services.virtual_trading.execution_engine import VirtualExecutionEngine
from app.services.virtual_trading.simulation_model import get_virtual_simulation_model_info


class VirtualTradingCanonicalModulesTest(unittest.TestCase):
    def test_execution_engine_implementation_lives_under_virtual_trading_package(self) -> None:
        self.assertEqual(VirtualExecutionEngine.__module__, "app.services.virtual_trading.execution_engine")
        self.assertIs(LegacyVirtualExecutionEngine, VirtualExecutionEngine)

    def test_simulation_model_implementation_lives_under_virtual_trading_package(self) -> None:
        self.assertEqual(
            get_virtual_simulation_model_info.__module__,
            "app.services.virtual_trading.simulation_model",
        )
        self.assertIs(legacy_simulation_model_info, get_virtual_simulation_model_info)


if __name__ == "__main__":
    unittest.main()
