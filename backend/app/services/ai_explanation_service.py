from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.models.ai import SignalAIExplanation
from app.models.signal import TradingSignal
from app.schemas.ai import (
    AIExplanationNotReadyResponse,
    SignalAIExplanationCreate,
    SignalAIExplanationGenerateRequest,
    SignalAIExplanationResponse,
)


class AIExplanationOrchestrator(Protocol):
    def generate(
        self,
        signal: TradingSignal,
        request: SignalAIExplanationGenerateRequest,
    ) -> SignalAIExplanationCreate:
        ...


class AIExplanationNotReadyError(NotImplementedError):
    def __init__(self, response: AIExplanationNotReadyResponse) -> None:
        super().__init__(response.message)
        self.response = response


class AIExplanationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        orchestrator: AIExplanationOrchestrator | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._orchestrator = orchestrator

    def list_for_signal(self, signal_id: str | UUID, limit: int = 20) -> list[SignalAIExplanationResponse]:
        with self._session_factory() as session:
            signal = _get_signal(session, signal_id)
            if signal is None:
                raise LookupError(f"Signal is not found: {signal_id}")
            records = session.scalars(
                select(SignalAIExplanation)
                .where(SignalAIExplanation.signal_id == signal.id)
                .order_by(SignalAIExplanation.created_at.desc())
                .limit(limit)
            ).all()
            return [_explanation_to_response(record) for record in records]

    def save_explanation(self, payload: SignalAIExplanationCreate) -> SignalAIExplanationResponse:
        with self._session_factory() as session:
            signal = _get_signal(session, payload.signal_id)
            if signal is None:
                raise LookupError(f"Signal is not found: {payload.signal_id}")
            record = SignalAIExplanation(
                signal_id=signal.id,
                model_provider=payload.model_provider.strip(),
                model_name=payload.model_name.strip(),
                prompt_hash=payload.prompt_hash.strip(),
                explanation_md=payload.explanation_md.strip(),
                risk_notes=payload.risk_notes,
            )
            session.add(record)
            session.commit()
            return _explanation_to_response(record)

    def generate_for_signal(
        self,
        signal_id: str | UUID,
        request: SignalAIExplanationGenerateRequest,
    ) -> SignalAIExplanationResponse:
        with self._session_factory() as session:
            signal = _get_signal(session, signal_id)
            if signal is None:
                raise LookupError(f"Signal is not found: {signal_id}")
            if self._orchestrator is None:
                raise AIExplanationNotReadyError(
                    AIExplanationNotReadyResponse(
                        message=(
                            "AI explanation generation is not implemented yet. "
                            "Generated explanations will be stored in PostgreSQL signal_ai_explanations."
                        ),
                        signal_id=signal.id,
                        model_provider=request.model_provider,
                        model_name=request.model_name,
                        details={
                            "signal_key": signal.signal_key,
                            "exchange": signal.exchange.code,
                            "symbol": signal.pair.symbol,
                            "timeframe": signal.timeframe,
                            "strategy_version_id": str(signal.strategy_version_id),
                            "context_keys": sorted(request.context.keys()),
                        },
                    )
                )
            payload = self._orchestrator.generate(signal, request)
        return self.save_explanation(payload)


def _get_signal(session: Session, signal_id: str | UUID) -> TradingSignal | None:
    statement = select(TradingSignal).options(
        joinedload(TradingSignal.exchange),
        joinedload(TradingSignal.pair),
    )
    signal_uuid = _parse_uuid(signal_id)
    if signal_uuid is not None:
        signal = session.scalars(statement.where(TradingSignal.id == signal_uuid)).one_or_none()
        if signal is not None:
            return signal
    return session.scalars(statement.where(TradingSignal.signal_key == str(signal_id))).one_or_none()


def _explanation_to_response(record: SignalAIExplanation) -> SignalAIExplanationResponse:
    return SignalAIExplanationResponse(
        id=record.id,
        signal_id=record.signal_id,
        model_provider=record.model_provider,
        model_name=record.model_name,
        prompt_hash=record.prompt_hash,
        explanation_md=record.explanation_md,
        risk_notes=record.risk_notes,
        created_at=record.created_at,
    )


def _parse_uuid(value: str | UUID) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


ai_explanation_service = AIExplanationService()
