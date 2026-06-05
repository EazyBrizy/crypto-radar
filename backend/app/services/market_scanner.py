import asyncio
import contextlib
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from app.core.config import settings
from app.domain.virtual_trade_status import is_terminal_virtual_trade_status
from app.exchanges.bybit import BybitAdapter, fetch_bybit_klines
from app.schemas.candle import OHLCVCandle
from app.schemas.market import AlphaMarketContext, Features, MarketData, RecentTrade
from app.schemas.signal import StrategySignal
from app.schemas.trade import VirtualTrade
from app.services.alpha_market_context import (
    AlphaMarketContextService,
    alpha_market_context_service,
    recent_trade_from_market_data,
)
from app.services.candle_service import CandleService, candle_service
from app.services.derivative_market import (
    DerivativeMarketSnapshot,
    DerivativeMarketSnapshotService,
    derivative_market_snapshot_service,
)
from app.services.feature_engine import FeatureEngine
from app.services.market_persistence import (
    MarketDataPersistenceService,
    market_data_persistence_service,
)
from app.services.market_quality import MarketQualityData, MarketQualityService, market_quality_service
from app.services.pending_entry_trigger import pending_entry_trigger_service
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import (
    stop_loss_hit_event,
    take_profit_hit_event,
    trade_closed_event,
    trade_updated_event,
)
from app.services.strategy_config_service import StrategyConfigService, strategy_config_service
from app.services.support_resistance import (
    SupportResistanceService,
    SupportResistanceSnapshot,
    support_resistance_service,
)
from app.services.signal_lifecycle import SignalLifecycleWorker, signal_lifecycle_worker
from app.services.trade_invalidation import TradeInvalidationMonitor, trade_invalidation_monitor
from app.services.virtual_trading import virtual_trading_service
from app.workers.signal_outcome_worker import SignalOutcomeWorker, signal_outcome_worker
from app.strategies.engine import StrategyEngine
from app.strategies.pipeline import MarketQualityInput, context_timeframe_for, context_timeframes_for

logger = logging.getLogger(__name__)
HEARTBEAT_INTERVAL_SEC = 30.0
HISTORY_WARMUP_LIMIT = 250
OPEN_CANDLE_EVALUATION_INTERVAL_SEC = 2.0
COOPERATIVE_YIELD_EVERY = 2
TRADE_UPDATE_EVENT_MIN_INTERVAL_SEC = 3.0
RECENT_ALPHA_TRADES_LIMIT = 500

DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "1000PEPEUSDT",
]


class VirtualTradingPriceUpdater(Protocol):
    def update_market_price(self, exchange: str, symbol: str, price: float) -> list[VirtualTrade]:
        ...

    def process_virtual_positions_tick(
        self,
        exchange: str,
        symbol: str,
        market_tick_or_candle: object,
    ) -> list[VirtualTrade]:
        ...


class PendingEntryTriggerProcessor(Protocol):
    def process_market_tick(self, exchange: str, symbol: str, market_tick: MarketData) -> list[object]:
        ...


