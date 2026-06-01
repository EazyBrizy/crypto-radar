import unittest
from datetime import datetime, timezone

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import JSONB

from app.models.portfolio import Order, OrderFill, Portfolio
from app.models.portfolio import PortfolioBalance, PortfolioBalanceLedger, Position
from app.schemas.trade import VirtualTrade


class VirtualTradingModelsTest(unittest.TestCase):
    def test_portfolio_type_constraint_is_present(self) -> None:
        constraint_names = {constraint.name for constraint in Portfolio.__table__.constraints}
        self.assertIn("ck_portfolios_type", constraint_names)

    def test_balances_use_composite_primary_key(self) -> None:
        primary_key_columns = {column.name for column in PortfolioBalance.__table__.primary_key.columns}
        self.assertEqual(primary_key_columns, {"portfolio_id", "asset_id"})

    def test_balance_amounts_use_high_precision_numeric(self) -> None:
        for table, column_name in (
            (PortfolioBalance.__table__, "available"),
            (PortfolioBalance.__table__, "locked"),
            (PortfolioBalanceLedger.__table__, "delta_available"),
            (PortfolioBalanceLedger.__table__, "delta_locked"),
        ):
            column_type = table.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual((column_type.precision, column_type.scale), (38, 18))

    def test_order_metadata_keeps_database_name(self) -> None:
        self.assertIsInstance(Order.__table__.c.metadata.type, JSONB)
        self.assertEqual(Order.metadata_.property.columns[0].name, "metadata")

    def test_order_constraints_and_idempotency_are_present(self) -> None:
        constraint_names = {constraint.name for constraint in Order.__table__.constraints}
        self.assertIn("ck_orders_mode", constraint_names)
        self.assertIn("ck_orders_side", constraint_names)
        self.assertIn("ck_orders_order_type", constraint_names)
        self.assertIn("ck_orders_status", constraint_names)
        self.assertIn("uq_orders_user_idempotency_key", constraint_names)

    def test_order_fills_cascade_on_order_delete(self) -> None:
        foreign_key = next(iter(OrderFill.__table__.c.order_id.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_position_take_profit_is_jsonb(self) -> None:
        self.assertIsInstance(Position.__table__.c.take_profit.type, JSONB)

    def test_position_constraints_are_present(self) -> None:
        constraint_names = {constraint.name for constraint in Position.__table__.constraints}
        self.assertIn("ck_positions_mode", constraint_names)
        self.assertIn("ck_positions_side", constraint_names)
        self.assertIn("ck_positions_status", constraint_names)

    def test_virtual_trade_lifecycle_fields_are_backward_compatible(self) -> None:
        now = datetime.now(timezone.utc)
        trade = VirtualTrade(
            id="legacy_trade",
            user_id="demo_user",
            signal_id="legacy_signal",
            exchange="bybit",
            symbol="BTCUSDT",
            strategy="legacy",
            timeframe="15m",
            side="long",
            entry_price=100.0,
            current_price=100.0,
            size_usd=100.0,
            quantity=1.0,
            leverage=1,
            risk_percent=1.0,
            stop_loss=90.0,
            take_profit=[120.0],
            status="open",
            opened_at=now,
            updated_at=now,
        )

        self.assertIsNone(trade.initial_quantity)
        self.assertIsNone(trade.remaining_quantity)
        self.assertEqual(trade.closed_quantity, 0.0)
        self.assertIsNone(trade.current_stop_loss)
        self.assertEqual(trade.realized_pnl, 0.0)
        self.assertEqual(trade.exit_fees, 0.0)
        self.assertEqual(trade.target_states, [])
        self.assertEqual(trade.lifecycle_events, [])


if __name__ == "__main__":
    unittest.main()
