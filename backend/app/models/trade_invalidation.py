from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TradeInvalidationAction(Base):
    __tablename__ = "trade_invalidation_actions"
    __table_args__ = (
        CheckConstraint("mode IN ('virtual', 'real')", name="ck_trade_invalidation_actions_mode"),
        CheckConstraint(
            "action IN ('close_market', 'keep_stop_loss', 'dismissed')",
            name="ck_trade_invalidation_actions_action",
        ),
        CheckConstraint("length(trim(fingerprint)) > 0", name="ck_trade_invalidation_actions_fingerprint_not_blank"),
        CheckConstraint("length(trim(trade_id)) > 0", name="ck_trade_invalidation_actions_trade_id_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("app_users.id", name="fk_trade_invalidation_actions_user_id", ondelete="SET NULL"),
        nullable=True,
    )
    trade_id: Mapped[str] = mapped_column(Text, nullable=False)
    signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_signals.id", name="fk_trade_invalidation_actions_signal_id", ondelete="SET NULL"),
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


Index(
    "idx_trade_invalidation_actions_trade_fingerprint_time",
    TradeInvalidationAction.trade_id,
    TradeInvalidationAction.fingerprint,
    TradeInvalidationAction.created_at.desc(),
)
Index("idx_trade_invalidation_actions_user_time", TradeInvalidationAction.user_id, TradeInvalidationAction.created_at.desc())
