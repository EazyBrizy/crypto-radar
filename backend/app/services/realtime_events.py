import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.schemas.notification import NotificationResponse
from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.signal import RadarSignal
from app.schemas.trade import TradeInvalidationAlert, TradeJournalEntry, VirtualTrade

RealtimeEventType = Literal[
    "signal.created",
    "signal.updated",
    "signal.invalidated",
    "signal.expired",
    "trade.activated",
    "trade.updated",
    "trade.closed",
    "trade.invalidation",
    "take_profit.hit",
    "stop_loss.hit",
    "price.touched_entry",
    "order.status_changed",
    "pending_entry.updated",
    "notification.created",
    "connection.heartbeat",
    "subscription.updated",
    "radar.status",
]


def create_realtime_event(
    event_type: RealtimeEventType,
    payload: dict[str, Any],
    *,
    version: int = 1,
) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid4().hex}",
        "type": event_type,
        "version": version,
        "timestamp": _utc_timestamp(),
        "payload": _to_json_compatible(payload),
    }


def signal_created_event(signal: RadarSignal) -> dict[str, Any]:
    return _signal_event("signal.created", signal)


def signal_updated_event(signal: RadarSignal) -> dict[str, Any]:
    return _signal_event("signal.updated", signal)


def signal_invalidated_event(signal: RadarSignal, reason: str | None = None) -> dict[str, Any]:
    payload = _signal_payload(signal)
    payload["reason"] = reason
    return create_realtime_event("signal.invalidated", payload)


def signal_expired_event(signal: RadarSignal, reason: str | None = None) -> dict[str, Any]:
    payload = _signal_payload(signal)
    payload["reason"] = reason or "ttl_expired"
    return create_realtime_event("signal.expired", payload)


def trade_activated_event(trade: VirtualTrade | TradeJournalEntry) -> dict[str, Any]:
    payload = _trade_payload(trade)
    payload["entryPrice"] = trade.entry_price
    return create_realtime_event("trade.activated", payload)


def trade_updated_event(trade: VirtualTrade | TradeJournalEntry) -> dict[str, Any]:
    return create_realtime_event("trade.updated", _trade_payload(trade))


def trade_closed_event(trade: VirtualTrade | TradeJournalEntry) -> dict[str, Any]:
    payload = _trade_payload(trade)
    payload["exitPrice"] = trade.exit_price
    payload["pnl"] = trade.pnl
    payload["pnlPercent"] = trade.pnl_percent
    return create_realtime_event(
        "trade.closed",
        payload,
    )


def trade_invalidation_event(alert: TradeInvalidationAlert) -> dict[str, Any]:
    alert_payload = _model_payload(alert)
    return create_realtime_event(
        "trade.invalidation",
        {
            "alert": alert_payload,
            "tradeId": alert.trade_id,
            "signalId": alert.signal_id,
            "pair": alert.symbol,
            "exchange": alert.exchange,
            "side": alert.side.upper(),
            "reason": alert.reason,
            "triggeredConditions": alert.triggered_conditions,
            "fingerprint": alert.fingerprint,
        },
    )


def take_profit_hit_event(trade: VirtualTrade | TradeJournalEntry) -> dict[str, Any]:
    target_event = _latest_lifecycle_event(trade, {"partial_take_profit", "take_profit"})
    trade_payload = _model_payload(trade)
    return create_realtime_event(
        "take_profit.hit",
        {
            "tradeId": trade.id,
            "signalId": trade.signal_id,
            "pair": trade.symbol,
            "exchange": trade.exchange,
            "price": trade.exit_price or trade.current_price,
            "target": target_event.get("target_label") or "TP1",
            "targetPrice": target_event.get("metadata", {}).get("trigger_price")
            if target_event
            else (trade.take_profit[-1] if trade.take_profit else None),
            "trade": trade_payload,
        },
    )


def stop_loss_hit_event(trade: VirtualTrade | TradeJournalEntry) -> dict[str, Any]:
    trade_payload = _model_payload(trade)
    return create_realtime_event(
        "stop_loss.hit",
        {
            "tradeId": trade.id,
            "signalId": trade.signal_id,
            "pair": trade.symbol,
            "exchange": trade.exchange,
            "price": trade.exit_price or trade.current_price,
            "stopLoss": trade.current_stop_loss or trade.stop_loss,
            "trade": trade_payload,
        },
    )


def price_touched_entry_event(signal: RadarSignal, price: float) -> dict[str, Any]:
    payload = _signal_payload(signal)
    payload["price"] = price
    return create_realtime_event("price.touched_entry", payload)


