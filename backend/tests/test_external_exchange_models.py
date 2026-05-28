import unittest

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import JSONB

from app.models.external_exchange import ExternalExchangeOrder, ExternalExchangeTrade


class ExternalExchangeModelsTest(unittest.TestCase):
    def test_metadata_columns_keep_database_name(self) -> None:
        self.assertIsInstance(ExternalExchangeOrder.__table__.c.metadata.type, JSONB)
        self.assertIsInstance(ExternalExchangeTrade.__table__.c.metadata.type, JSONB)
        self.assertEqual(ExternalExchangeOrder.metadata_.property.columns[0].name, "metadata")
        self.assertEqual(ExternalExchangeTrade.metadata_.property.columns[0].name, "metadata")

    def test_order_unique_constraint_is_connection_scoped(self) -> None:
        constraint_names = {constraint.name for constraint in ExternalExchangeOrder.__table__.constraints}
        self.assertIn("uq_external_exchange_orders_connection_order", constraint_names)

    def test_trade_unique_constraint_is_connection_scoped(self) -> None:
        constraint_names = {constraint.name for constraint in ExternalExchangeTrade.__table__.constraints}
        self.assertIn("uq_external_exchange_trades_connection_trade", constraint_names)

    def test_numeric_precision_matches_schema(self) -> None:
        for table, column_name in (
            (ExternalExchangeOrder.__table__, "quantity"),
            (ExternalExchangeOrder.__table__, "price"),
            (ExternalExchangeTrade.__table__, "price"),
            (ExternalExchangeTrade.__table__, "quantity"),
            (ExternalExchangeTrade.__table__, "fee_amount"),
        ):
            column_type = table.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual((column_type.precision, column_type.scale), (38, 18))

    def test_trade_required_positive_constraints_are_present(self) -> None:
        constraint_names = {constraint.name for constraint in ExternalExchangeTrade.__table__.constraints}
        self.assertIn("ck_external_exchange_trades_price_positive", constraint_names)
        self.assertIn("ck_external_exchange_trades_quantity_positive", constraint_names)


if __name__ == "__main__":
    unittest.main()
