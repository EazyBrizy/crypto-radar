from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.user import AppUser
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

    def test_unknown_user_raises_lookup_error(self) -> None:
        with self.SessionFactory() as session:
            with self.assertRaisesRegex(LookupError, "User is not seeded: missing-user"):
                resolve_app_user(session, "missing-user")

    def test_user_service_get_profile_accepts_demo_aliases(self) -> None:
        service = UserService(self.SessionFactory)

        self.assertEqual(service.get_profile("usr_demo").id, self.demo_user_id)
        self.assertEqual(service.get_profile("demo_user").id, self.demo_user_id)


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
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            AppUser(
                id=user_id,
                email="demo@crypto-radar.local",
                username="demo",
                status="active",
                locale="ru",
                timezone="Europe/Warsaw",
                risk_profile="balanced",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


if __name__ == "__main__":
    unittest.main()
