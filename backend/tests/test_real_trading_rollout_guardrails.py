import unittest
from types import SimpleNamespace

from app.services.real_trading.rollout_guardrails import (
    RealTradingRolloutContext,
    RealTradingRolloutGuard,
)


class RealTradingRolloutGuardrailsTest(unittest.TestCase):
    def test_disabled_mode_blocks_live_order_submission(self) -> None:
        decision = RealTradingRolloutGuard(
            settings_obj=SimpleNamespace(real_trading_mode="disabled")
        ).evaluate(
            RealTradingRolloutContext(
                environment="testnet",
                order_placement_mode="testnet_real_orders",
                adapter_is_dry_run=False,
                requested_notional=25.0,
                has_protective_stop=True,
                kill_switch_state="healthy",
                portfolio_risk_passed=True,
                edge_status="positive",
                explicit_unlock=False,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.mode, "disabled")
        self.assertEqual(decision.reason_codes, ["real_trading_mode_disabled"])

    def test_dry_run_orders_mode_never_allows_live_adapter(self) -> None:
        decision = RealTradingRolloutGuard(
            settings_obj=SimpleNamespace(real_trading_mode="dry_run_orders")
        ).evaluate(
            RealTradingRolloutContext(
                environment="testnet",
                order_placement_mode="testnet_real_orders",
                adapter_is_dry_run=False,
                requested_notional=25.0,
                has_protective_stop=True,
                kill_switch_state="healthy",
                portfolio_risk_passed=True,
                edge_status="positive",
                explicit_unlock=False,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_codes, ["real_trading_dry_run_only"])

    def test_testnet_mode_blocks_mainnet(self) -> None:
        decision = RealTradingRolloutGuard(
            settings_obj=SimpleNamespace(real_trading_mode="testnet_real_orders")
        ).evaluate(
            RealTradingRolloutContext(
                environment="mainnet",
                order_placement_mode="mainnet_small_size",
                adapter_is_dry_run=False,
                requested_notional=25.0,
                has_protective_stop=True,
                kill_switch_state="healthy",
                portfolio_risk_passed=True,
                edge_status="positive",
                explicit_unlock=True,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_codes, ["real_trading_testnet_only"])

    def test_mainnet_requires_unlock_stop_healthy_kill_switch_risk_and_positive_edge(self) -> None:
        decision = RealTradingRolloutGuard(
            settings_obj=SimpleNamespace(
                real_trading_mode="mainnet_small_size",
                real_trading_explicit_unlock=False,
                real_trading_mainnet_small_size_cap_usd=50.0,
            )
        ).evaluate(
            RealTradingRolloutContext(
                environment="mainnet",
                order_placement_mode="mainnet_small_size",
                adapter_is_dry_run=False,
                requested_notional=25.0,
                has_protective_stop=False,
                kill_switch_state="paused",
                portfolio_risk_passed=False,
                edge_status="unknown",
                explicit_unlock=False,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason_codes,
            [
                "real_trading_unlock_required",
                "mainnet_protective_stop_required",
                "mainnet_kill_switch_not_healthy",
                "mainnet_portfolio_risk_blocked",
                "mainnet_calibration_not_positive",
            ],
        )

    def test_mainnet_small_size_enforces_cap(self) -> None:
        decision = RealTradingRolloutGuard(
            settings_obj=SimpleNamespace(
                real_trading_mode="mainnet_small_size",
                real_trading_explicit_unlock=True,
                real_trading_mainnet_small_size_cap_usd=50.0,
            )
        ).evaluate(
            RealTradingRolloutContext(
                environment="mainnet",
                order_placement_mode="mainnet_small_size",
                adapter_is_dry_run=False,
                requested_notional=51.0,
                has_protective_stop=True,
                kill_switch_state="healthy",
                portfolio_risk_passed=True,
                edge_status="positive",
                explicit_unlock=True,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_codes, ["mainnet_size_cap_exceeded"])


if __name__ == "__main__":
    unittest.main()
