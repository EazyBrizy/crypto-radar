from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.schemas.market import Features
from app.schemas.signal import NoTradeFilterResult, SignalLayerCheck, StrategySignal


class NoTradeFilterService:
    def evaluate(
        self,
        signal: StrategySignal,
        features: Features,
        context: Any,
        settings: Mapping[str, Any] | None,
    ) -> NoTradeFilterResult:
        settings_map = dict(settings or {})
        if not _bool_setting(settings_map, "no_trade_filters_enabled", False):
            return NoTradeFilterResult(
                enabled=False,
                checks=[
                    SignalLayerCheck(
                        name="no_trade_filter",
                        status="skipped",
                        reason="No-trade filters are disabled by settings",
                    )
                ],
                metadata={"enabled": False},
            )

        checks = [
            _missing_market_data_check(context, settings_map),
            _low_liquidity_check(signal, context, settings_map),
            _high_spread_check(signal, context, settings_map),
            _high_slippage_check(context, settings_map),
            _near_htf_obstacle_check(signal, context, settings_map),
            _overextended_entry_check(signal, context),
            _extreme_funding_check(signal, features, settings_map),
            _strategy_cooldown_check(features, context, settings_map),
            _daily_loss_streak_check(context, settings_map),
            _negative_edge_check(signal, context, settings_map),
        ]
        blockers = [check.reason or check.name for check in checks if check.status == "failed"]
        warnings = [check.reason or check.name for check in checks if check.status == "warning"]
        blocker_codes = [check.name for check in checks if check.status == "failed"]
        warning_codes = [check.name for check in checks if check.status == "warning"]

        return NoTradeFilterResult(
            enabled=True,
            blocked=bool(blockers),
            hard_block=bool(blockers),
            blockers=blockers,
            warnings=warnings,
            checks=checks,
            metadata={
                "blocker_codes": blocker_codes,
                "warning_codes": warning_codes,
            },
        )


