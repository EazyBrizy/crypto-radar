import unittest
from typing import Any, Mapping

from app.schemas.market import Features
from app.schemas.signal import StrategySignal
from app.strategies.engine import StrategyEngine
from app.strategies.plugins import (
    EXPANDABLE_EDGE_CLASSES,
    ExplicitNoTradeStrategyPlugin,
    StrategyPluginCapabilities,
    StrategyPluginRegistry,
    default_strategy_plugin_registry,
)


class StrategyPluginRegistryTest(unittest.IsolatedAsyncioTestCase):
    def test_edge_class_catalog_contains_block_17_classes(self) -> None:
        self.assertEqual(
            EXPANDABLE_EDGE_CLASSES,
            (
                "relative_strength",
                "market_neutral_pair_trade",
                "funding_basis",
                "liquidation_momentum",
                "range_mean_reversion",
                "explicit_no_trade_strategy",
            ),
        )

    def test_default_plugins_use_common_strategy_testing_capabilities(self) -> None:
        for plugin in default_strategy_plugin_registry.plugins:
            capabilities = plugin.capabilities

            self.assertTrue(capabilities.uses_common_status_contract)
            self.assertTrue(capabilities.uses_execution_gate)
            self.assertTrue(capabilities.supports_backtest)
            self.assertTrue(capabilities.supports_forward_virtual)
            self.assertTrue(capabilities.supports_edge_calibration)
            self.assertTrue(capabilities.uses_risk_execution_policy)

    async def test_engine_accepts_custom_plugin_without_core_pipeline_changes(self) -> None:
        plugin = _NoSignalPlugin()
        engine = StrategyEngine(strategy_registry=StrategyPluginRegistry([plugin]))

        signals = await engine.generate_signals(_features())

        self.assertEqual(engine.strategy_names, ["relative_strength_demo"])
        self.assertEqual(signals, [])

    async def test_explicit_no_trade_plugin_emits_diagnostics_not_trading_signal(self) -> None:
        plugin = ExplicitNoTradeStrategyPlugin()

        signals = await plugin.evaluate(_features())
        diagnostics = plugin.diagnostics(_features(), {"reason": "Funding and liquidity are unfavorable."})

        self.assertEqual(signals, [])
        self.assertTrue(diagnostics.no_trade.blocked)
        self.assertTrue(diagnostics.no_trade.hard_block)
        self.assertIn("explicit_no_trade_strategy", diagnostics.no_trade.metadata["edge_classes"])
        self.assertIn("explicit_no_trade_strategy", diagnostics.metadata["edge_class"])

    async def test_engine_exposes_explicit_no_trade_diagnostics_without_signals(self) -> None:
        engine = StrategyEngine(strategy_registry=StrategyPluginRegistry([ExplicitNoTradeStrategyPlugin()]))

        signals = await engine.generate_signals(_features())
        diagnostics = engine.generate_diagnostics(
            _features(),
            strategy_configs={
                "explicit_no_trade_strategy": type(
                    "RuntimeConfig",
                    (),
                    {"params": {"reason": "No positive edge is active."}},
                )(),
            },
        )

        self.assertEqual(engine.strategy_names, [])
        self.assertEqual(signals, [])
        self.assertEqual(len(diagnostics), 1)
        self.assertTrue(diagnostics[0].no_trade.blocked)
        self.assertIn("No positive edge is active.", diagnostics[0].no_trade.blockers)


class _NoSignalPlugin:
    name = "relative_strength_demo"
    version = "0.1"
    required_data: list[str] = []
    capabilities = StrategyPluginCapabilities(edge_class="relative_strength")

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> list[StrategySignal]:
        return []


def _features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=1_780_000_000,
        candle_state="closed",
        price=100.0,
        open=99.0,
        high=101.0,
        low=98.0,
        close=100.0,
        volume=1_000_000,
        price_change_1m=0.0,
        volume_spike=1.0,
        volume_ma_20=1_000_000,
        volatility=1.0,
        history_length=250,
    )


if __name__ == "__main__":
    unittest.main()
