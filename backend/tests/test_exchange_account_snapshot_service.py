from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.exchanges.bybit import BybitPositionInfo, BybitWalletBalance
from app.models.exchange_connection import UserExchangeConnection
from app.models.market import MarketExchange
from app.models.user import AppUser
from app.services.execution_service import _live_account_snapshot_blockers
from app.services.exchange_account_snapshot import ExchangeAccountSnapshotService

USER_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd524")
OTHER_USER_ID = UUID("c6d793f7-96d2-4330-9d08-1fe69e9b09c3")
EXCHANGE_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
CONNECTION_ID = UUID("bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb")
OTHER_CONNECTION_ID = UUID("cccccccc-cccc-4ccc-cccc-cccccccccccc")


class ExchangeAccountSnapshotServiceTest(unittest.TestCase):
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
        _seed_user(self.SessionFactory, USER_ID, email="demo@crypto-radar.local", username="demo")
        _seed_user(
            self.SessionFactory,
            OTHER_USER_ID,
            email="other@example.test",
            username="other",
        )
        _seed_exchange(self.SessionFactory)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_get_snapshot_fetches_wallet_and_positions_from_active_connection(self) -> None:
        _seed_connection(self.SessionFactory, CONNECTION_ID, USER_ID)
        captured: dict[str, Any] = {}

        def wallet_fetcher(**kwargs: Any) -> BybitWalletBalance:
            captured["wallet"] = kwargs
            return _wallet()

        def position_fetcher(**kwargs: Any) -> list[BybitPositionInfo]:
            captured["positions"] = kwargs
            return [_position()]

        service = _service(
            self.SessionFactory,
            wallet_fetcher=wallet_fetcher,
            position_fetcher=position_fetcher,
        )

        snapshot = service.get_snapshot(user_id=str(USER_ID), exchange="bybit")

        self.assertEqual(snapshot.status, "fresh")
        self.assertEqual(snapshot.source, "exchange")
        self.assertEqual(snapshot.account_equity, Decimal("100.25"))
        self.assertIsInstance(snapshot.account_equity, Decimal)
        self.assertEqual(snapshot.available_balance, Decimal("80.5"))
        self.assertIsInstance(snapshot.available_balance, Decimal)
        self.assertEqual(snapshot.wallet_balance, Decimal("99.75"))
        self.assertEqual(snapshot.total_initial_margin, Decimal("10.25"))
        self.assertEqual(snapshot.total_maintenance_margin, Decimal("5.125"))
        self.assertEqual(len(snapshot.positions), 1)
        self.assertEqual(snapshot.positions[0].symbol, "BTCUSDT")
        self.assertEqual(snapshot.positions[0].side, "long")
        self.assertEqual(snapshot.positions[0].quantity, Decimal("0.1"))
        self.assertEqual(snapshot.positions[0].notional, Decimal("5000"))
        self.assertEqual(snapshot.positions[0].entry_price, Decimal("50000"))
        self.assertEqual(snapshot.positions[0].mark_price, Decimal("51000"))
        self.assertEqual(snapshot.positions[0].unrealized_pnl, Decimal("12.5"))
        self.assertEqual(captured["wallet"]["account_type"], "UNIFIED")
        self.assertEqual(captured["wallet"]["base_url"], "https://api-testnet.bybit.com")
        self.assertEqual(captured["positions"]["category"], "linear")
        self.assertEqual(captured["positions"]["api_key"], "api_key")

    def test_missing_connection_returns_missing_snapshot_with_clear_warning(self) -> None:
        snapshot = _service(self.SessionFactory).get_snapshot(user_id=str(USER_ID), exchange="bybit")

        self.assertEqual(snapshot.status, "missing")
        self.assertEqual(snapshot.source, "exchange")
        self.assertTrue(
            any("Active bybit exchange connection is missing" in warning for warning in snapshot.warnings)
        )

    def test_connection_id_validates_ownership(self) -> None:
        _seed_connection(self.SessionFactory, OTHER_CONNECTION_ID, OTHER_USER_ID)

        snapshot = _service(self.SessionFactory).get_snapshot(
            user_id=str(USER_ID),
            exchange="bybit",
            connection_id=OTHER_CONNECTION_ID,
        )

        self.assertEqual(snapshot.status, "missing")
        self.assertTrue(
            any("does not belong to the resolved user" in warning for warning in snapshot.warnings)
        )

    def test_wallet_failure_returns_stale_cached_snapshot_without_crashing_live_guard(self) -> None:
        _seed_connection(self.SessionFactory, CONNECTION_ID, USER_ID)
        calls = 0

        def wallet_fetcher(**_kwargs: Any) -> BybitWalletBalance:
            nonlocal calls
            calls += 1
            if calls == 1:
                return _wallet()
            raise RuntimeError("wallet timeout")

        service = _service(self.SessionFactory, wallet_fetcher=wallet_fetcher)

        fresh = service.get_snapshot(user_id=str(USER_ID), exchange="bybit")
        stale = service.get_snapshot(user_id=str(USER_ID), exchange="bybit", force_refresh=True)

        self.assertEqual(fresh.status, "fresh")
        self.assertEqual(stale.status, "stale")
        self.assertEqual(stale.account_equity, Decimal("100.25"))
        self.assertTrue(any("wallet timeout" in warning for warning in stale.warnings))
        self.assertEqual(
            _live_account_snapshot_blockers(stale),
            ["Fresh exchange account snapshot is required before live entry."],
        )

    def test_get_real_account_snapshot_dry_run_does_not_fetch_wallet(self) -> None:
        calls = 0

        def wallet_fetcher(**_kwargs: Any) -> BybitWalletBalance:
            nonlocal calls
            calls += 1
            raise AssertionError("wallet fetcher should not run in dry-run")

        service = _service(self.SessionFactory, wallet_fetcher=wallet_fetcher)

        snapshot = service.get_real_account_snapshot(
            user_id="usr_demo",
            exchange="bybit",
            mode="real",
            live_adapter=False,
            request_account_balance=Decimal("321.50"),
        )

        self.assertEqual(calls, 0)
        self.assertEqual(snapshot.status, "fresh")
        self.assertEqual(snapshot.source, "demo")
        self.assertEqual(snapshot.account_equity, Decimal("321.50"))
        self.assertEqual(snapshot.available_balance, Decimal("321.50"))

    def test_usr_demo_resolves_to_seeded_demo_user(self) -> None:
        _seed_connection(self.SessionFactory, CONNECTION_ID, USER_ID)

        snapshot = _service(self.SessionFactory).get_snapshot(user_id="usr_demo", exchange="bybit")

        self.assertEqual(snapshot.status, "fresh")
        self.assertEqual(snapshot.account_equity, Decimal("100.25"))

    def test_cache_reuses_snapshot_and_force_refresh_bypasses_it_without_secrets(self) -> None:
        _seed_connection(self.SessionFactory, CONNECTION_ID, USER_ID)
        calls = 0

        def wallet_fetcher(**_kwargs: Any) -> BybitWalletBalance:
            nonlocal calls
            calls += 1
            return _wallet(total_equity=Decimal("100.25") + Decimal(calls - 1))

        service = _service(self.SessionFactory, wallet_fetcher=wallet_fetcher)

        first = service.get_snapshot(user_id=str(USER_ID), exchange="bybit")
        second = service.get_snapshot(user_id=str(USER_ID), exchange="bybit")
        refreshed = service.get_snapshot(user_id=str(USER_ID), exchange="bybit", force_refresh=True)

        self.assertEqual(calls, 2)
        self.assertEqual(first.account_equity, Decimal("100.25"))
        self.assertEqual(second.account_equity, Decimal("100.25"))
        self.assertEqual(refreshed.account_equity, Decimal("101.25"))
        dumped = json.dumps(refreshed.model_dump(mode="json"), sort_keys=True)
        self.assertNotIn("api_secret", dumped)
        self.assertNotIn("secret", dumped.lower())


