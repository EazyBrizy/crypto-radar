from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.pending_entry import PendingEntryIntent
from app.repositories.pending_entry_repository import PendingEntryIntentRepository
from app.schemas.pending_entry import PendingEntryIntentCreate, PendingEntryIntentRead, PendingEntryIntentStatus


class PendingEntryIntentService:
    def __init__(self, repository: PendingEntryIntentRepository | None = None) -> None:
        self._repository = repository or PendingEntryIntentRepository()

    def create_intent(self, intent: PendingEntryIntentCreate) -> PendingEntryIntentRead:
        return self._repository.create_intent(intent)

    def get_by_id(self, intent_id: str | UUID) -> PendingEntryIntentRead | None:
        return self._repository.get_by_id(intent_id)

    def list_pending_for_market(self, exchange: str, symbol: str) -> list[PendingEntryIntentRead]:
        return self._repository.list_pending_for_market(exchange, symbol)

    def transition_status(
        self,
        intent_id: str | UUID,
        *,
        status: PendingEntryIntentStatus,
        failure_reason: str | None = None,
        filled_trade_id: str | UUID | None = None,
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        return self._repository.transition_status(
            intent_id,
            status=status,
            failure_reason=failure_reason,
            filled_trade_id=filled_trade_id,
            now=now,
        )

    def lock_for_trigger(self, intent_id: str | UUID, *, session: Session) -> PendingEntryIntent | None:
        return self._repository.lock_for_trigger(intent_id, session=session)


pending_entry_intent_service = PendingEntryIntentService()
