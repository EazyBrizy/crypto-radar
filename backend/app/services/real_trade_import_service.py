from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.clickhouse_client import get_clickhouse_client
from app.core.database import SessionLocal
from app.models.audit import AuditLog
from app.models.exchange_connection import UserExchangeConnection
from app.models.external_exchange import ExternalExchangeOrder, ExternalExchangeTrade
from app.models.market import MarketPair
from app.models.portfolio import Order, Position
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


@dataclass(frozen=True)
class ExchangeOrderSnapshot:
    exchange: str
    symbol: str
    side: str
    status: str
    exchange_order_id: str | None = None
    client_order_id: str | None = None
    order_type: str | None = None
    quantity: Decimal | None = None
    filled_quantity: Decimal | None = None
    price: Decimal | None = None
    stop_price: Decimal | None = None
    avg_price: Decimal | None = None
    reduce_only: bool = False
    role: str | None = None
    signal_id: str | None = None
    position_id: str | None = None
    updated_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangePositionSnapshot:
    exchange: str
    symbol: str
    side: str
    quantity: Decimal
    entry_avg_price: Decimal
    signal_id: str | None = None
    position_id: str | None = None
    exchange_position_id: str | None = None
    mark_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    updated_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalOrderRef:
    id: UUID
    user_id: UUID
    exchange: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: Decimal
    signal_id: str | None = None
    position_id: str | None = None
    exchange_order_id: str | None = None
    client_order_id: str | None = None
    role: str | None = None
    reduce_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalPositionRef:
    id: UUID
    user_id: UUID
    exchange: str
    symbol: str
    side: str
    status: str
    quantity: Decimal
    entry_avg_price: Decimal
    signal_id: str | None = None
    stop_loss: Decimal | None = None


@dataclass(frozen=True)
class RealPositionSyncChange:
    action: str
    entity_type: str
    entity_id: str | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RealPositionSyncResult:
    connection_id: str
    orders_seen: int
    positions_seen: int
    external_orders_written: int
    local_orders_updated: int
    local_positions_updated: int
    audit_events: int
    unmatched_positions: list[dict[str, Any]]
    changes: list[RealPositionSyncChange]


class RealTradeImportRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def list_active_connections(self) -> list[UserExchangeConnection]:
        with self._session_factory() as session:
            connections = session.scalars(
                _connection_select().where(UserExchangeConnection.status == "active")
            ).unique().all()
            for connection in connections:
                session.expunge(connection)
            return list(connections)

    def get_connection(self, connection_id: UUID | str) -> UserExchangeConnection:
        with self._session_factory() as session:
            connection = session.scalars(
                _connection_select().where(UserExchangeConnection.id == _parse_uuid(connection_id))
            ).one_or_none()
            if connection is None:
                raise LookupError(f"Exchange connection not found: {connection_id}")
            session.expunge(connection)
            return connection

    def list_reconciliation_order_refs(self, connection: UserExchangeConnection) -> list[LocalOrderRef]:
        with self._session_factory() as session:
            orders = session.scalars(
                select(Order)
                .join(Order.pair)
                .join(Order.exchange)
                .options(
                    joinedload(Order.pair).joinedload(MarketPair.exchange),
                )
                .where(
                    Order.user_id == connection.user_id,
                    Order.mode == "live",
                    Order.status.in_(("created", "submitted", "partially_filled")),
                    Order.exchange_id == connection.exchange_id,
                )
            ).unique().all()
            return [_local_order_ref(order) for order in orders]

    def list_reconciliation_position_refs(self, connection: UserExchangeConnection) -> list[LocalPositionRef]:
        with self._session_factory() as session:
            positions = session.scalars(
                select(Position)
                .join(Position.pair)
                .options(
                    joinedload(Position.pair).joinedload(MarketPair.exchange),
                )
                .where(
                    Position.user_id == connection.user_id,
                    Position.mode == "live",
                    Position.status == "open",
                    MarketPair.exchange_id == connection.exchange_id,
                )
            ).unique().all()
            return [_local_position_ref(position) for position in positions]

    def upsert_external_order(
        self,
        *,
        connection: UserExchangeConnection,
        order: ExchangeOrderSnapshot,
        imported_at: datetime,
    ) -> bool:
        exchange_order_id = order.exchange_order_id
        if not exchange_order_id:
            return False
        pair = self._get_pair(order.exchange, order.symbol)
        if pair is None:
            return False
        metadata = _external_order_metadata(order)
        with self._session_factory() as session:
            existing = session.scalars(
                select(ExternalExchangeOrder).where(
                    ExternalExchangeOrder.connection_id == connection.id,
                    ExternalExchangeOrder.exchange_order_id == exchange_order_id,
                )
            ).one_or_none()
            created = existing is None
            if existing is None:
                existing = ExternalExchangeOrder(
                    user_id=connection.user_id,
                    connection_id=connection.id,
                    exchange_order_id=exchange_order_id,
                    pair_id=pair.id,
                    side=order.side,
                    order_type=order.order_type,
                    status=order.status,
                    quantity=order.quantity,
                    price=order.price,
                    created_exchange_at=order.updated_at,
                    updated_exchange_at=order.updated_at,
                    imported_at=imported_at,
                    metadata_=metadata,
                )
                session.add(existing)
            else:
                existing.side = order.side
                existing.order_type = order.order_type
                existing.status = order.status
                existing.quantity = order.quantity
                existing.price = order.price
                existing.updated_exchange_at = order.updated_at or imported_at
                existing.imported_at = imported_at
                existing.metadata_ = {**(existing.metadata_ or {}), **metadata}
            session.commit()
            return created

    def update_local_order_from_exchange(
        self,
        *,
        order_ref: LocalOrderRef,
        exchange_order: ExchangeOrderSnapshot,
        imported_at: datetime,
    ) -> bool:
        local_status = _local_order_status(exchange_order)
        with self._session_factory() as session:
            order = session.get(Order, order_ref.id)
            if order is None:
                return False
            metadata = {
                **(order.metadata_ or {}),
                **_external_order_metadata(exchange_order),
                "last_exchange_sync_at": imported_at.isoformat(),
            }
            changed = order.status != local_status or order.metadata_ != metadata
            if exchange_order.price is not None and order.price != exchange_order.price:
                order.price = exchange_order.price
                changed = True
            if exchange_order.stop_price is not None and order.stop_price != exchange_order.stop_price:
                order.stop_price = exchange_order.stop_price
                changed = True
            if changed:
                order.status = local_status
                order.metadata_ = metadata
                order.updated_at = imported_at
                session.commit()
            return changed

    def update_local_position_from_exchange(
        self,
        *,
        position_ref: LocalPositionRef,
        exchange_position: ExchangePositionSnapshot | None,
        status: str,
        imported_at: datetime,
        exit_price: Decimal | None = None,
    ) -> bool:
        with self._session_factory() as session:
            position = session.get(Position, position_ref.id)
            if position is None:
                return False
            changed = False
            if status == "closed":
                if position.status != "closed":
                    position.status = "closed"
                    position.closed_at = imported_at
                    changed = True
                if exit_price is not None and position.exit_avg_price != exit_price:
                    position.exit_avg_price = exit_price
                    changed = True
            elif exchange_position is not None:
                quantity = abs(exchange_position.quantity)
                if quantity > 0 and position.quantity != quantity:
                    position.quantity = quantity
                    changed = True
                if exchange_position.entry_avg_price > 0 and position.entry_avg_price != exchange_position.entry_avg_price:
                    position.entry_avg_price = exchange_position.entry_avg_price
                    changed = True
                if position.status != "open":
                    position.status = "open"
                    changed = True
            if changed:
                position.updated_at = imported_at
                session.commit()
            return changed

    def record_reconciliation_audit(
        self,
        *,
        connection: UserExchangeConnection,
        action: str,
        payload: dict[str, Any],
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        created_at: datetime,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                AuditLog(
                    user_id=connection.user_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    payload=payload,
                    created_at=created_at,
                )
            )
            session.commit()

    def mark_connection_synced(self, connection: UserExchangeConnection, synced_at: datetime) -> None:
        with self._session_factory() as session:
            record = session.get(UserExchangeConnection, connection.id)
            if record is None:
                return
            record.last_sync_at = synced_at
            session.commit()

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

    def _get_pair(self, exchange_code: str, symbol: str) -> MarketPair | None:
        with self._session_factory() as session:
            pair = session.scalars(
                select(MarketPair)
                .join(MarketPair.exchange)
                .where(
                    MarketPair.symbol == symbol.strip().upper(),
                    MarketPair.exchange.has(code=exchange_code.strip().lower()),
                )
                .limit(1)
            ).one_or_none()
            if pair is not None:
                session.expunge(pair)
            return pair


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

    def list_active_connections(self) -> list[UserExchangeConnection]:
        return self._repository.list_active_connections()

    def list_reconciliation_order_refs(self, connection: UserExchangeConnection) -> list[LocalOrderRef]:
        return self._repository.list_reconciliation_order_refs(connection)

    def reconcile_connection(
        self,
        *,
        connection: UserExchangeConnection,
        exchange_orders: list[ExchangeOrderSnapshot | Mapping[str, Any]],
        exchange_positions: list[ExchangePositionSnapshot | Mapping[str, Any]],
        imported_at: datetime | None = None,
    ) -> RealPositionSyncResult:
        now = imported_at or datetime.now(timezone.utc)
        orders = [_normalize_order_snapshot(order) for order in exchange_orders]
        positions = [_normalize_position_snapshot(position) for position in exchange_positions]
        local_orders = self._repository.list_reconciliation_order_refs(connection)
        local_positions = self._repository.list_reconciliation_position_refs(connection)
        context = _ReconciliationContext(
            connection=connection,
            local_orders=local_orders,
            local_positions=local_positions,
        )
        changes: list[RealPositionSyncChange] = []
        unmatched_positions: list[dict[str, Any]] = []
        external_orders_written = 0
        local_orders_updated = 0
        local_positions_updated = 0
        audit_events = 0
        matched_position_ids: set[str] = set()
        terminal_order_position_ids: set[str] = set()

        def append_change(change: RealPositionSyncChange) -> None:
            nonlocal audit_events
            changes.append(change)
            self._repository.record_reconciliation_audit(
                connection=connection,
                action=f"real_position_sync.{change.action}",
                payload={
                    "reason": change.reason,
                    "connection_id": str(connection.id),
                    **change.metadata,
                },
                entity_type=change.entity_type,
                entity_id=_parse_uuid(change.entity_id) if change.entity_id else None,
                created_at=now,
            )
            audit_events += 1

        for order in orders:
            if self._repository.upsert_external_order(
                connection=connection,
                order=order,
                imported_at=now,
            ):
                external_orders_written += 1
            local_order = context.match_order(order)
            if local_order is None:
                continue
            if self._repository.update_local_order_from_exchange(
                order_ref=local_order,
                exchange_order=order,
                imported_at=now,
            ):
                local_orders_updated += 1
                append_change(
                    RealPositionSyncChange(
                        action="order_updated",
                        entity_type="order",
                        entity_id=str(local_order.id),
                        reason=order.status,
                        metadata=_change_metadata(order),
                    )
                )

            local_position = context.match_position_for_order(order, local_order)
            if local_position is None:
                continue
            if _is_entry_order(local_order, order) and _is_cancelled_or_rejected(order):
                if not _has_exchange_position(positions, local_position):
                    if self._repository.update_local_position_from_exchange(
                        position_ref=local_position,
                        exchange_position=None,
                        status="closed",
                        imported_at=now,
                    ):
                        local_positions_updated += 1
                        terminal_order_position_ids.add(str(local_position.id))
                        append_change(
                            RealPositionSyncChange(
                                action="position_closed",
                                entity_type="position",
                                entity_id=str(local_position.id),
                                reason="entry_order_cancelled_or_rejected",
                                metadata=_change_metadata(order),
                            )
                        )
            if _is_reduce_only_exit_order(local_order, order) and _is_filled(order):
                if not _has_exchange_position(positions, local_position):
                    exit_price = order.avg_price or order.price or order.stop_price
                    if self._repository.update_local_position_from_exchange(
                        position_ref=local_position,
                        exchange_position=None,
                        status="closed",
                        imported_at=now,
                        exit_price=exit_price,
                    ):
                        local_positions_updated += 1
                        terminal_order_position_ids.add(str(local_position.id))
                        append_change(
                            RealPositionSyncChange(
                                action="position_closed",
                                entity_type="position",
                                entity_id=str(local_position.id),
                                reason=_exit_close_reason(local_order, order),
                                metadata=_change_metadata(order),
                            )
                        )
            if _is_entry_order(local_order, order) and order.filled_quantity is not None and order.filled_quantity > 0:
                exchange_position = _position_from_entry_order(order)
                if self._repository.update_local_position_from_exchange(
                    position_ref=local_position,
                    exchange_position=exchange_position,
                    status="open",
                    imported_at=now,
                ):
                    local_positions_updated += 1
                    matched_position_ids.add(str(local_position.id))
                    append_change(
                        RealPositionSyncChange(
                            action="position_quantity_updated",
                            entity_type="position",
                            entity_id=str(local_position.id),
                            reason="partial_or_full_entry_fill",
                            metadata=_change_metadata(order),
                        )
                    )

        for position in positions:
            if position.quantity == 0:
                continue
            local_position = context.match_position(position)
            if local_position is None:
                payload = {
                    "reason": "unmatched_exchange_position",
                    "connection_id": str(connection.id),
                    "exchange_position": _position_payload(position),
                }
                unmatched_positions.append(payload["exchange_position"])
                append_change(
                    RealPositionSyncChange(
                        action="manual_exchange_position_flagged",
                        entity_type="position",
                        entity_id=None,
                        reason="unmatched_exchange_position",
                        metadata=payload,
                    )
                )
                continue
            matched_position_ids.add(str(local_position.id))
            if self._repository.update_local_position_from_exchange(
                position_ref=local_position,
                exchange_position=position,
                status="open",
                imported_at=now,
            ):
                local_positions_updated += 1
                append_change(
                    RealPositionSyncChange(
                        action="position_quantity_updated",
                        entity_type="position",
                        entity_id=str(local_position.id),
                        reason="exchange_position_actual",
                        metadata=_position_payload(position),
                    )
                )

        for local_position in local_positions:
            position_id = str(local_position.id)
            if position_id in matched_position_ids or position_id in terminal_order_position_ids:
                continue
            if _has_same_symbol_side_position(positions, local_position):
                continue
            if self._repository.update_local_position_from_exchange(
                position_ref=local_position,
                exchange_position=None,
                status="closed",
                imported_at=now,
            ):
                local_positions_updated += 1
                payload = {
                    "reason": "local_position_missing_on_exchange",
                    "position_id": position_id,
                    "exchange": local_position.exchange,
                    "symbol": local_position.symbol,
                    "side": local_position.side,
                }
                append_change(
                    RealPositionSyncChange(
                        action="position_closed",
                        entity_type="position",
                        entity_id=position_id,
                        reason="local_position_missing_on_exchange",
                        metadata=payload,
                    )
                )

        self._repository.mark_connection_synced(connection, now)
        return RealPositionSyncResult(
            connection_id=str(connection.id),
            orders_seen=len(orders),
            positions_seen=len(positions),
            external_orders_written=external_orders_written,
            local_orders_updated=local_orders_updated,
            local_positions_updated=local_positions_updated,
            audit_events=audit_events,
            unmatched_positions=unmatched_positions,
            changes=changes,
        )

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


