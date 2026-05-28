from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.clickhouse_client import get_clickhouse_client
from app.core.database import SessionLocal
from app.models.exchange_connection import UserExchangeConnection
from app.models.external_exchange import ExternalExchangeOrder, ExternalExchangeTrade
from app.models.market import MarketPair
from app.schemas.external_exchange import (
    ExternalExchangeOrderResponse,
    ExternalExchangeTradeResponse,
    RealTradeImportNotReadyResponse,
    RealTradeImportRequest,
    RealTradeImportResult,
)
from app.services.bootstrap_service import DEMO_USERNAME


class ClickHouseInsertClient(Protocol):
    def insert(
        self,
        table: str,
        data: list[list[Any]],
        column_names: list[str],
    ) -> None:
        ...


class RealTradeConnector(Protocol):
    def import_connection(
        self,
        connection: UserExchangeConnection,
        request: RealTradeImportRequest,
    ) -> RealTradeImportResult:
        ...


class RealTradeImportNotReadyError(NotImplementedError):
    def __init__(self, response: RealTradeImportNotReadyResponse) -> None:
        super().__init__(response.message)
        self.response = response


class RealTradeImportRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def get_connection(self, connection_id: UUID | str) -> UserExchangeConnection:
        with self._session_factory() as session:
            connection = session.scalars(
                _connection_select().where(UserExchangeConnection.id == _parse_uuid(connection_id))
            ).one_or_none()
            if connection is None:
                raise LookupError(f"Exchange connection not found: {connection_id}")
            session.expunge(connection)
            return connection

    def list_orders(
        self,
        *,
        user_id: str = "demo_user",
        connection_id: UUID | str | None = None,
        limit: int = 100,
    ) -> list[ExternalExchangeOrderResponse]:
        with self._session_factory() as session:
            statement = (
                select(ExternalExchangeOrder)
                .join(ExternalExchangeOrder.connection)
                .options(
                    joinedload(ExternalExchangeOrder.connection).joinedload(UserExchangeConnection.exchange),
                    joinedload(ExternalExchangeOrder.pair).joinedload(MarketPair.exchange),
                )
                .order_by(ExternalExchangeOrder.imported_at.desc())
                .limit(limit)
            )
            statement = _scope_to_user(statement, user_id)
            if connection_id is not None:
                statement = statement.where(ExternalExchangeOrder.connection_id == _parse_uuid(connection_id))
            return [_order_to_response(order) for order in session.scalars(statement).all()]

    def list_trades(
        self,
        *,
        user_id: str = "demo_user",
        connection_id: UUID | str | None = None,
        limit: int = 100,
    ) -> list[ExternalExchangeTradeResponse]:
        with self._session_factory() as session:
            statement = (
                select(ExternalExchangeTrade)
                .join(ExternalExchangeTrade.connection)
                .options(
                    joinedload(ExternalExchangeTrade.connection).joinedload(UserExchangeConnection.exchange),
                    joinedload(ExternalExchangeTrade.pair).joinedload(MarketPair.exchange),
                    joinedload(ExternalExchangeTrade.fee_asset),
                )
                .order_by(ExternalExchangeTrade.traded_at.desc(), ExternalExchangeTrade.imported_at.desc())
                .limit(limit)
            )
            statement = _scope_to_user(statement, user_id)
            if connection_id is not None:
                statement = statement.where(ExternalExchangeTrade.connection_id == _parse_uuid(connection_id))
            return [_trade_to_response(trade) for trade in session.scalars(statement).all()]


