from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.pending_entry_intent import (
    ACTIVE_PENDING_ENTRY_INTENT_STATUSES,
    PENDING_ENTRY_INTENT_STATUSES,
)


def _sql_in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class PendingEntryIntent(Base):
    __tablename__ = "pending_entry_intents"
    __table_args__ = (
        CheckConstraint("mode IN ('virtual', 'real')", name="ck_pending_entry_intents_mode"),
        CheckConstraint(
            f"status IN ({_sql_in(PENDING_ENTRY_INTENT_STATUSES)})",
            name="ck_pending_entry_intents_status",
        ),
        CheckConstraint("side IN ('long', 'short')", name="ck_pending_entry_intents_side"),
        CheckConstraint("length(trim(exchange)) > 0", name="ck_pending_entry_intents_exchange_not_blank"),
        CheckConstraint("length(trim(symbol)) > 0", name="ck_pending_entry_intents_symbol_not_blank"),
        CheckConstraint(
            "length(trim(entry_price_policy)) > 0",
            name="ck_pending_entry_intents_entry_policy_not_blank",
        ),
        CheckConstraint(
            "length(trim(accepted_trade_plan_hash)) > 0",
            name="ck_pending_entry_intents_trade_plan_hash_not_blank",
        ),
        CheckConstraint(
            "length(trim(accepted_signal_status)) > 0",
            name="ck_pending_entry_intents_signal_status_not_blank",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_pending_entry_intents_idempotency_key_not_blank",
        ),
        CheckConstraint("entry_min > 0", name="ck_pending_entry_intents_entry_min_positive"),
        CheckConstraint("entry_max > 0", name="ck_pending_entry_intents_entry_max_positive"),
        CheckConstraint("entry_max >= entry_min", name="ck_pending_entry_intents_entry_range_order"),
        CheckConstraint("stop_loss > 0", name="ck_pending_entry_intents_stop_loss_positive"),
        UniqueConstraint("idempotency_key", name="uq_pending_entry_intents_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_pending_entry_intents_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_signals.id", name="fk_pending_entry_intents_signal_id", ondelete="CASCADE"),
        nullable=False,
    )
    strategy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("strategy_templates.id", name="fk_pending_entry_intents_strategy_id", ondelete="SET NULL"),
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))

    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)

    entry_min: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_max: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_price_policy: Mapped[str] = mapped_column(Text, nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    targets_snapshot: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    accepted_trade_plan_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    accepted_trade_plan_hash: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_signal_status: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_signal_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_signal_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution_profile_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_trade_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["AppUser"] = relationship(back_populates="pending_entry_intents")
    signal: Mapped["TradingSignal"] = relationship(back_populates="pending_entry_intents")
    strategy: Mapped["StrategyTemplate | None"] = relationship()


Index(
    "idx_pending_entry_intents_market_status",
    PendingEntryIntent.exchange,
    PendingEntryIntent.symbol,
    PendingEntryIntent.status,
)
Index(
    "idx_pending_entry_intents_user_signal_status",
    PendingEntryIntent.user_id,
    PendingEntryIntent.signal_id,
    PendingEntryIntent.status,
)
Index(
    "uq_pending_entry_intents_active_user_signal_mode",
    PendingEntryIntent.user_id,
    PendingEntryIntent.signal_id,
    PendingEntryIntent.mode,
    unique=True,
    postgresql_where=PendingEntryIntent.status.in_(ACTIVE_PENDING_ENTRY_INTENT_STATUSES),
)
