import logging
import statistics
from collections import defaultdict, deque
from typing import Deque, Dict, Iterator, Optional, Set

from app.models.schemas import Features, MarketData

logger = logging.getLogger(__name__)

BUFFER_MAXLEN = 200
VOLUME_LOOKBACK = 20
PRICE_LOOKBACK = 20
ONE_MINUTE_MS = 60_000
VOLUME_EPSILON = 1e-8
VOLUME_SPIKE_MAX = 20.0
VOLUME_SPIKE_ABNORMAL = 10.0
MIN_VOLUME = 0.001


class FeatureEngine:
    """Derives Features from a stream of MarketData using per-symbol trade buffers."""

    def __init__(self) -> None:
        self._buffers: Dict[str, Deque[MarketData]] = defaultdict(
            lambda: deque(maxlen=BUFFER_MAXLEN)
        )
        self._initialized_symbols: Set[str] = set()
        self._volume_spike_maturity_logged: Set[str] = set()
        self._price_change_maturity_logged: Set[str] = set()
        self._volatility_maturity_logged: Set[str] = set()

    def _trim_buffer(self, buffer: Deque[MarketData], current_timestamp: int) -> None:
        cutoff = current_timestamp - ONE_MINUTE_MS
        while buffer and buffer[0].timestamp < cutoff:
            buffer.popleft()

    def _append_to_buffer(self, buffer: Deque[MarketData], data: MarketData) -> None:
        if buffer and data.timestamp // 1000 == buffer[-1].timestamp // 1000:
            buffer[-1] = data
        else:
            buffer.append(data)
        self._trim_buffer(buffer, data.timestamp)

    @staticmethod
    def _last_n_trades(buffer: Deque[MarketData], n: int) -> Iterator[MarketData]:
        start = len(buffer) - n
        for index in range(start, len(buffer)):
            yield buffer[index]

    def _volume_spike(self, data: MarketData, buffer: Deque[MarketData]) -> float:
        if data.volume < MIN_VOLUME:
            return 0.0

        if len(buffer) < VOLUME_LOOKBACK:
            if data.symbol not in self._volume_spike_maturity_logged:
                self._volume_spike_maturity_logged.add(data.symbol)
                logger.info("Not enough data for volume spike")
            return 1.0

        average_volume = (
            sum(trade.volume for trade in self._last_n_trades(buffer, VOLUME_LOOKBACK))
            / VOLUME_LOOKBACK
        )
        volume_spike = data.volume / (average_volume + VOLUME_EPSILON)

        if volume_spike > VOLUME_SPIKE_ABNORMAL:
            logger.info(
                "Abnormal volume spike detected for %s: %.4f",
                data.symbol,
                volume_spike,
            )

        if volume_spike > VOLUME_SPIKE_MAX:
            volume_spike = VOLUME_SPIKE_MAX

        return volume_spike

    def _price_change_1m(self, data: MarketData, buffer: Deque[MarketData]) -> float:
        target_time = data.timestamp - ONE_MINUTE_MS
        past_trade: Optional[MarketData] = None

        if not buffer or buffer[0].timestamp > target_time:
            if data.symbol not in self._price_change_maturity_logged:
                self._price_change_maturity_logged.add(data.symbol)
                logger.info("Not enough data for price_change_1m")
            return 0.0

        for trade in reversed(buffer):
            if trade.timestamp <= target_time:
                past_trade = trade
                break

        if past_trade is None or past_trade.price == 0:
            return 0.0

        return (data.price - past_trade.price) / past_trade.price

    def _volatility(self, symbol: str, buffer: Deque[MarketData]) -> float:
        if len(buffer) < PRICE_LOOKBACK:
            if symbol not in self._volatility_maturity_logged:
                self._volatility_maturity_logged.add(symbol)
                logger.info("Buffer too small for volatility")
            return 0.0

        start = len(buffer) - PRICE_LOOKBACK
        min_price = buffer[start].price
        max_price = min_price

        for index in range(start + 1, len(buffer)):
            price = buffer[index].price
            if price < min_price:
                min_price = price
            elif price > max_price:
                max_price = price

        if min_price == max_price:
            return 0.0

        prices = [buffer[index].price for index in range(start, len(buffer))]
        return statistics.stdev(prices)

    async def process(self, data: MarketData) -> Features:
        try:
            buffer = self._buffers[data.symbol]

            if data.symbol not in self._initialized_symbols:
                self._initialized_symbols.add(data.symbol)
                logger.info("Feature buffer initialized for symbol %s", data.symbol)

            features = Features(
                symbol=data.symbol,
                timestamp=data.timestamp,
                price=data.price,
                price_change_1m=self._price_change_1m(data, buffer),
                volume=data.volume,
                volume_spike=self._volume_spike(data, buffer),
                volatility=self._volatility(data.symbol, buffer),
                oi_change=None,
                funding_rate=None,
            )

            self._append_to_buffer(buffer, data)
            return features
        except Exception as exc:
            logger.exception(
                "Error processing features for %s: %s",
                data.symbol,
                exc,
            )
            raise
