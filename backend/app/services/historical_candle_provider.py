from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Protocol

from app.core.config import settings
from app.core.clickhouse_client import create_clickhouse_client
from app.exchanges.bybit import fetch_bybit_klines_range
from app.schemas.candle import OHLCVCandle
from app.services.candle_service import TIMEFRAME_MS
from app.services.market_persistence import OHLCV_TABLES_BY_TIMEFRAME, market_data_persistence_service

logger = logging.getLogger(__name__)


class HistoricalCandleProvider(Protocol):
    async def load_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[OHLCVCandle]:
        ...

    async def count_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        ...

    async def count_raw_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        ...


class ClickHouseQueryClient(Protocol):
    def query(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        ...


RangeKlineFetcher = Callable[..., list[OHLCVCandle]]


class CandlePersistenceService(Protocol):
    def persist_candles(self, candles: list[OHLCVCandle]) -> int:
        ...


class ClickHouseHistoricalCandleProvider:
    def __init__(self, clickhouse_client_factory: Any = create_clickhouse_client) -> None:
        self._clickhouse_client_factory = clickhouse_client_factory

    async def load_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[OHLCVCandle]:
        return await asyncio.to_thread(
            self._load_candles_sync,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )

    async def count_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        return await asyncio.to_thread(
            self._count_candles_sync,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )

    async def count_raw_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        return await asyncio.to_thread(
            self._count_candles_sync,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
            deduped=False,
        )

    def _load_candles_sync(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[OHLCVCandle]:
        table = OHLCV_TABLES_BY_TIMEFRAME.get(timeframe)
        if table is None:
            raise ValueError(f"unsupported_timeframe: {timeframe}")

        tie_breaker = (
            "tuple(created_at, open, high, low, close, "
            "volume_base, volume_quote, trades_count)"
        )
        query = f"""
            SELECT
                exchange,
                symbol,
                ts,
                selected_open AS open,
                selected_high AS high,
                selected_low AS low,
                selected_close AS close,
                selected_volume_base AS volume_base,
                selected_trades_count AS trades_count,
                latest_created_at
            FROM (
                SELECT
                    exchange,
                    symbol,
                    ts,
                    argMax(open, {tie_breaker}) AS selected_open,
                    argMax(high, {tie_breaker}) AS selected_high,
                    argMax(low, {tie_breaker}) AS selected_low,
                    argMax(close, {tie_breaker}) AS selected_close,
                    argMax(volume_base, {tie_breaker}) AS selected_volume_base,
                    argMax(trades_count, {tie_breaker}) AS selected_trades_count,
                    max(created_at) AS latest_created_at
                FROM {table}
                WHERE exchange = {{exchange:String}}
                  AND symbol = {{symbol:String}}
                  AND ts >= {{start_at:DateTime64(3, 'UTC')}}
                  AND ts <= {{closed_open_end_at:DateTime64(3, 'UTC')}}
                  AND toUnixTimestamp(ts) % {{timeframe_seconds:UInt32}} = 0
                GROUP BY exchange, symbol, ts
            )
            ORDER BY ts ASC
        """
        client = self._client()
        try:
            closed_open_end_at = _closed_open_end_at(end_at, timeframe)
            result = client.query(
                query,
                parameters={
                    "exchange": exchange,
                    "symbol": symbol,
                    "start_at": _as_utc(start_at),
                    "closed_open_end_at": closed_open_end_at,
                    "timeframe_seconds": TIMEFRAME_MS[timeframe] // 1000,
                },
            )
            rows = _named_result_rows(result)
            rows = _dedupe_rows(rows)
            end_ms = _datetime_to_ms(end_at)
            return [
                _row_to_candle(row, timeframe)
                for row in rows
                if _is_expected_closed_row(row, timeframe=timeframe, end_ms=end_ms)
            ]
        finally:
            self._close_client(client)

    def _count_candles_sync(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
        deduped: bool = True,
    ) -> int:
        table = OHLCV_TABLES_BY_TIMEFRAME.get(timeframe)
        if table is None:
            raise ValueError(f"unsupported_timeframe: {timeframe}")

        inner_query = f"""
            SELECT ts
            FROM {table}
            WHERE exchange = {{exchange:String}}
              AND symbol = {{symbol:String}}
              AND ts >= {{start_at:DateTime64(3, 'UTC')}}
              AND ts <= {{closed_open_end_at:DateTime64(3, 'UTC')}}
              AND toUnixTimestamp(ts) % {{timeframe_seconds:UInt32}} = 0
        """
        query = (
            f"""
                SELECT count() AS candles_count
                FROM (
                    {inner_query}
                    GROUP BY ts
                )
            """
            if deduped
            else f"""
                SELECT count() AS candles_count
                FROM {table}
                WHERE exchange = {{exchange:String}}
                  AND symbol = {{symbol:String}}
                  AND ts >= {{start_at:DateTime64(3, 'UTC')}}
                  AND ts <= {{closed_open_end_at:DateTime64(3, 'UTC')}}
                  AND toUnixTimestamp(ts) % {{timeframe_seconds:UInt32}} = 0
            """
        )
        client = self._client()
        try:
            result = client.query(
                query,
                parameters={
                    "exchange": exchange,
                    "symbol": symbol,
                    "start_at": _as_utc(start_at),
                    "closed_open_end_at": _closed_open_end_at(end_at, timeframe),
                    "timeframe_seconds": TIMEFRAME_MS[timeframe] // 1000,
                },
            )
            return _count_from_result(result)
        finally:
            self._close_client(client)

    def _client(self) -> ClickHouseQueryClient:
        return self._clickhouse_client_factory()

    @staticmethod
    def _close_client(client: ClickHouseQueryClient) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()


class BackfillingHistoricalCandleProvider:
    def __init__(
        self,
        base_provider: HistoricalCandleProvider | None = None,
        *,
        range_fetcher: RangeKlineFetcher = fetch_bybit_klines_range,
        persistence_service: CandlePersistenceService = market_data_persistence_service,
        settings_obj: Any = settings,
        coverage_ratio: float = 0.98,
    ) -> None:
        self._base_provider = base_provider or ClickHouseHistoricalCandleProvider()
        self._range_fetcher = range_fetcher
        self._persistence_service = persistence_service
        self._settings = settings_obj
        self._coverage_ratio = max(0.0, min(float(coverage_ratio), 1.0))

    async def load_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[OHLCVCandle]:
        await self.ensure_candles(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )
        return await self._base_provider.load_candles(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )

    async def ensure_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> None:
        if timeframe not in TIMEFRAME_MS:
            raise ValueError(f"unsupported_timeframe: {timeframe}")
        if not _truthy_setting(
            self._settings,
            "strategy_test_historical_backfill_enabled",
            default=True,
        ):
            return
        if exchange.strip().lower() != "bybit":
            return

        expected_count = _expected_closed_candle_count(
            start_at=start_at,
            end_at=end_at,
            timeframe=timeframe,
        )
        if expected_count <= 0:
            return
        max_candles = max(
            1,
            int(
                getattr(
                    self._settings,
                    "strategy_test_historical_backfill_max_candles_per_pair_timeframe",
                    500_000,
                )
            ),
        )
        if expected_count > max_candles:
            raise ValueError(
                "historical_backfill_range_too_large: "
                f"expected {expected_count} candles for {exchange} {symbol} {timeframe}, "
                f"limit is {max_candles}"
            )

        actual_count = await self._base_provider.count_candles(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )
        coverage = actual_count / expected_count
        if actual_count >= expected_count * self._coverage_ratio:
            logger.info(
                "Historical candle cache hit exchange=%s symbol=%s timeframe=%s candles=%s expected=%s coverage=%.4f",
                exchange,
                symbol,
                timeframe,
                actual_count,
                expected_count,
                coverage,
                extra={
                    "exchange": exchange,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "candles_count": actual_count,
                    "expected_candles": expected_count,
                    "coverage": coverage,
                },
            )
            return

        logger.info(
            "Historical candle cache miss exchange=%s symbol=%s timeframe=%s candles=%s expected=%s coverage=%.4f",
            exchange,
            symbol,
            timeframe,
            actual_count,
            expected_count,
            coverage,
            extra={
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "candles_count": actual_count,
                "expected_candles": expected_count,
                "coverage": coverage,
            },
        )
        try:
            candles = await asyncio.wait_for(
                asyncio.to_thread(
                    self._range_fetcher,
                    symbol=symbol,
                    timeframe=timeframe,
                    start_at=_as_utc(start_at),
                    end_at=_as_utc(end_at),
                    category="linear",
                    limit=max(
                        1,
                        int(getattr(self._settings, "strategy_test_historical_backfill_batch_limit", 1000)),
                    ),
                ),
                timeout=max(
                    0.1,
                    float(getattr(self._settings, "strategy_test_historical_backfill_timeout_seconds", 30.0)),
                ),
            )
            closed_candles = _closed_candles_in_range(
                candles,
                timeframe=timeframe,
                start_at=start_at,
                end_at=end_at,
            )
            if closed_candles:
                rows_written = await asyncio.to_thread(self._persistence_service.persist_candles, closed_candles)
                logger.info(
                    "Historical candle backfill persisted exchange=%s symbol=%s timeframe=%s fetched=%s closed=%s rows_written=%s",
                    exchange,
                    symbol,
                    timeframe,
                    len(candles),
                    len(closed_candles),
                    rows_written,
                    extra={
                        "exchange": exchange,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "fetched_candles": len(candles),
                        "closed_candles": len(closed_candles),
                        "rows_written": rows_written,
                    },
                )
            else:
                logger.warning(
                    "Historical candle backfill returned no closed candles exchange=%s symbol=%s timeframe=%s fetched=%s",
                    exchange,
                    symbol,
                    timeframe,
                    len(candles),
                    extra={
                        "exchange": exchange,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "fetched_candles": len(candles),
                    },
                )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            timeout = float(getattr(self._settings, "strategy_test_historical_backfill_timeout_seconds", 30.0))
            raise RuntimeError(
                f"historical_backfill_failed: {exchange} {symbol} {timeframe} "
                f"timeout after {timeout:g}s"
            ) from exc
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            raise RuntimeError(
                f"historical_backfill_failed: {exchange} {symbol} {timeframe} {detail}"
            ) from exc

    async def count_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        return await self._base_provider.count_candles(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )

    async def count_raw_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        return await self._base_provider.count_raw_candles(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )


class InMemoryHistoricalCandleProvider:
    def __init__(self, candles: list[OHLCVCandle] | None = None) -> None:
        self._candles = list(candles or [])

    def set_candles(self, candles: list[OHLCVCandle]) -> None:
        self._candles = list(candles)

    async def load_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[OHLCVCandle]:
        start_ms = _datetime_to_ms(start_at)
        end_ms = _datetime_to_ms(end_at)
        candles = [
            candle
            for candle in self._candles
            if candle.exchange == exchange
            and candle.symbol == symbol
            and candle.timeframe == timeframe
            and candle.is_closed
            and start_ms <= candle.open_time <= end_ms
        ]
        return _dedupe_candles(candles, end_ms=end_ms)

    async def count_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        return len(
            await self.load_candles(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                start_at=start_at,
                end_at=end_at,
            )
        )

    async def count_raw_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        start_ms = _datetime_to_ms(start_at)
        end_ms = _datetime_to_ms(end_at)
        return len(
            [
                candle
                for candle in self._candles
                if candle.exchange == exchange
                and candle.symbol == symbol
                and candle.timeframe == timeframe
                and candle.is_closed
                and start_ms <= candle.open_time <= end_ms
                and candle.close_time <= end_ms
            ]
        )


def _row_to_candle(row: dict[str, Any], timeframe: str) -> OHLCVCandle:
    open_time = _datetime_to_ms(row["ts"])
    return OHLCVCandle(
        exchange=row["exchange"],
        symbol=row["symbol"],
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + TIMEFRAME_MS[timeframe] - 1,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume_base"]),
        trades=int(row.get("trades_count") or 0),
        is_closed=True,
    )


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["exchange"]), str(row["symbol"]), _datetime_to_ms(row["ts"]))
        current = deduped.get(key)
        if current is None or _row_tie_breaker(row) > _row_tie_breaker(current):
            deduped[key] = row
    return sorted(deduped.values(), key=lambda row: _datetime_to_ms(row["ts"]))


