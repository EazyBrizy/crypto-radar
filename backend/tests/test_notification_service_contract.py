import unittest
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.schemas.notification import (
    NotificationCreateRequest,
    NotificationDeliveryResponse,
    NotificationResponse,
)
from app.schemas.signal import RadarSignal, SignalEdgeSnapshot, SignalExecutionGateSnapshot
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

    async def test_signal_notification_is_execution_ready_contract(self) -> None:
        hot_store = FakeHotStore()
        broker = FakeBroker()
        service = SpyNotificationService(hot_store, broker)

        await service.create_signal_notification(_signal())

        notification = hot_store.notifications[0]
        self.assertEqual(notification.type, "signal.execution_ready")
        self.assertEqual(notification.title, "Execution signal")
        self.assertIn("BTCUSDT LONG 15m", notification.body or "")
        self.assertEqual(notification.payload["signal_id"], "sig_execution")
        self.assertEqual(notification.payload["feed_kind"], "execution_signal")
        self.assertEqual(notification.payload["execution_gate"]["status"], "passed")
        self.assertEqual(notification.payload["selected_rr"], 2.5)
        self.assertEqual(notification.payload["status_reason"], "trigger confirmed")
        self.assertEqual(notification.payload["edge"]["status"], "positive")


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


def _signal() -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_execution",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        score=82,
        status="actionable",
        status_reason="trigger confirmed",
        timeframe="15m",
        candle_state="closed",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        selected_rr=2.5,
        created_at=now,
        updated_at=now,
        edge=SignalEdgeSnapshot(
            status="positive",
            sample_size=80,
            min_sample_size=50,
            expectancy_after_costs_r=0.18,
            profit_factor=1.4,
            confidence_score=0.8,
            source="outcome",
        ),
        execution_gate=SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="execution_signal",
            can_notify=True,
            can_enter_now=True,
            can_arm_pending=True,
            can_show_in_execution_feed=True,
        ),
    )


if __name__ == "__main__":
    unittest.main()
