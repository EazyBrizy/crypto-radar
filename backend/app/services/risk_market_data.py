from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from app.exchanges.bybit import (
    BybitOrderBookSnapshot,
    BybitPositionInfo,
    BybitTicker,
    fetch_bybit_orderbook,
    fetch_bybit_tickers,
)
from app.services.exchange_connection_service import exchange_connection_service

logger = logging.getLogger(__name__)


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
    liquidation_price: float | None = None
    market_data_status: str = "unknown"
    market_data_source: str | None = None
    warnings: tuple[str, ...] = ()


class RiskMarketDataService:
    """Collects exchange market context before the mandatory risk-gate decision."""

    def __init__(
        self,
        *,
        ticker_fetcher: BybitTickerFetcher = fetch_bybit_tickers,
        orderbook_fetcher: BybitOrderBookFetcher = fetch_bybit_orderbook,
        position_provider: BybitPositionProvider | None = exchange_connection_service,
    ) -> None:
        self._ticker_fetcher = ticker_fetcher
        self._orderbook_fetcher = orderbook_fetcher
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
        orderbook = self._fetch_orderbook(category, normalized_symbol, warnings)
        best_bid = _first_not_none(
            ticker.bid1_price if ticker is not None else None,
            orderbook.bids[0][0] if orderbook is not None and orderbook.bids else None,
        )
        best_ask = _first_not_none(
            ticker.ask1_price if ticker is not None else None,
            orderbook.asks[0][0] if orderbook is not None and orderbook.asks else None,
        )
        spread_percent = _spread_percent(best_bid, best_ask)
        spread_bps = spread_percent * 100 if spread_percent is not None else None
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
        status = _market_status(ticker=ticker, orderbook=orderbook, best_bid=best_bid, best_ask=best_ask)
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
            liquidation_price=liquidation_price,
            market_data_status=status,
            market_data_source="bybit_v5",
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
        category: str,
        symbol: str,
        warnings: list[str],
    ) -> BybitOrderBookSnapshot | None:
        try:
            return self._orderbook_fetcher(category=category, symbol=symbol, limit=50)
        except Exception as exc:
            logger.warning("Bybit orderbook lookup failed for %s %s: %s", category, symbol, exc)
            warnings.append("Bybit orderbook is unavailable.")
            return None

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
    return "spot" if instrument_type == "spot" else "linear"


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


def _side_depth_usd(orderbook: BybitOrderBookSnapshot | None, side: str) -> float | None:
    if orderbook is None:
        return None
    levels = orderbook.asks if side == "long" else orderbook.bids
    return sum(price * quantity for price, quantity in levels if price > 0 and quantity > 0)


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
