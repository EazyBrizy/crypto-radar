from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.domain.signal_status import is_terminal_signal_status
from app.models.pending_entry import PendingEntryIntent
from app.schemas.lifecycle import LifecycleTrace
from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.risk import RiskOverride, StrategyExecutionSettings
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, RecentTradePrint, VirtualMarketSnapshot, VirtualTrade
from app.services.pending_entry import (
    TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
    accepted_trade_plan_hash,
    pending_entry_service,
)
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
from app.services.signal_service import signal_service
from app.services.virtual_trading import VirtualExecutionRejected, virtual_trading_service

logger = logging.getLogger(__name__)

TEMPORARY_RISKGATE_REASON_MARKERS: tuple[str, ...] = (
    "balance",
    "spread",
    "slippage",
    "stale",
    "orderbook",
    "order book",
    "market data",
    "depth",
    "liquidity",
    "fee",
    "funding",
    "maximum open virtual positions",
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
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        ...


class SignalProvider(Protocol):
    def get_signal(self, signal_id: str) -> RadarSignal | None:
        ...

    def update_auto_entry(
        self,
        signal_id: str,
        *,
        status: str,
        message: str | None = None,
        trade_id: str | None = None,
        event_type: str = "signal.updated",
    ) -> RadarSignal | None:
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
    ) -> None:
        self._pending_entries = pending_entries or pending_entry_service
        self._signals = signals or signal_service
        self._virtual_trading = virtual_trading or virtual_trading_service
        self._session_factory = session_factory

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
            signal = self._signals.get_signal(str(record.signal_id))
            if signal is None:
                _transition_locked(
                    record,
                    status="failed",
                    failure_reason="Pending entry signal is missing.",
                    now=now,
                )
                session.commit()
                return _result(record, touched=False, reason=record.failure_reason)
            if record.expires_at is not None and _as_utc(record.expires_at) <= now:
                _transition_locked(
                    record,
                    status="expired",
                    failure_reason="Pending entry intent expired before entry touch.",
                    now=now,
                )
                session.commit()
                return _result(record, touched=False, reason=record.failure_reason)
            if is_terminal_signal_status(signal.status):
                _transition_locked(
                    record,
                    status="cancelled",
                    failure_reason=f"Signal is terminal at trigger time: {signal.status}.",
                    now=now,
                )
                session.commit()
                return _result(record, touched=False, reason=record.failure_reason)
            try:
                current_hash = accepted_trade_plan_hash(signal)
            except ValueError as exc:
                _transition_locked(
                    record,
                    status="failed",
                    failure_reason=f"Current trade plan is invalid: {exc}",
                    now=now,
                )
                session.commit()
                return _result(record, touched=False, reason=record.failure_reason)
            if current_hash != record.accepted_trade_plan_hash:
                _mark_requires_reconfirmation_locked(
                    record,
                    current_trade_plan_hash=current_hash,
                    now=now,
                )
                session.commit()
                self._mirror_auto_entry(
                    record.signal_id,
                    status="requires_reconfirmation",
                    message=TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
                )
                return _result(record, touched=False, reason=record.failure_reason)

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
                    warnings=touch.warnings,
                    lifecycle_trace=LifecycleTrace(
                        signal_id=str(record.signal_id),
                        pending_entry_intent_id=str(record.id),
                    ),
                )

            _transition_locked(record, status="triggered", failure_reason=None, now=now)
            session.commit()

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
        intent = self._pending_entries.transition_status(
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
            )

        try:
            request = _trigger_confirm_request(intent, market_tick, touch)
        except ValueError as exc:
            return self._finish_structural_failure(intent, str(exc), touch)

        execution_signal = signal.model_copy(update={"status": "entry_touched"})
        try:
            _, trade = self._virtual_trading.confirm_signal(execution_signal, request)
        except StrategyRiskRewardBlocked as exc:
            return self._finish_structural_failure(intent, exc.reason, touch)
        except VirtualExecutionRejected as exc:
            reason = str(exc)
            return self._finish_temporary_failure(intent, reason, touch)
        except ValueError as exc:
            reason = str(exc) or exc.__class__.__name__
            if _is_temporary_riskgate_failure(reason):
                return self._finish_temporary_failure(intent, reason, touch)
            return self._finish_structural_failure(intent, reason, touch)

        filled = self._pending_entries.transition_status(
            intent.id,
            status="filled",
            filled_trade_id=trade.id,
            failure_reason=None,
            now=_utc_now(),
        )
        self._mirror_auto_entry(intent.signal_id, status="filled", message=None, trade_id=trade.id)
        return PendingEntryTriggerResult(
            intent_id=str(intent.id),
            status=filled.status if filled is not None else "filled",
            touched=True,
            signal_id=str(intent.signal_id),
            price=touch.price,
            price_source=touch.price_source,
            virtual_trade_id=trade.id,
            risk_decision_id=_trade_risk_decision_id(trade),
            warnings=touch.warnings,
            lifecycle_trace=_trade_lifecycle_trace(intent, trade),
        )

    def _finish_temporary_failure(
        self,
        intent: PendingEntryIntentRead,
        reason: str,
        touch: EntryTouchResult,
    ) -> PendingEntryTriggerResult:
        updated = self._pending_entries.transition_status(
            intent.id,
            status="pending",
            failure_reason=reason,
            now=_utc_now(),
        )
        self._mirror_auto_entry(intent.signal_id, status="pending", message=reason)
        return PendingEntryTriggerResult(
            intent_id=str(intent.id),
            status=updated.status if updated is not None else "pending",
            touched=True,
            signal_id=str(intent.signal_id),
            price=touch.price,
            price_source=touch.price_source,
            reason=reason,
            warnings=touch.warnings,
            lifecycle_trace=_intent_lifecycle_trace(intent),
        )

    def _finish_structural_failure(
        self,
        intent: PendingEntryIntentRead,
        reason: str,
        touch: EntryTouchResult,
    ) -> PendingEntryTriggerResult:
        updated = self._pending_entries.transition_status(
            intent.id,
            status="failed",
            failure_reason=reason,
            now=_utc_now(),
        )
        self._mirror_auto_entry(intent.signal_id, status="failed", message=reason)
        return PendingEntryTriggerResult(
            intent_id=str(intent.id),
            status=updated.status if updated is not None else "failed",
            touched=True,
            signal_id=str(intent.signal_id),
            price=touch.price,
            price_source=touch.price_source,
            reason=reason,
            warnings=touch.warnings,
            lifecycle_trace=_intent_lifecycle_trace(intent),
        )

    def _mirror_auto_entry(
        self,
        signal_id: str | UUID,
        *,
        status: str,
        message: str | None,
        trade_id: str | None = None,
    ) -> None:
        update = getattr(self._signals, "update_auto_entry", None)
        if update is None:
            return
        try:
            update(str(signal_id), status=status, message=message, trade_id=trade_id)
        except Exception as exc:
            logger.warning("Pending entry legacy auto-entry mirror update failed: %s", exc)


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
        "metadata": _trigger_request_metadata(request, intent, touch),
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


