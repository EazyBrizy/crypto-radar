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


class Portfolio(Base):
    __tablename__ = "portfolios"
    __table_args__ = (
        CheckConstraint("type IN ('virtual', 'live')", name="ck_portfolios_type"),
        CheckConstraint("length(trim(name)) > 0", name="ck_portfolios_name_not_blank"),
        CheckConstraint("length(trim(base_currency)) > 0", name="ck_portfolios_base_currency_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_portfolios_user_id", ondelete="CASCADE"),
        index=True,
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'USDT'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped["AppUser"] = relationship(back_populates="portfolios")
    balances: Mapped[list["PortfolioBalance"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
    balance_ledger_entries: Mapped[list["PortfolioBalanceLedger"]] = relationship(back_populates="portfolio")
    orders: Mapped[list["Order"]] = relationship(back_populates="portfolio")
    positions: Mapped[list["Position"]] = relationship(back_populates="portfolio")


class PortfolioBalance(Base):
    __tablename__ = "portfolio_balances"
    __table_args__ = (
        CheckConstraint("available >= 0", name="ck_portfolio_balances_available_non_negative"),
        CheckConstraint("locked >= 0", name="ck_portfolio_balances_locked_non_negative"),
    )

    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", name="fk_portfolio_balances_portfolio_id", ondelete="CASCADE"),
        primary_key=True,
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_assets.id", name="fk_portfolio_balances_asset_id"),
        primary_key=True,
        index=True,
    )
    available: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    locked: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="balances")
    asset: Mapped["MarketAsset"] = relationship(back_populates="portfolio_balances")


class PortfolioBalanceLedger(Base):
    __tablename__ = "portfolio_balance_ledger"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) > 0", name="ck_portfolio_balance_ledger_reason_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", name="fk_portfolio_balance_ledger_portfolio_id"),
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_assets.id", name="fk_portfolio_balance_ledger_asset_id"),
        index=True,
    )
    delta_available: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    delta_locked: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    ref_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="balance_ledger_entries")
    asset: Mapped["MarketAsset"] = relationship(back_populates="portfolio_balance_ledger_entries")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("mode IN ('virtual', 'live')", name="ck_orders_mode"),
        CheckConstraint("side IN ('buy', 'sell')", name="ck_orders_side"),
        CheckConstraint("order_type IN ('market', 'limit', 'stop', 'take_profit')", name="ck_orders_order_type"),
        CheckConstraint(
            "status IN ('created', 'submitted', 'partially_filled', 'filled', 'cancelled', 'rejected')",
            name="ck_orders_status",
        ),
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="ck_orders_idempotency_key_not_blank"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id", name="fk_orders_user_id"))
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", name="fk_orders_portfolio_id"),
        index=True,
    )
    signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_signals.id", name="fk_orders_signal_id"),
        nullable=True,
        index=True,
    )
    exchange_id: Mapped[UUID] = mapped_column(ForeignKey("market_exchanges.id", name="fk_orders_exchange_id"))
    pair_id: Mapped[UUID] = mapped_column(ForeignKey("market_pairs.id", name="fk_orders_pair_id"), index=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    order_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    time_in_force: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped["AppUser"] = relationship(back_populates="orders")
    portfolio: Mapped[Portfolio] = relationship(back_populates="orders")
    signal: Mapped["TradingSignal | None"] = relationship(back_populates="orders")
    exchange: Mapped["MarketExchange"] = relationship(back_populates="orders")
    pair: Mapped["MarketPair"] = relationship(back_populates="orders")
    fills: Mapped[list["OrderFill"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )
    risk_decisions: Mapped[list["RiskDecisionRecord"]] = relationship(back_populates="order")


class OrderFill(Base):
    __tablename__ = "order_fills"
    __table_args__ = (
        CheckConstraint("liquidity IN ('maker', 'taker', 'simulated')", name="ck_order_fills_liquidity"),
        CheckConstraint("price > 0", name="ck_order_fills_price_positive"),
        CheckConstraint("quantity > 0", name="ck_order_fills_quantity_positive"),
        CheckConstraint("fee_amount >= 0", name="ck_order_fills_fee_amount_non_negative"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", name="fk_order_fills_order_id", ondelete="CASCADE"),
        index=True,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    fee_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("market_assets.id", name="fk_order_fills_fee_asset_id"),
        nullable=True,
        index=True,
    )
    liquidity: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    order: Mapped[Order] = relationship(back_populates="fills")
    fee_asset: Mapped["MarketAsset | None"] = relationship(back_populates="fee_order_fills")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("mode IN ('virtual', 'live')", name="ck_positions_mode"),
        CheckConstraint("side IN ('long', 'short')", name="ck_positions_side"),
        CheckConstraint(
            "status IN ('open', 'partially_closed', 'closed', 'stopped', 'invalidated', 'expired', 'cancelled', 'liquidated')",
            name="ck_positions_status",
        ),
        CheckConstraint("quantity > 0", name="ck_positions_quantity_positive"),
        CheckConstraint("entry_avg_price > 0", name="ck_positions_entry_avg_price_positive"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id", name="fk_positions_user_id"), index=True)
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", name="fk_positions_portfolio_id"),
        index=True,
    )
    signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_signals.id", name="fk_positions_signal_id"),
        nullable=True,
        index=True,
    )
    pair_id: Mapped[UUID] = mapped_column(ForeignKey("market_pairs.id", name="fk_positions_pair_id"), index=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_avg_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    exit_avg_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    take_profit: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True, server_default=text("0"))
    fees_total: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True, server_default=text("0"))
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

    user: Mapped["AppUser"] = relationship(back_populates="positions")
    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")
    signal: Mapped["TradingSignal | None"] = relationship(back_populates="positions")
    pair: Mapped["MarketPair"] = relationship(back_populates="positions")
    risk_decisions: Mapped[list["RiskDecisionRecord"]] = relationship(back_populates="position")
    risk_snapshot: Mapped["PositionRiskSnapshot | None"] = relationship(
        back_populates="position",
        cascade="all, delete-orphan",
        uselist=False,
    )


Index(
    "ix_portfolio_balance_ledger_portfolio_time",
    PortfolioBalanceLedger.portfolio_id,
    PortfolioBalanceLedger.created_at.desc(),
)
