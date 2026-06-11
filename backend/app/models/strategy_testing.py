from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StrategyTestRun(Base):
    __tablename__ = "strategy_test_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'stopping')",
            name="ck_strategy_test_runs_status",
        ),
        CheckConstraint(
            "test_type IN ('historical_backtest', 'forward_virtual')",
            name="ck_strategy_test_runs_test_type",
        ),
        CheckConstraint(
            "mode IN ('discovery', 'research_virtual', 'production_like')",
            name="ck_strategy_test_runs_mode",
        ),
        CheckConstraint("end_at > start_at", name="ck_strategy_test_runs_time_range"),
        CheckConstraint(
            "coalesce(array_length(requested_strategies, 1), 0) > 0",
            name="ck_strategy_test_runs_requested_strategies_non_empty",
        ),
        CheckConstraint(
            "coalesce(array_length(requested_timeframes, 1), 0) > 0",
            name="ck_strategy_test_runs_requested_timeframes_non_empty",
        ),
        Index("ix_strategy_test_runs_user_created", "user_id", text("created_at DESC")),
        Index("ix_strategy_test_runs_status_created", "status", text("created_at DESC")),
        Index("ix_strategy_test_runs_mode", "mode"),
        Index("ix_strategy_test_runs_test_type", "test_type"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_strategy_test_runs_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    test_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'historical_backtest'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    requested_strategies: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    requested_pairs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    requested_timeframes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    runtime_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    metric_set: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY[]::text[]"),
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY['backtest']::text[]"),
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["AppUser"] = relationship()


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
        Index("ix_strategy_execution_eligibility_profiles_lookup", "strategy_code", "exchange", "timeframe"),
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
