import unittest

from app.services.virtual_trading.simulation_model import get_virtual_simulation_model_info


class VirtualSimulationModelContractTest(unittest.TestCase):
    def test_model_info_separates_active_and_planned_capabilities(self) -> None:
        info = get_virtual_simulation_model_info()
        active_codes = {capability.code for capability in info.active_capabilities}
        planned_codes = {capability.code for capability in info.planned_capabilities}

        self.assertEqual(info.current_tier, "advanced")
        self.assertIn("orderbook_depth_simulation", active_codes)
        self.assertIn("execution_realism_check", active_codes)
        self.assertNotIn("reject_unrealistic_trades", active_codes)
        self.assertIn("impact_decay", active_codes)
        self.assertIn("queue_position_limit_orders", planned_codes)
        self.assertIn("agent_based_market_simulator", planned_codes)
        self.assertNotIn("monte_carlo_execution_simulation", active_codes)


if __name__ == "__main__":
    unittest.main()
