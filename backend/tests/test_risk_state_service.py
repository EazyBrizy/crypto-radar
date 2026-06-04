import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.models.risk import RiskProtectionState
from app.models.user import AppUser
from app.schemas.risk import AccountRiskSnapshot
from app.schemas.user import RiskManagementSettings
from app.services.risk_state import (
    RiskStateService,
    _account_drawdown_percent,
    _apply_protection_policy,
    _reset_protection_windows,
    _window_starts,
)


class _FakeAccountSnapshotProvider:
    def __init__(self, snapshot: AccountRiskSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[dict[str, Any]] = []

    def get_real_account_snapshot(self, **kwargs: Any) -> AccountRiskSnapshot:
        self.calls.append(kwargs)
        return self.snapshot


class RiskStateServiceTest(unittest.TestCase):
    def test_live_real_snapshot_delegates_to_account_snapshot_provider(self) -> None:
        snapshot = AccountRiskSnapshot(
            status="fresh",
            fetched_at=datetime.now(timezone.utc),
            account_equity=Decimal("2500.50"),
            available_balance=Decimal("2400.25"),
            margin_mode="cross",
            positions=[],
            open_risk_amount=Decimal("0"),
            source="exchange",
        )
        provider = _FakeAccountSnapshotProvider(snapshot)
        service = RiskStateService(account_snapshot_provider=provider)

        result = service.get_real_account_snapshot(
            user_id="demo_user",
            exchange="bybit",
            mode="real",
            live_adapter=True,
            request_account_balance=Decimal("999999"),
        )

        self.assertEqual(result, snapshot)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["user_id"], "demo_user")
        self.assertEqual(provider.calls[0]["exchange"], "bybit")
        self.assertEqual(provider.calls[0]["mode"], "real")
        self.assertTrue(provider.calls[0]["live_adapter"])

    def test_dry_run_real_snapshot_uses_demo_balance_without_provider_call(self) -> None:
        provider = _FakeAccountSnapshotProvider(
            AccountRiskSnapshot(
                status="fresh",
                fetched_at=datetime.now(timezone.utc),
                account_equity=Decimal("999"),
                available_balance=Decimal("999"),
                margin_mode=None,
                positions=[],
                open_risk_amount=Decimal("0"),
                source="exchange",
            )
        )
        service = RiskStateService(account_snapshot_provider=provider)

        result = service.get_real_account_snapshot(
            user_id="usr_demo",
            exchange="bybit",
            mode="real",
            live_adapter=False,
            request_account_balance=Decimal("123.45"),
        )

        self.assertEqual(provider.calls, [])
        self.assertEqual(result.status, "fresh")
        self.assertEqual(result.source, "demo")
        self.assertEqual(result.account_equity, Decimal("123.45"))
        self.assertEqual(result.available_balance, Decimal("123.45"))

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
