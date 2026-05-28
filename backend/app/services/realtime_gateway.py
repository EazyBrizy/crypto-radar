import asyncio
import contextlib
import json
from typing import Any

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from app.services.message_broker import RedisMessageBroker, realtime_event_broker

WEBSOCKET_SEND_TIMEOUT_SEC = 2.0
WEBSOCKET_QUEUE_MAX_SIZE = 1_000
SSE_QUEUE_MAX_SIZE = 500


class RealtimeGateway:
    def __init__(self) -> None:
        self._websockets: set[WebSocket] = set()
        self._websocket_locks: dict[WebSocket, asyncio.Lock] = {}
        self._websocket_queues: dict[WebSocket, asyncio.Queue[dict[str, Any]]] = {}
        self._websocket_tasks: dict[WebSocket, asyncio.Task[None]] = {}
        self._sse_queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._broker_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._broker_task: asyncio.Task[None] | None = None

    def start_broker_bridge(self, broker: RedisMessageBroker = realtime_event_broker) -> None:
        if self._broker_task is not None and not self._broker_task.done():
            return
        self._broker_queue = broker.subscribe()
        self._broker_task = asyncio.create_task(self._consume_broker_events(broker))

    async def stop_broker_bridge(self, broker: RedisMessageBroker = realtime_event_broker) -> None:
        if self._broker_queue is not None:
            broker.unsubscribe(self._broker_queue)
            self._broker_queue = None

        if self._broker_task is None:
            return

        self._broker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._broker_task
        self._broker_task = None
        await broker.stop()

    async def connect_websocket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._websockets.add(websocket)
        self._websocket_locks[websocket] = asyncio.Lock()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=WEBSOCKET_QUEUE_MAX_SIZE)
        self._websocket_queues[websocket] = queue
        self._websocket_tasks[websocket] = asyncio.create_task(
            self._send_websocket_events(websocket, queue)
        )

    def disconnect_websocket(self, websocket: WebSocket) -> None:
        self._websockets.discard(websocket)
        self._websocket_locks.pop(websocket, None)
        self._websocket_queues.pop(websocket, None)
        task = self._websocket_tasks.pop(websocket, None)
        if task is None:
            return

        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None

        if task is not current_task:
            task.cancel()

    def subscribe_sse(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SSE_QUEUE_MAX_SIZE)
        self._sse_queues.add(queue)
        return queue

    def unsubscribe_sse(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._sse_queues.discard(queue)

    async def broadcast(self, message: dict[str, Any]) -> None:
        payload = jsonable_encoder(message)
        await self._broadcast_websockets(payload)
        self._broadcast_sse(payload)

    async def send_websocket(self, websocket: WebSocket, message: dict[str, Any]) -> bool:
        payload = jsonable_encoder(message)
        return await self._send_websocket_payload(websocket, payload)

    async def _send_websocket_payload(self, websocket: WebSocket, payload: dict[str, Any]) -> bool:
        lock = self._websocket_locks.get(websocket)
        if lock is None:
            return False

        try:
            async with lock:
                await asyncio.wait_for(
                    websocket.send_json(payload),
                    timeout=WEBSOCKET_SEND_TIMEOUT_SEC,
                )
            return True
        except Exception:
            self.disconnect_websocket(websocket)
            return False

    async def _send_websocket_events(
        self,
        websocket: WebSocket,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        try:
            while True:
                payload = await queue.get()
                try:
                    if not await self._send_websocket_payload(websocket, payload):
                        return
                finally:
                    queue.task_done()
        finally:
            self.disconnect_websocket(websocket)

    async def _consume_broker_events(self, broker: RedisMessageBroker) -> None:
        queue = self._broker_queue
        if queue is None:
            return

        try:
            while True:
                event = await queue.get()
                try:
                    await self.broadcast(event)
                finally:
                    queue.task_done()
        finally:
            broker.unsubscribe(queue)

    async def _broadcast_websockets(self, message: dict[str, Any]) -> None:
        for websocket in list(self._websockets):
            queue = self._websocket_queues.get(websocket)
            if queue is None:
                continue
            _put_latest(queue, message)
        await asyncio.sleep(0)

    def _broadcast_sse(self, message: dict[str, Any]) -> None:
        for queue in list(self._sse_queues):
            _put_latest(queue, message)


def _put_latest(queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
    try:
        queue.put_nowait(message)
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
        queue.put_nowait(message)


def sse_encode(message: dict[str, Any]) -> str:
    return f"data: {json.dumps(jsonable_encoder(message), ensure_ascii=False)}\n\n"


realtime_gateway = RealtimeGateway()
