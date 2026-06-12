from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.market import AlphaMarketContext, Features
from app.services.market_regime import (
    MarketQualityInput,
    MarketRegimeService,
    MarketWideRegimeContext,
)


MarketContextSeverity = Literal["blocker", "warning"]


class MarketContextBlocker(BaseModel):
    code: str
    severity: MarketContextSeverity = "blocker"
    source: str = "market_context"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketContextSnapshot(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    timestamp: int
    risk_off: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    blockers: list[MarketContextBlocker] = Field(default_factory=list)
    warnings: list[MarketContextBlocker] = Field(default_factory=list)
    btc_regime: str | None = None
    eth_regime: str | None = None
    funding_rate: float | None = None
    funding_pressure: float | None = None
    oi_delta: float | None = None
    spread_bps: float | None = None
    bid_depth_usd: float | None = None
    ask_depth_usd: float | None = None
    depth_usd: float | None = None
    market_wide: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)


class MarketContextService:
    def build_snapshot(
        self,
        *,
        features: Features,
        direction: str,
        alpha_context: AlphaMarketContext | None = None,
        market_quality: MarketQualityInput | None = None,
        market_wide_context: MarketWideRegimeContext | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> MarketContextSnapshot:
        settings_map = dict(settings or {})
        normalized_direction = direction.strip().lower()
        blockers: list[MarketContextBlocker] = []
        warnings: list[MarketContextBlocker] = []
        major_regimes = _major_regimes(market_wide_context, settings_map)

        normalized_symbol = _normalized_symbol(features.symbol)
        if normalized_direction == "long":
            btc_regime = major_regimes.get("BTCUSDT")
            eth_regime = major_regimes.get("ETHUSDT")
            if btc_regime == "trend_down":
                blockers.append(
                    _blocker(
                        "btc_risk_off",
                        "BTC market context is risk-off; altcoin longs are blocked.",
                        {"major_symbol": "BTCUSDT", "major_regime": btc_regime},
                    )
                )
            if eth_regime == "trend_down" and normalized_symbol not in {"BTCUSDT", "BTCUSD"}:
                blockers.append(
                    _blocker(
                        "eth_risk_off",
                        "ETH market context is risk-off; altcoin longs require caution.",
                        {"major_symbol": "ETHUSDT", "major_regime": eth_regime},
                    )
                )

        funding_rate = _first_float(
            getattr(alpha_context, "funding_rate", None),
            getattr(features, "funding_rate", None),
        )
        funding_pressure = _first_float(getattr(alpha_context, "funding_pressure", None))
        if _funding_extreme(
            direction=normalized_direction,
            funding_rate=funding_rate,
            funding_pressure=funding_pressure,
            settings=settings_map,
        ):
            blockers.append(
                _blocker(
                    "funding_extreme",
                    "Funding pressure is extreme for this trade direction.",
                    {
                        "funding_rate": funding_rate,
                        "funding_pressure": funding_pressure,
                    },
                )
            )

        oi_delta = _first_float(
            getattr(alpha_context, "oi_delta_5m", None),
            getattr(alpha_context, "oi_delta_15m", None),
            getattr(features, "oi_change", None),
        )
        oi_threshold = abs(_float_setting(settings_map, "market_context_oi_unstable_threshold", 0.15))
        if oi_delta is not None and abs(oi_delta) >= oi_threshold:
            blockers.append(
                _blocker(
                    "oi_unstable",
                    "Open interest is moving too aggressively for a clean entry.",
                    {"oi_delta": oi_delta, "threshold": oi_threshold},
                )
            )

        spread_bps = _first_float(getattr(market_quality, "spread_bps", None))
        max_spread_bps = _float_setting(settings_map, "market_context_max_spread_bps", 0.0)
        if max_spread_bps > 0 and spread_bps is not None and spread_bps > max_spread_bps:
            blockers.append(
                _blocker(
                    "spread_too_wide",
                    "Spread is too wide for the configured market-context limit.",
                    {"spread_bps": spread_bps, "max_spread_bps": max_spread_bps},
                )
            )

        bid_depth = _first_float(getattr(alpha_context, "bid_depth_usd", None))
        ask_depth = _first_float(getattr(alpha_context, "ask_depth_usd", None))
        depth = _min_positive(bid_depth, ask_depth)
        min_depth = _float_setting(settings_map, "market_context_min_depth_usd", 0.0)
        if min_depth > 0 and (depth is None or depth < min_depth):
            blockers.append(
                _blocker(
                    "depth_insufficient",
                    "Visible orderbook depth is below the configured market-context minimum.",
                    {"depth_usd": depth, "min_depth_usd": min_depth},
                )
            )

        reason_codes = _dedupe([blocker.code for blocker in blockers] + [warning.code for warning in warnings])
        return MarketContextSnapshot(
            exchange=features.exchange,
            symbol=features.symbol,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            risk_off=any(code in {"btc_risk_off", "eth_risk_off"} for code in reason_codes),
            reason_codes=reason_codes,
            blockers=blockers,
            warnings=warnings,
            btc_regime=major_regimes.get("BTCUSDT"),
            eth_regime=major_regimes.get("ETHUSDT"),
            funding_rate=funding_rate,
            funding_pressure=funding_pressure,
            oi_delta=oi_delta,
            spread_bps=spread_bps,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            depth_usd=depth,
            market_wide={
                "available_symbols": [] if market_wide_context is None else list(market_wide_context.available_symbols),
                "sufficient_data": bool(market_wide_context and market_wide_context.sufficient_data),
                "major_regimes": major_regimes,
            },
            data_quality=_data_quality(alpha_context, market_quality, market_wide_context),
        )


def _major_regimes(
    market_wide_context: MarketWideRegimeContext | None,
    settings: Mapping[str, Any],
) -> dict[str, str]:
    if market_wide_context is None:
        return {}
    service = MarketRegimeService()
    regimes: dict[str, str] = {}
    for symbol, features in market_wide_context.majors.items():
        regimes[symbol.upper()] = service.classify(features=features, settings=settings).base_label
    return regimes


def _funding_extreme(
    *,
    direction: str,
    funding_rate: float | None,
    funding_pressure: float | None,
    settings: Mapping[str, Any],
) -> bool:
    pressure_threshold = abs(_float_setting(settings, "market_context_funding_pressure_threshold", 1.0))
    rate_threshold = abs(_float_setting(settings, "market_context_funding_rate_threshold", 0.0015))
    directional_pressure = _directional_value(direction, funding_pressure)
    directional_rate = _directional_value(direction, funding_rate)
    return (
        directional_pressure is not None
        and directional_pressure >= pressure_threshold
    ) or (
        directional_rate is not None
        and directional_rate >= rate_threshold
    )


def _directional_value(direction: str, value: float | None) -> float | None:
    if value is None:
        return None
    return value if direction == "long" else -value if direction == "short" else abs(value)


def _blocker(code: str, message: str, metadata: Mapping[str, Any]) -> MarketContextBlocker:
    return MarketContextBlocker(code=code, message=message, metadata=dict(metadata))


def _normalized_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "").replace(":PERP", "")


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _float_setting(settings: Mapping[str, Any], key: str, default: float) -> float:
    try:
        return float(settings.get(key, default))
    except (TypeError, ValueError):
        return default


def _min_positive(*values: float | None) -> float | None:
    positives = [value for value in values if value is not None and value > 0]
    if not positives:
        return None
    return min(positives)


def _data_quality(
    alpha_context: AlphaMarketContext | None,
    market_quality: MarketQualityInput | None,
    market_wide_context: MarketWideRegimeContext | None,
) -> dict[str, Any]:
    available: list[str] = []
    missing: list[str] = []
    if alpha_context is None:
        missing.append("alpha_context")
    else:
        available.append("alpha_context")
        quality = alpha_context.data_quality or {}
        available.extend(str(item) for item in quality.get("available_sources", []) if item is not None)
        missing.extend(str(item) for item in quality.get("missing_sources", []) if item is not None)
    if market_quality is None:
        missing.append("market_quality")
    else:
        available.append("market_quality")
    if market_wide_context is None or not market_wide_context.sufficient_data:
        missing.append("market_wide_context")
    else:
        available.append("market_wide_context")
    return {
        "available_sources": _dedupe(available),
        "missing_sources": _dedupe(missing),
    }


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


market_context_service = MarketContextService()
