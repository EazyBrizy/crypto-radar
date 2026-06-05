import unittest

from sqlalchemy.dialects.postgresql import JSONB

from app.models.exchange_connection import UserExchangeConnection


class UserExchangeConnectionModelsTest(unittest.TestCase):
    def test_jsonb_columns_match_schema(self) -> None:
        self.assertIsInstance(UserExchangeConnection.__table__.c.permissions.type, JSONB)
        self.assertIsInstance(UserExchangeConnection.__table__.c.metadata.type, JSONB)

    def test_metadata_column_keeps_database_name(self) -> None:
        self.assertEqual(UserExchangeConnection.metadata_.property.columns[0].name, "metadata")

    def test_active_user_exchange_label_unique_index_is_present(self) -> None:
        index_names = {index.name for index in UserExchangeConnection.__table__.indexes}
        self.assertIn("uq_user_exchange_connections_active_label", index_names)

    def test_status_constraint_is_present(self) -> None:
        constraint_names = {constraint.name for constraint in UserExchangeConnection.__table__.constraints}
        self.assertIn("ck_user_exchange_connections_status", constraint_names)
        self.assertIn("ck_user_exchange_connections_environment", constraint_names)
        self.assertIn("ck_user_exchange_connections_order_placement_mode", constraint_names)
        self.assertIn("ck_user_exchange_connections_account_snapshot_status", constraint_names)

    def test_soft_delete_columns_are_present(self) -> None:
        column_names = set(UserExchangeConnection.__table__.c.keys())

        self.assertIn("revoked_at", column_names)
        self.assertIn("deleted_at", column_names)
        self.assertIn("deletion_reason", column_names)
        self.assertIn("environment", column_names)
        self.assertIn("order_placement_mode", column_names)
        self.assertIn("mainnet_explicitly_enabled", column_names)
        self.assertIn("last_account_snapshot_at", column_names)
        self.assertIn("account_snapshot_status", column_names)

    def test_user_foreign_key_cascades_on_delete(self) -> None:
        user_id_column = UserExchangeConnection.__table__.c.user_id
        foreign_key = next(iter(user_id_column.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")


if __name__ == "__main__":
    unittest.main()
