from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import settings
from app.models import strategy_testing as strategy_testing_models
from app.core.database import Base
from app.models.strategy_testing import StrategyTestRun
from app.models.user import AppUser
from app.services.strategy_testing.schemas import StrategyTestPair, StrategyTestRunRequest
from app.services.strategy_testing.stores import PostgresStrategyTestRunStore, _claim_next_run_statement


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
STRATEGY_TEST_WORKER_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "202606150001_add_strategy_test_worker_lease.py"
)
SCENARIO_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "202606150002_add_strategy_test_scenarios.py"
)


class StrategyTestingRunModelTest(unittest.TestCase):
    def test_model_table_exists_in_base_metadata(self) -> None:
        self.assertIn("strategy_test_runs", Base.metadata.tables)
        self.assertIs(Base.metadata.tables["strategy_test_runs"], StrategyTestRun.__table__)

    def test_scenario_model_table_exists_in_base_metadata(self) -> None:
        scenario_model = getattr(strategy_testing_models, "StrategyTestScenario", None)

        self.assertIsNotNone(scenario_model)
        self.assertIn("strategy_test_scenarios", Base.metadata.tables)
        self.assertIs(Base.metadata.tables["strategy_test_scenarios"], scenario_model.__table__)

    def test_scenario_model_constraints_and_indexes_match_contract(self) -> None:
        scenario_model = getattr(strategy_testing_models, "StrategyTestScenario", None)
        self.assertIsNotNone(scenario_model)
        table = scenario_model.__table__
        column_names = set(table.c.keys())
        constraint_names = {constraint.name for constraint in table.constraints}
        index_names = {index.name for index in table.indexes}

        self.assertIn("run_id", column_names)
        self.assertIn("scenario_key", column_names)
        self.assertIn("scenario_index", column_names)
        self.assertIn("strategy_code", column_names)
        self.assertIn("exchange", column_names)
        self.assertIn("symbol", column_names)
        self.assertIn("timeframe", column_names)
        self.assertIn("status", column_names)
        self.assertIn("bars_total", column_names)
        self.assertIn("bars_processed", column_names)
        self.assertIn("summary", column_names)
        self.assertIn("error", column_names)
        self.assertIn("result_written_at", column_names)
        self.assertIn("started_at", column_names)
        self.assertIn("completed_at", column_names)
        self.assertIn("uq_strategy_test_scenarios_run_key", constraint_names)
        self.assertIn("ck_strategy_test_scenarios_status", constraint_names)
        self.assertIn("ix_strategy_test_scenarios_run_status", index_names)

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
        self.assertIn("worker_id", column_names)
        self.assertIn("worker_attempt", column_names)
        self.assertIn("lease_expires_at", column_names)
        self.assertIn("claimed_at", column_names)
        self.assertIn("ck_strategy_test_runs_status", constraint_names)
        self.assertIn("ck_strategy_test_runs_test_type", constraint_names)
        self.assertIn("ck_strategy_test_runs_mode", constraint_names)
        self.assertIn("ck_strategy_test_runs_time_range", constraint_names)
        self.assertIn("ck_strategy_test_runs_requested_strategies_non_empty", constraint_names)
        self.assertIn("ck_strategy_test_runs_requested_timeframes_non_empty", constraint_names)
        self.assertIn("ix_strategy_test_runs_user_created", index_names)
        self.assertIn("ix_strategy_test_runs_status_created", index_names)
        self.assertIn("ix_strategy_test_runs_status_lease", index_names)
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

    def test_strategy_test_worker_lease_migration_contract_is_reflected_by_model(self) -> None:
        migration = STRATEGY_TEST_WORKER_MIGRATION_PATH.read_text(encoding="utf-8")
        table = StrategyTestRun.__table__

        self.assertIn("worker_id", table.c)
        self.assertIn("worker_attempt", table.c)
        self.assertIn("lease_expires_at", table.c)
        self.assertIn("claimed_at", table.c)
        self.assertIn("ix_strategy_test_runs_status_lease", {index.name for index in table.indexes})
        self.assertIn("worker_id", migration)
        self.assertIn("worker_attempt", migration)
        self.assertIn("lease_expires_at", migration)
        self.assertIn("claimed_at", migration)
        self.assertIn("ix_strategy_test_runs_status_lease", migration)

    def test_scenario_checkpoint_migration_contract_is_reflected_by_model(self) -> None:
        scenario_model = getattr(strategy_testing_models, "StrategyTestScenario", None)
        self.assertIsNotNone(scenario_model)
        migration = SCENARIO_MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn("strategy_test_scenarios", migration)
        self.assertIn("fk_strategy_test_scenarios_run_id", migration)
        self.assertIn("uq_strategy_test_scenarios_run_key", migration)
        self.assertIn("ix_strategy_test_scenarios_run_status", migration)
        self.assertIn("queued", migration)
        self.assertIn("running", migration)
        self.assertIn("completed", migration)
        self.assertIn("failed", migration)
        self.assertIn("cancelled", migration)
        self.assertIn("op.drop_table(\"strategy_test_scenarios\")", migration)

    def test_claim_next_run_statement_uses_postgres_skip_locked(self) -> None:
        now = datetime(2026, 6, 17, tzinfo=timezone.utc)
        statement = _claim_next_run_statement(now).limit(1)

        compiled = str(statement.compile(dialect=postgresql.dialect()))

        self.assertIn("FOR UPDATE SKIP LOCKED", compiled)
        self.assertIn("strategy_test_runs.status = ", compiled)
        self.assertIn("strategy_test_runs.lease_expires_at IS NULL", compiled)
        self.assertIn("strategy_test_runs.lease_expires_at <= ", compiled)


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
        self.assertEqual(
            detail.run.runtime_state,
            {"stale_threshold_seconds": settings.strategy_test_lease_seconds},
        )
        self.assertIsNone(detail.run.last_heartbeat_at)
        self.assertEqual(detail.run.requested_matrix["scenario_count"], 4)
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
            self.assertIsNone(run.worker_id)
            self.assertEqual(run.worker_attempt, 0)
            self.assertIsNone(run.lease_expires_at)
            self.assertIsNone(run.claimed_at)

    def test_scenario_checkpoint_lifecycle_and_completed_key_lookup(self) -> None:
        created = self.store.create_run(_request())

        running = self.store.mark_scenario_running(
            created.run.run_id,
            scenario_key="trend_pullback_continuation::bybit::BTCUSDT::1h",
            scenario_index=1,
            strategy_code="trend_pullback_continuation",
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            bars_total=250,
        )
        completed = self.store.mark_scenario_completed(
            created.run.run_id,
            scenario_key="trend_pullback_continuation::bybit::BTCUSDT::1h",
            summary={"signals_seen": 150_000, "trades_count": 7},
            bars_processed=250,
            result_written_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        scenarios = self.store.list_scenarios(created.run.run_id)

        self.assertEqual(running.status, "running")
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.summary["signals_seen"], 150_000)
        self.assertEqual(completed.bars_total, 250)
        self.assertEqual(completed.bars_processed, 250)
        self.assertEqual(
            self.store.completed_scenario_keys(created.run.run_id),
            {"trend_pullback_continuation::bybit::BTCUSDT::1h"},
        )
        self.assertEqual([scenario.scenario_key for scenario in scenarios], [completed.scenario_key])

    def test_claim_next_run_sets_worker_lease_and_attempt(self) -> None:
        created = self.store.create_run(_request())

        claimed = self.store.claim_next_run(worker_id="worker-a", lease_seconds=30)

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.run.run_id, created.run.run_id)
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.worker_id, "worker-a")
            self.assertEqual(run.worker_attempt, 1)
            self.assertIsNotNone(run.claimed_at)
            self.assertIsNotNone(run.lease_expires_at)

    def test_claim_next_run_does_not_reclaim_unexpired_queued_lease(self) -> None:
        created = self.store.create_run(_request())

        first_claim = self.store.claim_next_run(worker_id="worker-a", lease_seconds=30)
        second_claim = self.store.claim_next_run(worker_id="worker-b", lease_seconds=30)

        self.assertIsNotNone(first_claim)
        self.assertIsNone(second_claim)
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            run.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()

        reclaimed = self.store.claim_next_run(worker_id="worker-b", lease_seconds=30)

        self.assertIsNotNone(reclaimed)
        assert reclaimed is not None
        self.assertEqual(reclaimed.run.run_id, created.run.run_id)
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.worker_id, "worker-b")
            self.assertEqual(run.worker_attempt, 2)
            self.assertIsNotNone(run.lease_expires_at)

    def test_recover_expired_historical_running_lease_requeues_run_and_keeps_checkpoints(self) -> None:
        created = self.store.create_run(_request())
        self.store.claim_next_run(worker_id="worker-a", lease_seconds=30)
        self.store.mark_running(created.run.run_id)
        self.store.update_runtime_state(
            created.run.run_id,
            {
                "phase": "running_scenario",
                "partial_summary": {"scenario_count": 4, "completed_scenarios": 1},
            },
        )
        self.store.mark_scenario_running(
            created.run.run_id,
            scenario_key="trend_pullback_continuation::bybit::BTCUSDT::1h",
            scenario_index=1,
            strategy_code="trend_pullback_continuation",
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            bars_total=250,
        )
        self.store.mark_scenario_completed(
            created.run.run_id,
            scenario_key="trend_pullback_continuation::bybit::BTCUSDT::1h",
            summary={"trades_count": 2, "realized_r": 1.25},
            bars_processed=250,
        )
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            run.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()

        recovered = self.store.recover_expired_leases(worker_id="worker-b")

        self.assertEqual(recovered, {"failed": 0, "cancelled": 0, "requeued": 1})
        detail = self.store.get_run(created.run.run_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.run.status, "queued")
        self.assertIsNone(detail.run.worker_id)
        self.assertIsNone(detail.run.claimed_at)
        self.assertIsNone(detail.run.lease_expires_at)
        self.assertIsNone(detail.run.finished_at)
        self.assertIsNone(detail.run.error)
        self.assertEqual(detail.run.runtime_state["phase"], "queued")
        self.assertEqual(
            detail.run.runtime_state["last_heartbeat_reason"],
            "historical_lease_expired_requeued",
        )
        self.assertEqual(detail.run.runtime_state["partial_summary"]["completed_scenarios"], 1)
        self.assertEqual(
            self.store.completed_scenario_keys(created.run.run_id),
            {"trend_pullback_continuation::bybit::BTCUSDT::1h"},
        )

    def test_recover_expired_forward_running_lease_still_fails_realtime_run(self) -> None:
        created = self.store.create_run(_request(test_type="forward_virtual"))
        self.store.claim_next_run(worker_id="worker-a", lease_seconds=30)
        self.store.mark_running(created.run.run_id)
        self.store.update_runtime_state(
            created.run.run_id,
            {"status": "listening", "processed_ticks": 3},
        )
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            run.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()

        recovered = self.store.recover_expired_leases(worker_id="worker-b")

        self.assertEqual(recovered, {"failed": 1, "cancelled": 0, "requeued": 0})
        detail = self.store.get_run(created.run.run_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.run.status, "failed")
        self.assertEqual(detail.run.runtime_state["phase"], "failed")
        self.assertIn("lease expired", detail.run.error or "")

    def test_worker_lease_state_exposes_active_forward_worker_from_db(self) -> None:
        created = self.store.create_run(_request(test_type="forward_virtual"))
        self.store.claim_next_run(worker_id="strategy-test-worker-a", lease_seconds=30)
        self.store.mark_running(created.run.run_id)
        self.store.update_runtime_state(
            created.run.run_id,
            {
                "status": "listening",
                "last_heartbeat_reason": "market_data_received",
                "last_forward_event": "market_tick",
            },
        )

        state = self.store.get_worker_lease_state()

        self.assertEqual(state.status, "active")
        self.assertEqual(state.run_id, created.run.run_id)
        self.assertEqual(state.run_status, "running")
        self.assertEqual(state.test_type, "forward_virtual")
        self.assertEqual(state.worker_id, "strategy-test-worker-a")
        self.assertEqual(state.worker_attempt, 1)
        self.assertTrue(state.lease_active)
        self.assertGreater(state.lease_expires_in_seconds or 0, 0)
        self.assertEqual(state.runtime_status, "listening")
        self.assertEqual(state.last_heartbeat_reason, "market_data_received")
        self.assertEqual(state.last_forward_event, "market_tick")

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

    def test_update_runtime_state_merges_state_and_updates_heartbeat(self) -> None:
        created = self.store.create_run(_request(test_type="forward_virtual"))
        self.store.mark_running(created.run.run_id)

        first = self.store.update_runtime_state(
            created.run.run_id,
            {"status": "listening", "processed_signals": 1},
        )
        second = self.store.update_runtime_state(
            created.run.run_id,
            {"opened_trades": 1},
        )

        self.assertEqual(first.run.runtime_state["status"], "listening")
        self.assertEqual(second.run.runtime_state["status"], "listening")
        self.assertEqual(second.run.runtime_state["processed_signals"], 1)
        self.assertEqual(second.run.runtime_state["opened_trades"], 1)
        self.assertIsNotNone(second.run.last_heartbeat_at)
        with self.SessionFactory() as session:
            run = session.get(StrategyTestRun, created.run.run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.runtime_state["processed_signals"], 1)
            self.assertEqual(run.runtime_state["opened_trades"], 1)

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
    scenario_model = getattr(strategy_testing_models, "StrategyTestScenario", None)
    if scenario_model is not None:
        column = scenario_model.__table__.c["summary"]
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
                    worker_id TEXT,
                    worker_attempt INTEGER NOT NULL DEFAULT 0,
                    lease_expires_at DATETIME,
                    claimed_at DATETIME,
                    FOREIGN KEY(user_id) REFERENCES app_users(id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE strategy_test_scenarios (
                    id UUID PRIMARY KEY,
                    run_id UUID NOT NULL,
                    scenario_key TEXT NOT NULL,
                    scenario_index INTEGER NOT NULL,
                    strategy_code TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    status TEXT NOT NULL,
                    bars_total INTEGER NOT NULL DEFAULT 0,
                    bars_processed INTEGER NOT NULL DEFAULT 0,
                    summary JSON NOT NULL,
                    error TEXT,
                    result_written_at DATETIME,
                    started_at DATETIME,
                    completed_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES strategy_test_runs(id),
                    UNIQUE(run_id, scenario_key)
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
