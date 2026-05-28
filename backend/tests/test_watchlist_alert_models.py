import unittest

from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import JSONB

from app.models.watchlist import UserAlertRule, UserWatchlist, UserWatchlistPair


class WatchlistAlertModelsTest(unittest.TestCase):
    def test_watchlist_pair_uses_composite_primary_key(self) -> None:
        primary_key_columns = {column.name for column in UserWatchlistPair.__table__.primary_key.columns}
        self.assertEqual(primary_key_columns, {"watchlist_id", "pair_id"})

    def test_alert_condition_body_is_jsonb(self) -> None:
        self.assertIsInstance(UserAlertRule.__table__.c.condition_body.type, JSONB)

    def test_alert_channels_use_text_array(self) -> None:
        self.assertIsInstance(UserAlertRule.__table__.c.channels.type, ARRAY)
        default_sql = str(UserAlertRule.__table__.c.channels.server_default.arg)
        self.assertIn("websocket", default_sql)

    def test_user_owned_tables_cascade_on_user_delete(self) -> None:
        watchlist_fk = next(iter(UserWatchlist.__table__.c.user_id.foreign_keys))
        alert_fk = next(iter(UserAlertRule.__table__.c.user_id.foreign_keys))
        self.assertEqual(watchlist_fk.ondelete, "CASCADE")
        self.assertEqual(alert_fk.ondelete, "CASCADE")

    def test_watchlist_pairs_cascade_on_watchlist_delete(self) -> None:
        watchlist_id_column = UserWatchlistPair.__table__.c.watchlist_id
        foreign_key = next(iter(watchlist_id_column.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_alert_scope_columns_are_nullable(self) -> None:
        self.assertTrue(UserAlertRule.__table__.c.pair_id.nullable)
        self.assertTrue(UserAlertRule.__table__.c.strategy_version_id.nullable)


if __name__ == "__main__":
    unittest.main()
