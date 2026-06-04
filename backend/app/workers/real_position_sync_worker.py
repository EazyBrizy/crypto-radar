from __future__ import annotations

import asyncio
import contextlib
import logging
import urllib.request
from decimal import Decimal
from typing import Any, Protocol

from app.exchanges.bybit import (
    BYBIT_API_URL,
    BYBIT_TESTNET_API_URL,
    BybitExecutionInfo,
    BybitOrderInfo,
    BybitPositionInfo,
    fetch_bybit_closed_orders,
    fetch_bybit_executions,
    fetch_bybit_open_orders,
    fetch_bybit_orders,
    fetch_bybit_positions,
)
from app.services.exchange_connection_service import exchange_connection_service
from app.services.real_trade_import_service import (
    ExchangeExecutionSnapshot,
    ExchangeOrderSnapshot,
    ExchangePositionSnapshot,
    LocalOrderRef,
    RealPositionSyncResult,
    RealTradeImportService,
    real_trade_import_service,
)

logger = logging.getLogger(__name__)
STOP_TIMEOUT_SEC = 3.0


class RealPositionSyncClient(Protocol):
    def supports_connection(self, connection: Any) -> bool:
        ...

    async def fetch_open_orders(self, connection: Any) -> list[ExchangeOrderSnapshot | dict[str, Any]]:
        ...

    async def fetch_closed_orders(self, connection: Any) -> list[ExchangeOrderSnapshot | dict[str, Any]]:
        ...

    async def fetch_executions(
        self,
        connection: Any,
        local_order: LocalOrderRef,
    ) -> list[ExchangeExecutionSnapshot | dict[str, Any]]:
        ...

    async def fetch_positions(self, connection: Any) -> list[ExchangePositionSnapshot | dict[str, Any]]:
        ...

    async def get_order(
        self,
        *,
        connection: Any,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExchangeOrderSnapshot | dict[str, Any] | None:
        ...


class RealPositionSyncWorker:
    """Reconciles local live orders/positions from exchange-reported state."""

    def __init__(
        self,
        *,
        service: RealTradeImportService | None = None,
        client: RealPositionSyncClient | None = None,
        interval_seconds: int = 30,
    ) -> None:
        self._service = service or real_trade_import_service
        self._client = client
        self._interval_seconds = max(1, int(interval_seconds))
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._last_result: dict[str, Any] = {}

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_result(self) -> dict[str, Any]:
        return dict(self._last_result)

    def start(self) -> None:
        if self.is_running:
            return
        if self._client is None:
            logger.info("Real position sync worker is disabled: no exchange sync client configured")
            self._last_result = {"enabled": False, "reason": "client_not_configured"}
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        logger.info("Real position sync worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._task.done():
            self._task = None
            self._stopping = False
            return
        self._stopping = True
        self._task.cancel()
        try:
            done, pending = await asyncio.wait({self._task}, timeout=STOP_TIMEOUT_SEC)
        except asyncio.CancelledError:
            self._task.cancel()
            raise
        if pending:
            logger.warning("Real position sync worker stop timed out after %.1f seconds", STOP_TIMEOUT_SEC)
            return
        task = done.pop()
        with contextlib.suppress(asyncio.CancelledError):
            task.result()
        logger.info("Real position sync worker stopped")
        if self._task is task:
            self._task = None
            self._stopping = False

    async def sync_once(self) -> dict[str, Any]:
        if self._client is None:
            self._last_result = {"enabled": False, "reason": "client_not_configured"}
            return self.last_result

        connections = self._service.list_active_connections()
        results: list[RealPositionSyncResult] = []
        errors: list[str] = []
        for connection in connections:
            supports_connection = getattr(self._client, "supports_connection", None)
            if supports_connection is not None and not supports_connection(connection):
                continue
            try:
                results.append(await self._sync_connection(connection))
            except Exception as exc:
                message = f"{getattr(connection, 'id', 'unknown')}: {exc}"
                errors.append(message)
                self._service.mark_connection_stale(connection, error=str(exc))
                logger.warning("Real position sync failed for connection %s: %s", getattr(connection, "id", None), exc)
        self._last_result = {
            "enabled": True,
            "connections": len(connections),
            "synced": len(results),
            "orders_seen": sum(result.orders_seen for result in results),
            "positions_seen": sum(result.positions_seen for result in results),
            "executions_seen": sum(result.executions_seen for result in results),
            "external_orders_written": sum(result.external_orders_written for result in results),
            "external_trades_written": sum(result.external_trades_written for result in results),
            "local_fills_written": sum(result.local_fills_written for result in results),
            "local_orders_updated": sum(result.local_orders_updated for result in results),
            "local_positions_updated": sum(result.local_positions_updated for result in results),
            "audit_events": sum(result.audit_events for result in results),
            "unmatched_positions": [
                position
                for result in results
                for position in result.unmatched_positions
            ],
            "errors": errors,
        }
        return self.last_result

    async def _sync_connection(self, connection: Any) -> RealPositionSyncResult:
        assert self._client is not None
        open_orders = await self._client.fetch_open_orders(connection)
        closed_orders = await self._fetch_closed_orders(connection)
        positions = await self._client.fetch_positions(connection)
        order_snapshots = await self._with_terminal_order_states(connection, [*open_orders, *closed_orders])
        executions = await self._fetch_executions(connection)
        return self._service.reconcile_connection(
            connection=connection,
            exchange_orders=order_snapshots,
            exchange_positions=positions,
            exchange_executions=executions,
        )

    async def _fetch_closed_orders(self, connection: Any) -> list[ExchangeOrderSnapshot | dict[str, Any]]:
        assert self._client is not None
        fetch_closed_orders = getattr(self._client, "fetch_closed_orders", None)
        if fetch_closed_orders is None:
            return []
        return await fetch_closed_orders(connection)

    async def _fetch_executions(self, connection: Any) -> list[ExchangeExecutionSnapshot | dict[str, Any]]:
        assert self._client is not None
        fetch_executions = getattr(self._client, "fetch_executions", None)
        if fetch_executions is None:
            return []
        executions: list[ExchangeExecutionSnapshot | dict[str, Any]] = []
        seen_order_keys: set[tuple[str | None, str | None]] = set()
        for local_order in self._service.list_reconciliation_order_refs(connection):
            key = (local_order.exchange_order_id, local_order.client_order_id)
            if key in seen_order_keys:
                continue
            seen_order_keys.add(key)
            executions.extend(await fetch_executions(connection, local_order))
        return executions

    async def _with_terminal_order_states(
        self,
        connection: Any,
        open_orders: list[ExchangeOrderSnapshot | dict[str, Any]],
    ) -> list[ExchangeOrderSnapshot | dict[str, Any]]:
        assert self._client is not None
        order_snapshots: list[ExchangeOrderSnapshot | dict[str, Any]] = list(open_orders)
        open_keys = {_order_key(order) for order in open_orders}
        lookup = getattr(self._client, "get_order", None)
        if lookup is None:
            return order_snapshots

        for local_order in self._service.list_reconciliation_order_refs(connection):
            if not local_order.client_order_id:
                continue
            if (local_order.exchange.lower(), local_order.symbol.upper(), local_order.client_order_id) in open_keys:
                continue
            terminal = await lookup(
                connection=connection,
                exchange=local_order.exchange,
                symbol=local_order.symbol,
                client_order_id=local_order.client_order_id,
            )
            if terminal is not None:
                order_snapshots.append(terminal)
        return order_snapshots

    async def _run(self) -> None:
        while True:
            await self.sync_once()
            await asyncio.sleep(self._interval_seconds)


def _order_key(order: ExchangeOrderSnapshot | dict[str, Any]) -> tuple[str, str, str | None]:
    if isinstance(order, ExchangeOrderSnapshot):
        return (
            order.exchange.strip().lower(),
            order.symbol.strip().upper(),
            order.client_order_id,
        )
    return (
        str(order.get("exchange") or "").strip().lower(),
        str(order.get("symbol") or "").strip().upper(),
        str(order.get("client_order_id") or "").strip() or None,
    )


class BybitRealPositionSyncClient:
    def __init__(
        self,
        *,
        connection_service: Any = exchange_connection_service,
        recv_window: int = 5_000,
        urlopen: Any = urllib.request.urlopen,
    ) -> None:
        self._connection_service = connection_service
        self._recv_window = recv_window
        self._urlopen = urlopen

    def supports_connection(self, connection: Any) -> bool:
        exchange = getattr(connection, "exchange", None)
        return str(getattr(exchange, "code", "")).strip().lower() == "bybit"

    async def fetch_open_orders(self, connection: Any) -> list[ExchangeOrderSnapshot]:
        orders = await asyncio.to_thread(
            self._fetch_open_orders_sync,
            connection,
        )
        return [_order_snapshot(order) for order in orders]

    async def fetch_closed_orders(self, connection: Any) -> list[ExchangeOrderSnapshot]:
        orders = await asyncio.to_thread(
            self._fetch_closed_orders_sync,
            connection,
        )
        return [_order_snapshot(order) for order in orders]

    async def fetch_executions(
        self,
        connection: Any,
        local_order: LocalOrderRef,
    ) -> list[ExchangeExecutionSnapshot]:
        executions = await asyncio.to_thread(
            self._fetch_executions_sync,
            connection,
            local_order,
        )
        return [_execution_snapshot(execution) for execution in executions]

    async def fetch_positions(self, connection: Any) -> list[ExchangePositionSnapshot]:
        positions = await asyncio.to_thread(
            self._fetch_positions_sync,
            connection,
        )
        return [_position_snapshot(position) for position in positions]

    async def get_order(
        self,
        *,
        connection: Any,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExchangeOrderSnapshot | None:
        _ = exchange
        orders = await asyncio.to_thread(
            self._fetch_order_sync,
            connection,
            symbol,
            client_order_id,
        )
        return _order_snapshot(orders[0]) if orders else None

    def _fetch_open_orders_sync(self, connection: Any) -> list[BybitOrderInfo]:
        api_key, api_secret = self._credentials(connection)
        return fetch_bybit_open_orders(
            api_key=api_key,
            api_secret=api_secret,
            category=_category(connection),
            base_url=_base_url(connection),
            recv_window=self._recv_window,
            urlopen=self._urlopen,
        )

    def _fetch_closed_orders_sync(self, connection: Any) -> list[BybitOrderInfo]:
        api_key, api_secret = self._credentials(connection)
        return fetch_bybit_closed_orders(
            api_key=api_key,
            api_secret=api_secret,
            category=_category(connection),
            base_url=_base_url(connection),
            recv_window=self._recv_window,
            urlopen=self._urlopen,
        )

    def _fetch_executions_sync(
        self,
        connection: Any,
        local_order: LocalOrderRef,
    ) -> list[BybitExecutionInfo]:
        api_key, api_secret = self._credentials(connection)
        return fetch_bybit_executions(
            api_key=api_key,
            api_secret=api_secret,
            category=_category(connection),
            symbol=local_order.symbol,
            order_id=local_order.exchange_order_id,
            order_link_id=local_order.client_order_id,
            base_url=_base_url(connection),
            recv_window=self._recv_window,
            urlopen=self._urlopen,
        )

    def _fetch_positions_sync(self, connection: Any) -> list[BybitPositionInfo]:
        api_key, api_secret = self._credentials(connection)
        return fetch_bybit_positions(
            api_key=api_key,
            api_secret=api_secret,
            category=_category(connection),
            base_url=_base_url(connection),
            recv_window=self._recv_window,
            urlopen=self._urlopen,
        )

    def _fetch_order_sync(self, connection: Any, symbol: str, client_order_id: str) -> list[BybitOrderInfo]:
        api_key, api_secret = self._credentials(connection)
        return fetch_bybit_orders(
            api_key=api_key,
            api_secret=api_secret,
            category=_category(connection),
            symbol=symbol,
            order_link_id=client_order_id,
            base_url=_base_url(connection),
            recv_window=self._recv_window,
            urlopen=self._urlopen,
        )

    def _credentials(self, connection: Any) -> tuple[str, str]:
        credentials = self._connection_service.load_credentials(connection.key_ref)
        if credentials is None:
            raise ValueError("Exchange credentials are not available for reconciliation.")
        api_key = str(credentials.get("api_key") or "").strip()
        api_secret = str(credentials.get("api_secret") or "").strip()
        if not api_key or not api_secret:
            raise ValueError("Bybit reconciliation requires api_key and api_secret.")
        return api_key, api_secret


def _order_snapshot(order: BybitOrderInfo) -> ExchangeOrderSnapshot:
    return ExchangeOrderSnapshot(
        exchange="bybit",
        symbol=order.symbol,
        side=_order_side(order.side),
        status=order.order_status,
        exchange_order_id=order.order_id,
        client_order_id=order.order_link_id,
        order_type=(order.order_type or "").lower() or None,
        quantity=order.qty,
        filled_quantity=order.cum_exec_qty,
        price=order.price,
        stop_price=order.trigger_price,
        avg_price=order.avg_price,
        reduce_only=order.reduce_only,
        updated_at=_datetime_from_ms(order.updated_time),
        raw=order.raw_payload,
    )


def _execution_snapshot(execution: BybitExecutionInfo) -> ExchangeExecutionSnapshot:
    return ExchangeExecutionSnapshot(
        exchange="bybit",
        symbol=execution.symbol,
        side=_order_side(execution.side),
        exchange_execution_id=execution.exec_id,
        exchange_order_id=execution.order_id,
        client_order_id=execution.order_link_id,
        price=execution.exec_price,
        quantity=execution.exec_qty,
        fee_amount=execution.exec_fee,
        fee_asset_symbol=execution.fee_currency,
        liquidity="maker" if execution.is_maker is True else "taker" if execution.is_maker is False else None,
        order_type=(execution.order_type or "").lower() or None,
        executed_at=_datetime_from_ms(execution.exec_time),
        raw=execution.raw_payload,
    )


def _position_snapshot(position: BybitPositionInfo) -> ExchangePositionSnapshot:
    return ExchangePositionSnapshot(
        exchange="bybit",
        symbol=position.symbol,
        side=_position_side(position.side, position.size),
        quantity=abs(position.size or Decimal("0")),
        entry_avg_price=position.entry_price or Decimal("0"),
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        mark_price=position.mark_price,
        unrealized_pnl=position.unrealized_pnl,
        updated_at=_datetime_from_ms(position.updated_time),
        raw=position.raw_payload,
    )


def _category(connection: Any) -> str:
    metadata = getattr(connection, "metadata_", None) or {}
    category = metadata.get("category") or metadata.get("position_category")
    if isinstance(category, str) and category.strip():
        return category.strip().lower()
    account_type = str(getattr(connection, "account_type", "") or "").strip().lower()
    if account_type in {"inverse", "option", "linear"}:
        return account_type
    return "linear"


def _base_url(connection: Any) -> str:
    metadata = getattr(connection, "metadata_", None) or {}
    api_base_url = metadata.get("api_base_url")
    if isinstance(api_base_url, str) and api_base_url.strip():
        return api_base_url.strip().rstrip("/")
    if metadata.get("testnet") is True or str(metadata.get("environment") or "").strip().lower() == "testnet":
        return BYBIT_TESTNET_API_URL
    exchange = getattr(connection, "exchange", None)
    exchange_base_url = getattr(exchange, "api_base_url", None)
    if isinstance(exchange_base_url, str) and exchange_base_url.strip():
        return exchange_base_url.strip().rstrip("/")
    return BYBIT_API_URL


def _order_side(side: str | None) -> str:
    return "sell" if str(side or "").strip().lower() == "sell" else "buy"


def _position_side(side: str | None, size: Any) -> str:
    normalized = str(side or "").strip().lower()
    if normalized in {"sell", "short"}:
        return "short"
    if normalized in {"buy", "long"}:
        return "long"
    return "short" if size is not None and size < 0 else "long"


def _datetime_from_ms(value: int | None) -> Any:
    if value is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


real_position_sync_worker = RealPositionSyncWorker()
