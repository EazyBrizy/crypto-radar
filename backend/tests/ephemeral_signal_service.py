from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.signal_repository import (
    MAX_STORED_SIGNALS,
    SIGNAL_CONFIRMED_EVENT,
    SIGNAL_CREATED_EVENT,
    SIGNAL_INVALIDATED_EVENT,
    SIGNAL_UPDATED_EVENT,
    SignalWriteResult,
)
from app.schemas.signal import RadarSignal, StrategySignal
from app.services.signal_service import NullSignalAnalyticsWriter, NullSignalHotStore, SignalService


class EphemeralSignalRepository:
    def __init__(self) -> None:
        self._signals: dict[str, RadarSignal] = {}

    def list_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        return sorted(self._signals.values(), key=lambda signal: signal.created_at, reverse=True)[:limit]

    def list_active_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        return [signal for signal in self.list_signals(limit) if signal.status == "active"]

    def list_open_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        return [
            signal
            for signal in self.list_signals(limit)
            if signal.status in {"new", "active"}
        ]

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        return self._signals.get(signal_id)

    def add_signal(self, signal: RadarSignal) -> SignalWriteResult:
        created = signal.id not in self._signals
        self._signals[signal.id] = signal
        return _write_result(signal, created, SIGNAL_CREATED_EVENT if created else SIGNAL_UPDATED_EVENT)

    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> SignalWriteResult:
        now = datetime.now(timezone.utc)
        score = signal.score or int(signal.confidence * 100)
        radar_signal = RadarSignal(
            id=str(uuid4()),
            symbol=signal.symbol,
            exchange=exchange or signal.exchange,
            strategy=signal.strategy,
            direction=signal.direction.lower(),
            confidence=signal.confidence,
            status="active" if score >= 70 else "new",
            score=score,
            timeframe=signal.timeframe,
            urgency=signal.urgency,
            entry_min=signal.entry_min,
            entry_max=signal.entry_max,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            risk_reward=signal.risk_reward,
            explanation=explanation or signal.explanation,
            risks=signal.risks,
            score_breakdown=signal.score_breakdown,
            created_at=now,
            updated_at=now,
        )
        return self.add_signal(radar_signal)

    def confirm_signal(
        self,
        signal_id: str,
        trade_id: str | None = None,
        mode: str = "virtual",
        note: str | None = None,
    ) -> SignalWriteResult | None:
        signal = self._signals.get(signal_id)
        if signal is None:
            return None
        now = datetime.now(timezone.utc)
        updated = signal.model_copy(
            update={
                "status": "confirmed",
                "updated_at": now,
                "confirmed_at": now,
                "decision_mode": mode,
                "decision_note": note,
                "confirmed_trade_id": trade_id,
            }
        )
        self._signals[signal_id] = updated
        return _write_result(updated, False, SIGNAL_CONFIRMED_EVENT)

    def reject_signal(self, signal_id: str, note: str | None = None) -> SignalWriteResult | None:
        signal = self._signals.get(signal_id)
        if signal is None:
            return None
        now = datetime.now(timezone.utc)
        updated = signal.model_copy(
            update={
                "status": "invalidated",
                "updated_at": now,
                "rejected_at": now,
                "decision_note": note,
            }
        )
        self._signals[signal_id] = updated
        return _write_result(updated, False, SIGNAL_INVALIDATED_EVENT)


def ephemeral_signal_service() -> SignalService:
    return SignalService(
        repository=EphemeralSignalRepository(),
        analytics_writer=NullSignalAnalyticsWriter(),
        hot_store=NullSignalHotStore(),
    )


def _write_result(signal: RadarSignal, created: bool, event_type: str) -> SignalWriteResult:
    now = datetime.now(timezone.utc)
    return SignalWriteResult(
        signal=signal,
        created=created,
        event_type=event_type,
        analytics_event={
            "signal_id": uuid4(),
            "signal_key": signal.id,
            "event_type": event_type,
            "exchange": signal.exchange,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "strategy_code": signal.strategy,
            "strategy_version": "test",
            "direction": signal.direction,
            "confidence": signal.confidence,
            "score": signal.score,
            "entry_price": signal.entry_min or signal.entry_max or 0,
            "stop_loss": signal.stop_loss,
            "features_json": signal.model_dump(mode="json"),
            "event_ts": now,
            "ingest_ts": now,
        },
    )
