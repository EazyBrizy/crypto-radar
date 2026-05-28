from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[2]
CLICKHOUSE_SCHEMA = ROOT_DIR / "infra" / "clickhouse" / "init" / "002_market_analytics.sql"


class ClickHouseSchemaContractTest(unittest.TestCase):
    def test_liquidity_snapshots_table_is_defined_for_market_analytics(self) -> None:
        schema = CLICKHOUSE_SCHEMA.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS market.liquidity_snapshots", schema)
        self.assertIn("spread_percent Nullable(Float64)", schema)
        self.assertIn("depth_bid_1_0 Nullable(Decimal(38, 18))", schema)
        self.assertIn("ORDER BY (exchange, symbol, snapshot_ts)", schema)


if __name__ == "__main__":
    unittest.main()
