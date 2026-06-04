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
from app.exchanges.bybit import BybitApiError, BybitPositionInfo, fetch_bybit_fee_rates, fetch_bybit_positions
from app.schemas.exchange_connection import (
    ExchangeConnectionActionResponse,
    ExchangeConnectionCreateRequest,
    ExchangeFeeRateResponse,
    ExchangeConnectionResponse,
    ExchangeConnectionUpdateRequest,
)
from app.services.user_identity import resolve_app_user


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

    def load_exchange_credentials(self, key_ref: str) -> dict[str, str] | None:
        ...


class StubSecretRefProvider:
    """Dev Vault/KMS boundary stub.

    Raw credentials stay in process memory only and are never returned in API
    responses or persisted to PostgreSQL.
    """

    def __init__(self) -> None:
        self._credentials_by_ref: dict[str, dict[str, str]] = {}

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
        key_ref = f"vault://stub/exchange/{user_id}/{exchange_code.lower()}/{safe_label}/{suffix}"
        self._credentials_by_ref[key_ref] = dict(credentials)
        return key_ref

    def load_exchange_credentials(self, key_ref: str) -> dict[str, str] | None:
        credentials = self._credentials_by_ref.get(key_ref)
        return dict(credentials) if credentials is not None else None


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
            user = resolve_app_user(session, user_id)
            records = session.scalars(
                _connection_select()
                .where(UserExchangeConnection.user_id == user.id)
                .order_by(UserExchangeConnection.created_at.desc())
            ).all()
            return [_connection_to_response(record) for record in records]

    def create_connection(self, request: ExchangeConnectionCreateRequest) -> ExchangeConnectionResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, request.user_id)
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

    def load_credentials(self, key_ref: str) -> dict[str, str] | None:
        return self._secret_provider.load_exchange_credentials(key_ref)

    def test_connection(self, connection_id: str) -> ExchangeConnectionActionResponse:
        connection = self.get_connection(connection_id)
        fee_rate_status: dict[str, Any] = {"checked": False}
        if connection.exchange_code == "bybit":
            try:
                fees = self.get_fee_rates(connection_id, category=_default_fee_category(connection.account_type), symbol=None)
                fee_rate_status = {
                    "checked": True,
                    "status": "ok",
                    "rates": [fee.model_dump(mode="json") for fee in fees[:3]],
                }
            except ValueError as exc:
                fee_rate_status = {
                    "checked": True,
                    "status": "unavailable",
                    "reason": str(exc),
                }
        return ExchangeConnectionActionResponse(
            connection=connection,
            status="ok" if fee_rate_status.get("status") == "ok" else "stubbed",
            message=(
                "Bybit fee-rate API check succeeded."
                if fee_rate_status.get("status") == "ok"
                else "Vault/KMS lookup is stubbed; fee-rate API requires in-process credentials."
            ),
            details={
                "key_ref_present": bool(connection.key_ref),
                "provider": "stub",
                "exchange": connection.exchange_code,
                "fee_rate": fee_rate_status,
            },
        )

    def sync_trades(self, connection_id: str) -> ExchangeConnectionActionResponse:
        _ = self.get_connection(connection_id)
        raise NotImplementedError("External order/trade import must use RealTradeImportService and a connector.")

    def get_fee_rates(
        self,
        connection_id: str,
        *,
        category: str = "linear",
        symbol: str | None = None,
    ) -> list[ExchangeFeeRateResponse]:
        normalized_category = category.strip().lower()
        normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None
        with self._session_factory() as session:
            connection = _get_connection(session, connection_id)
            return self._get_fee_rates_for_connection(
                session=session,
                connection=connection,
                category=normalized_category,
                symbol=normalized_symbol,
                allow_sync=True,
            )

    def get_fee_rates_for_user(
        self,
        *,
        user_id: str = "demo_user",
        exchange_code: str = "bybit",
        category: str = "linear",
        symbol: str | None = None,
        account_type: str | None = None,
        allow_sync: bool = True,
    ) -> list[ExchangeFeeRateResponse]:
        normalized_category = category.strip().lower()
        normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            connection = _active_connection_for_fee(
                session=session,
                user=user,
                exchange_code=exchange_code,
                category=normalized_category,
                account_type=account_type,
            )
            if connection is None:
                return []
            return self._get_fee_rates_for_connection(
                session=session,
                connection=connection,
                category=normalized_category,
                symbol=normalized_symbol,
                allow_sync=allow_sync,
            )

    def _get_fee_rates_for_connection(
        self,
        *,
        session: Session,
        connection: UserExchangeConnection,
        category: str,
        symbol: str | None,
        allow_sync: bool,
    ) -> list[ExchangeFeeRateResponse]:
        cached = _cached_fee_rates(connection, category, symbol)
        if cached:
            return cached
        if not allow_sync:
            return []
        credentials = self._secret_provider.load_exchange_credentials(connection.key_ref)
        if credentials is None:
            raise ValueError(
                "Exchange credentials are not available in the current secret provider. "
                "Reconnect the exchange account or configure a real Vault/KMS provider."
            )
        if connection.exchange.code != "bybit":
            raise ValueError(f"Fee-rate sync is not implemented for {connection.exchange.code}")
        api_key = credentials.get("api_key")
        api_secret = credentials.get("api_secret")
        if not api_key or not api_secret:
            raise ValueError("Bybit fee-rate API requires api_key and api_secret")
        base_url = _bybit_base_url(connection)
        try:
            fetched = fetch_bybit_fee_rates(
                api_key=api_key,
                api_secret=api_secret,
                category=category,
                symbol=symbol,
                base_url=base_url,
            )
        except BybitApiError as exc:
            raise ValueError(str(exc)) from exc
        fetched_at = datetime.now(timezone.utc)
        responses = [
            ExchangeFeeRateResponse(
                connection_id=connection.id,
                exchange_code=connection.exchange.code,
                account_type=connection.account_type,
                category=rate.category,
                symbol=rate.symbol,
                maker_fee_rate=rate.maker_fee_rate,
                taker_fee_rate=rate.taker_fee_rate,
                source="bybit_api",
                fetched_at=fetched_at,
            )
            for rate in fetched
        ]
        _write_fee_rate_cache(connection, responses)
        connection.last_sync_at = fetched_at
        session.commit()
        return responses

    def get_bybit_positions(
        self,
        *,
        user_id: str = "demo_user",
        category: str = "linear",
        symbol: str | None = None,
    ) -> list[BybitPositionInfo]:
        normalized_category = category.strip().lower()
        normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            connection = session.scalars(
                _connection_select()
                .where(UserExchangeConnection.user_id == user.id)
                .where(UserExchangeConnection.status == "active")
                .where(UserExchangeConnection.exchange.has(MarketExchange.code == "bybit"))
                .order_by(UserExchangeConnection.created_at.desc())
            ).first()
            if connection is None:
                return []
            credentials = self._secret_provider.load_exchange_credentials(connection.key_ref)
            if credentials is None:
                raise ValueError(
                    "Exchange credentials are not available in the current secret provider. "
                    "Reconnect the exchange account or configure a real Vault/KMS provider."
                )
            api_key = credentials.get("api_key")
            api_secret = credentials.get("api_secret")
            if not api_key or not api_secret:
                raise ValueError("Bybit position-list API requires api_key and api_secret")
            try:
                return fetch_bybit_positions(
                    api_key=api_key,
                    api_secret=api_secret,
                    category=normalized_category,
                    symbol=normalized_symbol,
                    base_url=_bybit_base_url(connection),
                )
            except BybitApiError as exc:
                raise ValueError(str(exc)) from exc


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


