from datetime import datetime, timezone
from uuid import uuid4

from app.domain.signal_status import (
    OPEN_SIGNAL_STATUSES,
    is_execution_candidate_status,
    is_market_opportunity_status,
)
from app.repositories.signal_repository import (
    MAX_STORED_SIGNALS,
    SIGNAL_AUTO_ENTRY_ARMED_EVENT,
    SIGNAL_CONFIRMED_EVENT,
    SIGNAL_CREATED_EVENT,
    SIGNAL_REJECTED_EVENT,
    SIGNAL_UPDATED_EVENT,
    SignalWriteResult,
    _signal_expires_at,
)
from app.schemas.signal import RadarSignal, SignalAutoEntrySnapshot, StrategySignal
from app.services.signal_service import NullSignalAnalyticsWriter, NullSignalHotStore, SignalService


class EphemeralSignalRepository:
    def __init__(self) -> None:
        self._signals: dict[str, RadarSignal] = {}

    def list_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        return sorted(self._signals.values(), key=lambda signal: signal.created_at, reverse=True)[:limit]

    def list_active_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        return [
            signal
            for signal in self.list_signals(limit)
            if is_execution_candidate_status(signal.status)
            and is_market_opportunity_status(signal.status)
            and _is_signal_actionable(signal)
        ]

    def list_open_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        return [
            signal
            for signal in self.list_signals(limit)
            if is_market_opportunity_status(signal.status) and _is_signal_actionable(signal)
        ]

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        signal = self._signals.get(signal_id)
        if signal is None:
            return None
        if signal.status in OPEN_SIGNAL_STATUSES and not _is_signal_actionable(signal):
            return None
        return signal

    def expire_open_signals(self, now: datetime | None = None, limit: int = MAX_STORED_SIGNALS) -> int:
        return self._expire_open_signals(now=now, limit=limit)

    def add_signal(self, signal: RadarSignal) -> SignalWriteResult:
        created = signal.id not in self._signals
        if signal.status in OPEN_SIGNAL_STATUSES and signal.expires_at is None:
            signal = signal.model_copy(update={"expires_at": _signal_expires_at(signal.created_at)})
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
            status=signal.status,
            score=score,
            timeframe=signal.timeframe,
            candle_state=signal.candle_state,
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
            status_reason=signal.status_reason,
            quality=signal.quality,
            regime=signal.regime,
            setup=signal.setup,
            confirmation=signal.confirmation,
            trigger=signal.trigger,
            invalidation=signal.invalidation,
            exit_plan=signal.exit_plan,
            trade_plan=signal.trade_plan,
            edge=signal.edge,
            execution_gate=signal.execution_gate,
            no_trade_filter=signal.no_trade_filter,
            decision=signal.decision,
            created_at=now,
            updated_at=now,
            expires_at=_signal_expires_at(now),
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
                "status": "rejected",
                "updated_at": now,
                "rejected_at": now,
                "decision_note": note,
            }
        )
        self._signals[signal_id] = updated
        return _write_result(updated, False, SIGNAL_REJECTED_EVENT)

    def arm_auto_entry(self, signal_id: str, *, request: dict) -> SignalWriteResult | None:
        signal = self._signals.get(signal_id)
        if signal is None:
            return None
        now = datetime.now(timezone.utc)
        updated = signal.model_copy(
            update={
                "auto_entry": SignalAutoEntrySnapshot(
                    enabled=True,
                    status="pending",
                    mode=request.get("mode", "virtual"),
                    user_id=request.get("user_id", "demo_user"),
                    armed_at=now,
                    message="Auto-entry is armed and waiting for strategy confirmation",
                    request=request,
                ),
                "updated_at": now,
            }
        )
        self._signals[signal_id] = updated
        return _write_result(updated, False, SIGNAL_AUTO_ENTRY_ARMED_EVENT)

    def _expire_open_signals(
        self,
        *,
        now: datetime | None = None,
        limit: int = MAX_STORED_SIGNALS,
    ) -> int:
        resolved_now = now or datetime.now(timezone.utc)
        expired = 0
        for signal_id, signal in list(self._signals.items()):
            if expired >= limit:
                break
            if signal.status not in OPEN_SIGNAL_STATUSES:
                continue
            expires_at = signal.expires_at or _signal_expires_at(signal.created_at)
            if expires_at is None:
                continue
            if expires_at > resolved_now:
                if signal.expires_at is None:
                    self._signals[signal_id] = signal.model_copy(update={"expires_at": expires_at})
                continue
            self._signals[signal_id] = signal.model_copy(
                update={
                    "status": "expired",
                    "updated_at": resolved_now,
                    "expires_at": expires_at,
                }
            )
            expired += 1
        return expired


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


def _is_signal_actionable(signal: RadarSignal) -> bool:
    if signal.expires_at is None:
        return True
    return signal.expires_at > datetime.now(timezone.utc)
