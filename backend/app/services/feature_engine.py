import logging
import statistics
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, Iterable, Iterator, List, Optional, Set

from app.schemas.candle import OHLCVCandle
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
ONE_MINUTE_MS = 60_000
VOLUME_EPSILON = 1e-8
VOLUME_SPIKE_MAX = 20.0
VOLUME_SPIKE_ABNORMAL = 10.0
MIN_VOLUME = 0.001


class FeatureEngine:
    """Строит derived Features из OHLCV-свечей и сохраняет tick-fallback для ранних этапов."""

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

    def _volatility(self, symbol: str, values: Iterable[float]) -> float:
        prices = list(values)
        if len(prices) < PRICE_LOOKBACK:
            if symbol not in self._volatility_maturity_logged:
                self._volatility_maturity_logged.add(symbol)
                logger.debug("Buffer too small for volatility; warming up %s", symbol)
            return 0.0

        window = prices[-PRICE_LOOKBACK:]
        if len(set(window)) <= 1:
            return 0.0
        return statistics.stdev(window)

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
    def _true_ranges(candles: List[OHLCVCandle]) -> List[float]:
        ranges: List[float] = []
        for previous, current in zip(candles[:-1], candles[1:]):
            ranges.append(
                max(
                    current.high - current.low,
                    abs(current.high - previous.close),
                    abs(current.low - previous.close),
                )
            )
        return ranges

    @staticmethod
    def _atr_from_candles(
        candles: List[OHLCVCandle],
        period: int = ATR_LOOKBACK,
    ) -> Optional[float]:
        if len(candles) <= period:
            return None
        true_ranges = FeatureEngine._true_ranges(candles)
        if len(true_ranges) < period:
            return None
        return sum(true_ranges[-period:]) / period

    @staticmethod
    def _atr_from_values(values: List[float], period: int = ATR_LOOKBACK) -> Optional[float]:
        if len(values) <= period:
            return None
        ranges = [
            abs(current - previous)
            for previous, current in zip(values[-period - 1 : -1], values[-period:])
        ]
        return sum(ranges) / period

    @staticmethod
    def _atr_increasing(candles: List[OHLCVCandle]) -> bool:
        if len(candles) <= ATR_LOOKBACK * 2:
            return False
        current = FeatureEngine._atr_from_candles(candles, ATR_LOOKBACK)
        previous = FeatureEngine._atr_from_candles(candles[: -ATR_LOOKBACK // 2], ATR_LOOKBACK)
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
    def _wick_ratios(candle: OHLCVCandle) -> tuple[float, float, bool, bool]:
        candle_range = candle.high - candle.low
        if candle_range == 0:
            return 0.0, 0.0, False, False

        upper_wick = candle.high - max(candle.open, candle.close)
        lower_wick = min(candle.open, candle.close) - candle.low
        return (
            upper_wick / candle_range,
            lower_wick / candle_range,
            candle.close > candle.open,
            candle.close < candle.open,
        )

    @staticmethod
    def _session_vwap(candles: List[OHLCVCandle]) -> Optional[float]:
        if not candles:
            return None
        latest = candles[-1]
        if latest.timeframe == "1d":
            return None
        latest_session = datetime.fromtimestamp(latest.open_time / 1000, tz=timezone.utc).date()
        numerator = 0.0
        denominator = 0.0
        for candle in candles:
            candle_session = datetime.fromtimestamp(candle.open_time / 1000, tz=timezone.utc).date()
            if candle_session != latest_session:
                continue
            if candle.volume <= 0:
                continue
            typical_price = (candle.high + candle.low + candle.close) / 3
            numerator += typical_price * candle.volume
            denominator += candle.volume
        if denominator <= 0:
            return None
        return numerator / denominator

    @staticmethod
    def _rolling_vwap(values: List[float], volumes: List[float], period: int = PRICE_LOOKBACK) -> Optional[float]:
        if not values or not volumes:
            return None
        price_window = values[-period:]
        volume_window = volumes[-period:]
        denominator = sum(volume for volume in volume_window if volume > 0)
        if denominator <= 0:
            return None
        numerator = sum(price * max(volume, 0.0) for price, volume in zip(price_window, volume_window))
        return numerator / denominator

    def process_candles(self, candles: List[OHLCVCandle]) -> Optional[Features]:
        if not candles:
            return None

        ordered = sorted(candles, key=lambda candle: candle.open_time)
        latest = ordered[-1]
        closes = [candle.close for candle in ordered]
        volumes = [candle.volume for candle in ordered]
        previous_candles = ordered[:-1]
        previous_closes = closes[:-1]
        volume_ma_20 = self._sma(volumes, VOLUME_LOOKBACK) or latest.volume
        volume_spike = latest.volume / (volume_ma_20 + VOLUME_EPSILON)
        volume_spike = min(volume_spike, VOLUME_SPIKE_MAX)
        upper_wick_ratio, lower_wick_ratio, candle_bullish, candle_bearish = (
            self._wick_ratios(latest)
        )

        donchian_high = (
            max(candle.high for candle in previous_candles[-DONCHIAN_LOOKBACK:])
            if len(previous_candles) >= DONCHIAN_LOOKBACK
            else None
        )
        donchian_low = (
            min(candle.low for candle in previous_candles[-DONCHIAN_LOOKBACK:])
            if len(previous_candles) >= DONCHIAN_LOOKBACK
            else None
        )
        previous_close = previous_closes[-1] if previous_closes else latest.open
        price_change = (
            (latest.close - previous_close) / previous_close
            if previous_close
            else 0.0
        )

        return Features(
            exchange=latest.exchange,
            symbol=latest.symbol,
            timeframe=latest.timeframe,
            timestamp=latest.close_time,
            price=latest.close,
            open=latest.open,
            high=latest.high,
            low=latest.low,
            close=latest.close,
            price_change_1m=price_change,
            volume=latest.volume,
            volume_spike=volume_spike,
            volume_ma_20=volume_ma_20,
            volatility=self._volatility(latest.symbol, closes),
            history_length=len(ordered),
            ema_20=self._ema(closes, EMA_SHORT),
            ema_50=self._ema(closes, EMA_MID),
            ema_200=self._ema(closes, EMA_LONG),
            sma_20=self._sma(closes, PRICE_LOOKBACK),
            vwap=self._session_vwap(ordered),
            rsi_14=self._rsi(closes, RSI_LOOKBACK),
            atr_14=self._atr_from_candles(ordered, ATR_LOOKBACK),
            adx=self._adx_proxy(closes),
            adx_rising=self._adx_rising(closes),
            bb_width=self._bb_width(closes, PRICE_LOOKBACK),
            bb_width_percentile=self._bb_width_percentile(closes),
            donchian_high_20=donchian_high,
            donchian_low_20=donchian_low,
            swing_high=donchian_high,
            swing_low=donchian_low,
            candle_bullish=candle_bullish,
            candle_bearish=candle_bearish,
            upper_wick_ratio=upper_wick_ratio,
            lower_wick_ratio=lower_wick_ratio,
            atr_increasing=self._atr_increasing(ordered),
            oi_change=None,
            funding_rate=None,
        )

    async def process(self, data: MarketData) -> Features:
        try:
            buffer_key = f"{data.exchange}:{data.symbol}"
            buffer = self._buffers[buffer_key]
            history = list(buffer)
            values = [trade.price for trade in history] + [data.price]
            volumes = [trade.volume for trade in history] + [data.volume]
            recent_window = values[-5:]

            volume_ma_20 = self._sma(volumes, VOLUME_LOOKBACK) or data.volume
            ema_20 = self._ema(values, EMA_SHORT)
            ema_50 = self._ema(values, EMA_MID)
            ema_200 = self._ema(values, EMA_LONG)
            sma_20 = self._sma(values, PRICE_LOOKBACK)
            rsi_14 = self._rsi(values, RSI_LOOKBACK)
            atr_14 = self._atr_from_values(values, ATR_LOOKBACK)
            bb_width = self._bb_width(values, PRICE_LOOKBACK)
            bb_width_percentile = self._bb_width_percentile(values)
            adx = self._adx_proxy(values)

            pseudo_open = recent_window[0]
            pseudo_close = data.price
            pseudo_high = max(recent_window)
            pseudo_low = min(recent_window)
            candle_range = pseudo_high - pseudo_low
            if candle_range:
                upper_wick_ratio = (pseudo_high - max(pseudo_open, pseudo_close)) / candle_range
                lower_wick_ratio = (min(pseudo_open, pseudo_close) - pseudo_low) / candle_range
            else:
                upper_wick_ratio = 0.0
                lower_wick_ratio = 0.0

            previous_values = values[:-1]
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

            if buffer_key not in self._initialized_symbols:
                self._initialized_symbols.add(buffer_key)
                logger.info(
                    "Feature buffer initialized for %s %s",
                    data.exchange,
                    data.symbol,
                )

            features = Features(
                exchange=data.exchange,
                symbol=data.symbol,
                timeframe="stream",
                timestamp=data.timestamp,
                price=data.price,
                open=pseudo_open,
                high=pseudo_high,
                low=pseudo_low,
                close=data.price,
                price_change_1m=self._price_change_1m(data, buffer),
                volume=data.volume,
                volume_spike=self._volume_spike(data, buffer),
                volume_ma_20=volume_ma_20,
                volatility=self._volatility(data.symbol, values),
                history_length=len(values),
                ema_20=ema_20,
                ema_50=ema_50,
                ema_200=ema_200,
                sma_20=sma_20,
                vwap=self._rolling_vwap(values, volumes),
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
                candle_bullish=pseudo_close > pseudo_open,
                candle_bearish=pseudo_close < pseudo_open,
                upper_wick_ratio=upper_wick_ratio,
                lower_wick_ratio=lower_wick_ratio,
                atr_increasing=False,
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
