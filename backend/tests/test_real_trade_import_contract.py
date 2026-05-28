from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
import unittest

from app.schemas.external_exchange import RealTradeImportRequest
from app.services.real_trade_import_service import (
    ClickHouseRealTradeAnalyticsWriter,
    RealTradeImportNotReadyError,
    RealTradeImportService,
)


CONNECTION_ID = UUID("9ab5a7ec-91d1-45f5-9e36-ae4127270d7f")
USER_ID = UUID("9e30ff75-1139-46d2-88dd-57a7bb8ca1b1")
PAIR_ID = UUID("4a890d03-255c-4cc4-9122-6f0123c4e027")


class FakeRepository:
    def get_connection(self, connection_id: UUID):
        return SimpleNamespace(
            id=connection_id,
            user_id=USER_ID,
            account_type="spot",
            key_ref="vault://stub/exchange/user/bybit/main/ref",
            exchange=SimpleNamespace(code="bybit"),
        )


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, list[list[object]], list[str]]] = []

    def insert(self, table: str, data: list[list[object]], column_names: list[str]) -> None:
        self.inserts.append((table, data, column_names))


class RealTradeImportContractTest(unittest.TestCase):
    def test_import_without_connector_returns_not_ready_contract(self) -> None:
        service = RealTradeImportService(repository=FakeRepository())
        request = RealTradeImportRequest(
            connection_id=CONNECTION_ID,
            symbols=["BTCUSDT"],
            dry_run=True,
        )

        with self.assertRaises(RealTradeImportNotReadyError) as ctx:
            service.import_connection(request)

        response = ctx.exception.response
        self.assertEqual(response.status, "not_implemented")
        self.assertTrue(response.connector_required)
        self.assertIn("external_exchange_orders", response.normalized_targets)
        self.assertIn("external_exchange_trades", response.normalized_targets)
        self.assertIn("analytics.external_trade_events", response.analytics_targets)
        self.assertIn("market.raw_exchange_events", response.raw_targets)
        self.assertEqual(response.details["exchange"], "bybit")
        self.assertEqual(response.details["requested_symbols"], ["BTCUSDT"])
        self.assertTrue(response.details["key_ref_present"])

    def test_clickhouse_writer_targets_external_trade_analytics_table(self) -> None:
        client = FakeClickHouseClient()
        writer = ClickHouseRealTradeAnalyticsWriter(lambda: client)
        now = datetime.now(timezone.utc)
        trade = SimpleNamespace(
            user_id=USER_ID,
            connection_id=CONNECTION_ID,
            exchange_trade_id="bybit-trade-1",
            side="buy",
            price=Decimal("100.25"),
            quantity=Decimal("0.5"),
            fee_amount=Decimal("0.01"),
            traded_at=now,
            imported_at=now,
            connection=SimpleNamespace(exchange=SimpleNamespace(code="bybit")),
            pair=SimpleNamespace(id=PAIR_ID, symbol="BTCUSDT"),
        )

        writer.write_external_trade(trade)

        table, rows, columns = client.inserts[0]
        self.assertEqual(table, "analytics.external_trade_events")
        self.assertIn("exchange_trade_id", columns)
        self.assertEqual(rows[0][2], "bybit")
        self.assertEqual(rows[0][3], "BTCUSDT")

    def test_clickhouse_writer_targets_raw_import_table(self) -> None:
        client = FakeClickHouseClient()
        writer = ClickHouseRealTradeAnalyticsWriter(lambda: client)
        now = datetime.now(timezone.utc)
        connection = SimpleNamespace(exchange=SimpleNamespace(code="bybit"))

        writer.write_raw_import_event(
            connection=connection,
            symbol="BTCUSDT",
            source_id="raw-sync-1",
            payload={"exchange_order_id": "order-1"},
            event_ts=now,
        )

        table, rows, columns = client.inserts[0]
        self.assertEqual(table, "market.raw_exchange_events")
        self.assertIn("raw_payload", columns)
        self.assertEqual(rows[0][1], "external_trade.import")
        self.assertEqual(rows[0][2], "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
