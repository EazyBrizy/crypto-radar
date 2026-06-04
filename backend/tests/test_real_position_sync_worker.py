from __future__ import annotations

import unittest
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from app.services.real_trade_import_service import LocalOrderRef, LocalPositionRef, RealTradeImportService
from app.workers.real_position_sync_worker import RealPositionSyncWorker


CONNECTION_ID = UUID("20000000-0000-0000-0000-000000000001")
USER_ID = UUID("20000000-0000-0000-0000-000000000002")
ORDER_ID = UUID("20000000-0000-0000-0000-000000000003")
POSITION_ID = UUID("20000000-0000-0000-0000-000000000004")
SIGNAL_ID = "20000000-0000-0000-0000-000000000005"


class RealPositionSyncWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_partial_fill_updates_local_position(self) -> None:
        repository = FakeWorkerRepository()
        client = FakeSyncClient(
            open_orders=[
                {
                    "exchange": "bybit",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "status": "partially_filled",
                    "exchange_order_id": "ex-entry-1",
                    "client_order_id": "client-entry-1",
                    "role": "entry",
                    "quantity": "1",
                    "filled_quantity": "0.25",
                    "avg_price": "102",
                    "signal_id": SIGNAL_ID,
                    "position_id": str(POSITION_ID),
                }
            ],
            positions=[
                {
                    "exchange": "bybit",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "quantity": "0.25",
                    "entry_avg_price": "102",
                    "signal_id": SIGNAL_ID,
                    "position_id": str(POSITION_ID),
                }
            ],
        )
        worker = RealPositionSyncWorker(
            service=RealTradeImportService(repository=repository),
            client=client,
        )

        result = await worker.sync_once()

        self.assertEqual(repository.positions[POSITION_ID]["quantity"], Decimal("0.25"))
        self.assertEqual(repository.orders[ORDER_ID]["status"], "partially_filled")
        self.assertEqual(result["positions_seen"], 1)

    async def test_cancelled_order_is_not_open_risk(self) -> None:
        repository = FakeWorkerRepository()
        client = FakeSyncClient(
            open_orders=[],
            positions=[],
            terminal_orders={
                "client-entry-1": {
                    "exchange": "bybit",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "status": "cancelled",
                    "exchange_order_id": "ex-entry-1",
                    "client_order_id": "client-entry-1",
                    "role": "entry",
                    "quantity": "1",
                    "filled_quantity": "0",
                    "signal_id": SIGNAL_ID,
                    "position_id": str(POSITION_ID),
                }
            },
        )
        worker = RealPositionSyncWorker(
            service=RealTradeImportService(repository=repository),
            client=client,
        )

        await worker.sync_once()

        self.assertEqual(repository.orders[ORDER_ID]["status"], "cancelled")
        self.assertEqual(repository.positions[POSITION_ID]["status"], "closed")
        self.assertEqual(repository.open_risk_quantity(), Decimal("0"))
        self.assertEqual(client.get_order_calls, ["client-entry-1"])

    async def test_unmatched_exchange_position_is_flagged(self) -> None:
        repository = FakeWorkerRepository(include_local_position=False)
        client = FakeSyncClient(
            open_orders=[],
            positions=[
                {
                    "exchange": "bybit",
                    "symbol": "ETHUSDT",
                    "side": "long",
                    "quantity": "2",
                    "entry_avg_price": "2500",
                }
            ],
        )
        worker = RealPositionSyncWorker(
            service=RealTradeImportService(repository=repository),
            client=client,
        )

        result = await worker.sync_once()

        self.assertEqual(len(result["unmatched_positions"]), 1)
        self.assertTrue(
            any(event["action"] == "real_position_sync.manual_exchange_position_flagged" for event in repository.audit_events)
        )

    async def test_exchange_error_marks_snapshot_stale_without_corrupting_positions(self) -> None:
        repository = FakeWorkerRepository()
        client = FailingSyncClient()
        worker = RealPositionSyncWorker(
            service=RealTradeImportService(repository=repository),
            client=client,
        )

        result = await worker.sync_once()

        self.assertEqual(repository.positions[POSITION_ID]["status"], "open")
        self.assertEqual(repository.positions[POSITION_ID]["quantity"], Decimal("1"))
        self.assertEqual(repository.stale_error, "exchange timeout")
        self.assertEqual(result["synced"], 0)
        self.assertEqual(len(result["errors"]), 1)


class FakeSyncClient:
    def __init__(
        self,
        *,
        open_orders: list[dict],
        positions: list[dict],
        terminal_orders: dict[str, dict] | None = None,
    ) -> None:
        self.open_orders = open_orders
        self.positions = positions
        self.terminal_orders = terminal_orders or {}
        self.get_order_calls: list[str] = []

    async def fetch_open_orders(self, _connection):
        return list(self.open_orders)

    async def fetch_positions(self, _connection):
        return list(self.positions)

    async def get_order(self, *, connection, exchange, symbol, client_order_id):
        self.get_order_calls.append(client_order_id)
        return self.terminal_orders.get(client_order_id)


class FailingSyncClient:
    async def fetch_open_orders(self, _connection):
        raise RuntimeError("exchange timeout")

    async def fetch_positions(self, _connection):
        raise AssertionError("positions should not be fetched after order failure")

    async def get_order(self, *, connection, exchange, symbol, client_order_id):
        raise AssertionError("terminal lookup should not run after order failure")


