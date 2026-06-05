import unittest
from datetime import datetime, timezone

from app.domain.signal_status import (
    can_signal_enter_now,
    is_execution_candidate_status,
    is_market_opportunity_status,
    is_terminal_signal_status,
    is_waiting_entry_status,
)
from app.schemas.signal import RadarSignal


class SignalStatusContractTest(unittest.IsolatedAsyncioTestCase):
    def test_active_is_market_opportunity_but_not_execution_candidate(self) -> None:
        self.assertTrue(is_market_opportunity_status("active"))
        self.assertTrue(is_waiting_entry_status("active"))
        self.assertFalse(is_execution_candidate_status("active"))
        active = _signal(status="active", can_enter=True)
        self.assertFalse(
            can_signal_enter_now(
                active.status,
                decision=active.decision,
                can_enter=active.can_enter,
            )
        )
        self.assertFalse(
            can_signal_enter_now(
                "active",
                can_enter=True,
                decision={
                    "signal_actionable": True,
                    "execution_allowed_virtual": True,
                    "execution_allowed_real": True,
                    "blockers": [],
                },
            )
        )

    def test_entry_touched_and_actionable_are_consistent_execution_candidates(self) -> None:
        self.assertTrue(is_execution_candidate_status("entry_touched"))
        self.assertTrue(is_execution_candidate_status("actionable"))
        self.assertTrue(is_execution_candidate_status("confirmed"))
        for status in ("entry_touched", "actionable"):
            signal = _signal(status=status, can_enter=True)
            self.assertTrue(
                can_signal_enter_now(
                    signal.status,
                    decision=signal.decision,
                    can_enter=signal.can_enter,
                )
            )

            denied_signal = _signal(status=status, can_enter=False)
            self.assertFalse(
                can_signal_enter_now(
                    denied_signal.status,
                    decision=denied_signal.decision,
                    can_enter=denied_signal.can_enter,
                )
            )
            self.assertTrue(
                can_signal_enter_now(
                    status,
                    decision={
                        "signal_actionable": True,
                        "execution_allowed_virtual": True,
                        "execution_allowed_real": True,
                        "blockers": [],
                    },
                    can_enter=None,
                )
            )

    def test_invalidated_and_expired_are_terminal(self) -> None:
        self.assertTrue(is_terminal_signal_status("invalidated"))
        self.assertTrue(is_terminal_signal_status("expired"))
        self.assertFalse(is_market_opportunity_status("invalidated"))
        self.assertFalse(is_market_opportunity_status("expired"))

def _signal(
    *,
    status: str,
    can_enter: bool | None = None,
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
        can_enter=can_enter,
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
