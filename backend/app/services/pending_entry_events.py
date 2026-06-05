from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from app.schemas.pending_entry import PendingEntryIntentRead
from app.services.message_broker import RedisMessageBroker, realtime_event_broker
from app.services.realtime_events import pending_entry_updated_event
from app.services.signal_views import annotate_pending_entry_view

logger = logging.getLogger(__name__)


class PendingEntryUpdatePublisher(Protocol):
    def publish_update(
        self,
        intent: PendingEntryIntentRead,
        *,
        message: str | None = None,
    ) -> None:
        ...


class RealtimePendingEntryUpdatePublisher:
    def __init__(self, broker: RedisMessageBroker = realtime_event_broker) -> None:
        self._broker = broker

    def publish_update(
        self,
        intent: PendingEntryIntentRead,
        *,
        message: str | None = None,
    ) -> None:
        event = pending_entry_updated_event(annotate_pending_entry_view(intent), message=message)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._publish_without_running_loop(event)
            return

        task = loop.create_task(self._publish(event))
        task.add_done_callback(_log_publish_task_failure)

    def _publish_without_running_loop(self, event: dict[str, Any]) -> None:
        try:
            asyncio.run(self._publish(event))
        except Exception as exc:
            logger.warning("Pending entry realtime event publish failed: %s", exc)

    async def _publish(self, event: dict[str, Any]) -> None:
        await self._broker.publish(event)


def _log_publish_task_failure(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception as exc:
        logger.warning("Pending entry realtime event publish failed: %s", exc)


pending_entry_update_publisher = RealtimePendingEntryUpdatePublisher()