class FakeWorkerRepository:
    def __init__(self, *, include_local_position: bool = True) -> None:
        self.connection = SimpleNamespace(
            id=CONNECTION_ID,
            user_id=USER_ID,
            exchange_id=UUID("20000000-0000-0000-0000-000000000006"),
            exchange=SimpleNamespace(code="bybit"),
        )
        self.orders = {
            ORDER_ID: {
                "id": ORDER_ID,
                "user_id": USER_ID,
                "exchange": "bybit",
                "symbol": "BTCUSDT",
                "side": "buy",
                "order_type": "market",
                "status": "submitted",
                "quantity": Decimal("1"),
                "signal_id": SIGNAL_ID,
                "position_id": str(POSITION_ID),
                "exchange_order_id": "ex-entry-1",
                "client_order_id": "client-entry-1",
                "role": "entry",
                "reduce_only": False,
                "metadata": {},
            }
        }
        self.positions = {}
        if include_local_position:
            self.positions[POSITION_ID] = {
                "id": POSITION_ID,
                "user_id": USER_ID,
                "exchange": "bybit",
                "symbol": "BTCUSDT",
                "side": "long",
                "status": "open",
                "quantity": Decimal("1"),
                "entry_avg_price": Decimal("100"),
                "signal_id": SIGNAL_ID,
                "stop_loss": Decimal("95"),
            }
        self.external_orders: dict[tuple[UUID, str], dict] = {}
        self.external_trades: dict[tuple[UUID, str], dict] = {}
        self.order_fills: dict[tuple[UUID, str], dict] = {}
        self.audit_events: list[dict] = []
        self.stale_error: str | None = None
        self.live_entry_blocked = False

    def list_active_connections(self):
        return [self.connection]

    def list_reconciliation_order_refs(self, _connection):
        return [
            LocalOrderRef(**deepcopy(order))
            for order in self.orders.values()
            if order["status"] in {"created", "submitted", "partially_filled"}
        ]

    def list_reconciliation_position_refs(self, _connection):
        return [
            LocalPositionRef(**deepcopy(position))
            for position in self.positions.values()
            if position["status"] == "open"
        ]

    def upsert_external_order(self, *, connection, order, imported_at):
        if not order.exchange_order_id:
            return False
        key = (connection.id, order.exchange_order_id)
        created = key not in self.external_orders
        self.external_orders[key] = {"order": order, "imported_at": imported_at}
        return created

    def upsert_external_trade(self, *, connection, execution, imported_at):
        key = (connection.id, execution.exchange_execution_id)
        created = key not in self.external_trades
        self.external_trades[key] = {"execution": execution, "imported_at": imported_at}
        return created

    def insert_order_fill_from_execution(self, *, order_ref, execution, imported_at):
        key = (order_ref.id, f"{execution.exchange}:{execution.exchange_execution_id}")
        if key in self.order_fills:
            return False
        self.order_fills[key] = {"execution": execution, "imported_at": imported_at}
        return True

    def update_local_order_from_exchange(self, *, order_ref, exchange_order, imported_at):
        order = self.orders[order_ref.id]
        if exchange_order.status == "filled":
            status = "filled"
        elif exchange_order.status == "cancelled":
            status = "cancelled"
        elif exchange_order.status == "rejected":
            status = "rejected"
        elif exchange_order.filled_quantity and exchange_order.filled_quantity > 0:
            status = "partially_filled"
        else:
            status = "submitted"
        changed = order["status"] != status
        order["status"] = status
        order["metadata"]["filled_quantity"] = exchange_order.filled_quantity
        return changed

    def mark_order_needs_manual_review(self, *, order_ref, imported_at, reason):
        order = self.orders[order_ref.id]
        changed = order["status"] != "needs_manual_review"
        order["status"] = "needs_manual_review"
        order["metadata"]["reconciliation_status"] = "needs_manual_review"
        order["metadata"]["reconciliation_reason"] = reason
        return changed

    def update_local_position_from_exchange(self, *, position_ref, exchange_position, status, imported_at, exit_price=None):
        position = self.positions[position_ref.id]
        before = deepcopy(position)
        if status == "closed":
            position["status"] = "closed"
            position["exit_avg_price"] = exit_price
        elif exchange_position is not None:
            position["status"] = "open"
            position["quantity"] = abs(exchange_position.quantity)
            if exchange_position.entry_avg_price > 0:
                position["entry_avg_price"] = exchange_position.entry_avg_price
        return before != position

    def record_reconciliation_audit(self, *, connection, action, payload, entity_type=None, entity_id=None, created_at):
        self.audit_events.append(
            {
                "connection_id": connection.id,
                "action": action,
                "payload": payload,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "created_at": created_at,
            }
        )

    def mark_connection_synced(self, _connection, _synced_at):
        return None

    def mark_connection_stale(self, _connection, *, error, stale_at):
        self.stale_error = error
        self.stale_at = stale_at

    def set_live_entry_blocker(self, *, connection, blocked, reason, metadata, updated_at):
        before = self.live_entry_blocked
        self.live_entry_blocked = blocked
        return before != blocked

    def open_risk_quantity(self) -> Decimal:
        return sum(
            position["quantity"]
            for position in self.positions.values()
            if position["status"] == "open"
        )


if __name__ == "__main__":
    unittest.main()
