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
        pending_entry_intent_id: str | UUID | None = None,
        portfolio_id: str | UUID | None = None,
        order_id: str | UUID | None = None,
        position_id: str | UUID | None = None,
        input_snapshot: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> UUID:
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
            input_payload = dict(input_snapshot or {})
            trace = _trace_from_decision(decision, input_payload)
            resolved_signal_id = signal_id or trace.get("signal_id")
            resolved_pending_entry_intent_id = (
                pending_entry_intent_id or trace.get("pending_entry_intent_id")
            )
            record = RiskDecisionRecord(
                user_id=user.id,
                signal_id=_parse_uuid(resolved_signal_id),
                pending_entry_intent_id=_parse_uuid(resolved_pending_entry_intent_id),
                portfolio_id=_parse_uuid(portfolio_id),
                order_id=_parse_uuid(order_id),
                position_id=_parse_uuid(position_id),
                mode=decision.mode,
                instrument_type=decision.instrument_type,
                stage=decision.stage,
                status=decision.status,
                blockers=decision.blockers,
                warnings=decision.warnings,
                input_snapshot=input_payload,
                result_snapshot=decision.model_dump(mode="json"),
                created_at=created_at or datetime.now(timezone.utc),
            )
            session.add(record)
            session.flush()
            trace = _completed_trace(
                trace,
                risk_decision_id=record.id,
                signal_id=resolved_signal_id,
                pending_entry_intent_id=resolved_pending_entry_intent_id,
                position_id=position_id,
                decision_mode=decision.mode,
            )
            record.input_snapshot = _snapshot_with_trace(input_payload, trace)
            record.result_snapshot = _snapshot_with_trace(
                decision.model_dump(mode="json"),
                trace,
            )
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


def _trace_from_decision(decision: RiskDecision, input_snapshot: dict[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    decision_trace = decision.lifecycle_trace.model_dump(mode="json", exclude_none=True)
    if decision_trace:
        trace.update(decision_trace)
    input_trace = input_snapshot.get("lifecycle_trace")
    if isinstance(input_trace, dict):
        trace.update({key: value for key, value in input_trace.items() if value is not None})
    request = input_snapshot.get("request")
    if isinstance(request, dict):
        metadata = request.get("metadata")
        if isinstance(metadata, dict):
            metadata_trace = metadata.get("lifecycle_trace")
            if isinstance(metadata_trace, dict):
                trace.update({key: value for key, value in metadata_trace.items() if value is not None})
            if metadata.get("pending_entry_intent_id") is not None:
                trace["pending_entry_intent_id"] = metadata["pending_entry_intent_id"]
    return trace


def _completed_trace(
    trace: dict[str, Any],
    *,
    risk_decision_id: UUID,
    signal_id: str | UUID | None,
    pending_entry_intent_id: str | UUID | None,
    position_id: str | UUID | None,
    decision_mode: str,
) -> dict[str, Any]:
    completed = {key: value for key, value in trace.items() if value is not None}
    completed["risk_decision_id"] = str(risk_decision_id)
    completed["audit_id"] = str(risk_decision_id)
    if signal_id is not None:
        completed["signal_id"] = str(signal_id)
    if pending_entry_intent_id is not None:
        completed["pending_entry_intent_id"] = str(pending_entry_intent_id)
    if decision_mode == "virtual" and position_id is not None and not completed.get("virtual_trade_id"):
        completed["virtual_trade_id"] = str(position_id)
    return completed


def _snapshot_with_trace(snapshot: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    updated = dict(snapshot)
    updated["lifecycle_trace"] = trace
    return updated


risk_audit_service = RiskAuditService()