class _ReconciliationContext:
    def __init__(
        self,
        *,
        connection: UserExchangeConnection,
        local_orders: list[LocalOrderRef],
        local_positions: list[LocalPositionRef],
    ) -> None:
        self.connection = connection
        self.local_orders = local_orders
        self.local_positions = local_positions
        self._orders_by_exchange_id = {
            order.exchange_order_id: order
            for order in local_orders
            if order.exchange_order_id
        }
        self._orders_by_client_id = {
            order.client_order_id: order
            for order in local_orders
            if order.client_order_id
        }
        self._positions_by_id = {str(position.id): position for position in local_positions}
        self._positions_by_signal = {
            position.signal_id: position
            for position in local_positions
            if position.signal_id
        }
        self._positions_by_symbol_side: dict[tuple[str, str, str], list[LocalPositionRef]] = {}
        for position in local_positions:
            key = _symbol_side_key(position.exchange, position.symbol, position.side)
            self._positions_by_symbol_side.setdefault(key, []).append(position)

    def match_order(self, exchange_order: ExchangeOrderSnapshot) -> LocalOrderRef | None:
        if exchange_order.exchange_order_id and exchange_order.exchange_order_id in self._orders_by_exchange_id:
            return self._orders_by_exchange_id[exchange_order.exchange_order_id]
        if exchange_order.client_order_id and exchange_order.client_order_id in self._orders_by_client_id:
            return self._orders_by_client_id[exchange_order.client_order_id]
        return None

    def match_position_for_order(
        self,
        exchange_order: ExchangeOrderSnapshot,
        local_order: LocalOrderRef,
    ) -> LocalPositionRef | None:
        for value in (exchange_order.position_id, local_order.position_id):
            if value and str(value) in self._positions_by_id:
                return self._positions_by_id[str(value)]
        for value in (exchange_order.signal_id, local_order.signal_id):
            if value and str(value) in self._positions_by_signal:
                return self._positions_by_signal[str(value)]
        side = _position_side_from_order(exchange_order, local_order)
        candidates = self._positions_by_symbol_side.get(
            _symbol_side_key(local_order.exchange, local_order.symbol, side),
            [],
        )
        return candidates[0] if len(candidates) == 1 else None

    def match_position(self, exchange_position: ExchangePositionSnapshot) -> LocalPositionRef | None:
        if exchange_position.position_id and exchange_position.position_id in self._positions_by_id:
            return self._positions_by_id[exchange_position.position_id]
        if exchange_position.signal_id and exchange_position.signal_id in self._positions_by_signal:
            return self._positions_by_signal[exchange_position.signal_id]
        candidates = self._positions_by_symbol_side.get(
            _symbol_side_key(exchange_position.exchange, exchange_position.symbol, exchange_position.side),
            [],
        )
        return candidates[0] if len(candidates) == 1 else None


