import json
import logging
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.models.notification import Notification, NotificationDelivery
from app.schemas.notification import (
    NotificationCreateRequest,
    NotificationDeliveryResponse,
    NotificationResponse,
    NotificationTestRequest,
    NotificationUpdateRequest,
)
from app.schemas.signal import RadarSignal
from app.services.message_broker import RedisMessageBroker, realtime_event_broker
from app.services.realtime_events import notification_created_event
from app.services.user_identity import resolve_app_user

logger = logging.getLogger(__name__)

NOTIFICATION_STREAM = "stream:notifications"
NOTIFICATION_PUBSUB = "pubsub:notifications:new"


class NotificationHotStore(Protocol):
    def write_notification(self, notification: NotificationResponse) -> None:
        ...


class RedisNotificationHotStore:
    _max_stream_items = 10_000

    def write_notification(self, notification: NotificationResponse) -> None:
        payload = json.dumps(notification.model_dump(mode="json"), ensure_ascii=False, default=str)
        client = get_redis_client()
        client.xadd(
            NOTIFICATION_STREAM,
            {
                "notification_id": str(notification.id),
                "user_id": str(notification.user_id),
                "type": notification.type,
                "payload": payload,
            },
            maxlen=self._max_stream_items,
            approximate=True,
        )
        client.publish(NOTIFICATION_PUBSUB, payload)
        client.publish(f"pubsub:notifications:{notification.user_id}", payload)


class NullNotificationHotStore:
    def write_notification(self, notification: NotificationResponse) -> None:
        return None


class NotificationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        hot_store: NotificationHotStore | None = None,
        broker: RedisMessageBroker = realtime_event_broker,
    ) -> None:
        self._session_factory = session_factory
        self._hot_store = hot_store or RedisNotificationHotStore()
        self._broker = broker

    def list_notifications(
        self,
        user_id: str = "demo_user",
        *,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[NotificationResponse]:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            statement = _notification_select().where(Notification.user_id == user.id)
            if unread_only:
                statement = statement.where(Notification.is_read.is_(False))
            records = session.scalars(
                statement.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 200)))
            ).unique().all()
            return [_notification_to_response(record) for record in records]

    def get_notification(self, notification_id: str) -> NotificationResponse:
        with self._session_factory() as session:
            notification = _get_notification(session, notification_id)
            return _notification_to_response(notification)

    async def create_notification(self, request: NotificationCreateRequest) -> NotificationResponse:
        notification = self._create_notification_record(request)
        await self.dispatch_notification(notification)
        return self.get_notification(str(notification.id))

    async def create_test_notification(self, request: NotificationTestRequest) -> NotificationResponse:
        return await self.create_notification(
            NotificationCreateRequest(
                user_id=request.user_id,
                type="system.test",
                title="Notification test",
                body="Email and Telegram delivery are stubbed; WebSocket/Redis fanout is live.",
                payload={"stubbed": True, "source": "notifications.test"},
                channels=request.channels,
            )
        )

    async def create_alert_test_notification(
        self,
        *,
        user_id: str,
        alert_rule_id: str,
        title: str,
        body: str,
        payload: dict[str, Any],
        channels: list[str],
    ) -> NotificationResponse:
        return await self.create_notification(
            NotificationCreateRequest(
                user_id=user_id,
                type="alert.rule_test",
                title=title,
                body=body,
                payload={"alert_rule_id": alert_rule_id, **payload},
                channels=channels,
            )
        )

    async def create_signal_notification(self, signal: RadarSignal, user_id: str = "demo_user") -> NotificationResponse:
        gate = signal.execution_gate.model_dump(mode="json") if signal.execution_gate is not None else None
        edge = signal.edge.model_dump(mode="json") if signal.edge is not None else None
        return await self.create_notification(
            NotificationCreateRequest(
                user_id=user_id,
                type="signal.execution_ready",
                title="Execution signal",
                body=(
                    f"{signal.symbol} {signal.direction.upper()} {signal.timeframe} "
                    f"{signal.strategy} status {signal.status} score {round(signal.score)}"
                ),
                payload={
                    "signal_id": signal.id,
                    "symbol": signal.symbol,
                    "exchange": signal.exchange,
                    "direction": signal.direction,
                    "score": signal.score,
                    "timeframe": signal.timeframe,
                    "strategy": signal.strategy,
                    "status": signal.status,
                    "status_reason": signal.status_reason,
                    "selected_rr": signal.selected_rr,
                    "feed_kind": signal.execution_gate.feed_kind if signal.execution_gate is not None else None,
                    "execution_gate": gate,
                    "edge": edge,
                },
                channels=["websocket"],
            )
        )

    def update_notification(
        self,
        notification_id: str,
        request: NotificationUpdateRequest,
    ) -> NotificationResponse:
        with self._session_factory() as session:
            notification = _get_notification(session, notification_id)
            if request.is_read is not None:
                notification.is_read = request.is_read
            session.commit()
            return self.get_notification(notification_id)

    def mark_all_read(self, user_id: str = "demo_user") -> int:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            notifications = session.scalars(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.is_read.is_(False),
                )
            ).all()
            for notification in notifications:
                notification.is_read = True
            count = len(notifications)
            session.commit()
            return count

    def delete_notification(self, notification_id: str) -> None:
        with self._session_factory() as session:
            notification = _get_notification(session, notification_id)
            session.delete(notification)
            session.commit()

    async def dispatch_notification(self, notification: NotificationResponse) -> None:
        redis_error: str | None = None
        try:
            self._hot_store.write_notification(notification)
        except Exception as exc:
            redis_error = exc.__class__.__name__
            logger.warning("Redis notification fanout failed: %s", exc)

        event = notification_created_event(notification)
        await self._broker.publish(event)
        self._mark_websocket_delivered(notification.id, event["id"], redis_error)

    def _create_notification_record(self, request: NotificationCreateRequest) -> NotificationResponse:
        channels = _normalize_channels(request.channels)
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            user = resolve_app_user(session, request.user_id)
            notification = Notification(
                user_id=user.id,
                type=request.type.strip(),
                title=request.title.strip(),
                body=request.body,
                payload=request.payload,
            )
            notification.deliveries = [
                _build_delivery(channel, now)
                for channel in channels
            ]
            session.add(notification)
            session.commit()
            return self.get_notification(str(notification.id))

    def _mark_websocket_delivered(
        self,
        notification_id: UUID,
        provider_msg_id: str,
        redis_error: str | None,
    ) -> None:
        with self._session_factory() as session:
            deliveries = session.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == notification_id,
                    NotificationDelivery.channel == "websocket",
                )
            ).all()
            for delivery in deliveries:
                delivery.status = "sent"
                delivery.provider_msg_id = provider_msg_id
                delivery.sent_at = datetime.now(timezone.utc)
                delivery.error = f"Redis fanout failed: {redis_error}" if redis_error else None
            session.commit()


