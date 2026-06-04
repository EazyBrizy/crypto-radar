from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AppUser(Base):
    __tablename__ = "app_users"
    __table_args__ = (
        CheckConstraint("length(trim(email::text)) > 0", name="ck_app_users_email_not_blank"),
        CheckConstraint("username IS NULL OR length(trim(username)) > 0", name="ck_app_users_username_not_blank"),
        UniqueConstraint("email", name="uq_app_users_email"),
        UniqueConstraint("username", name="uq_app_users_username"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ru'"))
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Europe/Warsaw'"))
    risk_profile: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=text("'balanced'"))
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

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    subscriptions: Mapped[list["UserSubscription"]] = relationship(back_populates="user")
    exchange_connections: Mapped[list["UserExchangeConnection"]] = relationship(back_populates="user")
    strategy_configs: Mapped[list["UserStrategyConfig"]] = relationship(back_populates="user")
    watchlists: Mapped[list["UserWatchlist"]] = relationship(back_populates="user")
    alert_rules: Mapped[list["UserAlertRule"]] = relationship(back_populates="user")
    portfolios: Mapped[list["Portfolio"]] = relationship(back_populates="user")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    positions: Mapped[list["Position"]] = relationship(back_populates="user")
    pending_entry_intents: Mapped[list["PendingEntryIntent"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    external_orders: Mapped[list["ExternalExchangeOrder"]] = relationship(back_populates="user")
    external_trades: Mapped[list["ExternalExchangeTrade"]] = relationship(back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
    risk_decisions: Mapped[list["RiskDecisionRecord"]] = relationship(back_populates="user")
    risk_protection_state: Mapped["RiskProtectionState | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    auth_identities: Mapped[list["UserAuthIdentity"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserAuthIdentity(Base):
    __tablename__ = "user_auth_identities"
    __table_args__ = (
        CheckConstraint("length(trim(provider)) > 0", name="ck_user_auth_identities_provider_not_blank"),
        CheckConstraint(
            "length(trim(provider_subject)) > 0",
            name="ck_user_auth_identities_provider_subject_not_blank",
        ),
        UniqueConstraint("provider", "provider_subject", name="uq_user_auth_identities_provider_subject"),
        Index("ix_user_auth_identities_provider_subject", "provider_subject"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_user_auth_identities_user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_subject: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
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

    user: Mapped[AppUser] = relationship(back_populates="auth_identities")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_user_profiles_user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    onboarding_done: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped[AppUser] = relationship(back_populates="profile")


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint("length(trim(code)) > 0", name="ck_subscription_plans_code_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="ck_subscription_plans_name_not_blank"),
        CheckConstraint("price_monthly >= 0", name="ck_subscription_plans_price_monthly_non_negative"),
        CheckConstraint("length(trim(currency)) > 0", name="ck_subscription_plans_currency_not_blank"),
        UniqueConstraint("code", name="uq_subscription_plans_code"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'USD'"))
    limits: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    subscriptions: Mapped[list["UserSubscription"]] = relationship(back_populates="plan")


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'canceled')",
            name="ck_user_subscriptions_status",
        ),
        CheckConstraint(
            "current_period_end IS NULL OR current_period_start IS NULL OR current_period_end >= current_period_start",
            name="ck_user_subscriptions_period_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", name="fk_user_subscriptions_user_id"),
        index=True,
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("subscription_plans.id", name="fk_user_subscriptions_plan_id"),
        index=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped[AppUser] = relationship(back_populates="subscriptions")
    plan: Mapped[SubscriptionPlan] = relationship(back_populates="subscriptions")