def _normalize_order_snapshot(order: ExchangeOrderSnapshot | Mapping[str, Any]) -> ExchangeOrderSnapshot:
    if isinstance(order, ExchangeOrderSnapshot):
        return order
    raw = dict(order)
    return ExchangeOrderSnapshot(
        exchange=str(raw.get("exchange") or "").strip().lower(),
        symbol=str(raw.get("symbol") or "").strip().upper(),
        side=_normalize_order_side(raw.get("side")),
        status=_normalize_exchange_order_status(raw.get("status")),
        exchange_order_id=_optional_string(raw.get("exchange_order_id") or raw.get("order_id") or raw.get("orderId")),
        client_order_id=_optional_string(raw.get("client_order_id") or raw.get("order_link_id") or raw.get("orderLinkId")),
        order_type=_optional_string(raw.get("order_type") or raw.get("orderType")),
        quantity=_decimal(raw.get("quantity") or raw.get("qty")),
        filled_quantity=_decimal(
            raw.get("filled_quantity")
            or raw.get("filled_qty")
            or raw.get("cum_exec_qty")
            or raw.get("cumExecQty")
        ),
        price=_decimal(raw.get("price")),
        stop_price=_decimal(raw.get("stop_price") or raw.get("trigger_price") or raw.get("triggerPrice")),
        avg_price=_decimal(raw.get("avg_price") or raw.get("average_price") or raw.get("avgPrice")),
        reduce_only=_boolish(raw.get("reduce_only") if "reduce_only" in raw else raw.get("reduceOnly")),
        role=_optional_string(raw.get("role")),
        signal_id=_optional_string(raw.get("signal_id")),
        position_id=_optional_string(raw.get("position_id")),
        updated_at=_datetime_or_none(raw.get("updated_at") or raw.get("updated_exchange_at")),
        raw=raw.get("raw") if isinstance(raw.get("raw"), dict) else raw,
    )


