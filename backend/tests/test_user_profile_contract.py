from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
import unittest

from app.api.v1.users import router
from app.schemas.user import RiskManagementPatch, UserProfileResponse, UserSettingsPatchRequest
from app.services import user_service as user_service_module


class UserProfileContractTest(unittest.TestCase):
    def test_user_profile_response_exposes_postgres_profile_fields(self) -> None:
        response = UserProfileResponse(
            id=UUID("ba520631-d035-4f95-a4c0-3b40553dd524"),
            email="demo@crypto-radar.local",
            username="demo_user",
            name="Demo Trader",
            display_name="Demo Trader",
            avatar_url=None,
            status="active",
            locale="ru",
            timezone="Europe/Warsaw",
            risk_profile="balanced",
            onboarding_done=True,
            settings={"theme": "dark"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.assertEqual(response.email, "demo@crypto-radar.local")
        self.assertEqual(response.name, "Demo Trader")
        self.assertEqual(response.settings["theme"], "dark")

    def test_users_router_exposes_me_endpoint(self) -> None:
        paths = {route.path for route in router.routes}

        self.assertIn("/users/me", paths)
        self.assertIn("/users/me/settings", paths)

    def test_user_settings_patch_accepts_virtual_simulation_level(self) -> None:
        request = UserSettingsPatchRequest(virtual_simulation_level="advanced")

        self.assertEqual(request.virtual_simulation_level, "advanced")

    def test_virtual_simulation_level_patch_preserves_risk_management(self) -> None:
        settings = {
            "virtual_trading": {"simulation_level": "mvp"},
            "risk_management": {
                "risk_profile": "custom",
                "max_spread_bps": 25,
                "max_slippage_bps": 80,
            },
        }

        updated = user_service_module._apply_virtual_simulation_level_patch(
            settings,
            "advanced",
        )

        self.assertEqual(updated["virtual_trading"]["simulation_level"], "advanced")
        self.assertEqual(updated["virtual_trading"]["simulation_level_status"], "stub")
        self.assertEqual(updated["virtual_trading"]["effective_simulation_level"], "mvp")
        self.assertEqual(updated["risk_management"], settings["risk_management"])

    def test_user_settings_patch_accepts_risk_management(self) -> None:
        request = UserSettingsPatchRequest(
            risk_profile="custom",
            risk_management=RiskManagementPatch(
                risk_per_trade_percent=0.75,
                min_rr_ratio=2.5,
                rr_guard_mode="soft",
                discovery_rr_guard_mode="soft",
                virtual_rr_guard_mode="off",
                backtest_rr_guard_mode="soft",
                real_rr_guard_mode="hard",
                strategy_rr_guard_modes={"trend_pullback_continuation": "hard"},
                max_daily_loss_percent=2.0,
                max_account_drawdown_percent=8.0,
                max_open_risk_percent=4.0,
                stop_loss_mode="atr",
                atr_period=14,
                atr_multiplier=2.0,
                tp1_r_multiple=1.0,
                tp2_r_multiple=2.0,
                tp3_r_multiple=3.0,
                partial_take_profit_enabled=True,
                tp1_close_percent=30.0,
                tp2_close_percent=40.0,
                tp3_close_percent=30.0,
                move_sl_to_breakeven_after_r=1.0,
                breakeven_offset_percent=0.05,
                trailing_stop_enabled=True,
                trailing_mode="atr",
                trailing_atr_multiplier=1.5,
                trailing_stop_percent=0.5,
                max_leverage=3,
                min_liquidation_buffer_percent=2.0,
            ),
        )

        self.assertEqual(request.risk_profile, "custom")
        self.assertEqual(request.risk_management.risk_per_trade_percent, 0.75)
        self.assertEqual(request.risk_management.virtual_rr_guard_mode, "off")
        self.assertEqual(request.risk_management.strategy_rr_guard_modes["trend_pullback_continuation"], "hard")
        self.assertEqual(request.risk_management.stop_loss_mode, "atr")
        self.assertEqual(request.risk_management.tp3_close_percent, 30.0)
        self.assertEqual(request.risk_management.max_leverage, 3)

    def test_virtual_balance_change_synchronizes_portfolio_balance(self) -> None:
        calls: list[tuple[object, object, object]] = []
        original = user_service_module.sync_virtual_starting_balance
        user_service_module.sync_virtual_starting_balance = (
            lambda session, user, target_balance: calls.append((session, user, target_balance))
        )
        session = object()
        user = object()
        try:
            user_service_module._sync_virtual_balance_if_changed(
                session=session,
                user=user,
                previous_settings={"virtual_starting_balance": 100},
                next_settings={"virtual_starting_balance": 10_000},
            )
        finally:
            user_service_module.sync_virtual_starting_balance = original

        self.assertEqual(calls, [(session, user, Decimal("10000"))])


if __name__ == "__main__":
    unittest.main()
