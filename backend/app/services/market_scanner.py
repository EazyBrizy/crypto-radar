import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import List, Optional

from app.exchanges.bybit import BybitAdapter, fetch_bybit_klines
from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features, MarketData
from app.schemas.signal import StrategySignal
from app.schemas.trade import VirtualTrade
from app.services.candle_service import CandleService, candle_service
from app.services.feature_engine import FeatureEngine
from app.services.market_persistence import (
    MarketDataPersistenceService,
    market_data_persistence_service,
)
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import (
    stop_loss_hit_event,
    take_profit_hit_event,
    trade_closed_event,
    trade_updated_event,
)
from app.services.virtual_trading import virtual_trading_service
from app.strategies.engine import StrategyEngine

logger = logging.getLogger(__name__)
HEARTBEAT_INTERVAL_SEC = 30.0
HISTORY_WARMUP_LIMIT = 250
OPEN_CANDLE_EVALUATION_INTERVAL_SEC = 2.0
COOPERATIVE_YIELD_EVERY = 2
TRADE_UPDATE_EVENT_MIN_INTERVAL_SEC = 3.0

DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "1000PEPEUSDT",
]


@dataclass
class ScannerRuntimeStats:
    ticks_processed: int = 0
    candles_updated: int = 0
    features_built: int = 0
    strategy_evaluations: int = 0
    signals_found: int = 0
    candles_seeded: int = 0
    last_tick_at: Optional[int] = None
    last_signal_at: Optional[int] = None
    last_exchange: Optional[str] = None
    last_symbol: Optional[str] = None
    last_price: Optional[float] = None
    candle_history: dict[str, int] = field(default_factory=dict)