def _normalize_position_snapshot(position: ExchangePositionSnapshot | Mapping[str, Any]) -> ExchangePositionSnapshot:
    if isinstance(position, ExchangePositionSnapshot):
        return position
    raw = dict(position)
    quantity = _decimal(raw.get("quantity") or raw.get("size") or raw.get("qty")) or Decimal("0")
    side = _normalize_position_side(raw.get("side"), quantity)
    return ExchangePositionSnapshot(
        exchange=str(raw.get("exchange") or "").strip().lower(),
        symbol=str(raw.get("symbol") or "").strip().upper(),
        side=side,
        quantity=abs(quantity),
        entry_avg_price=_decimal(
            raw.get("entry_avg_price")
            or raw.get("entry_price")
            or raw.get("avg_price")
            or raw.get("avgPrice")
            or raw.get("entryPrice")
        ) or Decimal("0"),
        signal_id=_optional_string(raw.get("signal_id")),
        position_id=_optional_string(raw.get("position_id")),
        exchange_position_id=_optional_string(raw.get("exchange_position_id")),
        mark_price=_decimal(raw.get("mark_price")),
        unrealized_pnl=_decimal(raw.get("unrealized_pnl")),
        updated_at=_datetime_or_none(raw.get("updated_at")),
        raw=raw.get("raw") if isinstance(raw.get("raw"), dict) else raw,
    )


