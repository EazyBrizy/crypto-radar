from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Literal, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.exchanges.bybit import (
    BYBIT_API_URL,
    BybitPositionInfo,
    BybitWalletBalance,
    fetch_bybit_positions,
    fetch_bybit_wallet_balance,
)
from app.models.exchange_connection import UserExchangeConnection
from app.models.market import MarketExchange
from app.models.user import AppUser
from app.schemas.risk import AccountRiskSnapshot, PositionRiskSummary
from app.services.exchange_connection_service import exchange_connection_service
from app.services.user_identity import resolve_app_user

logger = logging.getLogger(__name__)

BybitWalletFetcher = Callable[..., BybitWalletBalance]
BybitPositionFetcher = Callable[..., list[BybitPositionInfo]]


class ExchangeCredentialProvider(Protocol):
    def load_credentials(self, key_ref: str) -> dict[str, str] | None:
        ...


@dataclass(frozen=True)
class _ConnectionLookup:
    connection: UserExchangeConnection | None
    warning: str | None = None


@dataclass(frozen=True)
class _CachedSnapshot:
    snapshot: AccountRiskSnapshot
    stored_at_monotonic: float


class ExchangeAccountSnapshotService:
    """Builds live account risk snapshots from exchange wallet and positions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        *,
        credential_provider: ExchangeCredentialProvider = exchange_connection_service,
        bybit_wallet_fetcher: BybitWalletFetcher = fetch_bybit_wallet_balance,
        bybit_position_fetcher: BybitPositionFetcher = fetch_bybit_positions,
        snapshot_ttl_seconds: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._credential_provider = credential_provider
        self._bybit_wallet_fetcher = bybit_wallet_fetcher
        self._bybit_position_fetcher = bybit_position_fetcher
        self._snapshot_ttl_seconds = int(
            settings.exchange_account_snapshot_ttl_seconds
            if snapshot_ttl_seconds is None
            else snapshot_ttl_seconds
        )
        self._cache: dict[tuple[str, str, str, str, str], _CachedSnapshot] = {}

    def get_snapshot(
        self,
        *,
        user_id: str | UUID,
        exchange: str = "bybit",
        connection_id: UUID | None = None,
        mode: Literal["real", "virtual"] = "real",
        force_refresh: bool = False,
    ) -> AccountRiskSnapshot:
        normalized_exchange = exchange.strip().lower()
        if mode == "virtual":
            return _missing_snapshot(
                source="virtual",
                warnings=["Exchange account snapshot is not used for virtual mode."],
            )
        if normalized_exchange != "bybit":
            return _missing_snapshot(
                source="exchange",
                warnings=[
                    f"Exchange account snapshot is not implemented for exchange {normalized_exchange}."
                ],
            )

        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            lookup = _find_connection(
                session=session,
                user=user,
                exchange_code=normalized_exchange,
                connection_id=connection_id,
            )
            if lookup.connection is None:
                return _missing_snapshot(
                    source="exchange",
                    warnings=[lookup.warning or "Active exchange connection is missing."],
                )
            connection = lookup.connection
            account_type = _wallet_account_type(connection)
            cache_key = (
                str(user.id),
                normalized_exchange,
                str(connection.id),
                account_type,
                mode,
            )
            cached = self._cache.get(cache_key)
            if not force_refresh:
                cached_snapshot = self._fresh_cached_snapshot(cached)
                if cached_snapshot is not None:
                    return cached_snapshot

            credentials = self._credential_provider.load_credentials(connection.key_ref)
            if credentials is None:
                return self._failure_snapshot(
                    cache_key,
                    cached,
                    warnings=[
                        "Exchange credentials are not available in the configured secret provider."
                    ],
                )
            api_key = credentials.get("api_key")
            api_secret = credentials.get("api_secret")
            if not api_key or not api_secret:
                return self._failure_snapshot(
                    cache_key,
                    cached,
                    warnings=["Bybit account snapshot requires api_key and api_secret."],
                )

            try:
                wallet = self._bybit_wallet_fetcher(
                    api_key=api_key,
                    api_secret=api_secret,
                    account_type=account_type,
                    coin=_wallet_coin(connection),
                    base_url=_bybit_base_url(connection),
                )
            except Exception as exc:
                logger.warning(
                    "Bybit wallet balance lookup failed for user=%s connection=%s: %s",
                    user.id,
                    connection.id,
                    exc,
                )
                return self._failure_snapshot(
                    cache_key,
                    cached,
                    warnings=[f"Bybit wallet balance is unavailable: {exc}"],
                )

            snapshot = self._snapshot_from_bybit_wallet(
                connection=connection,
                wallet=wallet,
                api_key=api_key,
                api_secret=api_secret,
                fetched_at=datetime.now(timezone.utc),
            )
            self._cache[cache_key] = _CachedSnapshot(
                snapshot=snapshot.model_copy(deep=True),
                stored_at_monotonic=time.monotonic(),
            )
            return snapshot

    def get_real_account_snapshot(
        self,
        *,
        user_id: str,
        exchange: str,
        mode: str,
        live_adapter: bool,
        request_account_balance: float | Decimal | None = None,
        reference: object | None = None,
    ) -> AccountRiskSnapshot:
        if not live_adapter:
            from app.services.risk_state import RiskStateService

            return RiskStateService(self._session_factory).get_real_account_snapshot(
                user_id=user_id,
                exchange=exchange,
                mode=mode,
                live_adapter=False,
                request_account_balance=request_account_balance,
                reference=reference,
            )
        connection_id = _reference_uuid(reference, "exchange_connection_id", "connection_id")
        return self.get_snapshot(
            user_id=user_id,
            exchange=exchange,
            connection_id=connection_id,
            mode="real",
        )

    def _fresh_cached_snapshot(
        self,
        cached: _CachedSnapshot | None,
    ) -> AccountRiskSnapshot | None:
        if cached is None or self._snapshot_ttl_seconds <= 0:
            return None
        age_seconds = time.monotonic() - cached.stored_at_monotonic
        if age_seconds > self._snapshot_ttl_seconds:
            return None
        return cached.snapshot.model_copy(deep=True)

    def _failure_snapshot(
        self,
        cache_key: tuple[str, str, str, str, str],
        cached: _CachedSnapshot | None,
        *,
        warnings: list[str],
    ) -> AccountRiskSnapshot:
        cached = cached or self._cache.get(cache_key)
        if cached is not None:
            snapshot = cached.snapshot.model_copy(deep=True)
            return snapshot.model_copy(
                update={
                    "status": "stale",
                    "warnings": _dedupe([*snapshot.warnings, *warnings]),
                }
            )
        return _missing_snapshot(source="exchange", warnings=warnings)

    def _snapshot_from_bybit_wallet(
        self,
        *,
        connection: UserExchangeConnection,
        wallet: BybitWalletBalance,
        api_key: str,
        api_secret: str,
        fetched_at: datetime,
    ) -> AccountRiskSnapshot:
        warnings: list[str] = []
        account_equity = _positive_decimal(wallet.total_equity)
        available_balance = _non_negative_decimal(wallet.total_available_balance)
        wallet_balance = _non_negative_decimal(wallet.total_wallet_balance)
        total_initial_margin = _non_negative_decimal(wallet.total_initial_margin)
        total_maintenance_margin = _non_negative_decimal(wallet.total_maintenance_margin)
        if account_equity is None:
            warnings.append("Bybit wallet total_equity is missing or not positive.")
        if available_balance is None:
            warnings.append("Bybit wallet total_available_balance is missing.")

        positions: list[PositionRiskSummary] = []
        try:
            raw_positions = self._bybit_position_fetcher(
                api_key=api_key,
                api_secret=api_secret,
                category=_position_category(connection),
                symbol=None,
                base_url=_bybit_base_url(connection),
            )
        except Exception as exc:
            logger.warning(
                "Bybit position-list lookup failed for connection=%s: %s",
                connection.id,
                exc,
            )
            warnings.append(f"Bybit positions are unavailable: {exc}")
        else:
            positions = _position_summaries(raw_positions)

        return AccountRiskSnapshot(
            status="fresh",
            fetched_at=fetched_at,
            account_equity=account_equity,
            available_balance=available_balance,
            wallet_balance=wallet_balance,
            margin_mode=_account_margin_mode(connection, positions),
            total_initial_margin=total_initial_margin,
            total_maintenance_margin=total_maintenance_margin,
            maintenance_margin_rate=None,
            positions=positions,
            open_risk_amount=_open_risk_amount(positions),
            source="exchange",
            warnings=_dedupe(warnings),
        )


def _find_connection(
    *,
    session: Session,
    user: AppUser,
    exchange_code: str,
    connection_id: UUID | None,
) -> _ConnectionLookup:
    if connection_id is not None:
        connection = session.scalars(
            _connection_select().where(UserExchangeConnection.id == connection_id)
        ).one_or_none()
        if connection is None:
            return _ConnectionLookup(
                None,
                f"Exchange connection not found: {connection_id}",
            )
        if connection.user_id != user.id:
            return _ConnectionLookup(
                None,
                "Exchange connection does not belong to the resolved user.",
            )
        if connection.exchange.code.strip().lower() != exchange_code:
            return _ConnectionLookup(
                None,
                f"Exchange connection is not for exchange {exchange_code}.",
            )
        if connection.status.strip().lower() != "active":
            return _ConnectionLookup(None, "Exchange connection is not active.")
        return _ConnectionLookup(connection)

    connection = session.scalars(
        _connection_select()
        .where(UserExchangeConnection.user_id == user.id)
        .where(UserExchangeConnection.status == "active")
        .where(UserExchangeConnection.exchange.has(MarketExchange.code == exchange_code))
        .order_by(UserExchangeConnection.created_at.desc())
    ).first()
    if connection is None:
        return _ConnectionLookup(
            None,
            f"Active {exchange_code} exchange connection is missing for user.",
        )
    return _ConnectionLookup(connection)


def _connection_select():
    return select(UserExchangeConnection).options(
        joinedload(UserExchangeConnection.exchange),
        joinedload(UserExchangeConnection.user),
    )


def _wallet_account_type(connection: UserExchangeConnection) -> str:
    metadata = _metadata_dict(connection)
    raw = (
        metadata.get("accountType")
        or metadata.get("account_type")
        or metadata.get("wallet_account_type")
        or "UNIFIED"
    )
    text = str(raw).strip()
    return text or "UNIFIED"


def _wallet_coin(connection: UserExchangeConnection) -> str | None:
    metadata = _metadata_dict(connection)
    raw = metadata.get("wallet_coin", "USDT")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _position_category(connection: UserExchangeConnection) -> str:
    metadata = _metadata_dict(connection)
    raw = metadata.get("position_category") or metadata.get("category")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    normalized_account_type = connection.account_type.strip().lower()
    if normalized_account_type in {"inverse", "inverse_perpetual"}:
        return "inverse"
    if normalized_account_type == "option":
        return "option"
    return "linear"


def _bybit_base_url(connection: UserExchangeConnection) -> str:
    metadata = _metadata_dict(connection)
    if metadata.get("testnet") is True:
        return "https://api-testnet.bybit.com"
    api_base_url = connection.exchange.api_base_url
    if isinstance(api_base_url, str) and api_base_url:
        return api_base_url.rstrip("/")
    return BYBIT_API_URL


def _account_margin_mode(
    connection: UserExchangeConnection,
    positions: list[PositionRiskSummary],
) -> str | None:
    metadata = _metadata_dict(connection)
    raw = metadata.get("margin_mode")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    for position in positions:
        if position.margin_mode:
            return position.margin_mode
    return None


def _metadata_dict(connection: UserExchangeConnection) -> dict[str, Any]:
    metadata = connection.metadata_ or {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _position_summaries(
    positions: list[BybitPositionInfo],
) -> list[PositionRiskSummary]:
    summaries: list[PositionRiskSummary] = []
    for position in positions:
        summary = _position_summary(position)
        if summary is not None:
            summaries.append(summary)
    return summaries


def _position_summary(position: BybitPositionInfo) -> PositionRiskSummary | None:
    raw = position.raw_payload if isinstance(position.raw_payload, Mapping) else {}
    quantity = _non_negative_decimal(_first_value(raw, "size", "qty") or position.size)
    if quantity is None or quantity <= 0:
        return None
    entry_price = _positive_decimal(_first_value(raw, "avgPrice", "entryPrice"))
    mark_price = _positive_decimal(_first_value(raw, "markPrice", "indexPrice"))
    notional = _non_negative_decimal(
        _first_value(raw, "positionValue", "notional", "positionBalance")
    )
    if notional is None and mark_price is not None:
        notional = abs(quantity * mark_price)
    return PositionRiskSummary(
        symbol=position.symbol,
        side=_position_side(position.side),
        quantity=quantity,
        notional=notional,
        entry_price=entry_price,
        mark_price=mark_price,
        unrealized_pnl=_decimal_or_none(
            _first_value(raw, "unrealisedPnl", "unrealizedPnl", "curRealisedPnl")
        ),
        risk_amount=None,
        initial_margin=_non_negative_decimal(
            _first_value(raw, "positionIM", "positionInitialMargin", "initialMargin")
        ),
        maintenance_margin=_non_negative_decimal(
            _first_value(raw, "positionMM", "maintenanceMargin")
        ),
        margin_mode=_position_margin_mode(raw),
    )


def _position_side(value: object) -> Literal["long", "short", "unknown"]:
    normalized = str(value or "").strip().lower()
    if normalized in {"buy", "long"}:
        return "long"
    if normalized in {"sell", "short"}:
        return "short"
    return "unknown"


def _position_margin_mode(raw: Mapping[str, Any]) -> str | None:
    raw_mode = _first_value(raw, "marginMode", "margin_mode")
    if isinstance(raw_mode, str) and raw_mode.strip():
        return raw_mode.strip().lower()
    trade_mode = _first_value(raw, "tradeMode")
    if str(trade_mode) == "0":
        return "cross"
    if str(trade_mode) == "1":
        return "isolated"
    return None


def _open_risk_amount(positions: list[PositionRiskSummary]) -> Decimal:
    total = Decimal("0")
    for position in positions:
        if position.risk_amount is not None:
            total += position.risk_amount
    return total


def _first_value(raw: Mapping[str, Any], *keys: str) -> object | None:
    for key in keys:
        value = raw.get(key)
        if value is not None and value != "":
            return value
    return None


def _positive_decimal(value: object) -> Decimal | None:
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def _non_negative_decimal(value: object) -> Decimal | None:
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None and parsed >= 0 else None


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _missing_snapshot(
    *,
    source: Literal["exchange", "virtual"],
    warnings: list[str],
) -> AccountRiskSnapshot:
    return AccountRiskSnapshot(
        status="missing",
        fetched_at=None,
        account_equity=None,
        available_balance=None,
        wallet_balance=None,
        margin_mode=None,
        total_initial_margin=None,
        total_maintenance_margin=None,
        positions=[],
        open_risk_amount=Decimal("0"),
        source=source,
        warnings=_dedupe(warnings),
    )


def _reference_uuid(reference: object | None, *names: str) -> UUID | None:
    if reference is None:
        return None
    for name in names:
        if not hasattr(reference, name):
            continue
        value = getattr(reference, name)
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            continue
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


exchange_account_snapshot_service = ExchangeAccountSnapshotService()
