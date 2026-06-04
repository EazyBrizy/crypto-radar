from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.config import settings as app_settings
from app.core.database import SessionLocal
from app.models.exchange_connection import UserExchangeConnection
from app.models.market import MarketAsset, MarketExchange, MarketPair
from app.models.portfolio import Portfolio, Position
from app.models.risk import AssetRiskGroup, ExchangeInstrumentRule, RiskProtectionState
from app.models.user import AppUser, UserProfile
from app.schemas.risk import AccountRiskSnapshot, PositionRiskSummary, RiskStateResponse
from app.schemas.user import RiskManagementSettings
from app.services.user_identity import DEMO_USER_ALIASES, resolve_app_user


@dataclass(frozen=True)
class RiskReferenceSnapshot:
    state: RiskStateResponse
    exchange_min_order_size: float | None = None
    exchange_max_order_size: float | None = None
    exchange_min_notional: float | None = None
    exchange_qty_step: float | None = None
    exchange_tick_size: float | None = None
    exchange_max_leverage: int | None = None
    exchange_rule_status: str = "unknown"
    exchange_rule_age_seconds: float | None = None
    exchange_rule_ttl_seconds: int | None = None
    exchange_instrument_rules: dict[str, object] | None = None
    correlation_group: str | None = None
    open_risk_amount: float = 0.0
    correlated_open_risk_amount: float = 0.0
    daily_loss_amount: float = 0.0
    user_mode_multiplier: float = 1.0
    protection_state: str = "normal"
    protection_reason: str | None = None
    account_drawdown_percent: float = 0.0
    max_account_drawdown_percent: float = 0.0
    account_snapshot: AccountRiskSnapshot | None = None
    position_reconciliation_enabled: bool = False


class RiskStateService:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        *,
        account_snapshot_provider: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._account_snapshot_provider = account_snapshot_provider

    def get_state(
        self,
        *,
        user_id: str = "demo_user",
        mode: str | None = None,
        exchange: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        instrument_type: str | None = None,
    ) -> RiskStateResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            settings = _risk_settings(session, user)
            equity = _portfolio_equity(session, user)
            state = _get_or_create_state(session, user, equity)
            _reset_protection_windows(state, user)
            _apply_protection_policy(state, settings)
            reference = _reference_from_session(
                session=session,
                user=user,
                settings=settings,
                state=state,
                equity=equity,
                mode=mode,
                exchange=exchange,
                symbol=symbol,
                side=side,
                instrument_type=instrument_type,
            )
            session.commit()
            return reference.state

    def get_reference(
        self,
        *,
        user_id: str,
        mode: str,
        exchange: str,
        symbol: str,
        side: str,
        instrument_type: str | None = None,
        read_only: bool = False,
    ) -> RiskReferenceSnapshot:
        with self._session_factory() as session:
            flush_context = session.no_autoflush if read_only else nullcontext()
            with flush_context:
                user = resolve_app_user(session, user_id)
                settings = _risk_settings(session, user)
                equity = _portfolio_equity(session, user)
                state = _get_or_create_state(
                    session,
                    user,
                    equity,
                    persist=not read_only,
                )
                _reset_protection_windows(state, user)
                _apply_protection_policy(state, settings)
                reference = _reference_from_session(
                    session=session,
                    user=user,
                    settings=settings,
                    state=state,
                    equity=equity,
                    mode=mode,
                    exchange=exchange,
                    symbol=symbol,
                    side=side,
                    instrument_type=instrument_type,
                )
            if read_only:
                session.rollback()
            else:
                session.commit()
            return reference

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
            return _dry_run_account_snapshot(
                user_id=user_id,
                request_account_balance=request_account_balance,
            )

        reference_snapshot = _account_snapshot_from_reference(reference)
        if reference_snapshot is not None:
            return reference_snapshot

        provider = self._account_snapshot_provider or _default_account_snapshot_provider()
        if mode == "real" and provider is not None and provider is not self:
            if hasattr(provider, "get_real_account_snapshot"):
                return provider.get_real_account_snapshot(
                    user_id=user_id,
                    exchange=exchange,
                    mode=mode,
                    live_adapter=live_adapter,
                    request_account_balance=request_account_balance,
                    reference=reference,
                )
            if hasattr(provider, "get_snapshot"):
                return provider.get_snapshot(
                    user_id=user_id,
                    exchange=exchange,
                    mode="real",
                )

        return AccountRiskSnapshot(
            status="missing",
            fetched_at=None,
            account_equity=None,
            available_balance=None,
            margin_mode=None,
            positions=[],
            open_risk_amount=Decimal("0"),
            source="exchange",
            warnings=[
                (
                    "Live real execution requires a fresh exchange account snapshot; "
                    "request.account_balance is ignored."
                )
            ],
        )

    def update_after_trade_close(
        self,
        *,
        session: Session,
        user: AppUser,
        realized_pnl: Decimal,
        current_equity: Decimal,
        risk_settings: RiskManagementSettings | None = None,
    ) -> RiskProtectionState:
        settings = risk_settings or _risk_settings(session, user)
        state = _get_or_create_state(session, user, current_equity)
        _reset_protection_windows(state, user)
        pnl = Decimal(str(realized_pnl))
        if pnl < 0:
            loss = abs(pnl)
            state.loss_streak += 1
            state.daily_loss_amount += loss
            state.weekly_loss_amount += loss
        elif pnl > 0:
            state.loss_streak = 0

        state.current_equity = max(current_equity, Decimal("0"))
        state.peak_equity = max(state.peak_equity, state.current_equity)
        _apply_protection_policy(state, settings)
        state.updated_at = datetime.now(timezone.utc)
        return state


