import unittest

from sqlalchemy import Numeric

from app.models.market import MarketAsset, MarketExchange, MarketPair


class MarketReferenceModelsTest(unittest.TestCase):
    def test_metadata_columns_keep_database_name(self) -> None:
        self.assertEqual(MarketExchange.metadata_.property.columns[0].name, "metadata")
        self.assertEqual(MarketAsset.metadata_.property.columns[0].name, "metadata")
        self.assertEqual(MarketPair.metadata_.property.columns[0].name, "metadata")

    def test_market_pair_numeric_precision_matches_migration(self) -> None:
        for column_name in ("min_qty", "tick_size", "lot_size"):
            column_type = MarketPair.__table__.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual(column_type.precision, 38)
            self.assertEqual(column_type.scale, 18)

        for column_name in (
            "quote_volume_24h",
            "base_volume_24h",
            "turnover_24h",
            "last_price",
            "mark_price",
            "bid_price",
            "ask_price",
        ):
            column_type = MarketPair.__table__.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual((column_type.precision, column_type.scale), (38, 18))

        for column_name in ("spread_bps",):
            column_type = MarketPair.__table__.c[column_name].type
            self.assertIsInstance(column_type, Numeric)
            self.assertEqual((column_type.precision, column_type.scale), (18, 8))

        column_type = MarketPair.__table__.c["funding_rate"].type
        self.assertIsInstance(column_type, Numeric)
        self.assertEqual((column_type.precision, column_type.scale), (18, 10))

    def test_market_pair_universe_constraints_and_indexes_are_present(self) -> None:
        table = MarketPair.__table__
        constraint_names = {constraint.name for constraint in table.constraints}
        index_names = {index.name for index in table.indexes}

        self.assertIn("ck_market_pairs_liquidity_tier", constraint_names)
        self.assertIn("ck_market_pairs_turnover_24h_non_negative", constraint_names)
        self.assertIn("ck_market_pairs_spread_bps_non_negative", constraint_names)
        self.assertIn("idx_market_pairs_exchange_category_rank", index_names)
        self.assertIn("idx_market_pairs_exchange_quote_rank", index_names)
        self.assertIn("idx_market_pairs_exchange_turnover", index_names)


if __name__ == "__main__":
    unittest.main()
