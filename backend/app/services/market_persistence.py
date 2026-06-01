import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from app.core.clickhouse_client import get_clickhouse_client
from app.core.redis_client import get_redis_client
from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features, MarketData, OrderBookSnapshot

PRICE_TTL_SECONDS = 30
ORDERBOOK_TTL_SECONDS = 5
ORDERBOOK_HOT_KEY_PREFIX = "orderbook"

OHLCV_TABLES_BY_TIMEFRAME = {
    "1m": "market.ohlcv_1m",
    "5m": "market.ohlcv_5m",
    "15m": "market.ohlcv_15m",
    "1h": "market.ohlcv_1h",
    "4h": "market.ohlcv_4h",
    "1d": "market.ohlcv_1d",
}


class ClickHouseInsertClient(Protocol):
    def insert(
        self,
        table: str,
        data: list[list[Any]],
        column_names: list[str],
    ) -> None:
        ...


class RedisHotClient(Protocol):
    def setex(self, name: str, time: int, value: str) -> Any:
        ...


def _utc_from_ms(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: float | int | str | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def orderbook_hot_key(*, exchange: str, symbol: str) -> str:
    return f"{ORDERBOOK_HOT_KEY_PREFIX}:{exchange.strip().lower()}:{symbol.strip().upper()}"


def _tick_source_id(tick: MarketData) -> str:
    return (
        f"{tick.exchange}:{tick.symbol}:{tick.timestamp}:"
        f"{tick.price:.18g}:{tick.volume:.18g}"
    )


class MarketDataPersistenceService:
    """Persists market data only to ClickHouse and Redis."""

    _raw_event_columns = [
        "exchange",
        "event_type",
        "symbol",
        "event_ts",
        "ingest_ts",
        "source_id",
        "sequence_id",
        "raw_payload",
    ]
    _trade_columns = [
        "exchange",
        "symbol",
        "trade_id",
        "side",
        "price",
        "quantity",
        "trade_ts",
        "ingest_ts",
        "is_buyer_maker",
    ]
    _candle_columns = [
        "exchange",
        "symbol",
        "ts",
        "open",
        "high",
        "low",
        "close",
        "volume_base",
        "volume_quote",
        "trades_count",
        "created_at",
    ]
    _indicator_columns = [
        "exchange",
        "symbol",
        "timeframe",
        "ts",
        "rsi_14",
        "ema_20",
        "ema_50",
        "ema_200",
        "atr_14",
        "volume_sma_20",
        "features_json",
        "calculated_at",
    ]

    def __init__(
        self,
        clickhouse_client_factory: Any = get_clickhouse_client,
        redis_client_factory: Any = get_redis_client,
    ) -> None:
        self._clickhouse_client_factory = clickhouse_client_factory
        self._redis_client_factory = redis_client_factory

    def persist_tick(self, tick: MarketData) -> None:
        source_id = _tick_source_id(tick)
        event_ts = _utc_from_ms(tick.timestamp)
        ingest_ts = _utc_now()
        self._write_raw_exchange_event(tick, source_id, event_ts, ingest_ts)
        self._write_trade(tick, source_id, event_ts, ingest_ts)
        self._write_hot_price(tick)

    def persist_candles(self, candles: list[OHLCVCandle]) -> int:
        grouped_rows: dict[str, list[list[Any]]] = defaultdict(list)
        for candle in candles:
            table = OHLCV_TABLES_BY_TIMEFRAME.get(candle.timeframe)
            if table is None:
                continue
            grouped_rows[table].append(self._candle_row(candle))

        client = self._clickhouse()
        rows_written = 0
        for table, rows in grouped_rows.items():
            client.insert(table, rows, column_names=self._candle_columns)
            rows_written += len(rows)
        return rows_written

    def persist_features(self, features: Features) -> None:
        self._clickhouse().insert(
            "market.indicator_values",
            [self._feature_row(features)],
            column_names=self._indicator_columns,
        )

    def persist_orderbook_snapshot(
        self,
        snapshot: OrderBookSnapshot,
        *,
        ttl_seconds: int = ORDERBOOK_TTL_SECONDS,
    ) -> None:
        self._redis().setex(
            orderbook_hot_key(exchange=snapshot.exchange, symbol=snapshot.symbol),
            ttl_seconds,
            snapshot.model_dump_json(exclude_none=True),
        )

    def _clickhouse(self) -> ClickHouseInsertClient:
        return self._clickhouse_client_factory()

    def _redis(self) -> RedisHotClient:
        return self._redis_client_factory()

    def _write_raw_exchange_event(
        self,
        tick: MarketData,
        source_id: str,
        event_ts: datetime,
        ingest_ts: datetime,
    ) -> None:
        payload = tick.model_dump(mode="json")
        payload["source"] = "normalized_trade_tick"
        self._clickhouse().insert(
            "market.raw_exchange_events",
            [
                [
                    tick.exchange,
                    "trade.normalized",
                    tick.symbol,
                    event_ts,
                    ingest_ts,
                    source_id,
                    None,
                    _json_dumps(payload),
                ]
            ],
            column_names=self._raw_event_columns,
        )

    def _write_trade(
        self,
        tick: MarketData,
        source_id: str,
        event_ts: datetime,
        ingest_ts: datetime,
    ) -> None:
        self._clickhouse().insert(
            "market.trades",
            [
                [
                    tick.exchange,
                    tick.symbol,
                    source_id,
                    "unknown",
                    _decimal(tick.price),
                    _decimal(tick.volume),
                    event_ts,
                    ingest_ts,
                    None,
                ]
            ],
            column_names=self._trade_columns,
        )

    def _write_hot_price(self, tick: MarketData) -> None:
        payload = {
            "price": str(tick.price),
            "bid": str(tick.price),
            "ask": str(tick.price),
            "ts": _utc_from_ms(tick.timestamp).isoformat().replace("+00:00", "Z"),
            "source": "trade_tick",
        }
        self._redis().setex(
            f"price:{tick.exchange}:{tick.symbol}",
            PRICE_TTL_SECONDS,
            _json_dumps(payload),
        )

    def _candle_row(self, candle: OHLCVCandle) -> list[Any]:
        volume_base = _decimal(candle.volume)
        close = _decimal(candle.close)
        volume_quote = None
        if volume_base is not None and close is not None:
            volume_quote = volume_base * close
        return [
            candle.exchange,
            candle.symbol,
            _utc_from_ms(candle.open_time),
            _decimal(candle.open),
            _decimal(candle.high),
            _decimal(candle.low),
            close,
            volume_base,
            volume_quote,
            candle.trades,
            _utc_now(),
        ]

    def _feature_row(self, features: Features) -> list[Any]:
        return [
            features.exchange,
            features.symbol,
            features.timeframe,
            _utc_from_ms(features.timestamp),
            features.rsi_14,
            _decimal(features.ema_20),
            _decimal(features.ema_50),
            _decimal(features.ema_200),
            _decimal(features.atr_14),
            _decimal(features.volume_ma_20),
            features.model_dump_json(),
            _utc_now(),
        ]


market_data_persistence_service = MarketDataPersistenceService()
