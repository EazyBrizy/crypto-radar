import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.signal_repository import _snapshot_from_signal, _snapshot_from_strategy_signal
from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot, StrategySignal


class SignalRepositoryExecutionGateSnapshotTest(unittest.TestCase):
    def test_strategy_signal_snapshot_persists_execution_gate(self) -> None:
        signal = StrategySignal(
            exchange="bybit",
            symbol="BTCUSDT",
            strategy="trend_pullback_continuation",
            direction="LONG",
            confidence=0.82,
            timestamp=int(datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()),
            score=82,
            status="actionable",
            execution_gate=_gate(),
        )

        snapshot = _snapshot_from_strategy_signal(signal, explanation=None)

        self.assertEqual(snapshot["execution_gate"]["feed_kind"], "execution_signal")
        self.assertTrue(snapshot["execution_gate"]["can_show_in_execution_feed"])

    def test_radar_signal_snapshot_persists_execution_gate(self) -> None:
        now = datetime.now(timezone.utc)
        signal = RadarSignal(
            id=str(uuid4()),
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction="long",
            confidence=0.82,
            score=82,
            status="actionable",
            created_at=now,
            updated_at=now,
            execution_gate=_gate(),
        )

        snapshot = _snapshot_from_signal(signal)

        self.assertEqual(snapshot["execution_gate"]["status"], "passed")
        self.assertEqual(snapshot["execution_gate"]["feed_kind"], "execution_signal")


def _gate() -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed",
        feed_kind="execution_signal",
        can_notify=True,
        can_enter_now=True,
        can_arm_pending=True,
        can_show_in_execution_feed=True,
    )


if __name__ == "__main__":
    unittest.main()
