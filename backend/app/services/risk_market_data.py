from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.exchanges.bybit import (
    BybitOrderBookSnapshot,
    BybitPositionInfo,
    BybitTicker,
    fetch_bybit_tickers,
)
from app.schemas.market import OrderBookSnapshot
from app.services.exchange_connection_service import exchange_connection_service
from app.services.market_persistence import orderbook_hot_key
from app.services.orderbook_snapshot import build_orderbook_snapshot

logger = logging.getLogger(__name__)
PLACEHOLDER_ORDERBOOK_SOURCE = "orderbook_l2_not_available"


class BybitPositionProvider(Protocol):
    def get_bybit_positions(
        self,
        *,
        user_id: str = "demo_user",
        category: str = "linear",
        symbol: str | None = None,
    ) -> list[BybitPositionInfo]:
        ...


BybitTickerFetcher = Callable[..., list[BybitTicker]]
BybitOrderBookFetcher = Callable[..., BybitOrderBookSnapshot]


class RedisHotClient(Protocol):
    def get(self, name: str) -> object:
        ...


@dataclass(frozen=True)
class RiskMarketDataSnapshot:
    exchange: str
    symbol: str
    category: str | None
    entry_price: float
    slippage_bps: float
    best_bid: float | None = None
    best_ask: float | None = None
    mark_price: float | None = None
    funding_rate: float | None = None
    funding_buffer_per_unit: float = 0.0
    spread_percent: float | None = None
    spread_bps: float | None = None
    orderbook_depth_usd: float | None = None
    orderbook_snapshot: OrderBookSnapshot | None = None
    liquidation_price: float | None = None
    market_data_status: str = "unknown"
    market_data_source: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderBookReadResult:
    snapshot: OrderBookSnapshot | None
    status: str
    source: str | None
    warnings: tuple[str, ...] = ()


