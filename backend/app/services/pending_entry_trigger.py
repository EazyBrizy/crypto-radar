from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.domain.pending_entry_reason import (
    ENTRY_ZONE_NOT_TOUCHED,
    PENDING_ENTRY_EXECUTION_INVALID,
    PENDING_ENTRY_EXPIRED_BEFORE_TOUCH,
    PENDING_ENTRY_GATE_SNAPSHOT_KEY,
    PENDING_ENTRY_LAST_REASON_KEY,
    PENDING_ENTRY_SIGNAL_MISSING,
    PENDING_ENTRY_TERMINAL_REASON_KEY,
    REAL_PENDING_EXECUTION_NOT_ENABLED,
    RISK_GATE_REJECTED,
    SIGNAL_TERMINAL,
    TEMPORARY_EXECUTION_FAILURE,
    TRADE_PLAN_RECONFIRMATION_REQUIRED,
    VIRTUAL_EXECUTION_REJECTED,
)
from app.core.database import SessionLocal
from app.domain.signal_status import is_terminal_signal_status
from app.models.pending_entry import PendingEntryIntent
from app.schemas.lifecycle import LifecycleTrace
from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.risk import RiskOverride, StrategyExecutionSettings
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, RecentTradePrint, VirtualMarketSnapshot, VirtualTrade
from app.schemas.trade_plan import TradePlan
from app.services.pending_entry import (
    TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
    pending_entry_service,
)
from app.services.pending_entry_events import PendingEntryUpdatePublisher, pending_entry_update_publisher
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
from app.services.signal_service import signal_service
from app.services.trade_plan_fingerprint import (
    evaluate_pending_entry_material_change,
    material_change_policy_from_snapshot,
    normalized_pending_entry_payload,
)
from app.services.virtual_trading import VirtualExecutionRejected, virtual_trading_service

logger = logging.getLogger(__name__)

TEMPORARY_RISKGATE_REASON_MARKERS: tuple[str, ...] = (
    "stale",
    "market data",
    "ticker",
    "bybit market data is unavailable",
    "bybit market data is stale",
)


