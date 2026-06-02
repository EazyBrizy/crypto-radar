import unittest

from app.services.risk_management import (
    calculate_trade_risk_adjustment,
    execution_profile_resolver,
)
from app.schemas.user import RiskManagementSettings


class ExecutionProfileResolverTest(unittest.TestCase):
    def test_percent_profile_resolves_from_user_settings(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(risk_per_trade_percent=1.25),
            strategy_execution_settings={},
            request_override=None,
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.risk_mode, "percent")
        self.assertAlmostEqual(float(profile.risk_percent or 0), 1.25)
        self.assertEqual(profile.sources["risk_percent"], "user.risk_per_trade_percent")

    def test_fixed_profile_resolves_from_strategy_settings(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(risk_per_trade_percent=1.0),
            strategy_execution_settings={
                "risk_mode": "fixed",
                "fixed_risk_amount": 25,
                "fixed_risk_currency": "usdt",
                "instrument_type": "futures",
                "leverage": 5,
            },
            request_override=None,
            mode="real",
            instrument_type="spot",
        )

        self.assertEqual(profile.risk_mode, "fixed")
        self.assertEqual(profile.instrument_type, "futures")
        self.assertAlmostEqual(float(profile.fixed_risk_amount or 0), 25.0)
        self.assertEqual(profile.fixed_risk_currency, "USDT")
        self.assertEqual(int(profile.leverage), 5)
        self.assertEqual(profile.sources["fixed_risk_amount"], "strategy")

        applied_settings = execution_profile_resolver.apply_to_risk_settings(
            RiskManagementSettings(risk_per_trade_percent=1.0),
            profile,
        )
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=1_000,
            risk_settings=applied_settings,
            instrument_type="futures",
            strategy="trend_pullback_continuation",
            signal_score=100,
        )

        self.assertAlmostEqual(risk_plan.base_risk_amount, 25.0)
        self.assertAlmostEqual(risk_plan.base_risk_percent, 2.5)

    def test_fixed_mode_without_amount_fails_validation(self) -> None:
        with self.assertRaises(Exception) as context:
            execution_profile_resolver.resolve(
                user_risk_settings=RiskManagementSettings(risk_per_trade_percent=1.0),
                strategy_execution_settings={"risk_mode": "fixed"},
                request_override=None,
                mode="real",
                instrument_type="futures",
            )

        self.assertIn("fixed_risk_amount", str(context.exception))

    def test_legacy_risk_per_trade_percent_still_works(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(risk_per_trade_percent=1.0),
            strategy_execution_settings={"risk_per_trade_percent": 2.5},
            request_override=None,
            mode="real",
            instrument_type="spot",
        )

        self.assertEqual(profile.risk_mode, "percent")
        self.assertAlmostEqual(float(profile.risk_percent or 0), 2.5)
        self.assertEqual(profile.sources["risk_percent"], "strategy")

    def test_default_legacy_request_risk_percent_does_not_override_user_profile(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(risk_per_trade_percent=0.75),
            strategy_execution_settings={},
            request_override=None,
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.risk_mode, "percent")
        self.assertAlmostEqual(float(profile.risk_percent or 0), 0.75)
        self.assertEqual(profile.sources["risk_percent"], "user.risk_per_trade_percent")


if __name__ == "__main__":
    unittest.main()
