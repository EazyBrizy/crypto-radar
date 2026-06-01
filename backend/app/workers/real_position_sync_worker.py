from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Protocol

from app.services.real_trade_import_service import (
    ExchangeOrderSnapshot,
    ExchangePositionSnapshot,
    RealPositionSyncResult,
    RealTradeImportService,
    real_trade_import_service,
)

logger = logging.getLogger(__name__)
STOP_TIMEOUT_SEC = 3.0


class RealPositionSyncClient(Protocol):
    async def fetch_open_orders(self, connection: Any) -> list[ExchangeOrderSnapshot | dict[str, Any]]:
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
            try:
                results.append(await self._sync_connection(connection))
            except Exception as exc:
                message = f"{getattr(connection, 'id', 'unknown')}: {exc}"
                errors.append(message)
                logger.warning("Real position sync failed for connection %s: %s", getattr(connection, "id", None), exc)
        self._last_result = {
            "enabled": True,
            "connections": len(connections),
            "synced": len(results),
            "orders_seen": sum(result.orders_seen for result in results),
            "positions_seen": sum(result.positions_seen for result in results),
            "external_orders_written": sum(result.external_orders_written for result in results),
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
        positions = await self._client.fetch_positions(connection)
        order_snapshots = await self._with_terminal_order_states(connection, open_orders)
        return self._service.reconcile_connection(
            connection=connection,
            exchange_orders=order_snapshots,
            exchange_positions=positions,
        )

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


real_position_sync_worker = RealPositionSyncWorker()
