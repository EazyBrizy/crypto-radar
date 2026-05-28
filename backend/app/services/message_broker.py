import asyncio
import contextlib
import json
import logging
from collections import deque
from collections.abc import Callable
from typing import Any

from app.core.redis_client import get_redis_client


RealtimeEvent = dict[str, Any]
BROKER_QUEUE_MAX_SIZE = 2_000
REALTIME_PUBSUB_CHANNEL = "pubsub:realtime"

logger = logging.getLogger(__name__)


class RedisMessageBroker:
    """Redis-backed realtime event broker with local socket queues.

    Redis Pub/Sub provides cross-process fanout. Local asyncio queues are only
    the per-process delivery bridge to active WebSocket/SSE connections.
    """

    def __init__(
        self,
        redis_client_factory: Callable[[], Any] = get_redis_client,
        *,
        channel: str = REALTIME_PUBSUB_CHANNEL,
        enable_redis: bool = True,
    ) -> None:
        self._redis_client_factory = redis_client_factory
        self._channel = channel
        self._enable_redis = enable_redis
        self._subscribers: set[asyncio.Queue[RealtimeEvent]] = set()
        self._listener_task: asyncio.Task[None] | None = None
        self._local_event_ids: deque[str] = deque(maxlen=2_000)
        self._local_event_id_set: set[str] = set()

    def subscribe(self) -> asyncio.Queue[RealtimeEvent]:
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=BROKER_QUEUE_MAX_SIZE)
        self._subscribers.add(queue)
        self._ensure_listener_started()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[RealtimeEvent]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: RealtimeEvent) -> None:
        self._remember_local_event(event)
        self._publish_local(event)
        if not self._enable_redis:
            return
        try:
            await asyncio.to_thread(
                self._redis_client_factory().publish,
                self._channel,
                json.dumps(event, ensure_ascii=False, default=str, separators=(",", ":")),
            )
        except Exception as exc:
            logger.warning("Redis realtime publish failed: %s", exc)

    async def stop(self) -> None:
        if self._listener_task is None:
            return
        self._listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._listener_task
        self._listener_task = None

    def _ensure_listener_started(self) -> None:
        if not self._enable_redis:
            return
        if self._listener_task is not None and not self._listener_task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._listener_task = asyncio.create_task(self._consume_redis_pubsub())

    async def _consume_redis_pubsub(self) -> None:
        pubsub = None
        try:
            pubsub = self._redis_client_factory().pubsub(ignore_subscribe_messages=True)
            await asyncio.to_thread(pubsub.subscribe, self._channel)
            while True:
                message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if not message:
                    await asyncio.sleep(0.01)
                    continue
                event = _decode_pubsub_event(message.get("data"))
                if event is None:
                    continue
                event_id = event.get("id")
                if isinstance(event_id, str) and event_id in self._local_event_id_set:
                    continue
                self._publish_local(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Redis realtime listener stopped: %s", exc)
        finally:
            if pubsub is not None:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(pubsub.close)

    def _publish_local(self, event: RealtimeEvent) -> None:
        for queue in list(self._subscribers):
            _put_latest(queue, event)

    def _remember_local_event(self, event: RealtimeEvent) -> None:
        event_id = event.get("id")
        if not isinstance(event_id, str):
            return
        if len(self._local_event_ids) == self._local_event_ids.maxlen:
            old_event_id = self._local_event_ids.popleft()
            self._local_event_id_set.discard(old_event_id)
        self._local_event_ids.append(event_id)
        self._local_event_id_set.add(event_id)


def _put_latest(queue: asyncio.Queue[RealtimeEvent], event: RealtimeEvent) -> None:
    try:
        queue.put_nowait(event)
        return
    except asyncio.QueueFull:
        pass

    dropped = False
    with contextlib.suppress(asyncio.QueueEmpty):
        queue.get_nowait()
        dropped = True
    if dropped:
        with contextlib.suppress(ValueError):
            queue.task_done()

    with contextlib.suppress(asyncio.QueueFull):
        queue.put_nowait(event)


def _decode_pubsub_event(data: Any) -> RealtimeEvent | None:
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    if not isinstance(data, str):
        return None
    try:
        event = json.loads(data)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


realtime_event_broker = RedisMessageBroker()
