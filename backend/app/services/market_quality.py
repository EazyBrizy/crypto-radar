from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.exchanges.bybit import BybitTicker, fetch_bybit_tickers

logger = logging.getLogger(__name__)

QUALITY_SNAPSHOT_TTL_SEC = 60.0


BybitTickerFetcher = Callable[..., list[BybitTicker]]


@dataclass(frozen=True)
class MarketQualityData:
    exchange: str
    symbol: str
    volume_24h_quote: float | None = None
    spread_bps: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    source: str | None = None
    warnings: tuple[str, ...] = ()


class MarketQualityService:
    """Builds pre-strategy pair quality inputs without making entry decisions."""

    def __init__(
        self,
        *,
        ticker_fetcher: BybitTickerFetcher = fetch_bybit_tickers,
        ttl_seconds: float = QUALITY_SNAPSHOT_TTL_SEC,
    ) -> None:
        self._ticker_fetcher = ticker_fetcher
        self._ttl_seconds = ttl_seconds
        self._cache: dict[tuple[str, str], tuple[float, MarketQualityData]] = {}

    def snapshot(self, *, exchange: str, symbol: str) -> MarketQualityData:
        normalized_exchange = exchange.strip().lower()
        normalized_symbol = symbol.strip().upper()
        cache_key = (normalized_exchange, normalized_symbol)
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and now - cached[0] <= self._ttl_seconds:
            return cached[1]

        if normalized_exchange != "bybit":
            snapshot = MarketQualityData(
                exchange=normalized_exchange,
                symbol=normalized_symbol,
                source=None,
                warnings=(f"Market quality ticker is not implemented for {normalized_exchange}.",),
            )
            self._cache[cache_key] = (now, snapshot)
            return snapshot

        warnings: list[str] = []
        try:
            tickers = self._ticker_fetcher(category="linear", symbol=normalized_symbol)
        except Exception as exc:
            logger.warning("Market quality ticker lookup failed for %s:%s: %s", normalized_exchange, normalized_symbol, exc)
            tickers = []
            warnings.append("Ticker snapshot is unavailable for market-quality filter.")

        ticker = tickers[0] if tickers else None
        spread_bps = _spread_bps(
            ticker.bid1_price if ticker is not None else None,
            ticker.ask1_price if ticker is not None else None,
        )
        volume_24h_quote = ticker.turnover_24h if ticker is not None else None
        if ticker is not None and volume_24h_quote is None and ticker.volume_24h is not None and ticker.mark_price is not None:
            volume_24h_quote = ticker.volume_24h * ticker.mark_price
        if ticker is not None and volume_24h_quote is None:
            warnings.append("Ticker does not include usable 24h quote volume.")
        if ticker is not None and spread_bps is None:
            warnings.append("Ticker does not include usable bid/ask spread.")

        snapshot = MarketQualityData(
            exchange=normalized_exchange,
            symbol=normalized_symbol,
            volume_24h_quote=volume_24h_quote,
            spread_bps=spread_bps,
            best_bid=ticker.bid1_price if ticker is not None else None,
            best_ask=ticker.ask1_price if ticker is not None else None,
            source="bybit_v5_tickers" if ticker is not None else None,
            warnings=tuple(warnings),
        )
        self._cache[cache_key] = (now, snapshot)
        return snapshot


def _spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return None
    mid = (best_bid + best_ask) / 2
    if mid <= 0:
        return None
    return (best_ask - best_bid) / mid * 10_000


market_quality_service = MarketQualityService()
