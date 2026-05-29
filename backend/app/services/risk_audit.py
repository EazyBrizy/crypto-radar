from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.risk import RiskDecisionRecord
from app.models.user import AppUser
from app.schemas.risk import RiskDecision
from app.services.bootstrap_service import DEMO_USERNAME


class RiskAuditService:
    """Persists backend risk-gate decisions for preview and execution audit."""

    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def record_decision(
        self,
        *,
        decision: RiskDecision,
        user_id: str,
        signal_id: str | UUID | None = None,
        portfolio_id: str | UUID | None = None,
        order_id: str | UUID | None = None,
        position_id: str | UUID | None = None,
        input_snapshot: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> UUID:
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
            record = RiskDecisionRecord(
                user_id=user.id,
                signal_id=_parse_uuid(signal_id),
                portfolio_id=_parse_uuid(portfolio_id),
                order_id=_parse_uuid(order_id),
                position_id=_parse_uuid(position_id),
                mode=decision.mode,
                instrument_type=decision.instrument_type,
                stage=decision.stage,
                status=decision.status,
                blockers=decision.blockers,
                warnings=decision.warnings,
                input_snapshot=input_snapshot or {},
                result_snapshot=decision.model_dump(mode="json"),
                created_at=created_at or datetime.now(timezone.utc),
            )
            session.add(record)
            session.commit()
            return record.id


def _resolve_user(session: Session, user_id: str) -> AppUser:
    user_uuid = _parse_uuid(user_id)
    if user_uuid is not None:
        user = session.get(AppUser, user_uuid)
        if user is not None:
            return user
    user = session.scalars(
        select(AppUser).where((AppUser.username == user_id) | (AppUser.email == user_id))
    ).one_or_none()
    if user is not None:
        return user
    if user_id == "demo_user":
        user = session.scalars(select(AppUser).where(AppUser.username == DEMO_USERNAME)).one_or_none()
        if user is not None:
            return user
    raise ValueError(f"User is not seeded: {user_id}")


def _parse_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


risk_audit_service = RiskAuditService()
