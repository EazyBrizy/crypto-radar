import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.risk import RiskProtectionState
from app.models.user import AppUser
from app.schemas.user import RiskManagementSettings
from app.services.risk_state import (
    _account_drawdown_percent,
    _apply_protection_policy,
    _reset_protection_windows,
    _window_starts,
)


class RiskStateServiceTest(unittest.TestCase):
    def test_daily_and_weekly_windows_reset_by_user_timezone(self) -> None:
        user = AppUser(email="risk-window@example.test", username="risk-window", timezone="Europe/Moscow")
        now = datetime(2026, 5, 29, 1, 30, tzinfo=timezone.utc)
        state = RiskProtectionState(
            state="blocked",
            loss_streak=2,
            daily_loss_amount=Decimal("12"),
            weekly_loss_amount=Decimal("25"),
            daily_window_start=now - timedelta(days=2),
            weekly_window_start=now - timedelta(days=10),
            window_timezone="UTC",
            peak_equity=Decimal("1000"),
            current_equity=Decimal("900"),
            adaptive_multiplier=Decimal("0.75"),
        )

        _reset_protection_windows(state, user, now=now)
        expected_daily, expected_weekly = _window_starts(now, "Europe/Moscow")

        self.assertEqual(state.daily_loss_amount, Decimal("0"))
        self.assertEqual(state.weekly_loss_amount, Decimal("0"))
        self.assertEqual(state.daily_window_start, expected_daily)
        self.assertEqual(state.weekly_window_start, expected_weekly)
        self.assertEqual(state.window_timezone, "Europe/Moscow")
        self.assertEqual(state.peak_equity, Decimal("1000"))

    def test_weekly_loss_limit_recalculates_protection_state(self) -> None:
        state = RiskProtectionState(
            state="normal",
            loss_streak=0,
            daily_loss_amount=Decimal("0"),
            weekly_loss_amount=Decimal("8"),
            peak_equity=Decimal("100"),
            current_equity=Decimal("100"),
            adaptive_multiplier=Decimal("1"),
        )

        _apply_protection_policy(
            state,
            RiskManagementSettings(max_daily_loss_percent=3, max_weekly_loss_percent=7),
        )

        self.assertEqual(state.state, "blocked")
        self.assertEqual(state.reason, "Risk protection mode blocks entries after weekly loss limit.")

    def test_zero_loss_limits_disable_protection_blocks(self) -> None:
        state = RiskProtectionState(
            state="normal",
            loss_streak=0,
            daily_loss_amount=Decimal("50"),
            weekly_loss_amount=Decimal("80"),
            peak_equity=Decimal("100"),
            current_equity=Decimal("50"),
            adaptive_multiplier=Decimal("1"),
        )

        _apply_protection_policy(
            state,
            RiskManagementSettings(
                max_daily_loss_percent=0,
                max_weekly_loss_percent=0,
                max_account_drawdown_percent=0,
                auto_reduce_risk_after_losses=False,
            ),
        )

        self.assertEqual(state.state, "normal")
        self.assertIsNone(state.reason)

    def test_account_drawdown_percent_uses_peak_equity(self) -> None:
        state = RiskProtectionState(
            state="normal",
            loss_streak=0,
            daily_loss_amount=Decimal("0"),
            weekly_loss_amount=Decimal("0"),
            peak_equity=Decimal("10000"),
            current_equity=Decimal("8750"),
            adaptive_multiplier=Decimal("1"),
        )

        self.assertEqual(_account_drawdown_percent(state), 12.5)


if __name__ == "__main__":
    unittest.main()
