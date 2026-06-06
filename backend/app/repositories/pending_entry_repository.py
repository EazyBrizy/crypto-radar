from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.domain.pending_entry_intent import (
    ACTIVE_PENDING_ENTRY_INTENT_STATUSES,
    TERMINAL_PENDING_ENTRY_INTENT_STATUSES,
)
from app.domain.pending_entry_reason import (
    PENDING_ENTRY_GATE_SNAPSHOT_KEY,
    PENDING_ENTRY_LAST_REASON_KEY,
    PENDING_ENTRY_TERMINAL_REASON_KEY,
    pending_entry_reason_code_from_snapshot,
)
from app.models.pending_entry import PendingEntryIntent
from app.schemas.pending_entry import (
    PendingEntryIntentCreate,
    PendingEntryIntentRead,
    PendingEntryIntentStatus,
    PendingEntryView,
)


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

    def list_history_for_user_signal_mode(
        self,
        *,
        signal_id: str | UUID,
        user_id: str | UUID,
        mode: str,
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
                    PendingEntryIntent.mode == mode.strip().lower(),
                    PendingEntryIntent.status.in_(TERMINAL_PENDING_ENTRY_INTENT_STATUSES),
                )
                .order_by(PendingEntryIntent.updated_at.desc(), PendingEntryIntent.created_at.desc())
            ).all()
            return [_to_read(record) for record in records]

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

    def list_active_for_user(
        self,
        *,
        user_id: str | UUID,
        mode: str | None = None,
        limit: int = 100,
    ) -> list[PendingEntryIntentRead]:
        return self._list_for_user(
            user_id=user_id,
            statuses=ACTIVE_PENDING_ENTRY_INTENT_STATUSES,
            mode=mode,
            limit=limit,
            active_order=True,
        )

    def list_history_for_user(
        self,
        *,
        user_id: str | UUID,
        mode: str | None = None,
        limit: int = 50,
    ) -> list[PendingEntryIntentRead]:
        return self._list_for_user(
            user_id=user_id,
            statuses=TERMINAL_PENDING_ENTRY_INTENT_STATUSES,
            mode=mode,
            limit=limit,
            active_order=False,
        )

    def _list_for_user(
        self,
        *,
        user_id: str | UUID,
        statuses: tuple[str, ...],
        mode: str | None,
        limit: int,
        active_order: bool,
    ) -> list[PendingEntryIntentRead]:
        parsed_user_id = _parse_uuid(user_id)
        if parsed_user_id is None:
            return []
        bounded_limit = max(1, min(limit, 200))
        with self._session_factory() as session:
            statement = select(PendingEntryIntent).where(
                PendingEntryIntent.user_id == parsed_user_id,
                PendingEntryIntent.status.in_(statuses),
            )
            if mode:
                statement = statement.where(PendingEntryIntent.mode == mode.strip().lower())
            if active_order:
                statement = statement.order_by(PendingEntryIntent.created_at.asc(), PendingEntryIntent.updated_at.asc())
            else:
                statement = statement.order_by(PendingEntryIntent.updated_at.desc(), PendingEntryIntent.created_at.desc())
            records = session.scalars(statement.limit(bounded_limit)).all()
            return [_to_read(record) for record in records]

    def transition_status(
        self,
        intent_id: str | UUID,
        *,
        status: PendingEntryIntentStatus,
        failure_reason: str | None = None,
        filled_trade_id: str | UUID | None = None,
        reason_code: str | None = None,
        gate_snapshot: dict[str, Any] | None = None,
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
            if reason_code is not None or gate_snapshot is not None:
                record.request_snapshot = _request_snapshot_with_reason_code(
                    record.request_snapshot,
                    status=status,
                    reason_code=reason_code,
                    gate_snapshot=gate_snapshot,
                )
            if status == "triggered" and record.triggered_at is None:
                record.triggered_at = changed_at
            if status == "filled":
                record.filled_at = changed_at
                record.filled_trade_id = parsed_trade_id
            session.commit()
            return _to_read(record)

    def update_reconfirmed_acceptance(
        self,
        intent_id: str | UUID,
        *,
        entry_min: Decimal,
        entry_max: Decimal,
        entry_price_policy: str,
        stop_loss: Decimal,
        targets_snapshot: dict[str, Any] | list[Any],
        accepted_trade_plan_snapshot: dict[str, Any],
        accepted_trade_plan_hash: str,
        accepted_signal_status: str,
        accepted_signal_version: str | None,
        accepted_signal_fingerprint: str | None,
        execution_profile_snapshot: dict[str, Any],
        request_snapshot: dict[str, Any],
        expires_at: datetime | None,
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        parsed_id = _parse_uuid(intent_id)
        if parsed_id is None:
            return None
        with self._session_factory() as session:
            record = session.get(PendingEntryIntent, parsed_id)
            if record is None:
                return None
            changed_at = now or datetime.now(timezone.utc)
            record.status = "pending"
            record.entry_min = entry_min
            record.entry_max = entry_max
            record.entry_price_policy = entry_price_policy.strip()
            record.stop_loss = stop_loss
            record.targets_snapshot = targets_snapshot
            record.accepted_trade_plan_snapshot = accepted_trade_plan_snapshot
            record.accepted_trade_plan_hash = accepted_trade_plan_hash.strip()
            record.accepted_signal_status = accepted_signal_status
            record.accepted_signal_version = accepted_signal_version
            record.accepted_signal_fingerprint = accepted_signal_fingerprint
            record.execution_profile_snapshot = execution_profile_snapshot
            record.request_snapshot = request_snapshot
            record.expires_at = expires_at
            record.failure_reason = None
            record.triggered_at = None
            record.filled_at = None
            record.filled_trade_id = None
            record.updated_at = changed_at
            session.commit()
            return _to_read(record)

    def update_market_review_snapshot(
        self,
        intent_id: str | UUID,
        *,
        request_snapshot: dict[str, Any],
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        parsed_id = _parse_uuid(intent_id)
        if parsed_id is None:
            return None
        with self._session_factory() as session:
            record = session.get(PendingEntryIntent, parsed_id)
            if record is None:
                return None
            record.request_snapshot = request_snapshot
            record.updated_at = now or datetime.now(timezone.utc)
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
    read = PendingEntryIntentRead.model_validate(record)
    terminal = record.status in TERMINAL_PENDING_ENTRY_INTENT_STATUSES
    reason_code = pending_entry_reason_code_from_snapshot(record.request_snapshot, terminal=terminal)
    view = _pending_entry_view(record, reason_code) if reason_code is not None or record.failure_reason else None
    return read.model_copy(update={"reason_code": reason_code, "view": view})


def _request_snapshot_with_reason_code(
    request_snapshot: Any,
    *,
    status: str,
    reason_code: str | None,
    gate_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = dict(request_snapshot or {}) if isinstance(request_snapshot, dict) else {}
    if reason_code is not None:
        snapshot[PENDING_ENTRY_LAST_REASON_KEY] = reason_code
        if status in TERMINAL_PENDING_ENTRY_INTENT_STATUSES:
            snapshot[PENDING_ENTRY_TERMINAL_REASON_KEY] = reason_code
    if gate_snapshot is not None:
        snapshot[PENDING_ENTRY_GATE_SNAPSHOT_KEY] = gate_snapshot
    return snapshot


def _pending_entry_view(record: PendingEntryIntent, reason_code: str | None) -> PendingEntryView:
    return PendingEntryView(
        status_label=_status_label(record.status),
        status_tone=_status_tone(record.status),
        reason_code=reason_code,
        reason=record.failure_reason or _status_label(record.status),
        technical_message=record.failure_reason,
        entry_zone=f"{record.entry_min}-{record.entry_max}",
        current_price=_request_snapshot_current_price(record.request_snapshot),
    )


def _request_snapshot_current_price(snapshot: Any) -> Decimal | None:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get("pending_entry_current_price")
    if value is None:
        gate_snapshot = snapshot.get(PENDING_ENTRY_GATE_SNAPSHOT_KEY)
        if isinstance(gate_snapshot, dict):
            value = gate_snapshot.get("reference_price")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _status_label(status: str) -> str:
    labels = {
        "pending": "Waiting for entry",
        "triggered": "Entry touched",
        "filling": "Filling",
        "filled": "Filled",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "expired": "Expired",
        "requires_reconfirmation": "Needs reconfirmation",
    }
    return labels.get(status, status.replace("_", " ").title())


def _status_tone(status: str) -> str:
    if status == "filled":
        return "green"
    if status in {"failed", "cancelled", "expired"}:
        return "red"
    if status == "requires_reconfirmation":
        return "yellow"
    if status in {"triggered", "filling"}:
        return "blue"
    return "neutral"


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