def _local_order_ref(order: Order) -> LocalOrderRef:
    metadata = order.metadata_ or {}
    return LocalOrderRef(
        id=order.id,
        user_id=order.user_id,
        exchange=order.exchange.code,
        symbol=order.pair.symbol,
        side=order.side,
        order_type=order.order_type,
        status=order.status,
        quantity=order.quantity,
        signal_id=str(order.signal_id) if order.signal_id is not None else _optional_string(metadata.get("signal_id")),
        position_id=_optional_string(metadata.get("position_id")),
        exchange_order_id=_optional_string(metadata.get("exchange_order_id")),
        client_order_id=_optional_string(metadata.get("client_order_id")),
        role=_optional_string(metadata.get("role")),
        reduce_only=_boolish(metadata.get("reduce_only")),
        metadata=dict(metadata),
    )


def _local_position_ref(position: Position) -> LocalPositionRef:
    return LocalPositionRef(
        id=position.id,
        user_id=position.user_id,
        exchange=position.pair.exchange.code,
        symbol=position.pair.symbol,
        side=position.side,
        status=position.status,
        quantity=position.quantity,
        entry_avg_price=position.entry_avg_price,
        signal_id=str(position.signal_id) if position.signal_id is not None else None,
        stop_loss=position.stop_loss,
    )


def _external_order_metadata(order: ExchangeOrderSnapshot) -> dict[str, Any]:
    return {
        "client_order_id": order.client_order_id,
        "exchange_order_id": order.exchange_order_id,
        "filled_quantity": str(order.filled_quantity) if order.filled_quantity is not None else None,
        "avg_price": str(order.avg_price) if order.avg_price is not None else None,
        "stop_price": str(order.stop_price) if order.stop_price is not None else None,
        "reduce_only": order.reduce_only,
        "role": order.role,
        "signal_id": order.signal_id,
        "position_id": order.position_id,
        "raw": _jsonable(order.raw),
    }


def _local_order_status(order: ExchangeOrderSnapshot) -> str:
    if _is_cancelled(order):
        return "cancelled"
    if _is_rejected(order):
        return "rejected"
    if _is_filled(order):
        return "filled"
    if order.filled_quantity is not None and order.filled_quantity > 0:
        return "partially_filled"
    return "submitted"


def _normalize_exchange_order_status(value: Any) -> str:
    status = str(value or "submitted").strip().lower().replace("-", "_").replace(" ", "_")
    if status in {"new", "open", "created", "untriggered", "triggered"}:
        return "submitted"
    if status in {"partiallyfilled", "partial_filled", "partial_fill"}:
        return "partially_filled"
    if status in {"canceled", "cancelled"}:
        return "cancelled"
    if status in {"reject"}:
        return "rejected"
    if status in {"filled", "partially_filled", "submitted", "cancelled", "rejected"}:
        return status
    return status or "submitted"


def _normalize_order_side(value: Any) -> str:
    side = str(value or "").strip().lower()
    if side in {"sell", "short"}:
        return "sell"
    return "buy"


def _normalize_position_side(value: Any, quantity: Decimal) -> str:
    side = str(value or "").strip().lower()
    if side in {"sell", "short"} or quantity < 0:
        return "short"
    return "long"


def _position_side_from_order(order: ExchangeOrderSnapshot, local_order: LocalOrderRef) -> str:
    side = order.side or local_order.side
    reduce_only = _is_reduce_only_exit_order(local_order, order)
    if reduce_only:
        return "long" if side == "sell" else "short"
    return "long" if side == "buy" else "short"