class MarketScanner:
    """Запускает market-data pipeline для выбранных бирж и торговых пар."""

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        exchanges: Optional[List[str]] = None,
        candle_store: CandleService = candle_service,
        market_persistence: (
            MarketDataPersistenceService | None
        ) = market_data_persistence_service,
    ) -> None:
        self._symbols = list(symbols) if symbols else list(DEFAULT_SYMBOLS)
        self._exchanges = [exchange.lower() for exchange in (exchanges or ["bybit"])]
        self._adapters = self._build_adapters()
        self._candle_store = candle_store
        self._market_persistence = market_persistence
        self._feature_engine = FeatureEngine()
        self._strategy_engine = StrategyEngine()
        self._stats = ScannerRuntimeStats()
        self._last_heartbeat_monotonic = 0.0
        self._last_series_evaluation_monotonic: dict[str, float] = {}
        self._last_trade_update_event_monotonic: dict[str, float] = {}
        self._history_warmed_up = False

    def _build_adapters(self) -> list[BybitAdapter]:
        adapters: list[BybitAdapter] = []
        for exchange in self._exchanges:
            if exchange == "bybit":
                adapters.append(BybitAdapter(self._symbols))
            else:
                logger.warning("Exchange adapter is not implemented: %s", exchange)
        return adapters

    async def process_tick(self, data: MarketData) -> List[StrategySignal]:
        self._stats.ticks_processed += 1
        self._stats.last_tick_at = data.timestamp
        self._stats.last_exchange = data.exchange
        self._stats.last_symbol = data.symbol
        self._stats.last_price = data.price

        await self._persist_market_tick(data)
        updated_trades = virtual_trading_service.update_market_price(data.exchange, data.symbol, data.price)
        if updated_trades:
            await self._publish_trade_updates(updated_trades)
        updated_candles = self._candle_store.update_from_tick(data)
        await self._persist_market_candles(updated_candles)
        self._stats.candles_updated += len(updated_candles)
        signals: list[StrategySignal] = []
        evaluated_candles = 0
        for candle in updated_candles:
            series_key = f"{candle.exchange}:{candle.symbol}:{candle.timeframe}"
            if not self._should_evaluate_series(series_key, candle):
                continue

            candle_series = self._candle_store.list_candles(
                exchange=candle.exchange,
                symbol=candle.symbol,
                timeframe=candle.timeframe,
                include_open=True,
                limit=250,
            )
            self._stats.candle_history[series_key] = len(candle_series)
            features = await asyncio.to_thread(
                self._feature_engine.process_candles,
                candle_series,
            )
            if features is None:
                continue
            await self._persist_market_features(features)
            self._stats.features_built += 1
            self._stats.strategy_evaluations += self._strategy_engine.strategy_count
            signals.extend(await self._strategy_engine.generate_signals(features))
            evaluated_candles += 1
            if evaluated_candles % COOPERATIVE_YIELD_EVERY == 0:
                await asyncio.sleep(0)

        if signals:
            self._stats.signals_found += len(signals)
            self._stats.last_signal_at = data.timestamp
            for signal in signals:
                logger.debug(
                    "Signal detected: %s %s %s %s %s score=%s",
                    signal.exchange,
                    signal.symbol,
                    signal.strategy,
                    signal.direction,
                    signal.timeframe,
                    signal.score,
                )
        self._log_heartbeat()
        await asyncio.sleep(0)
        return signals

    async def _persist_market_tick(self, data: MarketData) -> None:
        if self._market_persistence is None:
            return
        try:
            await asyncio.to_thread(self._market_persistence.persist_tick, data)
        except Exception as exc:
            logger.warning(
                "Market tick persistence failed for %s:%s: %s",
                data.exchange,
                data.symbol,
                exc,
            )

    async def _persist_market_candles(self, candles: list[OHLCVCandle]) -> None:
        if self._market_persistence is None or not candles:
            return
        try:
            await asyncio.to_thread(self._market_persistence.persist_candles, candles)
        except Exception as exc:
            logger.warning("Market candle persistence failed: %s", exc)

    async def _persist_market_features(self, features: Features) -> None:
        if self._market_persistence is None:
            return
        try:
            await asyncio.to_thread(self._market_persistence.persist_features, features)
        except Exception as exc:
            logger.warning(
                "Market feature persistence failed for %s:%s:%s: %s",
                features.exchange,
                features.symbol,
                features.timeframe,
                exc,
            )

    async def _publish_trade_updates(self, trades: list[VirtualTrade]) -> None:
        now = time.monotonic()
        for trade in trades:
            if trade.status == "closed":
                self._last_trade_update_event_monotonic.pop(trade.id, None)
                await realtime_event_broker.publish(trade_closed_event(trade))
                if trade.close_reason == "take_profit":
                    await realtime_event_broker.publish(take_profit_hit_event(trade))
                elif trade.close_reason == "stop_loss":
                    await realtime_event_broker.publish(stop_loss_hit_event(trade))
                continue

            last_published = self._last_trade_update_event_monotonic.get(trade.id)
            if (
                last_published is not None
                and now - last_published < TRADE_UPDATE_EVENT_MIN_INTERVAL_SEC
            ):
                continue

            self._last_trade_update_event_monotonic[trade.id] = now
            await realtime_event_broker.publish(trade_updated_event(trade))

    def _should_evaluate_series(self, series_key: str, candle: OHLCVCandle) -> bool:
        now = time.monotonic()
        last_evaluation = self._last_series_evaluation_monotonic.get(series_key)
        is_new_bucket = candle.trades <= 1

        if (
            not is_new_bucket
            and last_evaluation is not None
            and now - last_evaluation < OPEN_CANDLE_EVALUATION_INTERVAL_SEC
        ):
            return False

        self._last_series_evaluation_monotonic[series_key] = now
        return True

    @property
    def stats(self) -> dict[str, object]:
        return {
            "exchanges": self.exchanges,
            "symbols": self.symbols,
            "timeframes": self._candle_store.timeframes,
            "strategies": self._strategy_engine.strategy_names,
            "ticks_processed": self._stats.ticks_processed,
            "candles_updated": self._stats.candles_updated,
            "features_built": self._stats.features_built,
            "strategy_evaluations": self._stats.strategy_evaluations,
            "signals_found": self._stats.signals_found,
            "candles_seeded": self._stats.candles_seeded,
            "last_tick_at": self._stats.last_tick_at,
            "last_signal_at": self._stats.last_signal_at,
            "last_exchange": self._stats.last_exchange,
            "last_symbol": self._stats.last_symbol,
            "last_price": self._stats.last_price,
            "candle_history": dict(sorted(self._stats.candle_history.items())),
        }

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    @property
    def exchanges(self) -> list[str]:
        return list(self._exchanges)

    def _log_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat_monotonic < HEARTBEAT_INTERVAL_SEC:
            return
        self._last_heartbeat_monotonic = now
        logger.info(
            "Scanner heartbeat: ticks=%s candles=%s features=%s strategy_checks=%s "
            "signals=%s last=%s:%s price=%s",
            self._stats.ticks_processed,
            self._stats.candles_updated,
            self._stats.features_built,
            self._stats.strategy_evaluations,
            self._stats.signals_found,
            self._stats.last_exchange,
            self._stats.last_symbol,
            self._stats.last_price,
        )

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
        await self._warm_up_history()
        logger.info(
            "Market scanner started for exchanges=%s symbols=%s",
            ", ".join(self._exchanges),
            ", ".join(self._symbols),
        )
        async for tick in self.listen():
            signals = await self.process_tick(tick)
            for signal in signals:
                yield signal

    async def _warm_up_history(self) -> None:
        if self._history_warmed_up:
            return
        self._history_warmed_up = True

        if "bybit" not in self._exchanges:
            return

        logger.info(
            "Warming up OHLCV history from Bybit for symbols=%s timeframes=%s",
            ", ".join(self._symbols),
            ", ".join(self._candle_store.timeframes),
        )
        seeded_total = 0
        for symbol in self._symbols:
            for timeframe in self._candle_store.timeframes:
                try:
                    candles = await asyncio.to_thread(
                        fetch_bybit_klines,
                        symbol,
                        timeframe,
                        HISTORY_WARMUP_LIMIT,
                    )
                    seeded = self._candle_store.seed_history(candles)
                    seeded_total += seeded
                    if candles:
                        series_key = f"bybit:{candles[-1].symbol}:{timeframe}"
                        self._stats.candle_history[series_key] = len(
                            self._candle_store.list_candles(
                                exchange="bybit",
                                symbol=candles[-1].symbol,
                                timeframe=timeframe,
                                include_open=False,
                                limit=HISTORY_WARMUP_LIMIT,
                            )
                        )
                except Exception as exc:
                    logger.warning(
                        "Bybit OHLCV warmup failed for %s %s: %s",
                        symbol,
                        timeframe,
                        exc,
                    )
        self._stats.candles_seeded = seeded_total
        logger.info("OHLCV warmup completed: seeded_candles=%s", seeded_total)
