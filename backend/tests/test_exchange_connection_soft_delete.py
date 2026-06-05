from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.exchange_connection import UserExchangeConnection
from app.models.external_exchange import ExternalExchangeTrade
from app.models.market import MarketExchange
from app.models.user import AppUser
from app.services.exchange_connection_service import (
    ExchangeConnectionHardDeleteConflict,
    ExchangeConnectionHardDeleteProtected,
    ExchangeConnectionService,
    StubSecretRefProvider,
)

USER_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd524")
EXCHANGE_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
CONNECTION_ID = UUID("bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb")
OTHER_CONNECTION_ID = UUID("cccccccc-cccc-4ccc-cccc-cccccccccccc")
PAIR_ID = UUID("dddddddd-dddd-4ddd-dddd-dddddddddddd")


class ExchangeConnectionSoftDeleteTest(unittest.TestCase):
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
        _create_sqlite_tables(self.engine)
        _seed_user(self.SessionFactory)
        _seed_exchange(self.SessionFactory)
        self.secret_provider = StubSecretRefProvider()
        self.service = ExchangeConnectionService(
            session_factory=self.SessionFactory,
            secret_provider=self.secret_provider,
        )

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_delete_connection_without_external_trades_soft_deletes(self) -> None:
        key_ref = _seed_connection(self.SessionFactory, self.secret_provider, CONNECTION_ID)

        self.service.delete_connection(str(CONNECTION_ID))

        with self.SessionFactory() as session:
            connection = session.get(UserExchangeConnection, CONNECTION_ID)
            self.assertIsNotNone(connection)
            assert connection is not None
            self.assertEqual(connection.status, "deleted")
            self.assertIsNotNone(connection.deleted_at)
            self.assertIsNotNone(connection.revoked_at)
            self.assertEqual(connection.deletion_reason, "user_requested_delete")
            self.assertEqual(connection.metadata_["deletion"]["reason"], "user_requested_delete")
        self.assertIsNone(self.secret_provider.load_exchange_credentials(key_ref))

    def test_delete_connection_with_external_trades_soft_deletes_and_keeps_trades(self) -> None:
        _seed_connection(self.SessionFactory, self.secret_provider, CONNECTION_ID)
        _seed_external_trade(self.SessionFactory, CONNECTION_ID)

        self.service.delete_connection(str(CONNECTION_ID))

        with self.SessionFactory() as session:
            connection = session.get(UserExchangeConnection, CONNECTION_ID)
            self.assertIsNotNone(connection)
            assert connection is not None
            self.assertEqual(connection.status, "deleted")
            self.assertEqual(
                session.scalar(select(func.count()).select_from(ExternalExchangeTrade)),
                1,
            )
            trade = session.scalars(select(ExternalExchangeTrade)).one()
            self.assertEqual(trade.connection_id, CONNECTION_ID)

    def test_list_connections_does_not_include_deleted_connections(self) -> None:
        _seed_connection(self.SessionFactory, self.secret_provider, CONNECTION_ID)
        _seed_connection(self.SessionFactory, self.secret_provider, OTHER_CONNECTION_ID, status="deleted")

        connections = self.service.list_connections(str(USER_ID))

        self.assertEqual([connection.id for connection in connections], [CONNECTION_ID])

    def test_direct_hard_delete_path_is_protected(self) -> None:
        _seed_connection(self.SessionFactory, self.secret_provider, CONNECTION_ID)

        with self.assertRaises(ExchangeConnectionHardDeleteProtected) as context:
            self.service.hard_delete_connection(str(CONNECTION_ID))

        self.assertEqual(context.exception.reason_code, "exchange_connection_hard_delete_protected")

    def test_hard_delete_with_external_trades_reports_conflict(self) -> None:
        _seed_connection(self.SessionFactory, self.secret_provider, CONNECTION_ID)
        _seed_external_trade(self.SessionFactory, CONNECTION_ID)

        with self.assertRaises(ExchangeConnectionHardDeleteConflict) as context:
            self.service.hard_delete_connection(str(CONNECTION_ID), admin_confirm=True)

        self.assertEqual(context.exception.reason_code, "exchange_connection_has_external_history")
        self.assertEqual(context.exception.details["dependencies"]["external_exchange_trades"], 1)


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        for statement in _SQLITE_DDL:
            connection.execute(text(statement))