def _dedupe_candles(candles: list[OHLCVCandle], *, end_ms: int) -> list[OHLCVCandle]:
    deduped: dict[int, OHLCVCandle] = {}
    for candle in candles:
        if not candle.is_closed:
            continue
        if candle.close_time > end_ms:
            continue
        current = deduped.get(candle.open_time)
        if current is None or _candle_tie_breaker(candle) > _candle_tie_breaker(current):
            deduped[candle.open_time] = candle
    return sorted(deduped.values(), key=lambda candle: candle.open_time)


def _candle_tie_breaker(candle: OHLCVCandle) -> tuple[float, float, float, float, float, int]:
    return (
        float(candle.open),
        float(candle.high),
        float(candle.low),
        float(candle.close),
        float(candle.volume),
        int(candle.trades),
    )


def _row_tie_breaker(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal, int]:
    created_at = row.get("created_at") or row.get("latest_created_at")
    created_at_ms = _datetime_to_ms(created_at) if isinstance(created_at, datetime) else 0
    return (
        created_at_ms,
        _decimal_sort_value(row.get("open")),
        _decimal_sort_value(row.get("high")),
        _decimal_sort_value(row.get("low")),
        _decimal_sort_value(row.get("close")),
        _decimal_sort_value(row.get("volume_base")),
        int(row.get("trades_count") or 0),
    )


