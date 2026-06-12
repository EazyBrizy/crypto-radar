from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from app.schemas.market import Features
from app.schemas.signal import NoTradeFilterResult, SignalLayerCheck, StrategySignal
from app.strategies.breakout import VolatilitySqueezeBreakoutStrategy
from app.strategies.liquidity_sweep import LiquiditySweepReversalStrategy
from app.strategies.trend_pullback import TrendPullbackContinuationStrategy


EXPANDABLE_EDGE_CLASSES = (
    "relative_strength",
    "market_neutral_pair_trade",
    "funding_basis",
    "liquidation_momentum",
    "range_mean_reversion",
    "explicit_no_trade_strategy",
)


@dataclass(frozen=True)
class StrategyPluginCapabilities:
    edge_class: str
    emits_trading_signals: bool = True
    uses_common_status_contract: bool = True
    uses_execution_gate: bool = True
    supports_backtest: bool = True
    supports_forward_virtual: bool = True
    supports_edge_calibration: bool = True
    uses_risk_execution_policy: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyPluginDiagnostics:
    strategy: str
    edge_class: str
    no_trade: NoTradeFilterResult
    checks: list[SignalLayerCheck] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class StrategyPlugin(Protocol):
    name: str
    version: str
    required_data: list[str]
    capabilities: StrategyPluginCapabilities

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> list[StrategySignal]:
        ...


class StrategyPluginBase:
    capabilities: StrategyPluginCapabilities

    def generate_setup(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"strategy": self.name, "features": features, "params": dict(params or {})}

    def build_trade_plan(
        self,
        signal: StrategySignal,
        params: Mapping[str, Any] | None = None,
    ) -> StrategySignal:
        return signal

    def trigger_layer(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> list[SignalLayerCheck]:
        return []

    def regime_compatibility(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> list[SignalLayerCheck]:
        return []

    def risk_execution_constraints(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return dict(params or {})

    def diagnostics(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> StrategyPluginDiagnostics:
        no_trade = NoTradeFilterResult(
            enabled=True,
            blocked=False,
            hard_block=False,
            metadata={"edge_class": self.capabilities.edge_class},
        )
        return StrategyPluginDiagnostics(
            strategy=self.name,
            edge_class=self.capabilities.edge_class,
            no_trade=no_trade,
            metadata={"edge_class": self.capabilities.edge_class},
        )


class LegacyStrategyPluginAdapter(StrategyPluginBase):
    def __init__(self, strategy: StrategyPlugin, *, edge_class: str | None = None) -> None:
        self._strategy = strategy
        self.capabilities = StrategyPluginCapabilities(edge_class=edge_class or strategy.name)

    @property
    def name(self) -> str:
        return self._strategy.name

    @property
    def version(self) -> str:
        return self._strategy.version

    @property
    def required_data(self) -> list[str]:
        return self._strategy.required_data

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> list[StrategySignal]:
        return await self._strategy.evaluate(features, params)


class ExplicitNoTradeStrategyPlugin(StrategyPluginBase):
    name = "explicit_no_trade_strategy"
    version = "1.0"
    required_data: list[str] = []
    capabilities = StrategyPluginCapabilities(
        edge_class="explicit_no_trade_strategy",
        emits_trading_signals=False,
    )

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> list[StrategySignal]:
        return []

    def diagnostics(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> StrategyPluginDiagnostics:
        values = dict(params or {})
        reason = str(values.get("reason") or "Explicit no-trade strategy selected.")
        check = SignalLayerCheck(
            name=self.name,
            status="failed",
            reason=reason,
            metadata={"diagnostic_only": True},
        )
        no_trade = NoTradeFilterResult(
            enabled=True,
            blocked=True,
            hard_block=True,
            blockers=[reason],
            checks=[check],
            metadata={
                "diagnostic_only": True,
                "edge_classes": [self.capabilities.edge_class],
                "strategy": self.name,
            },
        )
        return StrategyPluginDiagnostics(
            strategy=self.name,
            edge_class=self.capabilities.edge_class,
            no_trade=no_trade,
            checks=[check],
            metadata={
                "diagnostic_only": True,
                "edge_class": self.capabilities.edge_class,
            },
        )


class StrategyPluginRegistry:
    def __init__(self, plugins: list[StrategyPlugin] | tuple[StrategyPlugin, ...]) -> None:
        self._plugins = tuple(plugins)
        duplicate_names = _duplicate_names(plugin.name for plugin in self._plugins)
        if duplicate_names:
            names = ", ".join(sorted(duplicate_names))
            raise ValueError(f"Duplicate strategy plugin names: {names}")

    @property
    def plugins(self) -> list[StrategyPlugin]:
        return list(self._plugins)

    @property
    def trading_plugins(self) -> list[StrategyPlugin]:
        return [
            plugin
            for plugin in self._plugins
            if getattr(plugin.capabilities, "emits_trading_signals", True)
        ]

    @property
    def diagnostic_plugins(self) -> list[StrategyPlugin]:
        return [
            plugin
            for plugin in self._plugins
            if not getattr(plugin.capabilities, "emits_trading_signals", True)
        ]

    @property
    def strategy_names(self) -> list[str]:
        return [plugin.name for plugin in self.trading_plugins]

    def get(self, name: str) -> StrategyPlugin | None:
        return next((plugin for plugin in self._plugins if plugin.name == name), None)


def _duplicate_names(names: Any) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return duplicates


default_strategy_plugin_registry = StrategyPluginRegistry(
    [
        LegacyStrategyPluginAdapter(
            TrendPullbackContinuationStrategy(),
            edge_class="relative_strength",
        ),
        LegacyStrategyPluginAdapter(
            VolatilitySqueezeBreakoutStrategy(),
            edge_class="liquidation_momentum",
        ),
        LegacyStrategyPluginAdapter(
            LiquiditySweepReversalStrategy(),
            edge_class="range_mean_reversion",
        ),
        ExplicitNoTradeStrategyPlugin(),
    ]
)
