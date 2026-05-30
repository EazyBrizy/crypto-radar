from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.models.market import MarketExchange, MarketPair
from app.models.strategy import StrategyTemplate, StrategyVersion, UserStrategyConfig
from app.models.user import AppUser
from app.schemas.candle import DEFAULT_TIMEFRAMES
from app.schemas.strategy import StrategyConfigResponse, StrategyConfigUpdateRequest, StrategyPairScope
from app.services.bootstrap_service import DEMO_USERNAME

RUNTIME_CONFIG_CACHE_TTL_SEC = 10.0

DEFAULT_STRATEGY_QUALITY_PARAMS: dict[str, Any] = {
    "min_24h_volume_quote": 10_000_000.0,
    "max_spread_bps": 25.0,
    "allow_low_liquidity": False,
    "quality_tiers": {
        "major": {"min_24h_volume_quote": 25_000_000.0, "max_spread_bps": 15.0},
        "mid_alt": {"min_24h_volume_quote": 10_000_000.0, "max_spread_bps": 25.0},
        "low_liquidity": {"min_24h_volume_quote": 5_000_000.0, "max_spread_bps": 35.0},
    },
}


@dataclass(frozen=True)
class StrategyRuntimeConfig:
    strategy_code: str
    exchanges: tuple[str, ...]
    pairs: tuple[tuple[str, str], ...]
    timeframes: tuple[str, ...]
    params: dict[str, Any]
    risk_settings: dict[str, Any] = field(default_factory=dict)
    is_enabled: bool = True
    pair_scope_configured: bool = False

    def matches(self, *, exchange: str, symbol: str, timeframe: str) -> bool:
        normalized_exchange = exchange.strip().lower()
        normalized_symbol = symbol.strip().upper()
        if not self.is_enabled:
            return False
        if self.exchanges and normalized_exchange not in self.exchanges:
            return False
        if self.timeframes and timeframe not in self.timeframes:
            return False
        if self.pairs and (normalized_exchange, normalized_symbol) not in self.pairs:
            return False
        return True


class StrategyConfigService:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._runtime_cache: tuple[float, list[StrategyRuntimeConfig]] | None = None

    def list_configs(self, user_id: str = "demo_user") -> list[StrategyConfigResponse]:
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
            _ensure_default_configs(session, user)
            records = session.scalars(
                _config_select()
                .where(UserStrategyConfig.user_id == user.id)
                .order_by(StrategyTemplate.name.asc())
            ).unique().all()
            return [_config_to_response(record) for record in records]

    def update_config(self, config_id: str, request: StrategyConfigUpdateRequest) -> StrategyConfigResponse:
        with self._session_factory() as session:
            user = _resolve_user(session, request.user_id)
            config = _get_config(session, config_id)
            if config.user_id != user.id:
                raise ValueError("Strategy config does not belong to this user")

            if request.name is not None:
                config.name = request.name.strip()
            if request.exchanges is not None:
                config.exchange_scope = _normalize_exchanges(request.exchanges)
            if request.pairs is not None:
                config.pair_scope = _normalize_pairs(request.pairs)
            if request.timeframes is not None:
                config.timeframes = list(dict.fromkeys(request.timeframes))
            if request.params is not None:
                config.params = _merge_params(config.params, request.params)
            if request.risk_settings is not None:
                config.risk_settings = _merge_params(config.risk_settings, request.risk_settings)
            if request.is_enabled is not None:
                config.is_enabled = request.is_enabled
            config.updated_at = datetime.now(timezone.utc)
            session.commit()
            self.invalidate_cache()
            return self.get_config(config_id, user_id=request.user_id)

    def get_config(self, config_id: str, user_id: str = "demo_user") -> StrategyConfigResponse:
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
            config = _get_config(session, config_id)
            if config.user_id != user.id:
                raise ValueError("Strategy config does not belong to this user")
            return _config_to_response(config)

    def runtime_configs(self, user_id: str = "demo_user") -> list[StrategyRuntimeConfig]:
        cached = self._runtime_cache
        now = time.monotonic()
        if cached is not None and now - cached[0] <= RUNTIME_CONFIG_CACHE_TTL_SEC:
            return cached[1]
        default_risk_settings = _default_strategy_risk_settings(user_id)
        configs = [
            _response_to_runtime(config, default_risk_settings=default_risk_settings)
            for config in self.list_configs(user_id=user_id)
            if config.is_enabled
        ]
        self._runtime_cache = (now, configs)
        return configs

    def configs_for(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        user_id: str = "demo_user",
    ) -> dict[str, StrategyRuntimeConfig]:
        return {
            config.strategy_code: config
            for config in self.runtime_configs(user_id=user_id)
            if config.matches(exchange=exchange, symbol=symbol, timeframe=timeframe)
        }

    def invalidate_cache(self) -> None:
        self._runtime_cache = None


def _config_select():
    return (
        select(UserStrategyConfig)
        .join(UserStrategyConfig.strategy_version)
        .join(StrategyVersion.strategy)
        .options(joinedload(UserStrategyConfig.strategy_version).joinedload(StrategyVersion.strategy))
    )


def _resolve_user(session: Session, user_id: str) -> AppUser:
    user = session.scalars(
        select(AppUser).where((AppUser.username == user_id) | (AppUser.email == user_id))
    ).first()
    if user is not None:
        return user
    user = session.scalars(select(AppUser).where(AppUser.username == DEMO_USERNAME)).first()
    if user is None:
        raise ValueError("User is not found")
    return user


