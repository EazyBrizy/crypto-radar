from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from app.services.real_trade_import_service import (
    ExchangeOrderSnapshot,
    ExchangePositionSnapshot,
    LocalOrderRef,
    LocalPositionRef,
    RealTradeImportService,
)


CONNECTION_ID = UUID("10000000-0000-0000-0000-000000000001")
USER_ID = UUID("10000000-0000-0000-0000-000000000002")
ORDER_ID = UUID("10000000-0000-0000-0000-000000000003")
STOP_ORDER_ID = UUID("10000000-0000-0000-0000-000000000004")
POSITION_ID = UUID("10000000-0000-0000-0000-000000000005")
SIGNAL_ID = "10000000-0000-0000-0000-000000000006"


class RealTradeImportReconciliationTest(unittest.TestCase):
    def test_partial_fill_updates_local_position(self) -> None:
        repository = FakeReconciliationRepository()
        service = RealTradeImportService(repository=repository)

        result = service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[
                ExchangeOrderSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="buy",
                    status="partially_filled",
                    exchange_order_id="ex-entry-1",
                    client_order_id="client-entry-1",
                    role="entry",
                    quantity=Decimal("1"),
                    filled_quantity=Decimal("0.4"),
                    avg_price=Decimal("101"),
                    signal_id=SIGNAL_ID,
                    position_id=str(POSITION_ID),
                )
            ],
            exchange_positions=[
                ExchangePositionSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="long",
                    quantity=Decimal("0.4"),
                    entry_avg_price=Decimal("101"),
                    signal_id=SIGNAL_ID,
                    position_id=str(POSITION_ID),
                )
            ],
        )

        self.assertEqual(repository.positions[POSITION_ID]["quantity"], Decimal("0.4"))
        self.assertEqual(repository.positions[POSITION_ID]["entry_avg_price"], Decimal("101"))
        self.assertEqual(repository.orders[ORDER_ID]["status"], "partially_filled")
        self.assertGreaterEqual(result.local_positions_updated, 1)

    def test_cancelled_order_is_not_open_risk(self) -> None:
        repository = FakeReconciliationRepository()
        service = RealTradeImportService(repository=repository)

        service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[
                ExchangeOrderSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="buy",
                    status="cancelled",
                    exchange_order_id="ex-entry-1",
                    client_order_id="client-entry-1",
                    role="entry",
                    quantity=Decimal("1"),
                    filled_quantity=Decimal("0"),
                    signal_id=SIGNAL_ID,
                    position_id=str(POSITION_ID),
                )
            ],
            exchange_positions=[],
        )

        self.assertEqual(repository.positions[POSITION_ID]["status"], "closed")
        self.assertEqual(repository.open_risk_quantity(), Decimal("0"))

    def test_stop_fill_closes_position(self) -> None:
        repository = FakeReconciliationRepository()
        service = RealTradeImportService(repository=repository)

        service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[
                ExchangeOrderSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="sell",
                    status="filled",
                    exchange_order_id="ex-stop-1",
                    client_order_id="client-stop-1",
                    order_type="stop",
                    role="protective_stop",
                    quantity=Decimal("1"),
                    filled_quantity=Decimal("1"),
                    avg_price=Decimal("95"),
                    reduce_only=True,
                    signal_id=SIGNAL_ID,
                    position_id=str(POSITION_ID),
                )
            ],
            exchange_positions=[],
        )

        self.assertEqual(repository.orders[STOP_ORDER_ID]["status"], "filled")
        self.assertEqual(repository.positions[POSITION_ID]["status"], "closed")
        self.assertEqual(repository.positions[POSITION_ID]["exit_avg_price"], Decimal("95"))

    def test_duplicate_sync_does_not_duplicate_orders(self) -> None:
        repository = FakeReconciliationRepository()
        service = RealTradeImportService(repository=repository)
        order = ExchangeOrderSnapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            side="buy",
            status="submitted",
            exchange_order_id="ex-entry-1",
            client_order_id="client-entry-1",
            role="entry",
            quantity=Decimal("1"),
            signal_id=SIGNAL_ID,
            position_id=str(POSITION_ID),
        )

        first = service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[order],
            exchange_positions=[],
        )
        second = service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[order],
            exchange_positions=[],
        )

        self.assertEqual(len(repository.external_orders), 1)
        self.assertEqual(first.external_orders_written, 1)
        self.assertEqual(second.external_orders_written, 0)

    def test_unmatched_exchange_position_is_flagged(self) -> None:
        repository = FakeReconciliationRepository(include_local_position=False)
        service = RealTradeImportService(repository=repository)

        result = service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[],
            exchange_positions=[
                ExchangePositionSnapshot(
                    exchange="bybit",
                    symbol="ETHUSDT",
                    side="long",
                    quantity=Decimal("2"),
                    entry_avg_price=Decimal("2500"),
                )
            ],
        )

        self.assertEqual(len(result.unmatched_positions), 1)
        self.assertIn("manual_exchange_position_flagged", [change.action for change in result.changes])
        self.assertTrue(
            any(event["action"] == "real_position_sync.manual_exchange_position_flagged" for event in repository.audit_events)
        )


