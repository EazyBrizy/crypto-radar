from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.models.exchange_connection import UserExchangeConnection
from app.models.market import MarketExchange
from app.models.user import AppUser
from app.schemas.exchange_connection import (
    ExchangeConnectionActionResponse,
    ExchangeConnectionCreateRequest,
    ExchangeConnectionResponse,
    ExchangeConnectionUpdateRequest,
)
from app.services.bootstrap_service import DEMO_USERNAME


class SecretRefProvider(Protocol):
    def store_exchange_credentials(
        self,
        *,
        user_id: UUID,
        exchange_code: str,
        label: str,
        credentials: dict[str, str],
    ) -> str:
        ...


class StubSecretRefProvider:
    """Vault/KMS boundary stub: returns only a secret reference and stores no raw credentials."""

    def store_exchange_credentials(
        self,
        *,
        user_id: UUID,
        exchange_code: str,
        label: str,
        credentials: dict[str, str],
    ) -> str:
        suffix = uuid4().hex
        safe_label = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in label.strip().lower())
        return f"vault://stub/exchange/{user_id}/{exchange_code.lower()}/{safe_label}/{suffix}"


class ExchangeConnectionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        secret_provider: SecretRefProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._secret_provider = secret_provider or StubSecretRefProvider()

    def list_connections(self, user_id: str = "demo_user") -> list[ExchangeConnectionResponse]:
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
            records = session.scalars(
                _connection_select()
                .where(UserExchangeConnection.user_id == user.id)
                .order_by(UserExchangeConnection.created_at.desc())
            ).all()
            return [_connection_to_response(record) for record in records]

    def create_connection(self, request: ExchangeConnectionCreateRequest) -> ExchangeConnectionResponse:
        with self._session_factory() as session:
            user = _resolve_user(session, request.user_id)
            exchange = _get_exchange(session, request.exchange_code)
            credentials = _extract_credentials(request)
            key_ref = self._secret_provider.store_exchange_credentials(
                user_id=user.id,
                exchange_code=exchange.code,
                label=request.label,
                credentials=credentials,
            )
            connection = UserExchangeConnection(
                user_id=user.id,
                exchange_id=exchange.id,
                label=request.label.strip(),
                account_type=request.account_type.strip() or "spot",
                key_ref=key_ref,
                permissions=request.permissions,
                status="active",
                metadata_={
                    **request.metadata,
                    "secret_provider": "stub",
                    "credentials_received": sorted(credentials.keys()),
                    "raw_credentials_stored": False,
                },
            )
            session.add(connection)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("Exchange connection label must be unique per user and exchange") from exc
            return self.get_connection(str(connection.id))

    def get_connection(self, connection_id: str) -> ExchangeConnectionResponse:
        with self._session_factory() as session:
            connection = _get_connection(session, connection_id)
            return _connection_to_response(connection)

    def update_connection(
        self,
        connection_id: str,
        request: ExchangeConnectionUpdateRequest,
    ) -> ExchangeConnectionResponse:
        with self._session_factory() as session:
            connection = _get_connection(session, connection_id)
            if request.label is not None:
                connection.label = request.label.strip()
            if request.account_type is not None:
                connection.account_type = request.account_type.strip() or connection.account_type
            if request.permissions is not None:
                connection.permissions = request.permissions
            if request.status is not None:
                connection.status = request.status.strip()
            if request.metadata is not None:
                connection.metadata_ = {**connection.metadata_, **request.metadata}

            credentials = _extract_credentials(request)
            if credentials:
                connection.key_ref = self._secret_provider.store_exchange_credentials(
                    user_id=connection.user_id,
                    exchange_code=connection.exchange.code,
                    label=connection.label,
                    credentials=credentials,
                )
                connection.metadata_ = {
                    **connection.metadata_,
                    "secret_provider": "stub",
                    "credentials_received": sorted(credentials.keys()),
                    "raw_credentials_stored": False,
                    "credentials_rotated_at": datetime.now(timezone.utc).isoformat(),
                }

            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("Exchange connection label must be unique per user and exchange") from exc
            return self.get_connection(connection_id)

    def delete_connection(self, connection_id: str) -> None:
        with self._session_factory() as session:
            connection = _get_connection(session, connection_id)
            session.delete(connection)
            session.commit()

    def test_connection(self, connection_id: str) -> ExchangeConnectionActionResponse:
        connection = self.get_connection(connection_id)
        return ExchangeConnectionActionResponse(
            connection=connection,
            message="Vault/KMS lookup and exchange auth are stubbed; key_ref is present.",
            details={
                "key_ref_present": bool(connection.key_ref),
                "provider": "stub",
                "exchange": connection.exchange_code,
            },
        )

    def sync_trades(self, connection_id: str) -> ExchangeConnectionActionResponse:
        _ = self.get_connection(connection_id)
        raise NotImplementedError("External order/trade import must use RealTradeImportService and a connector.")


def _connection_select():
    return select(UserExchangeConnection).options(
        joinedload(UserExchangeConnection.exchange),
        joinedload(UserExchangeConnection.user),
    )


def _get_connection(session: Session, connection_id: str) -> UserExchangeConnection:
    connection_uuid = _parse_uuid(connection_id)
    if connection_uuid is None:
        raise ValueError(f"Invalid exchange connection id: {connection_id}")
    connection = session.scalars(
        _connection_select().where(UserExchangeConnection.id == connection_uuid)
    ).one_or_none()
    if connection is None:
        raise LookupError(f"Exchange connection not found: {connection_id}")
    return connection


def _get_exchange(session: Session, exchange_code: str) -> MarketExchange:
    exchange = session.scalars(
        select(MarketExchange).where(MarketExchange.code == exchange_code.strip().lower())
    ).one_or_none()
    if exchange is None:
        raise LookupError(f"Market exchange is not seeded: {exchange_code}")
    return exchange


def _resolve_user(session: Session, user_id: str) -> AppUser:
    user_uuid = _parse_uuid(user_id)
    if user_uuid is not None:
        user = session.get(AppUser, user_uuid)
        if user is not None:
            return user
    user = session.scalars(
        select(AppUser).where((AppUser.username == user_id) | (AppUser.email == user_id))
    ).one_or_none()
    if user is not None:
        return user
    if user_id == "demo_user":
        user = session.scalars(select(AppUser).where(AppUser.username == DEMO_USERNAME)).one_or_none()
        if user is not None:
            return user
    raise ValueError(f"User is not seeded: {user_id}")


def _extract_credentials(request: ExchangeConnectionCreateRequest | ExchangeConnectionUpdateRequest) -> dict[str, str]:
    credentials: dict[str, str] = {}
    for field in ("api_key", "api_secret", "api_passphrase"):
        value = getattr(request, field, None)
        if isinstance(value, str) and value.strip():
            credentials[field] = value.strip()
    return credentials


def _parse_uuid(value: str | UUID) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _connection_to_response(connection: UserExchangeConnection) -> ExchangeConnectionResponse:
    return ExchangeConnectionResponse(
        id=connection.id,
        user_id=connection.user_id,
        exchange_id=connection.exchange_id,
        exchange_code=connection.exchange.code,
        exchange_name=connection.exchange.name,
        label=connection.label,
        account_type=connection.account_type,
        key_ref=connection.key_ref,
        permissions=connection.permissions,
        status=connection.status,
        last_sync_at=connection.last_sync_at,
        metadata=connection.metadata_,
        created_at=connection.created_at,
    )


exchange_connection_service = ExchangeConnectionService()