class PendingEntryProvider(Protocol):
    def list_pending_for_market(self, exchange: str, symbol: str) -> list[PendingEntryIntentRead]:
        ...

    def lock_for_trigger(self, intent_id: str | UUID, *, session: Session) -> PendingEntryIntent | None:
        ...

    def transition_status(
        self,
        intent_id: str | UUID,
        *,
        status: str,
        failure_reason: str | None = None,
        filled_trade_id: str | UUID | None = None,
        reason_code: str | None = None,
        gate_snapshot: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        ...


class SignalProvider(Protocol):
    def get_signal(self, signal_id: str) -> RadarSignal | None:
        ...


class VirtualEntryExecutor(Protocol):
    def confirm_signal(self, signal: RadarSignal, request: ManualConfirmRequest) -> tuple[RadarSignal, VirtualTrade]:
        ...


@dataclass(frozen=True)
class EntryTouchResult:
    touched: bool
    price: Decimal | None = None
    price_source: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingEntryTriggerResult:
    intent_id: str
    status: str
    touched: bool
    signal_id: str | None = None
    price: Decimal | None = None
    price_source: str | None = None
    virtual_trade_id: str | None = None
    risk_decision_id: str | None = None
    reason: str | None = None
    reason_code: str | None = None
    gate_snapshot: dict[str, Any] | None = None
    current_price: Decimal | None = None
    entry_zone_distance_bps: Decimal | None = None
    warnings: tuple[str, ...] = ()
    lifecycle_trace: LifecycleTrace = field(default_factory=LifecycleTrace)


class PendingEntryTriggerService:
    """Triggers accepted pending entries from actual market price touches."""

    def __init__(
        self,
        *,
        pending_entries: PendingEntryProvider | None = None,
        signals: SignalProvider | None = None,
        virtual_trading: VirtualEntryExecutor | None = None,
        session_factory: sessionmaker[Session] = SessionLocal,
        event_publisher: PendingEntryUpdatePublisher | None = None,
    ) -> None:
        self._pending_entries = pending_entries or pending_entry_service
        self._signals = signals or signal_service
        self._virtual_trading = virtual_trading or virtual_trading_service
        self._session_factory = session_factory
        self._event_publisher = event_publisher or pending_entry_update_publisher

    def process_market_tick(
        self,
        exchange: str,
        symbol: str,
        market_tick: Any,
    ) -> list[PendingEntryTriggerResult]:
        intents = self._pending_entries.list_pending_for_market(exchange, symbol)
        results: list[PendingEntryTriggerResult] = []
        for intent in intents:
            result = self._process_intent(intent.id, market_tick)
            if result is not None:
                results.append(result)
        return results

    def _process_intent(
        self,
        intent_id: str | UUID,
        market_tick: Any,
    ) -> PendingEntryTriggerResult | None:
        with self._session_factory() as session:
            record = self._pending_entries.lock_for_trigger(intent_id, session=session)
            if record is None or record.status != "pending":
                return None
            now = _utc_now()
            current_price = _current_price_for_intent(record, market_tick)
            entry_zone_distance_bps = _entry_zone_distance_bps(
                record.side,
                record.entry_min,
                record.entry_max,
                current_price,
            )
            signal = self._signals.get_signal(str(record.signal_id))
            if signal is None:
                _transition_locked(
                    record,
                    status="failed",
                    failure_reason="Pending entry signal is missing.",
                    reason_code=PENDING_ENTRY_SIGNAL_MISSING,
                    now=now,
                )
                session.commit()
                self._publish_locked_update(record)
                return _result(
                    record,
                    touched=False,
                    reason=record.failure_reason,
                    current_price=current_price,
                    entry_zone_distance_bps=entry_zone_distance_bps,
                )
            if record.expires_at is not None and _as_utc(record.expires_at) <= now:
                _transition_locked(
                    record,
                    status="expired",
                    failure_reason="Pending entry intent expired before entry touch.",
                    reason_code=PENDING_ENTRY_EXPIRED_BEFORE_TOUCH,
                    now=now,
                )
                session.commit()
                self._publish_locked_update(record)
                return _result(
                    record,
                    touched=False,
                    reason=record.failure_reason,
                    current_price=current_price,
                    entry_zone_distance_bps=entry_zone_distance_bps,
                )
            if is_terminal_signal_status(signal.status):
                _transition_locked(
                    record,
                    status="cancelled",
                    failure_reason=f"Signal is terminal at trigger time: {signal.status}.",
                    reason_code=SIGNAL_TERMINAL,
                    now=now,
                )
                session.commit()
                self._publish_locked_update(record)
                return _result(
                    record,
                    touched=False,
                    reason=record.failure_reason,
                    current_price=current_price,
                    entry_zone_distance_bps=entry_zone_distance_bps,
                )
            material = _material_change_evaluation(record, signal)
            if material.material:
                _mark_requires_reconfirmation_locked(
                    record,
                    current_signal=signal,
                    current_trade_plan_hash=material.current_hash,
                    current_trade_plan_snapshot=material.current_normalized,
                    change_summary=material.summary,
                    now=now,
                )
                session.commit()
                self._publish_locked_update(record)
                return _result(
                    record,
                    touched=False,
                    reason=record.failure_reason,
                    current_price=current_price,
                    entry_zone_distance_bps=entry_zone_distance_bps,
                )
            if (
                material.current_hash is not None
                and material.current_hash != record.accepted_trade_plan_hash
            ):
                _record_market_review_locked(
                    record,
                    signal=signal,
                    material_summary=material.summary,
                    material_change_pending_review=False,
                    now=now,
                )

            touch = entry_zone_touch(
                side=record.side,
                entry_min=record.entry_min,
                entry_max=record.entry_max,
                market_tick=market_tick,
            )
            if not touch.touched:
                session.commit()
                return PendingEntryTriggerResult(
                    intent_id=str(record.id),
                    status=record.status,
                    touched=False,
                    signal_id=str(record.signal_id),
                    price=touch.price,
                    price_source=touch.price_source,
                    reason="Entry zone was not touched.",
                    reason_code=ENTRY_ZONE_NOT_TOUCHED,
                    current_price=touch.price,
                    entry_zone_distance_bps=_entry_zone_distance_bps(
                        record.side,
                        record.entry_min,
                        record.entry_max,
                        touch.price,
                    ),
                    warnings=touch.warnings,
                    lifecycle_trace=LifecycleTrace(
                        signal_id=str(record.signal_id),
                        pending_entry_intent_id=str(record.id),
                    ),
                )

            _transition_locked(record, status="triggered", failure_reason=None, now=now)
            session.commit()
            self._publish_locked_update(record)

        return self._execute_triggered_intent(
            intent_id=intent_id,
            signal=signal,
            market_tick=market_tick,
            touch=touch,
        )

    def _execute_triggered_intent(
        self,
        *,
        intent_id: str | UUID,
        signal: RadarSignal,
        market_tick: Any,
        touch: EntryTouchResult,
    ) -> PendingEntryTriggerResult:
        intent = self._transition_status(
            intent_id,
            status="filling",
            failure_reason=None,
            now=_utc_now(),
        )
        if intent is None:
            return PendingEntryTriggerResult(
                intent_id=str(intent_id),
                status="failed",
                touched=True,
                signal_id=signal.id,
                price=touch.price,
                price_source=touch.price_source,
                reason="Triggered pending entry intent disappeared before fill.",
                warnings=touch.warnings,
                lifecycle_trace=LifecycleTrace(signal_id=signal.id),
            )
        if intent.mode != "virtual":
            return self._finish_structural_failure(
                intent,
                "Tick-driven pending real execution is not enabled in this virtual trigger service.",
                touch,
                reason_code=REAL_PENDING_EXECUTION_NOT_ENABLED,
            )

        try:
            request = _trigger_confirm_request(intent, market_tick, touch)
        except ValueError as exc:
            return self._finish_structural_failure(
                intent,
                str(exc),
                touch,
                reason_code=PENDING_ENTRY_EXECUTION_INVALID,
            )

        try:
            execution_signal = _execution_signal_from_accepted_snapshot(signal, intent)
        except ValueError as exc:
            return self._finish_structural_failure(
                intent,
                str(exc),
                touch,
                reason_code=PENDING_ENTRY_EXECUTION_INVALID,
            )
        try:
            _, trade = self._virtual_trading.confirm_signal(execution_signal, request)
        except StrategyRiskRewardBlocked as exc:
            return self._finish_structural_failure(
                intent,
                exc.reason,
                touch,
                reason_code=RISK_GATE_REJECTED,
            )
        except VirtualExecutionRejected as exc:
            reason = str(exc)
            if _is_temporary_virtual_execution_rejection(exc):
                return self._finish_temporary_failure(
                    intent,
                    reason,
                    touch,
                    gate_snapshot=_virtual_rejection_gate_snapshot(exc),
                )
            return self._finish_structural_failure(
                intent,
                reason,
                touch,
                reason_code=VIRTUAL_EXECUTION_REJECTED,
                gate_snapshot=_virtual_rejection_gate_snapshot(exc),
            )
        except ValueError as exc:
            reason = str(exc) or exc.__class__.__name__
            if _is_temporary_riskgate_failure(reason):
                return self._finish_temporary_failure(intent, reason, touch)
            return self._finish_structural_failure(
                intent,
                reason,
                touch,
                reason_code=RISK_GATE_REJECTED,
            )

        filled = self._transition_status(
            intent.id,
            status="filled",
            filled_trade_id=trade.id,
            failure_reason=None,
            now=_utc_now(),
        )
        return PendingEntryTriggerResult(
            intent_id=str(intent.id),
            status=filled.status if filled is not None else "filled",
            touched=True,
            signal_id=str(intent.signal_id),
            price=touch.price,
            price_source=touch.price_source,
            virtual_trade_id=trade.id,
            risk_decision_id=_trade_risk_decision_id(trade),
            current_price=touch.price,
            entry_zone_distance_bps=_entry_zone_distance_bps(
                intent.side,
                intent.entry_min,
                intent.entry_max,
                touch.price,
            ),
            warnings=touch.warnings,
            lifecycle_trace=_trade_lifecycle_trace(intent, trade),
        )

    def _finish_temporary_failure(
        self,
        intent: PendingEntryIntentRead,
        reason: str,
        touch: EntryTouchResult,
        gate_snapshot: dict[str, Any] | None = None,
    ) -> PendingEntryTriggerResult:
        updated = self._transition_status(
            intent.id,
            status="pending",
            failure_reason=reason,
            reason_code=TEMPORARY_EXECUTION_FAILURE,
            gate_snapshot=gate_snapshot,
            now=_utc_now(),
        )
        return PendingEntryTriggerResult(
            intent_id=str(intent.id),
            status=updated.status if updated is not None else "pending",
            touched=True,
            signal_id=str(intent.signal_id),
            price=touch.price,
            price_source=touch.price_source,
            reason=reason,
            reason_code=TEMPORARY_EXECUTION_FAILURE,
            gate_snapshot=gate_snapshot,
            current_price=touch.price,
            entry_zone_distance_bps=_entry_zone_distance_bps(
                intent.side,
                intent.entry_min,
                intent.entry_max,
                touch.price,
            ),
            warnings=touch.warnings,
            lifecycle_trace=_intent_lifecycle_trace(intent),
        )

    def _finish_structural_failure(
        self,
        intent: PendingEntryIntentRead,
        reason: str,
        touch: EntryTouchResult,
        *,
        reason_code: str,
        gate_snapshot: dict[str, Any] | None = None,
    ) -> PendingEntryTriggerResult:
        updated = self._transition_status(
            intent.id,
            status="failed",
            failure_reason=reason,
            reason_code=reason_code,
            gate_snapshot=gate_snapshot,
            now=_utc_now(),
        )
        return PendingEntryTriggerResult(
            intent_id=str(intent.id),
            status=updated.status if updated is not None else "failed",
            touched=True,
            signal_id=str(intent.signal_id),
            price=touch.price,
            price_source=touch.price_source,
            reason=reason,
            reason_code=reason_code,
            gate_snapshot=gate_snapshot,
            current_price=touch.price,
            entry_zone_distance_bps=_entry_zone_distance_bps(
                intent.side,
                intent.entry_min,
                intent.entry_max,
                touch.price,
            ),
            warnings=touch.warnings,
            lifecycle_trace=_intent_lifecycle_trace(intent),
        )

    def _transition_status(
        self,
        intent_id: str | UUID,
        *,
        status: str,
        failure_reason: str | None = None,
        filled_trade_id: str | UUID | None = None,
        reason_code: str | None = None,
        gate_snapshot: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        updated = self._pending_entries.transition_status(
            intent_id,
            status=status,
            failure_reason=failure_reason,
            filled_trade_id=filled_trade_id,
            reason_code=reason_code,
            gate_snapshot=gate_snapshot,
            now=now,
        )
        if updated is not None and not _provider_publishes_pending_entry_events(self._pending_entries):
            self._publish_update(updated)
        return updated

    def _publish_locked_update(self, record: PendingEntryIntent) -> None:
        try:
            intent = PendingEntryIntentRead.model_validate(record)
        except Exception as exc:
            logger.warning("Pending entry realtime event publish failed: %s", exc)
            return
        self._publish_update(intent)

    def _publish_update(self, intent: PendingEntryIntentRead) -> None:
        try:
            self._event_publisher.publish_update(intent)
        except Exception as exc:
            logger.warning("Pending entry realtime event publish failed: %s", exc)


def entry_zone_touch(
    *,
    side: str,
    entry_min: Decimal | float | str,
    entry_max: Decimal | float | str,
    market_tick: Any,
) -> EntryTouchResult:
    lower = _decimal(entry_min, "entry_min")
    upper = _decimal(entry_max, "entry_max")
    if upper < lower:
        lower, upper = upper, lower

    normalized_side = side.strip().lower()
    preferred_source = "ask" if normalized_side == "long" else "bid"
    preferred_price = _market_decimal(market_tick, preferred_source)
    warnings: list[str] = []
    if preferred_price is not None:
        return _touch_result(lower, upper, preferred_price, preferred_source, warnings)

    last_price = _market_decimal(market_tick, "last", "price")
    if last_price is not None:
        warnings.append(f"{preferred_source} is unavailable; entry touch used last price.")
        return _touch_result(lower, upper, last_price, "last", warnings)

    close_price = _market_decimal(market_tick, "close", "candle_close")
    if close_price is not None:
        warnings.append(f"{preferred_source} and last are unavailable; entry touch used candle close.")
        return _touch_result(lower, upper, close_price, "close", warnings)

    warnings.append(f"No usable {preferred_source}, last, or candle close price is available for entry touch.")
    return EntryTouchResult(touched=False, warnings=tuple(warnings))


def _trigger_confirm_request(
    intent: PendingEntryIntentRead,
    market_tick: Any,
    touch: EntryTouchResult,
) -> ManualConfirmRequest:
    try:
        request = ManualConfirmRequest.model_validate(dict(intent.request_snapshot or {}))
    except ValueError as exc:
        raise ValueError(f"Accepted pending-entry request snapshot is invalid: {exc}") from exc

    updates: dict[str, Any] = {
        "mode": intent.mode,
        "user_id": str(intent.user_id),
        "auto_enter_on_confirmation": True,
        "market_snapshot": _virtual_market_snapshot(market_tick, intent.side, touch),
        "metadata": _trigger_request_metadata(request, intent, touch, market_tick),
    }
    accepted_profile = _accepted_execution_profile(intent.execution_profile_snapshot)
    if accepted_profile is not None:
        updates["execution_profile"] = accepted_profile
        if accepted_profile.leverage is not None:
            updates["leverage"] = int(accepted_profile.leverage)
    if request.risk_override is None:
        risk_override = _risk_override_from_accepted_profile(intent.execution_profile_snapshot)
        if risk_override is not None:
            updates["risk_override"] = risk_override
    return request.model_copy(update=updates)


def _execution_signal_from_accepted_snapshot(
    signal: RadarSignal,
    intent: PendingEntryIntentRead,
) -> RadarSignal:
    trade_plan = _accepted_trade_plan_for_execution(intent)
    target_prices = _target_prices_for_signal(intent.targets_snapshot)
    accepted_signal = (
        intent.accepted_trade_plan_snapshot.get("accepted_signal")
        if isinstance(intent.accepted_trade_plan_snapshot, dict)
        else None
    )
    accepted_signal = accepted_signal if isinstance(accepted_signal, dict) else {}
    updates: dict[str, Any] = {
        "status": "entry_touched",
        "exchange": intent.exchange,
        "symbol": intent.symbol,
        "direction": intent.side,
        "entry_min": float(intent.entry_min),
        "entry_max": float(intent.entry_max),
        "stop_loss": float(intent.stop_loss),
        "take_profit_1": target_prices[0] if target_prices else None,
        "take_profit_2": target_prices[1] if len(target_prices) > 1 else None,
        "trade_plan": trade_plan,
    }
    for field_name in (
        "score",
        "confidence",
        "risk_reward",
        "first_target_rr",
        "final_target_rr",
        "selected_rr",
        "selected_rr_target",
        "min_rr_ratio",
    ):
        if accepted_signal.get(field_name) is not None:
            updates[field_name] = accepted_signal[field_name]
    return signal.model_copy(update=updates)


def _accepted_trade_plan_for_execution(intent: PendingEntryIntentRead) -> TradePlan:
    snapshot = dict(intent.accepted_trade_plan_snapshot or {})
    entry_min = _decimal(intent.entry_min, "entry_min")
    entry_max = _decimal(intent.entry_max, "entry_max")
    stop_loss = _decimal(intent.stop_loss, "stop_loss")
    entry = dict(snapshot.get("entry") if isinstance(snapshot.get("entry"), dict) else {})
    entry.update(
        {
            "min_price": float(entry_min),
            "max_price": float(entry_max),
            "price": float((entry_min + entry_max) / Decimal("2")),
        }
    )
    payload = {
        **snapshot,
        "entry": entry,
        "stop_loss": float(stop_loss),
        "targets": _targets_for_execution(intent.targets_snapshot),
        "invalidation": _invalidation_for_execution(snapshot, stop_loss),
    }
    metadata = dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {})
    metadata.update(
        {
            "source": "accepted_pending_entry_snapshot",
            "pending_entry_intent_id": str(intent.id),
            "accepted_trade_plan_hash": intent.accepted_trade_plan_hash,
        }
    )
    payload["metadata"] = metadata
    try:
        return TradePlan.model_validate(payload)
    except ValueError as exc:
        raise ValueError(f"Accepted pending-entry trade plan snapshot is invalid: {exc}") from exc


def _targets_for_execution(value: Any) -> list[dict[str, Any]]:
    raw_targets = value.get("targets") if isinstance(value, dict) else value
    if not isinstance(raw_targets, list):
        raw_targets = []
    targets: list[dict[str, Any]] = []
    for index, target in enumerate(raw_targets):
        target_payload = dict(target) if isinstance(target, dict) else {"price": target}
        price = _decimal(target_payload.get("price"), "target.price")
        target_payload["price"] = float(price)
        target_payload["label"] = str(target_payload.get("label") or f"TP{index + 1}")
        targets.append(target_payload)
    if not targets:
        raise ValueError("Accepted pending-entry snapshot requires at least one take-profit target.")
    return targets


def _target_prices_for_signal(value: Any) -> list[float]:
    return [float(_decimal(target["price"], "target.price")) for target in _targets_for_execution(value)]


def _invalidation_for_execution(snapshot: dict[str, Any], stop_loss: Decimal) -> dict[str, Any]:
    invalidation = snapshot.get("invalidation")
    if isinstance(invalidation, dict):
        payload = dict(invalidation)
    else:
        payload = {}
    payload["price"] = float(stop_loss)
    payload["hard_stop"] = float(stop_loss)
    metadata = dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {})
    metadata.setdefault("source", "accepted_pending_entry_snapshot")
    payload["metadata"] = metadata
    return payload