class RiskMarketDataService:
    """Collects exchange market context before the mandatory risk-gate decision."""

    def __init__(
        self,
        *,
        ticker_fetcher: BybitTickerFetcher = fetch_bybit_tickers,
        orderbook_fetcher: BybitOrderBookFetcher | None = None,
        redis_client_factory: Callable[[], RedisHotClient] = get_redis_client,
        orderbook_max_age_seconds: int | None = None,
        position_provider: BybitPositionProvider | None = exchange_connection_service,
    ) -> None:
        self._ticker_fetcher = ticker_fetcher
        self._orderbook_fetcher = orderbook_fetcher
        self._redis_client_factory = redis_client_factory
        self._prefer_hot_orderbook = orderbook_fetcher is None
        self._orderbook_max_age_seconds = int(orderbook_max_age_seconds or settings.orderbook_snapshot_ttl_seconds)
        self._position_provider = position_provider

    def build_snapshot(
        self,
        *,
        exchange: str,
        symbol: str,
        side: str,
        mode: str,
        instrument_type: str,
        fallback_entry_price: float,
        manual_entry_price: float | None = None,
        manual_slippage_bps: float = 0.0,
        user_id: str = "demo_user",
    ) -> RiskMarketDataSnapshot:
        normalized_exchange = exchange.strip().lower()
        normalized_symbol = symbol.strip().upper()
        category = _instrument_category(instrument_type)
        if normalized_exchange != "bybit":
            return RiskMarketDataSnapshot(
                exchange=normalized_exchange,
                symbol=normalized_symbol,
                category=category,
                entry_price=manual_entry_price or fallback_entry_price,
                slippage_bps=manual_slippage_bps,
                market_data_status="unknown",
                warnings=(f"Market context is not implemented for exchange {normalized_exchange}.",),
            )

        warnings: list[str] = []
        ticker = self._fetch_ticker(category, normalized_symbol, warnings)
        orderbook_result = self._fetch_orderbook(normalized_exchange, category, normalized_symbol)
        warnings.extend(orderbook_result.warnings)
        orderbook = orderbook_result.snapshot
        best_bid = _first_not_none(
            _best_bid(orderbook),
            ticker.bid1_price if ticker is not None else None,
        )
        best_ask = _first_not_none(
            _best_ask(orderbook),
            ticker.ask1_price if ticker is not None else None,
        )
        spread_bps = _spread_bps_from_orderbook(orderbook)
        if spread_bps is None:
            spread_percent = _spread_percent(best_bid, best_ask)
            spread_bps = spread_percent * 100 if spread_percent is not None else None
        else:
            spread_percent = spread_bps / 100
        if best_bid is None or best_ask is None:
            warnings.append("Bybit bid/ask is unavailable; risk-gate uses the signal entry fallback.")

        market_entry = _market_entry(
            side=side,
            best_bid=best_bid,
            best_ask=best_ask,
            fallback_entry_price=fallback_entry_price,
        )
        entry_price = manual_entry_price or market_entry
        slippage_bps = manual_slippage_bps + (spread_bps or 0.0)
        funding_rate = ticker.funding_rate if ticker is not None else None
        funding_buffer_per_unit = (
            abs(funding_rate) * entry_price
            if funding_rate is not None and category != "spot"
            else 0.0
        )
        orderbook_depth_usd = _side_depth_usd(orderbook, side) if orderbook is not None else None
        if orderbook_depth_usd is None:
            warnings.append("Bybit orderbook depth is unavailable; liquidity fill check is not exact.")
        elif orderbook_depth_usd <= 0:
            warnings.append("Bybit orderbook depth is empty for the entry side.")
            orderbook_depth_usd = 0.0

        liquidation_price = self._live_liquidation_price(
            mode=mode,
            category=category,
            symbol=normalized_symbol,
            side=side,
            user_id=user_id,
            warnings=warnings,
        )
        return RiskMarketDataSnapshot(
            exchange=normalized_exchange,
            symbol=normalized_symbol,
            category=category,
            entry_price=entry_price,
            slippage_bps=slippage_bps,
            best_bid=best_bid,
            best_ask=best_ask,
            mark_price=ticker.mark_price if ticker is not None else None,
            funding_rate=funding_rate,
            funding_buffer_per_unit=funding_buffer_per_unit,
            spread_percent=spread_percent,
            spread_bps=spread_bps,
            orderbook_depth_usd=orderbook_depth_usd,
            orderbook_snapshot=orderbook,
            liquidation_price=liquidation_price,
            market_data_status=orderbook_result.status,
            market_data_source=orderbook_result.source or "bybit_v5_tickers",
            warnings=tuple(_dedupe(warnings)),
        )

    def _fetch_ticker(
        self,
        category: str,
        symbol: str,
        warnings: list[str],
    ) -> BybitTicker | None:
        try:
            tickers = self._ticker_fetcher(category=category, symbol=symbol)
        except Exception as exc:
            logger.warning("Bybit ticker lookup failed for %s %s: %s", category, symbol, exc)
            warnings.append("Bybit ticker is unavailable.")
            return None
        return tickers[0] if tickers else None

    def _fetch_orderbook(
        self,
        exchange: str,
        category: str,
        symbol: str,
    ) -> OrderBookReadResult:
        if self._prefer_hot_orderbook:
            hot_snapshot = self._read_hot_orderbook(exchange=exchange, symbol=symbol)
            if hot_snapshot.snapshot is not None or self._orderbook_fetcher is None:
                return hot_snapshot
        if self._orderbook_fetcher is None:
            return OrderBookReadResult(
                snapshot=None,
                status="missing",
                source=None,
                warnings=("Bybit L2 orderbook snapshot is missing.",),
            )
        try:
            orderbook = self._orderbook_fetcher(category=category, symbol=symbol, limit=50)
        except Exception as exc:
            logger.warning("Bybit orderbook lookup failed for %s %s: %s", category, symbol, exc)
            return OrderBookReadResult(
                snapshot=None,
                status="missing",
                source=None,
                warnings=("Bybit orderbook is unavailable.",),
            )
        snapshot = build_orderbook_snapshot(
            orderbook,
            source="bybit_v5_orderbook_direct",
        )
        return OrderBookReadResult(
            snapshot=snapshot if snapshot.bids and snapshot.asks else None,
            status="fresh" if snapshot.bids and snapshot.asks else "missing",
            source=snapshot.source,
            warnings=() if snapshot.bids and snapshot.asks else ("Bybit L2 orderbook snapshot is empty.",),
        )

    def _read_hot_orderbook(self, *, exchange: str, symbol: str) -> OrderBookReadResult:
        key = orderbook_hot_key(exchange=exchange, symbol=symbol)
        try:
            raw = self._redis_client_factory().get(key)
        except Exception as exc:
            logger.warning("Orderbook hot snapshot read failed for %s: %s", key, exc)
            return OrderBookReadResult(
                snapshot=None,
                status="missing",
                source=None,
                warnings=("Bybit L2 orderbook snapshot is missing.",),
            )
        if raw is None:
            return OrderBookReadResult(
                snapshot=None,
                status="missing",
                source=None,
                warnings=("Bybit L2 orderbook snapshot is missing.",),
            )

        payload = raw.decode("utf8") if isinstance(raw, bytes) else str(raw)
        try:
            data = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Orderbook hot snapshot is malformed for %s: %s", key, exc)
            return OrderBookReadResult(
                snapshot=None,
                status="missing",
                source=None,
                warnings=("Bybit L2 orderbook snapshot is malformed.",),
            )
        if data.get("source") == PLACEHOLDER_ORDERBOOK_SOURCE:
            return OrderBookReadResult(
                snapshot=None,
                status="missing",
                source=PLACEHOLDER_ORDERBOOK_SOURCE,
                warnings=("Bybit L2 orderbook snapshot is missing.",),
            )
        try:
            snapshot = OrderBookSnapshot.model_validate(data)
        except (TypeError, ValueError) as exc:
            logger.warning("Orderbook hot snapshot validation failed for %s: %s", key, exc)
            return OrderBookReadResult(
                snapshot=None,
                status="missing",
                source=None,
                warnings=("Bybit L2 orderbook snapshot is malformed.",),
            )
        if not snapshot.bids or not snapshot.asks:
            return OrderBookReadResult(
                snapshot=None,
                status="missing",
                source=snapshot.source,
                warnings=("Bybit L2 orderbook snapshot is empty.",),
            )
        age_seconds = _orderbook_age_seconds(snapshot)
        if _is_orderbook_stale(snapshot, self._orderbook_max_age_seconds):
            return OrderBookReadResult(
                snapshot=_snapshot_with_freshness(snapshot, status="stale", age_seconds=age_seconds),
                status="stale",
                source=snapshot.source,
                warnings=("Bybit L2 orderbook snapshot is stale.",),
            )
        return OrderBookReadResult(
            snapshot=_snapshot_with_freshness(snapshot, status="fresh", age_seconds=age_seconds),
            status="fresh",
            source=snapshot.source,
        )

    def _live_liquidation_price(
        self,
        *,
        mode: str,
        category: str,
        symbol: str,
        side: str,
        user_id: str,
        warnings: list[str],
    ) -> float | None:
        if mode != "real" or category not in {"linear", "inverse"} or self._position_provider is None:
            return None
        try:
            positions = self._position_provider.get_bybit_positions(
                user_id=user_id,
                category=category,
                symbol=symbol,
            )
        except Exception as exc:
            logger.warning("Bybit position-list lookup failed for %s %s: %s", category, symbol, exc)
            warnings.append("Bybit live liquidation price is unavailable.")
            return None
        for position in positions:
            if position.liquidation_price is None or not position.size or position.size <= 0:
                continue
            if _bybit_position_side(position.side) == side:
                return position.liquidation_price
        return None


