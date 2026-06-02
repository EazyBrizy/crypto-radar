from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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

        query = f"""
            SELECT
                exchange,
                symbol,
                ts,
                open,
                high,
                low,
                close,
                volume_base,
                trades_count
            FROM {table}
            WHERE exchange = {{exchange:String}}
              AND symbol = {{symbol:String}}
              AND ts >= {{start_at:DateTime64(3, 'UTC')}}
              AND ts <= {{end_at:DateTime64(3, 'UTC')}}
            ORDER BY ts ASC
        """
        client = self._client()
        try:
            result = client.query(
                query,
                parameters={
                    "exchange": exchange,
                    "symbol": symbol,
                    "start_at": _as_utc(start_at),
                    "end_at": _as_utc(end_at),
                },
            )
            rows = result.named_results() if hasattr(result, "named_results") else []
            return [_row_to_candle(row, timeframe) for row in rows]
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


def _datetime_to_ms(value: datetime) -> int:
    return int(_as_utc(value).timestamp() * 1000)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