def _trigger_request_metadata(
    request: ManualConfirmRequest,
    intent: PendingEntryIntentRead,
    touch: EntryTouchResult,
    market_tick: Any,
) -> dict[str, Any]:
    metadata = dict(request.metadata or {})
    raw_trace = metadata.get("lifecycle_trace")
    trace = dict(raw_trace) if isinstance(raw_trace, dict) else {}
    trace.update(
        {
            "signal_id": str(intent.signal_id),
            "pending_entry_intent_id": str(intent.id),
        }
    )
    trigger_price = str(touch.price) if touch.price is not None else None
    metadata["pending_entry_intent_id"] = str(intent.id)
    metadata["accepted_trade_plan_hash"] = intent.accepted_trade_plan_hash
    metadata["trigger_source"] = "pending_entry"
    metadata["lifecycle_trace"] = trace
    metadata["origin"] = {
        **(metadata.get("origin") if isinstance(metadata.get("origin"), dict) else {}),
        "signal_id": str(intent.signal_id),
        "pending_entry_intent_id": str(intent.id),
        "strategy": None,
        "mode": intent.mode,
        "accepted_trade_plan_hash": intent.accepted_trade_plan_hash,
        "trigger_source": "pending_entry",
    }
    metadata["pending_entry_trigger"] = {
        "touch_price": trigger_price,
        "trigger_price": trigger_price,
        "trigger_reason": "entry_zone_touched",
        "touch_price_source": touch.price_source,
        "entry_candle_state": _market_value(market_tick, "candle_state"),
        "warnings": list(touch.warnings),
    }
    return metadata


