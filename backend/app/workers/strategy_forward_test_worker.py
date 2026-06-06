from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from app.core.config import settings
from app.services.strategy_testing.service import StrategyTestingService


logger = logging.getLogger(__name__)
STOP_TIMEOUT_SEC = 3.0


class StrategyForwardTestWorker:
    def __init__(
        self,
        *,
        interval_seconds: float | None = None,
        service: StrategyTestingService | None = None,
    ) -> None:
        self._interval_seconds = interval_seconds or settings.strategy_forward_test_worker_interval_seconds
        self._service = service or StrategyTestingService()
        self._task: Optional[asyncio.Task[None]] = None
        self._stopping = False
        self._last_processed = 0

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_stopping(self) -> bool:
        return self._stopping and self.is_running

    @property
    def last_processed(self) -> int:
        return self._last_processed

    def start(self) -> None:
        if self.is_running:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        logger.info("Strategy forward test worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._task.done():
            self._task = None
            self._stopping = False
            return
        self._stopping = True
        self._task.cancel()
        try:
            done, pending = await asyncio.wait({self._task}, timeout=STOP_TIMEOUT_SEC)
        except asyncio.CancelledError:
            self._task.cancel()
            raise
        if pending:
            logger.warning("Strategy forward test worker stop timed out after %.1f seconds", STOP_TIMEOUT_SEC)
            return
        task = done.pop()
        with contextlib.suppress(asyncio.CancelledError):
            task.result()
        if self._task is task:
            self._task = None
            self._stopping = False
        logger.info("Strategy forward test worker stopped")

    async def _run(self) -> None:
        while True:
            try:
                self._last_processed = await asyncio.to_thread(self._service.process_forward_runs_once)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Strategy forward test worker tick failed")
            await asyncio.sleep(self._interval_seconds)
