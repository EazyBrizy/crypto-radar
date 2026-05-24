from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from app.schemas.signal import RadarSignal, StrategySignal

MAX_STORED_SIGNALS = 200


class SignalService:
    """Хранит radar-сигналы для MVP 1.

    На первом API-срезе хранилище намеренно in-memory. Граница сервиса
    позволит заменить его на Redis/PostgreSQL без изменения API handlers.
    """

    def __init__(self) -> None:
        self._signals: Dict[str, RadarSignal] = {}

    def list_signals(self) -> List[RadarSignal]:
        return sorted(
            self._signals.values(),
            key=lambda signal: signal.created_at,
            reverse=True,
        )

    def list_active_signals(self) -> List[RadarSignal]:
        return [
            signal
            for signal in self.list_signals()
            if signal.status == "active"
        ]

    def get_signal(self, signal_id: str) -> Optional[RadarSignal]:
        return self._signals.get(signal_id)

    def add_signal(self, signal: RadarSignal) -> RadarSignal:
        self._signals[signal.id] = signal
        self._trim_signals()
        return signal

    def add_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: Optional[List[str]] = None,
    ) -> RadarSignal:
        now = datetime.now(timezone.utc)
        score = signal.score or int(signal.confidence * 100)
        radar_signal = RadarSignal(
            id=f"sig_{uuid4().hex[:12]}",
            symbol=signal.symbol,
            exchange=exchange or signal.exchange,
            strategy=signal.strategy,
            direction=signal.direction.lower(),
            confidence=signal.confidence,
            status="active" if score >= 70 else "watchlist",
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
            created_at=now,
            updated_at=now,
        )
        return self.add_signal(radar_signal)

    def _trim_signals(self) -> None:
        if len(self._signals) <= MAX_STORED_SIGNALS:
            return

        sorted_signals = sorted(
            self._signals.values(),
            key=lambda signal: signal.created_at,
            reverse=True,
        )
        keep_ids = {signal.id for signal in sorted_signals[:MAX_STORED_SIGNALS]}
        self._signals = {
            signal_id: signal
            for signal_id, signal in self._signals.items()
            if signal_id in keep_ids
        }

    def confirm_signal(self, signal_id: str) -> Optional[RadarSignal]:
        signal = self._signals.get(signal_id)
        if signal is None:
            return None

        now = datetime.now(timezone.utc)
        updated = signal.model_copy(
            update={
                "status": "confirmed",
                "updated_at": now,
                "confirmed_at": now,
            }
        )
        self._signals[signal_id] = updated
        return updated

    def reject_signal(self, signal_id: str) -> Optional[RadarSignal]:
        signal = self._signals.get(signal_id)
        if signal is None:
            return None

        now = datetime.now(timezone.utc)
        updated = signal.model_copy(
            update={
                "status": "rejected",
                "updated_at": now,
                "rejected_at": now,
            }
        )
        self._signals[signal_id] = updated
        return updated


signal_service = SignalService()