def _accepted_execution_profile(snapshot: dict[str, Any]) -> StrategyExecutionSettings | None:
    if not snapshot:
        return None
    try:
        return StrategyExecutionSettings.model_validate(snapshot)
    except ValueError as exc:
        raise ValueError(f"Accepted execution profile snapshot is invalid: {exc}") from exc


def _risk_override_from_accepted_profile(snapshot: dict[str, Any]) -> RiskOverride | None:
    if not snapshot:
        return None
    risk_mode = snapshot.get("risk_mode")
    if risk_mode not in {"percent", "fixed"}:
        return None
    payload: dict[str, Any] = {"risk_mode": risk_mode}
    if risk_mode == "percent":
        payload["risk_percent"] = snapshot.get("risk_percent")
    else:
        payload["fixed_risk_amount"] = snapshot.get("fixed_risk_amount")
    if snapshot.get("leverage") is not None:
        payload["leverage"] = snapshot.get("leverage")
    try:
        return RiskOverride.model_validate(payload)
    except ValueError as exc:
        raise ValueError(f"Accepted execution profile risk override is invalid: {exc}") from exc


def _virtual_market_snapshot(
    market_tick: Any,
    side: str,
    touch: EntryTouchResult,
) -> VirtualMarketSnapshot:
    bid = _market_float(market_tick, "bid", "best_bid")
    ask = _market_float(market_tick, "ask", "best_ask")
    last = _market_float(market_tick, "last", "price")
    close = _market_float(market_tick, "close", "candle_close")
    timestamp = _market_int(market_tick, "timestamp")

    if touch.price is not None:
        touch_price = float(touch.price)
        if side == "long" and ask is None:
            ask = touch_price
        if side == "short" and bid is None:
            bid = touch_price

    recent_price = last or close or (float(touch.price) if touch.price is not None else None)
    recent_trades = (
        [RecentTradePrint(price=recent_price, timestamp=timestamp)]
        if recent_price is not None
        else []
    )
    return VirtualMarketSnapshot(best_bid=bid, best_ask=ask, recent_trades=recent_trades)


