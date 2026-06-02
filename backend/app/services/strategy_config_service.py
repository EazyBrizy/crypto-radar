from __future__ import annotations

import time
import hashlib
import json
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
from app.schemas.user import RiskManagementSettings
from app.services.bootstrap_service import DEMO_USERNAME
from app.services.risk_management import resolve_rr_guard_mode

RUNTIME_CONFIG_CACHE_TTL_SEC = 10.0
RR_TARGET_DEFAULT_VERSION = "strategy-rr-target-v1"
RR_TARGET_BY_STRATEGY: dict[str, str] = {
    "trend_pullback_continuation": "final",
    "volatility_squeeze_breakout": "final",
    "liquidity_sweep_reversal": "nearest",
}

DEFAULT_STRATEGY_QUALITY_PARAMS: dict[str, Any] = {
    "min_24h_volume_quote": 10_000_000.0,
    "max_spread_bps": 25.0,
    "context_timeframe_map": {
        "1m": "15m",
        "5m": "1h",
        "15m": "1h",
        "1h": "4h",
        "4h": "1d",
    },
    "context_obstacle_min_atr": 1.0,
    "context_level_min_strength": 25.0,
    "allow_low_liquidity": False,
    "quality_tiers": {
        "major": {"min_24h_volume_quote": 25_000_000.0, "max_spread_bps": 15.0},
        "mid_alt": {"min_24h_volume_quote": 10_000_000.0, "max_spread_bps": 25.0},
        "low_liquidity": {"min_24h_volume_quote": 5_000_000.0, "max_spread_bps": 35.0},
    },
}

DEFAULT_NO_TRADE_RISK_SETTINGS: dict[str, Any] = {
    "no_trade_filters_enabled": True,
    "max_spread_bps_for_entry": 50.0,
    "max_slippage_bps_for_entry": 150.0,
    "min_depth_usd_for_entry": 0.0,
    "max_obstacle_distance_r": 1.0,
    "cooldown_after_stop_minutes": 0,
    "max_strategy_losses_per_day": 0,
}

DEFAULT_RR_GUARD_RISK_SETTINGS: dict[str, Any] = {
    "rr_guard_mode": "soft",
    "discovery_rr_guard_mode": "soft",
    "virtual_rr_guard_mode": "soft",
    "backtest_rr_guard_mode": "soft",
    "real_rr_guard_mode": "hard",
}

