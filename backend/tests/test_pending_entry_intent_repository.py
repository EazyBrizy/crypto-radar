from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Numeric, create_engine, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base
from app.models.pending_entry import PendingEntryIntent
from app.repositories.pending_entry_repository import PendingEntryIntentRepository
from app.schemas.pending_entry import PendingEntryIntentCreate


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "202606040001_create_pending_entry_intents.py"
)

USER_ID = UUID("7d7a4f33-a570-4334-b65f-3e5b4f0bb4a1")
SIGNAL_ID = UUID("eafefb92-8435-4d35-912f-6281ff0c1f19")


class PendingEntryIntentModelTest(unittest.TestCase):
    def test_model_table_exists_in_base_metadata(self) -> None:
        self.assertIn("pending_entry_intents", Base.metadata.tables)
        self.assertIs(Base.metadata.tables["pending_entry_intents"], PendingEntryIntent.__table__)

    def test_json_snapshots_and_numeric_precision_match_contract(self) -> None:
        table = PendingEntryIntent.__table__

        for column_name in (
            "targets_snapshot",
            "accepted_trade_plan_snapshot",
            "execution_profile_snapshot",
            "request_snapshot",
        ):
            self.assertIsInstance(table.c[column_name].type, JSONB)

        for column_name in ("entry_min", "entry_max", "stop_loss"):
            column_type = table.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual((column_type.precision, column_type.scale), (38, 18))

    def test_constraints_and_indexes_are_present(self) -> None:
        table = PendingEntryIntent.__table__
        constraint_names = {constraint.name for constraint in table.constraints}
        index_names = {index.name for index in table.indexes}

        self.assertIn("ck_pending_entry_intents_mode", constraint_names)
        self.assertIn("ck_pending_entry_intents_status", constraint_names)
        self.assertIn("ck_pending_entry_intents_side", constraint_names)
        self.assertIn("uq_pending_entry_intents_idempotency_key", constraint_names)
        self.assertIn("idx_pending_entry_intents_market_status", index_names)
        self.assertIn("idx_pending_entry_intents_user_signal_status", index_names)
        self.assertIn("uq_pending_entry_intents_active_user_signal_mode", index_names)

    def test_partial_unique_index_is_postgres_filtered_to_active_statuses(self) -> None:
        index = next(
            index
            for index in PendingEntryIntent.__table__.indexes
            if index.name == "uq_pending_entry_intents_active_user_signal_mode"
        )

        self.assertTrue(index.unique)
        where_clause = str(
            index.dialect_options["postgresql"]["where"].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("pending", where_clause)
        self.assertIn("requires_reconfirmation", where_clause)

    def test_migration_contains_required_indexes(self) -> None:
        migration = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn('revision = "202606040001"', migration)
        self.assertIn('down_revision = "202606010003"', migration)
        self.assertIn('"pending_entry_intents"', migration)
        self.assertIn("idx_pending_entry_intents_market_status", migration)
        self.assertIn("idx_pending_entry_intents_user_signal_status", migration)
        self.assertIn("uq_pending_entry_intents_idempotency_key", migration)
        self.assertIn("uq_pending_entry_intents_active_user_signal_mode", migration)
        self.assertIn("WHERE status IN", migration)


class PendingEntryIntentRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._type_patches = _patch_sqlite_column_types()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.SessionFactory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            future=True,
        )
        _create_sqlite_tables(self.engine)
        self.repository = PendingEntryIntentRepository(self.SessionFactory)

    def tearDown(self) -> None:
        self.engine.dispose()
        _restore_column_types(self._type_patches)

    def test_create_pending_intent_persists_snapshot(self) -> None:
        created = self.repository.create_intent(_intent_create())

        self.assertEqual(created.user_id, USER_ID)
        self.assertEqual(created.signal_id, SIGNAL_ID)
        self.assertEqual(created.status, "pending")
        self.assertEqual(created.exchange, "bybit")
        self.assertEqual(created.symbol, "BTCUSDT")
        self.assertEqual(created.targets_snapshot, [{"label": "TP1", "price": "110"}])
        self.assertEqual(created.accepted_trade_plan_hash, "trade-plan-hash")

        with self.SessionFactory() as session:
            count = session.scalar(select(func.count()).select_from(PendingEntryIntent))
        self.assertEqual(count, 1)

    def test_duplicate_idempotency_returns_existing_intent(self) -> None:
        first = self.repository.create_intent(_intent_create(idempotency_key="intent:same"))
        second = self.repository.create_intent(
            _intent_create(
                idempotency_key="intent:same",
                signal_id=uuid4(),
                symbol="ETHUSDT",
            )
        )

        self.assertEqual(second.id, first.id)
        self.assertEqual(second.signal_id, SIGNAL_ID)
        self.assertEqual(second.symbol, "BTCUSDT")

        with self.SessionFactory() as session:
            count = session.scalar(select(func.count()).select_from(PendingEntryIntent))
        self.assertEqual(count, 1)

    def test_list_pending_for_market_filters_by_exchange_symbol_and_status(self) -> None:
        btc_pending = self.repository.create_intent(_intent_create(idempotency_key="intent:btc"))
        eth_pending = self.repository.create_intent(
            _intent_create(
                signal_id=uuid4(),
                symbol="ETHUSDT",
                idempotency_key="intent:eth",
            )
        )
        self.repository.transition_status(eth_pending.id, status="triggered")

        pending = self.repository.list_pending_for_market("BYBIT", "BTC/USDT:PERP")

        self.assertEqual([intent.id for intent in pending], [btc_pending.id])

    def test_transition_status_updates_state_and_reason(self) -> None:
        created = self.repository.create_intent(_intent_create())
        changed_at = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)

        updated = self.repository.transition_status(
            created.id,
            status="failed",
            failure_reason="RiskGate rejected refreshed market context",
            now=changed_at,
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.status, "failed")
        self.assertEqual(updated.failure_reason, "RiskGate rejected refreshed market context")
        self.assertEqual(updated.updated_at, changed_at)

    def test_lock_for_trigger_selects_pending_intent_for_update(self) -> None:
        created = self.repository.create_intent(_intent_create())

        with self.SessionFactory() as session:
            locked = self.repository.lock_for_trigger(created.id, session=session)

            self.assertIsNotNone(locked)
            assert locked is not None
            self.assertEqual(locked.id, created.id)
            self.assertEqual(locked.status, "pending")


