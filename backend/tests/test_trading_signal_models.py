import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import JSONB

from app.models.market import MarketExchange, MarketPair
from app.models.signal import TradingSignal, TradingSignalEvent
from app.models.strategy import StrategyTemplate, StrategyVersion
from app.repositories.signal_repository import _record_to_radar_signal, _snapshot_from_strategy_signal
from app.schemas.signal import StrategySignal
from app.schemas.trade_plan import (
    TradePlan,
    TradePlanEntry,
    TradePlanInvalidation,
    TradePlanRiskRules,
    TradePlanTarget,
)


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

    def test_trade_plan_json_roundtrip_works(self) -> None:
        trade_plan = TradePlan(
            entry=TradePlanEntry(price=100.5, min_price=100.0, max_price=101.0),
            stop_loss=98.0,
            targets=[
                TradePlanTarget(
                    label="TP1",
                    price=103.0,
                    r_multiple=2.0,
                    action="partial_close",
                    close_percent=40,
                )
            ],
            invalidation=TradePlanInvalidation(
                price=98.0,
                hard_stop=98.0,
                conditions=["Close below structure"],
                metadata={"source": "test"},
            ),
            risk_rules=TradePlanRiskRules(
                risk_reward=2.5,
                first_target_rr=2.0,
                final_target_rr=2.5,
                selected_rr=2.5,
                selected_rr_target="final",
                min_rr_ratio=1.5,
            ),
        )

        payload = trade_plan.model_dump(mode="json")
        restored = TradePlan.model_validate(payload)

        self.assertEqual(restored.model_dump(mode="json"), payload)

    def test_repository_persists_and_restores_trade_plan(self) -> None:
        trade_plan = TradePlan(
            entry=TradePlanEntry(price=100.0, min_price=99.9, max_price=100.1),
            stop_loss=98.0,
            targets=[
                TradePlanTarget(label="TP1", price=102.0, r_multiple=1.0),
                TradePlanTarget(label="TP2", price=104.0, r_multiple=2.0),
            ],
            invalidation=TradePlanInvalidation(price=98.0, hard_stop=98.0),
            risk_rules=TradePlanRiskRules(risk_reward=2.0),
        )
        signal = StrategySignal(
            exchange="bybit",
            symbol="BTCUSDT",
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            confidence=0.8,
            timestamp=1_779_796_800_000,
            score=80,
            timeframe="15m",
            entry_min=99.9,
            entry_max=100.1,
            stop_loss=98.0,
            take_profit_1=102.0,
            take_profit_2=104.0,
            risk_reward=2.0,
            trade_plan=trade_plan,
        )

        snapshot = _snapshot_from_strategy_signal(signal, explanation=None)
        record = _trading_signal_record(snapshot)
        restored = _record_to_radar_signal(record)

        self.assertEqual(snapshot["trade_plan"]["version"], "v1")
        self.assertIsNotNone(restored.trade_plan)
        self.assertEqual(restored.trade_plan.entry.min_price if restored.trade_plan else None, 99.9)
        self.assertEqual(
            [target.price for target in restored.trade_plan.targets] if restored.trade_plan else [],
            [102.0, 104.0],
        )


def _trading_signal_record(snapshot: dict) -> TradingSignal:
    now = datetime.now(timezone.utc)
    strategy = StrategyTemplate(
        id=uuid4(),
        code="volatility_squeeze_breakout",
        name="Volatility Squeeze Breakout",
        category="breakout",
    )
    strategy_version = StrategyVersion(
        id=uuid4(),
        version="1",
        config_schema={},
        default_params={},
        status="active",
        strategy=strategy,
    )
    return TradingSignal(
        id=uuid4(),
        signal_key="test-signal",
        strategy_version_id=strategy_version.id,
        exchange_id=uuid4(),
        pair_id=uuid4(),
        timeframe="15m",
        direction="long",
        status="actionable",
        confidence=Decimal("0.80"),
        score=Decimal("80"),
        entry_price=Decimal("100.0"),
        stop_loss=Decimal("98.0"),
        take_profit=[102.0, 104.0],
        risk_reward=Decimal("2.0"),
        detected_at=now,
        expires_at=None,
        features_snapshot=snapshot,
        explanation="Breakout setup",
        created_at=now,
        updated_at=now,
        exchange=MarketExchange(id=uuid4(), code="bybit", name="Bybit", type="cex"),
        pair=MarketPair(id=uuid4(), symbol="BTCUSDT"),
        strategy_version=strategy_version,
    )


if __name__ == "__main__":
    unittest.main()
