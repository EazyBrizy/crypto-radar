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
ATR_SMA_LOOKBACK = 50
DONCHIAN_LOOKBACK = 20
RANGE_CONTRACTION_LOOKBACK = 50
SWING_MIN_LOOKBACK = 20
SWING_MAX_LOOKBACK = 50
SWING_FRACTAL_WINDOW = 2
SWING_TOUCH_TOLERANCE_ATR = 0.25
EMA200_CHOP_LOOKBACK = 50
EMA200_SLOPE_LOOKBACK = 20
EMA200_NEAR_ATR_MULTIPLIER = 0.5
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
    def _ema_series(values: List[float], period: int) -> List[Optional[float]]:
        series: List[Optional[float]] = [None] * len(values)
        if len(values) < period:
            return series
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        series[period - 1] = ema
        for index in range(period, len(values)):
            ema = (values[index] - ema) * multiplier + ema
            series[index] = ema
        return series

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
    def _atr_series_from_candles(
        candles: List[OHLCVCandle],
        period: int = ATR_LOOKBACK,
    ) -> List[Optional[float]]:
        series: List[Optional[float]] = [None] * len(candles)
        if len(candles) <= period:
            return series
        true_ranges = FeatureEngine._true_ranges(candles)
        if len(true_ranges) < period:
            return series
        for tr_index in range(period - 1, len(true_ranges)):
            candle_index = tr_index + 1
            series[candle_index] = sum(true_ranges[tr_index - period + 1 : tr_index + 1]) / period
        return series

    @staticmethod
    def _atr_sma_from_series(
        atr_series: List[Optional[float]],
        period: int = ATR_SMA_LOOKBACK,
    ) -> Optional[float]:
        values = [value for value in atr_series if value is not None]
        if len(values) < period:
            return None
        return sum(values[-period:]) / period

    @staticmethod
    def _range_compression_stats(
        candles: List[OHLCVCandle],
        period: int = DONCHIAN_LOOKBACK,
        lookback: int = RANGE_CONTRACTION_LOOKBACK,
    ) -> tuple[Optional[float], Optional[float]]:
        previous_candles = candles[:-1]
        if len(previous_candles) < period:
            return None, None

        rolling_ranges: list[float] = []
        for end_index in range(period, len(previous_candles) + 1):
            window = previous_candles[end_index - period : end_index]
            rolling_ranges.append(max(candle.high for candle in window) - min(candle.low for candle in window))

        if not rolling_ranges:
            return None, None
        current_range = rolling_ranges[-1]
        comparison_window = rolling_ranges[-lookback:]
        if not comparison_window:
            return current_range, None
        return current_range, sum(comparison_window) / len(comparison_window)

    @staticmethod
    def _fractal_swing_levels(
        candles: List[OHLCVCandle],
        atr: float | None,
    ) -> tuple[
        Optional[float],
        Optional[float],
        int,
        int,
        Optional[float],
        Optional[float],
        Optional[int],
        Optional[int],
    ]:
        previous_candles = candles[:-1]
        if len(previous_candles) < SWING_MIN_LOOKBACK:
            return None, None, 0, 0, None, None, None, None

        lookback = previous_candles[-SWING_MAX_LOOKBACK:]
        offset = len(previous_candles) - len(lookback)
        latest_close = candles[-1].close if candles else previous_candles[-1].close
        tolerance = max(
            (atr if atr is not None and atr > 0 else abs(latest_close) * 0.005) * SWING_TOUCH_TOLERANCE_ATR,
            abs(latest_close) * 0.0005,
        )
        average_volume = FeatureEngine._average_volume_from_candles(lookback)

        high_candidates: list[tuple[float, int, int, float | None]] = []
        low_candidates: list[tuple[float, int, int, float | None]] = []
        window = SWING_FRACTAL_WINDOW
        for local_index in range(window, len(lookback) - window):
            candle = lookback[local_index]
            neighbors = [
                *lookback[local_index - window:local_index],
                *lookback[local_index + 1:local_index + window + 1],
            ]
            if not neighbors:
                continue
            global_index = offset + local_index
            if (
                candle.high >= max(item.high for item in neighbors)
                and candle.high > lookback[local_index - 1].high
                and candle.high > lookback[local_index + 1].high
            ):
                touches, volume_score, last_touch_index = FeatureEngine._level_touch_stats(
                    lookback,
                    price=candle.high,
                    kind="high",
                    tolerance=tolerance,
                    average_volume=average_volume,
                    offset=offset,
                )
                high_candidates.append((candle.high, max(touches, 1), last_touch_index or global_index, volume_score))
            if (
                candle.low <= min(item.low for item in neighbors)
                and candle.low < lookback[local_index - 1].low
                and candle.low < lookback[local_index + 1].low
            ):
                touches, volume_score, last_touch_index = FeatureEngine._level_touch_stats(
                    lookback,
                    price=candle.low,
                    kind="low",
                    tolerance=tolerance,
                    average_volume=average_volume,
                    offset=offset,
                )
                low_candidates.append((candle.low, max(touches, 1), last_touch_index or global_index, volume_score))

        high_fallback = FeatureEngine._equal_level_fallback(
            lookback,
            kind="high",
            tolerance=tolerance,
            average_volume=average_volume,
            offset=offset,
        )
        low_fallback = FeatureEngine._equal_level_fallback(
            lookback,
            kind="low",
            tolerance=tolerance,
            average_volume=average_volume,
            offset=offset,
        )
        if high_fallback is not None and not high_candidates:
            high_candidates.append(high_fallback)
        if low_fallback is not None and not low_candidates:
            low_candidates.append(low_fallback)

        high = FeatureEngine._select_swing_level(high_candidates, latest_index=len(previous_candles) - 1)
        low = FeatureEngine._select_swing_level(low_candidates, latest_index=len(previous_candles) - 1)
        return (
            high[0] if high is not None else None,
            low[0] if low is not None else None,
            high[1] if high is not None else 0,
            low[1] if low is not None else 0,
            high[2] if high is not None else None,
            low[2] if low is not None else None,
            high[3] if high is not None else None,
            low[3] if low is not None else None,
        )

    @staticmethod
    def _level_touch_stats(
        candles: List[OHLCVCandle],
        *,
        price: float,
        kind: str,
        tolerance: float,
        average_volume: float,
        offset: int,
    ) -> tuple[int, float | None, int | None]:
        touches: list[tuple[int, OHLCVCandle]] = []
        for local_index, candle in enumerate(candles):
            level_price = candle.high if kind == "high" else candle.low
            if abs(level_price - price) <= tolerance:
                touches.append((offset + local_index, candle))
        if not touches:
            return 0, None, None
        volume_score = (
            sum(candle.volume for _, candle in touches) / len(touches) / average_volume
            if average_volume > 0
            else None
        )
        return len(touches), volume_score, touches[-1][0]

    @staticmethod
    def _equal_level_fallback(
        candles: List[OHLCVCandle],
        *,
        kind: str,
        tolerance: float,
        average_volume: float,
        offset: int,
    ) -> tuple[float, int, int, float | None] | None:
        if len(candles) < DONCHIAN_LOOKBACK:
            return None
        window = candles[-DONCHIAN_LOOKBACK:]
        price = max(candle.high for candle in window) if kind == "high" else min(candle.low for candle in window)
        touches, volume_score, last_touch_index = FeatureEngine._level_touch_stats(
            candles,
            price=price,
            kind=kind,
            tolerance=tolerance,
            average_volume=average_volume,
            offset=offset,
        )
        if touches < 2 or last_touch_index is None:
            return None
        return price, touches, last_touch_index, volume_score

    @staticmethod
    def _select_swing_level(
        candidates: list[tuple[float, int, int, float | None]],
        *,
        latest_index: int,
    ) -> tuple[float, int, float | None, int] | None:
        if not candidates:
            return None

        def level_score(candidate: tuple[float, int, int, float | None]) -> float:
            _, touches, index, volume_score = candidate
            age = max(0, latest_index - index)
            freshness = max(0.0, 1.0 - age / max(SWING_MAX_LOOKBACK, 1))
            volume_component = min(volume_score or 1.0, 2.5)
            return touches * 20 + freshness * 10 + volume_component * 5

        price, touches, index, volume_score = max(candidates, key=level_score)
        return price, touches, None if volume_score is None else round(volume_score, 3), max(0, latest_index - index)

    @staticmethod
    def _average_volume_from_candles(candles: List[OHLCVCandle]) -> float:
        volumes = [max(candle.volume, 0.0) for candle in candles]
        return sum(volumes) / len(volumes) if volumes else 0.0

    @staticmethod
    def _adx_series_from_candles(
        candles: List[OHLCVCandle],
        period: int = ATR_LOOKBACK,
    ) -> List[Optional[float]]:
        series: List[Optional[float]] = [None] * len(candles)
        if len(candles) <= period * 2:
            return series

        true_ranges: list[float] = []
        plus_dm: list[float] = []
        minus_dm: list[float] = []
        for previous, current in zip(candles[:-1], candles[1:]):
            high_move = current.high - previous.high
            low_move = previous.low - current.low
            true_ranges.append(
                max(
                    current.high - current.low,
                    abs(current.high - previous.close),
                    abs(current.low - previous.close),
                )
            )
            plus_dm.append(high_move if high_move > low_move and high_move > 0 else 0.0)
            minus_dm.append(low_move if low_move > high_move and low_move > 0 else 0.0)

        smoothed_tr = sum(true_ranges[:period])
        smoothed_plus_dm = sum(plus_dm[:period])
        smoothed_minus_dm = sum(minus_dm[:period])
        dx_values: list[float] = []
        adx: float | None = None

        for tr_index in range(period - 1, len(true_ranges)):
            if tr_index >= period:
                smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[tr_index]
                smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dm[tr_index]
                smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dm[tr_index]

            if smoothed_tr <= 0:
                dx = 0.0
            else:
                plus_di = 100 * smoothed_plus_dm / smoothed_tr
                minus_di = 100 * smoothed_minus_dm / smoothed_tr
                denominator = plus_di + minus_di
                dx = 0.0 if denominator <= 0 else 100 * abs(plus_di - minus_di) / denominator

            dx_values.append(dx)
            candle_index = tr_index + 1
            if len(dx_values) < period:
                continue
            if adx is None:
                adx = sum(dx_values[-period:]) / period
            else:
                adx = (adx * (period - 1) + dx) / period
            series[candle_index] = adx

        return series

    @staticmethod
    def _adx_stats(adx_series: List[Optional[float]]) -> tuple[Optional[float], bool, Optional[float], int]:
        values = [value for value in adx_series if value is not None]
        if not values:
            return None, False, None, 0

        latest = values[-1]
        rising_bars = 0
        for current, previous in zip(reversed(values[1:]), reversed(values[:-1])):
            if current > previous:
                rising_bars += 1
                if rising_bars >= 5:
                    break
                continue
            break

        slope_5 = latest - values[-6] if len(values) >= 6 else None
        return latest, bool(rising_bars >= 3 and (slope_5 is None or slope_5 > 0)), slope_5, rising_bars

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
    def _ema200_chop_metrics(
        closes: List[float],
        ema_200_series: List[Optional[float]],
        atr: float | None,
    ) -> tuple[int, Optional[float], Optional[float], Optional[float]]:
        window_indexes = [
            index
            for index in range(max(0, len(closes) - EMA200_CHOP_LOOKBACK), len(closes))
            if ema_200_series[index] is not None
        ]
        if not window_indexes:
            return 0, None, None, None

        signs: list[int] = []
        near_count = 0
        near_threshold = (atr or 0.0) * EMA200_NEAR_ATR_MULTIPLIER if atr is not None and atr > 0 else None
        for index in window_indexes:
            ema_200 = ema_200_series[index]
            if ema_200 is None:
                continue
            diff = closes[index] - ema_200
            if diff > 0:
                signs.append(1)
            elif diff < 0:
                signs.append(-1)
            else:
                signs.append(0)
            if near_threshold is not None and abs(diff) <= near_threshold:
                near_count += 1

        cross_count = 0
        previous_sign = 0
        for sign in signs:
            if sign == 0:
                continue
            if previous_sign and sign != previous_sign:
                cross_count += 1
            previous_sign = sign

        near_ratio = near_count / len(window_indexes) if near_threshold is not None else None
        latest_ema = ema_200_series[-1]
        past_index = len(ema_200_series) - EMA200_SLOPE_LOOKBACK - 1
        past_ema = ema_200_series[past_index] if past_index >= 0 else None
        slope_atr = (
            abs(latest_ema - past_ema) / atr
            if latest_ema is not None and past_ema is not None and atr is not None and atr > 0
            else None
        )
        cross_score = min(50.0, cross_count * 12.5)
        near_score = min(30.0, (near_ratio or 0.0) / 0.35 * 30.0) if near_ratio is not None else 0.0
        flat_score = max(0.0, (0.25 - slope_atr) / 0.25 * 20.0) if slope_atr is not None else 0.0
        return cross_count, near_ratio, slope_atr, min(100.0, cross_score + near_score + flat_score)

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
    def _session_high_low(candles: List[OHLCVCandle]) -> tuple[Optional[float], Optional[float]]:
        if not candles:
            return None, None
        latest = candles[-1]
        if latest.timeframe == "1d":
            return None, None
        latest_session = datetime.fromtimestamp(latest.open_time / 1000, tz=timezone.utc).date()
        session_candles = [
            candle
            for candle in candles
            if datetime.fromtimestamp(candle.open_time / 1000, tz=timezone.utc).date() == latest_session
        ]
        if not session_candles:
            return None, None
        return max(candle.high for candle in session_candles), min(candle.low for candle in session_candles)

    @staticmethod
    def _previous_day_high_low(candles: List[OHLCVCandle]) -> tuple[Optional[float], Optional[float]]:
        if len(candles) < 2:
            return None, None
        latest = candles[-1]
        latest_session = datetime.fromtimestamp(latest.open_time / 1000, tz=timezone.utc).date()
        previous_sessions = sorted(
            {
                datetime.fromtimestamp(candle.open_time / 1000, tz=timezone.utc).date()
                for candle in candles[:-1]
                if datetime.fromtimestamp(candle.open_time / 1000, tz=timezone.utc).date() < latest_session
            }
        )
        if not previous_sessions:
            return None, None
        previous_session = previous_sessions[-1]
        previous_candles = [
            candle
            for candle in candles
            if datetime.fromtimestamp(candle.open_time / 1000, tz=timezone.utc).date() == previous_session
        ]
        if not previous_candles:
            return None, None
        return max(candle.high for candle in previous_candles), min(candle.low for candle in previous_candles)

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
        ema_200_series = self._ema_series(closes, EMA_LONG)
        previous_candles = ordered[:-1]
        previous_closes = closes[:-1]
        previous_candle = previous_candles[-1] if previous_candles else None
        volume_ma_20 = self._sma(volumes, VOLUME_LOOKBACK) or latest.volume
        volume_spike = latest.volume / (volume_ma_20 + VOLUME_EPSILON)
        volume_spike = min(volume_spike, VOLUME_SPIKE_MAX)
        atr_series = self._atr_series_from_candles(ordered, ATR_LOOKBACK)
        atr_14 = atr_series[-1] if atr_series else None
        atr_sma_50 = self._atr_sma_from_series(atr_series, ATR_SMA_LOOKBACK)
        range_20, range_50_average = self._range_compression_stats(ordered)
        adx, adx_rising, adx_slope_5, adx_rising_bars = self._adx_stats(
            self._adx_series_from_candles(ordered, ATR_LOOKBACK)
        )
        ema_200_cross_count_50, ema_200_near_ratio_50, ema_200_slope_atr_20, ema_200_chop_score = (
            self._ema200_chop_metrics(closes, ema_200_series, atr_14)
        )
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
        (
            swing_high,
            swing_low,
            swing_high_touch_count,
            swing_low_touch_count,
            swing_high_volume_score,
            swing_low_volume_score,
            swing_high_age_candles,
            swing_low_age_candles,
        ) = self._fractal_swing_levels(ordered, atr_14)
        session_high, session_low = self._session_high_low(ordered)
        previous_day_high, previous_day_low = self._previous_day_high_low(ordered)
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
            candle_state="closed" if latest.is_closed else "open",
            price=latest.close,
            open=latest.open,
            high=latest.high,
            low=latest.low,
            close=latest.close,
            price_change_1m=price_change,
            previous_open=previous_candle.open if previous_candle is not None else None,
            previous_high=previous_candle.high if previous_candle is not None else None,
            previous_low=previous_candle.low if previous_candle is not None else None,
            previous_close=previous_candle.close if previous_candle is not None else None,
            previous_volume=previous_candle.volume if previous_candle is not None else None,
            volume=latest.volume,
            volume_spike=volume_spike,
            volume_ma_20=volume_ma_20,
            volatility=self._volatility(latest.symbol, closes),
            history_length=len(ordered),
            ema_20=self._ema(closes, EMA_SHORT),
            ema_50=self._ema(closes, EMA_MID),
            ema_200=ema_200_series[-1],
            sma_20=self._sma(closes, PRICE_LOOKBACK),
            vwap=self._session_vwap(ordered),
            session_high=session_high,
            session_low=session_low,
            previous_day_high=previous_day_high,
            previous_day_low=previous_day_low,
            rsi_14=self._rsi(closes, RSI_LOOKBACK),
            atr_14=atr_14,
            atr_sma_50=atr_sma_50,
            adx=adx,
            adx_rising=adx_rising,
            adx_slope_5=adx_slope_5,
            adx_rising_bars=adx_rising_bars,
            ema_200_cross_count_50=ema_200_cross_count_50,
            ema_200_near_ratio_50=ema_200_near_ratio_50,
            ema_200_slope_atr_20=ema_200_slope_atr_20,
            ema_200_chop_score=ema_200_chop_score,
            bb_width=self._bb_width(closes, PRICE_LOOKBACK),
            bb_width_percentile=self._bb_width_percentile(closes),
            donchian_high_20=donchian_high,
            donchian_low_20=donchian_low,
            range_20=range_20,
            range_50_average=range_50_average,
            range_20_atr=range_20 / atr_14 if range_20 is not None and atr_14 is not None and atr_14 > 0 else None,
            swing_high=swing_high,
            swing_low=swing_low,
            swing_high_touch_count=swing_high_touch_count,
            swing_low_touch_count=swing_low_touch_count,
            swing_high_volume_score=swing_high_volume_score,
            swing_low_volume_score=swing_low_volume_score,
            swing_high_age_candles=swing_high_age_candles,
            swing_low_age_candles=swing_low_age_candles,
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
            previous_price = previous_values[-1] if previous_values else None
            previous_volume = volumes[-2] if len(volumes) >= 2 else None
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
                candle_state="open",
                price=data.price,
                open=pseudo_open,
                high=pseudo_high,
                low=pseudo_low,
                close=data.price,
                price_change_1m=self._price_change_1m(data, buffer),
                previous_open=previous_price,
                previous_high=previous_price,
                previous_low=previous_price,
                previous_close=previous_price,
                previous_volume=previous_volume,
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
                atr_sma_50=None,
                adx=adx,
                adx_rising=self._adx_rising(values),
                adx_slope_5=None,
                adx_rising_bars=0,
                ema_200_cross_count_50=0,
                ema_200_near_ratio_50=None,
                ema_200_slope_atr_20=None,
                ema_200_chop_score=None,
                bb_width=bb_width,
                bb_width_percentile=bb_width_percentile,
                donchian_high_20=donchian_high,
                donchian_low_20=donchian_low,
                range_20=None,
                range_50_average=None,
                range_20_atr=None,
                swing_high=donchian_high,
                swing_low=donchian_low,
                swing_high_touch_count=1 if donchian_high is not None else 0,
                swing_low_touch_count=1 if donchian_low is not None else 0,
                swing_high_volume_score=None,
                swing_low_volume_score=None,
                swing_high_age_candles=None,
                swing_low_age_candles=None,
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
