import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot
from app.workers.signal_worker import _should_notify_signal


class SignalWorkerNotificationGateTest(unittest.TestCase):
    def test_notifications_are_created_only_for_execution_ready_signals(self) -> None:
        self.assertTrue(
            _should_notify_signal(
                _signal(
                    execution_gate=SignalExecutionGateSnapshot(
                        status="passed",
                        feed_kind="execution_signal",
                        can_notify=True,
                        can_enter_now=True,
                        can_arm_pending=True,
                        can_show_in_execution_feed=True,
                    )
                )
            )
        )
        self.assertFalse(
            _should_notify_signal(
                _signal(
                    execution_gate=SignalExecutionGateSnapshot(
                        status="warning",
                        feed_kind="watchlist",
                        can_notify=True,
                        can_enter_now=False,
                        can_arm_pending=False,
                        can_show_in_execution_feed=True,
                    )
                )
            )
        )
        self.assertFalse(
            _should_notify_signal(
                _signal(
                    execution_gate=SignalExecutionGateSnapshot(
                        status="blocked",
                        feed_kind="blocked",
                        can_notify=False,
                        can_enter_now=False,
                        can_arm_pending=False,
                        can_show_in_execution_feed=False,
                    )
                )
            )
        )

    def test_legacy_notification_fallback_is_strict(self) -> None:
        self.assertFalse(_should_notify_signal(_signal(execution_gate=None, score=23)))
        self.assertFalse(_should_notify_signal(_signal(execution_gate=None, candle_state="open")))
        self.assertFalse(_should_notify_signal(_signal(execution_gate=None, status="watchlist")))
        self.assertTrue(_should_notify_signal(_signal(execution_gate=None)))

    def test_execution_ready_notifications_are_deduped_by_pair_and_direction(self) -> None:
        seen: set[tuple[str, str, str]] = set()
        execution_gate = SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="execution_signal",
            can_notify=True,
            can_enter_now=True,
            can_arm_pending=True,
            can_show_in_execution_feed=True,
        )

        self.assertTrue(_should_notify_signal(_signal(execution_gate=execution_gate), notified_execution_keys=seen))
        self.assertFalse(
            _should_notify_signal(
                _signal(symbol="BTC/USDT", execution_gate=execution_gate),
                notified_execution_keys=seen,
            )
        )
        self.assertTrue(
            _should_notify_signal(
                _signal(direction="short", execution_gate=execution_gate),
                notified_execution_keys=seen,
            )
        )


def _signal(
    *,
    symbol: str = "BTCUSDT",
    direction: str = "long",
    score: int = 82,
    status: str = "actionable",
    candle_state: str = "closed",
    execution_gate: SignalExecutionGateSnapshot | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(uuid4()),
        symbol=symbol,
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction=direction,
        confidence=0.82,
        score=score,
        status=status,
        timeframe="15m",
        candle_state=candle_state,
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        created_at=now,
        updated_at=now,
        execution_gate=execution_gate,
    )


if __name__ == "__main__":
    unittest.main()