def _seed_user(session_factory: Any) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            AppUser(
                id=USER_ID,
                email="demo@crypto-radar.local",
                username="demo",
                status="active",
                locale="ru",
                timezone="Europe/Moscow",
                risk_profile="balanced",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _seed_exchange(session_factory: Any) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            MarketExchange(
                id=EXCHANGE_ID,
                code="bybit",
                name="Bybit",
                type="cex",
                status="active",
                api_base_url="https://api.bybit.com",
                ws_base_url=None,
                metadata_={},
                created_at=now,
            )
        )
        session.commit()


def _seed_connection(
    session_factory: Any,
    secret_provider: StubSecretRefProvider,
    connection_id: UUID,
    *,
    status: str = "active",
) -> str:
    now = datetime.now(timezone.utc)
    key_ref = secret_provider.store_exchange_credentials(
        user_id=USER_ID,
        exchange_code="bybit",
        label=f"Main {connection_id}",
        credentials={"api_key": "api_key", "api_secret": "api_secret"},
    )
    with session_factory() as session:
        session.add(
            UserExchangeConnection(
                id=connection_id,
                user_id=USER_ID,
                exchange_id=EXCHANGE_ID,
                label=f"Main {connection_id}",
                account_type="linear",
                key_ref=key_ref,
                permissions={},
                status=status,
                last_sync_at=None,
                revoked_at=now if status == "revoked" else None,
                deleted_at=now if status == "deleted" else None,
                deletion_reason="test_deleted" if status == "deleted" else None,
                metadata_={},
                created_at=now,
            )
        )
        session.commit()
    return key_ref


def _seed_external_trade(session_factory: Any, connection_id: UUID) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            ExternalExchangeTrade(
                id=UUID("eeeeeeee-eeee-4eee-eeee-eeeeeeeeeeee"),
                user_id=USER_ID,
                connection_id=connection_id,
                exchange_trade_id="bybit-trade-1",
                exchange_order_id="bybit-order-1",
                pair_id=PAIR_ID,
                side="buy",
                price=Decimal("100"),
                quantity=Decimal("0.5"),
                fee_amount=Decimal("0.01"),
                fee_asset_id=None,
                traded_at=now,
                imported_at=now,
                metadata_={},
            )
        )
        session.commit()


_SQLITE_DDL = [
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
    """,
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
    """,
    """
    CREATE TABLE market_exchanges (
        id UUID PRIMARY KEY,
        code TEXT,
        name TEXT,
        type TEXT,
        status TEXT,
        api_base_url TEXT,
        ws_base_url TEXT,
        metadata JSON,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE user_exchange_connections (
        id UUID PRIMARY KEY,
        user_id UUID,
        exchange_id UUID,
        label TEXT,
        account_type TEXT,
        key_ref TEXT,
        permissions JSON,
        status TEXT,
        environment TEXT DEFAULT 'testnet',
        order_placement_mode TEXT DEFAULT 'dry_run',
        mainnet_explicitly_enabled BOOLEAN DEFAULT 0,
        last_sync_at DATETIME,
        last_account_snapshot_at DATETIME,
        account_snapshot_status TEXT DEFAULT 'missing',
        revoked_at DATETIME,
        deleted_at DATETIME,
        deletion_reason TEXT,
        metadata JSON,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE external_exchange_orders (
        id UUID PRIMARY KEY,
        user_id UUID,
        connection_id UUID,
        exchange_order_id TEXT,
        pair_id UUID,
        side TEXT,
        order_type TEXT,
        status TEXT,
        quantity NUMERIC,
        price NUMERIC,
        created_exchange_at DATETIME,
        updated_exchange_at DATETIME,
        imported_at DATETIME,
        metadata JSON
    )
    """,
    """
    CREATE TABLE external_exchange_trades (
        id UUID PRIMARY KEY,
        user_id UUID,
        connection_id UUID,
        exchange_trade_id TEXT,
        exchange_order_id TEXT,
        pair_id UUID,
        side TEXT,
        price NUMERIC,
        quantity NUMERIC,
        fee_amount NUMERIC,
        fee_asset_id UUID,
        traded_at DATETIME,
        imported_at DATETIME,
        metadata JSON
    )
    """,
]


if __name__ == "__main__":
    unittest.main()
