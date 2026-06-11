import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot, StrategySignal
from app.workers import signal_worker
from app.workers.signal_worker import ScannerRunner, _should_notify_signal


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

    def test_terminal_signal_does_not_notify_even_with_stale_passed_gate(self) -> None:
        execution_gate = SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="execution_signal",
            can_notify=True,
            can_enter_now=True,
            can_arm_pending=True,
            can_show_in_execution_feed=True,
        )

        self.assertFalse(_should_notify_signal(_signal(status="invalidated", execution_gate=execution_gate)))

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


class ScannerRunnerForwardStrategyTestTest(unittest.IsolatedAsyncioTestCase):
    async def test_non_expired_scanner_signal_is_forwarded_as_original_strategy_signal(self) -> None:
        strategy_signal = _strategy_signal()
        forward = _AsyncForwardStrategyTests()
        broker = _RecordingBroker()
        runner = ScannerRunner(
            scanner=_Scanner([strategy_signal]),  # type: ignore[arg-type]
            store=_Store(_signal(status="watchlist")),  # type: ignore[arg-type]
            forward_strategy_tests=forward,
        )

        with patch.object(signal_worker, "realtime_event_broker", broker):
            await runner._run()

        self.assertEqual(forward.calls, [strategy_signal])
        self.assertIs(forward.calls[0], strategy_signal)
        self.assertEqual(runner.processed_signals, 1)
        self.assertEqual(len(broker.events), 1)

    async def test_expired_scanner_signal_is_not_forwarded(self) -> None:
        strategy_signal = _strategy_signal()
        forward = _AsyncForwardStrategyTests()
        runner = ScannerRunner(
            scanner=_Scanner([strategy_signal]),  # type: ignore[arg-type]
            store=_Store(_signal(status="expired")),  # type: ignore[arg-type]
            forward_strategy_tests=forward,
        )

        await runner._run()

        self.assertEqual(forward.calls, [])
        self.assertEqual(runner.processed_signals, 0)

    async def test_suppressed_terminal_scanner_signal_does_not_publish_realtime(self) -> None:
        strategy_signal = _strategy_signal()
        broker = _RecordingBroker()
        runner = ScannerRunner(
            scanner=_Scanner([strategy_signal]),  # type: ignore[arg-type]
            store=_Store(_signal(status="rejected")),  # type: ignore[arg-type]
        )

        with patch.object(signal_worker, "realtime_event_broker", broker):
            await runner._run()

        self.assertEqual(runner.processed_signals, 0)
        self.assertEqual(broker.events, [])

    async def test_forward_strategy_test_error_is_logged_and_does_not_stop_scanner(self) -> None:
        strategy_signal = _strategy_signal()
        forward = _FailingForwardStrategyTests()
        broker = _RecordingBroker()
        runner = ScannerRunner(
            scanner=_Scanner([strategy_signal]),  # type: ignore[arg-type]
            store=_Store(_signal(status="watchlist")),  # type: ignore[arg-type]
            forward_strategy_tests=forward,
        )

        with (
            patch.object(signal_worker, "realtime_event_broker", broker),
            self.assertLogs("app.workers.signal_worker", level="WARNING") as logs,
        ):
            await runner._run()

        self.assertEqual(forward.calls, [strategy_signal])
        self.assertEqual(runner.processed_signals, 1)
        self.assertEqual(len(broker.events), 1)
        self.assertIn("Forward strategy test signal processing skipped: forward failed", "\n".join(logs.output))


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


def _strategy_signal() -> StrategySignal:
    return StrategySignal(
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        direction="LONG",
        confidence=0.82,
        timestamp=1_780_000_000,
        score=82,
        status="actionable",
        timeframe="15m",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        risk_reward=2.0,
        explanation=["scanner explanation"],
    )


class _Scanner:
    def __init__(self, signals: list[StrategySignal]) -> None:
        self._signals = signals
        self.stats: dict[str, object] = {"stage": "idle"}
        self.errors: list[Exception] = []

    async def start(self) -> Any:
        for signal in self._signals:
            yield signal

    def record_error(self, exc: Exception) -> None:
        self.errors.append(exc)


class _Store:
    def __init__(self, radar_signal: RadarSignal) -> None:
        self.radar_signal = radar_signal
        self.calls: list[StrategySignal] = []

    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        **_: object,
    ) -> tuple[RadarSignal, bool]:
        self.calls.append(signal)
        return self.radar_signal, True


class _AsyncForwardStrategyTests:
    def __init__(self) -> None:
        self.calls: list[StrategySignal] = []

    async def process_strategy_signal(self, signal: StrategySignal) -> object:
        self.calls.append(signal)
        return object()


class _FailingForwardStrategyTests:
    def __init__(self) -> None:
        self.calls: list[StrategySignal] = []

    def process_strategy_signal(self, signal: StrategySignal) -> object:
        self.calls.append(signal)
        raise RuntimeError("forward failed")


class _RecordingBroker:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, event: dict[str, object]) -> None:
        self.events.append(event)


if __name__ == "__main__":
    unittest.main()
