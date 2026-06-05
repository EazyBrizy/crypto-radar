from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.market import MarketExchange
from app.models.user import AppUser


class UserExchangeConnection(Base):
    __tablename__ = "user_exchange_connections"
    __table_args__ = (
        CheckConstraint("length(trim(label)) > 0", name="ck_user_exchange_connections_label_not_blank"),
        CheckConstraint(
            "length(trim(account_type)) > 0",
            name="ck_user_exchange_connections_account_type_not_blank",
        ),
        CheckConstraint("length(trim(key_ref)) > 0", name="ck_user_exchange_connections_key_ref_not_blank"),
        CheckConstraint(
            "status IN ('active', 'disabled', 'revoked', 'deleted')",
            name="ck_user_exchange_connections_status",
        ),
        Index(
            "uq_user_exchange_connections_active_label",
            "user_id",
            "exchange_id",
            "label",
            unique=True,
            postgresql_where=text("status NOT IN ('deleted', 'revoked')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_user_exchange_connections_user_id", ondelete="CASCADE"),
        index=True,
    )
    exchange_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_exchanges.id", name="fk_user_exchange_connections_exchange_id"),
        index=True,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'spot'"))
    key_ref: Mapped[str] = mapped_column(Text, nullable=False)
    permissions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"), index=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped[AppUser] = relationship(back_populates="exchange_connections")
    exchange: Mapped[MarketExchange] = relationship(back_populates="user_connections")
    external_orders: Mapped[list["ExternalExchangeOrder"]] = relationship(back_populates="connection")
    external_trades: Mapped[list["ExternalExchangeTrade"]] = relationship(back_populates="connection")