def _notification_select():
    return select(Notification).options(joinedload(Notification.deliveries))


def _get_notification(session: Session, notification_id: str) -> Notification:
    notification_uuid = _parse_uuid(notification_id)
    if notification_uuid is None:
        raise ValueError(f"Invalid notification id: {notification_id}")
    notification = session.scalars(
        _notification_select().where(Notification.id == notification_uuid)
    ).unique().one_or_none()
    if notification is None:
        raise LookupError(f"Notification not found: {notification_id}")
    return notification


def _parse_uuid(value: str | UUID) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_channels(channels: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for channel in channels or ["websocket"]:
        value = channel.strip().lower()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized or ["websocket"]


def _build_delivery(channel: str, now: datetime) -> NotificationDelivery:
    if channel == "websocket":
        return NotificationDelivery(channel=channel, status="queued")
    return NotificationDelivery(
        channel=channel,
        status="stubbed",
        provider_msg_id=f"stub:{channel}",
        sent_at=now,
        error="Provider delivery is not configured",
    )


def _notification_to_response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        user_id=notification.user_id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        payload=notification.payload,
        is_read=notification.is_read,
        created_at=notification.created_at,
        deliveries=[_delivery_to_response(delivery) for delivery in notification.deliveries],
    )


def _delivery_to_response(delivery: NotificationDelivery) -> NotificationDeliveryResponse:
    return NotificationDeliveryResponse(
        id=delivery.id,
        notification_id=delivery.notification_id,
        channel=delivery.channel,
        status=delivery.status,
        provider_msg_id=delivery.provider_msg_id,
        sent_at=delivery.sent_at,
        error=delivery.error,
    )


notification_service = NotificationService()
