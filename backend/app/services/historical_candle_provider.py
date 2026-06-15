from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

from app.core.clickhouse_client import create_clickhouse_client
from app.schemas.candle import OHLCVCandle
from app.services.candle_service import TIMEFRAME_MS
from app.services.market_persistence import OHLCV_TABLES_BY_TIMEFRAME


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


class ClickHouseQueryClient(Protocol):
    def query(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
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
                argMax(open, {tie_breaker}) AS open,
                argMax(high, {tie_breaker}) AS high,
                argMax(low, {tie_breaker}) AS low,
                argMax(close, {tie_breaker}) AS close,
                argMax(volume_base, {tie_breaker}) AS volume_base,
                argMax(trades_count, {tie_breaker}) AS trades_count,
                max(created_at) AS created_at
            FROM {table}
            WHERE exchange = {{exchange:String}}
              AND symbol = {{symbol:String}}
              AND ts >= {{start_at:DateTime64(3, 'UTC')}}
              AND ts <= {{closed_open_end_at:DateTime64(3, 'UTC')}}
              AND toUnixTimestamp(ts) % {{timeframe_seconds:UInt32}} = 0
            GROUP BY exchange, symbol, ts
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
            rows = result.named_results() if hasattr(result, "named_results") else []
            rows = _dedupe_rows(rows)
            end_ms = _datetime_to_ms(end_at)
            return [
                _row_to_candle(row, timeframe)
                for row in rows
                if _is_expected_closed_row(row, timeframe=timeframe, end_ms=end_ms)
            ]
        finally:
            self._close_client(client)

    def _client(self) -> ClickHouseQueryClient:
        return self._clickhouse_client_factory()

    @staticmethod
    def _close_client(client: ClickHouseQueryClient) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()


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
        return sorted(candles, key=lambda candle: candle.open_time)


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


def _row_tie_breaker(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal, int]:
    created_at = row.get("created_at")
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


def _closed_open_end_at(end_at: datetime, timeframe: str) -> datetime:
    timeframe_ms = TIMEFRAME_MS[timeframe]
    return _as_utc(end_at) - timedelta(milliseconds=timeframe_ms - 1)


def _datetime_to_ms(value: datetime) -> int:
    return int(_as_utc(value).timestamp() * 1000)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
