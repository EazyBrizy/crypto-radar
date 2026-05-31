import asyncio
import contextlib
import logging
from collections.abc import Callable

from app.core.config import settings
from app.services.derivative_market import (
    DerivativeMarketSnapshotService,
    derivative_market_snapshot_service,
)
from app.services.radar_config_service import radar_config_service

logger = logging.getLogger(__name__)
STOP_TIMEOUT_SEC = 3.0


class DerivativeSnapshotSyncRunner:
    """Refreshes derivative ticker context into PostgreSQL and Redis hot cache."""

    def __init__(
        self,
        *,
        service: DerivativeMarketSnapshotService = derivative_market_snapshot_service,
        symbols_provider: Callable[[], list[str]] | None = None,
        categories_provider: Callable[[], list[str]] | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        self._service = service
        self._symbols_provider = symbols_provider or radar_config_service.selected_symbols
        self._categories_provider = categories_provider or _configured_bybit_categories
        self._interval_seconds = max(30, int(interval_seconds or settings.derivative_snapshot_sync_interval_seconds))
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._last_result: dict[str, object] = {}

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_result(self) -> dict[str, object]:
        return dict(self._last_result)

    def start(self) -> None:
        if self.is_running:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        logger.info("Derivative snapshot sync runner started")

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
            logger.warning(
                "Derivative snapshot sync runner stop timed out after %.1f seconds",
                STOP_TIMEOUT_SEC,
            )
            return
        task = done.pop()
        with contextlib.suppress(asyncio.CancelledError):
            task.result()
        logger.info("Derivative snapshot sync runner stopped")
        if self._task is task:
            self._task = None
            self._stopping = False

    async def sync_once(self) -> dict[str, object]:
        symbols = [symbol.strip().upper() for symbol in self._symbols_provider() if symbol.strip()]
        categories = self._categories_provider()
        result: dict[str, object] = {
            "symbols": symbols,
            "categories": categories,
            "synced": 0,
            "errors": [],
        }
        errors: list[str] = []
        synced_count = 0
        for category in categories:
            try:
                snapshots = await asyncio.to_thread(
                    self._service.refresh_bybit_symbols,
                    symbols=symbols,
                    category=category,
                )
            except Exception as exc:
                message = f"{category}: {exc}"
                errors.append(message)
                logger.warning("Bybit derivative snapshot sync failed for %s: %s", category, exc)
                continue
            synced_count += len(snapshots)
            logger.info("Bybit derivative snapshots synced: category=%s records=%s", category, len(snapshots))
        result["synced"] = synced_count
        result["errors"] = errors
        self._last_result = result
        return result

    async def _run(self) -> None:
        while True:
            await self.sync_once()
            await asyncio.sleep(self._interval_seconds)


def _configured_bybit_categories() -> list[str]:
    values = [
        value.strip().lower()
        for value in settings.bybit_derivative_snapshot_categories.split(",")
        if value.strip()
    ]
    allowed = {"linear", "inverse", "option"}
    return [value for value in dict.fromkeys(values) if value in allowed] or ["linear"]
