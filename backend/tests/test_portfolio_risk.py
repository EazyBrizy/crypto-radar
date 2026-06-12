from __future__ import annotations

import unittest

from app.services.portfolio_risk import (
    PortfolioRiskContext,
    PortfolioRiskLimits,
    PortfolioRiskService,
)


class PortfolioRiskServiceTest(unittest.TestCase):
    def test_reduces_size_to_fit_remaining_open_risk_budget(self) -> None:
        decision = PortfolioRiskService().evaluate(
            PortfolioRiskContext(
                account_equity=1_000,
                proposed_risk_amount=20,
                open_risk_amount=40,
            ),
            PortfolioRiskLimits(max_open_risk_percent=5),
        )

        self.assertEqual(decision.action, "reduce_size")
        self.assertEqual(decision.reason_code, "max_open_risk_exceeded")
        self.assertAlmostEqual(decision.approved_risk_amount, 10)
        self.assertAlmostEqual(decision.size_multiplier, 0.5)
        self.assertIn("max_open_risk_exceeded", decision.reason_codes)

    def test_blocks_trade_when_open_risk_budget_is_exhausted(self) -> None:
        decision = PortfolioRiskService().evaluate(
            PortfolioRiskContext(
                account_equity=1_000,
                proposed_risk_amount=10,
                open_risk_amount=50,
            ),
            PortfolioRiskLimits(max_open_risk_percent=5),
        )

        self.assertEqual(decision.action, "block_trade")
        self.assertFalse(decision.can_enter)
        self.assertEqual(decision.reason_code, "max_open_risk_exceeded")

    def test_stops_agent_when_daily_loss_limit_is_reached(self) -> None:
        decision = PortfolioRiskService().evaluate(
            PortfolioRiskContext(
                account_equity=1_000,
                proposed_risk_amount=5,
                daily_loss_amount=30,
            ),
            PortfolioRiskLimits(max_daily_loss_percent=3),
        )

        self.assertEqual(decision.action, "stop_agent")
        self.assertEqual(decision.reason_code, "daily_loss_limit_exceeded")
        self.assertFalse(decision.can_enter)

    def test_pauses_strategy_when_strategy_loss_limit_is_reached(self) -> None:
        decision = PortfolioRiskService().evaluate(
            PortfolioRiskContext(
                account_equity=1_000,
                proposed_risk_amount=5,
                strategy_losses_today=2,
            ),
            PortfolioRiskLimits(max_strategy_losses_per_day=2),
        )

        self.assertEqual(decision.action, "pause_strategy")
        self.assertEqual(decision.reason_code, "max_strategy_losses_per_day_exceeded")
        self.assertFalse(decision.can_enter)

    def test_blocks_symbol_and_strategy_exposure_limits(self) -> None:
        symbol_decision = PortfolioRiskService().evaluate(
            PortfolioRiskContext(
                account_equity=1_000,
                proposed_risk_amount=10,
                symbol_open_risk_amount=25,
            ),
            PortfolioRiskLimits(max_symbol_risk_percent=3),
        )
        strategy_decision = PortfolioRiskService().evaluate(
            PortfolioRiskContext(
                account_equity=1_000,
                proposed_risk_amount=10,
                strategy_open_risk_amount=35,
            ),
            PortfolioRiskLimits(max_strategy_exposure_percent=4),
        )

        self.assertEqual(symbol_decision.action, "block_trade")
        self.assertEqual(symbol_decision.reason_code, "max_symbol_risk_exceeded")
        self.assertEqual(strategy_decision.action, "block_trade")
        self.assertEqual(strategy_decision.reason_code, "max_strategy_exposure_exceeded")

    def test_blocks_when_concurrent_position_limit_is_reached(self) -> None:
        decision = PortfolioRiskService().evaluate(
            PortfolioRiskContext(
                account_equity=1_000,
                proposed_risk_amount=5,
                open_position_count=3,
            ),
            PortfolioRiskLimits(max_concurrent_positions=3),
        )

        self.assertEqual(decision.action, "block_trade")
        self.assertEqual(decision.reason_code, "max_concurrent_positions_exceeded")


if __name__ == "__main__":
    unittest.main()
