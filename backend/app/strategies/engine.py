import asyncio
from typing import Any, List, Mapping

from app.schemas.market import Features
from app.schemas.signal import StrategySignal
from app.services.support_resistance import SupportResistanceSnapshot
from app.strategies.breakout import VolatilitySqueezeBreakoutStrategy
from app.strategies.liquidity_sweep import LiquiditySweepReversalStrategy
from app.strategies.pipeline import MarketQualityInput, StrategyEvaluationContext, StrategySignalPipeline
from app.strategies.trend_pullback import TrendPullbackContinuationStrategy


class StrategyEngine:
    """Запускает MVP-набор стратегий и возвращает отсортированные сигналы."""

    def __init__(self) -> None:
        self._strategies = [
            TrendPullbackContinuationStrategy(),
            VolatilitySqueezeBreakoutStrategy(),
            LiquiditySweepReversalStrategy(),
        ]
        self._pipeline = StrategySignalPipeline()

    @property
    def strategy_count(self) -> int:
        return len(self._strategies)

    @property
    def strategy_names(self) -> list[str]:
        return [strategy.name for strategy in self._strategies]

    async def generate_signals(
        self,
        features: Features,
        context_features: Features | None = None,
        context_features_by_timeframe: Mapping[str, Features] | None = None,
        support_resistance_by_timeframe: Mapping[str, SupportResistanceSnapshot] | None = None,
        market_quality: MarketQualityInput | None = None,
        strategy_configs: Mapping[str, Any] | None = None,
    ) -> List[StrategySignal]:
        signals: List[StrategySignal] = []
        for strategy in self._strategies:
            runtime_config = strategy_configs.get(strategy.name) if strategy_configs is not None else None
            if strategy_configs is not None and runtime_config is None:
                continue
            strategy_params = dict(getattr(runtime_config, "params", {}) if runtime_config is not None else {})
            strategy_params.update(getattr(runtime_config, "risk_settings", {}) if runtime_config is not None else {})
            context = StrategyEvaluationContext(
                signal_features=features,
                context_features=context_features,
                context_features_by_timeframe=context_features_by_timeframe or {},
                support_resistance_by_timeframe=support_resistance_by_timeframe or {},
                market_quality=market_quality,
                strategy_params=strategy_params,
                pair_scope_configured=bool(getattr(runtime_config, "pair_scope_configured", False)),
            )
            candidates = await strategy.evaluate(features, strategy_params)
            for candidate in candidates:
                finalized = self._pipeline.finalize(candidate, context)
                if finalized is not None:
                    signals.append(finalized)
            await asyncio.sleep(0)
        return sorted(signals, key=lambda signal: signal.score, reverse=True)
