import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.signal_repository import OPEN_SIGNAL_STATUSES, SignalWriteResult
from app.schemas.signal import RadarSignal
from app.schemas.trade_plan import build_trade_plan_from_legacy_fields
from app.services.signal_service import SignalService


class FakeSignalRepository:
    def __init__(self, result: SignalWriteResult) -> None:
        self.result = result

    def list_signals(self, limit: int = 200) -> list[RadarSignal]:
        return [self.result.signal]

    def list_active_signals(self, limit: int = 200) -> list[RadarSignal]:
        return [self.result.signal] if self.result.signal.status == "active" else []

    def list_open_signals(self, limit: int = 200) -> list[RadarSignal]:
        return [self.result.signal] if self.result.signal.status in OPEN_SIGNAL_STATUSES else []

    def list_open_signals_for_series(self, *, exchange: str, symbol: str, timeframe: str, limit: int = 200) -> list[RadarSignal]:
        signal = self.result.signal
        if signal.exchange == exchange and signal.symbol == symbol and signal.timeframe == timeframe:
            return [signal]
        return []

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

    def transition_signal(self, *args, **kwargs) -> SignalWriteResult | None:
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
    def test_radar_signal_keeps_legacy_fields_with_trade_plan(self) -> None:
        signal = RadarSignal(
            id=str(uuid4()),
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction="long",
            confidence=0.82,
            status="active",
            score=82,
            entry_min=100.0,
            entry_max=101.0,
            stop_loss=98.0,
            take_profit_1=103.0,
            take_profit_2=105.0,
            risk_reward=2.5,
            trade_plan=build_trade_plan_from_legacy_fields(
                entry_min=100.0,
                entry_max=101.0,
                stop_loss=98.0,
                take_profit_1=103.0,
                take_profit_2=105.0,
                risk_reward=2.5,
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        payload = signal.model_dump(mode="json")

        self.assertEqual(payload["entry_min"], 100.0)
        self.assertEqual(payload["entry_max"], 101.0)
        self.assertEqual(payload["stop_loss"], 98.0)
        self.assertEqual(payload["take_profit_1"], 103.0)
        self.assertEqual(payload["take_profit_2"], 105.0)
        self.assertEqual(payload["trade_plan"]["targets"][0]["label"], "TP1")

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

    def test_lifecycle_transition_fans_out_to_analytics_and_hot_store(self) -> None:
        signal = RadarSignal(
            id=str(uuid4()),
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction="long",
            confidence=0.82,
            status="actionable",
            score=82,
            timeframe="15m",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        result = SignalWriteResult(
            signal=signal,
            created=False,
            event_type="signal.updated",
            analytics_event={"event_type": "signal.updated", "signal_id": signal.id},
        )
        analytics = SpyAnalyticsWriter()
        hot_store = SpyHotStore()
        service = SignalService(
            repository=FakeSignalRepository(result),
            analytics_writer=analytics,
            hot_store=hot_store,
        )

        transitioned = service.transition_signal(
            signal.id,
            new_status="actionable",
            event_type="signal.updated",
            reason="Confirmation candle closed",
        )

        self.assertEqual(transitioned, signal)
        self.assertEqual(analytics.events, [result.analytics_event])
        self.assertEqual(hot_store.results, [result])


if __name__ == "__main__":
    unittest.main()
