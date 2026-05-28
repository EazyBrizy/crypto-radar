from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, Boolean, CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserWatchlist(Base):
    __tablename__ = "user_watchlists"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_user_watchlists_name_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_user_watchlists_user_id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped["AppUser"] = relationship(back_populates="watchlists")
    pair_entries: Mapped[list["UserWatchlistPair"]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
    )


class UserWatchlistPair(Base):
    __tablename__ = "user_watchlist_pairs"

    watchlist_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_watchlists.id", name="fk_user_watchlist_pairs_watchlist_id", ondelete="CASCADE"),
        primary_key=True,
    )
    pair_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_pairs.id", name="fk_user_watchlist_pairs_pair_id"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    watchlist: Mapped[UserWatchlist] = relationship(back_populates="pair_entries")
    pair: Mapped["MarketPair"] = relationship(back_populates="watchlist_entries")


class UserAlertRule(Base):
    __tablename__ = "user_alert_rules"
    __table_args__ = (
        CheckConstraint(
            "length(trim(condition_type)) > 0",
            name="ck_user_alert_rules_condition_type_not_blank",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_user_alert_rules_user_id", ondelete="CASCADE"),
        index=True,
    )
    pair_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("market_pairs.id", name="fk_user_alert_rules_pair_id"),
        nullable=True,
        index=True,
    )
    strategy_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("strategy_versions.id", name="fk_user_alert_rules_strategy_version_id"),
        nullable=True,
        index=True,
    )
    condition_type: Mapped[str] = mapped_column(Text, nullable=False)
    condition_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY['websocket']::text[]"),
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped["AppUser"] = relationship(back_populates="alert_rules")
    pair: Mapped["MarketPair | None"] = relationship(back_populates="alert_rules")
    strategy_version: Mapped["StrategyVersion | None"] = relationship(back_populates="alert_rules")
