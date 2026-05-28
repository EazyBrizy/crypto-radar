import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.signal_repository import SignalWriteResult
from app.schemas.signal import RadarSignal
from app.services.signal_service import SignalService


class FakeSignalRepository:
    def __init__(self, result: SignalWriteResult) -> None:
        self.result = result

    def list_signals(self, limit: int = 200) -> list[RadarSignal]:
        return [self.result.signal]

    def list_active_signals(self, limit: int = 200) -> list[RadarSignal]:
        return [self.result.signal] if self.result.signal.status == "active" else []

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        return self.result.signal if signal_id == self.result.signal.id else None

    def add_signal(self, signal: RadarSignal) -> SignalWriteResult:
        return self.result

    def upsert_strategy_signal(self, *args, **kwargs) -> SignalWriteResult:
        return self.result

    def confirm_signal(self, *args, **kwargs) -> SignalWriteResult | None:
        return self.result

    def reject_signal(self, *args, **kwargs) -> SignalWriteResult | None:
        return self.result


class SpyAnalyticsWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def write_event(self, event: dict[str, object]) -> None:
        self.events.append(event)


class SpyHotStore:
    def __init__(self) -> None:
        self.results: list[SignalWriteResult] = []

    def write_signal(self, result: SignalWriteResult) -> None:
        self.results.append(result)


class SignalServiceContractTest(unittest.TestCase):
    def test_signal_writes_fan_out_to_analytics_and_hot_store(self) -> None:
        signal = RadarSignal(
            id=str(uuid4()),
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction="long",
            confidence=0.82,
            status="active",
            score=82,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        result = SignalWriteResult(
            signal=signal,
            created=True,
            event_type="signal.created",
            analytics_event={"event_type": "signal.created", "signal_id": signal.id},
        )
        analytics = SpyAnalyticsWriter()
        hot_store = SpyHotStore()
        service = SignalService(
            repository=FakeSignalRepository(result),
            analytics_writer=analytics,
            hot_store=hot_store,
        )

        stored = service.add_signal(signal)

        self.assertEqual(stored.id, signal.id)
        self.assertEqual(analytics.events, [result.analytics_event])
        self.assertEqual(hot_store.results, [result])


if __name__ == "__main__":
    unittest.main()
