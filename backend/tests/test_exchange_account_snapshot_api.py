from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import exchanges as exchanges_api
from app.exchanges.bybit import BybitCoinBalance, BybitPositionInfo, BybitWalletBalance
from app.models.exchange_connection import UserExchangeConnection
from app.models.market import MarketExchange
from app.models.user import AppUser
from app.services.exchange_account_snapshot import ExchangeAccountSnapshotService
from app.services.exchange_connection_service import ExchangeConnectionService

USER_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd524")
OTHER_USER_ID = UUID("c6d793f7-96d2-4330-9d08-1fe69e9b09c3")
EXCHANGE_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
CONNECTION_ID = UUID("bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb")
OTHER_CONNECTION_ID = UUID("cccccccc-cccc-4ccc-cccc-cccccccccccc")


class ExchangeAccountSnapshotApiTest(unittest.TestCase):
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
        _seed_connection(self.SessionFactory, CONNECTION_ID, USER_ID)
        _seed_connection(self.SessionFactory, OTHER_CONNECTION_ID, OTHER_USER_ID)
        app = FastAPI()
        app.include_router(exchanges_api.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_authorized_demo_user_can_fetch_account_snapshot(self) -> None:
        with self._patched_services():
            response = self.client.get(
                f"/exchanges/connections/{CONNECTION_ID}/account-snapshot",
                params={"user_id": "demo_user"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "fresh")
        self.assertEqual(_decimal(payload["account_equity"]), Decimal("100.25"))
        self.assertEqual(_decimal(payload["available_balance"]), Decimal("80.5"))
        self.assertEqual(payload["source"], "exchange")

    def test_usr_demo_alias_can_fetch_wallet_balance(self) -> None:
        with self._patched_services():
            response = self.client.get(
                f"/exchanges/connections/{CONNECTION_ID}/wallet-balance",
                params={"user_id": "usr_demo"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "fresh")
        self.assertEqual(payload["connection_id"], str(CONNECTION_ID))
        self.assertEqual(_decimal(payload["total_equity"]), Decimal("100.25"))
        self.assertEqual(payload["coins"][0]["coin"], "USDT")

    def test_unknown_user_fails_clearly(self) -> None:
        with self._patched_services():
            response = self.client.get(
                f"/exchanges/connections/{CONNECTION_ID}/account-snapshot",
                params={"user_id": "missing_user"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn("User is not seeded: missing_user", response.json()["detail"])

    def test_wrong_user_connection_ownership_is_rejected(self) -> None:
        with self._patched_services():
            response = self.client.get(
                f"/exchanges/connections/{OTHER_CONNECTION_ID}/account-snapshot",
                params={"user_id": "demo_user"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("does not belong to the resolved user", response.json()["detail"])

    def test_wallet_response_does_not_expose_api_secrets(self) -> None:
        with self._patched_services():
            response = self.client.get(
                f"/exchanges/connections/{CONNECTION_ID}/wallet-balance",
                params={"user_id": "demo_user", "force_refresh": True},
            )

        self.assertEqual(response.status_code, 200)
        dumped = json.dumps(response.json(), sort_keys=True).lower()
        self.assertNotIn("api_key", dumped)
        self.assertNotIn("api_secret", dumped)
        self.assertNotIn("secret", dumped)
        self.assertNotIn("vault://test/bybit", dumped)

    def test_wallet_fetch_error_returns_safe_status_and_warnings(self) -> None:
        def wallet_fetcher(**_kwargs: Any) -> BybitWalletBalance:
            raise RuntimeError("wallet timeout")

        with self._patched_services(wallet_fetcher=wallet_fetcher):
            response = self.client.get(
                f"/exchanges/connections/{CONNECTION_ID}/wallet-balance",
                params={"user_id": "demo_user", "force_refresh": True},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "missing")
        self.assertTrue(any("wallet timeout" in warning for warning in payload["warnings"]))

    def _patched_services(self, *, wallet_fetcher: Any | None = None):
        connection_service = ExchangeConnectionService(self.SessionFactory)
        snapshot_service = ExchangeAccountSnapshotService(
            self.SessionFactory,
            credential_provider=_CredentialProvider(),
            bybit_wallet_fetcher=wallet_fetcher or (lambda **_kwargs: _wallet()),
            bybit_position_fetcher=lambda **_kwargs: [_position()],
            snapshot_ttl_seconds=15,
        )
        return _PatchContext(
            patch("app.api.v1.exchanges.exchange_connection_service", connection_service),
            patch("app.api.v1.exchanges.exchange_account_snapshot_service", snapshot_service),
        )


class _PatchContext:
    def __init__(self, *patches: Any) -> None:
        self._patches = patches

    def __enter__(self) -> None:
        for patcher in self._patches:
            patcher.__enter__()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        for patcher in reversed(self._patches):
            patcher.__exit__(exc_type, exc, tb)


class _CredentialProvider:
    def load_credentials(self, key_ref: str) -> dict[str, str] | None:
        if key_ref != "vault://test/bybit":
            return None
        return {"api_key": "api_key", "api_secret": "api_secret"}


def _wallet() -> BybitWalletBalance:
    return BybitWalletBalance(
        account_type="UNIFIED",
        total_equity=Decimal("100.25"),
        total_wallet_balance=Decimal("99.75"),
        total_margin_balance=Decimal("100.00"),
        total_available_balance=Decimal("80.5"),
        total_initial_margin=Decimal("10.25"),
        total_maintenance_margin=Decimal("5.125"),
        total_perp_upl=Decimal("0.5"),
        coins=(
            BybitCoinBalance(
                coin="USDT",
                equity=Decimal("100.25"),
                usd_value=Decimal("100.25"),
                wallet_balance=Decimal("99.75"),
                available_to_withdraw=Decimal("80.5"),
                locked=Decimal("0"),
                borrow_amount=Decimal("0"),
                accrued_interest=Decimal("0"),
                total_order_im=Decimal("0"),
                total_position_im=Decimal("10.25"),
                total_position_mm=Decimal("5.125"),
                unrealised_pnl=Decimal("0.5"),
                raw_payload={},
            ),
        ),
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


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


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
        metadata JSON,
        created_at DATETIME
    )
    """,
]


if __name__ == "__main__":
    unittest.main()
