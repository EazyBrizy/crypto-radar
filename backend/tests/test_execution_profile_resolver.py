import unittest

from app.services.risk_management import (
    calculate_trade_risk_adjustment,
    execution_profile_resolver,
    request_risk_override_to_execution_settings,
    resolved_risk_profile_source,
)
from app.schemas.risk import RiskOverride, RiskPreviewRequest
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
            user_risk_settings=RiskManagementSettings(
                risk_per_trade_percent=5.0,
                futures_risk_per_trade_percent=5.0,
            ),
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
            RiskManagementSettings(
                risk_per_trade_percent=5.0,
                futures_risk_per_trade_percent=5.0,
            ),
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
            user_risk_settings=RiskManagementSettings(risk_per_trade_percent=5.0),
            strategy_execution_settings={"risk_per_trade_percent": 2.5},
            request_override=None,
            mode="real",
            instrument_type="spot",
        )

        self.assertEqual(profile.risk_mode, "percent")
        self.assertAlmostEqual(float(profile.risk_percent or 0), 2.5)
        self.assertEqual(profile.sources["risk_percent"], "strategy")

    def test_default_legacy_request_risk_percent_does_not_override_user_profile(self) -> None:
        request = RiskPreviewRequest(signal_id="sig_legacy", risk_percent=10.0)
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(risk_per_trade_percent=1.0),
            strategy_execution_settings={},
            request_override=request_risk_override_to_execution_settings(request.risk_override),
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.risk_mode, "percent")
        self.assertAlmostEqual(float(profile.risk_percent or 0), 1.0)
        self.assertEqual(profile.sources["risk_percent"], "user.risk_per_trade_percent")
        self.assertEqual(resolved_risk_profile_source(profile), "user_profile")

    def test_explicit_percent_risk_override_wins_over_saved_profile(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(risk_per_trade_percent=1.0),
            strategy_execution_settings={},
            request_override=request_risk_override_to_execution_settings(
                RiskOverride(risk_mode="percent", risk_percent=2)
            ),
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.risk_mode, "percent")
        self.assertAlmostEqual(float(profile.risk_percent or 0), 2.0)
        self.assertEqual(profile.sources["risk_percent"], "request_override")
        self.assertEqual(resolved_risk_profile_source(profile), "request_override")

    def test_explicit_fixed_risk_override_wins_over_saved_profile(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(risk_per_trade_percent=1.0),
            strategy_execution_settings={},
            request_override=request_risk_override_to_execution_settings(
                RiskOverride(risk_mode="fixed", fixed_risk_amount=50)
            ),
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.risk_mode, "fixed")
        self.assertAlmostEqual(float(profile.fixed_risk_amount or 0), 50.0)
        self.assertEqual(profile.sources["fixed_risk_amount"], "request_override")
        self.assertEqual(resolved_risk_profile_source(profile), "request_override")

        applied_settings = execution_profile_resolver.apply_to_risk_settings(
            RiskManagementSettings(risk_per_trade_percent=5.0),
            profile,
        )
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=1_000,
            risk_settings=applied_settings,
            instrument_type="virtual",
            strategy="trend_pullback_continuation",
            signal_score=100,
        )

        self.assertAlmostEqual(risk_plan.base_risk_amount, 50.0)
        self.assertAlmostEqual(risk_plan.base_risk_percent, 5.0)

    def test_invalid_risk_override_fails_validation(self) -> None:
        with self.assertRaises(Exception) as percent_context:
            RiskOverride(risk_mode="percent")
        with self.assertRaises(Exception) as fixed_context:
            RiskOverride(risk_mode="fixed")

        self.assertIn("risk_percent", str(percent_context.exception))
        self.assertIn("fixed_risk_amount", str(fixed_context.exception))

    def test_radar_display_mode_request_override_wins(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(radar_display_mode="execution_ready"),
            strategy_execution_settings={"radar_display_mode": "execution_ready"},
            request_override={"radar_display_mode": "all_market_opportunities"},
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.radar_display_mode, "all_market_opportunities")
        self.assertEqual(profile.sources["radar_display_mode"], "request_override")

    def test_radar_display_mode_strategy_override_wins_over_user(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(radar_display_mode="execution_ready"),
            strategy_execution_settings={"radar_display_mode": "all_market_opportunities"},
            request_override=None,
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.radar_display_mode, "all_market_opportunities")
        self.assertEqual(profile.sources["radar_display_mode"], "strategy")

    def test_radar_display_mode_user_setting_wins_over_default(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=RiskManagementSettings(radar_display_mode="execution_ready"),
            strategy_execution_settings={},
            request_override=None,
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.radar_display_mode, "execution_ready")
        self.assertEqual(profile.sources["radar_display_mode"], "user")

    def test_radar_display_mode_falls_back_to_default_without_user_setting(self) -> None:
        profile = execution_profile_resolver.resolve(
            user_risk_settings=None,
            strategy_execution_settings={},
            request_override=None,
            mode="virtual",
            instrument_type="spot",
        )

        self.assertEqual(profile.radar_display_mode, "all_market_opportunities")
        self.assertEqual(profile.sources["radar_display_mode"], "default")


if __name__ == "__main__":
    unittest.main()