class FakeReconciliationRepository:
    def __init__(self, *, include_local_position: bool = True) -> None:
        self.connection = SimpleNamespace(
            id=CONNECTION_ID,
            user_id=USER_ID,
            exchange_id=UUID("10000000-0000-0000-0000-000000000007"),
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
            },
            STOP_ORDER_ID: {
                "id": STOP_ORDER_ID,
                "user_id": USER_ID,
                "exchange": "bybit",
                "symbol": "BTCUSDT",
                "side": "sell",
                "order_type": "stop",
                "status": "submitted",
                "quantity": Decimal("1"),
                "signal_id": SIGNAL_ID,
                "position_id": str(POSITION_ID),
                "exchange_order_id": "ex-stop-1",
                "client_order_id": "client-stop-1",
                "role": "protective_stop",
                "reduce_only": True,
                "metadata": {},
            },
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
                "exit_avg_price": None,
            }
        self.external_orders: dict[tuple[UUID, str], dict] = {}
        self.audit_events: list[dict] = []
        self.synced_at: datetime | None = None

    def list_active_connections(self):
        return [self.connection]

    def list_reconciliation_order_refs(self, _connection):
        return [
            LocalOrderRef(**deepcopy(order))
            for order in self.orders.values()
            if order["status"] in {"created", "submitted", "partially_filled"}
        ]

    def list_reconciliation_position_refs(self, _connection):
        refs = []
        for position in self.positions.values():
            if position["status"] != "open":
                continue
            payload = {
                key: deepcopy(position[key])
                for key in (
                    "id",
                    "user_id",
                    "exchange",
                    "symbol",
                    "side",
                    "status",
                    "quantity",
                    "entry_avg_price",
                    "signal_id",
                    "stop_loss",
                )
            }
            refs.append(LocalPositionRef(**payload))
        return refs

    def upsert_external_order(self, *, connection, order, imported_at):
        if not order.exchange_order_id:
            return False
        key = (connection.id, order.exchange_order_id)
        created = key not in self.external_orders
        self.external_orders[key] = {"order": order, "imported_at": imported_at}
        return created

    def update_local_order_from_exchange(self, *, order_ref, exchange_order, imported_at):
        order = self.orders[order_ref.id]
        new_status = exchange_order.status
        if exchange_order.status == "cancelled":
            new_status = "cancelled"
        elif exchange_order.status == "rejected":
            new_status = "rejected"
        elif exchange_order.status == "filled":
            new_status = "filled"
        elif exchange_order.filled_quantity and exchange_order.filled_quantity > 0:
            new_status = "partially_filled"
        elif new_status not in {"created", "submitted", "partially_filled", "filled", "cancelled", "rejected"}:
            new_status = "submitted"
        changed = order["status"] != new_status or order["metadata"].get("filled_quantity") != exchange_order.filled_quantity
        order["status"] = new_status
        order["metadata"]["exchange_order_id"] = exchange_order.exchange_order_id
        order["metadata"]["client_order_id"] = exchange_order.client_order_id
        order["metadata"]["filled_quantity"] = exchange_order.filled_quantity
        order["metadata"]["last_exchange_sync_at"] = imported_at.isoformat()
        return changed

    def update_local_position_from_exchange(self, *, position_ref, exchange_position, status, imported_at, exit_price=None):
        position = self.positions[position_ref.id]
        before = deepcopy(position)
        if status == "closed":
            position["status"] = "closed"
            position["closed_at"] = imported_at
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

    def mark_connection_synced(self, _connection, synced_at):
        self.synced_at = synced_at

    def open_risk_quantity(self) -> Decimal:
        return sum(
            position["quantity"]
            for position in self.positions.values()
            if position["status"] == "open"
        )


if __name__ == "__main__":
    unittest.main()