def _transition_locked(
    record: PendingEntryIntent,
    *,
    status: str,
    failure_reason: str | None,
    reason_code: str | None = None,
    gate_snapshot: dict[str, Any] | None = None,
    now: datetime,
) -> None:
    record.status = status
    record.updated_at = now
    record.failure_reason = failure_reason
    if reason_code is not None or gate_snapshot is not None:
        record.request_snapshot = _request_snapshot_with_reason_code(
            record.request_snapshot,
            status=status,
            reason_code=reason_code,
            gate_snapshot=gate_snapshot,
        )
    if status == "triggered" and record.triggered_at is None:
        record.triggered_at = now
    if status == "filled":
        record.filled_at = now


def _material_change_evaluation(record: PendingEntryIntent, signal: RadarSignal):
    accepted_payload = normalized_pending_entry_payload(
        exchange=record.exchange,
        symbol=record.symbol,
        side=record.side,
        entry_min=record.entry_min,
        entry_max=record.entry_max,
        stop_loss=record.stop_loss,
        targets_snapshot=record.targets_snapshot,
    )
    return evaluate_pending_entry_material_change(
        accepted_payload=accepted_payload,
        current_signal=signal,
        policy=material_change_policy_from_snapshot(record.accepted_trade_plan_snapshot),
        execution_profile_snapshot=record.execution_profile_snapshot,
        mode=record.mode,
    )


