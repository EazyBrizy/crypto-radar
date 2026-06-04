import unittest

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import configure_mappers

from app.models import (
    AssetRiskGroup,
    ExchangeInstrumentRule,
    PositionRiskSnapshot,
    RiskDecisionRecord,
    RiskProtectionState,
)
from app.models.market import MarketAsset, MarketExchange, MarketPair
from app.models.portfolio import Order, Position
from app.models.user import AppUser


class RiskPersistenceModelsTest(unittest.TestCase):
    def test_mappers_include_risk_relationships(self) -> None:
        configure_mappers()

        self.assertIs(AppUser.risk_decisions.property.mapper.class_, RiskDecisionRecord)
        self.assertIs(AppUser.risk_protection_state.property.mapper.class_, RiskProtectionState)
        self.assertIs(Order.risk_decisions.property.mapper.class_, RiskDecisionRecord)
        self.assertIs(Position.risk_decisions.property.mapper.class_, RiskDecisionRecord)
        self.assertIs(Position.risk_snapshot.property.mapper.class_, PositionRiskSnapshot)
        self.assertIs(MarketExchange.instrument_rules.property.mapper.class_, ExchangeInstrumentRule)
        self.assertIs(MarketPair.instrument_rules.property.mapper.class_, ExchangeInstrumentRule)
        self.assertIs(MarketAsset.risk_groups.property.mapper.class_, AssetRiskGroup)

    def test_risk_decision_uses_jsonb_snapshots(self) -> None:
        table = RiskDecisionRecord.__table__

        self.assertIsInstance(table.c.blockers.type, JSONB)
        self.assertIsInstance(table.c.warnings.type, JSONB)
        self.assertIsInstance(table.c.input_snapshot.type, JSONB)
        self.assertIsInstance(table.c.result_snapshot.type, JSONB)

    def test_risk_decision_constraints_and_hot_indexes_are_present(self) -> None:
        table = RiskDecisionRecord.__table__
        constraint_names = {constraint.name for constraint in table.constraints}
        index_names = {index.name for index in table.indexes}

        self.assertIn("ck_risk_decisions_mode", constraint_names)
        self.assertIn("ck_risk_decisions_instrument_type", constraint_names)
        self.assertIn("ck_risk_decisions_stage", constraint_names)
        self.assertIn("ck_risk_decisions_status", constraint_names)
        self.assertIn("idx_risk_decisions_user_time", index_names)
        self.assertIn("idx_risk_decisions_status_time", index_names)
        self.assertIn("idx_risk_decisions_pending_entry_time", index_names)
        self.assertIn("pending_entry_intent_id", table.c)

    def test_position_risk_snapshot_uses_high_precision_numeric(self) -> None:
        table = PositionRiskSnapshot.__table__

        for column_name in ("risk_amount", "adjusted_risk_amount", "fee_estimate"):
            column_type = table.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual((column_type.precision, column_type.scale), (38, 18))

        for column_name in ("risk_percent", "rr", "strategy_multiplier", "signal_multiplier"):
            column_type = table.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual((column_type.precision, column_type.scale), (18, 8))

    def test_exchange_instrument_rules_cache_exchange_constraints(self) -> None:
        table = ExchangeInstrumentRule.__table__
        constraint_names = {constraint.name for constraint in table.constraints}

        self.assertIsInstance(table.c.raw_payload.type, JSONB)
        self.assertIn("uq_exchange_instrument_rules_exchange_category_symbol", constraint_names)
        self.assertIn("ck_exchange_instrument_rules_qty_step_positive", constraint_names)
        self.assertIn("ck_exchange_instrument_rules_tick_size_positive", constraint_names)

    def test_asset_risk_groups_allow_one_primary_group_for_mvp(self) -> None:
        table = AssetRiskGroup.__table__
        index_names = {index.name for index in table.indexes}

        self.assertIsInstance(table.c.metadata.type, JSONB)
        self.assertIn("uq_asset_risk_groups_primary_asset", index_names)

    def test_risk_protection_state_tracks_adaptive_mode(self) -> None:
        table = RiskProtectionState.__table__
        constraint_names = {constraint.name for constraint in table.constraints}

        self.assertIsInstance(table.c.metadata.type, JSONB)
        self.assertIn("ck_risk_protection_state_state", constraint_names)
        self.assertIn("ck_risk_protection_state_adaptive_multiplier_non_negative", constraint_names)
        self.assertIn("daily_window_start", table.c)
        self.assertIn("weekly_window_start", table.c)
        self.assertIn("window_timezone", table.c)


if __name__ == "__main__":
    unittest.main()