def _reference_from_session(
    *,
    session: Session,
    user: AppUser,
    settings: RiskManagementSettings,
    state: RiskProtectionState,
    equity: Decimal,
    mode: str | None,
    exchange: str | None,
    symbol: str | None,
    side: str | None,
    instrument_type: str | None,
) -> RiskReferenceSnapshot:
    pair = _get_pair(session, exchange, symbol) if exchange and symbol else None
    category = _instrument_category(instrument_type)
    rule = _get_rule(session, exchange, symbol, category=category) if exchange and symbol else None
    rule_status, rule_age_seconds = _rule_freshness(rule, has_symbol=bool(exchange and symbol))
    correlation_group = _primary_group_for_symbol(session, pair=pair, symbol=symbol)
    open_risk, correlated_risk = _open_risk(
        session=session,
        user=user,
        mode=mode,
        correlation_group=correlation_group,
        side=side,
    )
    equity_float = float(equity) if equity > 0 else 0.0
    daily_loss_percent = _percent(state.daily_loss_amount, equity)
    weekly_loss_percent = _percent(state.weekly_loss_amount, equity)
    account_drawdown_percent = _account_drawdown_percent(state)
    open_risk_percent = _percent(open_risk, equity)
    correlated_risk_percent = _percent(correlated_risk, equity)
    reconciliation_blocker = _live_reconciliation_blocker(
        session=session,
        user=user,
        mode=mode,
        exchange=exchange,
    )
    protection_state = "blocked" if reconciliation_blocker else state.state
    protection_reason = reconciliation_blocker or state.reason
    flags = _protection_flags(protection_state)
    response = RiskStateResponse(
        user_id=user.username or str(user.id),
        mode=mode if mode in {"virtual", "real"} else None,
        protection_state=protection_state,
        protection_reason=protection_reason,
        close_only=flags["close_only"],
        real_entries_allowed=flags["real_entries_allowed"],
        virtual_entries_allowed=flags["virtual_entries_allowed"],
        reduce_only_allowed=flags["reduce_only_allowed"],
        protective_orders_allowed=flags["protective_orders_allowed"],
        loss_streak=state.loss_streak,
        daily_loss_amount=float(state.daily_loss_amount),
        weekly_loss_amount=float(state.weekly_loss_amount),
        daily_window_start=state.daily_window_start,
        weekly_window_start=state.weekly_window_start,
        window_timezone=state.window_timezone,
        peak_equity=float(state.peak_equity),
        current_equity=equity_float,
        adaptive_multiplier=float(state.adaptive_multiplier),
        daily_loss_percent=daily_loss_percent,
        weekly_loss_percent=weekly_loss_percent,
        account_drawdown_percent=account_drawdown_percent,
        max_account_drawdown_percent=settings.max_account_drawdown_percent,
        open_risk_amount=float(open_risk),
        open_risk_percent=open_risk_percent,
        max_open_risk_percent=settings.max_open_risk_percent,
        correlated_risk_amount=float(correlated_risk),
        correlated_risk_percent=correlated_risk_percent,
        max_correlated_risk_percent=settings.max_correlated_risk_percent,
        correlation_group=correlation_group,
        exchange_rule_status=rule_status,
        exchange_rule_age_seconds=rule_age_seconds,
        exchange_rule_ttl_seconds=app_settings.exchange_instrument_rules_ttl_seconds,
    )
    return RiskReferenceSnapshot(
        state=response,
        exchange_min_order_size=_float_or_none(rule.min_order_size if rule else None),
        exchange_max_order_size=_float_or_none(rule.max_order_size if rule else None),
        exchange_min_notional=_float_or_none(rule.min_notional if rule else None),
        exchange_qty_step=_float_or_none(rule.qty_step if rule else None),
        exchange_tick_size=_float_or_none(rule.tick_size if rule else None),
        exchange_max_leverage=rule.max_leverage if rule else None,
        exchange_rule_status=rule_status,
        exchange_rule_age_seconds=rule_age_seconds,
        exchange_rule_ttl_seconds=app_settings.exchange_instrument_rules_ttl_seconds,
        exchange_instrument_rules=_instrument_rule_snapshot(rule),
        correlation_group=correlation_group,
        open_risk_amount=float(open_risk),
        correlated_open_risk_amount=float(correlated_risk),
        daily_loss_amount=float(state.daily_loss_amount),
        user_mode_multiplier=float(state.adaptive_multiplier),
        protection_state=protection_state,
        protection_reason=protection_reason,
        account_drawdown_percent=account_drawdown_percent,
        max_account_drawdown_percent=settings.max_account_drawdown_percent,
    )


