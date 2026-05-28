from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MarketExchange(Base):
    __tablename__ = "market_exchanges"
    __table_args__ = (
        CheckConstraint("type IN ('cex', 'dex')", name="ck_market_exchanges_type"),
        CheckConstraint("length(trim(code)) > 0", name="ck_market_exchanges_code_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="ck_market_exchanges_name_not_blank"),
        UniqueConstraint("code", name="uq_market_exchanges_code"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    api_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ws_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    pairs: Mapped[list["MarketPair"]] = relationship(back_populates="exchange")
    user_connections: Mapped[list["UserExchangeConnection"]] = relationship(back_populates="exchange")
    trading_signals: Mapped[list["TradingSignal"]] = relationship(back_populates="exchange")
    orders: Mapped[list["Order"]] = relationship(back_populates="exchange")


class MarketAsset(Base):
    __tablename__ = "market_assets"
    __table_args__ = (
        CheckConstraint("length(trim(symbol)) > 0", name="ck_market_assets_symbol_not_blank"),
        CheckConstraint("decimals IS NULL OR decimals >= 0", name="ck_market_assets_decimals_non_negative"),
        UniqueConstraint("symbol", name="uq_market_assets_symbol"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'crypto'"))
    decimals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coingecko_id: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    base_pairs: Mapped[list["MarketPair"]] = relationship(
        back_populates="base_asset",
        foreign_keys="MarketPair.base_asset_id",
    )
    quote_pairs: Mapped[list["MarketPair"]] = relationship(
        back_populates="quote_asset",
        foreign_keys="MarketPair.quote_asset_id",
    )
    portfolio_balances: Mapped[list["PortfolioBalance"]] = relationship(back_populates="asset")
    portfolio_balance_ledger_entries: Mapped[list["PortfolioBalanceLedger"]] = relationship(back_populates="asset")
    fee_order_fills: Mapped[list["OrderFill"]] = relationship(back_populates="fee_asset")
    external_fee_trades: Mapped[list["ExternalExchangeTrade"]] = relationship(back_populates="fee_asset")


class MarketPair(Base):
    __tablename__ = "market_pairs"
    __table_args__ = (
        CheckConstraint("length(trim(symbol)) > 0", name="ck_market_pairs_symbol_not_blank"),
        CheckConstraint("base_asset_id <> quote_asset_id", name="ck_market_pairs_distinct_assets"),
        CheckConstraint("min_qty IS NULL OR min_qty >= 0", name="ck_market_pairs_min_qty_non_negative"),
        CheckConstraint("tick_size IS NULL OR tick_size > 0", name="ck_market_pairs_tick_size_positive"),
        CheckConstraint("lot_size IS NULL OR lot_size > 0", name="ck_market_pairs_lot_size_positive"),
        UniqueConstraint("exchange_id", "symbol", name="uq_market_pairs_exchange_symbol"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    exchange_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_exchanges.id", name="fk_market_pairs_exchange_id"),
    )
    base_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_assets.id", name="fk_market_pairs_base_asset_id"),
        index=True,
    )
    quote_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_assets.id", name="fk_market_pairs_quote_asset_id"),
        index=True,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    min_qty: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    tick_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    lot_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
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

    exchange: Mapped[MarketExchange] = relationship(back_populates="pairs")
    base_asset: Mapped[MarketAsset] = relationship(
        back_populates="base_pairs",
        foreign_keys=[base_asset_id],
    )
    quote_asset: Mapped[MarketAsset] = relationship(
        back_populates="quote_pairs",
        foreign_keys=[quote_asset_id],
    )
    trading_signals: Mapped[list["TradingSignal"]] = relationship(back_populates="pair")
    watchlist_entries: Mapped[list["UserWatchlistPair"]] = relationship(back_populates="pair")
    alert_rules: Mapped[list["UserAlertRule"]] = relationship(back_populates="pair")
    orders: Mapped[list["Order"]] = relationship(back_populates="pair")
    positions: Mapped[list["Position"]] = relationship(back_populates="pair")
    external_orders: Mapped[list["ExternalExchangeOrder"]] = relationship(back_populates="pair")
    external_trades: Mapped[list["ExternalExchangeTrade"]] = relationship(back_populates="pair")
