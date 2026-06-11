from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base
from app.models.strategy_testing import StrategyTestRun
from app.models.user import AppUser
from app.services.strategy_testing.schemas import StrategyTestPair, StrategyTestRunRequest
from app.services.strategy_testing.stores import PostgresStrategyTestRunStore


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "202606010003_create_strategy_test_runs.py"
)
FORWARD_RUNTIME_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "202606060004_add_forward_strategy_test_runtime.py"
)


class StrategyTestingRunModelTest(unittest.TestCase):
    def test_model_table_exists_in_base_metadata(self) -> None:
        self.assertIn("strategy_test_runs", Base.metadata.tables)
        self.assertIs(Base.metadata.tables["strategy_test_runs"], StrategyTestRun.__table__)

    def test_model_constraints_and_indexes_match_contract(self) -> None:
        table = StrategyTestRun.__table__
        constraint_names = {constraint.name for constraint in table.constraints}
        index_names = {index.name for index in table.indexes}
        column_names = set(table.c.keys())
        status_constraint = next(
            constraint
            for constraint in table.constraints
            if constraint.name == "ck_strategy_test_runs_status"
        )

        self.assertIn("test_type", column_names)
        self.assertIn("summary", column_names)
        self.assertIn("runtime_state", column_names)
        self.assertIn("last_heartbeat_at", column_names)
        self.assertIn("ck_strategy_test_runs_status", constraint_names)
        self.assertIn("ck_strategy_test_runs_test_type", constraint_names)
        self.assertIn("ck_strategy_test_runs_mode", constraint_names)
        self.assertIn("ck_strategy_test_runs_time_range", constraint_names)
        self.assertIn("ck_strategy_test_runs_requested_strategies_non_empty", constraint_names)
        self.assertIn("ck_strategy_test_runs_requested_timeframes_non_empty", constraint_names)
        self.assertIn("ix_strategy_test_runs_user_created", index_names)
        self.assertIn("ix_strategy_test_runs_status_created", index_names)
        self.assertIn("ix_strategy_test_runs_mode", index_names)
        self.assertIn("ix_strategy_test_runs_test_type", index_names)
        status_sql = str(status_constraint.sqltext)
        self.assertIn("cancelled", status_sql)
        self.assertIn("stopping", status_sql)

    def test_migration_contains_table_constraints_and_indexes(self) -> None:
        migration = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn('revision = "202606010003"', migration)
        self.assertIn('down_revision = "202606010002"', migration)
        self.assertIn('"strategy_test_runs"', migration)
        self.assertIn("ck_strategy_test_runs_status", migration)
        self.assertIn("ck_strategy_test_runs_mode", migration)
        self.assertIn("ck_strategy_test_runs_time_range", migration)
        self.assertIn("ck_strategy_test_runs_requested_strategies_non_empty", migration)
        self.assertIn("ck_strategy_test_runs_requested_timeframes_non_empty", migration)
        self.assertIn("ix_strategy_test_runs_user_created", migration)
        self.assertIn("ix_strategy_test_runs_status_created", migration)
        self.assertIn("ix_strategy_test_runs_mode", migration)
        self.assertIn("op.drop_table(\"strategy_test_runs\")", migration)

    def test_forward_runtime_migration_contract_is_reflected_by_model(self) -> None:
        migration = FORWARD_RUNTIME_MIGRATION_PATH.read_text(encoding="utf-8")
        table = StrategyTestRun.__table__

        self.assertIn("test_type", table.c)
        self.assertIn("summary", table.c)
        self.assertIn("runtime_state", table.c)
        self.assertIn("last_heartbeat_at", table.c)
        self.assertIn("ck_strategy_test_runs_test_type", {constraint.name for constraint in table.constraints})
        self.assertIn("ix_strategy_test_runs_test_type", {index.name for index in table.indexes})
        self.assertIn("forward_virtual", migration)
        self.assertIn("stopping", migration)


