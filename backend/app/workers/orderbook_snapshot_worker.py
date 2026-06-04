from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from app.core.config import settings
from app.exchanges.bybit import BybitOrderBookSnapshot, fetch_bybit_orderbook
from app.schemas.market import OrderBookSnapshot
from app.services.market_persistence import (
    MarketDataPersistenceService,
    market_data_persistence_service,
)
from app.services.orderbook_snapshot import build_orderbook_snapshot
from app.services.radar_config_service import radar_config_service

logger = logging.getLogger(__name__)
STOP_TIMEOUT_SEC = 3.0

BybitOrderBookFetcher = Callable[..., BybitOrderBookSnapshot]


class OrderbookSnapshotWorker:
    """Refreshes real L2 orderbook snapshots into the Redis hot cache."""

    def __init__(
        self,
        *,
        orderbook_fetcher: BybitOrderBookFetcher = fetch_bybit_orderbook,
        persistence: MarketDataPersistenceService = market_data_persistence_service,
        symbols_provider: Callable[[], list[str]] | None = None,
        categories_provider: Callable[[], list[str]] | None = None,
        interval_seconds: int | None = None,
        ttl_seconds: int | None = None,
        limit: int | None = None,
    ) -> None:
        self._orderbook_fetcher = orderbook_fetcher
        self._persistence = persistence
        self._symbols_provider = symbols_provider or radar_config_service.selected_symbols
        self._categories_provider = categories_provider or _configured_bybit_categories
        self._interval_seconds = max(1, int(interval_seconds or settings.orderbook_snapshot_sync_interval_seconds))
        self._ttl_seconds = max(1, int(ttl_seconds or settings.orderbook_snapshot_ttl_seconds))
        self._limit = max(1, int(limit or settings.bybit_orderbook_snapshot_limit))
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
        logger.info("Orderbook snapshot worker started")

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
                "Orderbook snapshot worker stop timed out after %.1f seconds",
                STOP_TIMEOUT_SEC,
            )
            return
        task = done.pop()
        with contextlib.suppress(asyncio.CancelledError):
            task.result()
        logger.info("Orderbook snapshot worker stopped")
        if self._task is task:
            self._task = None
            self._stopping = False

    async def sync_once(self) -> dict[str, object]:
        symbols = _normalize_symbols(self._symbols_provider())
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
            for symbol in symbols:
                try:
                    snapshot = await asyncio.to_thread(
                        self._fetch_snapshot,
                        category=category,
                        symbol=symbol,
                    )
                except Exception as exc:
                    message = f"{category}:{symbol}: {exc}"
                    errors.append(message)
                    logger.warning("Bybit orderbook snapshot failed for %s %s: %s", category, symbol, exc)
                    continue
                self._persistence.persist_orderbook_snapshot(snapshot, ttl_seconds=self._ttl_seconds)
                synced_count += 1
        result["synced"] = synced_count
        result["errors"] = errors
        self._last_result = result
        return result

    def _fetch_snapshot(self, *, category: str, symbol: str) -> OrderBookSnapshot:
        orderbook = self._orderbook_fetcher(
            category=category,
            symbol=symbol,
            limit=self._limit,
        )
        return build_orderbook_snapshot(orderbook)

    async def _run(self) -> None:
        while True:
            await self.sync_once()
            await asyncio.sleep(self._interval_seconds)


def _normalize_symbols(symbols: list[str]) -> list[str]:
    normalized = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    return list(dict.fromkeys(normalized))


def _configured_bybit_categories() -> list[str]:
    values = [
        value.strip().lower()
        for value in settings.bybit_orderbook_snapshot_categories.split(",")
        if value.strip()
    ]
    allowed = {"spot", "linear", "inverse", "option"}
    return [value for value in dict.fromkeys(values) if value in allowed] or ["linear"]
