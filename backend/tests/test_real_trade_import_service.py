from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from app.services.real_trade_import_service import (
    ExchangeExecutionSnapshot,
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
    def test_multiple_executions_update_cumulative_fill(self) -> None:
        repository = FakeReconciliationRepository()
        service = RealTradeImportService(repository=repository)

        result = service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[
                ExchangeOrderSnapshot(
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
            ],
            exchange_positions=[
                ExchangePositionSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="long",
                    quantity=Decimal("0.6"),
                    entry_avg_price=Decimal("102"),
                    stop_loss=Decimal("95"),
                    signal_id=SIGNAL_ID,
                    position_id=str(POSITION_ID),
                )
            ],
            exchange_executions=[
                ExchangeExecutionSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="buy",
                    exchange_execution_id="exec-1",
                    exchange_order_id="ex-entry-1",
                    client_order_id="client-entry-1",
                    price=Decimal("100"),
                    quantity=Decimal("0.25"),
                    fee_amount=Decimal("0.01"),
                    fee_asset_symbol="USDT",
                ),
                ExchangeExecutionSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="buy",
                    exchange_execution_id="exec-2",
                    exchange_order_id="ex-entry-1",
                    client_order_id="client-entry-1",
                    price=Decimal("103.25"),
                    quantity=Decimal("0.35"),
                    fee_amount=Decimal("0.02"),
                    fee_asset_symbol="USDT",
                ),
            ],
        )

        self.assertEqual(repository.orders[ORDER_ID]["status"], "partially_filled")
        self.assertEqual(repository.orders[ORDER_ID]["metadata"]["filled_quantity"], Decimal("0.60"))
        self.assertEqual(len(repository.order_fills), 2)
        self.assertEqual(len(repository.external_trades), 2)
        self.assertEqual(result.executions_seen, 2)
        self.assertEqual(result.local_fills_written, 2)

    def test_duplicate_execution_response_does_not_double_count(self) -> None:
        repository = FakeReconciliationRepository()
        service = RealTradeImportService(repository=repository)
        execution = ExchangeExecutionSnapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            side="buy",
            exchange_execution_id="exec-dup",
            exchange_order_id="ex-entry-1",
            client_order_id="client-entry-1",
            price=Decimal("100"),
            quantity=Decimal("0.25"),
        )

        service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[
                ExchangeOrderSnapshot(
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
            ],
            exchange_positions=[
                ExchangePositionSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="long",
                    quantity=Decimal("0.25"),
                    entry_avg_price=Decimal("100"),
                    stop_loss=Decimal("95"),
                    signal_id=SIGNAL_ID,
                    position_id=str(POSITION_ID),
                )
            ],
            exchange_executions=[execution, execution],
        )

        self.assertEqual(repository.orders[ORDER_ID]["metadata"]["filled_quantity"], Decimal("0.25"))
        self.assertEqual(len(repository.order_fills), 1)
        self.assertEqual(len(repository.external_trades), 1)

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

    def test_missing_protective_stop_creates_blocker_alert(self) -> None:
        repository = FakeReconciliationRepository()
        service = RealTradeImportService(repository=repository)

        result = service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[],
            exchange_positions=[
                ExchangePositionSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="long",
                    quantity=Decimal("1"),
                    entry_avg_price=Decimal("100"),
                    stop_loss=None,
                    signal_id=SIGNAL_ID,
                    position_id=str(POSITION_ID),
                )
            ],
        )

        self.assertTrue(repository.live_entry_blocked)
        self.assertIn("critical_alert", [change.action for change in result.changes])
        self.assertTrue(
            any(event["action"] == "real_position_sync.critical_alert" for event in repository.audit_events)
        )

    def test_missing_exchange_order_after_timeout_needs_manual_review(self) -> None:
        repository = FakeReconciliationRepository()
        service = RealTradeImportService(repository=repository, missing_order_timeout_seconds=0)

        result = service.reconcile_connection(
            connection=repository.connection,
            exchange_orders=[],
            exchange_positions=[
                ExchangePositionSnapshot(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="long",
                    quantity=Decimal("1"),
                    entry_avg_price=Decimal("100"),
                    stop_loss=Decimal("95"),
                    signal_id=SIGNAL_ID,
                    position_id=str(POSITION_ID),
                )
            ],
        )

        self.assertEqual(repository.orders[ORDER_ID]["status"], "needs_manual_review")
        self.assertIn("order_needs_manual_review", [change.action for change in result.changes])


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
        self.external_trades: dict[tuple[UUID, str], dict] = {}
        self.order_fills: dict[tuple[UUID, str], dict] = {}
        self.audit_events: list[dict] = []
        self.synced_at: datetime | None = None
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

    def mark_order_needs_manual_review(self, *, order_ref, imported_at, reason):
        order = self.orders[order_ref.id]
        changed = order["status"] != "needs_manual_review"
        order["status"] = "needs_manual_review"
        order["metadata"]["reconciliation_status"] = "needs_manual_review"
        order["metadata"]["reconciliation_reason"] = reason
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

    def mark_connection_stale(self, _connection, *, error, stale_at):
        self.stale_error = error
        self.stale_at = stale_at

    def set_live_entry_blocker(self, *, connection, blocked, reason, metadata, updated_at):
        before = self.live_entry_blocked
        self.live_entry_blocked = blocked
        self.live_entry_block_reason = reason
        self.live_entry_block_metadata = metadata
        self.live_entry_blocked_at = updated_at
        return before != blocked

    def open_risk_quantity(self) -> Decimal:
        return sum(
            position["quantity"]
            for position in self.positions.values()
            if position["status"] == "open"
        )


if __name__ == "__main__":
    unittest.main()
