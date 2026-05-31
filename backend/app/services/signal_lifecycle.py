from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.repositories.signal_repository import SIGNAL_INVALIDATED_EVENT, SIGNAL_UPDATED_EVENT
from app.schemas.market import Features
from app.schemas.signal import RadarSignal
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import signal_invalidated_event, signal_updated_event
from app.services.signal_service import SignalService, signal_service
from app.services.trade_invalidation import signal_invalidation_conditions


class RealtimePublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None:
        ...


@dataclass(frozen=True)
class SignalLifecycleTransition:
    signal: RadarSignal
    old_status: str
    new_status: str
    event_type: str
    reason: str


@dataclass(frozen=True)
class _LifecycleDecision:
    status: str
    reason: str
    event_type: str = SIGNAL_UPDATED_EVENT


class SignalLifecycleWorker:
    """Moves open signal ideas forward on closed candles."""

    def __init__(
        self,
        *,
        signals: SignalService | None = None,
        publisher: RealtimePublisher | None = None,
    ) -> None:
        self._signals = signals or signal_service
        self._publisher = publisher or realtime_event_broker

    async def process_closed_candle(self, features: Features) -> list[SignalLifecycleTransition]:
        candidates = self._signals.list_open_signals_for_series(
            exchange=features.exchange,
            symbol=features.symbol,
            timeframe=features.timeframe,
        )
        transitions: list[SignalLifecycleTransition] = []
        for signal in candidates:
            decision = _lifecycle_decision(signal, features)
            if decision is None or decision.status == signal.status:
                continue
            updated = self._signals.transition_signal(
                signal.id,
                new_status=decision.status,
                event_type=decision.event_type,
                reason=decision.reason,
                lifecycle={
                    "trigger": "closed_candle",
                    "exchange": features.exchange,
                    "symbol": features.symbol,
                    "timeframe": features.timeframe,
                    "candle_timestamp": features.timestamp,
                    "close": features.close,
                    "volume_spike": features.volume_spike,
                },
            )
            if updated is None:
                continue
            transition = SignalLifecycleTransition(
                signal=updated,
                old_status=signal.status,
                new_status=updated.status,
                event_type=decision.event_type,
                reason=decision.reason,
            )
            transitions.append(transition)
            await self._publish_transition(transition)
        return transitions

    async def _publish_transition(self, transition: SignalLifecycleTransition) -> None:
        if transition.new_status == "invalidated":
            await self._publisher.publish(signal_invalidated_event(transition.signal, reason=transition.reason))
            return
        await self._publisher.publish(signal_updated_event(transition.signal))


def _lifecycle_decision(signal: RadarSignal, features: Features) -> _LifecycleDecision | None:
    invalidation_reason = _invalidation_reason(signal, features)
    if invalidation_reason:
        return _LifecycleDecision(
            status="invalidated",
            reason=invalidation_reason,
            event_type=SIGNAL_INVALIDATED_EVENT,
        )

    if signal.status == "wait_for_pullback":
        if not _entry_zone_touched(signal, features):
            return None
        if _confirmation_candle(signal, features) and not _status_reason_blocks_actionable(signal):
            return _LifecycleDecision(
                status="actionable",
                reason="Pullback retest reached and confirmation candle closed; entry still requires risk/reward gate",
            )
        return _LifecycleDecision(
            status="ready",
            reason="Pullback retest reached; waiting for a confirmation candle",
        )

    if signal.status == "ready" and not _status_reason_blocks_actionable(signal):
        if _confirmation_candle(signal, features):
            return _LifecycleDecision(
                status="actionable",
                reason="Confirmation candle closed after READY setup; entry still requires risk/reward gate",
            )

    if signal.status == "watchlist" and _entry_zone_touched(signal, features):
        return _LifecycleDecision(
            status="ready",
            reason="Watchlist idea reached the planned entry area; waiting for confirmation",
        )

    return None


def _invalidation_reason(signal: RadarSignal, features: Features) -> str | None:
    snapshot = signal.invalidation
    if snapshot is not None:
        triggered = signal_invalidation_conditions(
            strategy=signal.strategy,
            side=signal.direction,
            snapshot=snapshot,
            features=features,
            stop_loss=signal.stop_loss,
        )
        if triggered:
            return "; ".join(triggered)

    if signal.stop_loss is None:
        return None
    if signal.direction == "long" and features.close <= signal.stop_loss:
        return "Close reached or crossed the signal stop"
    if signal.direction == "short" and features.close >= signal.stop_loss:
        return "Close reached or crossed the signal stop"
    return None


def _entry_zone_touched(signal: RadarSignal, features: Features) -> bool:
    entry_min = signal.entry_min
    entry_max = signal.entry_max
    if entry_min is None and entry_max is None:
        return False
    lower = min(value for value in (entry_min, entry_max) if value is not None)
    upper = max(value for value in (entry_min, entry_max) if value is not None)
    return features.low <= upper and features.high >= lower


def _confirmation_candle(signal: RadarSignal, features: Features) -> bool:
    volume_ok = features.volume_spike >= 1.0
    if signal.direction == "long":
        entry_floor = signal.entry_min if signal.entry_min is not None else signal.entry_max
        if entry_floor is None:
            return False
        return volume_ok and features.close >= entry_floor and features.close > features.open
    entry_ceiling = signal.entry_max if signal.entry_max is not None else signal.entry_min
    if entry_ceiling is None:
        return False
    return volume_ok and features.close <= entry_ceiling and features.close < features.open


def _status_reason_blocks_actionable(signal: RadarSignal) -> bool:
    reason = (signal.status_reason or "").lower()
    blockers = (
        "risk/reward blocked",
        "support/resistance is too close",
        "higher timeframe is strongly against",
        "low-liquidity asset needs",
    )
    return any(blocker in reason for blocker in blockers)


signal_lifecycle_worker = SignalLifecycleWorker()
