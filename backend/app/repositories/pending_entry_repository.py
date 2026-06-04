from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.domain.pending_entry_intent import ACTIVE_PENDING_ENTRY_INTENT_STATUSES
from app.models.pending_entry import PendingEntryIntent
from app.schemas.pending_entry import PendingEntryIntentCreate, PendingEntryIntentRead, PendingEntryIntentStatus


class PendingEntryIntentRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def create_intent(self, intent: PendingEntryIntentCreate) -> PendingEntryIntentRead:
        with self._session_factory() as session:
            existing = _get_by_idempotency_key(session, intent.idempotency_key)
            if existing is not None:
                return _to_read(existing)
            active = _get_active_for_user_signal_mode(
                session,
                user_id=intent.user_id,
                signal_id=intent.signal_id,
                mode=intent.mode,
            )
            if active is not None:
                return _to_read(active)

            now = datetime.now(timezone.utc)
            record = PendingEntryIntent(
                id=uuid4(),
                user_id=intent.user_id,
                signal_id=intent.signal_id,
                strategy_id=intent.strategy_id,
                mode=intent.mode,
                status=intent.status,
                exchange=intent.exchange.strip().lower(),
                symbol=_normalize_symbol(intent.symbol),
                side=intent.side,
                entry_min=intent.entry_min,
                entry_max=intent.entry_max,
                entry_price_policy=intent.entry_price_policy.strip(),
                stop_loss=intent.stop_loss,
                targets_snapshot=intent.targets_snapshot,
                accepted_trade_plan_snapshot=intent.accepted_trade_plan_snapshot,
                accepted_trade_plan_hash=intent.accepted_trade_plan_hash.strip(),
                accepted_signal_status=intent.accepted_signal_status,
                accepted_signal_version=intent.accepted_signal_version,
                accepted_signal_fingerprint=intent.accepted_signal_fingerprint,
                execution_profile_snapshot=intent.execution_profile_snapshot,
                request_snapshot=intent.request_snapshot,
                idempotency_key=intent.idempotency_key.strip(),
                expires_at=intent.expires_at,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = _get_by_idempotency_key(session, intent.idempotency_key)
                if existing is not None:
                    return _to_read(existing)
                active = _get_active_for_user_signal_mode(
                    session,
                    user_id=intent.user_id,
                    signal_id=intent.signal_id,
                    mode=intent.mode,
                )
                if active is not None:
                    return _to_read(active)
                raise
            return _to_read(record)

    def get_by_id(self, intent_id: str | UUID) -> PendingEntryIntentRead | None:
        parsed_id = _parse_uuid(intent_id)
        if parsed_id is None:
            return None
        with self._session_factory() as session:
            record = session.get(PendingEntryIntent, parsed_id)
            return _to_read(record) if record is not None else None

    def get_active_for_user_signal_mode(
        self,
        *,
        user_id: str | UUID,
        signal_id: str | UUID,
        mode: str,
    ) -> PendingEntryIntentRead | None:
        parsed_user_id = _parse_uuid(user_id)
        parsed_signal_id = _parse_uuid(signal_id)
        if parsed_user_id is None or parsed_signal_id is None:
            return None
        with self._session_factory() as session:
            record = _get_active_for_user_signal_mode(
                session,
                user_id=parsed_user_id,
                signal_id=parsed_signal_id,
                mode=mode,
            )
            return _to_read(record) if record is not None else None

    def list_pending_for_market(self, exchange: str, symbol: str) -> list[PendingEntryIntentRead]:
        with self._session_factory() as session:
            records = session.scalars(
                select(PendingEntryIntent)
                .where(
                    PendingEntryIntent.exchange == exchange.strip().lower(),
                    PendingEntryIntent.symbol == _normalize_symbol(symbol),
                    PendingEntryIntent.status == "pending",
                )
                .order_by(PendingEntryIntent.created_at.asc())
            ).all()
            return [_to_read(record) for record in records]

    def list_active_for_signal(self, signal_id: str | UUID) -> list[PendingEntryIntentRead]:
        parsed_signal_id = _parse_uuid(signal_id)
        if parsed_signal_id is None:
            return []
        with self._session_factory() as session:
            records = session.scalars(
                select(PendingEntryIntent)
                .where(
                    PendingEntryIntent.signal_id == parsed_signal_id,
                    PendingEntryIntent.status.in_(ACTIVE_PENDING_ENTRY_INTENT_STATUSES),
                )
                .order_by(PendingEntryIntent.created_at.asc())
            ).all()
            return [_to_read(record) for record in records]

    def list_active_for_signal_user(
        self,
        *,
        signal_id: str | UUID,
        user_id: str | UUID,
    ) -> list[PendingEntryIntentRead]:
        parsed_signal_id = _parse_uuid(signal_id)
        parsed_user_id = _parse_uuid(user_id)
        if parsed_signal_id is None or parsed_user_id is None:
            return []
        with self._session_factory() as session:
            records = session.scalars(
                select(PendingEntryIntent)
                .where(
                    PendingEntryIntent.signal_id == parsed_signal_id,
                    PendingEntryIntent.user_id == parsed_user_id,
                    PendingEntryIntent.status.in_(ACTIVE_PENDING_ENTRY_INTENT_STATUSES),
                )
                .order_by(PendingEntryIntent.created_at.asc())
            ).all()
            return [_to_read(record) for record in records]

    def transition_status(
        self,
        intent_id: str | UUID,
        *,
        status: PendingEntryIntentStatus,
        failure_reason: str | None = None,
        filled_trade_id: str | UUID | None = None,
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        parsed_id = _parse_uuid(intent_id)
        if parsed_id is None:
            return None
        parsed_trade_id = _parse_uuid(filled_trade_id) if filled_trade_id is not None else None
        if filled_trade_id is not None and parsed_trade_id is None:
            raise ValueError("filled_trade_id must be a valid UUID")
        with self._session_factory() as session:
            record = session.get(PendingEntryIntent, parsed_id)
            if record is None:
                return None
            changed_at = now or datetime.now(timezone.utc)
            record.status = status
            record.updated_at = changed_at
            record.failure_reason = failure_reason
            if status == "triggered" and record.triggered_at is None:
                record.triggered_at = changed_at
            if status == "filled":
                record.filled_at = changed_at
                record.filled_trade_id = parsed_trade_id
            session.commit()
            return _to_read(record)

    def lock_for_trigger(
        self,
        intent_id: str | UUID,
        *,
        session: Session,
    ) -> PendingEntryIntent | None:
        parsed_id = _parse_uuid(intent_id)
        if parsed_id is None:
            return None
        return session.scalars(
            select(PendingEntryIntent)
            .where(
                PendingEntryIntent.id == parsed_id,
                PendingEntryIntent.status == "pending",
            )
            .with_for_update()
        ).one_or_none()


def _get_by_idempotency_key(session: Session, idempotency_key: str) -> PendingEntryIntent | None:
    return session.scalars(
        select(PendingEntryIntent).where(PendingEntryIntent.idempotency_key == idempotency_key.strip())
    ).one_or_none()


def _get_active_for_user_signal_mode(
    session: Session,
    *,
    user_id: UUID,
    signal_id: UUID,
    mode: str,
) -> PendingEntryIntent | None:
    return session.scalars(
        select(PendingEntryIntent).where(
            PendingEntryIntent.user_id == user_id,
            PendingEntryIntent.signal_id == signal_id,
            PendingEntryIntent.mode == mode.strip().lower(),
            PendingEntryIntent.status.in_(ACTIVE_PENDING_ENTRY_INTENT_STATUSES),
        )
    ).first()


def _to_read(record: PendingEntryIntent) -> PendingEntryIntentRead:
    return PendingEntryIntentRead.model_validate(record)


def _normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":PERP", "").upper()


def _parse_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None