def _active_connection_for_fee(
    *,
    session: Session,
    user: AppUser,
    exchange_code: str,
    category: str,
    account_type: str | None,
) -> UserExchangeConnection | None:
    records = session.scalars(
        _connection_select()
        .where(UserExchangeConnection.user_id == user.id)
        .where(UserExchangeConnection.status == "active")
        .where(UserExchangeConnection.exchange.has(MarketExchange.code == exchange_code.strip().lower()))
        .order_by(UserExchangeConnection.created_at.desc())
    ).all()
    if not records:
        return None
    requested_account_type = account_type.strip().lower() if isinstance(account_type, str) and account_type.strip() else None
    if requested_account_type is not None:
        for connection in records:
            if connection.account_type.strip().lower() == requested_account_type:
                return connection
    for connection in records:
        if _account_type_matches_category(connection.account_type, category):
            return connection
    return records[0]


def _get_exchange(session: Session, exchange_code: str) -> MarketExchange:
    exchange = session.scalars(
        select(MarketExchange).where(MarketExchange.code == exchange_code.strip().lower())
    ).one_or_none()
    if exchange is None:
        raise LookupError(f"Market exchange is not seeded: {exchange_code}")
    return exchange


def _extract_credentials(request: ExchangeConnectionCreateRequest | ExchangeConnectionUpdateRequest) -> dict[str, str]:
    credentials: dict[str, str] = {}
    for field in ("api_key", "api_secret", "api_passphrase"):
        value = getattr(request, field, None)
        if isinstance(value, str) and value.strip():
            credentials[field] = value.strip()
    return credentials


