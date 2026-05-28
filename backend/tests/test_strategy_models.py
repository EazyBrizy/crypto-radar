import unittest

from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import JSONB

from app.models.strategy import StrategyTemplate, StrategyVersion, UserStrategyConfig


class StrategyModelsTest(unittest.TestCase):
    def test_strategy_version_jsonb_columns_match_schema(self) -> None:
        self.assertIsInstance(StrategyVersion.__table__.c.config_schema.type, JSONB)
        self.assertIsInstance(StrategyVersion.__table__.c.default_params.type, JSONB)

    def test_user_strategy_config_scope_and_params_are_jsonb(self) -> None:
        self.assertIsInstance(UserStrategyConfig.__table__.c.exchange_scope.type, JSONB)
        self.assertIsInstance(UserStrategyConfig.__table__.c.pair_scope.type, JSONB)
        self.assertIsInstance(UserStrategyConfig.__table__.c.params.type, JSONB)
        self.assertIsInstance(UserStrategyConfig.__table__.c.risk_settings.type, JSONB)

    def test_user_strategy_config_timeframes_use_text_array(self) -> None:
        self.assertIsInstance(UserStrategyConfig.__table__.c.timeframes.type, ARRAY)

    def test_strategy_version_unique_constraint_is_present(self) -> None:
        constraint_names = {constraint.name for constraint in StrategyVersion.__table__.constraints}
        self.assertIn("uq_strategy_versions_strategy_version", constraint_names)

    def test_template_code_unique_constraint_is_present(self) -> None:
        constraint_names = {constraint.name for constraint in StrategyTemplate.__table__.constraints}
        self.assertIn("uq_strategy_templates_code", constraint_names)

    def test_user_config_foreign_key_cascades_on_user_delete(self) -> None:
        user_id_column = UserStrategyConfig.__table__.c.user_id
        foreign_key = next(iter(user_id_column.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")


if __name__ == "__main__":
    unittest.main()
