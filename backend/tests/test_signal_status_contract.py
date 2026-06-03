import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.api.v1.signals import _signal_can_enter_now
from app.domain.signal_status import (
    is_execution_candidate_status,
    is_market_opportunity_status,
    is_terminal_signal_status,
    is_waiting_entry_status,
)
from app.schemas.signal import RadarSignal, SignalAutoEntrySnapshot
from app.services.auto_entry import SignalAutoEntryService


class SignalStatusContractTest(unittest.IsolatedAsyncioTestCase):
    def test_active_is_market_opportunity_but_not_execution_candidate(self) -> None:
        self.assertTrue(is_market_opportunity_status("active"))
        self.assertTrue(is_waiting_entry_status("active"))
        self.assertFalse(is_execution_candidate_status("active"))
        self.assertFalse(_signal_can_enter_now(_signal(status="active", can_enter=True)))

    def test_entry_touched_and_actionable_are_execution_candidates(self) -> None:
        self.assertTrue(is_execution_candidate_status("entry_touched"))
        self.assertTrue(is_execution_candidate_status("actionable"))
        self.assertTrue(is_execution_candidate_status("confirmed"))
        self.assertTrue(_signal_can_enter_now(_signal(status="entry_touched", can_enter=True)))
        self.assertTrue(_signal_can_enter_now(_signal(status="actionable", can_enter=True)))

    def test_invalidated_and_expired_are_terminal(self) -> None:
        self.assertTrue(is_terminal_signal_status("invalidated"))
        self.assertTrue(is_terminal_signal_status("expired"))
        self.assertFalse(is_market_opportunity_status("invalidated"))
        self.assertFalse(is_market_opportunity_status("expired"))

    async def test_auto_entry_does_not_trigger_for_active(self) -> None:
        service = SignalAutoEntryService(signals=None)
        signal = _signal(
            status="active",
            auto_entry=SignalAutoEntrySnapshot(
                enabled=True,
                status="pending",
                mode="virtual",
                user_id="demo_user",
                request={"mode": "virtual", "user_id": "demo_user"},
            ),
        )

        with patch(
            "app.services.auto_entry.virtual_trading_service.confirm_signal",
            side_effect=AssertionError("active must not reach virtual execution"),
        ):
            result = await service.execute_if_ready(signal)

        self.assertIsNone(result)


def _signal(
    *,
    status: str,
    can_enter: bool | None = None,
    auto_entry: SignalAutoEntrySnapshot | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=f"sig_{status}",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.8,
        status=status,
        score=80,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        risk_reward=3.0,
        auto_entry=auto_entry,
        can_enter=can_enter,
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