def _decimal_sort_value(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _is_expected_closed_row(row: dict[str, Any], *, timeframe: str, end_ms: int) -> bool:
    open_time = _datetime_to_ms(row["ts"])
    timeframe_ms = TIMEFRAME_MS[timeframe]
    close_time = open_time + timeframe_ms - 1
    return open_time % timeframe_ms == 0 and close_time <= end_ms


def _closed_candles_in_range(
    candles: list[OHLCVCandle],
    *,
    timeframe: str,
    start_at: datetime,
    end_at: datetime,
) -> list[OHLCVCandle]:
    start_ms = _datetime_to_ms(start_at)
    end_ms = _datetime_to_ms(end_at)
    deduped: dict[int, OHLCVCandle] = {}
    for candle in candles:
        if candle.timeframe != timeframe or not candle.is_closed:
            continue
        if candle.open_time < start_ms or candle.close_time > end_ms:
            continue
        current = deduped.get(candle.open_time)
        if current is None or _candle_tie_breaker(candle) > _candle_tie_breaker(current):
            deduped[candle.open_time] = candle
    return sorted(deduped.values(), key=lambda candle: candle.open_time)


def _expected_closed_candle_count(
    *,
    start_at: datetime,
    end_at: datetime,
    timeframe: str,
) -> int:
    timeframe_ms = TIMEFRAME_MS[timeframe]
    start_ms = _datetime_to_ms(start_at)
    end_ms = _datetime_to_ms(end_at)
    first_open_ms = _ceil_to_timeframe_ms(start_ms, timeframe_ms)
    last_open_ms = ((end_ms - timeframe_ms + 1) // timeframe_ms) * timeframe_ms
    if last_open_ms < first_open_ms:
        return 0
    return ((last_open_ms - first_open_ms) // timeframe_ms) + 1


def _ceil_to_timeframe_ms(value_ms: int, timeframe_ms: int) -> int:
    return ((value_ms + timeframe_ms - 1) // timeframe_ms) * timeframe_ms


def _truthy_setting(settings_obj: Any, name: str, *, default: bool) -> bool:
    value = getattr(settings_obj, name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _closed_open_end_at(end_at: datetime, timeframe: str) -> datetime:
    timeframe_ms = TIMEFRAME_MS[timeframe]
    return _as_utc(end_at) - timedelta(milliseconds=timeframe_ms - 1)


def _count_from_result(result: Any) -> int:
    rows = _named_result_rows(result)
    if not rows:
        return 0
    first = rows[0]
    if isinstance(first, dict):
        for key in ("candles_count", "count()", "count"):
            if key in first:
                return int(first[key] or 0)
    return 0


def _named_result_rows(result: Any) -> list[dict[str, Any]]:
    rows = result.named_results() if hasattr(result, "named_results") else []
    return list(rows)


def _datetime_to_ms(value: datetime) -> int:
    return int(_as_utc(value).timestamp() * 1000)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