def order_status_changed_event(order_id: str, status: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return create_realtime_event(
        "order.status_changed",
        {
            "orderId": order_id,
            "status": status,
            "details": details or {},
        },
    )


def pending_entry_updated_event(
    intent: PendingEntryIntentRead,
    *,
    message: str | None = None,
) -> dict[str, Any]:
    reason = message if message is not None else intent.failure_reason
    pending_entry = intent.model_dump(mode="json")
    return create_realtime_event(
        "pending_entry.updated",
        {
            "pending_entry": pending_entry,
            "user_id": str(intent.user_id),
            "signal_id": str(intent.signal_id),
            "pending_entry_id": str(intent.id),
            "status": intent.status,
            "mode": intent.mode,
            "reason": reason,
            "message": reason,
            "updated_at": intent.updated_at.isoformat(),
        },
    )


def notification_created_event(notification: NotificationResponse) -> dict[str, Any]:
    payload = notification.model_dump(mode="json")
    return create_realtime_event(
        "notification.created",
        {
            "notification": payload,
            "notificationId": str(notification.id),
            "userId": str(notification.user_id),
            "kind": _notification_kind(notification.type),
            "title": notification.title,
            "body": notification.body,
            "payload": payload["payload"],
            "isRead": notification.is_read,
            "createdAt": notification.created_at.isoformat(),
        },
    )


def connection_heartbeat_event(status: str = "ok") -> dict[str, Any]:
    return create_realtime_event("connection.heartbeat", {"status": status})


def subscription_updated_event(status: str = "ok", channels: list[str] | None = None) -> dict[str, Any]:
    return create_realtime_event(
        "subscription.updated",
        {
            "status": status,
            "channels": channels or [],
        },
    )


def radar_status_event(status: dict[str, Any]) -> dict[str, Any]:
    return create_realtime_event("radar.status", {"status": status})


def _signal_event(event_type: Literal["signal.created", "signal.updated"], signal: RadarSignal) -> dict[str, Any]:
    return create_realtime_event(event_type, _signal_payload(signal))


def _signal_payload(signal: RadarSignal) -> dict[str, Any]:
    signal_payload = _model_payload(signal)
    return {
        "signal": signal_payload,
        "signalId": signal.id,
        "pair": signal.symbol,
        "exchange": signal.exchange.upper(),
        "side": signal.direction.upper(),
        "strategy": signal.strategy,
        "confidence": signal.score,
        "risk": signal.urgency.upper(),
        "entryZone": {
            "from": signal.entry_min,
            "to": signal.entry_max,
        },
        "stopLoss": signal.stop_loss,
        "takeProfit": [
            price
            for price in (signal.take_profit_1, signal.take_profit_2)
            if price is not None
        ],
        "timeframe": signal.timeframe,
    }


def _trade_payload(trade: VirtualTrade | TradeJournalEntry) -> dict[str, Any]:
    trade_payload = _model_payload(trade)
    return {
        "trade": trade_payload,
        "tradeId": trade.id,
        "signalId": trade.signal_id,
        "pair": trade.symbol,
        "exchange": trade.exchange,
        "side": trade.side.upper(),
        "status": trade.status,
        "entryPrice": trade.entry_price,
        "currentPrice": trade.current_price,
        "stopLoss": trade.stop_loss,
        "currentStopLoss": trade.current_stop_loss,
        "takeProfit": trade.take_profit,
        "initialQuantity": trade.initial_quantity,
        "remainingQuantity": trade.remaining_quantity,
        "closedQuantity": trade.closed_quantity,
        "initialSizeUsd": trade.initial_size_usd,
        "remainingSizeUsd": trade.remaining_size_usd,
        "realizedPnl": trade.realized_pnl,
        "unrealizedPnl": trade.unrealized_pnl,
        "exitFees": trade.exit_fees,
        "stopMovedToBreakeven": trade.stop_moved_to_breakeven,
        "trailingActive": trade.trailing_active,
        "targetStates": trade_payload["target_states"],
        "lifecycleEvents": trade_payload["lifecycle_events"],
        "riskAmount": trade.risk_amount,
        "riskReward": trade.risk_reward,
        "pnl": trade.pnl,
        "pnlPercent": trade.pnl_percent,
        "closeReason": trade.close_reason,
    }


def _latest_lifecycle_event(
    trade: VirtualTrade | TradeJournalEntry,
    event_types: set[str],
) -> dict[str, Any]:
    for event in reversed(trade.lifecycle_events):
        payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
        if isinstance(payload, dict) and payload.get("event_type") in event_types:
            return payload
    return {}


def _model_payload(value: BaseModel) -> dict[str, Any]:
    payload = value.model_dump(mode="json")
    if not isinstance(payload, dict):
        raise TypeError(f"{type(value).__name__}.model_dump(mode='json') did not return a dict")
    return payload


def _to_json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Realtime event payload contains a non-finite float")
        return value
    if isinstance(value, BaseModel):
        return _to_json_compatible(value.model_dump(mode="json"))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_compatible(item) for item in value]
    raise TypeError(f"Realtime event payload is not JSON-compatible: {type(value).__name__}")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _notification_kind(notification_type: str) -> str:
    if notification_type.startswith("signal"):
        return "signal"
    if notification_type.startswith("trade") or notification_type.startswith("virtual_trade"):
        return "trade"
    if notification_type.startswith("order"):
        return "order"
    if notification_type.startswith("alert"):
        return "alert"
    if notification_type.startswith("connection"):
        return "connection"
    return "system"
