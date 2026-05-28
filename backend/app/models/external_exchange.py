from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, Text
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ExternalExchangeOrder(Base):
    __tablename__ = "external_exchange_orders"
    __table_args__ = (
        CheckConstraint(
            "length(trim(exchange_order_id)) > 0",
            name="ck_external_exchange_orders_exchange_order_id_not_blank",
        ),
        CheckConstraint("length(trim(side)) > 0", name="ck_external_exchange_orders_side_not_blank"),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="ck_external_exchange_orders_quantity_non_negative"),
        CheckConstraint("price IS NULL OR price >= 0", name="ck_external_exchange_orders_price_non_negative"),
        UniqueConstraint(
            "connection_id",
            "exchange_order_id",
            name="uq_external_exchange_orders_connection_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_external_exchange_orders_user_id"),
        index=True,
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_exchange_connections.id", name="fk_external_exchange_orders_connection_id"),
        index=True,
    )
    exchange_order_id: Mapped[str] = mapped_column(Text, nullable=False)
    pair_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_pairs.id", name="fk_external_exchange_orders_pair_id"),
        index=True,
    )
    side: Mapped[str] = mapped_column(Text, nullable=False)
    order_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    created_exchange_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_exchange_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    user: Mapped["AppUser"] = relationship(back_populates="external_orders")
    connection: Mapped["UserExchangeConnection"] = relationship(back_populates="external_orders")
    pair: Mapped["MarketPair"] = relationship(back_populates="external_orders")


class ExternalExchangeTrade(Base):
    __tablename__ = "external_exchange_trades"
    __table_args__ = (
        CheckConstraint(
            "length(trim(exchange_trade_id)) > 0",
            name="ck_external_exchange_trades_exchange_trade_id_not_blank",
        ),
        CheckConstraint("length(trim(side)) > 0", name="ck_external_exchange_trades_side_not_blank"),
        CheckConstraint("price > 0", name="ck_external_exchange_trades_price_positive"),
        CheckConstraint("quantity > 0", name="ck_external_exchange_trades_quantity_positive"),
        CheckConstraint("fee_amount IS NULL OR fee_amount >= 0", name="ck_external_exchange_trades_fee_non_negative"),
        UniqueConstraint(
            "connection_id",
            "exchange_trade_id",
            name="uq_external_exchange_trades_connection_trade",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_external_exchange_trades_user_id"),
        index=True,
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_exchange_connections.id", name="fk_external_exchange_trades_connection_id"),
        index=True,
    )
    exchange_trade_id: Mapped[str] = mapped_column(Text, nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    pair_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_pairs.id", name="fk_external_exchange_trades_pair_id"),
        index=True,
    )
    side: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    fee_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("market_assets.id", name="fk_external_exchange_trades_fee_asset_id"),
        nullable=True,
        index=True,
    )
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    user: Mapped["AppUser"] = relationship(back_populates="external_trades")
    connection: Mapped["UserExchangeConnection"] = relationship(back_populates="external_trades")
    pair: Mapped["MarketPair"] = relationship(back_populates="external_trades")
    fee_asset: Mapped["MarketAsset | None"] = relationship(back_populates="external_fee_trades")
