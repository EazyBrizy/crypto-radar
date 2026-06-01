from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.exchanges.bybit import BybitTicker, fetch_bybit_tickers
from app.models.market import MarketDerivativeSnapshot, MarketExchange, MarketPair

logger = logging.getLogger(__name__)

DERIVATIVE_HOT_KEY_PREFIX = "derivative"
DEFAULT_DERIVATIVE_CATEGORY = "linear"

BybitTickerFetcher = Callable[..., list[BybitTicker]]


class RedisHotClient(Protocol):
    def setex(self, name: str, time: int, value: str) -> Any:
        ...

    def get(self, name: str) -> Any:
        ...


@dataclass(frozen=True)
class DerivativeMarketSnapshot:
    exchange: str
    symbol: str
    category: str = DEFAULT_DERIVATIVE_CATEGORY
    mark_price: float | None = None
    funding_rate: float | None = None
    open_interest: float | None = None
    open_interest_value: float | None = None
    oi_change: float | None = None
    volume_24h: float | None = None
    turnover_24h: float | None = None
    source: str | None = None
    fetched_at: datetime | None = None
    warnings: tuple[str, ...] = ()


class DerivativeMarketSnapshotService:
    """Maintains hot derivative context for strategies without scanner-time REST calls."""

    def __init__(
        self,
        *,
        ticker_fetcher: BybitTickerFetcher = fetch_bybit_tickers,
        session_factory: sessionmaker[Session] = SessionLocal,
        redis_client_factory: Callable[[], RedisHotClient] = get_redis_client,
        ttl_seconds: int | None = None,
    ) -> None:
        self._ticker_fetcher = ticker_fetcher
        self._session_factory = session_factory
        self._redis_client_factory = redis_client_factory
        self._ttl_seconds = int(ttl_seconds or settings.derivative_snapshot_ttl_seconds)

    def refresh_bybit_symbol(
        self,
        *,
        symbol: str,
        category: str = DEFAULT_DERIVATIVE_CATEGORY,
    ) -> DerivativeMarketSnapshot | None:
        normalized_symbol = _normalize_symbol(symbol)
        normalized_category = category.strip().lower() or DEFAULT_DERIVATIVE_CATEGORY
        tickers = self._ticker_fetcher(category=normalized_category, symbol=normalized_symbol)
        ticker = tickers[0] if tickers else None
        if ticker is None:
            return None
        previous_snapshot = self.hot_snapshot(exchange="bybit", symbol=ticker.symbol)
        snapshot = DerivativeMarketSnapshot(
            exchange="bybit",
            symbol=ticker.symbol.upper(),
            category=ticker.category.lower(),
            mark_price=ticker.mark_price,
            funding_rate=ticker.funding_rate,
            open_interest=ticker.open_interest,
            open_interest_value=ticker.open_interest_value,
            oi_change=_calculate_oi_change(
                previous_snapshot.open_interest if previous_snapshot is not None else None,
                ticker.open_interest,
            ),
            volume_24h=ticker.volume_24h,
            turnover_24h=ticker.turnover_24h,
            source="bybit_v5_tickers",
            fetched_at=datetime.now(timezone.utc),
        )
        self._persist_snapshot(snapshot, raw_payload=ticker.raw_payload)
        self._write_hot_snapshot(snapshot)
        return snapshot

    def refresh_bybit_symbols(
        self,
        *,
        symbols: list[str],
        category: str = DEFAULT_DERIVATIVE_CATEGORY,
    ) -> list[DerivativeMarketSnapshot]:
        snapshots: list[DerivativeMarketSnapshot] = []
        for symbol in dict.fromkeys(_normalize_symbol(symbol) for symbol in symbols):
            try:
                snapshot = self.refresh_bybit_symbol(symbol=symbol, category=category)
            except Exception as exc:
                logger.warning("Derivative snapshot refresh failed for bybit:%s: %s", symbol, exc)
                continue
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    def hot_snapshot(
        self,
        *,
        exchange: str,
        symbol: str,
        max_age_seconds: int | None = None,
    ) -> DerivativeMarketSnapshot | None:
        key = hot_snapshot_key(exchange=exchange, symbol=symbol)
        try:
            raw = self._redis_client_factory().get(key)
        except Exception as exc:
            logger.warning("Derivative hot snapshot read failed for %s: %s", key, exc)
            return None
        if raw is None:
            return None
        payload = raw.decode("utf8") if isinstance(raw, bytes) else str(raw)
        try:
            snapshot = _snapshot_from_json(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Derivative hot snapshot is malformed for %s: %s", key, exc)
            return None
        if _is_stale(snapshot, int(max_age_seconds or self._ttl_seconds)):
            return None
        return snapshot

    def _persist_snapshot(self, snapshot: DerivativeMarketSnapshot, *, raw_payload: dict[str, Any]) -> None:
        with self._session_factory() as session:
            exchange = session.scalars(
                select(MarketExchange).where(MarketExchange.code == snapshot.exchange)
            ).one_or_none()
            if exchange is None:
                logger.warning("Derivative snapshot skipped; exchange is not seeded: %s", snapshot.exchange)
                return
            pair = session.scalars(
                select(MarketPair).where(
                    MarketPair.exchange_id == exchange.id,
                    MarketPair.symbol == snapshot.symbol,
                )
            ).one_or_none()
            record = session.scalars(
                select(MarketDerivativeSnapshot).where(
                    MarketDerivativeSnapshot.exchange_id == exchange.id,
                    MarketDerivativeSnapshot.symbol == snapshot.symbol,
                    MarketDerivativeSnapshot.category == snapshot.category,
                )
            ).one_or_none()
            now = datetime.now(timezone.utc)
            values = {
                "pair_id": pair.id if pair is not None else None,
                "mark_price": _decimal(snapshot.mark_price),
                "funding_rate": _decimal(snapshot.funding_rate),
                "open_interest": _decimal(snapshot.open_interest),
                "open_interest_value": _decimal(snapshot.open_interest_value),
                "oi_change": _decimal(snapshot.oi_change),
                "volume_24h": _decimal(snapshot.volume_24h),
                "turnover_24h": _decimal(snapshot.turnover_24h),
                "source": snapshot.source or "bybit_v5_tickers",
                "raw_payload": raw_payload,
                "fetched_at": snapshot.fetched_at or now,
                "updated_at": now,
            }
            if record is None:
                record = MarketDerivativeSnapshot(
                    exchange_id=exchange.id,
                    symbol=snapshot.symbol,
                    category=snapshot.category,
                    **values,
                )
                session.add(record)
            else:
                for key, value in values.items():
                    setattr(record, key, value)
            session.commit()

    def _write_hot_snapshot(self, snapshot: DerivativeMarketSnapshot) -> None:
        key = hot_snapshot_key(exchange=snapshot.exchange, symbol=snapshot.symbol)
        payload = json.dumps(_snapshot_to_json(snapshot), separators=(",", ":"), ensure_ascii=False)
        try:
            self._redis_client_factory().setex(key, self._ttl_seconds, payload)
        except Exception as exc:
            logger.warning("Derivative hot snapshot write failed for %s: %s", key, exc)


def hot_snapshot_key(*, exchange: str, symbol: str) -> str:
    return f"{DERIVATIVE_HOT_KEY_PREFIX}:{exchange.strip().lower()}:{_normalize_symbol(symbol)}"


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "").replace(":PERP", "")


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _calculate_oi_change(
    previous_open_interest: float | None,
    current_open_interest: float | None,
) -> float | None:
    if previous_open_interest and current_open_interest:
        return (current_open_interest - previous_open_interest) / previous_open_interest
    return None


def _snapshot_to_json(snapshot: DerivativeMarketSnapshot) -> dict[str, Any]:
    payload = asdict(snapshot)
    fetched_at = snapshot.fetched_at
    payload["fetched_at"] = fetched_at.isoformat() if fetched_at is not None else None
    payload["warnings"] = list(snapshot.warnings)
    return payload


def _snapshot_from_json(payload: str) -> DerivativeMarketSnapshot:
    data = json.loads(payload)
    fetched_at = data.get("fetched_at")
    if isinstance(fetched_at, str) and fetched_at:
        data["fetched_at"] = datetime.fromisoformat(fetched_at)
    else:
        data["fetched_at"] = None
    warnings = data.get("warnings") or ()
    data["warnings"] = tuple(str(warning) for warning in warnings)
    return DerivativeMarketSnapshot(**data)


def _is_stale(snapshot: DerivativeMarketSnapshot, max_age_seconds: int) -> bool:
    if snapshot.fetched_at is None:
        return True
    fetched_at = snapshot.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    return age > max_age_seconds


derivative_market_snapshot_service = DerivativeMarketSnapshotService()
