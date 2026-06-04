from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RiskDecisionRecord(Base):
    __tablename__ = "risk_decisions"
    __table_args__ = (
        CheckConstraint("mode IN ('virtual', 'real')", name="ck_risk_decisions_mode"),
        CheckConstraint(
            "instrument_type IN ('spot', 'futures', 'virtual')",
            name="ck_risk_decisions_instrument_type",
        ),
        CheckConstraint(
            "stage IN ('preview', 'pre_execution', 'post_execution', 'confirm')",
            name="ck_risk_decisions_stage",
        ),
        CheckConstraint("status IN ('passed', 'warning', 'failed')", name="ck_risk_decisions_status"),
        Index("idx_risk_decisions_user_time", "user_id", text("created_at DESC")),
        Index("idx_risk_decisions_signal_time", "signal_id", text("created_at DESC")),
        Index("idx_risk_decisions_pending_entry_time", "pending_entry_intent_id", text("created_at DESC")),
        Index("idx_risk_decisions_status_time", "status", text("created_at DESC")),
        Index("idx_risk_decisions_position_time", "position_id", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_risk_decisions_user_id", ondelete="CASCADE"),
        index=True,
    )
    signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_signals.id", name="fk_risk_decisions_signal_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pending_entry_intent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pending_entry_intents.id", name="fk_risk_decisions_pending_entry_intent_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    portfolio_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolios.id", name="fk_risk_decisions_portfolio_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("orders.id", name="fk_risk_decisions_order_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    position_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("positions.id", name="fk_risk_decisions_position_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_type: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    blockers: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    warnings: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    result_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped["AppUser"] = relationship(back_populates="risk_decisions")
    signal: Mapped["TradingSignal | None"] = relationship()
    pending_entry_intent: Mapped["PendingEntryIntent | None"] = relationship()
    portfolio: Mapped["Portfolio | None"] = relationship()
    order: Mapped["Order | None"] = relationship(back_populates="risk_decisions")
    position: Mapped["Position | None"] = relationship(back_populates="risk_decisions")


class PositionRiskSnapshot(Base):
    __tablename__ = "position_risk_snapshots"
    __table_args__ = (
        CheckConstraint("risk_amount >= 0", name="ck_position_risk_snapshots_risk_amount_non_negative"),
        CheckConstraint("risk_percent >= 0", name="ck_position_risk_snapshots_risk_percent_non_negative"),
        CheckConstraint(
            "adjusted_risk_amount >= 0",
            name="ck_position_risk_snapshots_adjusted_risk_amount_non_negative",
        ),
        CheckConstraint("rr IS NULL OR rr >= 0", name="ck_position_risk_snapshots_rr_non_negative"),
        CheckConstraint("leverage >= 1", name="ck_position_risk_snapshots_leverage_positive"),
        CheckConstraint(
            "margin_mode IN ('spot', 'isolated', 'cross', 'unknown')",
            name="ck_position_risk_snapshots_margin_mode",
        ),
        CheckConstraint(
            "liquidation_price IS NULL OR liquidation_price > 0",
            name="ck_position_risk_snapshots_liquidation_price_positive",
        ),
        CheckConstraint(
            "liquidation_buffer_percent IS NULL OR liquidation_buffer_percent >= 0",
            name="ck_position_risk_snapshots_liquidation_buffer_non_negative",
        ),
        CheckConstraint(
            "strategy_multiplier >= 0",
            name="ck_position_risk_snapshots_strategy_multiplier_non_negative",
        ),
        CheckConstraint(
            "signal_multiplier >= 0",
            name="ck_position_risk_snapshots_signal_multiplier_non_negative",
        ),
        CheckConstraint("fee_estimate >= 0", name="ck_position_risk_snapshots_fee_estimate_non_negative"),
        CheckConstraint(
            "slippage_estimate >= 0",
            name="ck_position_risk_snapshots_slippage_estimate_non_negative",
        ),
        CheckConstraint("funding_buffer >= 0", name="ck_position_risk_snapshots_funding_buffer_non_negative"),
    )

    position_id: Mapped[UUID] = mapped_column(
        ForeignKey("positions.id", name="fk_position_risk_snapshots_position_id", ondelete="CASCADE"),
        primary_key=True,
    )
    risk_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("risk_decisions.id", name="fk_position_risk_snapshots_risk_decision_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    risk_amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    risk_percent: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    adjusted_risk_amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    rr: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    margin_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'spot'"))
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    liquidation_buffer_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    correlation_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategy_multiplier: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    signal_multiplier: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    fee_estimate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    slippage_estimate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    funding_buffer: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    position: Mapped["Position"] = relationship(back_populates="risk_snapshot")
    risk_decision: Mapped["RiskDecisionRecord | None"] = relationship()


class ExchangeInstrumentRule(Base):
    __tablename__ = "exchange_instrument_rules"
    __table_args__ = (
        CheckConstraint("length(trim(symbol)) > 0", name="ck_exchange_instrument_rules_symbol_not_blank"),
        CheckConstraint("length(trim(category)) > 0", name="ck_exchange_instrument_rules_category_not_blank"),
        CheckConstraint(
            "min_order_size IS NULL OR min_order_size >= 0",
            name="ck_exchange_instrument_rules_min_order_size_non_negative",
        ),
        CheckConstraint(
            "max_order_size IS NULL OR max_order_size >= 0",
            name="ck_exchange_instrument_rules_max_order_size_non_negative",
        ),
        CheckConstraint(
            "min_notional IS NULL OR min_notional >= 0",
            name="ck_exchange_instrument_rules_min_notional_non_negative",
        ),
        CheckConstraint("qty_step IS NULL OR qty_step > 0", name="ck_exchange_instrument_rules_qty_step_positive"),
        CheckConstraint("tick_size IS NULL OR tick_size > 0", name="ck_exchange_instrument_rules_tick_size_positive"),
        CheckConstraint(
            "max_leverage IS NULL OR max_leverage >= 1",
            name="ck_exchange_instrument_rules_max_leverage_positive",
        ),
        CheckConstraint(
            "funding_interval_minutes IS NULL OR funding_interval_minutes >= 0",
            name="ck_exchange_instrument_rules_funding_interval_non_negative",
        ),
        UniqueConstraint(
            "exchange_id",
            "category",
            "symbol",
            name="uq_exchange_instrument_rules_exchange_category_symbol",
        ),
        Index("idx_exchange_instrument_rules_pair", "pair_id", "category"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    exchange_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_exchanges.id", name="fk_exchange_instrument_rules_exchange_id", ondelete="CASCADE"),
        index=True,
    )
    pair_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("market_pairs.id", name="fk_exchange_instrument_rules_pair_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    min_order_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    max_order_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    min_notional: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    qty_step: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    tick_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    max_leverage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    funding_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'exchange'"))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    exchange: Mapped["MarketExchange"] = relationship(back_populates="instrument_rules")
    pair: Mapped["MarketPair | None"] = relationship(back_populates="instrument_rules")


class AssetRiskGroup(Base):
    __tablename__ = "asset_risk_groups"
    __table_args__ = (
        CheckConstraint("length(trim(group_code)) > 0", name="ck_asset_risk_groups_group_code_not_blank"),
        CheckConstraint("length(trim(group_name)) > 0", name="ck_asset_risk_groups_group_name_not_blank"),
        UniqueConstraint("asset_id", "group_code", name="uq_asset_risk_groups_asset_group"),
        Index(
            "uq_asset_risk_groups_primary_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        Index("idx_asset_risk_groups_group_code", "group_code"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_assets.id", name="fk_asset_risk_groups_asset_id", ondelete="CASCADE"),
        index=True,
    )
    group_code: Mapped[str] = mapped_column(Text, nullable=False)
    group_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
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

    asset: Mapped["MarketAsset"] = relationship(back_populates="risk_groups")


class RiskProtectionState(Base):
    __tablename__ = "risk_protection_state"
    __table_args__ = (
        CheckConstraint(
            "state IN ('normal', 'reduced', 'virtual_only', 'blocked')",
            name="ck_risk_protection_state_state",
        ),
        CheckConstraint("loss_streak >= 0", name="ck_risk_protection_state_loss_streak_non_negative"),
        CheckConstraint("daily_loss_amount >= 0", name="ck_risk_protection_state_daily_loss_non_negative"),
        CheckConstraint("weekly_loss_amount >= 0", name="ck_risk_protection_state_weekly_loss_non_negative"),
        CheckConstraint("peak_equity >= 0", name="ck_risk_protection_state_peak_equity_non_negative"),
        CheckConstraint("current_equity >= 0", name="ck_risk_protection_state_current_equity_non_negative"),
        CheckConstraint(
            "adaptive_multiplier >= 0",
            name="ck_risk_protection_state_adaptive_multiplier_non_negative",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_risk_protection_state_user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'normal'"))
    loss_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    daily_loss_amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    weekly_loss_amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    daily_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    weekly_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'UTC'"))
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    current_equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default=text("0"))
    adaptive_multiplier: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("1"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    user: Mapped["AppUser"] = relationship(back_populates="risk_protection_state")
