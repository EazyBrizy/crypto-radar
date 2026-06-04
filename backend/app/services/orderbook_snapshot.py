from __future__ import annotations

import time
from datetime import datetime, timezone

from app.exchanges.bybit import BybitOrderBookSnapshot
from app.schemas.market import OrderBookLevel, OrderBookSnapshot

ORDERBOOK_SOURCE = "bybit_v5_orderbook"
DEPTH_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("0_1", 0.001),
    ("0_5", 0.005),
    ("1", 0.01),
)


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
        best_bid=bids[0].price if bids else None,
        best_ask=asks[0].price if asks else None,
        bids=bids,
        asks=asks,
        timestamp=timestamp,
        fetched_at=datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc),
        ts=_iso_from_ms(timestamp),
        freshness_status="fresh" if bids and asks else "missing",
        age_seconds=0.0,
        source=source,
        spread_bps=metrics["spread_bps"],
        bid_levels_count=len(bids),
        ask_levels_count=len(asks),
        depth_levels=len(bids) + len(asks),
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