def _get_or_create_state(
    session: Session,
    user: AppUser,
    equity: Decimal,
    *,
    persist: bool = True,
) -> RiskProtectionState:
    state = session.get(RiskProtectionState, user.id)
    now = datetime.now(timezone.utc)
    if state is None:
        state = RiskProtectionState(
            user_id=user.id,
            state="normal",
            loss_streak=0,
            daily_loss_amount=Decimal("0"),
            weekly_loss_amount=Decimal("0"),
            daily_window_start=None,
            weekly_window_start=None,
            window_timezone=_user_timezone_name(user),
            peak_equity=max(equity, Decimal("0")),
            current_equity=max(equity, Decimal("0")),
            adaptive_multiplier=Decimal("1"),
            created_at=now,
            updated_at=now,
        )
        if persist:
            session.add(state)
            session.flush()
        return state
    state.current_equity = max(equity, Decimal("0"))
    state.peak_equity = max(state.peak_equity, state.current_equity)
    return state


def _reset_protection_windows(
    state: RiskProtectionState,
    user: AppUser,
    now: datetime | None = None,
) -> None:
    tz_name = _user_timezone_name(user)
    daily_start, weekly_start = _window_starts(now or datetime.now(timezone.utc), tz_name)
    state.window_timezone = tz_name
    if state.daily_window_start is None or _as_utc(state.daily_window_start) < daily_start:
        state.daily_loss_amount = Decimal("0")
        state.daily_window_start = daily_start
    if state.weekly_window_start is None or _as_utc(state.weekly_window_start) < weekly_start:
        state.weekly_loss_amount = Decimal("0")
        state.weekly_window_start = weekly_start


def _window_starts(now: datetime, timezone_name: str) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    zone = _user_zone(timezone_name)
    local_now = now.astimezone(zone)
    local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_week_start = local_day_start - timedelta(days=local_day_start.weekday())
    return (
        local_day_start.astimezone(timezone.utc),
        local_week_start.astimezone(timezone.utc),
    )


def _user_timezone_name(user: AppUser) -> str:
    return user.timezone or "UTC"


def _user_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _apply_protection_policy(
    state: RiskProtectionState,
    settings: RiskManagementSettings,
) -> None:
    equity = state.current_equity if state.current_equity > 0 else state.peak_equity
    daily_loss_percent = _percent_decimal(state.daily_loss_amount, equity)
    weekly_loss_percent = _percent_decimal(state.weekly_loss_amount, equity)
    drawdown_percent = (
        (state.peak_equity - state.current_equity) / state.peak_equity * Decimal("100")
        if state.peak_equity > 0
        else Decimal("0")
    )
    if state.loss_streak >= 3:
        state.adaptive_multiplier = Decimal("0.5")
    elif state.loss_streak >= 2:
        state.adaptive_multiplier = Decimal("0.75")
    else:
        state.adaptive_multiplier = Decimal("1")

    if _limit_enabled(settings.max_account_drawdown_percent) and drawdown_percent >= Decimal(str(settings.max_account_drawdown_percent)):
        state.state = "blocked"
        state.reason = "Risk protection mode blocks entries after account drawdown."
    elif _limit_enabled(settings.max_weekly_loss_percent) and weekly_loss_percent >= Decimal(str(settings.max_weekly_loss_percent)):
        state.state = "blocked"
        state.reason = "Risk protection mode blocks entries after weekly loss limit."
    elif _limit_enabled(settings.max_daily_loss_percent) and daily_loss_percent >= Decimal(str(settings.max_daily_loss_percent)):
        state.state = "blocked"
        state.reason = "Risk protection mode blocks entries after daily loss limit."
    elif settings.auto_reduce_risk_after_losses and daily_loss_percent >= Decimal("2"):
        state.state = "virtual_only"
        state.reason = "Daily drawdown reached the virtual-only protection threshold."
    elif state.adaptive_multiplier < 1:
        state.state = "reduced"
        state.reason = "Risk is reduced after consecutive losing trades."
    else:
        state.state = "normal"
        state.reason = None