def _missing_market_data_check(
    context: Any,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    status = _string_value(_context_value(context, "market_data_status"))
    mode = _mode(context)
    requires_fresh = _bool_setting(settings, "real_requires_fresh_market_data", True)
    if status in {"fresh", "partial", "missing", "stale", "unknown"}:
        if status == "fresh":
            return SignalLayerCheck(
                name="missing_market_data",
                status="passed",
                reason="Fresh market data is available",
                metadata={"market_data_status": status},
            )
        if status == "partial":
            return SignalLayerCheck(
                name="missing_market_data",
                status="warning",
                reason="Market data is partial; entry quality is uncertain",
                metadata={"market_data_status": status},
            )
        reason = (
            "Market data is missing or stale; real entries require fresh market data"
            if mode == "real" and requires_fresh
            else "Market data is missing or stale; no-trade filter can only warn outside real entry"
        )
        return SignalLayerCheck(
            name="missing_market_data",
            status="failed" if mode == "real" and requires_fresh else "warning",
            reason=reason,
            metadata={"market_data_status": status},
        )

    quality = _quality(context)
    market_quality = _context_value(context, "market_quality")
    if quality is None and market_quality is None:
        return SignalLayerCheck(
            name="missing_market_data",
            status="warning",
            reason="External market-quality data is unavailable for no-trade filters",
        )
    return SignalLayerCheck(
        name="missing_market_data",
        status="passed",
        reason="Market-quality context is available",
    )


def _low_liquidity_check(
    signal: StrategySignal,
    context: Any,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    min_depth = _positive_float_setting(settings, "min_depth_usd_for_entry")
    depth = _number_or_none(_context_value(context, "orderbook_depth_usd"))
    if min_depth is not None:
        if depth is None:
            return SignalLayerCheck(
                name="low_liquidity",
                status="skipped",
                reason="Orderbook depth is unavailable for configured liquidity threshold",
                metadata={"min_depth_usd_for_entry": min_depth},
            )
        if depth < min_depth:
            return SignalLayerCheck(
                name="low_liquidity",
                status="failed",
                score=round(depth, 3),
                reason=f"Orderbook depth ${depth:,.0f} is below entry minimum ${min_depth:,.0f}",
                metadata={"orderbook_depth_usd": depth, "min_depth_usd_for_entry": min_depth},
            )

    quality = signal.quality or _quality(context)
    if quality is None:
        return SignalLayerCheck(
            name="low_liquidity",
            status="skipped",
            reason="Market quality snapshot is unavailable for liquidity filter",
        )

    tier = _string_value(_attribute(quality, "tier"))
    allow_low_liquidity = _bool_setting(settings, "allow_low_liquidity", False)
    if tier == "low_liquidity" and not allow_low_liquidity:
        return SignalLayerCheck(
            name="low_liquidity",
            status="failed",
            reason="Low-liquidity asset tier is not allowed for entry",
            metadata={"tier": tier},
        )

    for check in _checks(quality):
        if check.name == "24h_volume" and check.status == "failed":
            return SignalLayerCheck(
                name="low_liquidity",
                status="failed",
                score=check.score,
                reason=check.reason or "24h quote volume is below configured market-quality minimum",
                metadata=dict(check.metadata),
            )

    return SignalLayerCheck(
        name="low_liquidity",
        status="passed",
        score=None if depth is None else round(depth, 3),
        reason="Liquidity filter passed",
        metadata={"tier": tier, "orderbook_depth_usd": depth},
    )


def _high_spread_check(
    signal: StrategySignal,
    context: Any,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    limit = _positive_float_setting(settings, "max_spread_bps_for_entry", "max_spread_bps")
    if limit is None:
        return SignalLayerCheck(
            name="high_spread",
            status="skipped",
            reason="Entry spread threshold is disabled",
        )
    spread = _first_number(
        _context_value(context, "spread_bps"),
        _attribute(signal.quality, "spread_bps"),
        _attribute(_quality(context), "spread_bps"),
        _attribute(_context_value(context, "market_quality"), "spread_bps"),
    )
    if spread is None:
        return SignalLayerCheck(
            name="high_spread",
            status="skipped",
            reason="Spread snapshot is unavailable for no-trade filter",
            metadata={"max_spread_bps_for_entry": limit},
        )
    if spread > limit:
        return SignalLayerCheck(
            name="high_spread",
            status="failed",
            score=round(spread, 3),
            reason=f"Spread {spread:.1f} bps is above entry limit {limit:.1f} bps",
            metadata={"spread_bps": spread, "max_spread_bps_for_entry": limit},
        )
    return SignalLayerCheck(
        name="high_spread",
        status="passed",
        score=round(spread, 3),
        reason=f"Spread {spread:.1f} bps is within entry limit {limit:.1f} bps",
        metadata={"spread_bps": spread, "max_spread_bps_for_entry": limit},
    )


def _high_slippage_check(
    context: Any,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    limit = _positive_float_setting(settings, "max_slippage_bps_for_entry", "max_slippage_bps")
    if limit is None:
        return SignalLayerCheck(
            name="high_slippage",
            status="skipped",
            reason="Entry slippage threshold is disabled",
        )
    slippage = _number_or_none(_context_value(context, "slippage_bps"))
    if slippage is None:
        return SignalLayerCheck(
            name="high_slippage",
            status="skipped",
            reason="Expected slippage is unavailable for no-trade filter",
            metadata={"max_slippage_bps_for_entry": limit},
        )
    if slippage > limit:
        return SignalLayerCheck(
            name="high_slippage",
            status="failed",
            score=round(slippage, 3),
            reason=f"Expected slippage {slippage:.1f} bps is above entry limit {limit:.1f} bps",
            metadata={"slippage_bps": slippage, "max_slippage_bps_for_entry": limit},
        )
    return SignalLayerCheck(
        name="high_slippage",
        status="passed",
        score=round(slippage, 3),
        reason=f"Expected slippage {slippage:.1f} bps is within entry limit {limit:.1f} bps",
        metadata={"slippage_bps": slippage, "max_slippage_bps_for_entry": limit},
    )


def _near_htf_obstacle_check(
    signal: StrategySignal,
    context: Any,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    regime = signal.regime or _context_value(context, "regime")
    if regime is None:
        return SignalLayerCheck(
            name="near_htf_obstacle",
            status="skipped",
            reason="Regime snapshot is unavailable for HTF obstacle filter",
        )

    obstacle = None
    for check in _checks(regime):
        if check.name in {"context_resistance", "context_support"} and check.status in {"warning", "failed"}:
            obstacle = check
            break
    if obstacle is None:
        return SignalLayerCheck(
            name="near_htf_obstacle",
            status="passed",
            reason="No blocking higher-timeframe obstacle is near the entry",
        )

    max_distance_r = _positive_float_setting(settings, "max_obstacle_distance_r")
    distance_r = _number_or_none(obstacle.metadata.get("distance_r"))
    before_tp1 = bool(obstacle.metadata.get("before_tp1"))
    if before_tp1 or max_distance_r is None or (distance_r is not None and distance_r <= max_distance_r):
        return SignalLayerCheck(
            name="near_htf_obstacle",
            status="failed",
            score=obstacle.score,
            reason=obstacle.reason or "Higher-timeframe support/resistance is too close to entry",
            metadata={
                **dict(obstacle.metadata),
                "max_obstacle_distance_r": max_distance_r,
            },
        )

    return SignalLayerCheck(
        name="near_htf_obstacle",
        status="passed",
        score=obstacle.score,
        reason="Higher-timeframe obstacle warning is outside the configured no-trade R distance",
        metadata={
            **dict(obstacle.metadata),
            "max_obstacle_distance_r": max_distance_r,
        },
    )


def _overextended_entry_check(
    signal: StrategySignal,
    context: Any,
) -> SignalLayerCheck:
    confirmation = signal.confirmation or _context_value(context, "confirmation")
    if confirmation is None:
        return SignalLayerCheck(
            name="overextended_entry",
            status="skipped",
            reason="Confirmation snapshot is unavailable for overextension filter",
        )

    for check in _checks(confirmation):
        if check.name == "overextension_guard":
            if check.status in {"warning", "failed"}:
                return SignalLayerCheck(
                    name="overextended_entry",
                    status="failed",
                    score=check.score,
                    reason=check.reason or "Entry candle is overextended",
                    metadata=dict(check.metadata),
                )
            return SignalLayerCheck(
                name="overextended_entry",
                status="passed",
                score=check.score,
                reason=check.reason or "Entry candle is not overextended",
                metadata=dict(check.metadata),
            )

    return SignalLayerCheck(
        name="overextended_entry",
        status="skipped",
        reason="Overextension guard check is unavailable",
    )


def _extreme_funding_check(
    signal: StrategySignal,
    features: Features,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    funding = features.funding_rate
    threshold = _positive_float_setting(settings, "max_abs_funding_rate_for_entry")
    direction_aware_threshold = _positive_float_setting(settings, "funding_block_threshold")
    if threshold is None and direction_aware_threshold is None:
        return SignalLayerCheck(
            name="extreme_funding",
            status="skipped",
            reason="Funding no-trade threshold is not configured",
        )
    if funding is None:
        return SignalLayerCheck(
            name="extreme_funding",
            status="skipped",
            reason="Funding rate is unavailable",
        )
    if threshold is not None:
        blocked = abs(funding) >= threshold
        active_threshold = threshold
    else:
        direction = signal.direction.upper()
        blocked = funding >= direction_aware_threshold if direction == "LONG" else funding <= -direction_aware_threshold
        active_threshold = direction_aware_threshold or 0.0
    if blocked:
        return SignalLayerCheck(
            name="extreme_funding",
            status="failed",
            score=round(funding, 8),
            reason=f"Funding {funding:.4%} is beyond configured entry threshold {active_threshold:.4%}",
            metadata={"funding_rate": funding, "threshold": active_threshold},
        )
    return SignalLayerCheck(
        name="extreme_funding",
        status="passed",
        score=round(funding, 8),
        reason="Funding filter passed",
        metadata={"funding_rate": funding, "threshold": active_threshold},
    )


def _strategy_cooldown_check(
    features: Features,
    context: Any,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    cooldown_minutes = _positive_int_setting(settings, "cooldown_after_stop_minutes")
    if cooldown_minutes is None:
        return SignalLayerCheck(
            name="strategy_cooldown",
            status="skipped",
            reason="Cooldown after stop-loss is disabled",
        )

    remaining = _number_or_none(
        _context_value(context, "strategy_cooldown_remaining_minutes")
        or _context_value(context, "cooldown_remaining_minutes")
    )
    if remaining is not None and remaining > 0:
        return SignalLayerCheck(
            name="strategy_cooldown",
            status="failed",
            score=round(remaining, 3),
            reason=f"Strategy is cooling down for {remaining:.1f} more minutes after stop-loss",
            metadata={"cooldown_remaining_minutes": remaining},
        )

    now = _reference_time(features)
    cooldown_until = _datetime_or_none(_context_value(context, "strategy_cooldown_until"))
    if cooldown_until is not None and cooldown_until > now:
        remaining_minutes = (cooldown_until - now).total_seconds() / 60
        return SignalLayerCheck(
            name="strategy_cooldown",
            status="failed",
            score=round(remaining_minutes, 3),
            reason=f"Strategy is cooling down for {remaining_minutes:.1f} more minutes after stop-loss",
            metadata={"cooldown_until": cooldown_until.isoformat()},
        )

    last_stop_loss_at = _datetime_or_none(_context_value(context, "last_stop_loss_at"))
    if last_stop_loss_at is not None:
        elapsed_minutes = (now - last_stop_loss_at).total_seconds() / 60
        if elapsed_minutes < cooldown_minutes:
            remaining_minutes = cooldown_minutes - elapsed_minutes
            return SignalLayerCheck(
                name="strategy_cooldown",
                status="failed",
                score=round(remaining_minutes, 3),
                reason=f"Strategy is cooling down for {remaining_minutes:.1f} more minutes after stop-loss",
                metadata={
                    "last_stop_loss_at": last_stop_loss_at.isoformat(),
                    "cooldown_after_stop_minutes": cooldown_minutes,
                },
            )
        return SignalLayerCheck(
            name="strategy_cooldown",
            status="passed",
            reason="Strategy cooldown after stop-loss has elapsed",
            metadata={
                "last_stop_loss_at": last_stop_loss_at.isoformat(),
                "cooldown_after_stop_minutes": cooldown_minutes,
            },
        )

    return SignalLayerCheck(
        name="strategy_cooldown",
        status="skipped",
        reason="No stop-loss cooldown context is available",
        metadata={"cooldown_after_stop_minutes": cooldown_minutes},
    )


def _daily_loss_streak_check(
    context: Any,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    max_losses = _positive_int_setting(settings, "max_strategy_losses_per_day")
    if max_losses is None:
        return SignalLayerCheck(
            name="daily_loss_streak",
            status="skipped",
            reason="Daily strategy loss-streak limit is disabled",
        )
    losses = _first_number(
        _context_value(context, "strategy_losses_today"),
        _context_value(context, "daily_strategy_losses"),
        _context_value(context, "strategy_loss_streak"),
        _context_value(context, "loss_streak"),
    )
    if losses is None:
        return SignalLayerCheck(
            name="daily_loss_streak",
            status="skipped",
            reason="Daily strategy loss-streak context is unavailable",
            metadata={"max_strategy_losses_per_day": max_losses},
        )
    if losses >= max_losses:
        return SignalLayerCheck(
            name="daily_loss_streak",
            status="failed",
            score=round(losses, 3),
            reason=f"Strategy has {int(losses)} losses today; configured no-trade limit is {max_losses}",
            metadata={"strategy_losses_today": losses, "max_strategy_losses_per_day": max_losses},
        )
    return SignalLayerCheck(
        name="daily_loss_streak",
        status="passed",
        score=round(losses, 3),
        reason="Daily strategy loss-streak filter passed",
        metadata={"strategy_losses_today": losses, "max_strategy_losses_per_day": max_losses},
    )


def _negative_edge_check(
    signal: StrategySignal,
    context: Any,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    if _mode(context) != "real":
        return SignalLayerCheck(
            name="negative_edge",
            status="skipped",
            reason="Positive-edge no-trade filter is enforced only for real entry context",
        )
    if not _bool_setting(settings, "real_requires_positive_edge", True):
        return SignalLayerCheck(
            name="negative_edge",
            status="skipped",
            reason="Positive edge is not required by settings",
        )

    edge = signal.edge or _context_value(context, "signal_edge")
    if edge is None:
        return SignalLayerCheck(
            name="negative_edge",
            status="failed",
            reason="Signal edge is missing; real entries require positive edge",
        )

    status = _string_value(_attribute(edge, "status"))
    sample_size = _number_or_none(_attribute(edge, "sample_size")) or 0
    min_sample_size = _positive_int_setting(settings, "edge_min_sample_size") or 0
    expectancy = _number_or_none(_attribute(edge, "expectancy_after_costs_r"))
    min_expectancy = _number_or_none(settings.get("min_expectancy_after_costs_r")) or 0.0
    if status != "positive":
        return SignalLayerCheck(
            name="negative_edge",
            status="failed",
            reason=f"Signal edge is {status or 'unknown'}; real entries require positive edge",
            metadata={"edge_status": status},
        )
    if sample_size < min_sample_size:
        return SignalLayerCheck(
            name="negative_edge",
            status="failed",
            reason="Signal edge sample size is below the configured real-entry minimum",
            metadata={"sample_size": sample_size, "edge_min_sample_size": min_sample_size},
        )
    if expectancy is None or expectancy <= min_expectancy:
        return SignalLayerCheck(
            name="negative_edge",
            status="failed",
            reason="Signal expectancy after costs is below the configured real-entry minimum",
            metadata={
                "expectancy_after_costs_r": expectancy,
                "min_expectancy_after_costs_r": min_expectancy,
            },
        )
    return SignalLayerCheck(
        name="negative_edge",
        status="passed",
        reason="Signal edge is positive for real entry",
        metadata={
            "edge_status": status,
            "sample_size": sample_size,
            "expectancy_after_costs_r": expectancy,
        },
    )


def _context_value(context: Any, key: str) -> Any:
    if context is None:
        return None
    if isinstance(context, Mapping):
        return context.get(key)
    return getattr(context, key, None)


def _quality(context: Any) -> Any:
    return _context_value(context, "quality")


def _checks(snapshot: Any) -> list[SignalLayerCheck]:
    raw_checks = _attribute(snapshot, "checks")
    if raw_checks is None:
        return []
    result: list[SignalLayerCheck] = []
    for check in raw_checks:
        if isinstance(check, SignalLayerCheck):
            result.append(check)
        elif isinstance(check, Mapping):
            result.append(SignalLayerCheck.model_validate(check))
    return result


def _attribute(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _mode(context: Any) -> str | None:
    mode = _string_value(_context_value(context, "mode") or _context_value(context, "execution_mode"))
    return mode.lower() if mode is not None else None


def _bool_setting(settings: Mapping[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _positive_float_setting(settings: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number_or_none(settings.get(key))
        if value is not None and value > 0:
            return value
    return None


def _positive_int_setting(settings: Mapping[str, Any], key: str) -> int | None:
    value = _number_or_none(settings.get(key))
    if value is None or value <= 0:
        return None
    return int(value)


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number_or_none(value)
        if number is not None:
            return number
    return None


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def _reference_time(features: Features) -> datetime:
    timestamp = features.timestamp
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, timezone.utc)


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    number = _number_or_none(value)
    if number is not None:
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, timezone.utc)
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


no_trade_filter_service = NoTradeFilterService()
