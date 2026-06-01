from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.repositories.signal_repository import SIGNAL_INVALIDATED_EVENT, SIGNAL_UPDATED_EVENT
from app.schemas.market import Features
from app.schemas.signal import RadarSignal
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import signal_invalidated_event, signal_updated_event
from app.services.signal_risk_reward import strategy_rr_block_reason
from app.services.signal_service import SignalService, signal_service
from app.services.trade_invalidation import signal_invalidation_conditions

FUNDING_ENTRY_BLOCK_THRESHOLD = 0.0015


class RealtimePublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None:
        ...


class AutoEntryExecutor(Protocol):
    async def execute_if_ready(self, signal: RadarSignal) -> RadarSignal | None:
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
    signal_updates: dict[str, Any] | None = None


class SignalLifecycleWorker:
    """Moves open signal ideas forward on closed candles."""

    def __init__(
        self,
        *,
        signals: SignalService | None = None,
        publisher: RealtimePublisher | None = None,
        auto_entry: AutoEntryExecutor | None = None,
    ) -> None:
        self._signals = signals or signal_service
        self._publisher = publisher or realtime_event_broker
        if auto_entry is None:
            from app.services.auto_entry import auto_entry_service

            auto_entry = auto_entry_service
        self._auto_entry = auto_entry

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
                signal_updates=decision.signal_updates,
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
            if updated.status in {"actionable", "active", "entry_touched"}:
                await self._auto_entry.execute_if_ready(updated)
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
            funding_reason = _funding_blocks_confirmation(signal, features)
            if funding_reason is not None:
                return _LifecycleDecision(
                    status="ready",
                    reason=funding_reason,
                )
            return _LifecycleDecision(
                status="actionable",
                reason="Pullback retest reached and confirmation candle closed; entry still requires risk/reward gate",
                signal_updates=_confirmation_signal_updates(signal, features),
            )
        return _LifecycleDecision(
            status="ready",
            reason="Pullback retest reached; waiting for a confirmation candle",
        )

    if signal.status == "ready" and not _status_reason_blocks_actionable(signal):
        if _confirmation_candle(signal, features):
            if _funding_blocks_confirmation(signal, features) is not None:
                return None
            return _LifecycleDecision(
                status="actionable",
                reason="Confirmation candle closed after READY setup; entry still requires risk/reward gate",
                signal_updates=_confirmation_signal_updates(signal, features),
            )

    if signal.status == "watchlist" and _entry_zone_touched(signal, features):
        rr_block_reason = strategy_rr_block_reason(signal)
        return _LifecycleDecision(
            status="ready",
            reason=rr_block_reason or "Watchlist idea reached the planned entry area; waiting for confirmation",
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
    volume_ok = features.volume_spike >= 1.1
    if signal.direction == "long":
        micro_break = features.previous_high is not None and features.close > features.previous_high
        return volume_ok and micro_break and features.close > features.open
    micro_break = features.previous_low is not None and features.close < features.previous_low
    return volume_ok and micro_break and features.close < features.open


def _funding_blocks_confirmation(signal: RadarSignal, features: Features) -> str | None:
    if signal.strategy != "trend_pullback_continuation" or features.funding_rate is None:
        return None
    if signal.direction == "long" and features.funding_rate >= FUNDING_ENTRY_BLOCK_THRESHOLD:
        return "Funding became extreme against long continuation; auto-entry waits for funding to normalize"
    if signal.direction == "short" and features.funding_rate <= -FUNDING_ENTRY_BLOCK_THRESHOLD:
        return "Funding became extreme against short continuation; auto-entry waits for funding to normalize"
    return None


def _confirmation_signal_updates(signal: RadarSignal, features: Features) -> dict[str, Any]:
    entry = features.close
    updates: dict[str, Any] = {
        "entry_min": entry,
        "entry_max": entry,
    }
    if signal.stop_loss is None:
        return updates
    risk = abs(entry - signal.stop_loss)
    if risk <= 0:
        return updates
    tp1_multiple = 1.5 if signal.strategy == "volatility_squeeze_breakout" else 1.0
    tp2_multiple = 2.5 if signal.strategy == "volatility_squeeze_breakout" else 2.0
    if signal.direction == "long":
        tp1 = entry + risk * tp1_multiple
        tp2 = entry + risk * tp2_multiple
    else:
        tp1 = entry - risk * tp1_multiple
        tp2 = entry - risk * tp2_multiple
    selected_target = signal.selected_rr_target or "final"
    updates.update(
        {
            "take_profit_1": round(tp1, 8),
            "take_profit_2": round(tp2, 8),
            "risk_reward": tp2_multiple,
            "first_target_rr": tp1_multiple,
            "final_target_rr": tp2_multiple,
            "selected_rr": tp1_multiple if selected_target == "nearest" else tp2_multiple,
            "selected_rr_target": selected_target,
            "confirmation": _confirmation_snapshot(signal, features),
        }
    )
    return updates


def _confirmation_snapshot(signal: RadarSignal, features: Features) -> dict[str, Any]:
    checks = signal.confirmation.model_dump(mode="json").get("checks", []) if signal.confirmation else []
    trigger_name = "previous_high_trigger" if signal.direction == "long" else "previous_low_trigger"
    trigger_level = features.previous_high if signal.direction == "long" else features.previous_low
    checks.append(
        {
            "name": trigger_name,
            "status": "passed",
            "score": trigger_level,
            "reason": "Closed confirmation candle broke the previous candle with >=1.1x volume",
            "metadata": {
                "close": features.close,
                "open": features.open,
                "volume_spike": features.volume_spike,
                "previous_high": features.previous_high,
                "previous_low": features.previous_low,
            },
        }
    )
    return {"passed": True, "checks": checks}


def _status_reason_blocks_actionable(signal: RadarSignal) -> bool:
    if strategy_rr_block_reason(signal) is not None:
        return True
    reason = (signal.status_reason or "").lower()
    blockers = (
        "risk/reward blocked",
        "support/resistance is too close",
        "higher timeframe is strongly against",
        "low-liquidity asset needs",
    )
    return any(blocker in reason for blocker in blockers)


signal_lifecycle_worker = SignalLifecycleWorker()
