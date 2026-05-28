from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("length(trim(aggregate_type)) > 0", name="ck_outbox_events_aggregate_type_not_blank"),
        CheckConstraint("length(trim(event_type)) > 0", name="ck_outbox_events_event_type_not_blank"),
        CheckConstraint("length(trim(status)) > 0", name="ck_outbox_events_status_not_blank"),
        CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts_non_negative"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=text("now()"),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "idx_outbox_pending",
    OutboxEvent.status,
    OutboxEvent.next_retry_at,
    OutboxEvent.created_at,
    postgresql_where=OutboxEvent.status == "pending",
)
Index(
    "ix_outbox_events_aggregate",
    OutboxEvent.aggregate_type,
    OutboxEvent.aggregate_id,
    OutboxEvent.created_at.desc(),
)
