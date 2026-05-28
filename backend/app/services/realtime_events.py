from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from app.schemas.notification import NotificationResponse
from app.schemas.signal import RadarSignal
from app.schemas.trade import TradeJournalEntry, VirtualTrade

RealtimeEventType = Literal[
    "signal.created",
    "signal.updated",
    "signal.invalidated",
    "trade.activated",
    "trade.updated",
    "trade.closed",
    "take_profit.hit",
    "stop_loss.hit",
    "price.touched_entry",
    "order.status_changed",
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
        "payload": payload,
    }


def signal_created_event(signal: RadarSignal) -> dict[str, Any]:
    return _signal_event("signal.created", signal)


def signal_updated_event(signal: RadarSignal) -> dict[str, Any]:
    return _signal_event("signal.updated", signal)


def signal_invalidated_event(signal: RadarSignal, reason: str | None = None) -> dict[str, Any]:
    payload = _signal_payload(signal)
    payload["reason"] = reason
    return create_realtime_event("signal.invalidated", payload)


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


def take_profit_hit_event(trade: VirtualTrade | TradeJournalEntry) -> dict[str, Any]:
    return create_realtime_event(
        "take_profit.hit",
        {
            "tradeId": trade.id,
            "signalId": trade.signal_id,
            "pair": trade.symbol,
            "exchange": trade.exchange,
            "price": trade.exit_price or trade.current_price,
            "target": "TP1",
            "targetPrice": trade.take_profit[-1] if trade.take_profit else None,
            "trade": trade,
        },
    )


def stop_loss_hit_event(trade: VirtualTrade | TradeJournalEntry) -> dict[str, Any]:
    return create_realtime_event(
        "stop_loss.hit",
        {
            "tradeId": trade.id,
            "signalId": trade.signal_id,
            "pair": trade.symbol,
            "exchange": trade.exchange,
            "price": trade.exit_price or trade.current_price,
            "stopLoss": trade.stop_loss,
            "trade": trade,
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
            "payload": notification.payload,
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
    return {
        "signal": signal,
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
    return {
        "trade": trade,
        "tradeId": trade.id,
        "signalId": trade.signal_id,
        "pair": trade.symbol,
        "exchange": trade.exchange,
        "side": trade.side.upper(),
        "status": trade.status,
        "entryPrice": trade.entry_price,
        "currentPrice": trade.current_price,
        "stopLoss": trade.stop_loss,
        "takeProfit": trade.take_profit,
        "riskAmount": trade.risk_amount,
        "riskReward": trade.risk_reward,
        "pnl": trade.pnl,
        "pnlPercent": trade.pnl_percent,
        "closeReason": trade.close_reason,
    }


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