def _is_entry_order(local_order: LocalOrderRef, exchange_order: ExchangeOrderSnapshot) -> bool:
    role = (exchange_order.role or local_order.role or "").strip().lower()
    return role in {"", "entry"}


def _is_reduce_only_exit_order(local_order: LocalOrderRef, exchange_order: ExchangeOrderSnapshot) -> bool:
    role = (exchange_order.role or local_order.role or "").strip().lower()
    return bool(exchange_order.reduce_only or local_order.reduce_only or role in {"protective_stop", "stop", "take_profit", "tp", "sl"})


def _is_cancelled_or_rejected(order: ExchangeOrderSnapshot) -> bool:
    return _is_cancelled(order) or _is_rejected(order)


def _is_cancelled(order: ExchangeOrderSnapshot) -> bool:
    return order.status in {"cancelled", "canceled", "expired"}


def _is_rejected(order: ExchangeOrderSnapshot) -> bool:
    return order.status == "rejected"


def _is_filled(order: ExchangeOrderSnapshot) -> bool:
    return order.status == "filled"


def _exit_close_reason(local_order: LocalOrderRef, order: ExchangeOrderSnapshot) -> str:
    role = (order.role or local_order.role or "").strip().lower()
    if role in {"take_profit", "tp"}:
        return "take_profit_fill"
    return "protective_stop_fill"


def _position_from_entry_order(order: ExchangeOrderSnapshot) -> ExchangePositionSnapshot:
    quantity = order.filled_quantity or order.quantity or Decimal("0")
    return ExchangePositionSnapshot(
        exchange=order.exchange,
        symbol=order.symbol,
        side="long" if order.side == "buy" else "short",
        quantity=abs(quantity),
        entry_avg_price=order.avg_price or order.price or Decimal("0"),
        signal_id=order.signal_id,
        position_id=order.position_id,
        updated_at=order.updated_at,
        raw=order.raw,
    )


def _has_exchange_position(positions: list[ExchangePositionSnapshot], local_position: LocalPositionRef) -> bool:
    return any(_matches_local_position(position, local_position) and position.quantity > 0 for position in positions)


def _has_same_symbol_side_position(positions: list[ExchangePositionSnapshot], local_position: LocalPositionRef) -> bool:
    return any(
        _symbol_side_key(position.exchange, position.symbol, position.side)
        == _symbol_side_key(local_position.exchange, local_position.symbol, local_position.side)
        and position.quantity > 0
        for position in positions
    )


def _matches_local_position(position: ExchangePositionSnapshot, local_position: LocalPositionRef) -> bool:
    if position.position_id and position.position_id == str(local_position.id):
        return True
    if position.signal_id and local_position.signal_id and position.signal_id == local_position.signal_id:
        return True
    return (
        _symbol_side_key(position.exchange, position.symbol, position.side)
        == _symbol_side_key(local_position.exchange, local_position.symbol, local_position.side)
    )


def _symbol_side_key(exchange: str, symbol: str, side: str) -> tuple[str, str, str]:
    return (exchange.strip().lower(), symbol.strip().upper(), side.strip().lower())


def _change_metadata(order: ExchangeOrderSnapshot) -> dict[str, Any]:
    return {
        "exchange": order.exchange,
        "symbol": order.symbol,
        "client_order_id": order.client_order_id,
        "exchange_order_id": order.exchange_order_id,
        "filled_quantity": str(order.filled_quantity) if order.filled_quantity is not None else None,
        "status": order.status,
        "role": order.role,
        "reduce_only": order.reduce_only,
    }


def _position_payload(position: ExchangePositionSnapshot) -> dict[str, Any]:
    return {
        "exchange": position.exchange,
        "symbol": position.symbol,
        "side": position.side,
        "quantity": str(position.quantity),
        "entry_avg_price": str(position.entry_avg_price),
        "signal_id": position.signal_id,
        "position_id": position.position_id,
        "exchange_position_id": position.exchange_position_id,
    }


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, Decimal, UUID)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None or isinstance(value, Decimal):
        return value
    return Decimal(str(value))


real_trade_import_service = RealTradeImportService()