DEFAULT_STRATEGY_PARAMS_BY_CODE: dict[str, dict[str, Any]] = {
    "trend_pullback_continuation": {
        "entry_model": "zone",
        "max_overextension_atr": 1.5,
        "require_htf_alignment": True,
        "time_stop_bars": 8,
        "funding_warning_threshold": 0.00075,
        "funding_block_threshold": 0.0015,
        "crowded_oi_change_threshold": 0.02,
        "crowded_oi_penalty": 15,
    },
    "volatility_squeeze_breakout": {
        "bb_width_percentile_threshold": 20.0,
        "volume_spike_multiplier": 1.5,
        "min_close_position": 0.7,
        "max_breakout_wick_ratio": 0.35,
        "max_squeeze_range_atr": 5.0,
        "watchlist_distance_atr": 0.6,
        "breakout_stop_atr": 1.0,
        "narrow_range_stop_atr": 0.5,
        "allow_aggressive_entry": True,
        "require_retest_after_large_candle": True,
        "large_candle_body_atr": 2.5,
        "measured_move_target_enabled": True,
        "oi_expansion_threshold": 0.01,
        "oi_expansion_bonus": 5,
        "oi_no_expansion_penalty": 10,
        "require_delta_expansion": False,
        "require_oi_expansion": False,
        "min_delta_expansion_score": 0.45,
        "min_oi_expansion_score": 0.45,
        "accepted_breakout_min_score": 0.55,
        "fakeout_risk_max_score": 0.55,
    },
    "liquidity_sweep_reversal": {
        "min_sweep_wick_ratio": 0.45,
        "sweep_volume_spike_multiplier": 1.3,
        "confirmation_volume_spike": 1.1,
        "watchlist_distance_atr": 0.6,
        "sweep_stop_atr": 0.3,
        "sweep_aggressive_close_position": 0.6,
        "min_level_retests": 2,
        "sweep_level_confluence_atr": 0.5,
        "require_reclaim": True,
        "require_absorption": False,
        "min_absorption_score": 0.35,
        "min_cvd_divergence_score": 0.0,
        "min_oi_flush_score": 0.0,
        "min_obvious_liquidity_score": 0.45,
        "min_target_distance_r": 0.0,
        "alpha_context_required": False,
        "require_oi_flush": False,
        "max_obstacle_distance_r": 1.0,
        "oi_flush_threshold": -0.01,
        "oi_flush_bonus": 8,
        "liquidation_flush_bonus": 6,
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
        if self.timeframes and timeframe not in self.timeframes:
            return False
        if self.pairs:
            if (normalized_exchange, normalized_symbol) not in self.pairs:
                return False
            return True
        if self.exchanges and normalized_exchange not in self.exchanges:
            return False
        return True


class StrategyConfigValidationError(ValueError):
    pass


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
                config.exchange_scope = _validate_exchanges(session, request.exchanges)
            if request.pairs is not None:
                config.pair_scope = _validate_pairs(session, request.pairs)
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
            _response_to_runtime(
                config,
                default_risk_settings=_risk_settings_for_strategy(
                    config.strategy_code,
                    default_risk_settings,
                ),
            )
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

    def config_hash(self, user_id: str = "demo_user") -> str:
        payload = [
            {
                "strategy_code": config.strategy_code,
                "exchanges": config.exchanges,
                "pairs": [pair.model_dump(mode="json") for pair in config.pairs],
                "timeframes": config.timeframes,
                "params": config.params,
                "risk_settings": config.risk_settings,
                "is_enabled": config.is_enabled,
            }
            for config in self.list_configs(user_id=user_id)
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

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
        params.update(_default_overextension_params(version.strategy.code))
        params.update(DEFAULT_STRATEGY_PARAMS_BY_CODE.get(version.strategy.code, {}))
        risk_settings = _persisted_risk_settings_for_strategy(version.strategy.code)
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
    changed = _normalize_existing_strategy_defaults(
        session.scalars(
            _config_select().where(UserStrategyConfig.user_id == user.id)
        ).unique().all()
    ) or changed
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
        values = settings.model_dump()
    except Exception:
        values = RiskManagementSettings().model_dump()
    return {
        "min_rr_ratio": values["min_rr_ratio"],
        "rr_guard_mode": resolve_rr_guard_mode(values, context="discovery"),
        "discovery_rr_guard_mode": values["discovery_rr_guard_mode"],
        "virtual_rr_guard_mode": values["virtual_rr_guard_mode"],
        "backtest_rr_guard_mode": values["backtest_rr_guard_mode"],
        "real_rr_guard_mode": values["real_rr_guard_mode"],
        "strategy_rr_guard_modes": dict(values.get("strategy_rr_guard_modes") or {}),
        "hide_failed_rr_signals": False,
        "show_only_active_setups": False,
        **DEFAULT_NO_TRADE_RISK_SETTINGS,
    }


def _risk_settings_for_strategy(strategy_code: str, base_settings: dict[str, Any]) -> dict[str, Any]:
    settings = dict(base_settings)
    settings["rr_guard_mode"] = resolve_rr_guard_mode(
        base_settings,
        context="discovery",
        strategy=strategy_code,
    )
    settings.setdefault("hide_failed_rr_signals", False)
    settings.setdefault("show_only_active_setups", False)
    for key, value in DEFAULT_RR_GUARD_RISK_SETTINGS.items():
        settings.setdefault(key, value)
    for key, value in DEFAULT_NO_TRADE_RISK_SETTINGS.items():
        settings.setdefault(key, value)
    settings["rr_target"] = _default_rr_target_for_strategy(strategy_code)
    settings["rr_target_default_version"] = RR_TARGET_DEFAULT_VERSION
    return settings


def _persisted_risk_settings_for_strategy(strategy_code: str) -> dict[str, Any]:
    return {
        "rr_target": _default_rr_target_for_strategy(strategy_code),
        "rr_target_default_version": RR_TARGET_DEFAULT_VERSION,
        **DEFAULT_RR_GUARD_RISK_SETTINGS,
        "hide_failed_rr_signals": False,
        "show_only_active_setups": False,
        **DEFAULT_NO_TRADE_RISK_SETTINGS,
    }


def _default_rr_target_for_strategy(strategy_code: str) -> str:
    return RR_TARGET_BY_STRATEGY.get(strategy_code, "final")


def _normalize_existing_strategy_defaults(configs: list[UserStrategyConfig]) -> bool:
    changed = False
    now = datetime.now(timezone.utc)
    for config in configs:
        strategy_code = config.strategy_version.strategy.code
        risk_settings = dict(config.risk_settings or {})
        params = dict(getattr(config, "params", {}) or {})
        config_changed = False
        params_changed = False
        for key, value in DEFAULT_STRATEGY_PARAMS_BY_CODE.get(strategy_code, {}).items():
            if key not in params:
                params[key] = value
                params_changed = True
        if "hide_failed_rr_signals" not in risk_settings:
            risk_settings["hide_failed_rr_signals"] = False
            config_changed = True
        if "show_only_active_setups" not in risk_settings:
            risk_settings["show_only_active_setups"] = False
            config_changed = True
        for key, value in DEFAULT_RR_GUARD_RISK_SETTINGS.items():
            if key not in risk_settings:
                risk_settings[key] = value
                config_changed = True
        for key, value in DEFAULT_NO_TRADE_RISK_SETTINGS.items():
            if key not in risk_settings:
                risk_settings[key] = value
                config_changed = True
        if "rr_target" not in risk_settings:
            risk_settings["rr_target"] = _default_rr_target_for_strategy(strategy_code)
            config_changed = True
        elif _is_legacy_default_rr_target(strategy_code, risk_settings):
            risk_settings["rr_target"] = _default_rr_target_for_strategy(strategy_code)
            config_changed = True
        if risk_settings.get("rr_target_default_version") != RR_TARGET_DEFAULT_VERSION:
            risk_settings["rr_target_default_version"] = RR_TARGET_DEFAULT_VERSION
            config_changed = True
        if config_changed:
            config.risk_settings = risk_settings
            config.updated_at = now
            changed = True
        if params_changed:
            config.params = params
            config.updated_at = now
            changed = True
    return changed


def _is_legacy_default_rr_target(strategy_code: str, risk_settings: dict[str, Any]) -> bool:
    if _default_rr_target_for_strategy(strategy_code) == "final":
        return False
    if risk_settings.get("rr_target_default_version"):
        return False
    if str(risk_settings.get("rr_target") or "").lower() != "final":
        return False
    allowed_legacy_keys = {
        "rr_target",
        "hide_failed_rr_signals",
        "show_only_active_setups",
        *DEFAULT_RR_GUARD_RISK_SETTINGS,
        *DEFAULT_NO_TRADE_RISK_SETTINGS,
    }
    return set(risk_settings).issubset(allowed_legacy_keys) and not bool(risk_settings.get("hide_failed_rr_signals"))


def _default_overextension_params(strategy_code: str) -> dict[str, float]:
    body_defaults = {
        "trend_pullback_continuation": 2.0,
        "volatility_squeeze_breakout": 2.5,
        "liquidity_sweep_reversal": 2.0,
    }
    range_defaults = {
        "trend_pullback_continuation": 3.0,
        "volatility_squeeze_breakout": 3.5,
        "liquidity_sweep_reversal": 3.8,
    }
    return {
        "max_body_atr": body_defaults.get(strategy_code, 2.5),
        "max_range_atr": range_defaults.get(strategy_code, 3.5),
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


def _normalize_pairs(values: list[StrategyPairScope]) -> list[tuple[str, str]]:
    pairs = [
        (pair.exchange.strip().lower(), pair.symbol.strip().upper())
        for pair in values
        if pair.exchange.strip() and pair.symbol.strip()
    ]
    return list(dict.fromkeys(pairs))


def _validate_exchanges(session: Session, values: list[str]) -> list[str]:
    exchanges = _normalize_exchanges(values)
    records = {
        exchange.code.lower(): exchange
        for exchange in session.scalars(
            select(MarketExchange).where(MarketExchange.code.in_(exchanges))
        ).all()
    }
    errors: list[str] = []
    for exchange in exchanges:
        record = records.get(exchange)
        if record is None:
            errors.append(f"Exchange '{exchange}' is not present in market_exchanges")
        elif record.status != "active":
            errors.append(f"Exchange '{exchange}' is disabled")
    if errors:
        raise StrategyConfigValidationError("; ".join(errors))
    return exchanges


def _validate_pairs(session: Session, values: list[StrategyPairScope]) -> list[dict[str, str]]:
    pairs = _normalize_pairs(values)
    if not pairs:
        return []

    exchanges = list(dict.fromkeys(exchange for exchange, _ in pairs))
    symbols = list(dict.fromkeys(symbol for _, symbol in pairs))
    records = {
        (pair.exchange.code.lower(), pair.symbol.upper()): pair
        for pair in session.scalars(
            select(MarketPair)
            .join(MarketPair.exchange)
            .options(joinedload(MarketPair.exchange))
            .where(MarketExchange.code.in_(exchanges), MarketPair.symbol.in_(symbols))
        ).unique().all()
    }

    errors: list[str] = []
    for exchange, symbol in pairs:
        pair = records.get((exchange, symbol))
        if pair is None:
            errors.append(f"Market pair '{exchange}:{symbol}' is not found in market_pairs")
            continue
        if pair.exchange.status != "active":
            errors.append(f"Exchange '{exchange}' is disabled for pair '{exchange}:{symbol}'")
        elif pair.status != "active":
            errors.append(f"Market pair '{exchange}:{symbol}' is disabled")

    if errors:
        raise StrategyConfigValidationError("; ".join(errors))

    return [{"exchange": exchange, "symbol": symbol} for exchange, symbol in pairs]


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
