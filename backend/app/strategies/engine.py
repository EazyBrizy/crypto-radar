import asyncio
from typing import List

from app.schemas.market import Features
from app.schemas.signal import StrategySignal
from app.strategies.breakout import VolatilitySqueezeBreakoutStrategy
from app.strategies.liquidity_sweep import LiquiditySweepReversalStrategy
from app.strategies.trend_pullback import TrendPullbackContinuationStrategy


class StrategyEngine:
    """Запускает MVP-набор стратегий и возвращает отсортированные сигналы."""

    def __init__(self) -> None:
        self._strategies = [
            TrendPullbackContinuationStrategy(),
            VolatilitySqueezeBreakoutStrategy(),
            LiquiditySweepReversalStrategy(),
        ]

    @property
    def strategy_count(self) -> int:
        return len(self._strategies)

    @property
    def strategy_names(self) -> list[str]:
        return [strategy.name for strategy in self._strategies]

    async def generate_signals(self, features: Features) -> List[StrategySignal]:
        signals: List[StrategySignal] = []
        for strategy in self._strategies:
            signals.extend(await strategy.evaluate(features))
            await asyncio.sleep(0)
        return sorted(signals, key=lambda signal: signal.score, reverse=True)
