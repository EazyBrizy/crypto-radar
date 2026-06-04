from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.exchanges.bybit import (
    BYBIT_API_URL,
    BYBIT_WS_URL,
    BybitApiError,
    BybitTicker,
    BybitUniverseInstrument,
    fetch_bybit_market_universe,
)
from app.models.market import MarketAsset, MarketDerivativeSnapshot, MarketExchange, MarketPair
from app.services.exchange_instrument_service import upsert_bybit_instrument_info_rule

MarketUniverseLimit = Literal["top_100", "top_200", "top_500", "all"]

SUPPORTED_EXCHANGE = "bybit"
SUPPORTED_CATEGORY = "linear"
SUPPORTED_QUOTE = "USDT"
DEFAULT_SORT = "turnover_24h_desc"
MARKET_UNIVERSE_SOURCE = "bybit_tickers"
DERIVATIVE_SNAPSHOT_SOURCE = "bybit_v5_tickers"
INSTRUMENT_RULE_SOURCE = "bybit_market_universe"

_LIMIT_SIZES: dict[MarketUniverseLimit, int | None] = {
    "top_100": 100,
    "top_200": 200,
    "top_500": 500,
    "all": None,
}


@dataclass(frozen=True)
class MarketUniverseSyncResult:
    exchange: str
    category: str
    quote: str
    requested_limit: MarketUniverseLimit
    synced_count: int
    total_available_count: int
    skipped_count: int
    synced_at: datetime
    warnings: list[str] = field(default_factory=list)


def sync_exchange_universe(
    session: Session,
    *,
    exchange: str,
    category: str,
    quote: str,
    limit: MarketUniverseLimit,
    sort: str = DEFAULT_SORT,
) -> MarketUniverseSyncResult:
    normalized_exchange = exchange.strip().lower()
    normalized_category = category.strip().lower()
    normalized_quote = quote.strip().upper()
    _validate_request(
        exchange=normalized_exchange,
        category=normalized_category,
        quote=normalized_quote,
        limit=limit,
        sort=sort,
    )

    try:
        fetched_universe = fetch_bybit_market_universe(
            category=normalized_category,
            quote_coin=normalized_quote,
        )
    except BybitApiError as exc:
        raise ValueError(str(exc)) from exc

    tradable_universe = [
        item
        for item in fetched_universe
        if (item.status or "").strip().lower() == "trading"
    ]
    ordered_universe = _sort_universe(tradable_universe, sort)
    selected_universe = _apply_limit(ordered_universe, limit)
    synced_at = datetime.now(timezone.utc)
    warnings: list[str] = []

    exchange_record = _upsert_exchange(session, normalized_exchange)
    synced_count = 0
    for rank, item in enumerate(selected_universe, start=1):
        base_symbol = _base_symbol(item, normalized_quote)
        quote_symbol = (item.quote_coin or normalized_quote).strip().upper()
        if not base_symbol or not quote_symbol:
            warnings.append(f"Skipped {item.symbol}: base/quote asset is missing.")
            continue

        base_asset = _upsert_asset(session, base_symbol)
        quote_asset = _upsert_asset(session, quote_symbol)
        pair = _upsert_pair(
            session,
            exchange=exchange_record,
            base_asset=base_asset,
            quote_asset=quote_asset,
            item=item,
            rank=rank,
            synced_at=synced_at,
        )
        upsert_bybit_instrument_info_rule(
            session,
            exchange=exchange_record,
            instrument=item.instrument,
            pair=pair,
            fetched_at=synced_at,
            source=INSTRUMENT_RULE_SOURCE,
        )
        _upsert_derivative_snapshot(
            session,
            exchange=exchange_record,
            pair=pair,
            item=item,
            fetched_at=synced_at,
        )
        synced_count += 1

    session.commit()
    return MarketUniverseSyncResult(
        exchange=normalized_exchange,
        category=normalized_category,
        quote=normalized_quote,
        requested_limit=limit,
        synced_count=synced_count,
        total_available_count=len(tradable_universe),
        skipped_count=len(fetched_universe) - synced_count,
        synced_at=synced_at,
        warnings=warnings,
    )


