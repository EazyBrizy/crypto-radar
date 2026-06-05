import unittest
from datetime import datetime, timezone

from app.schemas.market import Features
from app.schemas.signal import RadarSignal, SignalInvalidationSnapshot
from app.services.signal_lifecycle import SignalLifecycleWorker


class _FakeSignalStore:
    def __init__(self, signals: list[RadarSignal]) -> None:
        self.signals = {signal.id: signal for signal in signals}
        self.transitions: list[tuple[str, str, str | None]] = []

    def list_open_signals_for_series(self, *, exchange: str, symbol: str, timeframe: str, limit: int = 200):
        return [
            signal
            for signal in self.signals.values()
            if signal.exchange == exchange and signal.symbol == symbol and signal.timeframe == timeframe
        ][:limit]

    def transition_signal(
        self,
        signal_id: str,
        *,
        new_status: str,
        event_type: str,
        reason: str | None = None,
        lifecycle=None,
        signal_updates=None,
    ):
        signal = self.signals.get(signal_id)
        if signal is None:
            return None
        update = {"status": new_status, "status_reason": reason}
        if signal_updates:
            update.update(signal_updates)
        updated = signal.model_copy(update=update)
        self.signals[signal_id] = updated
        self.transitions.append((new_status, event_type, reason))
        return updated


class _FakePublisher:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


class SignalLifecycleWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_ready_signal_becomes_actionable_on_confirmation_candle(self) -> None:
        signal = _signal(status="ready")
        store = _FakeSignalStore([signal])
        publisher = _FakePublisher()
        worker = SignalLifecycleWorker(signals=store, publisher=publisher)

        transitions = await worker.process_closed_candle(
            _features(close=101.8, open=100.8, low=100.4, high=102.0, previous_high=101.4, volume_spike=1.2)
        )

        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].new_status, "actionable")
        self.assertEqual(store.signals[signal.id].status, "actionable")
        self.assertEqual(store.signals[signal.id].entry_min, 101.8)
        self.assertEqual(store.signals[signal.id].entry_max, 101.8)
        self.assertEqual(publisher.events[0]["type"], "signal.updated")

    async def test_low_rr_warning_does_not_block_actionable_transition(self) -> None:
        signal = _signal(
            status="ready",
            selected_rr=0.32,
            min_rr_ratio=1.5,
            selected_rr_target="nearest",
        )
        store = _FakeSignalStore([signal])
        worker = SignalLifecycleWorker(signals=store, publisher=_FakePublisher())

        transitions = await worker.process_closed_candle(
            _features(close=101.8, open=100.8, low=100.4, high=102.0, previous_high=101.4, volume_spike=1.2)
        )

        self.assertEqual(len(transitions), 1)
        self.assertEqual(store.signals[signal.id].status, "actionable")

    async def test_ready_signal_waits_without_micro_break(self) -> None:
        signal = _signal(status="ready")
        store = _FakeSignalStore([signal])
        worker = SignalLifecycleWorker(signals=store, publisher=_FakePublisher())

        transitions = await worker.process_closed_candle(
            _features(close=101.2, open=100.8, low=100.4, high=101.5, previous_high=101.4, volume_spike=1.2)
        )

        self.assertEqual(transitions, [])
        self.assertEqual(store.signals[signal.id].status, "ready")

    async def test_ready_signal_waits_without_previous_candle_level(self) -> None:
        signal = _signal(status="ready")
        store = _FakeSignalStore([signal])
        worker = SignalLifecycleWorker(signals=store, publisher=_FakePublisher())

        transitions = await worker.process_closed_candle(
            _features(close=101.8, open=100.8, low=100.4, high=102.0, previous_high=None, volume_spike=1.2)
        )

        self.assertEqual(transitions, [])
        self.assertEqual(store.signals[signal.id].status, "ready")

    async def test_wait_for_pullback_becomes_ready_on_retest_without_confirmation(self) -> None:
        signal = _signal(status="wait_for_pullback")
        store = _FakeSignalStore([signal])
        worker = SignalLifecycleWorker(signals=store, publisher=_FakePublisher())

        transitions = await worker.process_closed_candle(
            _features(close=100.7, open=101.3, low=99.8, high=101.4, volume_spike=0.8)
        )

        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].new_status, "ready")
        self.assertIn("Pullback retest", transitions[0].reason)

    async def test_wait_for_pullback_does_not_confirm_when_funding_turns_extreme(self) -> None:
        signal = _signal(status="wait_for_pullback")
        store = _FakeSignalStore([signal])
        worker = SignalLifecycleWorker(signals=store, publisher=_FakePublisher())

        transitions = await worker.process_closed_candle(
            _features(
                close=101.8,
                open=100.8,
                low=100.4,
                high=102.0,
                previous_high=101.4,
                volume_spike=1.2,
                funding_rate=0.0016,
            )
        )

        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].new_status, "ready")
        self.assertIn("Funding became extreme", transitions[0].reason)

    async def test_actionable_signal_becomes_invalidated_on_logical_break(self) -> None:
        signal = _signal(
            status="actionable",
            invalidation=SignalInvalidationSnapshot(
                price=98.0,
                hard_stop=98.0,
                conditions=["Close below EMA50"],
                metadata={
                    "strategy": "trend_pullback_continuation",
                    "direction": "long",
                    "ema_50": 99.0,
                    "swing_low": 97.0,
                    "rsi_long_min": 45.0,
                },
            ),
        )
        store = _FakeSignalStore([signal])
        publisher = _FakePublisher()
        worker = SignalLifecycleWorker(signals=store, publisher=publisher)

        transitions = await worker.process_closed_candle(
            _features(close=98.7, open=100.0, low=98.5, high=100.2, rsi_14=44.0)
        )

        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].new_status, "invalidated")
        self.assertIn("Close below EMA50", transitions[0].reason)
        self.assertEqual(publisher.events[0]["type"], "signal.invalidated")


def _signal(
    *,
    status: str,
    invalidation: SignalInvalidationSnapshot | None = None,
    selected_rr: float | None = 2.0,
    min_rr_ratio: float | None = 1.5,
    selected_rr_target: str | None = "final",
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="signal-1",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        risk_reward=2.0,
        urgency="medium",
        status=status,
        score=82,
        timeframe="15m",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=103.0,
        take_profit_2=105.0,
        selected_rr=selected_rr,
        selected_rr_target=selected_rr_target,
        min_rr_ratio=min_rr_ratio,
        status_reason="Strategy setup exists; waiting for confirmation",
        invalidation=invalidation,
        created_at=now,
        updated_at=now,
    )


def _features(
    *,
    close: float,
    open: float,
    low: float,
    high: float,
    volume_spike: float = 1.2,
    rsi_14: float = 55.0,
    previous_high: float | None = None,
    previous_low: float | None = None,
    funding_rate: float | None = None,
) -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=1_779_796_800_000,
        price=close,
        open=open,
        high=high,
        low=low,
        close=close,
        price_change_1m=0.0,
        previous_high=previous_high,
        previous_low=previous_low,
        volume=120.0,
        volume_spike=volume_spike,
        volume_ma_20=100.0,
        volatility=1.0,
        history_length=120,
        ema_50=99.0,
        rsi_14=rsi_14,
        atr_14=1.0,
        funding_rate=funding_rate,
        candle_bullish=close > open,
        candle_bearish=close < open,
    )


if __name__ == "__main__":
    unittest.main()