def _protection_flags(state: str) -> dict[str, bool]:
    return {
        "close_only": state in {"virtual_only", "blocked"},
        "real_entries_allowed": state not in {"virtual_only", "blocked"},
        "virtual_entries_allowed": state != "blocked",
        "reduce_only_allowed": True,
        "protective_orders_allowed": True,
    }


def _live_reconciliation_blocker(
    *,
    session: Session,
    user: AppUser,
    mode: str | None,
    exchange: str | None,
) -> str | None:
    if mode != "real" or exchange is None:
        return None
    connection = session.scalars(
        select(UserExchangeConnection)
        .where(UserExchangeConnection.user_id == user.id)
        .where(UserExchangeConnection.status == "active")
        .where(UserExchangeConnection.exchange.has(MarketExchange.code == exchange.strip().lower()))
        .order_by(UserExchangeConnection.created_at.desc())
        .limit(1)
    ).one_or_none()
    if connection is None:
        return None
    sync_state = (connection.metadata_ or {}).get("real_position_sync")
    if not isinstance(sync_state, dict) or not sync_state.get("live_entry_blocked"):
        return None
    reason = sync_state.get("live_entry_block_reason")
    if isinstance(reason, str) and reason.strip():
        return f"Live entries blocked by exchange reconciliation: {reason.strip()}."
    return "Live entries blocked by exchange reconciliation."


def _limit_enabled(value: float | int | Decimal | None) -> bool:
    return value is not None and Decimal(str(value)) > 0


def _risk_settings(session: Session, user: AppUser) -> RiskManagementSettings:
    profile = session.get(UserProfile, user.id)
    settings = (profile.settings or {}).get("risk_management") if profile else None
    return RiskManagementSettings.model_validate(settings or {})


def _portfolio_equity(session: Session, user: AppUser) -> Decimal:
    portfolios = session.scalars(
        select(Portfolio)
        .options(joinedload(Portfolio.balances))
        .where(Portfolio.user_id == user.id, Portfolio.status == "active")
    ).unique().all()
    total = Decimal("0")
    for portfolio in portfolios:
        for balance in portfolio.balances:
            total += Decimal(balance.available or 0) + Decimal(balance.locked or 0)
    return total


def _get_pair(
    session: Session,
    exchange_code: str | None,
    symbol: str | None,
) -> MarketPair | None:
    if exchange_code is None or symbol is None:
        return None
    exchange = session.scalars(
        select(MarketExchange).where(MarketExchange.code == exchange_code.strip().lower())
    ).one_or_none()
    if exchange is None:
        return None
    return session.scalars(
        select(MarketPair)
        .options(
            joinedload(MarketPair.base_asset).joinedload(MarketAsset.risk_groups)
        )
        .where(
            MarketPair.exchange_id == exchange.id,
            MarketPair.symbol == symbol.strip().upper(),
        )
    ).unique().one_or_none()


def _get_rule(
    session: Session,
    exchange_code: str | None,
    symbol: str | None,
    *,
    category: str | None = None,
) -> ExchangeInstrumentRule | None:
    if exchange_code is None or symbol is None:
        return None
    exchange = session.scalars(
        select(MarketExchange).where(MarketExchange.code == exchange_code.strip().lower())
    ).one_or_none()
    if exchange is None:
        return None
    statement = select(ExchangeInstrumentRule).where(
        ExchangeInstrumentRule.exchange_id == exchange.id,
        ExchangeInstrumentRule.symbol == symbol.strip().upper(),
    )
    if category is not None:
        statement = statement.where(ExchangeInstrumentRule.category == category)
    return session.scalars(statement.order_by(ExchangeInstrumentRule.updated_at.desc()).limit(1)).one_or_none()


