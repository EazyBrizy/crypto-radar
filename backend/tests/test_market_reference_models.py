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


if __name__ == "__main__":
    unittest.main()
