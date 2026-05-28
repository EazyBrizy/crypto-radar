import unittest
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.schemas.notification import (
    NotificationCreateRequest,
    NotificationDeliveryResponse,
    NotificationResponse,
)
from app.services.notification_service import NotificationService


class FakeHotStore:
    def __init__(self) -> None:
        self.notifications: list[NotificationResponse] = []

    def write_notification(self, notification: NotificationResponse) -> None:
        self.notifications.append(notification)


class FakeBroker:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, event: dict[str, object]) -> None:
        self.events.append(event)


class FakeSessionFactory:
    pass


class SpyNotificationService(NotificationService):
    def __init__(self, hot_store: FakeHotStore, broker: FakeBroker) -> None:
        super().__init__(session_factory=FakeSessionFactory(), hot_store=hot_store, broker=broker)  # type: ignore[arg-type]
        self.marked: list[tuple[UUID, str, str | None]] = []
        self.created = _notification()

    def _create_notification_record(self, request: NotificationCreateRequest) -> NotificationResponse:
        return self.created.model_copy(
            update={
                "type": request.type,
                "title": request.title,
                "body": request.body,
                "payload": request.payload,
            }
        )

    def get_notification(self, notification_id: str) -> NotificationResponse:
        return self.created

    def _mark_websocket_delivered(
        self,
        notification_id: UUID,
        provider_msg_id: str,
        redis_error: str | None,
    ) -> None:
        self.marked.append((notification_id, provider_msg_id, redis_error))


class NotificationServiceContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_notification_writes_hot_store_and_realtime_fanout(self) -> None:
        hot_store = FakeHotStore()
        broker = FakeBroker()
        service = SpyNotificationService(hot_store, broker)

        notification = await service.create_notification(
            NotificationCreateRequest(
                type="system.test",
                title="Notification test",
                body="fanout",
                payload={"source": "unit"},
                channels=["websocket", "email"],
            )
        )

        self.assertEqual(notification.title, "Notification test")
        self.assertEqual(hot_store.notifications[0].id, notification.id)
        self.assertEqual(broker.events[0]["type"], "notification.created")
        self.assertEqual(broker.events[0]["payload"]["notificationId"], str(notification.id))
        self.assertEqual(service.marked[0][0], notification.id)
        self.assertTrue(service.marked[0][1].startswith("evt_"))


def _notification() -> NotificationResponse:
    now = datetime.now(timezone.utc)
    notification_id = uuid4()
    return NotificationResponse(
        id=notification_id,
        user_id=uuid4(),
        type="system.test",
        title="Notification test",
        body="body",
        payload={},
        is_read=False,
        created_at=now,
        deliveries=[
            NotificationDeliveryResponse(
                id=uuid4(),
                notification_id=notification_id,
                channel="websocket",
                status="queued",
                provider_msg_id=None,
                sent_at=None,
                error=None,
            )
        ],
    )


if __name__ == "__main__":
    unittest.main()
