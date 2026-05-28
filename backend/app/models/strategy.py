from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, Boolean, CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import AppUser


class StrategyTemplate(Base):
    __tablename__ = "strategy_templates"
    __table_args__ = (
        CheckConstraint("length(trim(code)) > 0", name="ck_strategy_templates_code_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="ck_strategy_templates_name_not_blank"),
        CheckConstraint("length(trim(category)) > 0", name="ck_strategy_templates_category_not_blank"),
        UniqueConstraint("code", name="uq_strategy_templates_code"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'medium'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    versions: Mapped[list["StrategyVersion"]] = relationship(back_populates="strategy")


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (
        CheckConstraint("length(trim(version)) > 0", name="ck_strategy_versions_version_not_blank"),
        UniqueConstraint("strategy_id", "version", name="uq_strategy_versions_strategy_version"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    strategy_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy_templates.id", name="fk_strategy_versions_strategy_id"),
        index=True,
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
    config_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    default_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    strategy: Mapped[StrategyTemplate] = relationship(back_populates="versions")
    user_configs: Mapped[list["UserStrategyConfig"]] = relationship(back_populates="strategy_version")
    trading_signals: Mapped[list["TradingSignal"]] = relationship(back_populates="strategy_version")
    alert_rules: Mapped[list["UserAlertRule"]] = relationship(back_populates="strategy_version")


class UserStrategyConfig(Base):
    __tablename__ = "user_strategy_configs"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_user_strategy_configs_name_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_user_strategy_configs_user_id", ondelete="CASCADE"),
        index=True,
    )
    strategy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy_versions.id", name="fk_user_strategy_configs_strategy_version_id"),
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange_scope: Mapped[list[dict[str, Any]] | list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    pair_scope: Mapped[list[dict[str, Any]] | list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    timeframes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    risk_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), index=True)
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

    user: Mapped[AppUser] = relationship(back_populates="strategy_configs")
    strategy_version: Mapped[StrategyVersion] = relationship(back_populates="user_configs")
