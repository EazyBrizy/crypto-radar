import unittest

from app.services.bootstrap_service import (
    DEFAULT_WATCHLIST_NAME,
    DEMO_USER_EMAIL,
    INITIAL_VIRTUAL_BALANCE,
    SEED_ASSETS,
    SEED_EXCHANGES,
    SEED_PAIRS,
    SEED_STRATEGIES,
    SEED_STRATEGY_VERSIONS,
    SEED_SUBSCRIPTION_PLANS,
)
from app.services.market_scanner import DEFAULT_SYMBOLS
from app.strategies.engine import StrategyEngine


class BootstrapSeedContractTest(unittest.TestCase):
    def test_seed_codes_are_unique(self) -> None:
        self.assert_unique([item["code"] for item in SEED_EXCHANGES])
        self.assert_unique([item["symbol"] for item in SEED_ASSETS])
        self.assert_unique([item["symbol"] for item in SEED_PAIRS])
        self.assert_unique([item["code"] for item in SEED_SUBSCRIPTION_PLANS])
        self.assert_unique([item["code"] for item in SEED_STRATEGIES])

    def test_seed_pairs_cover_scanner_symbols(self) -> None:
        pair_symbols = {item["symbol"] for item in SEED_PAIRS}

        self.assertTrue(set(DEFAULT_SYMBOLS).issubset(pair_symbols))

    def test_seed_strategies_cover_runtime_engine(self) -> None:
        seeded_codes = {item["code"] for item in SEED_STRATEGIES}
        runtime_names = set(StrategyEngine().strategy_names)

        self.assertTrue(runtime_names.issubset(seeded_codes))

    def test_each_seed_strategy_has_initial_version(self) -> None:
        strategy_codes = {item["code"] for item in SEED_STRATEGIES}
        version_strategy_codes = {item["strategy_code"] for item in SEED_STRATEGY_VERSIONS}

        self.assertEqual(strategy_codes, version_strategy_codes)

    def test_demo_state_constants_are_defined(self) -> None:
        self.assertEqual(DEMO_USER_EMAIL, "demo@crypto-radar.local")
        self.assertEqual(DEFAULT_WATCHLIST_NAME, "Default")
        self.assertGreater(INITIAL_VIRTUAL_BALANCE, 0)

    def assert_unique(self, values: list[str]) -> None:
        self.assertEqual(len(values), len(set(values)))


if __name__ == "__main__":
    unittest.main()
