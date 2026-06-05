from dataclasses import dataclass
from datetime import datetime
import json
import logging
from typing import Any, Protocol

from app.core.clickhouse_client import get_clickhouse_client
from app.core.redis_client import get_redis_client
from app.domain.signal_status import is_market_opportunity_status
from app.repositories.signal_repository import (
    MAX_STORED_SIGNALS,
    PostgresSignalRepository,
    SignalRepository,
    SignalWriteResult,
)
from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.risk import RadarDisplayMode, RiskDecision, RiskPreviewRequest
from app.schemas.signal import RadarSignal, StrategySignal
from app.schemas.trade import ManualConfirmRequest
from app.services.risk_management import default_rr_guard_mode_for_context
from app.services.signal_risk_reward import ensure_signal_execution_eligible

logger = logging.getLogger(__name__)


class RiskPreviewEvaluator(Protocol):
    def evaluate(
        self,
        request: RiskPreviewRequest,
        *,
        record_audit: bool = True,
    ) -> RiskDecision:
        ...


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


@dataclass(frozen=True)
class SignalAutoEntryArmResult:
    signal: RadarSignal
    pending_entry_intent: PendingEntryIntentRead


class SignalService:
    def __init__(
        self,
        repository: SignalRepository | None = None,
        analytics_writer: SignalAnalyticsWriter | None = None,
        hot_store: SignalHotStore | None = None,
        risk_preview_evaluator: RiskPreviewEvaluator | None = None,
    ) -> None:
        self._repository = repository or PostgresSignalRepository()
        self._analytics_writer = analytics_writer or ClickHouseSignalAnalyticsWriter()
        self._hot_store = hot_store or RedisSignalHotStore()
        self._risk_preview_evaluator = risk_preview_evaluator

    def list_signals(self) -> list[RadarSignal]:
        return self._repository.list_signals()

    def list_active_signals(self) -> list[RadarSignal]:
        return self._repository.list_active_signals()

    def list_open_signals(self) -> list[RadarSignal]:
        list_open = getattr(self._repository, "list_open_signals", None)
        if list_open is not None:
            return list_open()
        return [
            signal
            for signal in self._repository.list_signals()
            if is_market_opportunity_status(signal.status)
        ]

    def list_open_signals_for_radar(
        self,
        *,
        user_id: str = "demo_user",
        radar_display_mode: RadarDisplayMode | None = None,
    ) -> list[RadarSignal]:
        return self.list_open_signals()

    def list_open_signals_for_series(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int = MAX_STORED_SIGNALS,
    ) -> list[RadarSignal]:
        list_for_series = getattr(self._repository, "list_open_signals_for_series", None)
        if list_for_series is not None:
            return list_for_series(exchange=exchange, symbol=symbol, timeframe=timeframe, limit=limit)
        return [
            signal
            for signal in self.list_open_signals()
            if signal.exchange == exchange and signal.symbol == symbol and signal.timeframe == timeframe
        ][:limit]

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        return self._repository.get_signal(signal_id)

    def expire_open_signals(self, now: datetime | None = None, limit: int = 500) -> int:
        expire = getattr(self._repository, "expire_open_signals", None)
        if expire is None:
            return 0
        return expire(now=now, limit=limit)

    def add_signal(self, signal: RadarSignal) -> RadarSignal:
        result = self._repository.add_signal(signal)
        self._after_write(result)
        self._reconcile_pending_entry_trade_plan(result)
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
        self._reconcile_pending_entry_trade_plan(result)
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
        self._reconcile_pending_entry_trade_plan(result)
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

    def transition_signal(
        self,
        signal_id: str,
        *,
        new_status: str,
        event_type: str,
        reason: str | None = None,
        lifecycle: dict[str, Any] | None = None,
        signal_updates: dict[str, Any] | None = None,
    ) -> RadarSignal | None:
        transition = getattr(self._repository, "transition_signal", None)
        if transition is None:
            return None
        result = transition(
            signal_id,
            new_status=new_status,
            event_type=event_type,
            reason=reason,
            lifecycle=lifecycle,
            signal_updates=signal_updates,
        )
        if result is None:
            return None
        self._after_write(result)
        self._reconcile_pending_entry_trade_plan(result)
        return result.signal

    def arm_auto_entry(
        self,
        signal_id: str,
        request: dict[str, Any],
        *,
        pending_entry_intent: PendingEntryIntentRead | None = None,
    ) -> SignalAutoEntryArmResult | None:
        # TODO(migration-v2.2): remove this legacy signal.auto_entry compatibility
        # writer after old signal snapshots are migrated to pending_entry_intents.
        signal = self._repository.get_signal(signal_id)
        if signal is None:
            return None
        raw_mode = str(request.get("mode") or "virtual").strip().lower()
        mode = "real" if raw_mode == "real" else "virtual"
        request_model = ManualConfirmRequest.model_validate({**request, "mode": mode})
        if pending_entry_intent is None:
            from app.services.pending_entry import pending_entry_intent_service

            execution_profile = pending_entry_intent_service.resolve_execution_profile(
                signal,
                request_model,
                mode=mode,
            )
            ensure_signal_execution_eligible(
                signal,
                mode=mode,
                rr_guard_mode=execution_profile.rr_guard_mode,
            )
            pending_entry_intent = pending_entry_intent_service.arm_from_signal(
                user_id=request_model.user_id,
                signal_id=signal.id,
                mode=mode,
                request=request_model,
                execution_profile=execution_profile,
            )
        else:
            ensure_signal_execution_eligible(
                signal,
                mode=mode,
                rr_guard_mode=pending_entry_intent.execution_profile_snapshot.get(
                    "rr_guard_mode",
                    default_rr_guard_mode_for_context(mode),
                ),
            )
        arm = getattr(self._repository, "arm_auto_entry", None)
        if arm is None:
            return SignalAutoEntryArmResult(signal=signal, pending_entry_intent=pending_entry_intent)
        mirror_request = {
            **request_model.model_dump(mode="json"),
            "pending_entry_intent_id": str(pending_entry_intent.id),
            "accepted_trade_plan_hash": pending_entry_intent.accepted_trade_plan_hash,
            "idempotency_key": pending_entry_intent.idempotency_key,
        }
        result = arm(signal_id, request=mirror_request)
        if result is None:
            return None
        self._after_write(result)
        return SignalAutoEntryArmResult(signal=result.signal, pending_entry_intent=pending_entry_intent)

    def update_auto_entry(
        self,
        signal_id: str,
        *,
        status: str,
        message: str | None = None,
        trade_id: str | None = None,
        real_execution: dict[str, Any] | None = None,
        event_type: str = "signal.updated",
    ) -> RadarSignal | None:
        # TODO(migration-v2.2): remove this legacy signal.auto_entry compatibility
        # writer after old signal snapshots are migrated to pending_entry_intents.
        update = getattr(self._repository, "update_auto_entry", None)
        if update is None:
            return None
        result = update(
            signal_id,
            status=status,
            message=message,
            trade_id=trade_id,
            real_execution=real_execution,
            event_type=event_type,
        )
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

    def _reconcile_pending_entry_trade_plan(self, result: SignalWriteResult) -> None:
        try:
            from app.services.pending_entry import pending_entry_intent_service

            pending_entry_intent_service.reconcile_signal_trade_plan(
                result.signal,
            )
        except Exception as exc:
            logger.warning("Pending entry trade-plan reconciliation failed: %s", exc)


signal_service = SignalService()