class PostgresStrategyTestRunStoreTest(unittest.TestCase):
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
        self.demo_user_id = uuid4()
        _create_sqlite_tables(self.engine)
        _seed_demo_user(self.SessionFactory, self.demo_user_id)
        self.store = PostgresStrategyTestRunStore(self.SessionFactory)

    def tearDown(self) -> None:
        self.engine.dispose()
        _restore_column_types(self._type_patches)

    def test_create_run_persists_queued_run_with_requested_matrix(self) -> None:
        detail = self.store.create_run(_request())

        self.assertEqual(detail.run.status, "queued")
        self.assertEqual(detail.run.test_type, "historical_backtest")
        self.assertEqual(detail.run.summary, {})
        self.assertEqual(detail.run.runtime_state, {})
        self.assertIsNone(detail.run.last_heartbeat_at)
        matrix = detail.run.requested_matrix
        self.assertEqual(matrix["user_id"], "demo_user")
        self.assertEqual(matrix["mode"], "research_virtual")
        self.assertEqual(matrix["strategies"], ["trend_pullback_continuation"])
        self.assertEqual(
            matrix["pairs"],
            [
                {"exchange": "bybit", "symbol": "BTCUSDT"},
                {"exchange": "binance", "symbol": "ETHUSDT"},
            ],
        )
        self.assertEqual(matrix["timeframes"], ["1h", "4h"])
        self.assertEqual(matrix["params"], {"risk": "standard"})
        self.assertEqual(matrix["metric_set"], ["expectancy_r"])
        self.assertEqual(matrix["tags"], ["research", "backtest"])
        self.assertEqual(matrix["scenario_count"], 4)

        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, detail.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.user_id, self.demo_user_id)
            self.assertEqual(run.requested_user_id, "demo_user")
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.test_type, "historical_backtest")

    def test_create_run_persists_forward_virtual_test_type(self) -> None:
        detail = self.store.create_run(_request(test_type="forward_virtual"))

        self.assertEqual(detail.run.test_type, "forward_virtual")
        self.assertEqual(detail.run.requested_matrix["test_type"], "forward_virtual")
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, detail.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.test_type, "forward_virtual")

    def test_list_and_get_return_persisted_run(self) -> None:
        created = self.store.create_run(_request())

        runs = self.store.list_runs(user_id="demo_user", limit=50)
        fetched = self.store.get_run(created.run.run_id)

        self.assertEqual([detail.run.run_id for detail in runs], [created.run.run_id])
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.run.run_id, created.run.run_id)

    def test_list_runs_can_filter_by_status(self) -> None:
        created = self.store.create_run(_request())
        self.store.mark_completed(created.run.run_id)

        completed_runs = self.store.list_runs(user_id="demo_user", limit=50, status="completed")
        queued_runs = self.store.list_runs(user_id="demo_user", limit=50, status="queued")

        self.assertEqual([detail.run.run_id for detail in completed_runs], [created.run.run_id])
        self.assertEqual(queued_runs, [])

    def test_mark_running_sets_started_at_and_status(self) -> None:
        created = self.store.create_run(_request())

        running = self.store.mark_running(created.run.run_id)

        self.assertEqual(running.run.status, "running")
        self.assertIsNotNone(running.run.started_at)
        self.assertIsNotNone(running.run.last_heartbeat_at)
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "running")
            self.assertIsNotNone(run.started_at)
            self.assertIsNotNone(run.last_heartbeat_at)

    def test_mark_completed_persists_summary_finished_at_and_heartbeat(self) -> None:
        created = self.store.create_run(_request())

        completed = self.store.mark_completed(created.run.run_id, summary={"trades_count": 0})
        reloaded = self.store.get_run(created.run.run_id)

        self.assertEqual(completed.run.status, "completed")
        self.assertEqual(completed.run.summary, {"trades_count": 0})
        self.assertIsNotNone(completed.run.finished_at)
        self.assertIsNotNone(completed.run.last_heartbeat_at)
        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.run.summary, {"trades_count": 0})
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.summary, {"trades_count": 0})
            self.assertIsNotNone(run.finished_at)
            self.assertIsNotNone(run.last_heartbeat_at)

    def test_mark_failed_sets_error_finished_at_and_heartbeat(self) -> None:
        created = self.store.create_run(_request())

        failed = self.store.mark_failed(created.run.run_id, "historical data unavailable")

        self.assertEqual(failed.run.status, "failed")
        self.assertEqual(failed.run.error, "historical data unavailable")
        self.assertIsNotNone(failed.run.finished_at)
        self.assertIsNotNone(failed.run.last_heartbeat_at)
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "failed")
            self.assertEqual(run.error, "historical data unavailable")
            self.assertIsNotNone(run.finished_at)
            self.assertIsNotNone(run.last_heartbeat_at)

    def test_mark_stopping_and_cancelled_use_forward_runtime_statuses(self) -> None:
        created = self.store.create_run(_request(test_type="forward_virtual"))

        stopping = self.store.mark_stopping(created.run.run_id)
        cancelled = self.store.mark_cancelled(created.run.run_id)

        self.assertEqual(stopping.run.status, "stopping")
        self.assertEqual(cancelled.run.status, "cancelled")
        self.assertIsNotNone(cancelled.run.finished_at)
        self.assertIsNotNone(cancelled.run.last_heartbeat_at)

    def test_demo_user_resolves_to_seeded_demo_username(self) -> None:
        created = self.store.create_run(_request(user_id="demo_user"))

        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.user_id, self.demo_user_id)