class ClickHouseRealTradeAnalyticsWriter:
    _external_trade_columns = [
        "user_id",
        "connection_id",
        "exchange",
        "symbol",
        "exchange_trade_id",
        "side",
        "price",
        "quantity",
        "fee",
        "traded_at",
        "imported_at",
    ]
    _raw_event_columns = [
        "exchange",
        "event_type",
        "symbol",
        "event_ts",
        "ingest_ts",
        "source_id",
        "sequence_id",
        "raw_payload",
    ]

    def __init__(self, clickhouse_client_factory: Any = get_clickhouse_client) -> None:
        self._clickhouse_client_factory = clickhouse_client_factory

    def write_external_trade(self, trade: ExternalExchangeTrade) -> None:
        self._client().insert(
            "analytics.external_trade_events",
            [
                [
                    trade.user_id,
                    trade.connection_id,
                    trade.connection.exchange.code,
                    trade.pair.symbol,
                    trade.exchange_trade_id,
                    trade.side,
                    trade.price,
                    trade.quantity,
                    trade.fee_amount,
                    trade.traded_at,
                    trade.imported_at,
                ]
            ],
            column_names=self._external_trade_columns,
        )

    def write_raw_import_event(
        self,
        *,
        connection: UserExchangeConnection,
        symbol: str,
        source_id: str,
        payload: dict[str, Any],
        event_ts: datetime | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self._client().insert(
            "market.raw_exchange_events",
            [
                [
                    connection.exchange.code,
                    "external_trade.import",
                    symbol,
                    event_ts or now,
                    now,
                    source_id,
                    None,
                    json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")),
                ]
            ],
            column_names=self._raw_event_columns,
        )

    def _client(self) -> ClickHouseInsertClient:
        return self._clickhouse_client_factory()


class RealTradeImportService:
    def __init__(
        self,
        repository: RealTradeImportRepository | None = None,
        connector: RealTradeConnector | None = None,
        analytics_writer: ClickHouseRealTradeAnalyticsWriter | None = None,
    ) -> None:
        self._repository = repository or RealTradeImportRepository()
        self._connector = connector
        self._analytics_writer = analytics_writer or ClickHouseRealTradeAnalyticsWriter()

    def import_connection(self, request: RealTradeImportRequest) -> RealTradeImportResult:
        connection = self._repository.get_connection(request.connection_id)
        if self._connector is None:
            raise RealTradeImportNotReadyError(
                RealTradeImportNotReadyResponse(
                    message=(
                        "External exchange trade import connector is not implemented yet. "
                        "Normalized writes are reserved for PostgreSQL external_exchange_orders/external_exchange_trades; "
                        "analytics writes are reserved for ClickHouse analytics.external_trade_events and market.raw_exchange_events."
                    ),
                    connection_id=connection.id,
                    details={
                        "exchange": connection.exchange.code,
                        "account_type": connection.account_type,
                        "key_ref_present": bool(connection.key_ref),
                        "requested_symbols": request.symbols,
                        "since": request.since.isoformat() if request.since else None,
                        "until": request.until.isoformat() if request.until else None,
                        "dry_run": request.dry_run,
                    },
                )
            )
        return self._connector.import_connection(connection, request)

    def list_orders(
        self,
        *,
        user_id: str = "demo_user",
        connection_id: UUID | str | None = None,
        limit: int = 100,
    ) -> list[ExternalExchangeOrderResponse]:
        return self._repository.list_orders(user_id=user_id, connection_id=connection_id, limit=limit)

    def list_trades(
        self,
        *,
        user_id: str = "demo_user",
        connection_id: UUID | str | None = None,
        limit: int = 100,
    ) -> list[ExternalExchangeTradeResponse]:
        return self._repository.list_trades(user_id=user_id, connection_id=connection_id, limit=limit)


def _connection_select():
    return select(UserExchangeConnection).options(
        joinedload(UserExchangeConnection.exchange),
        joinedload(UserExchangeConnection.user),
    )


def _scope_to_user(statement: Any, user_id: str) -> Any:
    if user_id == "demo_user":
        return statement.where(UserExchangeConnection.user.has(username=DEMO_USERNAME))
    user_uuid = _parse_uuid(user_id)
    if user_uuid is not None:
        return statement.where(UserExchangeConnection.user_id == user_uuid)
    return statement.where(UserExchangeConnection.user.has(username=user_id))


def _order_to_response(order: ExternalExchangeOrder) -> ExternalExchangeOrderResponse:
    return ExternalExchangeOrderResponse(
        id=order.id,
        user_id=order.user_id,
        connection_id=order.connection_id,
        exchange_order_id=order.exchange_order_id,
        pair_id=order.pair_id,
        exchange_code=order.connection.exchange.code,
        symbol=order.pair.symbol,
        side=order.side,
        order_type=order.order_type,
        status=order.status,
        quantity=order.quantity,
        price=order.price,
        created_exchange_at=order.created_exchange_at,
        updated_exchange_at=order.updated_exchange_at,
        imported_at=order.imported_at,
        metadata=order.metadata_,
    )


def _trade_to_response(trade: ExternalExchangeTrade) -> ExternalExchangeTradeResponse:
    return ExternalExchangeTradeResponse(
        id=trade.id,
        user_id=trade.user_id,
        connection_id=trade.connection_id,
        exchange_trade_id=trade.exchange_trade_id,
        exchange_order_id=trade.exchange_order_id,
        pair_id=trade.pair_id,
        exchange_code=trade.connection.exchange.code,
        symbol=trade.pair.symbol,
        side=trade.side,
        price=trade.price,
        quantity=trade.quantity,
        fee_amount=trade.fee_amount,
        fee_asset_id=trade.fee_asset_id,
        fee_asset_symbol=trade.fee_asset.symbol if trade.fee_asset is not None else None,
        traded_at=trade.traded_at,
        imported_at=trade.imported_at,
        metadata=trade.metadata_,
    )


def _parse_uuid(value: UUID | str) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None or isinstance(value, Decimal):
        return value
    return Decimal(str(value))


real_trade_import_service = RealTradeImportService()