class _CredentialProvider:
    def load_credentials(self, key_ref: str) -> dict[str, str] | None:
        if key_ref != "vault://test/bybit":
            return None
        return {"api_key": "api_key", "api_secret": "api_secret"}


def _service(
    session_factory: Any,
    *,
    wallet_fetcher: Any | None = None,
    position_fetcher: Any | None = None,
) -> ExchangeAccountSnapshotService:
    return ExchangeAccountSnapshotService(
        session_factory,
        credential_provider=_CredentialProvider(),
        bybit_wallet_fetcher=wallet_fetcher or (lambda **_kwargs: _wallet()),
        bybit_position_fetcher=position_fetcher or (lambda **_kwargs: []),
        snapshot_ttl_seconds=15,
    )


def _wallet(*, total_equity: Decimal = Decimal("100.25")) -> BybitWalletBalance:
    return BybitWalletBalance(
        account_type="UNIFIED",
        total_equity=total_equity,
        total_wallet_balance=Decimal("99.75"),
        total_margin_balance=Decimal("100.00"),
        total_available_balance=Decimal("80.5"),
        total_initial_margin=Decimal("10.25"),
        total_maintenance_margin=Decimal("5.125"),
        total_perp_upl=Decimal("0.5"),
        coins=(),
        raw_payload={},
    )


def _position() -> BybitPositionInfo:
    return BybitPositionInfo(
        category="linear",
        symbol="BTCUSDT",
        side="Buy",
        size=0.1,
        liquidation_price=45000.0,
        raw_payload={
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "0.1",
            "avgPrice": "50000",
            "markPrice": "51000",
            "positionValue": "5000",
            "unrealisedPnl": "12.5",
            "positionIM": "100",
            "positionMM": "25",
            "tradeMode": "0",
        },
    )


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        for statement in _SQLITE_DDL:
            connection.execute(text(statement))


def _seed_user(session_factory: Any, user_id: UUID, *, email: str, username: str) -> None:
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
    connection_id: UUID,
    user_id: UUID,
) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            UserExchangeConnection(
                id=connection_id,
                user_id=user_id,
                exchange_id=EXCHANGE_ID,
                label="Main",
                account_type="linear",
                key_ref="vault://test/bybit",
                permissions={},
                status="active",
                last_sync_at=None,
                metadata_={
                    "accountType": "UNIFIED",
                    "position_category": "linear",
                    "testnet": True,
                },
                created_at=now,
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
        last_sync_at DATETIME,
        revoked_at DATETIME,
        deleted_at DATETIME,
        deletion_reason TEXT,
        metadata JSON,
        created_at DATETIME
    )
    """,
]


if __name__ == "__main__":
    unittest.main()