def _default_fee_category(account_type: str) -> str:
    normalized = account_type.strip().lower()
    if normalized in {"linear", "futures", "perpetual", "usdt_perpetual"}:
        return "linear"
    if normalized in {"inverse", "inverse_perpetual"}:
        return "inverse"
    if normalized == "option":
        return "option"
    return "spot"


def _account_type_matches_category(account_type: str, category: str) -> bool:
    return _default_fee_category(account_type) == category.strip().lower()


def _bybit_base_url(connection: UserExchangeConnection) -> str:
    metadata = connection.metadata_ or {}
    if metadata.get("testnet") is True:
        return "https://api-testnet.bybit.com"
    api_base_url = connection.exchange.api_base_url
    if isinstance(api_base_url, str) and api_base_url:
        return api_base_url.rstrip("/")
    return "https://api.bybit.com"


def _fee_rate_cache_key(category: str, symbol: str | None) -> str:
    return f"{category}:{symbol or '*'}"


def _cached_fee_rates(
    connection: UserExchangeConnection,
    category: str,
    symbol: str | None,
) -> list[ExchangeFeeRateResponse]:
    cache = (connection.metadata_ or {}).get("fee_rates")
    if not isinstance(cache, dict):
        return []
    keys = [_fee_rate_cache_key(category, symbol)]
    if symbol is not None:
        keys.append(_fee_rate_cache_key(category, None))
    responses: list[ExchangeFeeRateResponse] = []
    for key in keys:
        value = cache.get(key)
        if not isinstance(value, dict):
            continue
        try:
            responses.append(
                ExchangeFeeRateResponse(
                    connection_id=connection.id,
                    exchange_code=connection.exchange.code,
                    account_type=str(value.get("account_type") or connection.account_type),
                    category=str(value.get("category") or category),
                    symbol=str(value["symbol"]) if value.get("symbol") else None,
                    maker_fee_rate=float(value["maker_fee_rate"]),
                    taker_fee_rate=float(value["taker_fee_rate"]),
                    source="cache",
                    fetched_at=datetime.fromisoformat(str(value["fetched_at"])),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return responses


def _write_fee_rate_cache(
    connection: UserExchangeConnection,
    fees: list[ExchangeFeeRateResponse],
) -> None:
    metadata = dict(connection.metadata_ or {})
    cache = dict(metadata.get("fee_rates") or {})
    for fee in fees:
        cache[_fee_rate_cache_key(fee.category, fee.symbol)] = {
            "category": fee.category,
            "symbol": fee.symbol,
            "account_type": fee.account_type or connection.account_type,
            "maker_fee_rate": fee.maker_fee_rate,
            "taker_fee_rate": fee.taker_fee_rate,
            "fetched_at": fee.fetched_at.isoformat(),
            "source": fee.source,
        }
    metadata["fee_rates"] = cache
    metadata["fee_rates_updated_at"] = datetime.now(timezone.utc).isoformat()
    connection.metadata_ = metadata


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