def _validate_request(
    *,
    exchange: str,
    category: str,
    quote: str,
    limit: str,
    sort: str,
) -> None:
    if exchange != SUPPORTED_EXCHANGE:
        raise ValueError("Market universe sync supports only exchange='bybit'.")
    if category != SUPPORTED_CATEGORY:
        raise ValueError("Market universe sync supports only category='linear' for bybit.")
    if quote != SUPPORTED_QUOTE:
        raise ValueError("Market universe sync supports only quote='USDT' for bybit linear.")
    if limit not in _LIMIT_SIZES:
        raise ValueError("Market universe limit must be top_100, top_200, top_500, or all.")
    if sort != DEFAULT_SORT:
        raise ValueError("Market universe sort supports only turnover_24h_desc.")


def _sort_universe(
    universe: list[BybitUniverseInstrument],
    sort: str,
) -> list[BybitUniverseInstrument]:
    if sort != DEFAULT_SORT:
        raise ValueError("Market universe sort supports only turnover_24h_desc.")
    return sorted(universe, key=_turnover_desc_sort_key)


def _turnover_desc_sort_key(item: BybitUniverseInstrument) -> tuple[bool, Decimal, str]:
    turnover = item.turnover_24h
    return (turnover is None, -(turnover or Decimal("0")), item.symbol)


def _apply_limit(
    universe: list[BybitUniverseInstrument],
    limit: MarketUniverseLimit,
) -> list[BybitUniverseInstrument]:
    size = _LIMIT_SIZES[limit]
    if size is None:
        return universe
    return universe[:size]


def _upsert_exchange(session: Session, exchange_code: str) -> MarketExchange:
    exchange = session.scalars(
        select(MarketExchange).where(MarketExchange.code == exchange_code)
    ).one_or_none()
    values: dict[str, Any] = {
        "code": exchange_code,
        "name": "Bybit",
        "type": "cex",
        "status": "active",
        "api_base_url": BYBIT_API_URL,
        "ws_base_url": BYBIT_WS_URL,
    }
    if exchange is None:
        exchange = MarketExchange(id=uuid4(), metadata_={"market_types": ["linear_perpetual"]}, **values)
        session.add(exchange)
        session.flush()
        return exchange
    for key, value in values.items():
        setattr(exchange, key, value)
    metadata = dict(exchange.metadata_ or {})
    existing_market_types = metadata.get("market_types", [])
    if not isinstance(existing_market_types, list):
        existing_market_types = []
    market_types = list(dict.fromkeys([*existing_market_types, "linear_perpetual"]))
    metadata["market_types"] = market_types
    exchange.metadata_ = metadata
    session.flush()
    return exchange


def _upsert_asset(session: Session, symbol: str) -> MarketAsset:
    normalized_symbol = symbol.strip().upper()
    asset = session.scalars(
        select(MarketAsset).where(MarketAsset.symbol == normalized_symbol)
    ).one_or_none()
    if asset is None:
        asset = MarketAsset(
            id=uuid4(),
            symbol=normalized_symbol,
            name=None,
            asset_type="crypto",
            metadata_={"source": "market_universe"},
        )
        session.add(asset)
        session.flush()
    return asset


def _upsert_pair(
    session: Session,
    *,
    exchange: MarketExchange,
    base_asset: MarketAsset,
    quote_asset: MarketAsset,
    item: BybitUniverseInstrument,
    rank: int,
    synced_at: datetime,
) -> MarketPair:
    pair = session.scalars(
        select(MarketPair).where(
            MarketPair.exchange_id == exchange.id,
            MarketPair.symbol == item.symbol,
        )
    ).one_or_none()
    values: dict[str, Any] = {
        "exchange_id": exchange.id,
        "base_asset_id": base_asset.id,
        "quote_asset_id": quote_asset.id,
        "symbol": item.symbol,
        "status": "active",
        "market_type": _market_type(item),
        "category": item.category,
        "quote_volume_24h": item.turnover_24h,
        "base_volume_24h": item.volume_24h,
        "turnover_24h": item.turnover_24h,
        "last_price": item.last_price,
        "mark_price": item.mark_price,
        "bid_price": item.bid1_price,
        "ask_price": item.ask1_price,
        "spread_bps": item.spread_bps,
        "funding_rate": item.funding_rate,
        "liquidity_rank": rank,
        "liquidity_tier": _liquidity_tier(item.turnover_24h),
        "exchange_status": item.status,
        "universe_source": MARKET_UNIVERSE_SOURCE,
        "synced_at": synced_at,
    }
    if pair is None:
        pair = MarketPair(
            id=uuid4(),
            metadata_=_pair_metadata(None, item),
            **values,
        )
        session.add(pair)
    else:
        for key, value in values.items():
            setattr(pair, key, value)
        pair.metadata_ = _pair_metadata(pair.metadata_, item)
    session.flush()
    return pair