def _instrument_category(instrument_type: str) -> str:
    return "linear" if instrument_type == "futures" else "spot"


def _first_not_none(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _market_entry(
    *,
    side: str,
    best_bid: float | None,
    best_ask: float | None,
    fallback_entry_price: float,
) -> float:
    if side == "long" and best_ask is not None:
        return best_ask
    if side == "short" and best_bid is not None:
        return best_bid
    return fallback_entry_price


def _spread_percent(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2
    if mid <= 0 or best_ask < best_bid:
        return None
    return (best_ask - best_bid) / mid * 100


def _best_bid(orderbook: OrderBookSnapshot | None) -> float | None:
    if orderbook is None:
        return None
    if orderbook.best_bid is not None:
        return orderbook.best_bid
    if not orderbook.bids:
        return None
    level = orderbook.bids[0]
    return float(level.price)


def _best_ask(orderbook: OrderBookSnapshot | None) -> float | None:
    if orderbook is None:
        return None
    if orderbook.best_ask is not None:
        return orderbook.best_ask
    if not orderbook.asks:
        return None
    level = orderbook.asks[0]
    return float(level.price)


def _spread_bps_from_orderbook(orderbook: OrderBookSnapshot | None) -> float | None:
    if orderbook is None:
        return None
    if orderbook.spread_bps is not None:
        return orderbook.spread_bps
    return _spread_bps(_best_bid(orderbook), _best_ask(orderbook))


def _side_depth_usd(orderbook: OrderBookSnapshot | None, side: str) -> float | None:
    if orderbook is None:
        return None
    return (
        orderbook.ask_depth_usd_0_5_pct
        if side == "long"
        else orderbook.bid_depth_usd_0_5_pct
    )


def _spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    spread_percent = _spread_percent(best_bid, best_ask)
    return spread_percent * 100 if spread_percent is not None else None


def _is_orderbook_stale(snapshot: OrderBookSnapshot, max_age_seconds: int) -> bool:
    if max_age_seconds <= 0:
        return False
    age_seconds = _orderbook_age_seconds(snapshot)
    return age_seconds is None or age_seconds > max_age_seconds


def _orderbook_age_seconds(snapshot: OrderBookSnapshot) -> float | None:
    if snapshot.timestamp <= 0:
        return None
    return max(0.0, (int(time.time() * 1000) - snapshot.timestamp) / 1000)


def _snapshot_with_freshness(
    snapshot: OrderBookSnapshot,
    *,
    status: str,
    age_seconds: float | None,
) -> OrderBookSnapshot:
    return snapshot.model_copy(
        update={
            "freshness_status": status,
            "age_seconds": age_seconds,
        }
    )


def _bybit_position_side(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if normalized == "buy":
        return "long"
    if normalized == "sell":
        return "short"
    return None


def _market_status(
    *,
    ticker: BybitTicker | None,
    orderbook: BybitOrderBookSnapshot | None,
    best_bid: float | None,
    best_ask: float | None,
) -> str:
    has_bid_ask = best_bid is not None and best_ask is not None
    has_depth = orderbook is not None and bool(orderbook.bids or orderbook.asks)
    if ticker is not None and has_bid_ask and has_depth:
        return "fresh"
    if ticker is None and orderbook is None:
        return "missing"
    return "partial"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


risk_market_data_service = RiskMarketDataService()
