from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TradingSignal(Base):
    __tablename__ = "trading_signals"
    __table_args__ = (
        CheckConstraint("length(trim(signal_key)) > 0", name="ck_trading_signals_signal_key_not_blank"),
        CheckConstraint("length(trim(timeframe)) > 0", name="ck_trading_signals_timeframe_not_blank"),
        CheckConstraint("direction IN ('long', 'short')", name="ck_trading_signals_direction"),
        CheckConstraint(
            "status IN ("
            "'new', 'active', 'watchlist', 'ready', 'actionable', 'wait_for_pullback', "
            "'entry_touched', 'confirmed', 'expired', 'invalidated', 'closed'"
            ")",
            name="ck_trading_signals_status",
        ),
        UniqueConstraint("signal_key", name="uq_trading_signals_signal_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    signal_key: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy_versions.id", name="fk_trading_signals_strategy_version_id"),
    )
    exchange_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_exchanges.id", name="fk_trading_signals_exchange_id"),
    )
    pair_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_pairs.id", name="fk_trading_signals_pair_id"),
    )
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    take_profit: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    risk_reward: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    features_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    strategy_version: Mapped["StrategyVersion"] = relationship(back_populates="trading_signals")
    exchange: Mapped["MarketExchange"] = relationship(back_populates="trading_signals")
    pair: Mapped["MarketPair"] = relationship(back_populates="trading_signals")
    events: Mapped[list["TradingSignalEvent"]] = relationship(
        back_populates="signal",
        cascade="all, delete-orphan",
    )
    orders: Mapped[list["Order"]] = relationship(back_populates="signal")
    positions: Mapped[list["Position"]] = relationship(back_populates="signal")
    ai_explanations: Mapped[list["SignalAIExplanation"]] = relationship(
        back_populates="signal",
        cascade="all, delete-orphan",
    )
    outcome: Mapped["SignalOutcome | None"] = relationship(
        back_populates="signal",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TradingSignalEvent(Base):
    __tablename__ = "trading_signal_events"
    __table_args__ = (
        CheckConstraint("length(trim(event_type)) > 0", name="ck_trading_signal_events_event_type_not_blank"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_signals.id", name="fk_trading_signal_events_signal_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    old_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=text("now()"),
    )

    signal: Mapped[TradingSignal] = relationship(back_populates="events")


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    __table_args__ = (
        CheckConstraint("length(trim(exchange)) > 0", name="ck_signal_outcomes_exchange_not_blank"),
        CheckConstraint("length(trim(symbol)) > 0", name="ck_signal_outcomes_symbol_not_blank"),
        CheckConstraint("length(trim(timeframe)) > 0", name="ck_signal_outcomes_timeframe_not_blank"),
        CheckConstraint("length(trim(strategy)) > 0", name="ck_signal_outcomes_strategy_not_blank"),
        CheckConstraint("direction IN ('long', 'short')", name="ck_signal_outcomes_direction"),
        CheckConstraint(
            "status IN ("
            "'tracking', 'entry_touched', 'tp1', 'tp2', 'tp3', "
            "'stop_loss', 'expired', 'invalidated', 'time_stop'"
            ")",
            name="ck_signal_outcomes_status",
        ),
        CheckConstraint(
            "outcome IN ('win', 'loss', 'breakeven', 'expired', 'invalidated', 'open')",
            name="ck_signal_outcomes_outcome",
        ),
        CheckConstraint("signal_score >= 0 AND signal_score <= 100", name="ck_signal_outcomes_signal_score"),
        CheckConstraint("entry_price > 0", name="ck_signal_outcomes_entry_price_positive"),
        CheckConstraint("stop_loss > 0", name="ck_signal_outcomes_stop_loss_positive"),
        UniqueConstraint("signal_id", name="uq_signal_outcomes_signal_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_signals.id", name="fk_signal_outcomes_signal_id", ondelete="CASCADE"),
        nullable=False,
    )
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    signal_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_min: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_max: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    targets: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    selected_rr: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    realized_r: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default=text("0"))
    mfe_r: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default=text("0"))
    mae_r: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default=text("0"))
    bars_to_entry: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bars_to_outcome: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    signal: Mapped[TradingSignal] = relationship(back_populates="outcome")


Index("idx_trading_signals_active", TradingSignal.status, TradingSignal.detected_at.desc())
Index(
    "idx_trading_signals_pair_time",
    TradingSignal.pair_id,
    TradingSignal.timeframe,
    TradingSignal.detected_at.desc(),
)
Index("idx_trading_signals_strategy", TradingSignal.strategy_version_id, TradingSignal.detected_at.desc())
Index("idx_trading_signals_features_gin", TradingSignal.features_snapshot, postgresql_using="gin")
Index(
    "idx_trading_signal_events_signal_time",
    TradingSignalEvent.signal_id,
    TradingSignalEvent.created_at.desc(),
)
Index(
    "idx_trading_signal_events_event_type_time",
    TradingSignalEvent.event_type,
    TradingSignalEvent.created_at.desc(),
)
Index(
    "idx_signal_outcomes_open_series",
    SignalOutcome.exchange,
    SignalOutcome.symbol,
    SignalOutcome.timeframe,
    SignalOutcome.outcome,
)
Index("idx_signal_outcomes_created_at", SignalOutcome.created_at.desc())
