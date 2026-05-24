from collections import defaultdict, deque
from typing import Deque, Dict, Iterable, Optional, Tuple

from app.schemas.candle import DEFAULT_TIMEFRAMES, OHLCVCandle, Timeframe
from app.schemas.market import MarketData

TIMEFRAME_MS: dict[Timeframe, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}
MAX_CANDLES_PER_SERIES = 500

SeriesKey = Tuple[str, str, Timeframe]


class CandleService:
    """Агрегирует поток сделок в OHLCV-свечи по exchange/symbol/timeframe."""

    def __init__(
        self,
        timeframes: Optional[Iterable[Timeframe]] = None,
        max_candles: int = MAX_CANDLES_PER_SERIES,
    ) -> None:
        self._timeframes = list(timeframes or DEFAULT_TIMEFRAMES)
        self._max_candles = max_candles
        self._current: Dict[SeriesKey, OHLCVCandle] = {}
        self._history: Dict[SeriesKey, Deque[OHLCVCandle]] = defaultdict(
            lambda: deque(maxlen=self._max_candles)
        )

    @property
    def timeframes(self) -> list[Timeframe]:
        return list(self._timeframes)

    def configure_timeframes(self, timeframes: Iterable[Timeframe]) -> None:
        self._timeframes = list(dict.fromkeys(timeframes))

    def update_from_tick(self, tick: MarketData) -> list[OHLCVCandle]:
        updated: list[OHLCVCandle] = []
        for timeframe in self._timeframes:
            updated.append(self._update_timeframe(tick, timeframe))
        return updated

    def list_candles(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[Timeframe] = None,
        include_open: bool = True,
        limit: int = 100,
    ) -> list[OHLCVCandle]:
        candles: list[OHLCVCandle] = []

        keys = set(self._history.keys()) | set(self._current.keys())
        for key in keys:
            key_exchange, key_symbol, key_timeframe = key
            if exchange is not None and key_exchange != exchange:
                continue
            if symbol is not None and key_symbol != symbol:
                continue
            if timeframe is not None and key_timeframe != timeframe:
                continue

            candles.extend(self._history.get(key, []))
            if include_open and key in self._current:
                candles.append(self._current[key])

        return sorted(candles, key=lambda candle: candle.open_time)[-limit:]

    def _update_timeframe(
        self,
        tick: MarketData,
        timeframe: Timeframe,
    ) -> OHLCVCandle:
        timeframe_ms = TIMEFRAME_MS[timeframe]
        bucket_open = tick.timestamp - (tick.timestamp % timeframe_ms)
        bucket_close = bucket_open + timeframe_ms - 1
        key: SeriesKey = (tick.exchange, tick.symbol, timeframe)
        current = self._current.get(key)

        if current is None:
            current = self._new_candle(tick, timeframe, bucket_open, bucket_close)
            self._current[key] = current
            return current

        if current.open_time != bucket_open:
            closed = current.model_copy(update={"is_closed": True})
            self._history[key].append(closed)
            current = self._new_candle(tick, timeframe, bucket_open, bucket_close)
            self._current[key] = current
            return current

        updated = current.model_copy(
            update={
                "high": max(current.high, tick.price),
                "low": min(current.low, tick.price),
                "close": tick.price,
                "volume": current.volume + tick.volume,
                "trades": current.trades + 1,
            }
        )
        self._current[key] = updated
        return updated

    @staticmethod
    def _new_candle(
        tick: MarketData,
        timeframe: Timeframe,
        open_time: int,
        close_time: int,
    ) -> OHLCVCandle:
        return OHLCVCandle(
            exchange=tick.exchange,
            symbol=tick.symbol,
            timeframe=timeframe,
            open_time=open_time,
            close_time=close_time,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.volume,
            trades=1,
            is_closed=False,
        )


candle_service = CandleService()
