import unittest

from app.services.trade_service import trade_service as compatibility_trade_service
from app.services.virtual_trading import (
    VirtualExecutionEngine,
    VirtualTradingService,
    get_virtual_simulation_model_info,
    virtual_trading_service,
)


class VirtualTradingServiceBoundaryTest(unittest.TestCase):
    def test_virtual_trading_package_is_primary_service_entrypoint(self) -> None:
        self.assertIsInstance(virtual_trading_service, VirtualTradingService)
        self.assertIs(compatibility_trade_service, virtual_trading_service)

    def test_virtual_trading_package_exports_execution_dependencies(self) -> None:
        self.assertIsNotNone(VirtualExecutionEngine)
        model_info = get_virtual_simulation_model_info()
        self.assertEqual(model_info.current_tier, "advanced")
        self.assertTrue(any(
            capability.code == "orderbook_depth_simulation"
            for capability in model_info.active_capabilities
        ))


if __name__ == "__main__":
    unittest.main()
