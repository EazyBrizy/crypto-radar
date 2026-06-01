import unittest
from types import SimpleNamespace

from app.schemas.strategy import StrategyPairScope
from app.services.strategy_config_service import (
    DEFAULT_STRATEGY_PARAMS_BY_CODE,
    RR_TARGET_DEFAULT_VERSION,
    StrategyConfigValidationError,
    _default_rr_target_for_strategy,
    _normalize_existing_strategy_defaults,
    _validate_exchanges,
    _validate_pairs,
)


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values

    def unique(self):
        return self


class _Session:
    def __init__(self, values):
        self._values = values

    def scalars(self, _statement):
        return _ScalarResult(self._values)


class StrategyConfigValidationTest(unittest.TestCase):
    def test_validate_pairs_rejects_missing_market_pair(self) -> None:
        session = _Session([])

        with self.assertRaises(StrategyConfigValidationError) as context:
            _validate_pairs(session, [StrategyPairScope(exchange="bybit", symbol="BADUSDT")])

        self.assertIn("bybit:BADUSDT", str(context.exception))
        self.assertIn("market_pairs", str(context.exception))

    def test_validate_pairs_rejects_disabled_market_pair(self) -> None:
        session = _Session([
            SimpleNamespace(
                symbol="BTCUSDT",
                status="disabled",
                exchange=SimpleNamespace(code="bybit", status="active"),
            )
        ])

        with self.assertRaises(StrategyConfigValidationError) as context:
            _validate_pairs(session, [StrategyPairScope(exchange="bybit", symbol="BTCUSDT")])

        self.assertIn("disabled", str(context.exception))

    def test_validate_pairs_accepts_active_pair(self) -> None:
        session = _Session([
            SimpleNamespace(
                symbol="BTCUSDT",
                status="active",
                exchange=SimpleNamespace(code="bybit", status="active"),
            )
        ])

        pairs = _validate_pairs(session, [StrategyPairScope(exchange="BYBIT", symbol="btcusdt")])

        self.assertEqual(pairs, [{"exchange": "bybit", "symbol": "BTCUSDT"}])

    def test_validate_exchanges_rejects_disabled_exchange(self) -> None:
        session = _Session([SimpleNamespace(code="bybit", status="disabled")])

        with self.assertRaises(StrategyConfigValidationError):
            _validate_exchanges(session, ["bybit"])

    def test_rr_target_defaults_are_strategy_specific(self) -> None:
        self.assertEqual(_default_rr_target_for_strategy("volatility_squeeze_breakout"), "final")
        self.assertEqual(_default_rr_target_for_strategy("trend_pullback_continuation"), "final")
        self.assertEqual(_default_rr_target_for_strategy("liquidity_sweep_reversal"), "nearest")

    def test_legacy_sweep_rr_default_migrates_to_nearest(self) -> None:
        config = SimpleNamespace(
            risk_settings={"rr_target": "final", "hide_failed_rr_signals": False},
            strategy_version=SimpleNamespace(
                strategy=SimpleNamespace(code="liquidity_sweep_reversal")
            ),
            updated_at=None,
        )

        changed = _normalize_existing_strategy_defaults([config])

        self.assertTrue(changed)
        self.assertEqual(config.risk_settings["rr_target"], "nearest")
        self.assertEqual(config.risk_settings["rr_target_default_version"], RR_TARGET_DEFAULT_VERSION)

    def test_squeeze_defaults_are_added_to_existing_params(self) -> None:
        config = SimpleNamespace(
            params={},
            risk_settings={},
            strategy_version=SimpleNamespace(
                strategy=SimpleNamespace(code="volatility_squeeze_breakout")
            ),
            updated_at=None,
        )

        changed = _normalize_existing_strategy_defaults([config])

        self.assertTrue(changed)
        for key in DEFAULT_STRATEGY_PARAMS_BY_CODE["volatility_squeeze_breakout"]:
            self.assertIn(key, config.params)

    def test_trend_pullback_defaults_are_added_to_existing_params(self) -> None:
        config = SimpleNamespace(
            params={},
            risk_settings={},
            strategy_version=SimpleNamespace(
                strategy=SimpleNamespace(code="trend_pullback_continuation")
            ),
            updated_at=None,
        )

        changed = _normalize_existing_strategy_defaults([config])

        self.assertTrue(changed)
        for key in DEFAULT_STRATEGY_PARAMS_BY_CODE["trend_pullback_continuation"]:
            self.assertIn(key, config.params)

    def test_liquidity_sweep_defaults_are_added_to_existing_params(self) -> None:
        config = SimpleNamespace(
            params={},
            risk_settings={},
            strategy_version=SimpleNamespace(
                strategy=SimpleNamespace(code="liquidity_sweep_reversal")
            ),
            updated_at=None,
        )

        changed = _normalize_existing_strategy_defaults([config])

        self.assertTrue(changed)
        for key in DEFAULT_STRATEGY_PARAMS_BY_CODE["liquidity_sweep_reversal"]:
            self.assertIn(key, config.params)


if __name__ == "__main__":
    unittest.main()