def _upsert_derivative_snapshot(
    session: Session,
    *,
    exchange: MarketExchange,
    pair: MarketPair,
    item: BybitUniverseInstrument,
    fetched_at: datetime,
) -> MarketDerivativeSnapshot:
    record = session.scalars(
        select(MarketDerivativeSnapshot).where(
            MarketDerivativeSnapshot.exchange_id == exchange.id,
            MarketDerivativeSnapshot.symbol == item.symbol,
            MarketDerivativeSnapshot.category == item.category,
        )
    ).one_or_none()
    open_interest = _ticker_decimal(item.ticker, "openInterest", "open_interest")
    values: dict[str, Any] = {
        "exchange_id": exchange.id,
        "pair_id": pair.id,
        "symbol": item.symbol,
        "category": item.category,
        "mark_price": item.mark_price,
        "funding_rate": item.funding_rate,
        "open_interest": open_interest,
        "open_interest_value": _ticker_decimal(item.ticker, "openInterestValue", "open_interest_value"),
        "oi_change": _oi_change(record.open_interest if record is not None else None, open_interest),
        "volume_24h": item.volume_24h,
        "turnover_24h": item.turnover_24h,
        "source": DERIVATIVE_SNAPSHOT_SOURCE,
        "raw_payload": dict(item.ticker.raw_payload) if item.ticker is not None else {},
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
    }
    if record is None:
        record = MarketDerivativeSnapshot(id=uuid4(), **values)
        session.add(record)
    else:
        for key, value in values.items():
            setattr(record, key, value)
    session.flush()
    return record


def _base_symbol(item: BybitUniverseInstrument, quote: str) -> str | None:
    if item.base_coin:
        return item.base_coin.strip().upper()
    symbol = item.symbol.strip().upper()
    if symbol.endswith(quote):
        return symbol.removesuffix(quote)
    return None


def _market_type(item: BybitUniverseInstrument) -> str:
    contract_type = (item.contract_type or "").strip()
    if item.category == "linear" and contract_type.lower() == "linearperpetual":
        return "linear_perpetual"
    if item.category == "spot":
        return "spot"
    return _snake_case(contract_type) or item.category


def _snake_case(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    result: list[str] = []
    for index, char in enumerate(normalized):
        if char.isupper() and index > 0 and normalized[index - 1].islower():
            result.append("_")
        result.append(char.lower())
    return "".join(result).replace("-", "_").replace(" ", "_")


def _liquidity_tier(turnover_24h: Decimal | None) -> str:
    if turnover_24h is None:
        return "unknown"
    if turnover_24h >= settings.market_universe_high_turnover_24h:
        return "high"
    if turnover_24h >= settings.market_universe_medium_turnover_24h:
        return "medium"
    return "low"


def _ticker_decimal(
    ticker: BybitTicker | None,
    raw_key: str,
    attr: str,
) -> Decimal | None:
    if ticker is None:
        return None
    parsed = _decimal_or_none(ticker.raw_payload.get(raw_key))
    if parsed is not None:
        return parsed
    return _decimal_or_none(getattr(ticker, attr, None))


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _oi_change(previous_open_interest: Decimal | None, current_open_interest: Decimal | None) -> Decimal | None:
    if previous_open_interest is None or current_open_interest is None or previous_open_interest <= 0:
        return None
    return (current_open_interest - previous_open_interest) / previous_open_interest


def _pair_metadata(
    existing: dict[str, Any] | None,
    item: BybitUniverseInstrument,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    metadata["market_universe"] = {
        "source": MARKET_UNIVERSE_SOURCE,
        "contract_type": item.contract_type,
        "launch_time": item.launch_time,
        "delivery_time": item.delivery_time,
        "turnover_rank": item.turnover_rank,
        "instrument": dict(item.instrument.raw_payload),
        "ticker": dict(item.ticker.raw_payload) if item.ticker is not None else None,
    }
    return metadata