@dataclass
class ScannerRuntimeStats:
    ticks_processed: int = 0
    candles_updated: int = 0
    features_built: int = 0
    strategy_evaluations: int = 0
    signals_found: int = 0
    candles_seeded: int = 0
    stage: str = "idle"
    warmup_total: int = 0
    warmup_completed: int = 0
    warmup_failed: int = 0
    warmup_started_at: Optional[int] = None
    warmup_finished_at: Optional[int] = None
    last_tick_at: Optional[int] = None
    last_tick_monotonic_at: Optional[float] = None
    last_signal_at: Optional[int] = None
    last_exchange: Optional[str] = None
    last_symbol: Optional[str] = None
    last_price: Optional[float] = None
    last_error: Optional[str] = None
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
        market_quality: MarketQualityService | None = market_quality_service,
        support_resistance: SupportResistanceService | None = support_resistance_service,
        signal_lifecycle: SignalLifecycleWorker | None = signal_lifecycle_worker,
        signal_outcomes: SignalOutcomeWorker | None = signal_outcome_worker,
        trade_invalidation: TradeInvalidationMonitor | None = trade_invalidation_monitor,
        strategy_configs: StrategyConfigService | None = strategy_config_service,
        virtual_trading: VirtualTradingPriceUpdater | None = virtual_trading_service,
        pending_entry_trigger: PendingEntryTriggerProcessor | None = pending_entry_trigger_service,
        derivative_market: DerivativeMarketSnapshotService | None = derivative_market_snapshot_service,
        alpha_market_context: AlphaMarketContextService | None = alpha_market_context_service,
        scan_pairs: Iterable[tuple[str, str]] | None = None,
        universe_source: str = "default",
        universe_warning: str | None = None,
        max_scanner_pairs: int | None = None,
        estimated_strategy_checks: int | None = None,
        warmup_concurrency: int | None = None,
        warmup_timeout_seconds: float | None = None,
        market_data_stale_seconds: float | None = None,
    ) -> None:
        requested_symbols = list(symbols) if symbols else list(DEFAULT_SYMBOLS)
        requested_exchanges = [exchange.lower() for exchange in (exchanges or ["bybit"])]
        explicit_scan_pairs = scan_pairs is not None
        self._scan_pairs = _normalize_scan_pairs(
            scan_pairs
            if explicit_scan_pairs
            else [
                (exchange, symbol)
                for exchange in requested_exchanges
                for symbol in requested_symbols
            ]
        )
        self._scan_pair_keys = set(self._scan_pairs)
        self._symbols_by_exchange = _symbols_by_exchange(self._scan_pairs)
        self._symbols = _unique_symbols(self._scan_pairs) or ([] if explicit_scan_pairs else requested_symbols)
        self._exchanges = _unique_exchanges(self._scan_pairs) or ([] if explicit_scan_pairs else requested_exchanges)
        self._universe_source = universe_source
        self._universe_warning = universe_warning
        self._max_scanner_pairs = max_scanner_pairs
        self._adapters = self._build_adapters()
        self._candle_store = candle_store
        self._market_persistence = market_persistence
        self._market_quality = market_quality
        self._support_resistance = support_resistance
        self._signal_lifecycle = signal_lifecycle
        self._signal_outcomes = signal_outcomes
        self._trade_invalidation = trade_invalidation
        self._strategy_configs = strategy_configs
        self._virtual_trading = virtual_trading
        self._pending_entry_trigger = pending_entry_trigger
        self._derivative_market = derivative_market
        self._alpha_market_context = alpha_market_context
        self._feature_engine = FeatureEngine()
        self._strategy_engine = StrategyEngine()
        self._stats = ScannerRuntimeStats()
        self._warmup_concurrency = max(
            1,
            int(
                warmup_concurrency
                if warmup_concurrency is not None
                else settings.scanner_warmup_concurrency
            ),
        )
        self._warmup_timeout_seconds = max(
            0.1,
            float(
                warmup_timeout_seconds
                if warmup_timeout_seconds is not None
                else settings.scanner_warmup_timeout_seconds
            ),
        )
        self._market_data_stale_seconds = max(
            1.0,
            float(
                market_data_stale_seconds
                if market_data_stale_seconds is not None
                else settings.scanner_market_data_stale_seconds
            ),
        )
        self._last_heartbeat_monotonic = 0.0
        self._last_series_evaluation_monotonic: dict[str, float] = {}
        self._last_trade_update_event_monotonic: dict[str, float] = {}
        self._recent_trades_by_symbol: defaultdict[tuple[str, str], deque[RecentTrade]] = defaultdict(
            lambda: deque(maxlen=RECENT_ALPHA_TRADES_LIMIT)
        )
        self._last_alpha_context_by_series: dict[tuple[str, str, str], AlphaMarketContext] = {}
        self._history_warmed_up = False
        self._history_warmup_in_progress = False
        self._warmup_task: asyncio.Task[None] | None = None
        self._estimated_strategy_checks = (
            estimated_strategy_checks
            if estimated_strategy_checks is not None
            else self._estimate_strategy_checks()
        )

    def _build_adapters(self) -> list[BybitAdapter]:
        adapters: list[BybitAdapter] = []
        for exchange in self._exchanges:
            symbols = self._symbols_by_exchange.get(exchange, [])
            if not symbols:
                continue
            if exchange == "bybit":
                adapters.append(BybitAdapter(symbols))
            else:
                logger.warning("Exchange adapter is not implemented: %s", exchange)
        return adapters

    async def process_tick(self, data: MarketData) -> List[StrategySignal]:
        if not self._can_scan_pair(data.exchange, data.symbol):
            logger.debug(
                "Market tick skipped outside scanner universe: %s:%s",
                data.exchange,
                data.symbol,
            )
            return []

        self._stats.ticks_processed += 1
        self._stats.last_tick_at = data.timestamp
        self._stats.last_tick_monotonic_at = time.monotonic()
        self._stats.last_exchange = data.exchange
        self._stats.last_symbol = data.symbol
        self._stats.last_price = data.price
        if self._stats.stage in {"starting", "warming_up", "stale", "degraded"}:
            self._set_stage("listening")

        self._record_recent_trade(data)
        await self._persist_market_tick(data)
        updated_trades = await self._process_virtual_positions(data)
        if updated_trades:
            await self._publish_trade_updates(updated_trades)
        await self._process_pending_entry_triggers(data)
        updated_candles = self._candle_store.update_from_tick(data)
        await self._persist_market_candles(updated_candles)
        self._stats.candles_updated += len(updated_candles)
        signals: list[StrategySignal] = []
        evaluated_candles = 0
        for candle in updated_candles:
            series_key = f"{candle.exchange}:{candle.symbol}:{candle.timeframe}"
            if candle.trades <= 1:
                await self._process_closed_candle_lifecycle(candle)
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
            derivative_snapshot = await self._derivative_snapshot_for(features)
            features = _features_with_derivative_context(features, derivative_snapshot)
            context_features_by_timeframe = await self._context_features_for(candle)
            primary_context_timeframe = context_timeframe_for(candle.timeframe)
            context_features = (
                context_features_by_timeframe.get(primary_context_timeframe)
                if primary_context_timeframe is not None
                else None
            )
            support_resistance_by_timeframe = await self._support_resistance_for(
                candle,
                context_features_by_timeframe,
            )
            quality = await self._market_quality_for(features)
            alpha_context = await self._alpha_context_for(
                features,
                derivative_snapshot=derivative_snapshot,
            )
            strategy_configs = self._strategy_configs_for(features)
            await self._persist_market_features(features)
            self._stats.features_built += 1
            self._stats.strategy_evaluations += (
                len(strategy_configs)
                if strategy_configs is not None
                else self._strategy_engine.strategy_count
            )
            signals.extend(
                await self._strategy_engine.generate_signals(
                    features,
                    context_features=context_features,
                    context_features_by_timeframe=context_features_by_timeframe,
                    support_resistance_by_timeframe=support_resistance_by_timeframe,
                    market_quality=quality,
                    strategy_configs=strategy_configs,
                    alpha_context=alpha_context,
                )
            )
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

    async def _process_virtual_positions(self, data: MarketData) -> list[VirtualTrade]:
        if self._virtual_trading is None:
            return []
        try:
            processor = getattr(self._virtual_trading, "process_virtual_positions_tick", None)
            if processor is not None:
                return await asyncio.to_thread(
                    processor,
                    data.exchange,
                    data.symbol,
                    data,
                )
            return await asyncio.to_thread(
                self._virtual_trading.update_market_price,
                data.exchange,
                data.symbol,
                data.price,
            )
        except Exception as exc:
            logger.warning(
                "Virtual position lifecycle failed for %s:%s: %s",
                data.exchange,
                data.symbol,
                exc,
            )
            return []

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

    async def _process_pending_entry_triggers(self, data: MarketData) -> None:
        if self._pending_entry_trigger is None:
            return
        try:
            results = await asyncio.to_thread(
                self._pending_entry_trigger.process_market_tick,
                data.exchange,
                data.symbol,
                data,
            )
        except Exception as exc:
            logger.warning(
                "Pending entry trigger failed for %s:%s: %s",
                data.exchange,
                data.symbol,
                exc,
            )
            return
        if results:
            logger.info(
                "Pending entry trigger processed for %s:%s: %s",
                data.exchange,
                data.symbol,
                len(results),
            )

    async def _context_features_for(self, candle: OHLCVCandle) -> dict[str, Features]:
        result: dict[str, Features] = {}
        for context_timeframe in self._context_timeframes_for_signal(candle.timeframe):
            candle_series = self._candle_store.list_candles(
                exchange=candle.exchange,
                symbol=candle.symbol,
                timeframe=context_timeframe,
                include_open=False,
                limit=250,
            )
            if len(candle_series) < 2:
                continue
            features = await asyncio.to_thread(self._feature_engine.process_candles, candle_series)
            if features is not None:
                result[context_timeframe] = features
        return result

    async def _support_resistance_for(
        self,
        candle: OHLCVCandle,
        context_features_by_timeframe: dict[str, Features],
    ) -> dict[str, SupportResistanceSnapshot]:
        if self._support_resistance is None:
            return {}
        result: dict[str, SupportResistanceSnapshot] = {}
        for context_timeframe in self._context_timeframes_for_signal(candle.timeframe):
            candle_series = self._candle_store.list_candles(
                exchange=candle.exchange,
                symbol=candle.symbol,
                timeframe=context_timeframe,
                include_open=False,
                limit=250,
            )
            if len(candle_series) < 5:
                continue
            context_features = context_features_by_timeframe.get(context_timeframe)
            snapshot = await asyncio.to_thread(
                self._support_resistance.build_snapshot,
                candle_series,
                atr=context_features.atr_14 if context_features is not None else None,
            )
            if snapshot is not None:
                result[context_timeframe] = snapshot
        return result

    async def _process_closed_candle_lifecycle(self, candle: OHLCVCandle) -> None:
        candle_series = self._candle_store.list_candles(
            exchange=candle.exchange,
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            include_open=False,
            limit=250,
        )
        if candle_series and self._signal_outcomes is not None:
            try:
                updated_outcomes = await self._signal_outcomes.process_closed_candle(candle_series[-1])
            except Exception as exc:
                logger.warning(
                    "Signal outcome lifecycle failed for %s:%s:%s: %s",
                    candle.exchange,
                    candle.symbol,
                    candle.timeframe,
                    exc,
                )
            else:
                if updated_outcomes:
                    logger.info(
                        "Signal outcomes updated for %s:%s:%s: %s",
                        candle.exchange,
                        candle.symbol,
                        candle.timeframe,
                        len(updated_outcomes),
                    )
        if len(candle_series) < 2:
            return
        features = await asyncio.to_thread(self._feature_engine.process_candles, candle_series)
        if features is None:
            return
        features = await self._enrich_derivative_context(features)
        if self._signal_lifecycle is not None:
            try:
                transitions = await self._signal_lifecycle.process_closed_candle(features)
            except Exception as exc:
                logger.warning(
                    "Signal lifecycle failed for %s:%s:%s: %s",
                    candle.exchange,
                    candle.symbol,
                    candle.timeframe,
                    exc,
                )
            else:
                if transitions:
                    logger.info(
                        "Signal lifecycle transitions for %s:%s:%s: %s",
                        candle.exchange,
                        candle.symbol,
                        candle.timeframe,
                        len(transitions),
                    )
        if self._trade_invalidation is None:
            return
        try:
            await self._trade_invalidation.process_closed_candle(features)
        except Exception as exc:
            logger.warning(
                "Trade invalidation lifecycle failed for %s:%s:%s: %s",
                candle.exchange,
                candle.symbol,
                candle.timeframe,
                exc,
            )

    def _context_timeframes_for_signal(self, timeframe: str) -> tuple[str, ...]:
        result = list(context_timeframes_for(timeframe))
        if self._strategy_configs is None:
            return tuple(result)
        try:
            runtime_configs = self._strategy_configs.runtime_configs()
        except Exception as exc:
            logger.warning("Strategy context timeframe lookup failed: %s", exc)
            return tuple(result)
        for config in runtime_configs:
            if config.timeframes and timeframe not in config.timeframes:
                continue
            for candidate in context_timeframes_for(timeframe, config.params):
                if candidate not in result:
                    result.append(candidate)
        return tuple(result)

    async def _market_quality_for(self, features: Features) -> MarketQualityInput | None:
        if self._market_quality is None:
            return None
        snapshot = await asyncio.to_thread(
            self._market_quality.snapshot,
            exchange=features.exchange,
            symbol=features.symbol,
        )
        return _quality_input(snapshot)

    async def _enrich_derivative_context(self, features: Features) -> Features:
        snapshot = await self._derivative_snapshot_for(features)
        return _features_with_derivative_context(features, snapshot)

    async def _derivative_snapshot_for(self, features: Features) -> DerivativeMarketSnapshot | None:
        if self._derivative_market is None:
            return None
        snapshot = await asyncio.to_thread(
            self._derivative_market.hot_snapshot,
            exchange=features.exchange,
            symbol=features.symbol,
        )
        return snapshot

    async def _alpha_context_for(
        self,
        features: Features,
        *,
        derivative_snapshot: DerivativeMarketSnapshot | None,
    ) -> AlphaMarketContext | None:
        if self._alpha_market_context is None:
            return None
        symbol_key = _symbol_key(features.exchange, features.symbol)
        series_key = (symbol_key[0], symbol_key[1], features.timeframe)
        recent_trades = list(self._recent_trades_by_symbol.get(symbol_key, ()))
        previous_context = self._last_alpha_context_by_series.get(series_key)
        try:
            context = await asyncio.to_thread(
                self._alpha_market_context.build_context,
                features=features,
                recent_trades=recent_trades,
                derivative_snapshot=derivative_snapshot,
                previous_context=previous_context,
            )
        except Exception as exc:
            logger.warning(
                "Alpha context build failed for %s:%s:%s: %s",
                features.exchange,
                features.symbol,
                features.timeframe,
                exc,
            )
            context = AlphaMarketContext(
                symbol=features.symbol,
                timeframe=features.timeframe,
                timestamp=features.timestamp,
                data_quality={
                    "available_sources": [],
                    "missing_sources": ["alpha_context_error"],
                    "warnings": [str(exc)],
                    "source": "alpha_market_context",
                },
            )
        self._last_alpha_context_by_series[series_key] = context
        return context

    def _record_recent_trade(self, data: MarketData) -> None:
        try:
            trade = recent_trade_from_market_data(data)
        except ValueError as exc:
            logger.warning("Recent trade alpha buffer skipped malformed tick: %s", exc)
            return
        self._recent_trades_by_symbol[_symbol_key(data.exchange, data.symbol)].append(trade)

    def _strategy_configs_for(self, features: Features):
        if self._strategy_configs is None:
            return None
        try:
            return self._strategy_configs.configs_for(
                exchange=features.exchange,
                symbol=features.symbol,
                timeframe=features.timeframe,
            )
        except Exception as exc:
            logger.warning(
                "Strategy config lookup failed for %s:%s:%s: %s",
                features.exchange,
                features.symbol,
                features.timeframe,
                exc,
            )
            return None

    async def _publish_trade_updates(self, trades: list[VirtualTrade]) -> None:
        now = time.monotonic()
        for trade in trades:
            if is_terminal_virtual_trade_status(trade.status):
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
        last_tick_age_seconds = self._last_tick_age_seconds()
        stage = self._runtime_stage(last_tick_age_seconds)
        market_stream_connected = self.market_stream_connected
        return {
            "exchanges": self.exchanges,
            "symbols": self.symbols,
            "scan_pairs": [f"{exchange}:{symbol}" for exchange, symbol in self._scan_pairs],
            "scanner_pairs_count": len(self._scan_pairs),
            "scanner_universe_source": self._universe_source,
            "scanner_universe_warning": self._universe_warning,
            "max_scanner_pairs": self._max_scanner_pairs,
            "estimated_strategy_checks": self._estimated_strategy_checks,
            "timeframes": self._candle_store.timeframes,
            "strategies": self._strategy_engine.strategy_names,
            "ticks_processed": self._stats.ticks_processed,
            "candles_updated": self._stats.candles_updated,
            "features_built": self._stats.features_built,
            "strategy_evaluations": self._stats.strategy_evaluations,
            "signals_found": self._stats.signals_found,
            "candles_seeded": self._stats.candles_seeded,
            "stage": stage,
            "warmup_total": self._stats.warmup_total,
            "warmup_completed": self._stats.warmup_completed,
            "warmup_failed": self._stats.warmup_failed,
            "warmup_started_at": self._stats.warmup_started_at,
            "warmup_finished_at": self._stats.warmup_finished_at,
            "last_tick_age_seconds": last_tick_age_seconds,
            "last_error": self._stats.last_error,
            "market_stream_connected": market_stream_connected,
            "ws_connected": market_stream_connected,
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

    @property
    def market_stream_connected(self) -> bool:
        return any(bool(getattr(adapter, "connected", False)) for adapter in self._adapters)

    def record_error(self, exc: BaseException | str) -> None:
        self._stats.last_error = str(exc)
        self._set_stage("error")

    def _can_scan_pair(self, exchange: str, symbol: str) -> bool:
        return _symbol_key(exchange, symbol) in self._scan_pair_keys

    def _estimate_strategy_checks(self) -> int:
        if self._strategy_configs is not None:
            try:
                runtime_configs = self._strategy_configs.runtime_configs()
            except Exception as exc:
                logger.warning("Strategy config lookup failed for scanner estimate: %s", exc)
                runtime_configs = []
            if runtime_configs:
                return sum(
                    1
                    for exchange, symbol in self._scan_pairs
                    for timeframe in self._candle_store.timeframes
                    for config in runtime_configs
                    if config.matches(exchange=exchange, symbol=symbol, timeframe=timeframe)
                )
        return len(self._scan_pairs) * len(self._candle_store.timeframes) * self._strategy_engine.strategy_count

    def _log_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat_monotonic < HEARTBEAT_INTERVAL_SEC:
            return
        self._last_heartbeat_monotonic = now
        logger.info(
            "Scanner heartbeat: pairs=%s timeframes=%s strategy_checks=%s ticks=%s "
            "candles=%s features=%s actual_strategy_checks=%s signals=%s last=%s:%s price=%s",
            len(self._scan_pairs),
            len(self._candle_store.timeframes),
            self._estimated_strategy_checks,
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
        self._stats.last_error = None
        self._set_stage("starting")
        self._set_stage("warming_up")
        self._warmup_task = asyncio.create_task(self._warm_up_history())
        self._warmup_task.add_done_callback(self._handle_warmup_task_done)
        try:
            logger.info(
                "Market scanner started for exchanges=%s symbols=%s",
                ", ".join(self._exchanges),
                ", ".join(self._symbols),
            )
            logger.info(
                "Scanner activity: pairs=%s timeframes=%s strategy_checks=%s universe=%s",
                len(self._scan_pairs),
                len(self._candle_store.timeframes),
                self._estimated_strategy_checks,
                self._universe_source,
            )
            if self._universe_warning:
                logger.warning("Scanner universe warning: %s", self._universe_warning)
            async for tick in self.listen():
                signals = await self.process_tick(tick)
                for signal in signals:
                    yield signal
        except asyncio.CancelledError:
            self._set_stage("stopped")
            raise
        except Exception as exc:
            self.record_error(exc)
            raise
        finally:
            await self._cancel_warmup_task()
            if self._stats.stage not in {"error", "stopped"}:
                self._set_stage("stopped")

    async def _warm_up_history(self) -> None:
        if self._history_warmed_up or self._history_warmup_in_progress:
            return
        self._history_warmup_in_progress = True
        self._stats.warmup_started_at = _epoch_ms()
        self._stats.warmup_finished_at = None
        self._stats.warmup_total = 0
        self._stats.warmup_completed = 0
        self._stats.warmup_failed = 0
        if self._stats.stage in {"idle", "starting"}:
            self._set_stage("warming_up")

        tasks: list[asyncio.Task[None]] = []
        try:
            if "bybit" not in self._exchanges:
                self._stats.warmup_finished_at = _epoch_ms()
                self._history_warmed_up = True
                return

            bybit_symbols = self._symbols_by_exchange.get("bybit", [])
            warmup_items = [
                (symbol, timeframe)
                for symbol in bybit_symbols
                for timeframe in self._candle_store.timeframes
            ]
            self._stats.warmup_total = len(warmup_items)
            logger.info(
                "Warming up OHLCV history from Bybit for symbols=%s timeframes=%s concurrency=%s timeout=%ss",
                ", ".join(bybit_symbols),
                ", ".join(self._candle_store.timeframes),
                self._warmup_concurrency,
                self._warmup_timeout_seconds,
            )
            semaphore = asyncio.Semaphore(self._warmup_concurrency)
            tasks = [
                asyncio.create_task(self._warm_up_history_item(symbol, timeframe, semaphore))
                for symbol, timeframe in warmup_items
            ]
            for task in asyncio.as_completed(tasks):
                await task
            self._history_warmed_up = True
            self._stats.warmup_finished_at = _epoch_ms()
            logger.info(
                "OHLCV warmup completed: seeded_candles=%s failed=%s",
                self._stats.candles_seeded,
                self._stats.warmup_failed,
            )
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            self._history_warmup_in_progress = False

    async def _warm_up_history_item(
        self,
        symbol: str,
        timeframe: str,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            try:
                candles = await asyncio.wait_for(
                    asyncio.to_thread(
                        fetch_bybit_klines,
                        symbol,
                        timeframe,
                        HISTORY_WARMUP_LIMIT,
                    ),
                    timeout=self._warmup_timeout_seconds,
                )
                seeded = self._candle_store.seed_history(candles)
                self._stats.candles_seeded += seeded
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
                self._stats.warmup_failed += 1
                self._stats.last_error = f"Bybit OHLCV warmup failed for {symbol} {timeframe}: {exc}"
                logger.warning(
                    "Bybit OHLCV warmup failed for %s %s: %s",
                    symbol,
                    timeframe,
                    exc,
                )
            finally:
                self._stats.warmup_completed += 1

    async def _cancel_warmup_task(self) -> None:
        task = self._warmup_task
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def _handle_warmup_task_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:
            self._stats.last_error = f"OHLCV warmup failed: {exc}"
            if self._stats.stage in {"listening", "stale"}:
                self._set_stage("degraded")
            else:
                self._set_stage("error")
            logger.exception("OHLCV warmup failed: %s", exc)
        else:
            if self._stats.stage == "warming_up":
                self._set_stage("degraded" if self._stats.warmup_failed else "listening")

    def _set_stage(self, stage: str) -> None:
        self._stats.stage = stage

    def _last_tick_age_seconds(self) -> float | None:
        if self._stats.last_tick_monotonic_at is None:
            return None
        return max(0.0, time.monotonic() - self._stats.last_tick_monotonic_at)

    def _runtime_stage(self, last_tick_age_seconds: float | None) -> str:
        if self._stats.stage in {"idle", "starting", "warming_up", "stopped", "error"}:
            return self._stats.stage
        if (
            last_tick_age_seconds is not None
            and last_tick_age_seconds > self._market_data_stale_seconds
        ):
            return "stale"
        if self._stats.warmup_finished_at is not None and self._stats.warmup_failed > 0:
            return "degraded"
        return self._stats.stage


def _quality_input(snapshot: MarketQualityData) -> MarketQualityInput:
    return MarketQualityInput(
        volume_24h_quote=snapshot.volume_24h_quote,
        spread_bps=snapshot.spread_bps,
        source=snapshot.source,
        warnings=snapshot.warnings,
    )


def _features_with_derivative_context(
    features: Features,
    snapshot: DerivativeMarketSnapshot | None,
) -> Features:
    if snapshot is None:
        return features
    return features.model_copy(
        update={
            "funding_rate": snapshot.funding_rate,
            "oi_change": snapshot.oi_change,
        }
    )


def _symbol_key(exchange: str, symbol: str) -> tuple[str, str]:
    return (exchange.strip().lower(), symbol.strip().upper())


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _normalize_scan_pairs(pairs: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    normalized = [
        _symbol_key(exchange, symbol)
        for exchange, symbol in pairs
        if exchange.strip() and symbol.strip()
    ]
    return tuple(dict.fromkeys(normalized))


def _symbols_by_exchange(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for exchange, symbol in pairs:
        if symbol not in result[exchange]:
            result[exchange].append(symbol)
    return dict(result)


def _unique_symbols(pairs: Iterable[tuple[str, str]]) -> list[str]:
    return list(dict.fromkeys(symbol for _, symbol in pairs))


def _unique_exchanges(pairs: Iterable[tuple[str, str]]) -> list[str]:
    return list(dict.fromkeys(exchange for exchange, _ in pairs))
