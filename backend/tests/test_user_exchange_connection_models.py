import unittest

from sqlalchemy.dialects.postgresql import JSONB

from app.models.exchange_connection import UserExchangeConnection


class UserExchangeConnectionModelsTest(unittest.TestCase):
    def test_jsonb_columns_match_schema(self) -> None:
        self.assertIsInstance(UserExchangeConnection.__table__.c.permissions.type, JSONB)
        self.assertIsInstance(UserExchangeConnection.__table__.c.metadata.type, JSONB)

    def test_metadata_column_keeps_database_name(self) -> None:
        self.assertEqual(UserExchangeConnection.metadata_.property.columns[0].name, "metadata")

    def test_unique_user_exchange_label_constraint_is_present(self) -> None:
        constraint_names = {constraint.name for constraint in UserExchangeConnection.__table__.constraints}
        self.assertIn("uq_user_exchange_connections_user_exchange_label", constraint_names)

    def test_user_foreign_key_cascades_on_delete(self) -> None:
        user_id_column = UserExchangeConnection.__table__.c.user_id
        foreign_key = next(iter(user_id_column.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")


if __name__ == "__main__":
    unittest.main()
