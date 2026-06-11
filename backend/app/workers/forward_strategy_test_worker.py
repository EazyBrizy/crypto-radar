from __future__ import annotations

import asyncio
import contextlib
import logging

from app.schemas.market import MarketData
from app.schemas.signal import StrategySignal
from app.services.strategy_testing.forward_runtime import ForwardRuntimeResult, ForwardStrategyTestRuntime

logger = logging.getLogger(__name__)
DEFAULT_FORWARD_STRATEGY_TEST_INTERVAL_SECONDS = 5.0
STOP_TIMEOUT_SECONDS = 3.0


class ForwardStrategyTestWorker:
    """Keeps forward_virtual strategy-test runs alive and processes injected market ticks."""

    def __init__(
        self,
        *,
        runtime: ForwardStrategyTestRuntime | None = None,
        interval_seconds: float = DEFAULT_FORWARD_STRATEGY_TEST_INTERVAL_SECONDS,
    ) -> None:
        self._runtime = runtime or ForwardStrategyTestRuntime()
        self._interval_seconds = max(0.5, float(interval_seconds))
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._last_result = ForwardRuntimeResult()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_stopping(self) -> bool:
        return self._stopping and self.is_running

    @property
    def last_result(self) -> ForwardRuntimeResult:
        return self._last_result

    def start(self) -> None:
        if self.is_running:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        logger.info("Forward strategy test worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._task.done():
            self._task = None
            self._stopping = False
            return
        self._stopping = True
        self._task.cancel()
        done, pending = await asyncio.wait({self._task}, timeout=STOP_TIMEOUT_SECONDS)
        if pending:
            logger.warning("Forward strategy test worker stop timed out")
            return
        task = done.pop()
        with contextlib.suppress(asyncio.CancelledError):
            task.result()
        self._task = None
        self._stopping = False
        logger.info("Forward strategy test worker stopped")

    async def process_market_tick(self, tick: MarketData) -> ForwardRuntimeResult:
        self._last_result = await self._runtime.process_market_tick(tick)
        return self._last_result

    async def process_strategy_signal(self, signal: StrategySignal) -> ForwardRuntimeResult:
        self._last_result = await self._runtime.process_strategy_signal(signal)
        return self._last_result

    async def _run(self) -> None:
        while True:
            try:
                self._last_result = self._runtime.heartbeat_active_runs()
            except Exception as exc:
                logger.warning("Forward strategy test heartbeat failed: %s", exc)
                self._last_result = ForwardRuntimeResult(errors=[str(exc)])
            await asyncio.sleep(self._interval_seconds)


forward_strategy_test_worker = ForwardStrategyTestWorker()
