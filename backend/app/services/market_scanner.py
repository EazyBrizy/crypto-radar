import logging
from collections.abc import AsyncIterator
from typing import List, Optional

from app.exchanges.bybit import BybitAdapter
from app.schemas.market import MarketData
from app.schemas.signal import StrategySignal
from app.services.feature_engine import FeatureEngine
from app.strategies.breakout import StrategyEngine

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "1000PEPEUSDT",
]


class MarketScanner:
    """Запускает pipeline MarketData -> Features -> StrategySignal для нескольких символов."""

    def __init__(self, symbols: Optional[List[str]] = None) -> None:
        self._symbols = list(symbols) if symbols else list(DEFAULT_SYMBOLS)
        self._market = BybitAdapter(self._symbols)
        self._feature_engine = FeatureEngine()
        self._strategy_engine = StrategyEngine()

    async def process_tick(self, data: MarketData) -> List[StrategySignal]:
        features = await self._feature_engine.process(data)
        signals = await self._strategy_engine.generate_signals(features)
        if signals:
            for signal in signals:
                print(
                    f"signal {signal.symbol} {signal.strategy} "
                    f"{signal.direction} confidence={signal.confidence:.2f}"
                )
        return signals

    def listen(self) -> AsyncIterator[MarketData]:
        return self._market.listen()

    async def start(self) -> AsyncIterator[StrategySignal]:
        logger.info("Market scanner started for symbols: %s", ", ".join(self._symbols))
        async for tick in self._market.listen():
            signals = await self.process_tick(tick)
            for signal in signals:
                yield signal
