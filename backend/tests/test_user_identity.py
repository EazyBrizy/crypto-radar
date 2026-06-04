from __future__ import annotations

import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.user import AppUser, UserAuthIdentity
from app.services import bootstrap_service
from app.services.user_identity import resolve_app_user, resolve_app_user_uuid
from app.services.user_service import UserService


class UserIdentityResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.SessionFactory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            future=True,
        )
        self.demo_user_id = uuid4()
        _create_sqlite_tables(self.engine)
        _seed_demo_user(self.SessionFactory, self.demo_user_id)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_demo_aliases_resolve_to_same_seeded_user(self) -> None:
        aliases = ["demo_user", "usr_demo", "demo", "demo@crypto-radar.local"]

        with self.SessionFactory() as session:
            resolved_ids = {
                resolve_app_user(session, alias).id
                for alias in aliases
            }

        self.assertEqual(resolved_ids, {self.demo_user_id})

    def test_resolve_app_user_uuid_returns_seeded_user_id(self) -> None:
        with self.SessionFactory() as session:
            resolved_id = resolve_app_user_uuid(session, "usr_demo")

        self.assertEqual(resolved_id, self.demo_user_id)

    def test_resolve_app_user_checks_auth_identity_provider_subject(self) -> None:
        identity_user_id = uuid4()
        _seed_user(
            self.SessionFactory,
            identity_user_id,
            email="identity-target@example.test",
            username="identity-target",
        )
        _seed_auth_identity(
            self.SessionFactory,
            identity_user_id,
            provider="test-auth",
            provider_subject="usr_demo",
            email="identity-target@example.test",
        )

        with self.SessionFactory() as session:
            resolved_id = resolve_app_user(session, "usr_demo").id

        self.assertEqual(resolved_id, identity_user_id)

    def test_deleting_auth_identity_keeps_demo_alias_fallback(self) -> None:
        _seed_auth_identity(
            self.SessionFactory,
            self.demo_user_id,
            provider=bootstrap_service.DEMO_AUTH_PROVIDER,
            provider_subject=bootstrap_service.DEMO_AUTH_PROVIDER_SUBJECT,
            email=bootstrap_service.DEMO_USER_EMAIL,
        )
        with self.SessionFactory() as session:
            identity = session.scalars(
                select(UserAuthIdentity).where(
                    UserAuthIdentity.provider == bootstrap_service.DEMO_AUTH_PROVIDER,
                    UserAuthIdentity.provider_subject == bootstrap_service.DEMO_AUTH_PROVIDER_SUBJECT,
                )
            ).one()
            session.delete(identity)
            session.commit()

        with self.SessionFactory() as session:
            resolved_id = resolve_app_user(session, "usr_demo").id

        self.assertEqual(resolved_id, self.demo_user_id)

    def test_unknown_user_raises_lookup_error(self) -> None:
        with self.SessionFactory() as session:
            with self.assertRaisesRegex(LookupError, "User is not seeded: missing-user"):
                resolve_app_user(session, "missing-user")

    def test_user_service_get_profile_accepts_demo_aliases(self) -> None:
        service = UserService(self.SessionFactory)

        self.assertEqual(service.get_profile("usr_demo").id, self.demo_user_id)
        self.assertEqual(service.get_profile("demo_user").id, self.demo_user_id)


class BootstrapUserAuthIdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.SessionFactory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            future=True,
        )
        self.demo_user_id = uuid4()
        _create_sqlite_tables(self.engine)
        _seed_demo_user(self.SessionFactory, self.demo_user_id)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_bootstrap_creates_demo_auth_identity_once(self) -> None:
        with self.SessionFactory() as session:
            with _patched_non_identity_bootstrap_dependencies():
                first = bootstrap_service.bootstrap_postgres_seed(session)
                second = bootstrap_service.bootstrap_postgres_seed(session)

            identity_count = session.scalar(select(func.count()).select_from(UserAuthIdentity))
            identity = session.scalars(select(UserAuthIdentity)).one()

        self.assertEqual(first.created.get("user_auth_identities"), 1)
        self.assertEqual(second.unchanged.get("user_auth_identities"), 1)
        self.assertEqual(identity_count, 1)
        self.assertEqual(identity.user_id, self.demo_user_id)
        self.assertEqual(identity.provider, bootstrap_service.DEMO_AUTH_PROVIDER)
        self.assertEqual(identity.provider_subject, bootstrap_service.DEMO_AUTH_PROVIDER_SUBJECT)
        self.assertEqual(identity.email, bootstrap_service.DEMO_USER_EMAIL)


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE app_users (
                    id UUID PRIMARY KEY,
                    email TEXT NOT NULL,
                    username TEXT,
                    status TEXT,
                    locale TEXT,
                    timezone TEXT,
                    risk_profile TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE user_auth_identities (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    provider TEXT NOT NULL,
                    provider_subject TEXT NOT NULL,
                    email TEXT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(user_id) REFERENCES app_users(id),
                    UNIQUE(provider, provider_subject)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE user_profiles (
                    user_id UUID PRIMARY KEY,
                    display_name TEXT,
                    avatar_url TEXT,
                    onboarding_done BOOLEAN,
                    settings JSON NOT NULL,
                    updated_at DATETIME,
                    FOREIGN KEY(user_id) REFERENCES app_users(id)
                )
                """
            )
        )


def _seed_demo_user(session_factory: Any, user_id: Any) -> None:
    _seed_user(
        session_factory,
        user_id,
        email="demo@crypto-radar.local",
        username="demo",
    )


def _seed_user(session_factory: Any, user_id: Any, *, email: str, username: str) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            AppUser(
                id=user_id,
                email=email,
                username=username,
                status="active",
                locale="ru",
                timezone="Europe/Warsaw",
                risk_profile="balanced",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _seed_auth_identity(
    session_factory: Any,
    user_id: Any,
    *,
    provider: str,
    provider_subject: str,
    email: str | None,
) -> None:
    with session_factory() as session:
        session.add(
            UserAuthIdentity(
                user_id=user_id,
                provider=provider,
                provider_subject=provider_subject,
                email=email,
            )
        )
        session.commit()


def _patched_non_identity_bootstrap_dependencies() -> ExitStack:
    stack = ExitStack()
    stack.enter_context(patch.object(bootstrap_service, "_seed_exchanges", return_value={}))
    stack.enter_context(patch.object(bootstrap_service, "_seed_assets", return_value={"USDT": object()}))
    stack.enter_context(patch.object(bootstrap_service, "_seed_asset_risk_groups", return_value=None))
    stack.enter_context(patch.object(bootstrap_service, "_seed_pairs", return_value={}))
    stack.enter_context(
        patch.object(bootstrap_service, "_seed_subscription_plans", return_value={"pro": object()})
    )
    stack.enter_context(patch.object(bootstrap_service, "_seed_strategy_templates", return_value={}))
    stack.enter_context(patch.object(bootstrap_service, "_seed_strategy_versions", return_value=None))
    stack.enter_context(patch.object(bootstrap_service, "_seed_demo_profile", return_value=None))
    stack.enter_context(patch.object(bootstrap_service, "_seed_demo_subscription", return_value=None))
    stack.enter_context(patch.object(bootstrap_service, "_seed_demo_portfolio", return_value=object()))
    stack.enter_context(patch.object(bootstrap_service, "_seed_initial_balance", return_value=None))
    stack.enter_context(patch.object(bootstrap_service, "_seed_default_watchlist", return_value=None))
    return stack


if __name__ == "__main__":
    unittest.main()
