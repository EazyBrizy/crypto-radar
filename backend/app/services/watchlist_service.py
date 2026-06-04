from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.models.market import MarketExchange, MarketPair
from app.models.strategy import StrategyVersion
from app.models.user import AppUser
from app.models.watchlist import UserAlertRule, UserWatchlist, UserWatchlistPair
from app.schemas.watchlist import (
    AlertRuleCreateRequest,
    AlertRuleResponse,
    AlertRuleTestResponse,
    AlertRuleUpdateRequest,
    MarketPairOption,
    WatchlistCreateRequest,
    WatchlistPairCreateRequest,
    WatchlistPairResponse,
    WatchlistResponse,
    WatchlistUpdateRequest,
)
from app.services.bootstrap_service import DEFAULT_WATCHLIST_NAME
from app.services.user_identity import resolve_app_user


class WatchlistService:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def list_available_pairs(self) -> list[MarketPairOption]:
        with self._session_factory() as session:
            pairs = session.scalars(_pair_select().order_by(MarketExchange.code, MarketPair.symbol)).all()
            return [_pair_to_option(pair) for pair in pairs]

    def list_watchlists(self, user_id: str = "demo_user") -> list[WatchlistResponse]:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            records = session.scalars(
                _watchlist_select()
                .where(UserWatchlist.user_id == user.id)
                .order_by(UserWatchlist.is_default.desc(), UserWatchlist.created_at.asc())
            ).unique().all()
            return [_watchlist_to_response(record) for record in records]

    def get_default_watchlist(self, user_id: str = "demo_user") -> WatchlistResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            watchlist = _get_default_watchlist(session, user)
            return _watchlist_to_response(watchlist)

    def create_watchlist(self, request: WatchlistCreateRequest) -> WatchlistResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, request.user_id)
            if request.is_default:
                _clear_default_watchlists(session, user.id)
            watchlist = UserWatchlist(
                user_id=user.id,
                name=request.name.strip(),
                is_default=request.is_default,
            )
            session.add(watchlist)
            session.commit()
            return self.get_watchlist(str(watchlist.id))

    def get_watchlist(self, watchlist_id: str) -> WatchlistResponse:
        with self._session_factory() as session:
            watchlist = _get_watchlist(session, watchlist_id)
            return _watchlist_to_response(watchlist)

    def update_watchlist(
        self,
        watchlist_id: str,
        request: WatchlistUpdateRequest,
    ) -> WatchlistResponse:
        with self._session_factory() as session:
            watchlist = _get_watchlist(session, watchlist_id)
            if request.name is not None:
                watchlist.name = request.name.strip()
            if request.is_default is not None:
                if request.is_default:
                    _clear_default_watchlists(session, watchlist.user_id)
                watchlist.is_default = request.is_default
            session.commit()
            return self.get_watchlist(watchlist_id)

    def delete_watchlist(self, watchlist_id: str) -> None:
        with self._session_factory() as session:
            watchlist = _get_watchlist(session, watchlist_id)
            session.delete(watchlist)
            session.commit()

    def add_pair_to_default(self, request: WatchlistPairCreateRequest) -> WatchlistResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, request.user_id)
            watchlist = _get_default_watchlist(session, user)
            pair = _resolve_pair(session, request)
            _ensure_watchlist_pair(session, watchlist, pair)
            session.commit()
            return self.get_watchlist(str(watchlist.id))

    def remove_pair_from_default(self, pair_id: str, user_id: str = "demo_user") -> WatchlistResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            watchlist = _get_default_watchlist(session, user)
            _delete_watchlist_pair(session, watchlist.id, pair_id)
            session.commit()
            return self.get_watchlist(str(watchlist.id))

    def add_pair(
        self,
        watchlist_id: str,
        request: WatchlistPairCreateRequest,
    ) -> WatchlistResponse:
        with self._session_factory() as session:
            watchlist = _get_watchlist(session, watchlist_id)
            pair = _resolve_pair(session, request)
            _ensure_watchlist_pair(session, watchlist, pair)
            session.commit()
            return self.get_watchlist(watchlist_id)

    def remove_pair(self, watchlist_id: str, pair_id: str) -> WatchlistResponse:
        with self._session_factory() as session:
            watchlist = _get_watchlist(session, watchlist_id)
            _delete_watchlist_pair(session, watchlist.id, pair_id)
            session.commit()
            return self.get_watchlist(watchlist_id)

    def list_alert_rules(self, user_id: str = "demo_user") -> list[AlertRuleResponse]:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            records = session.scalars(
                _alert_select()
                .where(UserAlertRule.user_id == user.id)
                .order_by(UserAlertRule.created_at.desc())
            ).all()
            return [_alert_to_response(record) for record in records]

    def create_alert_rule(self, request: AlertRuleCreateRequest) -> AlertRuleResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, request.user_id)
            if request.pair_id is not None:
                _get_pair(session, str(request.pair_id))
            if request.strategy_version_id is not None:
                _get_strategy_version(session, request.strategy_version_id)
            alert = UserAlertRule(
                user_id=user.id,
                pair_id=request.pair_id,
                strategy_version_id=request.strategy_version_id,
                condition_type=request.condition_type.strip(),
                condition_body=request.condition_body,
                channels=request.channels,
                is_enabled=request.is_enabled,
            )
            session.add(alert)
            session.commit()
            return self.get_alert_rule(str(alert.id))

    def get_alert_rule(self, alert_id: str) -> AlertRuleResponse:
        with self._session_factory() as session:
            alert = _get_alert_rule(session, alert_id)
            return _alert_to_response(alert)

    def update_alert_rule(
        self,
        alert_id: str,
        request: AlertRuleUpdateRequest,
    ) -> AlertRuleResponse:
        with self._session_factory() as session:
            alert = _get_alert_rule(session, alert_id)
            if request.pair_id is not None:
                _get_pair(session, str(request.pair_id))
                alert.pair_id = request.pair_id
            if request.strategy_version_id is not None:
                _get_strategy_version(session, request.strategy_version_id)
                alert.strategy_version_id = request.strategy_version_id
            if request.condition_type is not None:
                alert.condition_type = request.condition_type.strip()
            if request.condition_body is not None:
                alert.condition_body = request.condition_body
            if request.channels is not None:
                alert.channels = request.channels
            if request.is_enabled is not None:
                alert.is_enabled = request.is_enabled
            session.commit()
            return self.get_alert_rule(alert_id)

    def delete_alert_rule(self, alert_id: str) -> None:
        with self._session_factory() as session:
            alert = _get_alert_rule(session, alert_id)
            session.delete(alert)
            session.commit()

    def test_alert_rule(self, alert_id: str) -> AlertRuleTestResponse:
        alert = self.get_alert_rule(alert_id)
        event = {
            "type": "alert.rule_test",
            "alert_rule_id": str(alert.id),
            "pair": alert.pair.model_dump(mode="json") if alert.pair is not None else None,
            "condition_type": alert.condition_type,
            "condition_body": alert.condition_body,
            "channels": alert.channels,
            "stubbed": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return AlertRuleTestResponse(alert_rule=alert, event=event)


def _watchlist_select():
    return select(UserWatchlist).options(
        joinedload(UserWatchlist.pair_entries)
        .joinedload(UserWatchlistPair.pair)
        .joinedload(MarketPair.exchange),
        joinedload(UserWatchlist.pair_entries)
        .joinedload(UserWatchlistPair.pair)
        .joinedload(MarketPair.base_asset),
        joinedload(UserWatchlist.pair_entries)
        .joinedload(UserWatchlistPair.pair)
        .joinedload(MarketPair.quote_asset),
    )


def _pair_select():
    return (
        select(MarketPair)
        .join(MarketPair.exchange)
        .options(
            joinedload(MarketPair.exchange),
            joinedload(MarketPair.base_asset),
            joinedload(MarketPair.quote_asset),
        )
    )


def _alert_select():
    return select(UserAlertRule).options(
        joinedload(UserAlertRule.pair).joinedload(MarketPair.exchange),
        joinedload(UserAlertRule.pair).joinedload(MarketPair.base_asset),
        joinedload(UserAlertRule.pair).joinedload(MarketPair.quote_asset),
    )


def _get_default_watchlist(session: Session, user: AppUser) -> UserWatchlist:
    watchlist = session.scalars(
        _watchlist_select()
        .where(UserWatchlist.user_id == user.id, UserWatchlist.is_default.is_(True))
        .limit(1)
    ).unique().one_or_none()
    if watchlist is not None:
        return watchlist

    watchlist = UserWatchlist(
        user_id=user.id,
        name=DEFAULT_WATCHLIST_NAME,
        is_default=True,
    )
    session.add(watchlist)
    session.flush()
    return watchlist


def _get_watchlist(session: Session, watchlist_id: str) -> UserWatchlist:
    watchlist_uuid = _parse_uuid(watchlist_id)
    if watchlist_uuid is None:
        raise ValueError("Invalid watchlist id")
    watchlist = session.scalars(
        _watchlist_select().where(UserWatchlist.id == watchlist_uuid)
    ).unique().one_or_none()
    if watchlist is None:
        raise LookupError("Watchlist is not found")
    return watchlist


def _get_pair(session: Session, pair_id: str) -> MarketPair:
    pair_uuid = _parse_uuid(pair_id)
    if pair_uuid is None:
        raise ValueError("Invalid pair id")
    pair = session.scalars(_pair_select().where(MarketPair.id == pair_uuid)).one_or_none()
    if pair is None:
        raise LookupError("Market pair is not found")
    return pair


def _resolve_pair(session: Session, request: WatchlistPairCreateRequest) -> MarketPair:
    if request.pair_id is not None:
        return _get_pair(session, str(request.pair_id))
    if not request.exchange or not request.symbol:
        raise ValueError("pair_id or exchange+symbol is required")
    pair = session.scalars(
        _pair_select().where(
            MarketExchange.code == request.exchange.lower(),
            MarketPair.symbol == request.symbol.upper(),
        )
    ).one_or_none()
    if pair is None:
        raise LookupError("Market pair is not found")
    return pair


def _get_strategy_version(session: Session, version_id: UUID) -> StrategyVersion:
    version = session.get(StrategyVersion, version_id)
    if version is None:
        raise LookupError("Strategy version is not found")
    return version


def _get_alert_rule(session: Session, alert_id: str) -> UserAlertRule:
    alert_uuid = _parse_uuid(alert_id)
    if alert_uuid is None:
        raise ValueError("Invalid alert rule id")
    alert = session.scalars(_alert_select().where(UserAlertRule.id == alert_uuid)).one_or_none()
    if alert is None:
        raise LookupError("Alert rule is not found")
    return alert


def _ensure_watchlist_pair(
    session: Session,
    watchlist: UserWatchlist,
    pair: MarketPair,
) -> None:
    existing = session.get(UserWatchlistPair, {"watchlist_id": watchlist.id, "pair_id": pair.id})
    if existing is None:
        session.add(UserWatchlistPair(watchlist_id=watchlist.id, pair_id=pair.id))


def _delete_watchlist_pair(session: Session, watchlist_id: UUID, pair_id: str) -> None:
    pair_uuid = _parse_uuid(pair_id)
    if pair_uuid is None:
        raise ValueError("Invalid pair id")
    entry = session.get(UserWatchlistPair, {"watchlist_id": watchlist_id, "pair_id": pair_uuid})
    if entry is not None:
        session.delete(entry)


def _clear_default_watchlists(session: Session, user_id: UUID) -> None:
    for watchlist in session.scalars(
        select(UserWatchlist).where(UserWatchlist.user_id == user_id, UserWatchlist.is_default.is_(True))
    ):
        watchlist.is_default = False


def _watchlist_to_response(watchlist: UserWatchlist) -> WatchlistResponse:
    entries = sorted(watchlist.pair_entries, key=lambda entry: (entry.pair.exchange.code, entry.pair.symbol))
    return WatchlistResponse(
        id=watchlist.id,
        user_id=watchlist.user_id,
        name=watchlist.name,
        is_default=watchlist.is_default,
        pairs=[
            WatchlistPairResponse(
                **_pair_to_option(entry.pair).model_dump(),
                added_at=entry.created_at,
            )
            for entry in entries
        ],
        created_at=watchlist.created_at,
    )


def _pair_to_option(pair: MarketPair) -> MarketPairOption:
    return MarketPairOption(
        id=pair.id,
        exchange=pair.exchange.code,
        symbol=pair.symbol,
        base_asset=pair.base_asset.symbol,
        quote_asset=pair.quote_asset.symbol,
        status=pair.status,
    )


def _alert_to_response(alert: UserAlertRule) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=alert.id,
        user_id=alert.user_id,
        pair=_pair_to_option(alert.pair) if alert.pair is not None else None,
        strategy_version_id=alert.strategy_version_id,
        condition_type=alert.condition_type,
        condition_body=alert.condition_body,
        channels=list(alert.channels or []),
        is_enabled=alert.is_enabled,
        created_at=alert.created_at,
    )


def _parse_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None


watchlist_service = WatchlistService()