def _mark_requires_reconfirmation_locked(
    record: PendingEntryIntent,
    *,
    current_signal: RadarSignal,
    current_trade_plan_hash: str | None,
    current_trade_plan_snapshot: dict[str, Any] | None,
    change_summary: dict[str, Any],
    now: datetime,
) -> None:
    _transition_locked(
        record,
        status="requires_reconfirmation",
        failure_reason=TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
        reason_code=TRADE_PLAN_RECONFIRMATION_REQUIRED,
        now=now,
    )
    snapshot = dict(record.request_snapshot or {})
    raw_events = snapshot.get("pending_entry_lifecycle_events")
    lifecycle_events = list(raw_events) if isinstance(raw_events, list) else []
    lifecycle_events.append(
        {
            "event": "pending_entry.requires_reconfirmation",
            "created_at": now.isoformat(),
            "intent_id": str(record.id),
            "signal_id": str(record.signal_id),
            "reason": TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
            "accepted_trade_plan_hash": record.accepted_trade_plan_hash,
            "current_trade_plan_hash": current_trade_plan_hash,
            "accepted_trade_plan_snapshot": record.accepted_trade_plan_snapshot,
            "current_trade_plan_snapshot": current_trade_plan_snapshot,
            "change_summary": change_summary,
        }
    )
    snapshot["pending_entry_lifecycle_events"] = lifecycle_events[-20:]
    snapshot = _request_snapshot_with_market_review(
        snapshot,
        signal_id=str(current_signal.id),
        signal_status=current_signal.status,
        signal_exchange=current_signal.exchange,
        signal_symbol=current_signal.symbol,
        signal_side=current_signal.direction,
        signal_updated_at=current_signal.updated_at,
        signal_expires_at=current_signal.expires_at,
        material_summary=change_summary,
        material_change_pending_review=True,
        now=now,
    )
    record.request_snapshot = snapshot


