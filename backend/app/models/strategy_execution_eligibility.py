from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StrategyExecutionEligibilityProfile(Base):
    __tablename__ = "strategy_execution_eligibility_profiles"
    __table_args__ = (
        CheckConstraint(
            "source IN ('historical_backtest', 'forward_virtual', 'mixed')",
            name="ck_strategy_execution_eligibility_profiles_source",
        ),
        Index(
            "ux_strategy_execution_eligibility_profile_key",
            "strategy_code",
            "exchange",
            "symbol_scope",
            "timeframe",
            "market_regime",
            "score_bucket",
            "direction",
            unique=True,
        ),
        Index(
            "ix_strategy_execution_eligibility_profiles_lookup",
            "strategy_code",
            "exchange",
            "timeframe",
        ),
        Index("ix_strategy_execution_eligibility_profiles_eligible", "eligible"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    strategy_code: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_scope: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    market_regime: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unknown'"))
    score_bucket: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unknown'"))
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expectancy_after_costs_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_touch_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_entry_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    run_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
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
