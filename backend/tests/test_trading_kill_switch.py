from __future__ import annotations

import unittest

from app.services.trading_kill_switch import KillSwitchInput, TradingKillSwitchService


class TradingKillSwitchServiceTest(unittest.TestCase):
    def test_stale_market_data_pauses_execution_and_exports_metrics(self) -> None:
        decision = TradingKillSwitchService().evaluate(
            KillSwitchInput(
                market_data_status="stale",
                stale_data_seconds=95,
                max_stale_data_seconds=60,
            )
        )

        self.assertEqual(decision.state, "paused")
        self.assertFalse(decision.execution_allowed)
        self.assertIn("kill_switch_stale_market_data", decision.reason_codes)
        self.assertEqual(decision.metrics["kill_switch_state"], 2)
        self.assertEqual(decision.metrics["stale_data_seconds"], 95)

    def test_daily_loss_requires_manual_unlock(self) -> None:
        decision = TradingKillSwitchService().evaluate(
            KillSwitchInput(
                daily_loss_pct=3.2,
                max_daily_loss_pct=3.0,
            )
        )

        self.assertEqual(decision.state, "manual_unlock_required")
        self.assertFalse(decision.execution_allowed)
        self.assertTrue(decision.manual_unlock_required)
        self.assertIn("kill_switch_daily_loss_exceeded", decision.reason_codes)

    def test_exchange_degraded_is_visible_without_blocking_execution(self) -> None:
        decision = TradingKillSwitchService().evaluate(
            KillSwitchInput(exchange_status="degraded")
        )

        self.assertEqual(decision.state, "degraded")
        self.assertTrue(decision.execution_allowed)
        self.assertIn("kill_switch_exchange_degraded", decision.reason_codes)


if __name__ == "__main__":
    unittest.main()
