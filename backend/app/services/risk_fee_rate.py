from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.schemas.exchange_connection import ExchangeFeeRateResponse
from app.schemas.user import RiskManagementSettings
from app.services.exchange_connection_service import exchange_connection_service

logger = logging.getLogger(__name__)

CONSERVATIVE_FEE_RATE_FALLBACK = 0.001


class FeeRateProvider(Protocol):
    def get_fee_rates_for_user(
        self,
        *,
        user_id: str = "demo_user",
        exchange_code: str = "bybit",
        category: str = "linear",
        symbol: str | None = None,
        account_type: str | None = None,
        allow_sync: bool = True,
    ) -> list[ExchangeFeeRateResponse]:
        ...


@dataclass(frozen=True)
class RiskFeeRateSnapshot:
    fee_rate: float
    maker_fee_rate: float | None = None
    taker_fee_rate: float | None = None
    source: str = "fallback"
    exchange: str | None = None
    category: str | None = None
    symbol: str | None = None
    account_type: str | None = None
    fetched_at: datetime | None = None
    warnings: tuple[str, ...] = ()


class RiskFeeRateService:
    """Resolves the fee rate used by risk sizing from cached exchange fees."""

    def __init__(
        self,
        *,
        provider: FeeRateProvider = exchange_connection_service,
        fallback_fee_rate: float = CONSERVATIVE_FEE_RATE_FALLBACK,
    ) -> None:
        self._provider = provider
        self._fallback_fee_rate = fallback_fee_rate

    def resolve(
        self,
        *,
        user_id: str,
        exchange: str,
        mode: str,
        instrument_type: str,
        symbol: str,
        risk_settings: RiskManagementSettings,
        requested_fee_rate: float = 0.0,
    ) -> RiskFeeRateSnapshot:
        category = _fee_category(instrument_type)
        normalized_exchange = exchange.strip().lower()
        normalized_symbol = symbol.strip().upper()
        if mode == "virtual" and risk_settings.virtual_fee_model == "manual":
            warnings = ()
            if requested_fee_rate <= 0:
                warnings = ("Manual virtual fee model is active, but request fee_rate is zero.",)
            return RiskFeeRateSnapshot(
                fee_rate=max(requested_fee_rate, 0.0),
                maker_fee_rate=requested_fee_rate,
                taker_fee_rate=requested_fee_rate,
                source="manual_request",
                exchange=normalized_exchange,
                category=category,
                symbol=normalized_symbol,
                warnings=warnings,
            )
        if normalized_exchange != "bybit":
            return self._fallback(
                exchange=normalized_exchange,
                category=category,
                symbol=normalized_symbol,
                requested_fee_rate=requested_fee_rate,
                reason=f"Cached fee-rate is unavailable for exchange {normalized_exchange}.",
            )
        try:
            rates = self._provider.get_fee_rates_for_user(
                user_id=user_id,
                exchange_code=normalized_exchange,
                category=category,
                symbol=normalized_symbol,
                account_type=category,
                allow_sync=True,
            )
        except Exception as exc:
            logger.warning("Fee-rate lookup failed for %s %s %s: %s", normalized_exchange, category, normalized_symbol, exc)
            return self._fallback(
                exchange=normalized_exchange,
                category=category,
                symbol=normalized_symbol,
                requested_fee_rate=requested_fee_rate,
                reason="Cached fee-rate is unavailable; using conservative fallback fee rate.",
            )
        rate = _select_rate(rates, category=category, symbol=normalized_symbol)
        if rate is None:
            return self._fallback(
                exchange=normalized_exchange,
                category=category,
                symbol=normalized_symbol,
                requested_fee_rate=requested_fee_rate,
                reason="Cached fee-rate is unavailable; using conservative fallback fee rate.",
            )
        fee_rate = max(rate.taker_fee_rate, rate.maker_fee_rate)
        return RiskFeeRateSnapshot(
            fee_rate=fee_rate,
            maker_fee_rate=rate.maker_fee_rate,
            taker_fee_rate=rate.taker_fee_rate,
            source=rate.source,
            exchange=rate.exchange_code,
            category=rate.category,
            symbol=rate.symbol or normalized_symbol,
            account_type=rate.account_type,
            fetched_at=rate.fetched_at,
        )

    def _fallback(
        self,
        *,
        exchange: str,
        category: str,
        symbol: str,
        requested_fee_rate: float,
        reason: str,
    ) -> RiskFeeRateSnapshot:
        fee_rate = max(self._fallback_fee_rate, requested_fee_rate, 0.0)
        return RiskFeeRateSnapshot(
            fee_rate=fee_rate,
            maker_fee_rate=fee_rate,
            taker_fee_rate=fee_rate,
            source="conservative_fallback",
            exchange=exchange,
            category=category,
            symbol=symbol,
            warnings=(reason,),
        )


def _fee_category(instrument_type: str) -> str:
    return "linear" if instrument_type == "futures" else "spot"


def _select_rate(
    rates: list[ExchangeFeeRateResponse],
    *,
    category: str,
    symbol: str,
) -> ExchangeFeeRateResponse | None:
    for rate in rates:
        if rate.category == category and rate.symbol == symbol:
            return rate
    for rate in rates:
        if rate.category == category and rate.symbol is None:
            return rate
    return rates[0] if rates else None


risk_fee_rate_service = RiskFeeRateService()
