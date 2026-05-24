from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from app.models.schemas import RadarSignal, StrategySignal


class SignalService:
    """Stores radar signals for MVP 1.

    This is intentionally in-memory for the first API slice. The service boundary
    lets us replace it with Redis/PostgreSQL without changing API handlers.
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
        return signal

    def add_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str = "bybit",
        explanation: Optional[List[str]] = None,
    ) -> RadarSignal:
        now = datetime.now(timezone.utc)
        radar_signal = RadarSignal(
            id=f"sig_{uuid4().hex[:12]}",
            symbol=signal.symbol,
            exchange=exchange,
            strategy=signal.strategy,
            direction=signal.direction.lower(),
            confidence=signal.confidence,
            urgency="medium",
            explanation=explanation or [],
            created_at=now,
            updated_at=now,
        )
        return self.add_signal(radar_signal)

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