def _instrument_category(instrument_type: str | None) -> str | None:
    if instrument_type in {"spot", "virtual"}:
        return "spot"
    if instrument_type == "futures":
        return "linear"
    return None


def _rule_freshness(
    rule: ExchangeInstrumentRule | None,
    *,
    has_symbol: bool,
) -> tuple[str, float | None]:
    if not has_symbol:
        return "unknown", None
    if rule is None:
        return "missing", None
    fetched_at = rule.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (datetime.now(timezone.utc) - fetched_at).total_seconds())
    ttl_seconds = max(0, app_settings.exchange_instrument_rules_ttl_seconds)
    if ttl_seconds and age_seconds > ttl_seconds:
        return "stale", age_seconds
    return "fresh", age_seconds


def _instrument_rule_snapshot(rule: ExchangeInstrumentRule | None) -> dict[str, object] | None:
    if rule is None:
        return None
    return {
        "symbol": rule.symbol,
        "category": rule.category,
        "min_order_size": _float_or_none(rule.min_order_size),
        "max_order_size": _float_or_none(rule.max_order_size),
        "min_notional": _float_or_none(rule.min_notional),
        "qty_step": _float_or_none(rule.qty_step),
        "tick_size": _float_or_none(rule.tick_size),
        "max_leverage": rule.max_leverage,
        "funding_interval_minutes": rule.funding_interval_minutes,
        "source": rule.source,
        "fetched_at": rule.fetched_at,
        "updated_at": rule.updated_at,
        "raw_payload": rule.raw_payload,
    }


def _primary_group(pair: MarketPair) -> str | None:
    return _primary_group_from_asset(pair.base_asset)


def _primary_group_for_symbol(
    session: Session,
    *,
    pair: MarketPair | None,
    symbol: str | None,
) -> str | None:
    if pair is not None:
        return _primary_group(pair)
    base_symbol = _base_asset_symbol(symbol)
    if base_symbol is None:
        return None
    asset = session.scalars(
        select(MarketAsset)
        .options(joinedload(MarketAsset.risk_groups))
        .where(MarketAsset.symbol == base_symbol)
    ).unique().one_or_none()
    if asset is None:
        return None
    return _primary_group_from_asset(asset)


def _primary_group_from_asset(asset: MarketAsset) -> str | None:
    groups = [
        group
        for group in asset.risk_groups
        if group.is_primary
    ]
    if not groups:
        return None
    return groups[0].group_code


def _base_asset_symbol(symbol: str | None) -> str | None:
    if symbol is None:
        return None
    normalized = symbol.strip().upper()
    if not normalized:
        return None
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized[: -len(quote)]
    return normalized


def _open_risk(
    *,
    session: Session,
    user: AppUser,
    mode: str | None,
    correlation_group: str | None,
    side: str | None,
) -> tuple[Decimal, Decimal]:
    statement = (
        select(Position)
        .options(
            joinedload(Position.risk_snapshot),
            joinedload(Position.pair)
            .joinedload(MarketPair.base_asset)
            .joinedload(MarketAsset.risk_groups),
        )
        .where(Position.user_id == user.id, Position.status == "open")
    )
    if mode == "virtual":
        statement = statement.where(Position.mode == "virtual")
    elif mode == "real":
        statement = statement.where(Position.mode == "live")
    total = Decimal("0")
    correlated = Decimal("0")
    positions = session.scalars(statement).unique().all()
    for position in positions:
        amount = _position_risk_amount(position)
        total += amount
        group = _primary_group(position.pair)
        if correlation_group and group == correlation_group and (side is None or position.side == side):
            correlated += amount
    return total, correlated


def _position_risk_amount(position: Position) -> Decimal:
    if position.risk_snapshot is not None:
        return Decimal(position.risk_snapshot.risk_amount or 0)
    if position.stop_loss is None:
        return Decimal("0")
    return abs(Decimal(position.entry_avg_price) - Decimal(position.stop_loss)) * Decimal(position.quantity)


def _percent(amount: Decimal, equity: Decimal) -> float:
    return float(_percent_decimal(amount, equity))


def _percent_decimal(amount: Decimal, equity: Decimal) -> Decimal:
    if equity <= 0:
        return Decimal("0")
    return Decimal(amount) / Decimal(equity) * Decimal("100")


def _account_drawdown_percent(state: RiskProtectionState) -> float:
    if state.peak_equity <= 0:
        return 0.0
    drawdown = (state.peak_equity - state.current_equity) / state.peak_equity * Decimal("100")
    return float(max(drawdown, Decimal("0")))


