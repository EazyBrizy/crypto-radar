import unittest
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid4

from app.schemas.notification import NotificationCreateRequest, NotificationDeliveryResponse, NotificationResponse
from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot
from app.services.notification_service import NotificationService
from app.workers.signal_worker import _should_notify_signal, _should_publish_created_signal


class SignalWorkerNotificationGateTest(unittest.TestCase):
    def test_notifications_are_created_only_for_execution_ready_signals(self) -> None:
        self.assertTrue(
            _should_notify_signal(
                _signal(
                    execution_gate=SignalExecutionGateSnapshot(
                        status="passed",
                        feed_kind="execution_signal",
                        can_notify=True,
                        can_enter_now=True,
                        can_arm_pending=True,
                        can_show_in_execution_feed=True,
                    )
                )
            )
        )
        self.assertFalse(
            _should_notify_signal(
                _signal(
                    execution_gate=SignalExecutionGateSnapshot(
                        status="warning",
                        feed_kind="watchlist",
                        can_notify=True,
                        can_enter_now=False,
                        can_arm_pending=False,
                        can_show_in_execution_feed=True,
                    )
                )
            )
        )
        self.assertFalse(
            _should_notify_signal(
                _signal(
                    execution_gate=SignalExecutionGateSnapshot(
                        status="blocked",
                        feed_kind="blocked",
                        can_notify=False,
                        can_enter_now=False,
                        can_arm_pending=False,
                        can_show_in_execution_feed=False,
                    )
                )
            )
        )

    def test_legacy_notification_fallback_is_strict(self) -> None:
        self.assertFalse(_should_notify_signal(_signal(execution_gate=None, score=23)))
        self.assertFalse(_should_notify_signal(_signal(execution_gate=None, candle_state="open")))
        self.assertFalse(_should_notify_signal(_signal(execution_gate=None, status="watchlist")))
        self.assertTrue(_should_notify_signal(_signal(execution_gate=None)))

    def test_terminal_signal_does_not_notify_even_with_stale_passed_gate(self) -> None:
        execution_gate = SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="execution_signal",
            can_notify=True,
            can_enter_now=True,
            can_arm_pending=True,
            can_show_in_execution_feed=True,
        )

        self.assertFalse(_should_notify_signal(_signal(status="invalidated", execution_gate=execution_gate)))

    def test_signal_worker_no_created_event_for_suppressed_duplicate(self) -> None:
        self.assertFalse(
            _should_publish_created_signal(
                _signal(status="rejected", execution_gate=_suppressed_execution_gate())
            )
        )

    def test_signal_worker_no_notification_for_suppressed_duplicate(self) -> None:
        stale_execution_gate = SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="execution_signal",
            can_notify=True,
            can_enter_now=True,
            can_arm_pending=True,
            can_show_in_execution_feed=True,
            metadata={"dedup": {"action": "suppress"}},
        )

        self.assertFalse(_should_notify_signal(_signal(execution_gate=stale_execution_gate)))

    def test_execution_ready_notifications_are_deduped_by_pair_and_direction(self) -> None:
        seen: set[tuple[str, str, str]] = set()
        execution_gate = SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="execution_signal",
            can_notify=True,
            can_enter_now=True,
            can_arm_pending=True,
            can_show_in_execution_feed=True,
        )

        self.assertTrue(_should_notify_signal(_signal(execution_gate=execution_gate), notified_execution_keys=seen))
        self.assertFalse(
            _should_notify_signal(
                _signal(symbol="BTC/USDT", execution_gate=execution_gate),
                notified_execution_keys=seen,
            )
        )
        self.assertTrue(
            _should_notify_signal(
                _signal(direction="short", execution_gate=execution_gate),
                notified_execution_keys=seen,
            )
        )


class SignalWorkerNotificationIdempotencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_signal_worker_no_duplicate_after_restart_simulation(self) -> None:
        clock = WorkerMutableClock()
        redis = WorkerFakeRedisDedup(clock)
        hot_store = WorkerFakeHotStore()
        service = WorkerSpyNotificationService(
            hot_store,
            clock=clock,
            redis_client_factory=lambda: redis,
        )
        execution_gate = SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="execution_signal",
            can_notify=True,
            can_enter_now=True,
            can_arm_pending=True,
            can_show_in_execution_feed=True,
        )

        first_restart_seen: set[tuple[str, str, str]] = set()
        first_signal = _signal(execution_gate=execution_gate)
        self.assertTrue(_should_notify_signal(first_signal, notified_execution_keys=first_restart_seen))
        first = await service.create_signal_notification(first_signal)

        second_restart_seen: set[tuple[str, str, str]] = set()
        second_signal = _signal(execution_gate=execution_gate)
        self.assertTrue(_should_notify_signal(second_signal, notified_execution_keys=second_restart_seen))
        second = await service.create_signal_notification(second_signal)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(hot_store.notifications), 1)


def _signal(
    *,
    symbol: str = "BTCUSDT",
    direction: str = "long",
    score: int = 82,
    status: str = "actionable",
    candle_state: str = "closed",
    execution_gate: SignalExecutionGateSnapshot | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(uuid4()),
        symbol=symbol,
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction=direction,
        confidence=0.82,
        score=score,
        status=status,
        timeframe="15m",
        candle_state=candle_state,
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        created_at=now,
        updated_at=now,
        execution_gate=execution_gate,
    )


class WorkerFakeHotStore:
    def __init__(self) -> None:
        self.notifications: list[NotificationResponse] = []

    def write_notification(self, notification: NotificationResponse) -> None:
        self.notifications.append(notification)


class WorkerFakeBroker:
    async def publish(self, event: dict[str, object]) -> None:
        return None


class WorkerFakeSessionFactory:
    pass


class WorkerFakeRedisDedup:
    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now
        self.values: dict[str, tuple[str, float | None]] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        now_ts = self._now().timestamp()
        self.values = {
            existing_key: existing_value
            for existing_key, existing_value in self.values.items()
            if existing_value[1] is None or existing_value[1] > now_ts
        }
        if nx and key in self.values:
            return None
        self.values[key] = (value, now_ts + ex if ex is not None else None)
        return True


class WorkerMutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class WorkerSpyNotificationService(NotificationService):
    def __init__(
        self,
        hot_store: WorkerFakeHotStore,
        *,
        clock: Callable[[], datetime],
        redis_client_factory: Callable[[], object],
    ) -> None:
        super().__init__(
            session_factory=WorkerFakeSessionFactory(),
            hot_store=hot_store,
            broker=WorkerFakeBroker(),  # type: ignore[arg-type]
            redis_client_factory=redis_client_factory,
            clock=clock,
        )  # type: ignore[arg-type]

    def _create_notification_record(self, request: NotificationCreateRequest) -> NotificationResponse:
        notification_id = uuid4()
        return NotificationResponse(
            id=notification_id,
            user_id=uuid4(),
            type=request.type,
            title=request.title,
            body=request.body,
            payload=request.payload,
            is_read=False,
            created_at=datetime.now(timezone.utc),
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

    def get_notification(self, notification_id: str) -> NotificationResponse:
        return _notification_response(UUID(notification_id))

    def _mark_websocket_delivered(
        self,
        notification_id: UUID,
        provider_msg_id: str,
        redis_error: str | None,
    ) -> None:
        return None


def _notification_response(notification_id: UUID) -> NotificationResponse:
    return NotificationResponse(
        id=notification_id,
        user_id=uuid4(),
        type="signal.execution_ready",
        title="Execution signal",
        body="body",
        payload={},
        is_read=False,
        created_at=datetime.now(timezone.utc),
        deliveries=[],
    )


def _suppressed_execution_gate() -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="blocked",
        feed_kind="blocked",
        can_notify=False,
        can_enter_now=False,
        can_arm_pending=False,
        can_show_in_execution_feed=False,
        metadata={"dedup": {"action": "suppress"}},
    )


if __name__ == "__main__":
    unittest.main()
