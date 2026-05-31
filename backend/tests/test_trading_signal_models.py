import unittest

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import JSONB

from app.models.signal import TradingSignal, TradingSignalEvent


class TradingSignalModelsTest(unittest.TestCase):
    def test_signal_numeric_precision_matches_migration(self) -> None:
        expected = {
            "confidence": (5, 2),
            "score": (8, 4),
            "entry_price": (38, 18),
            "stop_loss": (38, 18),
            "risk_reward": (10, 4),
        }
        for column_name, precision_scale in expected.items():
            column_type = TradingSignal.__table__.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual((column_type.precision, column_type.scale), precision_scale)

    def test_signal_jsonb_columns_match_schema(self) -> None:
        self.assertIsInstance(TradingSignal.__table__.c.take_profit.type, JSONB)
        self.assertIsInstance(TradingSignal.__table__.c.features_snapshot.type, JSONB)
        self.assertIsInstance(TradingSignalEvent.__table__.c.payload.type, JSONB)

    def test_signal_constraints_are_present(self) -> None:
        constraint_names = {constraint.name for constraint in TradingSignal.__table__.constraints}
        self.assertIn("ck_trading_signals_direction", constraint_names)
        self.assertIn("ck_trading_signals_status", constraint_names)
        self.assertIn("uq_trading_signals_signal_key", constraint_names)

    def test_status_constraint_allows_strategy_lifecycle_statuses(self) -> None:
        status_constraint = next(
            constraint
            for constraint in TradingSignal.__table__.constraints
            if constraint.name == "ck_trading_signals_status"
        )
        status_sql = str(status_constraint.sqltext)
        for status in ("watchlist", "ready", "actionable", "wait_for_pullback", "entry_touched"):
            self.assertIn(status, status_sql)

    def test_event_table_is_partitioned_by_created_at(self) -> None:
        self.assertEqual(
            TradingSignalEvent.__table__.dialect_options["postgresql"]["partition_by"],
            "RANGE (created_at)",
        )

    def test_event_primary_key_includes_partition_key(self) -> None:
        primary_key_columns = {column.name for column in TradingSignalEvent.__table__.primary_key.columns}
        self.assertEqual(primary_key_columns, {"id", "created_at"})

    def test_event_foreign_key_cascades_on_signal_delete(self) -> None:
        signal_id_column = TradingSignalEvent.__table__.c.signal_id
        foreign_key = next(iter(signal_id_column.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_required_signal_indexes_are_present(self) -> None:
        index_names = {index.name for index in TradingSignal.__table__.indexes}
        self.assertIn("idx_trading_signals_active", index_names)
        self.assertIn("idx_trading_signals_pair_time", index_names)
        self.assertIn("idx_trading_signals_strategy", index_names)
        self.assertIn("idx_trading_signals_features_gin", index_names)


if __name__ == "__main__":
    unittest.main()
