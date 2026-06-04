from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.exchanges.bybit import BybitApiError, BybitInstrumentInfo, BybitInstrumentRule, fetch_bybit_instrument_rules
from app.models.market import MarketExchange, MarketPair
from app.models.risk import ExchangeInstrumentRule
from app.schemas.exchange_connection import ExchangeInstrumentRuleResponse


class ExchangeInstrumentRuleService:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def get_rule(
        self,
        *,
        exchange_code: str,
        symbol: str,
        category: str | None = None,
    ) -> ExchangeInstrumentRule | None:
        with self._session_factory() as session:
            return _get_rule(
                session,
                exchange_code=exchange_code,
                symbol=symbol,
                category=category,
            )

    def sync_bybit_rules(
        self,
        *,
        category: str = "linear",
        symbol: str | None = None,
    ) -> list[ExchangeInstrumentRuleResponse]:
        try:
            fetched_rules = fetch_bybit_instrument_rules(category=category, symbol=symbol)
        except BybitApiError as exc:
            raise ValueError(str(exc)) from exc

        with self._session_factory() as session:
            exchange = _get_exchange(session, "bybit")
            now = datetime.now(timezone.utc)
            responses: list[ExchangeInstrumentRuleResponse] = []
            for fetched in fetched_rules:
                pair = _get_pair(session, exchange.id, fetched.symbol)
                record = upsert_bybit_instrument_rule(
                    session,
                    exchange=exchange,
                    fetched=fetched,
                    pair=pair,
                    fetched_at=now,
                    source="bybit_api",
                )
                responses.append(_rule_to_response(record, exchange.code))
            session.commit()
            return responses

    def list_rules(
        self,
        *,
        exchange_code: str = "bybit",
        category: str | None = None,
        symbol: str | None = None,
        limit: int = 200,
    ) -> list[ExchangeInstrumentRuleResponse]:
        with self._session_factory() as session:
            exchange = _get_exchange(session, exchange_code)
            statement = (
                select(ExchangeInstrumentRule)
                .where(ExchangeInstrumentRule.exchange_id == exchange.id)
                .order_by(ExchangeInstrumentRule.symbol.asc())
                .limit(limit)
            )
            if category is not None:
                statement = statement.where(ExchangeInstrumentRule.category == category)
            if symbol is not None:
                statement = statement.where(ExchangeInstrumentRule.symbol == symbol.strip().upper())
            return [
                _rule_to_response(record, exchange.code)
                for record in session.scalars(statement).all()
            ]


def upsert_bybit_instrument_info_rule(
    session: Session,
    *,
    exchange: MarketExchange,
    instrument: BybitInstrumentInfo,
    pair: MarketPair | None,
    fetched_at: datetime | None = None,
    source: str = "bybit_market_universe",
) -> ExchangeInstrumentRule:
    return upsert_bybit_instrument_rule(
        session,
        exchange=exchange,
        fetched=_instrument_info_to_rule(instrument),
        pair=pair,
        fetched_at=fetched_at,
        source=source,
    )


def upsert_bybit_instrument_rule(
    session: Session,
    *,
    exchange: MarketExchange,
    fetched: BybitInstrumentRule,
    pair: MarketPair | None,
    fetched_at: datetime | None = None,
    source: str = "bybit_api",
) -> ExchangeInstrumentRule:
    now = fetched_at or datetime.now(timezone.utc)
    record = session.scalars(
        select(ExchangeInstrumentRule).where(
            ExchangeInstrumentRule.exchange_id == exchange.id,
            ExchangeInstrumentRule.category == fetched.category,
            ExchangeInstrumentRule.symbol == fetched.symbol,
        )
    ).one_or_none()
    values: dict[str, Any] = {
        "exchange_id": exchange.id,
        "pair_id": pair.id if pair is not None else None,
        "symbol": fetched.symbol,
        "category": fetched.category,
        "min_order_size": _decimal_or_none(fetched.min_order_size),
        "max_order_size": _decimal_or_none(fetched.max_order_size),
        "min_notional": _decimal_or_none(fetched.min_notional),
        "qty_step": _decimal_or_none(fetched.qty_step),
        "tick_size": _decimal_or_none(fetched.tick_size),
        "max_leverage": fetched.max_leverage,
        "funding_interval_minutes": fetched.funding_interval_minutes,
        "raw_payload": fetched.raw_payload,
        "source": source,
        "fetched_at": now,
        "updated_at": now,
    }
    if record is None:
        record = ExchangeInstrumentRule(id=uuid4(), **values)
        session.add(record)
    else:
        for key, value in values.items():
            setattr(record, key, value)
    if pair is not None:
        if fetched.min_order_size is not None:
            pair.min_qty = _decimal_or_none(fetched.min_order_size)
        if fetched.qty_step is not None:
            pair.lot_size = _decimal_or_none(fetched.qty_step)
        if fetched.tick_size is not None:
            pair.tick_size = _decimal_or_none(fetched.tick_size)
    session.flush()
    return record