def _request(user_id: str = "demo_user", test_type: str = "historical_backtest") -> StrategyTestRunRequest:
    start_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return StrategyTestRunRequest(
        user_id=user_id,
        test_type=test_type,
        strategies=["trend_pullback_continuation"],
        pairs=[
            StrategyTestPair(exchange="bybit", symbol="btcusdt"),
            StrategyTestPair(exchange="binance", symbol="ethusdt"),
        ],
        timeframes=["1h", "4h"],
        start_at=start_at,
        end_at=start_at + timedelta(days=30),
        mode="research_virtual",
        params={"risk": "standard"},
        metric_set=["expectancy_r"],
        tags=["research"],
    )


def _patch_sqlite_column_types() -> list[tuple[Any, Any]]:
    patches: list[tuple[Any, Any]] = []
    for column_name in (
        "requested_strategies",
        "requested_pairs",
        "requested_timeframes",
        "params",
        "summary",
        "runtime_state",
        "metric_set",
        "tags",
    ):
        column = StrategyTestRun.__table__.c[column_name]
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
                CREATE TABLE app_users (
                    id UUID PRIMARY KEY,
                    email TEXT NOT NULL,
                    username TEXT,
                    status TEXT,
                    locale TEXT,
                    timezone TEXT,
                    risk_profile TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE user_auth_identities (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    provider TEXT NOT NULL,
                    provider_subject TEXT NOT NULL,
                    email TEXT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(user_id) REFERENCES app_users(id),
                    UNIQUE(provider, provider_subject)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE strategy_test_runs (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    requested_user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    test_type TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    requested_strategies JSON NOT NULL,
                    requested_pairs JSON NOT NULL,
                    requested_timeframes JSON NOT NULL,
                    start_at DATETIME NOT NULL,
                    end_at DATETIME NOT NULL,
                    params JSON NOT NULL,
                    summary JSON NOT NULL,
                    runtime_state JSON NOT NULL,
                    metric_set JSON NOT NULL,
                    tags JSON NOT NULL,
                    error TEXT,
                    created_at DATETIME NOT NULL,
                    started_at DATETIME,
                    finished_at DATETIME,
                    last_heartbeat_at DATETIME,
                    FOREIGN KEY(user_id) REFERENCES app_users(id)
                )
                """
            )
        )


def _seed_demo_user(session_factory: Any, user_id: Any) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            AppUser(
                id=user_id,
                email="demo@crypto-radar.local",
                username="demo",
                status="active",
                locale="ru",
                timezone="Europe/Warsaw",
                risk_profile="balanced",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


if __name__ == "__main__":
    unittest.main()