def _record_market_review_locked(
    record: PendingEntryIntent,
    *,
    signal: RadarSignal,
    material_summary: dict[str, Any],
    material_change_pending_review: bool,
    now: datetime,
) -> None:
    record.request_snapshot = _request_snapshot_with_market_review(
        dict(record.request_snapshot or {}),
        signal_id=str(signal.id),
        signal_status=signal.status,
        signal_exchange=signal.exchange,
        signal_symbol=signal.symbol,
        signal_side=signal.direction,
        signal_updated_at=signal.updated_at,
        signal_expires_at=signal.expires_at,
        material_summary=material_summary,
        material_change_pending_review=material_change_pending_review,
        now=now,
    )
    record.updated_at = now


def _request_snapshot_with_reason_code(
    request_snapshot: Any,
    *,
    status: str,
    reason_code: str | None,
    gate_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(request_snapshot or {}) if isinstance(request_snapshot, dict) else {}
    if reason_code is not None:
        snapshot[PENDING_ENTRY_LAST_REASON_KEY] = reason_code
        if status in {"failed", "cancelled", "expired"}:
            snapshot[PENDING_ENTRY_TERMINAL_REASON_KEY] = reason_code
    if gate_snapshot is not None:
        snapshot[PENDING_ENTRY_GATE_SNAPSHOT_KEY] = gate_snapshot
    return snapshot


def _request_snapshot_with_market_review(
    request_snapshot: dict[str, Any],
    *,
    signal_id: str,
    signal_status: str,
    material_summary: dict[str, Any],
    material_change_pending_review: bool,
    now: datetime,
    signal_exchange: str | None = None,
    signal_symbol: str | None = None,
    signal_side: str | None = None,
    signal_updated_at: datetime | None = None,
    signal_expires_at: datetime | None = None,
) -> dict[str, Any]:
    snapshot = dict(request_snapshot or {})
    current_market_snapshot: dict[str, Any] = {
        "observed_at": now.isoformat(),
        "signal_id": signal_id,
        "status": signal_status,
        "material_change_pending_review": material_change_pending_review,
        "material_change_summary": material_summary,
    }
    if signal_exchange is not None:
        current_market_snapshot["exchange"] = signal_exchange
    if signal_symbol is not None:
        current_market_snapshot["symbol"] = signal_symbol
    if signal_side is not None:
        current_market_snapshot["side"] = signal_side
    if signal_updated_at is not None:
        current_market_snapshot["updated_at"] = signal_updated_at.isoformat()
    if signal_expires_at is not None:
        current_market_snapshot["expires_at"] = signal_expires_at.isoformat()
    if isinstance(material_summary.get("current_trade_plan_hash"), str):
        current_market_snapshot["trade_plan_hash"] = material_summary["current_trade_plan_hash"]
    snapshot["current_market_snapshot"] = current_market_snapshot
    snapshot["material_change_pending_review"] = material_change_pending_review
    raw_warnings = snapshot.get("pending_entry_warnings")
    warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []
    if material_change_pending_review:
        warnings.append("Pending entry material change requires user review.")
    elif material_summary.get("current_trade_plan_hash") is not None:
        warnings.append("Pending entry live signal changed without material execution-plan impact.")
    snapshot["pending_entry_warnings"] = _dedupe_strings(warnings)[-20:]
    return snapshot


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _result(
    record: PendingEntryIntent,
    *,
    touched: bool,
    reason: str | None,
    current_price: Decimal | None = None,
    entry_zone_distance_bps: Decimal | None = None,
) -> PendingEntryTriggerResult:
    snapshot = record.request_snapshot if isinstance(record.request_snapshot, dict) else {}
    reason_code = snapshot.get(PENDING_ENTRY_TERMINAL_REASON_KEY) or snapshot.get(PENDING_ENTRY_LAST_REASON_KEY)
    gate_snapshot = snapshot.get(PENDING_ENTRY_GATE_SNAPSHOT_KEY)
    trace = LifecycleTrace(
        signal_id=str(record.signal_id),
        pending_entry_intent_id=str(record.id),
        virtual_trade_id=str(record.filled_trade_id) if record.filled_trade_id is not None else None,
    )
    return PendingEntryTriggerResult(
        intent_id=str(record.id),
        status=record.status,
        touched=touched,
        signal_id=str(record.signal_id),
        virtual_trade_id=str(record.filled_trade_id) if record.filled_trade_id is not None else None,
        reason=reason,
        reason_code=str(reason_code) if reason_code is not None else None,
        gate_snapshot=gate_snapshot if isinstance(gate_snapshot, dict) else None,
        current_price=current_price,
        entry_zone_distance_bps=entry_zone_distance_bps,
        lifecycle_trace=trace,
    )


def _touch_result(
    lower: Decimal,
    upper: Decimal,
    price: Decimal,
    source: str,
    warnings: list[str],
) -> EntryTouchResult:
    return EntryTouchResult(
        touched=lower <= price <= upper,
        price=price,
        price_source=source,
        warnings=tuple(warnings),
    )


def _current_price_for_intent(record: PendingEntryIntent, market_tick: Any) -> Decimal | None:
    preferred = "ask" if record.side == "long" else "bid"
    return _market_decimal(market_tick, preferred, "last", "price", "close", "candle_close")


def _entry_zone_distance_bps(
    side: str,
    entry_min: Decimal | float | str,
    entry_max: Decimal | float | str,
    current_price: Decimal | None,
) -> Decimal | None:
    if current_price is None:
        return None
    lower = _decimal(entry_min, "entry_min")
    upper = _decimal(entry_max, "entry_max")
    if upper < lower:
        lower, upper = upper, lower
    price = _decimal(current_price, "current_price")
    if lower <= price <= upper:
        return Decimal("0")
    boundary = lower if price < lower else upper
    return ((abs(price - boundary) / boundary) * Decimal("10000")).quantize(Decimal("0.0001"))


def _market_decimal(market_tick: Any, *names: str) -> Decimal | None:
    for name in names:
        value = _market_value(market_tick, name)
        if value is None:
            continue
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if number > 0:
            return number
    return None


def _market_float(market_tick: Any, *names: str) -> float | None:
    number = _market_decimal(market_tick, *names)
    return float(number) if number is not None else None


def _market_int(market_tick: Any, *names: str) -> int | None:
    for name in names:
        value = _market_value(market_tick, name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _market_value(market_tick: Any, name: str) -> Any:
    if isinstance(market_tick, dict):
        return market_tick.get(name)
    value = getattr(market_tick, name, None)
    if value is not None:
        return value
    if name == "bid":
        return getattr(market_tick, "best_bid", None)
    if name == "ask":
        return getattr(market_tick, "best_ask", None)
    if name == "last":
        return getattr(market_tick, "price", None)
    return None


def _decimal(value: Decimal | float | str, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if number <= 0:
        raise ValueError(f"{field_name} must be positive")
    return number


def _is_temporary_riskgate_failure(reason: str) -> bool:
    normalized = reason.lower()
    return any(marker in normalized for marker in TEMPORARY_RISKGATE_REASON_MARKERS)


def _is_temporary_virtual_execution_rejection(exc: VirtualExecutionRejected) -> bool:
    report = exc.report
    values = [
        report.rejected_reason,
        report.fill_result.reason if report.fill_result is not None else None,
        *(report.quality_gate.blockers or []),
        *(report.notes or []),
        str(exc),
    ]
    normalized = " ".join(str(value).lower() for value in values if value)
    return "market_data_stale" in normalized or "market_data_missing" in normalized or _is_temporary_riskgate_failure(normalized)


def _virtual_rejection_gate_snapshot(exc: VirtualExecutionRejected) -> dict[str, Any]:
    report = exc.report
    snapshot: dict[str, Any] = {
        "status": report.status,
        "rejected_reason": report.rejected_reason,
        "reason_code": report.reason_code,
        "reason_codes": list(report.reason_codes or []),
        "blockers": list(report.blockers or []),
    }
    if report.quality_gate is not None:
        snapshot["quality_gate"] = report.quality_gate.model_dump(mode="json", exclude_none=True)
    if report.fill_result is not None:
        snapshot["fill_result"] = report.fill_result.model_dump(mode="json", exclude_none=True)
    return {key: value for key, value in snapshot.items() if value not in (None, [], {})}


def _intent_lifecycle_trace(intent: PendingEntryIntentRead) -> LifecycleTrace:
    return LifecycleTrace(
        signal_id=str(intent.signal_id),
        pending_entry_intent_id=str(intent.id),
        virtual_trade_id=str(intent.filled_trade_id) if intent.filled_trade_id is not None else None,
    )


def _trade_lifecycle_trace(intent: PendingEntryIntentRead, trade: VirtualTrade) -> LifecycleTrace:
    trace = trade.lifecycle_trace.model_copy(
        update={
            "signal_id": str(intent.signal_id),
            "pending_entry_intent_id": str(intent.id),
            "virtual_trade_id": trade.id,
            "risk_decision_id": _trade_risk_decision_id(trade),
        }
    )
    return trace


def _trade_risk_decision_id(trade: VirtualTrade) -> str | None:
    if trade.lifecycle_trace.risk_decision_id is not None:
        return trade.lifecycle_trace.risk_decision_id
    if trade.execution is None or trade.execution.risk_decision is None:
        return None
    return trade.execution.risk_decision.lifecycle_trace.risk_decision_id


def _provider_publishes_pending_entry_events(provider: PendingEntryProvider) -> bool:
    return getattr(provider, "publishes_pending_entry_events", False) is True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


pending_entry_trigger_service = PendingEntryTriggerService()