def _get_rule(
    session: Session,
    *,
    exchange_code: str,
    symbol: str,
    category: str | None,
) -> ExchangeInstrumentRule | None:
    exchange = _get_exchange(session, exchange_code)
    statement = select(ExchangeInstrumentRule).where(
        ExchangeInstrumentRule.exchange_id == exchange.id,
        ExchangeInstrumentRule.symbol == symbol.strip().upper(),
    )
    if category is not None:
        statement = statement.where(ExchangeInstrumentRule.category == category)
    return session.scalars(
        statement.order_by(ExchangeInstrumentRule.updated_at.desc()).limit(1)
    ).one_or_none()


def _get_exchange(session: Session, exchange_code: str) -> MarketExchange:
    exchange = session.scalars(
        select(MarketExchange).where(MarketExchange.code == exchange_code.strip().lower())
    ).one_or_none()
    if exchange is None:
        raise LookupError(f"Market exchange is not seeded: {exchange_code}")
    return exchange


def _get_pair(session: Session, exchange_id, symbol: str) -> MarketPair | None:
    return session.scalars(
        select(MarketPair)
        .options(joinedload(MarketPair.base_asset))
        .where(
            MarketPair.exchange_id == exchange_id,
            MarketPair.symbol == symbol.strip().upper(),
        )
    ).one_or_none()


def _decimal_or_none(value: Any | None) -> Decimal | None:
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


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None


def _first_decimal_or_none(*values: object) -> Decimal | None:
    for value in values:
        parsed = _decimal_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _instrument_info_to_rule(instrument: BybitInstrumentInfo) -> BybitInstrumentRule:
    lot_filter = instrument.lot_size_filter if isinstance(instrument.lot_size_filter, dict) else {}
    price_filter = instrument.price_filter if isinstance(instrument.price_filter, dict) else {}
    leverage_filter = instrument.leverage_filter if isinstance(instrument.leverage_filter, dict) else {}
    min_notional = _first_decimal_or_none(
        lot_filter.get("minNotionalValue")
        or lot_filter.get("minOrderAmt"),
        lot_filter.get("minOrderValue"),
    )
    return BybitInstrumentRule(
        category=instrument.category,
        symbol=instrument.symbol,
        min_order_size=_first_decimal_or_none(
            lot_filter.get("minOrderQty")
            or lot_filter.get("minTradingQty"),
            instrument.raw_payload.get("minTradeQty"),
        ),
        max_order_size=_first_decimal_or_none(
            lot_filter.get("maxOrderQty")
            or lot_filter.get("maxTradingQty"),
            instrument.raw_payload.get("maxTradeQty"),
        ),
        min_notional=min_notional,
        qty_step=_first_decimal_or_none(lot_filter.get("qtyStep"), instrument.raw_payload.get("qtyStep")),
        tick_size=_first_decimal_or_none(price_filter.get("tickSize"), instrument.raw_payload.get("tickSize")),
        max_leverage=_int_or_none(leverage_filter.get("maxLeverage")),
        funding_interval_minutes=_int_or_none(instrument.raw_payload.get("fundingInterval")),
        raw_payload=instrument.raw_payload,
    )


def _rule_to_response(
    record: ExchangeInstrumentRule,
    exchange_code: str,
) -> ExchangeInstrumentRuleResponse:
    age_seconds = _age_seconds(record.fetched_at)
    ttl_seconds = settings.exchange_instrument_rules_ttl_seconds
    return ExchangeInstrumentRuleResponse(
        id=record.id,
        exchange_id=record.exchange_id,
        exchange_code=exchange_code,
        pair_id=record.pair_id,
        symbol=record.symbol,
        category=record.category,
        min_order_size=_float_or_none(record.min_order_size),
        max_order_size=_float_or_none(record.max_order_size),
        min_notional=_float_or_none(record.min_notional),
        qty_step=_float_or_none(record.qty_step),
        tick_size=_float_or_none(record.tick_size),
        max_leverage=record.max_leverage,
        funding_interval_minutes=record.funding_interval_minutes,
        source=record.source,
        fetched_at=record.fetched_at,
        updated_at=record.updated_at,
        age_seconds=age_seconds,
        ttl_seconds=ttl_seconds,
        is_stale=bool(ttl_seconds and age_seconds is not None and age_seconds > ttl_seconds),
    )


def _age_seconds(fetched_at: datetime | None) -> float | None:
    if fetched_at is None:
        return None
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - fetched_at).total_seconds())


exchange_instrument_rule_service = ExchangeInstrumentRuleService()
