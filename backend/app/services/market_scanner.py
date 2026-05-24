import asyncio
import logging
from collections.abc import AsyncIterator
from typing import List, Optional

from app.exchanges.bybit import BybitAdapter
from app.schemas.market import MarketData
from app.schemas.signal import StrategySignal
from app.services.candle_service import CandleService, candle_service
from app.services.feature_engine import FeatureEngine
from app.strategies.engine import StrategyEngine

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "1000PEPEUSDT",
]


class MarketScanner:
    """Запускает market-data pipeline для выбранных бирж и торговых пар."""

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        exchanges: Optional[List[str]] = None,
        candle_store: CandleService = candle_service,
    ) -> None:
        self._symbols = list(symbols) if symbols else list(DEFAULT_SYMBOLS)
        self._exchanges = [exchange.lower() for exchange in (exchanges or ["bybit"])]
        self._adapters = self._build_adapters()
        self._candle_store = candle_store
        self._feature_engine = FeatureEngine()
        self._strategy_engine = StrategyEngine()

    def _build_adapters(self) -> list[BybitAdapter]:
        adapters: list[BybitAdapter] = []
        for exchange in self._exchanges:
            if exchange == "bybit":
                adapters.append(BybitAdapter(self._symbols))
            else:
                logger.warning("Exchange adapter is not implemented: %s", exchange)
        return adapters

    async def process_tick(self, data: MarketData) -> List[StrategySignal]:
        self._candle_store.update_from_tick(data)
        features = await self._feature_engine.process(data)
        signals = await self._strategy_engine.generate_signals(features)
        if signals:
            for signal in signals:
                print(
                    f"signal {signal.exchange} {signal.symbol} {signal.strategy} "
                    f"{signal.direction} score={signal.score}"
                )
        return signals

    def listen(self) -> AsyncIterator[MarketData]:
        return self._listen_all()

    async def _listen_all(self) -> AsyncIterator[MarketData]:
        if not self._adapters:
            logger.warning("No exchange adapters configured")
            return

        if len(self._adapters) == 1:
            async for tick in self._adapters[0].listen():
                yield tick
            return

        queue: asyncio.Queue[MarketData] = asyncio.Queue()
        tasks = [
            asyncio.create_task(self._produce_ticks(adapter, queue))
            for adapter in self._adapters
        ]
        try:
            while True:
                yield await queue.get()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _produce_ticks(
        self,
        adapter: BybitAdapter,
        queue: asyncio.Queue[MarketData],
    ) -> None:
        async for tick in adapter.listen():
            await queue.put(tick)

    async def start(self) -> AsyncIterator[StrategySignal]:
        logger.info(
            "Market scanner started for exchanges=%s symbols=%s",
            ", ".join(self._exchanges),
            ", ".join(self._symbols),
        )
        async for tick in self.listen():
            signals = await self.process_tick(tick)
            for signal in signals:
                yield signal