def _ensure_default_configs(session: Session, user: AppUser) -> None:
    versions = session.scalars(
        select(StrategyVersion)
        .join(StrategyVersion.strategy)
        .options(joinedload(StrategyVersion.strategy))
        .where(StrategyVersion.status == "active", StrategyTemplate.is_active.is_(True))
        .order_by(StrategyTemplate.name.asc())
    ).unique().all()
    existing_version_ids = {
        config.strategy_version_id
        for config in session.scalars(
            select(UserStrategyConfig).where(UserStrategyConfig.user_id == user.id)
        ).all()
    }
    changed = False
    for version in versions:
        if version.id in existing_version_ids:
            continue
        params = dict(version.default_params or {})
        params.update(DEFAULT_STRATEGY_QUALITY_PARAMS)
        risk_settings = {
            "rr_target": "final",
            "hide_failed_rr_signals": False,
        }
        session.add(
            UserStrategyConfig(
                user_id=user.id,
                strategy_version_id=version.id,
                name=version.strategy.name,
                exchange_scope=["bybit"],
                pair_scope=[],
                timeframes=list(DEFAULT_TIMEFRAMES),
                params=params,
                risk_settings=risk_settings,
                is_enabled=True,
            )
        )
        changed = True
    if changed:
        session.commit()


def _get_config(session: Session, config_id: str) -> UserStrategyConfig:
    try:
        config_uuid = UUID(config_id)
    except ValueError as exc:
        raise ValueError("Invalid strategy config id") from exc
    config = session.scalars(_config_select().where(UserStrategyConfig.id == config_uuid)).unique().first()
    if config is None:
        raise ValueError("Strategy config is not found")
    return config


def _config_to_response(config: UserStrategyConfig) -> StrategyConfigResponse:
    version = config.strategy_version
    return StrategyConfigResponse(
        id=config.id,
        user_id=config.user_id,
        strategy_version_id=config.strategy_version_id,
        strategy_code=version.strategy.code,
        strategy_name=version.strategy.name,
        strategy_version=version.version,
        name=config.name,
        exchanges=_normalize_exchanges(config.exchange_scope),
        pairs=[StrategyPairScope(exchange=exchange, symbol=symbol) for exchange, symbol in _pairs_from_scope(config.pair_scope)],
        timeframes=config.timeframes,
        params=config.params or {},
        risk_settings=config.risk_settings or {},
        is_enabled=config.is_enabled,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _response_to_runtime(
    config: StrategyConfigResponse,
    *,
    default_risk_settings: dict[str, Any] | None = None,
) -> StrategyRuntimeConfig:
    risk_settings = dict(default_risk_settings or {})
    risk_settings.update(config.risk_settings)
    return StrategyRuntimeConfig(
        strategy_code=config.strategy_code,
        exchanges=tuple(exchange.strip().lower() for exchange in config.exchanges if exchange.strip()),
        pairs=tuple((pair.exchange.strip().lower(), pair.symbol.strip().upper()) for pair in config.pairs),
        timeframes=tuple(config.timeframes),
        params=dict(config.params),
        risk_settings=risk_settings,
        is_enabled=config.is_enabled,
        pair_scope_configured=bool(config.pairs),
    )


def _default_strategy_risk_settings(user_id: str) -> dict[str, Any]:
    try:
        from app.services.risk_management import get_user_risk_management_settings

        settings = get_user_risk_management_settings(user_id)
        min_rr_ratio = settings.min_rr_ratio
    except Exception:
        min_rr_ratio = 2.0
    return {
        "min_rr_ratio": min_rr_ratio,
        "rr_target": "final",
        "hide_failed_rr_signals": False,
    }


def _normalize_exchanges(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        if isinstance(value, str):
            exchange = value.strip().lower()
        elif isinstance(value, dict):
            exchange = str(value.get("exchange") or value.get("code") or "").strip().lower()
        else:
            continue
        if exchange:
            normalized.append(exchange)
    return list(dict.fromkeys(normalized))


def _normalize_pairs(values: list[StrategyPairScope]) -> list[dict[str, str]]:
    pairs = [
        (pair.exchange.strip().lower(), pair.symbol.strip().upper())
        for pair in values
        if pair.exchange.strip() and pair.symbol.strip()
    ]
    return [{"exchange": exchange, "symbol": symbol} for exchange, symbol in dict.fromkeys(pairs)]


def _pairs_from_scope(values: Any) -> list[tuple[str, str]]:
    if not isinstance(values, list):
        return []
    pairs: list[tuple[str, str]] = []
    for value in values:
        if isinstance(value, str):
            exchange, symbol = _pair_from_string(value)
        elif isinstance(value, dict):
            exchange = str(value.get("exchange") or "bybit").strip().lower()
            symbol = str(value.get("symbol") or "").strip().upper()
        else:
            continue
        if exchange and symbol:
            pairs.append((exchange, symbol))
    return list(dict.fromkeys(pairs))


def _pair_from_string(value: str) -> tuple[str, str]:
    normalized = value.strip()
    if ":" in normalized:
        exchange, symbol = normalized.split(":", 1)
        return exchange.strip().lower(), symbol.strip().upper()
    return "bybit", normalized.upper()


def _merge_params(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


strategy_config_service = StrategyConfigService()
