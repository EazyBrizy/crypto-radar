import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.signal_repository import _record_to_radar_signal, _snapshot_from_signal, _snapshot_from_strategy_signal
from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot, SignalTriggerSnapshot, StrategySignal


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

    def test_strategy_signal_snapshot_persists_trigger(self) -> None:
        signal = StrategySignal(
            exchange="bybit",
            symbol="BTCUSDT",
            strategy="trend_pullback_continuation",
            direction="LONG",
            confidence=0.82,
            timestamp=int(datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()),
            score=82,
            status="actionable",
            trigger=SignalTriggerSnapshot(passed=False, reason="Trigger not confirmed"),
        )

        snapshot = _snapshot_from_strategy_signal(signal, explanation=None)

        self.assertEqual(snapshot["trigger"]["passed"], False)
        self.assertEqual(snapshot["trigger"]["reason"], "Trigger not confirmed")

    def test_record_to_radar_signal_restores_trigger(self) -> None:
        record = _FakeRecord(
            features_snapshot={
                "trigger": {
                    "passed": False,
                    "reason": "Breakout trigger not confirmed",
                    "source": "confirmation",
                }
            }
        )

        signal = _record_to_radar_signal(record)

        self.assertIsNotNone(signal.trigger)
        self.assertFalse(signal.trigger.passed if signal.trigger else True)
        self.assertEqual(signal.trigger.reason if signal.trigger else None, "Breakout trigger not confirmed")


def _gate() -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed",
        feed_kind="execution_signal",
        can_notify=True,
        can_enter_now=True,
        can_arm_pending=True,
        can_show_in_execution_feed=True,
    )


class _FakeExchange:
    code = "bybit"


class _FakePair:
    symbol = "BTCUSDT"


class _FakeStrategy:
    code = "trend_pullback_continuation"


class _FakeStrategyVersion:
    strategy = _FakeStrategy()


class _FakeRecord:
    def __init__(self, *, features_snapshot: dict) -> None:
        now = datetime(2026, 6, 6, tzinfo=timezone.utc)
        self.id = uuid4()
        self.signal_key = str(self.id)
        self.pair = _FakePair()
        self.exchange = _FakeExchange()
        self.strategy_version = _FakeStrategyVersion()
        self.direction = "long"
        self.confidence = 0.82
        self.risk_reward = None
        self.score = 82
        self.timeframe = "15m"
        self.stop_loss = None
        self.take_profit = []
        self.explanation = None
        self.status = "actionable"
        self.features_snapshot = features_snapshot
        self.created_at = now
        self.detected_at = now
        self.updated_at = now
        self.expires_at = None


if __name__ == "__main__":
    unittest.main()