def _trigger_request_metadata(
    request: ManualConfirmRequest,
    intent: PendingEntryIntentRead,
    touch: EntryTouchResult,
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
    metadata["pending_entry_intent_id"] = str(intent.id)
    metadata["lifecycle_trace"] = trace
    metadata["pending_entry_trigger"] = {
        "touch_price": str(touch.price) if touch.price is not None else None,
        "touch_price_source": touch.price_source,
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
    now: datetime,
) -> None:
    record.status = status
    record.updated_at = now
    record.failure_reason = failure_reason
    if status == "triggered" and record.triggered_at is None:
        record.triggered_at = now
    if status == "filled":
        record.filled_at = now


def _mark_requires_reconfirmation_locked(
    record: PendingEntryIntent,
    *,
    current_trade_plan_hash: str,
    now: datetime,
) -> None:
    _transition_locked(
        record,
        status="requires_reconfirmation",
        failure_reason=TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
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
        }
    )
    snapshot["pending_entry_lifecycle_events"] = lifecycle_events[-20:]
    record.request_snapshot = snapshot


def _result(
    record: PendingEntryIntent,
    *,
    touched: bool,
    reason: str | None,
) -> PendingEntryTriggerResult:
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


pending_entry_trigger_service = PendingEntryTriggerService()
