import asyncio
import contextlib
import json
import logging
from collections import deque
from collections.abc import Callable
from inspect import isawaitable
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.core.config import settings
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
        self._subscriber_loops: dict[asyncio.Queue[RealtimeEvent], asyncio.AbstractEventLoop | None] = {}
        self._listener_task: asyncio.Task[None] | None = None
        self._local_event_ids: deque[str] = deque(maxlen=2_000)
        self._local_event_id_set: set[str] = set()

    def subscribe(self) -> asyncio.Queue[RealtimeEvent]:
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=BROKER_QUEUE_MAX_SIZE)
        self._subscribers.add(queue)
        self._subscriber_loops[queue] = _running_loop_or_none()
        self._ensure_listener_started()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[RealtimeEvent]) -> None:
        self._subscribers.discard(queue)
        self._subscriber_loops.pop(queue, None)

    async def publish(self, event: RealtimeEvent) -> None:
        encoded_event = encode_realtime_event(event)
        self._remember_local_event(encoded_event)
        self._publish_local(encoded_event)
        if not self._enable_redis:
            return
        self._publish_redis_background(encoded_event)

    def _publish_redis_background(self, encoded_event: RealtimeEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._publish_redis(encoded_event))
        task.add_done_callback(_log_background_publish_exception)

    async def _publish_redis(self, encoded_event: RealtimeEvent) -> None:
        timeout_seconds = _configured_publish_timeout_seconds()
        try:
            await _await_with_optional_timeout(
                asyncio.to_thread(
                    self._redis_client_factory().publish,
                    self._channel,
                    json.dumps(
                        encoded_event,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ),
                ),
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "Redis realtime publish timed out after %.2f seconds: %s",
                timeout_seconds,
                encoded_event.get("type"),
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
            _put_latest_for_subscriber(queue, event, self._subscriber_loops.get(queue))

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


def _put_latest_for_subscriber(
    queue: asyncio.Queue[RealtimeEvent],
    event: RealtimeEvent,
    loop: asyncio.AbstractEventLoop | None,
) -> None:
    if loop is None or not loop.is_running() or loop is _running_loop_or_none():
        _put_latest(queue, event)
        return
    loop.call_soon_threadsafe(_put_latest, queue, event)


def _running_loop_or_none() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


async def publish_realtime_event(
    event: RealtimeEvent,
    *,
    broker: Any | None = None,
    timeout_seconds: float | None = None,
) -> None:
    publisher = broker or realtime_event_broker
    resolved_timeout = _configured_publish_timeout_seconds(timeout_seconds)
    try:
        result = publisher.publish(event)
        if isawaitable(result):
            await _await_with_optional_timeout(result, timeout_seconds=resolved_timeout)
    except TimeoutError:
        logger.warning(
            "Realtime publish timed out after %.2f seconds: %s",
            resolved_timeout,
            event.get("type"),
        )
    except Exception as exc:
        logger.warning("Realtime publish failed: %s", exc)


def publish_realtime_event_background(
    event: RealtimeEvent,
    *,
    broker: Any | None = None,
    timeout_seconds: float | None = None,
) -> asyncio.Task[None] | None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Realtime publish skipped because no running event loop is available")
        return None
    task = loop.create_task(
        publish_realtime_event(
            event,
            broker=broker,
            timeout_seconds=timeout_seconds,
        )
    )
    task.add_done_callback(_log_background_publish_exception)
    return task


async def _await_with_optional_timeout(awaitable: Any, *, timeout_seconds: float) -> Any:
    if timeout_seconds <= 0:
        return await awaitable
    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)


def _configured_publish_timeout_seconds(value: float | None = None) -> float:
    raw_value = settings.realtime_publish_timeout_seconds if value is None else value
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        return 0.75


def _log_background_publish_exception(task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        exc = task.exception()
        if exc is not None:
            logger.warning("Realtime background publish failed: %s", exc)


def encode_realtime_event(event: RealtimeEvent) -> RealtimeEvent:
    encoded = jsonable_encoder(event)
    if not isinstance(encoded, dict):
        raise TypeError("Realtime event must encode to a JSON object")
    _assert_json_compatible(encoded)
    return encoded


def _assert_json_compatible(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("Realtime event contains a non-finite float")
        return
    if isinstance(value, list):
        for item in value:
            _assert_json_compatible(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Realtime event object keys must be strings")
            _assert_json_compatible(item)
        return
    raise TypeError(f"Realtime event is not JSON-compatible: {type(value).__name__}")


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
