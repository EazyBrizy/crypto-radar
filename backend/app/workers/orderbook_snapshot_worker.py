from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

from app.core.config import settings
from app.exchanges.bybit import BybitOrderBookSnapshot, fetch_bybit_orderbook
from app.schemas.market import OrderBookLevel, OrderBookSnapshot
from app.services.market_persistence import (
    MarketDataPersistenceService,
    market_data_persistence_service,
)
from app.services.radar_config_service import radar_config_service

logger = logging.getLogger(__name__)
STOP_TIMEOUT_SEC = 3.0
ORDERBOOK_SOURCE = "bybit_v5_orderbook"
DEPTH_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("0_1", 0.001),
    ("0_5", 0.005),
    ("1", 0.01),
)

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


def build_orderbook_snapshot(
    orderbook: BybitOrderBookSnapshot,
    *,
    exchange: str = "bybit",
    source: str = ORDERBOOK_SOURCE,
    timestamp_ms: int | None = None,
) -> OrderBookSnapshot:
    bids = normalize_orderbook_levels(orderbook.bids, side="bid")
    asks = normalize_orderbook_levels(orderbook.asks, side="ask")
    timestamp = timestamp_ms or orderbook.timestamp_ms or int(time.time() * 1000)
    metrics = calculate_orderbook_depth_metrics(bids=bids, asks=asks)
    return OrderBookSnapshot(
        exchange=exchange.strip().lower(),
        symbol=orderbook.symbol.strip().upper(),
        category=orderbook.category.strip().lower() if orderbook.category else None,
        bids=bids,
        asks=asks,
        timestamp=timestamp,
        ts=_iso_from_ms(timestamp),
        source=source,
        spread_bps=metrics["spread_bps"],
        bid_depth_usd_0_1_pct=metrics["bid_depth_usd_0_1_pct"],
        ask_depth_usd_0_1_pct=metrics["ask_depth_usd_0_1_pct"],
        bid_depth_usd_0_5_pct=metrics["bid_depth_usd_0_5_pct"],
        ask_depth_usd_0_5_pct=metrics["ask_depth_usd_0_5_pct"],
        bid_depth_usd_1_pct=metrics["bid_depth_usd_1_pct"],
        ask_depth_usd_1_pct=metrics["ask_depth_usd_1_pct"],
    )


def normalize_orderbook_levels(
    levels: list[tuple[float, float]],
    *,
    side: str,
) -> list[OrderBookLevel]:
    normalized = [
        OrderBookLevel(price=price, quantity=quantity)
        for price, quantity in levels
        if price > 0 and quantity > 0
    ]
    return sorted(normalized, key=lambda level: level.price, reverse=side == "bid")


def calculate_orderbook_depth_metrics(
    *,
    bids: list[OrderBookLevel],
    asks: list[OrderBookLevel],
) -> dict[str, float | None]:
    best_bid = bids[0].price if bids else None
    best_ask = asks[0].price if asks else None
    metrics: dict[str, float | None] = {
        "spread_bps": _spread_bps(best_bid, best_ask),
        "bid_depth_usd_0_1_pct": 0.0,
        "ask_depth_usd_0_1_pct": 0.0,
        "bid_depth_usd_0_5_pct": 0.0,
        "ask_depth_usd_0_5_pct": 0.0,
        "bid_depth_usd_1_pct": 0.0,
        "ask_depth_usd_1_pct": 0.0,
    }
    if best_bid is None or best_ask is None:
        return metrics

    for label, threshold in DEPTH_THRESHOLDS:
        metrics[f"bid_depth_usd_{label}_pct"] = _bid_depth_usd(bids, best_bid, threshold)
        metrics[f"ask_depth_usd_{label}_pct"] = _ask_depth_usd(asks, best_ask, threshold)
    return metrics


def _bid_depth_usd(levels: list[OrderBookLevel], best_bid: float, threshold: float) -> float:
    min_price = best_bid * (1 - threshold)
    return sum(level.price * level.quantity for level in levels if level.price >= min_price)


def _ask_depth_usd(levels: list[OrderBookLevel], best_ask: float, threshold: float) -> float:
    max_price = best_ask * (1 + threshold)
    return sum(level.price * level.quantity for level in levels if level.price <= max_price)


def _spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2
    if mid <= 0 or best_ask < best_bid:
        return None
    return (best_ask - best_bid) / mid * 10_000


def _iso_from_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


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
