import json
import logging
from typing import Any, Protocol

from app.core.clickhouse_client import get_clickhouse_client
from app.core.redis_client import get_redis_client
from app.repositories.signal_repository import (
    PostgresSignalRepository,
    SignalRepository,
    SignalWriteResult,
)
from app.schemas.signal import RadarSignal, StrategySignal

logger = logging.getLogger(__name__)


class SignalAnalyticsWriter(Protocol):
    def write_event(self, event: dict[str, Any]) -> None:
        ...


class SignalHotStore(Protocol):
    def write_signal(self, result: SignalWriteResult) -> None:
        ...


class ClickHouseSignalAnalyticsWriter:
    _columns = [
        "signal_id",
        "signal_key",
        "event_type",
        "exchange",
        "symbol",
        "timeframe",
        "strategy_code",
        "strategy_version",
        "direction",
        "confidence",
        "score",
        "entry_price",
        "stop_loss",
        "features_json",
        "event_ts",
        "ingest_ts",
    ]

    def write_event(self, event: dict[str, Any]) -> None:
        row = []
        for column in self._columns:
            value = event[column]
            if column == "features_json" and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False, default=str)
            row.append(value)
        get_clickhouse_client().insert(
            "analytics.signal_events",
            [row],
            column_names=self._columns,
        )


class RedisSignalHotStore:
    _ttl_seconds = 3600
    _max_latest_items = 200

    def write_signal(self, result: SignalWriteResult) -> None:
        signal = result.signal
        score = float(signal.score)
        payload = signal.model_dump_json()
        client = get_redis_client()
        latest_keys = [
            "signals:latest",
            f"signals:latest:{signal.strategy}",
            f"signals:latest:{signal.exchange}:{signal.symbol}",
        ]
        with client.pipeline() as pipe:
            pipe.setex(f"signal:{signal.id}", self._ttl_seconds, payload)
            for key in latest_keys:
                pipe.zadd(key, {signal.id: score})
                pipe.zremrangebyrank(key, 0, -self._max_latest_items - 1)
            pipe.execute()

        channel = "pubsub:signals:new" if result.created else "pubsub:signals:update"
        client.publish(channel, payload)


class NullSignalAnalyticsWriter:
    def write_event(self, event: dict[str, Any]) -> None:
        return None


class NullSignalHotStore:
    def write_signal(self, result: SignalWriteResult) -> None:
        return None


class SignalService:
    def __init__(
        self,
        repository: SignalRepository | None = None,
        analytics_writer: SignalAnalyticsWriter | None = None,
        hot_store: SignalHotStore | None = None,
    ) -> None:
        self._repository = repository or PostgresSignalRepository()
        self._analytics_writer = analytics_writer or ClickHouseSignalAnalyticsWriter()
        self._hot_store = hot_store or RedisSignalHotStore()

    def list_signals(self) -> list[RadarSignal]:
        return self._repository.list_signals()

    def list_active_signals(self) -> list[RadarSignal]:
        return self._repository.list_active_signals()

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        return self._repository.get_signal(signal_id)

    def add_signal(self, signal: RadarSignal) -> RadarSignal:
        result = self._repository.add_signal(signal)
        self._after_write(result)
        return result.signal

    def add_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> RadarSignal:
        radar_signal, _ = self.upsert_strategy_signal(
            signal,
            exchange=exchange,
            explanation=explanation,
        )
        return radar_signal

    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> tuple[RadarSignal, bool]:
        result = self._repository.upsert_strategy_signal(
            signal,
            exchange=exchange,
            explanation=explanation,
        )
        self._after_write(result)
        return result.signal, result.created

    def confirm_signal(
        self,
        signal_id: str,
        trade_id: str | None = None,
        mode: str = "virtual",
        note: str | None = None,
    ) -> RadarSignal | None:
        result = self._repository.confirm_signal(
            signal_id,
            trade_id=trade_id,
            mode=mode,
            note=note,
        )
        if result is None:
            return None
        self._after_write(result)
        return result.signal

    def reject_signal(
        self,
        signal_id: str,
        note: str | None = None,
    ) -> RadarSignal | None:
        result = self._repository.reject_signal(signal_id, note=note)
        if result is None:
            return None
        self._after_write(result)
        return result.signal

    def _after_write(self, result: SignalWriteResult) -> None:
        try:
            self._analytics_writer.write_event(result.analytics_event)
        except Exception as exc:
            logger.warning("ClickHouse signal analytics write failed: %s", exc)
        try:
            self._hot_store.write_signal(result)
        except Exception as exc:
            logger.warning("Redis signal hot write failed: %s", exc)


signal_service = SignalService()
