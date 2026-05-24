import logging
import statistics
from collections import defaultdict, deque
from typing import Deque, Dict, Iterator, List, Optional, Set

from app.schemas.market import Features, MarketData

logger = logging.getLogger(__name__)

BUFFER_MAXLEN = 200
VOLUME_LOOKBACK = 20
PRICE_LOOKBACK = 20
EMA_SHORT = 20
EMA_MID = 50
EMA_LONG = 200
RSI_LOOKBACK = 14
ATR_LOOKBACK = 14
DONCHIAN_LOOKBACK = 20
PSEUDO_CANDLE_LOOKBACK = 5
ONE_MINUTE_MS = 60_000
VOLUME_EPSILON = 1e-8
VOLUME_SPIKE_MAX = 20.0
VOLUME_SPIKE_ABNORMAL = 10.0
MIN_VOLUME = 0.001


class FeatureEngine:
    """Строит Features из потока MarketData через буферы сделок по символам."""

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

    @staticmethod
    def _ema(values: List[float], period: int) -> Optional[float]:
        if len(values) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for value in values[period:]:
            ema = (value - ema) * multiplier + ema
        return ema

    @staticmethod
    def _sma(values: List[float], period: int) -> Optional[float]:
        if len(values) < period:
            return None
        return sum(values[-period:]) / period

    @staticmethod
    def _rsi(values: List[float], period: int = RSI_LOOKBACK) -> Optional[float]:
        if len(values) <= period:
            return None

        gains: List[float] = []
        losses: List[float] = []
        for previous, current in zip(values[-period - 1 : -1], values[-period:]):
            change = current - previous
            if change >= 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))

        average_loss = sum(losses) / period
        if average_loss == 0:
            return 100.0
        average_gain = sum(gains) / period
        relative_strength = average_gain / average_loss
        return 100 - (100 / (1 + relative_strength))

    @staticmethod
    def _atr(values: List[float], period: int = ATR_LOOKBACK) -> Optional[float]:
        if len(values) <= period:
            return None
        ranges = [
            abs(current - previous)
            for previous, current in zip(values[-period - 1 : -1], values[-period:])
        ]
        return sum(ranges) / period

    @staticmethod
    def _atr_increasing(values: List[float]) -> bool:
        if len(values) <= ATR_LOOKBACK * 2:
            return False
        current = FeatureEngine._atr(values, ATR_LOOKBACK)
        previous = FeatureEngine._atr(values[: -ATR_LOOKBACK // 2], ATR_LOOKBACK)
        return bool(current is not None and previous is not None and current > previous)

    @staticmethod
    def _bb_width(values: List[float], period: int = PRICE_LOOKBACK) -> Optional[float]:
        if len(values) < period:
            return None
        window = values[-period:]
        mean = sum(window) / period
        if mean == 0:
            return None
        deviation = statistics.stdev(window) if len(set(window)) > 1 else 0.0
        upper = mean + 2 * deviation
        lower = mean - 2 * deviation
        return (upper - lower) / mean

    @staticmethod
    def _bb_width_percentile(values: List[float]) -> Optional[float]:
        if len(values) < PRICE_LOOKBACK * 3:
            return None

        widths: List[float] = []
        for index in range(PRICE_LOOKBACK, len(values) + 1):
            width = FeatureEngine._bb_width(values[:index], PRICE_LOOKBACK)
            if width is not None:
                widths.append(width)

        if not widths:
            return None

        current = widths[-1]
        below_or_equal = sum(1 for width in widths if width <= current)
        return below_or_equal / len(widths) * 100

    @staticmethod
    def _adx_proxy(values: List[float]) -> Optional[float]:
        if len(values) <= PRICE_LOOKBACK:
            return None
        window = values[-PRICE_LOOKBACK:]
        directional_move = abs(window[-1] - window[0])
        total_move = sum(
            abs(current - previous)
            for previous, current in zip(window[:-1], window[1:])
        )
        if total_move == 0:
            return 0.0
        return min(100.0, directional_move / total_move * 100)

    @staticmethod
    def _adx_rising(values: List[float]) -> bool:
        if len(values) <= PRICE_LOOKBACK * 2:
            return False
        current = FeatureEngine._adx_proxy(values)
        previous = FeatureEngine._adx_proxy(values[: -PRICE_LOOKBACK // 2])
        return bool(current is not None and previous is not None and current > previous)

    @staticmethod
    def _wick_ratios(values: List[float]) -> tuple[float, float, bool, bool]:
        if not values:
            return 0.0, 0.0, False, False

        window = values[-PSEUDO_CANDLE_LOOKBACK:]
        open_price = window[0]
        close_price = window[-1]
        high_price = max(window)
        low_price = min(window)
        candle_range = high_price - low_price
        if candle_range == 0:
            return 0.0, 0.0, False, False

        upper_wick = high_price - max(open_price, close_price)
        lower_wick = min(open_price, close_price) - low_price
        return (
            upper_wick / candle_range,
            lower_wick / candle_range,
            close_price > open_price,
            close_price < open_price,
        )

    async def process(self, data: MarketData) -> Features:
        try:
            buffer = self._buffers[data.symbol]
            history = list(buffer)
            values = [trade.price for trade in history] + [data.price]
            volumes = [trade.volume for trade in history] + [data.volume]
            previous_values = [trade.price for trade in history]
            recent_window = values[-PSEUDO_CANDLE_LOOKBACK:]

            volume_ma_20 = self._sma(volumes, VOLUME_LOOKBACK) or data.volume
            ema_20 = self._ema(values, EMA_SHORT)
            ema_50 = self._ema(values, EMA_MID)
            ema_200 = self._ema(values, EMA_LONG)
            sma_20 = self._sma(values, PRICE_LOOKBACK)
            rsi_14 = self._rsi(values, RSI_LOOKBACK)
            atr_14 = self._atr(values, ATR_LOOKBACK)
            bb_width = self._bb_width(values, PRICE_LOOKBACK)
            bb_width_percentile = self._bb_width_percentile(values)
            adx = self._adx_proxy(values)
            upper_wick_ratio, lower_wick_ratio, candle_bullish, candle_bearish = (
                self._wick_ratios(values)
            )

            donchian_high = (
                max(previous_values[-DONCHIAN_LOOKBACK:])
                if len(previous_values) >= DONCHIAN_LOOKBACK
                else None
            )
            donchian_low = (
                min(previous_values[-DONCHIAN_LOOKBACK:])
                if len(previous_values) >= DONCHIAN_LOOKBACK
                else None
            )

            if data.symbol not in self._initialized_symbols:
                self._initialized_symbols.add(data.symbol)
                logger.info("Feature buffer initialized for symbol %s", data.symbol)

            features = Features(
                symbol=data.symbol,
                timestamp=data.timestamp,
                price=data.price,
                open=recent_window[0],
                high=max(recent_window),
                low=min(recent_window),
                close=data.price,
                price_change_1m=self._price_change_1m(data, buffer),
                volume=data.volume,
                volume_spike=self._volume_spike(data, buffer),
                volume_ma_20=volume_ma_20,
                volatility=self._volatility(data.symbol, buffer),
                history_length=len(values),
                ema_20=ema_20,
                ema_50=ema_50,
                ema_200=ema_200,
                sma_20=sma_20,
                rsi_14=rsi_14,
                atr_14=atr_14,
                adx=adx,
                adx_rising=self._adx_rising(values),
                bb_width=bb_width,
                bb_width_percentile=bb_width_percentile,
                donchian_high_20=donchian_high,
                donchian_low_20=donchian_low,
                swing_high=donchian_high,
                swing_low=donchian_low,
                candle_bullish=candle_bullish,
                candle_bearish=candle_bearish,
                upper_wick_ratio=upper_wick_ratio,
                lower_wick_ratio=lower_wick_ratio,
                atr_increasing=self._atr_increasing(values),
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