def _float_or_none(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _dry_run_account_snapshot(
    *,
    user_id: str,
    request_account_balance: float | Decimal | None,
) -> AccountRiskSnapshot:
    balance = _positive_decimal(request_account_balance)
    if balance is None:
        return AccountRiskSnapshot(
            status="missing",
            fetched_at=None,
            account_equity=None,
            available_balance=None,
            margin_mode=None,
            positions=[],
            open_risk_amount=Decimal("0"),
            source="dry_run",
            warnings=["Dry-run account balance is missing; request/demo balance is required."],
        )
    source = "demo" if user_id in DEMO_USER_ALIASES else "dry_run"
    return AccountRiskSnapshot(
        status="fresh",
        fetched_at=datetime.now(timezone.utc),
        account_equity=balance,
        available_balance=balance,
        margin_mode=None,
        positions=[],
        open_risk_amount=Decimal("0"),
        source=source,
        warnings=[
            (
                "Dry-run real execution uses request/demo account_balance for sizing; "
                "live adapters require a fresh exchange account snapshot."
            )
        ],
    )


def _account_snapshot_from_reference(reference: object | None) -> AccountRiskSnapshot | None:
    if reference is None:
        return None
    snapshot = getattr(reference, "account_snapshot", None)
    if isinstance(snapshot, AccountRiskSnapshot):
        return snapshot
    status = _first_attr(
        reference,
        "real_account_snapshot_status",
        "account_snapshot_status",
        "real_balance_status",
    )
    equity = _positive_decimal(_first_attr(reference, "real_account_equity", "account_equity"))
    available = _positive_decimal(_first_attr(reference, "real_available_balance", "available_balance"))
    if status is None and equity is None and available is None:
        return None
    normalized_status = str(status or "missing").strip().lower()
    if normalized_status not in {"fresh", "stale", "missing"}:
        normalized_status = "missing"
    fetched_at = _datetime_attr(
        reference,
        "real_account_fetched_at",
        "account_snapshot_fetched_at",
        "fetched_at",
    )
    if normalized_status == "fresh" and fetched_at is None:
        fetched_at = datetime.now(timezone.utc)
    return AccountRiskSnapshot(
        status=normalized_status,
        fetched_at=fetched_at,
        account_equity=equity,
        available_balance=available,
        wallet_balance=_positive_decimal(
            _first_attr(reference, "real_wallet_balance", "wallet_balance")
        ),
        margin_mode=_str_attr(reference, "real_margin_mode", "margin_mode"),
        total_initial_margin=_non_negative_decimal(
            _first_attr(reference, "real_total_initial_margin", "total_initial_margin")
        ),
        total_maintenance_margin=_non_negative_decimal(
            _first_attr(reference, "real_total_maintenance_margin", "total_maintenance_margin")
        ),
        maintenance_margin_rate=_non_negative_decimal(
            _first_attr(reference, "real_maintenance_margin_rate", "maintenance_margin_rate")
        ),
        positions=_position_summaries(reference),
        open_risk_amount=_positive_decimal(
            _first_attr(reference, "real_open_risk_amount", "open_risk_amount")
        )
        or Decimal("0"),
        source="exchange",
        warnings=[],
    )


def _position_summaries(reference: object) -> list[PositionRiskSummary]:
    raw_positions = _first_attr(reference, "real_positions", "account_positions", "positions")
    if not isinstance(raw_positions, list):
        return []
    summaries: list[PositionRiskSummary] = []
    for position in raw_positions:
        if isinstance(position, PositionRiskSummary):
            summaries.append(position)
            continue
        if not isinstance(position, dict):
            continue
        summaries.append(PositionRiskSummary.model_validate(position))
    return summaries


def _positive_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _non_negative_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    return parsed if parsed >= 0 else None


def _datetime_attr(reference: object, *names: str) -> datetime | None:
    value = _first_attr(reference, *names)
    if isinstance(value, datetime):
        return value
    return None


def _str_attr(reference: object, *names: str) -> str | None:
    value = _first_attr(reference, *names)
    if value is None:
        return None
    return str(value)


def _first_attr(reference: object, *names: str) -> object | None:
    for name in names:
        if hasattr(reference, name):
            return getattr(reference, name)
    return None


def _default_account_snapshot_provider() -> Any | None:
    from app.services.exchange_account_snapshot import exchange_account_snapshot_service

    return exchange_account_snapshot_service


risk_state_service = RiskStateService()