def _intent_create(**overrides: Any) -> PendingEntryIntentCreate:
    values: dict[str, Any] = {
        "user_id": USER_ID,
        "signal_id": SIGNAL_ID,
        "mode": "virtual",
        "exchange": "ByBit",
        "symbol": "BTC/USDT:PERP",
        "side": "long",
        "entry_min": Decimal("100"),
        "entry_max": Decimal("101"),
        "entry_price_policy": "entry_zone_midpoint",
        "stop_loss": Decimal("95"),
        "targets_snapshot": [{"label": "TP1", "price": "110"}],
        "accepted_trade_plan_snapshot": {"entry": {"min_price": "100", "max_price": "101"}},
        "accepted_trade_plan_hash": "trade-plan-hash",
        "accepted_signal_status": "ready",
        "accepted_signal_version": "v1",
        "accepted_signal_fingerprint": "signal-fingerprint",
        "execution_profile_snapshot": {"risk_mode": "percent", "risk_percent": "1"},
        "request_snapshot": {"auto_enter_on_confirmation": True},
        "idempotency_key": "pending-entry:test",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    values.update(overrides)
    return PendingEntryIntentCreate(**values)


def _patch_sqlite_column_types() -> list[tuple[Any, Any]]:
    patches: list[tuple[Any, Any]] = []
    for column_name in (
        "targets_snapshot",
        "accepted_trade_plan_snapshot",
        "execution_profile_snapshot",
        "request_snapshot",
    ):
        column = PendingEntryIntent.__table__.c[column_name]
        patches.append((column, column.type))
        column.type = JSON()
    return patches


def _restore_column_types(patches: list[tuple[Any, Any]]) -> None:
    for column, original_type in patches:
        column.type = original_type


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE pending_entry_intents (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    signal_id UUID NOT NULL,
                    strategy_id UUID,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_min NUMERIC NOT NULL,
                    entry_max NUMERIC NOT NULL,
                    entry_price_policy TEXT NOT NULL,
                    stop_loss NUMERIC NOT NULL,
                    targets_snapshot JSON NOT NULL,
                    accepted_trade_plan_snapshot JSON NOT NULL,
                    accepted_trade_plan_hash TEXT NOT NULL,
                    accepted_signal_status TEXT NOT NULL,
                    accepted_signal_version TEXT,
                    accepted_signal_fingerprint TEXT,
                    execution_profile_snapshot JSON NOT NULL,
                    request_snapshot JSON NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    expires_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    triggered_at DATETIME,
                    filled_at DATETIME,
                    filled_trade_id UUID,
                    failure_reason TEXT
                )
                """
            )
        )


if __name__ == "__main__":
    unittest.main()
