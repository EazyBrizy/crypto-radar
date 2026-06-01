from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.market import MarketExchange, MarketPair
from app.models.outbox import OutboxEvent
from app.models.signal import TradingSignal, TradingSignalEvent
from app.models.strategy import StrategyTemplate, StrategyVersion
from app.schemas.signal import RadarSignal, SignalScoreBreakdown, StrategySignal
from app.schemas.trade_plan import TradePlan, build_trade_plan_from_legacy_fields
from app.services.signal_outcome_service import SignalOutcomeService

MAX_STORED_SIGNALS = 200
OPEN_SIGNAL_STATUSES = (
    "new",
    "active",
    "watchlist",
    "ready",
    "actionable",
    "wait_for_pullback",
    "entry_touched",
)
ACTIONABLE_SIGNAL_STATUSES = ("active", "actionable", "entry_touched")
SIGNAL_CREATED_EVENT = "signal.created"
SIGNAL_UPDATED_EVENT = "signal.updated"
SIGNAL_CONFIRMED_EVENT = "signal.confirmed"
SIGNAL_INVALIDATED_EVENT = "signal.invalidated"
SIGNAL_EXPIRED_EVENT = "signal.expired"
SIGNAL_AUTO_ENTRY_ARMED_EVENT = "signal.auto_entry_armed"
SIGNAL_AUTO_ENTRY_FAILED_EVENT = "signal.auto_entry_failed"


class SignalReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class SignalWriteResult:
    signal: RadarSignal
    created: bool
    event_type: str
    analytics_event: dict[str, Any]


class SignalRepository(Protocol):
    def list_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        ...

    def list_active_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        ...

    def list_open_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        ...

    def list_open_signals_for_series(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int = MAX_STORED_SIGNALS,
    ) -> list[RadarSignal]:
        ...

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        ...

    def add_signal(self, signal: RadarSignal) -> SignalWriteResult:
        ...

    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> SignalWriteResult:
        ...

    def confirm_signal(
        self,
        signal_id: str,
        trade_id: str | None = None,
        mode: str = "virtual",
        note: str | None = None,
    ) -> SignalWriteResult | None:
        ...

    def reject_signal(
        self,
        signal_id: str,
        note: str | None = None,
    ) -> SignalWriteResult | None:
        ...

    def transition_signal(
        self,
        signal_id: str,
        *,
        new_status: str,
        event_type: str,
        reason: str | None = None,
        lifecycle: dict[str, Any] | None = None,
        signal_updates: dict[str, Any] | None = None,
    ) -> SignalWriteResult | None:
        ...

    def arm_auto_entry(
        self,
        signal_id: str,
        *,
        request: dict[str, Any],
    ) -> SignalWriteResult | None:
        ...

    def update_auto_entry(
        self,
        signal_id: str,
        *,
        status: str,
        message: str | None = None,
        trade_id: str | None = None,
        real_execution: dict[str, Any] | None = None,
        event_type: str = SIGNAL_UPDATED_EVENT,
    ) -> SignalWriteResult | None:
        ...


class PostgresSignalRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        signal_outcomes: SignalOutcomeService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._signal_outcomes = signal_outcomes or SignalOutcomeService(session_factory)

    def list_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            if _expire_open_signal_records(session, now):
                session.commit()
            records = session.scalars(
                _signal_select()
                .order_by(TradingSignal.detected_at.desc())
                .limit(limit)
            ).all()
            return [_record_to_radar_signal(record) for record in records]

    def list_active_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            if _expire_open_signal_records(session, now):
                session.commit()
            records = session.scalars(
                _signal_select()
                .where(
                    TradingSignal.status.in_(ACTIONABLE_SIGNAL_STATUSES),
                    _expires_after(now),
                )
                .order_by(TradingSignal.detected_at.desc())
                .limit(limit)
            ).all()
            return [_record_to_radar_signal(record) for record in records]

    def list_open_signals(self, limit: int = MAX_STORED_SIGNALS) -> list[RadarSignal]:
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            if _expire_open_signal_records(session, now):
                session.commit()
            records = session.scalars(
                _signal_select()
                .where(
                    TradingSignal.status.in_(OPEN_SIGNAL_STATUSES),
                    _expires_after(now),
                )
                .order_by(TradingSignal.detected_at.desc())
                .limit(limit)
            ).all()
            return [_record_to_radar_signal(record) for record in records]

    def list_open_signals_for_series(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int = MAX_STORED_SIGNALS,
    ) -> list[RadarSignal]:
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            if _expire_open_signal_records(session, now):
                session.commit()
            records = session.scalars(
                _signal_select()
                .join(TradingSignal.exchange)
                .join(TradingSignal.pair)
                .where(
                    MarketExchange.code == exchange.lower(),
                    MarketPair.symbol == _normalize_symbol(symbol),
                    TradingSignal.timeframe == timeframe,
                    TradingSignal.status.in_(OPEN_SIGNAL_STATUSES),
                    _expires_after(now),
                )
                .order_by(TradingSignal.detected_at.desc())
                .limit(limit)
            ).all()
            return [_record_to_radar_signal(record) for record in records]

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            if _expire_open_signal_records(session, now):
                session.commit()
            record = _get_signal_record(session, signal_id)
            return _record_to_radar_signal(record) if record is not None else None

    def add_signal(self, signal: RadarSignal) -> SignalWriteResult:
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            exchange, pair, strategy_version = _resolve_references(
                session,
                exchange_code=signal.exchange,
                symbol=signal.symbol,
                strategy_code=signal.strategy,
            )
            record = _get_signal_record(session, signal.id)
            db_status = _api_status_to_db(signal.status)
            expires_at = signal.expires_at or _signal_expires_at(signal.created_at)
            if db_status in OPEN_SIGNAL_STATUSES and expires_at is not None and expires_at <= now:
                db_status = "expired"
            created = record is None
            event_type = SIGNAL_CREATED_EVENT if created else SIGNAL_UPDATED_EVENT
            if record is None:
                record = TradingSignal(
                    signal_key=signal.id,
                    strategy_version_id=strategy_version.id,
                    exchange_id=exchange.id,
                    pair_id=pair.id,
                    timeframe=signal.timeframe,
                    direction=signal.direction,
                    status=db_status,
                    confidence=_decimal(signal.confidence) or Decimal("0"),
                    score=_decimal(signal.score) or Decimal("0"),
                    entry_price=_entry_price(signal),
                    stop_loss=_decimal(signal.stop_loss),
                    take_profit=_take_profit(signal),
                    risk_reward=_decimal(signal.risk_reward),
                    detected_at=signal.created_at,
                    expires_at=expires_at,
                    features_snapshot=_snapshot_from_signal(signal),
                    explanation="\n".join(signal.explanation) if signal.explanation else None,
                    created_at=signal.created_at,
                    updated_at=signal.updated_at,
                )
                session.add(record)
                session.flush()
            else:
                _update_record_from_signal(record, signal, db_status, expires_at=expires_at)
                record.updated_at = now

            result = _persist_signal_event(session, record, event_type, old_status=None, now=now)
            session.commit()
            return result

    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> SignalWriteResult:
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            exchange_code = exchange or signal.exchange
            direction = signal.direction.lower()
            score = signal.score or int(signal.confidence * 100)
            db_status = _strategy_signal_status_to_db(signal.status, score)
            detected_at = _timestamp_to_datetime(signal.timestamp)
            expires_at = _signal_expires_at(detected_at)
            if expires_at is not None and expires_at <= now:
                db_status = "expired"
            exchange_record, pair, strategy_version = _resolve_references(
                session,
                exchange_code=exchange_code,
                symbol=signal.symbol,
                strategy_code=signal.strategy,
            )
            _expire_open_signal_records(session, now)
            signal_key = _signal_key(signal, exchange_code, detected_at)
            record = session.scalars(
                _signal_select()
                .where(
                    TradingSignal.exchange_id == exchange_record.id,
                    TradingSignal.pair_id == pair.id,
                    TradingSignal.strategy_version_id == strategy_version.id,
                    TradingSignal.timeframe == signal.timeframe,
                    TradingSignal.direction == direction,
                    TradingSignal.status.in_(OPEN_SIGNAL_STATUSES),
                )
                .order_by(TradingSignal.detected_at.desc())
                .limit(1)
            ).first()
            if record is None:
                record = session.scalars(
                    _signal_select().where(TradingSignal.signal_key == signal_key)
                ).one_or_none()
            created = record is None
            old_status = record.status if record is not None else None
            event_type = SIGNAL_CREATED_EVENT if created else SIGNAL_UPDATED_EVENT
            snapshot = _snapshot_from_strategy_signal(signal, explanation=explanation)
            if record is None:
                record = TradingSignal(
                    signal_key=signal_key,
                    strategy_version_id=strategy_version.id,
                    exchange_id=exchange_record.id,
                    pair_id=pair.id,
                    timeframe=signal.timeframe,
                    direction=direction,
                    status=db_status,
                    confidence=_decimal(signal.confidence) or Decimal("0"),
                    score=_decimal(score) or Decimal("0"),
                    entry_price=_decimal(_strategy_entry_price(signal)),
                    stop_loss=_decimal(signal.stop_loss),
                    take_profit=_take_profit_from_strategy_signal(signal),
                    risk_reward=_decimal(signal.risk_reward),
                    detected_at=detected_at,
                    expires_at=expires_at,
                    features_snapshot=snapshot,
                    explanation=_explanation_text(explanation or signal.explanation),
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
                session.flush()
            else:
                snapshot = _merge_strategy_snapshot(record.features_snapshot, snapshot)
                record.status = db_status
                record.confidence = _decimal(signal.confidence) or Decimal("0")
                record.score = _decimal(score) or Decimal("0")
                record.entry_price = _decimal(_strategy_entry_price(signal))
                record.stop_loss = _decimal(signal.stop_loss)
                record.take_profit = _take_profit_from_strategy_signal(signal)
                record.risk_reward = _decimal(signal.risk_reward)
                record.detected_at = detected_at
                if record.expires_at is None:
                    record.expires_at = expires_at
                _ensure_signal_expiry(record)
                record.features_snapshot = snapshot
                record.explanation = _explanation_text(explanation or signal.explanation)
                record.updated_at = now
                session.flush()

            if record.status in OPEN_SIGNAL_STATUSES:
                self._signal_outcomes.create_tracking_for_signal(record, session=session)

            result = _persist_signal_event(
                session,
                record,
                event_type,
                old_status=old_status,
                now=now,
            )
            session.commit()
            return result

    def confirm_signal(
        self,
        signal_id: str,
        trade_id: str | None = None,
        mode: str = "virtual",
        note: str | None = None,
    ) -> SignalWriteResult | None:
        return self._transition_signal(
            signal_id,
            new_status="confirmed",
            event_type=SIGNAL_CONFIRMED_EVENT,
            decision={
                "confirmed_trade_id": trade_id,
                "decision_mode": mode,
                "decision_note": note,
            },
        )

    def reject_signal(self, signal_id: str, note: str | None = None) -> SignalWriteResult | None:
        return self._transition_signal(
            signal_id,
            new_status="invalidated",
            event_type=SIGNAL_INVALIDATED_EVENT,
            decision={"decision_note": note},
        )

    def transition_signal(
        self,
        signal_id: str,
        *,
        new_status: str,
        event_type: str,
        reason: str | None = None,
        lifecycle: dict[str, Any] | None = None,
        signal_updates: dict[str, Any] | None = None,
    ) -> SignalWriteResult | None:
        with self._session_factory() as session:
            record = _get_signal_record(session, signal_id)
            if record is None:
                return None
            now = datetime.now(timezone.utc)
            old_status = record.status
            if old_status == new_status:
                return None
            record.status = new_status
            record.updated_at = now
            snapshot = dict(record.features_snapshot or {})
            if signal_updates:
                _apply_signal_updates(record, snapshot, signal_updates)
            if reason:
                snapshot["status_reason"] = reason
            lifecycle_event = {
                "event": event_type,
                "old_status": old_status,
                "new_status": new_status,
                "reason": reason,
                "created_at": now.isoformat(),
                **(lifecycle or {}),
            }
            lifecycle_events = snapshot.get("lifecycle_events")
            if not isinstance(lifecycle_events, list):
                lifecycle_events = []
            snapshot["lifecycle_events"] = [*lifecycle_events[-19:], lifecycle_event]
            record.features_snapshot = snapshot
            result = _persist_signal_event(
                session,
                record,
                event_type,
                old_status=old_status,
                now=now,
            )
            session.commit()
            return result

    def arm_auto_entry(
        self,
        signal_id: str,
        *,
        request: dict[str, Any],
    ) -> SignalWriteResult | None:
        with self._session_factory() as session:
            record = _get_signal_record(session, signal_id)
            if record is None:
                return None
            now = datetime.now(timezone.utc)
            snapshot = dict(record.features_snapshot or {})
            snapshot["auto_entry"] = {
                "enabled": True,
                "status": "pending",
                "mode": str(request.get("mode") or "virtual"),
                "user_id": str(request.get("user_id") or "demo_user"),
                "armed_at": now.isoformat(),
                "message": "Auto-entry is armed and waiting for strategy confirmation",
                "request": request,
            }
            record.features_snapshot = snapshot
            record.updated_at = now
            result = _persist_signal_event(
                session,
                record,
                SIGNAL_AUTO_ENTRY_ARMED_EVENT,
                old_status=record.status,
                now=now,
            )
            session.commit()
            return result

    def update_auto_entry(
        self,
        signal_id: str,
        *,
        status: str,
        message: str | None = None,
        trade_id: str | None = None,
        real_execution: dict[str, Any] | None = None,
        event_type: str = SIGNAL_UPDATED_EVENT,
    ) -> SignalWriteResult | None:
        with self._session_factory() as session:
            record = _get_signal_record(session, signal_id)
            if record is None:
                return None
            now = datetime.now(timezone.utc)
            snapshot = dict(record.features_snapshot or {})
            auto_entry = dict(snapshot.get("auto_entry") or {})
            auto_entry.update(
                {
                    "enabled": status == "pending",
                    "status": status,
                    "message": message,
                }
            )
            if status in {"triggered", "failed", "cancelled"}:
                auto_entry["triggered_at"] = now.isoformat()
            if trade_id is not None:
                auto_entry["trade_id"] = trade_id
            if real_execution is not None:
                auto_entry["real_execution"] = real_execution
            snapshot["auto_entry"] = auto_entry
            if message:
                snapshot["status_reason"] = message
            record.features_snapshot = snapshot
            record.updated_at = now
            result = _persist_signal_event(
                session,
                record,
                event_type,
                old_status=record.status,
                now=now,
            )
            session.commit()
            return result

    def _transition_signal(
        self,
        signal_id: str,
        *,
        new_status: str,
        event_type: str,
        decision: dict[str, Any],
    ) -> SignalWriteResult | None:
        with self._session_factory() as session:
            record = _get_signal_record(session, signal_id)
            if record is None:
                return None
            now = datetime.now(timezone.utc)
            old_status = record.status
            record.status = new_status
            record.updated_at = now
            snapshot = dict(record.features_snapshot or {})
            snapshot["decision"] = {key: value for key, value in decision.items() if value is not None}
            record.features_snapshot = snapshot
            result = _persist_signal_event(
                session,
                record,
                event_type,
                old_status=old_status,
                now=now,
            )
            session.commit()
            return result


def _signal_select():
    return select(TradingSignal).options(
        joinedload(TradingSignal.exchange),
        joinedload(TradingSignal.pair),
        joinedload(TradingSignal.strategy_version).joinedload(StrategyVersion.strategy),
    )


def _get_signal_record(session: Session, signal_id: str) -> TradingSignal | None:
    statement = _signal_select()
    signal_uuid = _parse_uuid(signal_id)
    if signal_uuid is not None:
        record = session.scalars(statement.where(TradingSignal.id == signal_uuid)).one_or_none()
        if record is not None:
            return record
    return session.scalars(statement.where(TradingSignal.signal_key == signal_id)).one_or_none()


def _expire_open_signal_records(session: Session, now: datetime) -> bool:
    changed = False
    records = session.scalars(
        _signal_select()
        .where(TradingSignal.status.in_(OPEN_SIGNAL_STATUSES))
        .order_by(TradingSignal.detected_at.desc())
    ).all()
    for record in records:
        _, expiry_changed = _ensure_signal_expiry(record)
        changed = changed or expiry_changed
        if not _record_is_expired(record, now):
            continue
        old_status = record.status
        record.status = "expired"
        record.updated_at = now
        _persist_signal_event(
            session,
            record,
            SIGNAL_EXPIRED_EVENT,
            old_status=old_status,
            now=now,
        )
        changed = True
    if changed:
        session.flush()
    return changed


def _ensure_signal_expiry(record: TradingSignal) -> tuple[datetime | None, bool]:
    started_at = _as_utc(record.created_at or record.detected_at)
    default_expires_at = _signal_expires_at(started_at)
    if record.expires_at is not None:
        expires_at = _as_utc(record.expires_at)
        if default_expires_at is not None and expires_at > default_expires_at:
            record.expires_at = default_expires_at
            return default_expires_at, True
        return expires_at, False
    expires_at = default_expires_at
    if expires_at is None:
        return None, False
    record.expires_at = expires_at
    return expires_at, True


def _record_is_expired(record: TradingSignal, now: datetime) -> bool:
    expires_at, _ = _ensure_signal_expiry(record)
    return expires_at is not None and _as_utc(expires_at) <= _as_utc(now)


def _expires_after(now: datetime):
    return TradingSignal.expires_at.is_(None) | (TradingSignal.expires_at > now)


def _signal_expires_at(detected_at: datetime) -> datetime | None:
    ttl_seconds = max(0, int(settings.signal_active_ttl_seconds))
    if ttl_seconds == 0:
        return None
    return _as_utc(detected_at) + timedelta(seconds=ttl_seconds)


def _resolve_references(
    session: Session,
    *,
    exchange_code: str,
    symbol: str,
    strategy_code: str,
) -> tuple[MarketExchange, MarketPair, StrategyVersion]:
    exchange = session.scalars(
        select(MarketExchange).where(MarketExchange.code == exchange_code.lower())
    ).one_or_none()
    if exchange is None:
        raise SignalReferenceError(f"Exchange is not seeded: {exchange_code}")

    pair = session.scalars(
        select(MarketPair).where(
            MarketPair.exchange_id == exchange.id,
            MarketPair.symbol == _normalize_symbol(symbol),
        )
    ).one_or_none()
    if pair is None:
        raise SignalReferenceError(f"Market pair is not seeded: {exchange_code}:{symbol}")

    strategy_version = session.scalars(
        select(StrategyVersion)
        .join(StrategyTemplate)
        .where(
            StrategyTemplate.code == strategy_code,
            StrategyVersion.status == "active",
        )
        .order_by(StrategyVersion.created_at.desc())
        .limit(1)
    ).one_or_none()
    if strategy_version is None:
        raise SignalReferenceError(f"Strategy version is not seeded: {strategy_code}")
    return exchange, pair, strategy_version


def _persist_signal_event(
    session: Session,
    record: TradingSignal,
    event_type: str,
    *,
    old_status: str | None,
    now: datetime,
) -> SignalWriteResult:
    radar_signal = _record_to_radar_signal(record)
    payload = {
        "signal": radar_signal.model_dump(mode="json"),
        "signal_key": record.signal_key,
    }
    session.add(
        TradingSignalEvent(
            signal_id=record.id,
            event_type=event_type,
            old_status=old_status,
            new_status=record.status,
            payload=payload,
            created_at=now,
        )
    )
    session.add(
        OutboxEvent(
            aggregate_type="trading_signal",
            aggregate_id=record.id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempts=0,
            created_at=now,
        )
    )
    session.flush()
    return SignalWriteResult(
        signal=radar_signal,
        created=event_type == SIGNAL_CREATED_EVENT,
        event_type=event_type,
        analytics_event=_analytics_event(record, event_type, now),
    )


def _record_to_radar_signal(record: TradingSignal) -> RadarSignal:
    snapshot = record.features_snapshot or {}
    decision = snapshot.get("decision", {}) if isinstance(snapshot.get("decision"), dict) else {}
    score_breakdown = snapshot.get("score_breakdown") or {}
    explanation = snapshot.get("explanation")
    risks = snapshot.get("risks")
    take_profit = record.take_profit or []
    trade_plan = _trade_plan_from_snapshot_or_record(snapshot, record, take_profit)
    created_at = _as_utc(record.created_at or record.detected_at)
    updated_at = _as_utc(record.updated_at or created_at)
    status = record.status
    return RadarSignal(
        id=str(record.id),
        symbol=record.pair.symbol,
        exchange=record.exchange.code,
        strategy=record.strategy_version.strategy.code,
        direction=record.direction,
        confidence=float(record.confidence),
        risk_reward=_float(record.risk_reward),
        first_target_rr=_float(snapshot.get("first_target_rr")),
        final_target_rr=_float(snapshot.get("final_target_rr")),
        selected_rr=_float(snapshot.get("selected_rr")),
        selected_rr_target=_string_or_none(snapshot.get("selected_rr_target")),
        min_rr_ratio=_float(snapshot.get("min_rr_ratio")),
        urgency=snapshot.get("urgency", "medium"),
        status=status,
        score=int(round(float(record.score))),
        timeframe=record.timeframe,
        entry_min=_float(snapshot.get("entry_min")),
        entry_max=_float(snapshot.get("entry_max")),
        stop_loss=_float(record.stop_loss),
        take_profit_1=_float(take_profit[0]) if len(take_profit) > 0 else None,
        take_profit_2=_float(take_profit[1]) if len(take_profit) > 1 else None,
        explanation=explanation if isinstance(explanation, list) else _split_explanation(record.explanation),
        risks=risks if isinstance(risks, list) else [],
        score_breakdown=SignalScoreBreakdown.model_validate(score_breakdown or {}),
        status_reason=_string_or_none(snapshot.get("status_reason")),
        quality=snapshot.get("quality") if isinstance(snapshot.get("quality"), dict) else None,
        regime=snapshot.get("regime") if isinstance(snapshot.get("regime"), dict) else None,
        setup=snapshot.get("setup") if isinstance(snapshot.get("setup"), dict) else None,
        confirmation=snapshot.get("confirmation") if isinstance(snapshot.get("confirmation"), dict) else None,
        invalidation=snapshot.get("invalidation") if isinstance(snapshot.get("invalidation"), dict) else None,
        exit_plan=snapshot.get("exit_plan") if isinstance(snapshot.get("exit_plan"), dict) else None,
        trade_plan=trade_plan,
        auto_entry=snapshot.get("auto_entry") if isinstance(snapshot.get("auto_entry"), dict) else None,
        created_at=created_at,
        updated_at=updated_at,
        expires_at=_as_utc(record.expires_at) if record.expires_at else None,
        confirmed_at=updated_at if record.status == "confirmed" else None,
        rejected_at=updated_at if record.status == "invalidated" else None,
        decision_mode=decision.get("decision_mode"),
        decision_note=decision.get("decision_note"),
        confirmed_trade_id=decision.get("confirmed_trade_id"),
    )


def _trade_plan_from_snapshot_or_record(
    snapshot: dict[str, Any],
    record: TradingSignal,
    take_profit: list[Any],
) -> TradePlan:
    trade_plan = snapshot.get("trade_plan")
    if isinstance(trade_plan, dict):
        return TradePlan.model_validate(trade_plan)
    return build_trade_plan_from_legacy_fields(
        entry_min=_float(snapshot.get("entry_min")),
        entry_max=_float(snapshot.get("entry_max")),
        stop_loss=_float(record.stop_loss),
        take_profit_1=_float(take_profit[0]) if len(take_profit) > 0 else None,
        take_profit_2=_float(take_profit[1]) if len(take_profit) > 1 else None,
        risk_reward=_float(record.risk_reward),
        first_target_rr=_float(snapshot.get("first_target_rr")),
        final_target_rr=_float(snapshot.get("final_target_rr")),
        selected_rr=_float(snapshot.get("selected_rr")),
        selected_rr_target=_string_or_none(snapshot.get("selected_rr_target")),
        min_rr_ratio=_float(snapshot.get("min_rr_ratio")),
    )


def _analytics_event(record: TradingSignal, event_type: str, now: datetime) -> dict[str, Any]:
    return {
        "signal_id": record.id,
        "signal_key": record.signal_key,
        "event_type": event_type,
        "exchange": record.exchange.code,
        "symbol": record.pair.symbol,
        "timeframe": record.timeframe,
        "strategy_code": record.strategy_version.strategy.code,
        "strategy_version": record.strategy_version.version,
        "direction": record.direction,
        "confidence": float(record.confidence),
        "score": float(record.score),
        "entry_price": record.entry_price or Decimal("0"),
        "stop_loss": record.stop_loss,
        "features_json": record.features_snapshot or {},
        "event_ts": now,
        "ingest_ts": now,
    }


def _update_record_from_signal(
    record: TradingSignal,
    signal: RadarSignal,
    db_status: str,
    *,
    expires_at: datetime | None,
) -> None:
    record.status = db_status
    record.confidence = _decimal(signal.confidence) or Decimal("0")
    record.score = _decimal(signal.score) or Decimal("0")
    record.entry_price = _entry_price(signal)
    record.stop_loss = _decimal(signal.stop_loss)
    record.take_profit = _take_profit(signal)
    record.risk_reward = _decimal(signal.risk_reward)
    record.expires_at = expires_at
    record.features_snapshot = _snapshot_from_signal(signal)
    record.explanation = "\n".join(signal.explanation) if signal.explanation else None


def _apply_signal_updates(
    record: TradingSignal,
    snapshot: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    if "entry_min" in updates:
        snapshot["entry_min"] = updates["entry_min"]
    if "entry_max" in updates:
        snapshot["entry_max"] = updates["entry_max"]
    entry = _snapshot_entry_price(snapshot)
    if entry is not None:
        record.entry_price = _decimal(entry)
    if "stop_loss" in updates:
        record.stop_loss = _decimal(updates["stop_loss"])
    take_profit = list(record.take_profit or [])
    if "take_profit_1" in updates:
        if take_profit:
            take_profit[0] = updates["take_profit_1"]
        else:
            take_profit.append(updates["take_profit_1"])
    if "take_profit_2" in updates:
        if len(take_profit) >= 2:
            take_profit[1] = updates["take_profit_2"]
        else:
            while len(take_profit) < 1:
                take_profit.append(None)
            take_profit.append(updates["take_profit_2"])
    record.take_profit = [price for price in take_profit if price is not None]
    if "risk_reward" in updates:
        record.risk_reward = _decimal(updates["risk_reward"])
    if "trade_plan" in updates:
        snapshot["trade_plan"] = _model_dump_optional(updates["trade_plan"])
    for key in (
        "confirmation",
        "first_target_rr",
        "final_target_rr",
        "selected_rr",
        "selected_rr_target",
        "min_rr_ratio",
    ):
        if key in updates:
            snapshot[key] = updates[key]


def _snapshot_entry_price(snapshot: dict[str, Any]) -> float | None:
    entry_min = _float(snapshot.get("entry_min"))
    entry_max = _float(snapshot.get("entry_max"))
    if entry_min is not None and entry_max is not None:
        return (entry_min + entry_max) / 2
    return entry_min if entry_min is not None else entry_max


def _snapshot_from_signal(signal: RadarSignal) -> dict[str, Any]:
    return {
        "entry_min": signal.entry_min,
        "entry_max": signal.entry_max,
        "urgency": signal.urgency,
        "explanation": signal.explanation,
        "risks": signal.risks,
        "first_target_rr": signal.first_target_rr,
        "final_target_rr": signal.final_target_rr,
        "selected_rr": signal.selected_rr,
        "selected_rr_target": signal.selected_rr_target,
        "min_rr_ratio": signal.min_rr_ratio,
        "score_breakdown": signal.score_breakdown.model_dump(mode="json"),
        "status_reason": signal.status_reason,
        "quality": _model_dump_optional(signal.quality),
        "regime": _model_dump_optional(signal.regime),
        "setup": _model_dump_optional(signal.setup),
        "confirmation": _model_dump_optional(signal.confirmation),
        "invalidation": _model_dump_optional(signal.invalidation),
        "exit_plan": _model_dump_optional(signal.exit_plan),
        "trade_plan": _trade_plan_snapshot(signal),
        "auto_entry": _model_dump_optional(signal.auto_entry),
        "decision": {
            "confirmed_trade_id": signal.confirmed_trade_id,
            "decision_mode": signal.decision_mode,
            "decision_note": signal.decision_note,
        },
    }


def _snapshot_from_strategy_signal(
    signal: StrategySignal,
    *,
    explanation: list[str] | None,
) -> dict[str, Any]:
    return {
        "entry_min": signal.entry_min,
        "entry_max": signal.entry_max,
        "urgency": signal.urgency,
        "explanation": explanation or signal.explanation,
        "risks": signal.risks,
        "first_target_rr": signal.first_target_rr,
        "final_target_rr": signal.final_target_rr,
        "selected_rr": signal.selected_rr,
        "selected_rr_target": signal.selected_rr_target,
        "min_rr_ratio": signal.min_rr_ratio,
        "score_breakdown": signal.score_breakdown.model_dump(mode="json"),
        "source_timestamp": signal.timestamp,
        "status_reason": signal.status_reason,
        "quality": _model_dump_optional(signal.quality),
        "regime": _model_dump_optional(signal.regime),
        "setup": _model_dump_optional(signal.setup),
        "confirmation": _model_dump_optional(signal.confirmation),
        "invalidation": _model_dump_optional(signal.invalidation),
        "exit_plan": _model_dump_optional(signal.exit_plan),
        "trade_plan": _trade_plan_snapshot(signal),
        "auto_entry": _model_dump_optional(signal.auto_entry),
    }


def _merge_strategy_snapshot(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return incoming
    merged = dict(incoming)
    for key in ("auto_entry", "decision", "lifecycle_events"):
        value = existing.get(key)
        if value is not None and key not in merged:
            merged[key] = value
        elif value is not None and key == "auto_entry":
            merged[key] = value
    return merged


def _api_status_to_db(status: str) -> str:
    if status == "rejected":
        return "invalidated"
    return status


def _strategy_signal_status_to_db(status: str, score: int) -> str:
    if status in OPEN_SIGNAL_STATUSES:
        return status
    if status == "rejected":
        return "invalidated"
    return "actionable" if score >= 70 else "watchlist"


def _signal_key(signal: StrategySignal, exchange: str, detected_at: datetime) -> str:
    return ":".join(
        [
            exchange.lower(),
            _normalize_symbol(signal.symbol),
            signal.strategy,
            signal.timeframe,
            signal.direction.lower(),
            detected_at.isoformat(),
        ]
    )


def _normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":PERP", "").upper()


def _timestamp_to_datetime(timestamp: int) -> datetime:
    seconds = timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _strategy_entry_price(signal: StrategySignal) -> float | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    return signal.entry_min if signal.entry_min is not None else signal.entry_max


def _entry_price(signal: RadarSignal) -> Decimal | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return _decimal((signal.entry_min + signal.entry_max) / 2)
    return _decimal(signal.entry_min if signal.entry_min is not None else signal.entry_max)


def _take_profit(signal: RadarSignal) -> list[float]:
    return [price for price in (signal.take_profit_1, signal.take_profit_2) if price is not None]


def _take_profit_from_strategy_signal(signal: StrategySignal) -> list[float]:
    return [price for price in (signal.take_profit_1, signal.take_profit_2) if price is not None]


def _trade_plan_snapshot(signal: RadarSignal | StrategySignal) -> dict[str, Any]:
    trade_plan = signal.trade_plan or build_trade_plan_from_legacy_fields(
        entry_min=signal.entry_min,
        entry_max=signal.entry_max,
        stop_loss=signal.stop_loss,
        take_profit_1=signal.take_profit_1,
        take_profit_2=signal.take_profit_2,
        risk_reward=signal.risk_reward,
        first_target_rr=signal.first_target_rr,
        final_target_rr=signal.final_target_rr,
        selected_rr=signal.selected_rr,
        selected_rr_target=signal.selected_rr_target,
        min_rr_ratio=signal.min_rr_ratio,
    )
    return trade_plan.model_dump(mode="json")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _split_explanation(explanation: str | None) -> list[str]:
    if not explanation:
        return []
    return [line for line in explanation.splitlines() if line]


def _explanation_text(explanation: list[str]) -> str | None:
    return "\n".join(explanation) if explanation else None


def _model_dump_optional(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
