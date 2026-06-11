from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base
from app.models.strategy_execution_eligibility import StrategyExecutionEligibilityProfile
from app.repositories.strategy_execution_eligibility import (
    StrategyExecutionEligibilityProfileRepository,
    StrategyExecutionEligibilityProfileUpsert,
)


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "202606110001_create_strategy_execution_eligibility_profiles.py"
)


class StrategyExecutionEligibilityProfileModelTest(unittest.TestCase):
    def test_model_table_exists_in_base_metadata(self) -> None:
        self.assertIn("strategy_execution_eligibility_profiles", Base.metadata.tables)
        self.assertIs(
            Base.metadata.tables["strategy_execution_eligibility_profiles"],
            StrategyExecutionEligibilityProfile.__table__,
        )

    def test_model_constraints_and_indexes_match_migration_contract(self) -> None:
        table = StrategyExecutionEligibilityProfile.__table__
        constraint_names = {constraint.name for constraint in table.constraints}
        index_names = {index.name for index in table.indexes}

        self.assertIn("ck_strategy_execution_eligibility_profiles_source", constraint_names)
        self.assertIn("ux_strategy_execution_eligibility_profile_key", index_names)
        self.assertIn("ix_strategy_execution_eligibility_profiles_lookup", index_names)
        self.assertIn("ix_strategy_execution_eligibility_profiles_eligible", index_names)
        self.assertEqual(table.c.source.nullable, False)
        self.assertEqual(table.c.run_ids.nullable, False)

    def test_migration_contains_profile_table_contract(self) -> None:
        migration = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn('"strategy_execution_eligibility_profiles"', migration)
        self.assertIn("expectancy_after_costs_r", migration)
        self.assertIn("run_ids", migration)
        self.assertIn("historical_backtest", migration)
        self.assertIn("forward_virtual", migration)
        self.assertIn("mixed", migration)


class StrategyExecutionEligibilityProfileRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._type_patches = _patch_sqlite_column_types()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        _create_sqlite_tables(self.engine)
        self.repository = StrategyExecutionEligibilityProfileRepository(self.SessionFactory)

    def tearDown(self) -> None:
        self.engine.dispose()
        _restore_column_types(self._type_patches)

    def test_upsert_inserts_and_gets_profile_by_full_execution_key(self) -> None:
        profile = self.repository.upsert_profile(_upsert(expectancy_after_costs_r=0.18))

        fetched = self.repository.get_profile(
            strategy_code="trend_pullback_continuation",
            exchange="bybit",
            symbol_scope="BTCUSDT",
            timeframe="1h",
            market_regime="trend",
            score_bucket="80-89",
            direction="long",
        )

        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.id, profile.id)
        self.assertTrue(fetched.eligible)
        self.assertEqual(fetched.source, "historical_backtest")
        self.assertEqual(fetched.run_ids, ["run-1"])
        self.assertEqual(fetched.metrics["profit_factor"], 1.8)

    def test_upsert_updates_existing_key_and_merges_run_ids_without_duplicates(self) -> None:
        first = self.repository.upsert_profile(_upsert(run_ids=["run-1"], source="historical_backtest"))

        second = self.repository.upsert_profile(
            _upsert(
                run_ids=["run-1", "run-2"],
                source="forward_virtual",
                eligible=False,
                reason_code="strategy_eligibility_failed",
                reason="Forward profile failed.",
                expectancy_after_costs_r=-0.02,
            )
        )

        self.assertEqual(second.id, first.id)
        self.assertFalse(second.eligible)
        self.assertEqual(second.source, "mixed")
        self.assertEqual(second.run_ids, ["run-1", "run-2"])
        self.assertEqual(second.reason, "Forward profile failed.")


def _upsert(
    *,
    source: str = "historical_backtest",
    eligible: bool = True,
    reason_code: str = "strategy_eligibility_passed",
    reason: str = "Backtest profile passed.",
    expectancy_after_costs_r: float | None = 0.18,
    run_ids: list[str] | None = None,
) -> StrategyExecutionEligibilityProfileUpsert:
    return StrategyExecutionEligibilityProfileUpsert(
        strategy_code="trend_pullback_continuation",
        exchange="bybit",
        symbol_scope="BTCUSDT",
        timeframe="1h",
        market_regime="trend",
        score_bucket="80-89",
        direction="long",
        eligible=eligible,
        source=source,
        metrics={"profit_factor": 1.8, "entry_touch_rate": 0.5},
        sample_size=64,
        expectancy_after_costs_r=expectancy_after_costs_r,
        profit_factor=1.8,
        entry_touch_rate=0.5,
        no_entry_rate=0.2,
        max_drawdown_r=3.4,
        run_ids=run_ids or ["run-1"],
        reason_code=reason_code,
        reason=reason,
        updated_at=datetime.now(timezone.utc),
    )


def _patch_sqlite_column_types() -> list[tuple[Any, Any]]:
    patches: list[tuple[Any, Any]] = []
    for column_name in ("metrics", "run_ids"):
        column = StrategyExecutionEligibilityProfile.__table__.c[column_name]
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
                CREATE TABLE strategy_execution_eligibility_profiles (
                    id UUID PRIMARY KEY,
                    strategy_code TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol_scope TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    score_bucket TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    eligible BOOLEAN NOT NULL,
                    source TEXT NOT NULL,
                    metrics JSON NOT NULL,
                    sample_size INTEGER NOT NULL,
                    expectancy_after_costs_r FLOAT,
                    profit_factor FLOAT,
                    entry_touch_rate FLOAT,
                    no_entry_rate FLOAT,
                    max_drawdown_r FLOAT,
                    run_ids JSON NOT NULL,
                    reason_code TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    UNIQUE(strategy_code, exchange, symbol_scope, timeframe, market_regime, score_bucket, direction)
                )
                """
            )
        )


if __name__ == "__main__":
    unittest.main()
