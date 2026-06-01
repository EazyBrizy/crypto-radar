from __future__ import annotations

from typing import Any, Mapping

from app.schemas.risk import (
    BreakevenPlan,
    FuturesRiskPlan,
    PositionSizingResult,
    RiskAdjustmentPlan,
    RiskCheckResult,
    StopLossPlan,
    TakeProfitPlan,
    TakeProfitTarget,
    TradeInstrumentType,
    TrailingStopPlan,
)
from app.schemas.signal import SignalEdgeSnapshot
from app.schemas.trade_plan import TradePlan, TradePlanTarget
from app.schemas.user import RiskManagementPatch, RiskManagementSettings, RiskProfileName

RISK_PROFILE_PRESETS: dict[RiskProfileName, RiskManagementSettings] = {
    "conservative": RiskManagementSettings(
        risk_profile="conservative",
        risk_per_trade_percent=0.5,
        min_rr_ratio=2.0,
        max_daily_loss_percent=1.5,
        max_account_drawdown_percent=8.0,
        max_open_risk_percent=3.0,
        include_fees_in_risk=True,
        include_slippage_in_risk=True,
        stop_loss_mode="fixed_percent",
        default_stop_loss_percent=1.5,
        atr_period=14,
        atr_multiplier=2.0,
        take_profit_mode="risk_multiple",
        tp1_r_multiple=1.0,
        tp2_r_multiple=2.0,
        tp3_r_multiple=3.0,
        partial_take_profit_enabled=True,
        tp1_close_percent=30.0,
        tp2_close_percent=40.0,
        tp3_close_percent=30.0,
        move_sl_to_breakeven_after_r=1.0,
        breakeven_offset_percent=0.05,
        trailing_stop_enabled=True,
        trailing_mode="atr",
        trailing_atr_multiplier=1.5,
        trailing_stop_percent=0.5,
        max_leverage=3,
        min_liquidation_buffer_percent=2.0,
    ),
    "balanced": RiskManagementSettings(
        risk_profile="balanced",
        risk_per_trade_percent=1.0,
        min_rr_ratio=2.0,
        max_daily_loss_percent=3.0,
        max_account_drawdown_percent=10.0,
        max_open_risk_percent=5.0,
        include_fees_in_risk=True,
        include_slippage_in_risk=True,
        stop_loss_mode="fixed_percent",
        default_stop_loss_percent=1.5,
        atr_period=14,
        atr_multiplier=2.0,
        take_profit_mode="risk_multiple",
        tp1_r_multiple=1.0,
        tp2_r_multiple=2.0,
        tp3_r_multiple=3.0,
        partial_take_profit_enabled=True,
        tp1_close_percent=30.0,
        tp2_close_percent=40.0,
        tp3_close_percent=30.0,
        move_sl_to_breakeven_after_r=1.0,
        breakeven_offset_percent=0.05,
        trailing_stop_enabled=True,
        trailing_mode="atr",
        trailing_atr_multiplier=1.5,
        trailing_stop_percent=0.5,
        max_leverage=3,
        min_liquidation_buffer_percent=2.0,
    ),
    "aggressive": RiskManagementSettings(
        risk_profile="aggressive",
        risk_per_trade_percent=1.5,
        min_rr_ratio=1.5,
        max_daily_loss_percent=4.0,
        max_account_drawdown_percent=15.0,
        max_open_risk_percent=7.0,
        include_fees_in_risk=True,
        include_slippage_in_risk=True,
        stop_loss_mode="fixed_percent",
        default_stop_loss_percent=1.5,
        atr_period=14,
        atr_multiplier=2.0,
        take_profit_mode="risk_multiple",
        tp1_r_multiple=1.0,
        tp2_r_multiple=2.0,
        tp3_r_multiple=3.0,
        partial_take_profit_enabled=True,
        tp1_close_percent=30.0,
        tp2_close_percent=40.0,
        tp3_close_percent=30.0,
        move_sl_to_breakeven_after_r=1.0,
        breakeven_offset_percent=0.05,
        trailing_stop_enabled=True,
        trailing_mode="atr",
        trailing_atr_multiplier=1.5,
        trailing_stop_percent=0.5,
        max_leverage=3,
        min_liquidation_buffer_percent=2.0,
    ),
    "custom": RiskManagementSettings(
        risk_profile="custom",
        risk_per_trade_percent=1.0,
        min_rr_ratio=2.0,
        max_daily_loss_percent=3.0,
        max_account_drawdown_percent=10.0,
        max_open_risk_percent=5.0,
        include_fees_in_risk=True,
        include_slippage_in_risk=True,
        stop_loss_mode="fixed_percent",
        default_stop_loss_percent=1.5,
        atr_period=14,
        atr_multiplier=2.0,
        take_profit_mode="risk_multiple",
        tp1_r_multiple=1.0,
        tp2_r_multiple=2.0,
        tp3_r_multiple=3.0,
        partial_take_profit_enabled=True,
        tp1_close_percent=30.0,
        tp2_close_percent=40.0,
        tp3_close_percent=30.0,
        move_sl_to_breakeven_after_r=1.0,
        breakeven_offset_percent=0.05,
        trailing_stop_enabled=True,
        trailing_mode="atr",
        trailing_atr_multiplier=1.5,
        trailing_stop_percent=0.5,
        max_leverage=3,
        min_liquidation_buffer_percent=2.0,
    ),
}

_RISK_CUSTOM_FIELDS = {
    "risk_per_trade_percent",
    "min_rr_ratio",
    "max_daily_loss_percent",
    "max_weekly_loss_percent",
    "max_account_drawdown_percent",
    "max_open_risk_percent",
    "max_correlated_risk_percent",
    "max_spread_bps",
    "max_slippage_bps",
    "max_price_deviation_bps",
    "max_orderbook_liquidity_ratio",
    "stop_loss_required",
    "take_profit_required",
    "stop_loss_mode",
    "default_stop_loss_percent",
    "atr_period",
    "atr_multiplier",
    "take_profit_mode",
    "tp1_r_multiple",
    "tp2_r_multiple",
    "tp3_r_multiple",
    "partial_take_profit_enabled",
    "tp1_close_percent",
    "tp2_close_percent",
    "tp3_close_percent",
    "move_sl_to_breakeven_after_r",
    "breakeven_offset_percent",
    "trailing_stop_enabled",
    "trailing_mode",
    "trailing_atr_multiplier",
    "trailing_stop_percent",
    "max_leverage",
    "min_liquidation_buffer_percent",
    "liquidation_buffer_required",
    "spot_risk_per_trade_percent",
    "spot_max_position_size_percent",
    "spot_stop_required",
    "futures_risk_per_trade_percent",
    "futures_max_leverage",
    "futures_max_open_risk_percent",
    "futures_liquidation_buffer_required",
    "virtual_risk_mode",
    "virtual_risk_per_trade_percent",
    "virtual_starting_balance",
    "virtual_slippage_model",
    "virtual_fee_model",
    "virtual_trading_uses_realistic_execution",
    "real_requires_fresh_market_data",
    "real_requires_positive_edge",
    "no_trade_filters_enabled",
    "max_spread_bps_for_entry",
    "max_slippage_bps_for_entry",
    "min_depth_usd_for_entry",
    "max_obstacle_distance_r",
    "cooldown_after_stop_minutes",
    "max_strategy_losses_per_day",
    "edge_min_sample_size",
    "min_expectancy_after_costs_r",
    "strategy_risk_multipliers",
    "auto_reduce_risk_after_losses",
    "allow_risk_increase_after_profit",
    "increase_risk_after_profit_streak",
    "max_risk_boost",
}

_STRATEGY_RISK_ALIAS_FALLBACKS: dict[str, str] = {
    "trend_pullback": "trend_following",
    "trend_pullback_continuation": "trend_following",
    "volatility_squeeze_breakout": "breakout",
    "liquidity_sweep_reversal": "smart_money_setup",
}

_TAKE_PROFIT_LABELS = {"TP1", "TP2", "TP3"}
EDGE_VIRTUAL_WARNING = "Edge is insufficient/unknown; virtual-only recommended."


class TradePlanValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def normalize_risk_profile(value: Any) -> RiskProfileName:
    if value in RISK_PROFILE_PRESETS:
        return value
    return "balanced"


def risk_profile_preset(profile: RiskProfileName | str | None) -> RiskManagementSettings:
    return RISK_PROFILE_PRESETS[normalize_risk_profile(profile)]


def normalize_risk_management_settings(
    raw_settings: Mapping[str, Any] | None,
    user_profile: str | None = None,
) -> dict[str, Any]:
    raw = dict(raw_settings or {})
    profile = normalize_risk_profile(raw.get("risk_profile") or user_profile)
    if profile == "custom":
        values = risk_profile_preset("custom").model_dump()
        for field in _RISK_CUSTOM_FIELDS:
            if raw.get(field) is not None:
                values[field] = raw[field]
        values["risk_profile"] = "custom"
        return RiskManagementSettings.model_validate(values).model_dump()
    return risk_profile_preset(profile).model_dump()


def apply_risk_management_patch(
    *,
    current_settings: Mapping[str, Any] | None,
    current_user_profile: str | None,
    patch: RiskManagementPatch | None,
    risk_profile: RiskProfileName | None,
) -> dict[str, Any] | None:
    if patch is None and risk_profile is None:
        return None

    current = normalize_risk_management_settings(current_settings, current_user_profile)
    patch_values = patch.model_dump(exclude_none=True) if patch is not None else {}
    manual_values_present = any(field in patch_values for field in _RISK_CUSTOM_FIELDS)
    requested_profile = normalize_risk_profile(
        risk_profile
        or patch_values.get("risk_profile")
        or ("custom" if manual_values_present else current.get("risk_profile"))
    )

    if requested_profile != "custom":
        return risk_profile_preset(requested_profile).model_dump()

    values = dict(current)
    values["risk_profile"] = "custom"
    for field in _RISK_CUSTOM_FIELDS:
        if field in patch_values:
            values[field] = patch_values[field]
    return RiskManagementSettings.model_validate(values).model_dump()


def calculate_trade_risk_adjustment(
    *,
    account_equity: float,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
    instrument_type: TradeInstrumentType,
    strategy: str,
    signal_score: float,
    volatility_multiplier: float = 1.0,
    user_mode_multiplier: float = 1.0,
) -> RiskAdjustmentPlan:
    settings = _settings_model(risk_settings)
    if account_equity <= 0:
        raise ValueError("account_equity must be greater than zero")
    if not 0 <= signal_score <= 100:
        raise ValueError("signal_score must be between 0 and 100")
    if volatility_multiplier < 0 or user_mode_multiplier < 0:
        raise ValueError("risk multipliers must be greater than or equal to zero")

    base_risk_percent = _base_risk_percent(settings, instrument_type)
    normalized_strategy_key = _normalize_strategy_key(strategy)
    strategy_key = _strategy_key(strategy)
    strategy_multiplier = _strategy_risk_multiplier(settings, normalized_strategy_key)
    signal_multiplier, signal_trade_allowed, signal_virtual_only = _signal_score_multiplier(signal_score)
    warnings: list[str] = []
    if not signal_trade_allowed:
        warnings.append("Signal score is below the configured trading threshold.")
    elif signal_virtual_only:
        warnings.append("Signal score is low; trade should be virtual-only.")

    adjusted_risk_percent = (
        base_risk_percent
        * strategy_multiplier
        * signal_multiplier
        * volatility_multiplier
        * user_mode_multiplier
    )
    return RiskAdjustmentPlan(
        instrument_type=instrument_type,
        strategy=strategy_key,
        signal_score=signal_score,
        account_equity=account_equity,
        base_risk_percent=base_risk_percent,
        base_risk_amount=account_equity * base_risk_percent / 100,
        strategy_risk_multiplier=strategy_multiplier,
        signal_score_multiplier=signal_multiplier,
        volatility_multiplier=volatility_multiplier,
        user_mode_multiplier=user_mode_multiplier,
        adjusted_risk_percent=adjusted_risk_percent,
        adjusted_risk_amount=account_equity * adjusted_risk_percent / 100,
        signal_trade_allowed=signal_trade_allowed,
        signal_virtual_only=signal_virtual_only,
        warnings=warnings,
    )


def calculate_risk_check_result(
    *,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
    risk_adjustment: RiskAdjustmentPlan,
    position_sizing: PositionSizingResult,
    take_profit_plan: TakeProfitPlan | None = None,
    futures_risk_plan: FuturesRiskPlan | None = None,
    available_balance: float | None = None,
    open_risk_amount: float = 0.0,
    daily_loss_amount: float = 0.0,
    exchange_min_order_size: float | None = None,
    exchange_max_order_size: float | None = None,
    exchange_min_notional: float | None = None,
    exchange_max_leverage: int | None = None,
    exchange_rule_status: str = "unknown",
    exchange_rule_age_seconds: float | None = None,
    exchange_rule_ttl_seconds: int | None = None,
    market_data_status: str = "unknown",
    market_data_warnings: list[str] | None = None,
    fee_rate_source: str | None = None,
    maker_fee_rate: float | None = None,
    taker_fee_rate: float | None = None,
    fee_rate_warnings: list[str] | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    mark_price: float | None = None,
    funding_rate: float | None = None,
    spread_percent: float | None = None,
    spread_bps: float | None = None,
    orderbook_depth_usd: float | None = None,
    signal_entry_price: float | None = None,
    correlated_open_risk_amount: float = 0.0,
    correlation_group: str | None = None,
    protection_state: str = "normal",
    protection_reason: str | None = None,
    account_drawdown_percent: float | None = None,
    max_account_drawdown_percent: float | None = None,
    execution_mode: str = "virtual",
    signal_edge: SignalEdgeSnapshot | None = None,
) -> RiskCheckResult:
    settings = _settings_model(risk_settings)
    blockers: list[str] = []
    warnings: list[str] = list(risk_adjustment.warnings)
    warnings.extend(market_data_warnings or [])
    warnings.extend(fee_rate_warnings or [])
    real_entries_allowed = protection_state not in {"virtual_only", "blocked"}
    virtual_entries_allowed = protection_state != "blocked"
    close_only = protection_state in {"virtual_only", "blocked"}
    reduce_only_allowed = True
    protective_orders_allowed = True
    if protection_state == "blocked":
        blockers.append(
            protection_reason
            or "Risk protection mode blocks new entries; close-only actions remain allowed."
        )
    elif protection_state == "virtual_only" and execution_mode == "real":
        blockers.append(
            protection_reason
            or "Risk protection mode allows virtual trading only; real account is close-only."
        )
    elif protection_state == "reduced":
        warnings.append(
            protection_reason
            or "Risk protection mode reduced the current risk multiplier."
        )

    if not risk_adjustment.signal_trade_allowed:
        blockers.append("Signal score is below the minimum tradable threshold.")
    elif risk_adjustment.signal_virtual_only and execution_mode == "real":
        blockers.append("Signal score is virtual-only; real execution is blocked.")

    edge_blockers = _edge_gate_blockers(settings, signal_edge)
    if edge_blockers:
        if execution_mode == "real":
            blockers.extend(edge_blockers)
        elif signal_edge is not None and EDGE_VIRTUAL_WARNING not in warnings:
            warnings.append(EDGE_VIRTUAL_WARNING)

    rr = None
    if take_profit_plan is not None and take_profit_plan.targets:
        rr = (
            take_profit_plan.selected_rr
            if take_profit_plan.selected_rr is not None
            else take_profit_plan.targets[-1].r_multiple
        )
        if _limit_enabled(settings.min_rr_ratio) and rr < settings.min_rr_ratio:
            blockers.append("R:R is below the configured minimum.")
            if signal_entry_price is not None and signal_entry_price != position_sizing.entry_price:
                blockers.append("Market entry price moved far enough to invalidate R:R.")
    elif settings.take_profit_required:
        blockers.append("Take-profit plan is required.")

    if available_balance is not None and position_sizing.required_margin > available_balance:
        blockers.append("Required margin exceeds available balance.")
    if exchange_min_order_size is not None and position_sizing.position_size_base < exchange_min_order_size:
        blockers.append("Position size is below exchange minimum order size.")
    if exchange_max_order_size is not None and position_sizing.position_size_base > exchange_max_order_size:
        blockers.append("Position size is above exchange maximum order size.")
    if exchange_min_notional is not None and position_sizing.notional < exchange_min_notional:
        blockers.append("Position notional is below exchange minimum notional.")
    if exchange_max_leverage is not None and position_sizing.leverage > exchange_max_leverage:
        blockers.append("Leverage exceeds exchange maximum leverage.")
    if exchange_rule_status in {"missing", "stale"}:
        message = (
            "Exchange instrument rules are missing."
            if exchange_rule_status == "missing"
            else "Exchange instrument rules are stale."
        )
        if execution_mode == "real":
            blockers.append(message)
        else:
            warnings.append(message)

    if market_data_status in {"missing", "stale"}:
        message = (
            "Bybit market data is unavailable."
            if market_data_status == "missing"
            else "Bybit market data is stale."
        )
        if execution_mode == "real" and settings.real_requires_fresh_market_data:
            blockers.append(message)
        else:
            warnings.append(message)
    elif market_data_status == "partial":
        warnings.append("Bybit market data is incomplete.")
    if execution_mode == "real" and (best_bid is None or best_ask is None):
        blockers.append("Ticker bid/ask is unavailable.")
    if _limit_enabled(settings.max_spread_bps) and spread_bps is not None and spread_bps > settings.max_spread_bps:
        blockers.append("Spread is above the configured maximum.")
    if _limit_enabled(settings.max_slippage_bps) and position_sizing.slippage_bps > settings.max_slippage_bps:
        blockers.append("Expected slippage is above the configured maximum.")
    price_deviation_bps = None
    if signal_entry_price is not None:
        price_deviation_bps = abs(position_sizing.entry_price - signal_entry_price) / signal_entry_price * 10_000
        if _limit_enabled(settings.max_price_deviation_bps) and price_deviation_bps > settings.max_price_deviation_bps:
            blockers.append("Price moved too far from the signal entry.")

    effective_risk_amount = position_sizing.position_size_base * position_sizing.effective_risk_per_unit
    risk_tolerance = max(0.000001, risk_adjustment.adjusted_risk_amount * 0.02)
    if effective_risk_amount > risk_adjustment.adjusted_risk_amount + risk_tolerance:
        blockers.append("Risk per trade exceeds the adjusted risk limit.")
    if (
        risk_adjustment.instrument_type == "spot"
        and _limit_enabled(settings.spot_max_position_size_percent)
        and position_sizing.notional / risk_adjustment.account_equity * 100
        > settings.spot_max_position_size_percent
    ):
        blockers.append("Spot position size exceeds the configured maximum.")

    orderbook_can_fill = None
    orderbook_liquidity_ratio = None
    if orderbook_depth_usd is None:
        if execution_mode == "real" and settings.real_requires_fresh_market_data:
            blockers.append("Orderbook liquidity is unavailable.")
        elif market_data_status in {"missing", "stale"}:
            warnings.append("Orderbook liquidity is unavailable.")
    elif orderbook_depth_usd <= 0:
        orderbook_can_fill = False
        blockers.append("Orderbook liquidity is empty for the entry side.")
    else:
        orderbook_liquidity_ratio = position_sizing.notional / orderbook_depth_usd
        orderbook_can_fill = (
            True
            if not _limit_enabled(settings.max_orderbook_liquidity_ratio)
            else orderbook_liquidity_ratio <= settings.max_orderbook_liquidity_ratio
        )
        if not orderbook_can_fill:
            blockers.append("Orderbook liquidity is insufficient for calculated position size.")
        elif orderbook_liquidity_ratio > 0.5:
            warnings.append("Calculated position would consume more than half of visible orderbook depth.")

    daily_risk_used_percent = None
    if daily_loss_amount >= 0:
        daily_risk_used_percent = (daily_loss_amount + effective_risk_amount) / risk_adjustment.account_equity * 100
        if _limit_enabled(settings.max_daily_loss_percent) and daily_risk_used_percent > settings.max_daily_loss_percent:
            blockers.append("Daily loss limit would be exceeded.")

    max_open_risk_percent = (
        settings.futures_max_open_risk_percent
        if risk_adjustment.instrument_type == "futures"
        else settings.max_open_risk_percent
    )
    open_risk_used_percent = None
    if open_risk_amount >= 0:
        open_risk_used_percent = (open_risk_amount + effective_risk_amount) / risk_adjustment.account_equity * 100
        if _limit_enabled(max_open_risk_percent) and open_risk_used_percent > max_open_risk_percent:
            blockers.append("Max open risk would be exceeded.")

    correlated_risk_used_percent = None
    if correlation_group is not None and correlated_open_risk_amount >= 0:
        correlated_risk_used_percent = (
            (correlated_open_risk_amount + effective_risk_amount)
            / risk_adjustment.account_equity
            * 100
        )
        if (
            _limit_enabled(settings.max_correlated_risk_percent)
            and correlated_risk_used_percent > settings.max_correlated_risk_percent
        ):
            blockers.append("Max correlated risk would be exceeded.")

    if futures_risk_plan is not None:
        if futures_risk_plan.status == "blocked":
            blockers.append(futures_risk_plan.message)
        elif futures_risk_plan.status == "unknown":
            if (
                execution_mode == "real"
                and risk_adjustment.instrument_type == "futures"
                and _futures_liquidation_buffer_required(settings)
            ):
                blockers.append(futures_risk_plan.message)
            else:
                warnings.append(futures_risk_plan.message)

    return RiskCheckResult(
        status="failed" if blockers else ("warning" if warnings else "passed"),
        blockers=blockers,
        warnings=warnings,
        rr=rr,
        min_rr_ratio=settings.min_rr_ratio,
        account_equity=risk_adjustment.account_equity,
        adjusted_risk_amount=risk_adjustment.adjusted_risk_amount,
        adjusted_risk_percent=risk_adjustment.adjusted_risk_percent,
        effective_risk_amount=effective_risk_amount,
        position_notional=position_sizing.notional,
        position_size_base=position_sizing.position_size_base,
        required_margin=position_sizing.required_margin,
        available_balance=available_balance,
        close_only=close_only,
        real_entries_allowed=real_entries_allowed,
        virtual_entries_allowed=virtual_entries_allowed,
        reduce_only_allowed=reduce_only_allowed,
        protective_orders_allowed=protective_orders_allowed,
        daily_risk_used_percent=daily_risk_used_percent,
        max_daily_loss_percent=settings.max_daily_loss_percent,
        account_drawdown_percent=account_drawdown_percent,
        max_account_drawdown_percent=(
            settings.max_account_drawdown_percent
            if max_account_drawdown_percent is None
            else max_account_drawdown_percent
        ),
        open_risk_used_percent=open_risk_used_percent,
        max_open_risk_percent=max_open_risk_percent,
        correlated_risk_used_percent=correlated_risk_used_percent,
        max_correlated_risk_percent=settings.max_correlated_risk_percent,
        protection_state=protection_state,
        exchange_rule_status=exchange_rule_status,
        exchange_rule_age_seconds=exchange_rule_age_seconds,
        exchange_rule_ttl_seconds=exchange_rule_ttl_seconds,
        market_data_status=market_data_status,
        best_bid=best_bid,
        best_ask=best_ask,
        mark_price=mark_price,
        funding_rate=funding_rate,
        funding_buffer_amount=position_sizing.position_size_base * position_sizing.funding_buffer_per_unit,
        fee_rate_source=fee_rate_source,
        maker_fee_rate=maker_fee_rate,
        taker_fee_rate=taker_fee_rate,
        spread_percent=spread_percent,
        spread_bps=spread_bps,
        max_spread_bps=settings.max_spread_bps,
        slippage_bps=position_sizing.slippage_bps,
        max_slippage_bps=settings.max_slippage_bps,
        price_deviation_bps=price_deviation_bps,
        max_price_deviation_bps=settings.max_price_deviation_bps,
        orderbook_depth_usd=orderbook_depth_usd,
        orderbook_can_fill=orderbook_can_fill,
        orderbook_liquidity_ratio=orderbook_liquidity_ratio,
        max_orderbook_liquidity_ratio=settings.max_orderbook_liquidity_ratio,
    )


def calculate_stop_loss_plan(
    *,
    entry_price: float,
    side: str,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
    signal_stop_loss_price: float | None = None,
    atr_value: float | None = None,
    structure_stop_loss_price: float | None = None,
) -> StopLossPlan:
    settings = _settings_model(risk_settings)
    _validate_side_and_entry(side, entry_price)
    if signal_stop_loss_price is not None and signal_stop_loss_price <= 0:
        raise ValueError("signal_stop_loss_price must be greater than zero")
    if structure_stop_loss_price is not None and structure_stop_loss_price <= 0:
        raise ValueError("structure_stop_loss_price must be greater than zero")
    if atr_value is not None and atr_value <= 0:
        raise ValueError("atr_value must be greater than zero")

    warnings: list[str] = []
    source = settings.stop_loss_mode
    if settings.stop_loss_mode == "fixed_percent":
        stop_loss_price = _fixed_percent_stop(
            entry_price=entry_price,
            side=side,
            percent=settings.default_stop_loss_percent,
        )
    elif settings.stop_loss_mode == "atr":
        if atr_value is not None:
            distance = atr_value * settings.atr_multiplier
            stop_loss_price = entry_price - distance if side == "long" else entry_price + distance
        elif signal_stop_loss_price is not None and _stop_matches_side(
            entry_price,
            signal_stop_loss_price,
            side,
        ):
            stop_loss_price = signal_stop_loss_price
            source = "signal_stop_loss_fallback"
            warnings.append("ATR value is unavailable; using the signal stop-loss.")
        else:
            stop_loss_price = _fixed_percent_stop(
                entry_price=entry_price,
                side=side,
                percent=settings.default_stop_loss_percent,
            )
            source = "fixed_percent_fallback"
            warnings.append("ATR value is unavailable; using the fixed-percent fallback.")
    else:
        candidate = structure_stop_loss_price or signal_stop_loss_price
        if candidate is not None and _stop_matches_side(entry_price, candidate, side):
            stop_loss_price = candidate
        else:
            stop_loss_price = _fixed_percent_stop(
                entry_price=entry_price,
                side=side,
                percent=settings.default_stop_loss_percent,
            )
            source = "fixed_percent_fallback"
            warnings.append(
                "Structure stop source is unavailable; using the fixed-percent fallback."
            )

    if stop_loss_price <= 0:
        raise ValueError("calculated stop_loss_price must be greater than zero")
    if not _stop_matches_side(entry_price, stop_loss_price, side):
        raise ValueError("calculated stop_loss_price must be on the opposite side of entry")

    return StopLossPlan(
        side=side,
        mode=settings.stop_loss_mode,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        risk_per_unit=abs(entry_price - stop_loss_price),
        source=source,
        default_stop_loss_percent=settings.default_stop_loss_percent,
        atr_period=settings.atr_period,
        atr_multiplier=settings.atr_multiplier,
        atr_value=atr_value,
        warnings=warnings,
    )


def calculate_take_profit_plan(
    *,
    entry_price: float,
    stop_loss_price: float,
    side: str,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
) -> TakeProfitPlan:
    settings = _settings_model(risk_settings)
    _validate_side_and_entry(side, entry_price)
    if stop_loss_price <= 0:
        raise ValueError("stop_loss_price must be greater than zero")
    if not _stop_matches_side(entry_price, stop_loss_price, side):
        raise ValueError("stop_loss_price must be on the opposite side of entry")

    risk_per_unit = abs(entry_price - stop_loss_price)
    targets = [
        _take_profit_target(
            label="TP1",
            r_multiple=settings.tp1_r_multiple,
            entry_price=entry_price,
            risk_per_unit=risk_per_unit,
            side=side,
            close_percent=settings.tp1_close_percent,
            action="move_stop_to_breakeven",
            partial_enabled=settings.partial_take_profit_enabled,
        ),
        _take_profit_target(
            label="TP2",
            r_multiple=settings.tp2_r_multiple,
            entry_price=entry_price,
            risk_per_unit=risk_per_unit,
            side=side,
            close_percent=settings.tp2_close_percent,
            action="trailing_stop",
            partial_enabled=settings.partial_take_profit_enabled,
        ),
        _take_profit_target(
            label="TP3",
            r_multiple=settings.tp3_r_multiple,
            entry_price=entry_price,
            risk_per_unit=risk_per_unit,
            side=side,
            close_percent=settings.tp3_close_percent,
            action="full_close",
            partial_enabled=settings.partial_take_profit_enabled,
        ),
    ]
    return TakeProfitPlan(
        mode=settings.take_profit_mode,
        side=side,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        risk_per_unit=risk_per_unit,
        partial_take_profit_enabled=settings.partial_take_profit_enabled,
        targets=targets,
        source="risk_settings",
        selected_rr=targets[-1].r_multiple if targets else None,
        selected_rr_target="final",
    )


def calculate_take_profit_plan_from_trade_plan(
    *,
    trade_plan: TradePlan,
    entry_price: float,
    stop_loss_price: float,
    side: str,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
) -> TakeProfitPlan:
    settings = _settings_model(risk_settings)
    _validate_side_and_entry(side, entry_price)
    if stop_loss_price <= 0:
        raise TradePlanValidationError(["Resolved stop_loss_price must be greater than zero."])
    if not _stop_matches_side(entry_price, stop_loss_price, side):
        raise TradePlanValidationError(
            ["Resolved stop_loss_price must be on the risk side of entry."]
        )

    errors: list[str] = []
    notes = ["Take-profit plan source: signal.trade_plan."]
    _validate_trade_plan_stop(
        trade_plan=trade_plan,
        entry_price=entry_price,
        side=side,
        errors=errors,
    )

    risk_per_unit = abs(entry_price - stop_loss_price)
    targets: list[TakeProfitTarget] = []
    total_close_percent = 0.0
    for target in trade_plan.targets:
        label = _trade_plan_target_label(target, errors)
        if label is None:
            continue
        if target.price is None:
            if _is_unpriced_runner_target(target):
                notes.append(
                    f"TradePlan target {label} has no fixed price; risk gate skipped it."
                )
                continue
            errors.append(f"TradePlan target {label} price is required.")
            continue
        if target.price <= 0:
            errors.append(f"TradePlan target {label} price must be greater than zero.")
            continue
        if not _target_matches_side(entry_price, target.price, side):
            direction = "above" if side == "long" else "below"
            errors.append(
                f"TradePlan target {label} must be {direction} entry for {side} trades."
            )
            continue

        close_percent = _trade_plan_close_percent(
            target=target,
            label=label,
            settings=settings,
            used_close_percent=total_close_percent,
            errors=errors,
        )
        if close_percent is None:
            continue
        if close_percent <= 0:
            errors.append(f"TradePlan target {label} close_percent must be greater than zero.")
            continue

        total_close_percent += close_percent
        reward_per_unit = _target_reward_per_unit(
            entry_price=entry_price,
            target_price=target.price,
            side=side,
        )
        targets.append(
            TakeProfitTarget(
                label=label,
                r_multiple=reward_per_unit / risk_per_unit,
                price=target.price,
                close_percent=close_percent,
                action=_trade_plan_take_profit_action(target, label),
            )
        )

    if total_close_percent > 100.0 + 0.000001:
        errors.append("TradePlan close_percent total must not exceed 100.")
    if not targets:
        errors.append("TradePlan must include at least one executable take-profit target.")

    selected_rr_target = trade_plan.risk_rules.selected_rr_target
    selected_target = _selected_take_profit_target(
        targets=targets,
        selected_rr_target=selected_rr_target,
        errors=errors,
    )
    if errors:
        raise TradePlanValidationError(_dedupe(errors))

    resolved_selected_rr_target = selected_rr_target or "final"
    if selected_target is not None:
        notes.append(
            f"TradePlan selected_rr_target={resolved_selected_rr_target} resolved "
            f"to {selected_target.label} at {selected_target.r_multiple:.4f}R."
        )
    return TakeProfitPlan(
        mode=settings.take_profit_mode,
        side=side,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        risk_per_unit=risk_per_unit,
        partial_take_profit_enabled=settings.partial_take_profit_enabled,
        targets=targets,
        source="trade_plan",
        selected_rr=selected_target.r_multiple if selected_target is not None else None,
        selected_rr_target=resolved_selected_rr_target,
        notes=notes,
    )


def calculate_breakeven_plan(
    *,
    entry_price: float,
    stop_loss_price: float,
    side: str,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
) -> BreakevenPlan:
    settings = _settings_model(risk_settings)
    _validate_side_and_entry(side, entry_price)
    if stop_loss_price <= 0:
        raise ValueError("stop_loss_price must be greater than zero")
    if not _stop_matches_side(entry_price, stop_loss_price, side):
        raise ValueError("stop_loss_price must be on the opposite side of entry")

    risk_per_unit = abs(entry_price - stop_loss_price)
    trigger_distance = risk_per_unit * settings.move_sl_to_breakeven_after_r
    offset = entry_price * settings.breakeven_offset_percent / 100
    if side == "long":
        trigger_price = entry_price + trigger_distance
        breakeven_stop_price = entry_price + offset
    else:
        trigger_price = entry_price - trigger_distance
        breakeven_stop_price = entry_price - offset
    if trigger_price <= 0 or breakeven_stop_price <= 0:
        raise ValueError("calculated breakeven prices must be greater than zero")

    return BreakevenPlan(
        side=side,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        risk_per_unit=risk_per_unit,
        move_after_r=settings.move_sl_to_breakeven_after_r,
        trigger_price=trigger_price,
        breakeven_stop_price=breakeven_stop_price,
        offset_percent=settings.breakeven_offset_percent,
    )


def calculate_trailing_stop_plan(
    *,
    entry_price: float,
    side: str,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
    current_price: float | None = None,
    atr_value: float | None = None,
    structure_stop_price: float | None = None,
) -> TrailingStopPlan:
    settings = _settings_model(risk_settings)
    _validate_side_and_entry(side, entry_price)
    price = current_price or entry_price
    if price <= 0:
        raise ValueError("current_price must be greater than zero")
    if atr_value is not None and atr_value <= 0:
        raise ValueError("atr_value must be greater than zero")
    if structure_stop_price is not None and structure_stop_price <= 0:
        raise ValueError("structure_stop_price must be greater than zero")

    warnings: list[str] = []
    trailing_distance: float | None = None
    trailing_stop_price: float | None = None
    source = settings.trailing_mode

    if not settings.trailing_stop_enabled:
        return TrailingStopPlan(
            side=side,
            enabled=False,
            mode=settings.trailing_mode,
            entry_price=entry_price,
            current_price=price,
            trailing_distance=None,
            trailing_stop_price=None,
            trailing_percent=settings.trailing_stop_percent,
            atr_multiplier=settings.trailing_atr_multiplier,
            atr_value=atr_value,
            structure_stop_price=structure_stop_price,
            source="disabled",
            warnings=[],
        )

    if settings.trailing_mode == "atr":
        if atr_value is not None:
            trailing_distance = atr_value * settings.trailing_atr_multiplier
        else:
            trailing_distance = price * settings.trailing_stop_percent / 100
            source = "percent_fallback"
            warnings.append("ATR value is unavailable; using trailing percent fallback.")
    elif settings.trailing_mode == "percent":
        trailing_distance = price * settings.trailing_stop_percent / 100
    else:
        if structure_stop_price is not None and _stop_matches_side(price, structure_stop_price, side):
            trailing_stop_price = structure_stop_price
        else:
            trailing_distance = price * settings.trailing_stop_percent / 100
            source = "percent_fallback"
            warnings.append("Structure trailing source is unavailable; using trailing percent fallback.")

    if trailing_stop_price is None and trailing_distance is not None:
        trailing_stop_price = price - trailing_distance if side == "long" else price + trailing_distance
    if trailing_stop_price is not None and trailing_stop_price <= 0:
        raise ValueError("calculated trailing_stop_price must be greater than zero")

    return TrailingStopPlan(
        side=side,
        enabled=True,
        mode=settings.trailing_mode,
        entry_price=entry_price,
        current_price=price,
        trailing_distance=trailing_distance,
        trailing_stop_price=trailing_stop_price,
        trailing_percent=settings.trailing_stop_percent,
        atr_multiplier=settings.trailing_atr_multiplier,
        atr_value=atr_value,
        structure_stop_price=structure_stop_price,
        source=source,
        warnings=warnings,
    )


def calculate_futures_risk_plan(
    *,
    entry_price: float,
    stop_loss_price: float,
    side: str,
    leverage: int,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
    liquidation_price: float | None = None,
) -> FuturesRiskPlan:
    settings = _settings_model(risk_settings)
    _validate_side_and_entry(side, entry_price)
    if stop_loss_price <= 0:
        raise ValueError("stop_loss_price must be greater than zero")
    if leverage < 1:
        raise ValueError("leverage must be greater than or equal to 1")
    if liquidation_price is not None and liquidation_price <= 0:
        raise ValueError("liquidation_price must be greater than zero")

    warnings: list[str] = []
    effective_max_leverage = min(settings.max_leverage, settings.futures_max_leverage)
    leverage_allowed = leverage <= effective_max_leverage
    if not leverage_allowed:
        return FuturesRiskPlan(
            side=side,
            status="blocked",
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            leverage=leverage,
            max_leverage=effective_max_leverage,
            leverage_allowed=False,
            liquidation_price=liquidation_price,
            liquidation_buffer_percent=None,
            min_liquidation_buffer_percent=settings.min_liquidation_buffer_percent,
            liquidation_before_stop=None,
            message=f"Requested leverage {leverage}x exceeds max leverage {effective_max_leverage}x.",
            warnings=warnings,
        )

    if liquidation_price is None:
        return FuturesRiskPlan(
            side=side,
            status="unknown",
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            leverage=leverage,
            max_leverage=effective_max_leverage,
            leverage_allowed=True,
            liquidation_price=None,
            liquidation_buffer_percent=None,
            min_liquidation_buffer_percent=settings.min_liquidation_buffer_percent,
            liquidation_before_stop=None,
            message="Liquidation price is unavailable; exact futures liquidation risk is not checked.",
            warnings=["Liquidation price is unavailable."],
        )

    if side == "long":
        liquidation_before_stop = liquidation_price >= stop_loss_price
        liquidation_buffer_percent = max(stop_loss_price - liquidation_price, 0.0) / entry_price * 100
    else:
        liquidation_before_stop = liquidation_price <= stop_loss_price
        liquidation_buffer_percent = max(liquidation_price - stop_loss_price, 0.0) / entry_price * 100

    if liquidation_before_stop:
        return FuturesRiskPlan(
            side=side,
            status="blocked",
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            leverage=leverage,
            max_leverage=effective_max_leverage,
            leverage_allowed=True,
            liquidation_price=liquidation_price,
            liquidation_buffer_percent=liquidation_buffer_percent,
            min_liquidation_buffer_percent=settings.min_liquidation_buffer_percent,
            liquidation_before_stop=True,
            message="Trade is unsafe: liquidation may happen before stop-loss.",
            warnings=warnings,
        )

    if (
        _limit_enabled(settings.min_liquidation_buffer_percent)
        and liquidation_buffer_percent < settings.min_liquidation_buffer_percent
    ):
        return FuturesRiskPlan(
            side=side,
            status="blocked",
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            leverage=leverage,
            max_leverage=effective_max_leverage,
            leverage_allowed=True,
            liquidation_price=liquidation_price,
            liquidation_buffer_percent=liquidation_buffer_percent,
            min_liquidation_buffer_percent=settings.min_liquidation_buffer_percent,
            liquidation_before_stop=False,
            message="Trade is unsafe: liquidation buffer is below the configured minimum.",
            warnings=warnings,
        )

    return FuturesRiskPlan(
        side=side,
        status="passed",
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        leverage=leverage,
        max_leverage=effective_max_leverage,
        leverage_allowed=True,
        liquidation_price=liquidation_price,
        liquidation_buffer_percent=liquidation_buffer_percent,
        min_liquidation_buffer_percent=settings.min_liquidation_buffer_percent,
        liquidation_before_stop=False,
        message="Futures leverage and liquidation buffer checks passed.",
        warnings=warnings,
    )


def calculate_position_sizing(
    *,
    account_equity: float,
    risk_settings: RiskManagementSettings | Mapping[str, Any],
    entry_price: float,
    stop_loss_price: float,
    side: str,
    leverage: int = 1,
    fee_rate: float = 0.0,
    slippage_bps: float = 0.0,
    funding_buffer_per_unit: float = 0.0,
    risk_per_trade_percent: float | None = None,
) -> PositionSizingResult:
    settings = _settings_model(risk_settings)
    _validate_side_and_entry(side, entry_price)
    if account_equity <= 0:
        raise ValueError("account_equity must be greater than zero")
    if stop_loss_price <= 0:
        raise ValueError("stop_loss_price must be greater than zero")
    if leverage < 1:
        raise ValueError("leverage must be greater than or equal to 1")
    if fee_rate < 0:
        raise ValueError("fee_rate must be greater than or equal to zero")
    if slippage_bps < 0:
        raise ValueError("slippage_bps must be greater than or equal to zero")
    if funding_buffer_per_unit < 0:
        raise ValueError("funding_buffer_per_unit must be greater than or equal to zero")
    if risk_per_trade_percent is not None and risk_per_trade_percent < 0:
        raise ValueError("risk_per_trade_percent must be greater than or equal to zero")

    stop_distance_per_unit = abs(entry_price - stop_loss_price)
    if stop_distance_per_unit <= 0:
        raise ValueError("entry_price and stop_loss_price must be different")

    include_fees = settings.include_fees_in_risk
    include_slippage = settings.include_slippage_in_risk
    effective_risk_percent = (
        settings.risk_per_trade_percent
        if risk_per_trade_percent is None
        else risk_per_trade_percent
    )
    risk_amount = account_equity * effective_risk_percent / 100
    estimated_entry_fee_per_unit = entry_price * fee_rate if include_fees else 0.0
    estimated_exit_fee_per_unit = stop_loss_price * fee_rate if include_fees else 0.0
    slippage_buffer_per_unit = (
        (entry_price + stop_loss_price) * slippage_bps / 10_000
        if include_slippage
        else 0.0
    )
    effective_risk_per_unit = (
        stop_distance_per_unit
        + estimated_entry_fee_per_unit
        + estimated_exit_fee_per_unit
        + slippage_buffer_per_unit
        + funding_buffer_per_unit
    )
    if effective_risk_per_unit <= 0:
        raise ValueError("effective_risk_per_unit must be greater than zero")

    position_size_base = risk_amount / effective_risk_per_unit
    notional = position_size_base * entry_price
    return PositionSizingResult(
        side=side,
        account_equity=account_equity,
        risk_per_trade_percent=effective_risk_percent,
        risk_amount=risk_amount,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        stop_distance_per_unit=stop_distance_per_unit,
        estimated_entry_fee_per_unit=estimated_entry_fee_per_unit,
        estimated_exit_fee_per_unit=estimated_exit_fee_per_unit,
        slippage_buffer_per_unit=slippage_buffer_per_unit,
        funding_buffer_per_unit=funding_buffer_per_unit,
        effective_risk_per_unit=effective_risk_per_unit,
        position_size_base=position_size_base,
        notional=notional,
        leverage=leverage,
        required_margin=notional / leverage,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        include_fees_in_risk=include_fees,
        include_slippage_in_risk=include_slippage,
    )


def position_sizing_for_notional(
    sizing: PositionSizingResult,
    *,
    notional: float,
    entry_price: float,
    leverage: int,
) -> PositionSizingResult:
    if notional < 0:
        raise ValueError("notional must be greater than or equal to zero")
    if entry_price <= 0:
        raise ValueError("entry_price must be greater than zero")
    if leverage < 1:
        raise ValueError("leverage must be greater than or equal to 1")

    position_size_base = notional / entry_price
    effective_risk_amount = position_size_base * sizing.effective_risk_per_unit
    risk_percent = effective_risk_amount / sizing.account_equity * 100
    return sizing.model_copy(
        update={
            "risk_per_trade_percent": risk_percent,
            "risk_amount": effective_risk_amount,
            "notional": notional,
            "position_size_base": position_size_base,
            "required_margin": notional / leverage,
        }
    )


def _settings_model(risk_settings: RiskManagementSettings | Mapping[str, Any]) -> RiskManagementSettings:
    return (
        risk_settings
        if isinstance(risk_settings, RiskManagementSettings)
        else RiskManagementSettings.model_validate(risk_settings)
    )


def _limit_enabled(value: float | int | None) -> bool:
    return value is not None and float(value) > 0


def _base_risk_percent(settings: RiskManagementSettings, instrument_type: TradeInstrumentType) -> float:
    if instrument_type == "spot":
        return settings.spot_risk_per_trade_percent
    if instrument_type == "futures":
        return settings.futures_risk_per_trade_percent
    if settings.virtual_risk_mode == "custom":
        return settings.virtual_risk_per_trade_percent
    return settings.risk_per_trade_percent


def _strategy_risk_multiplier(settings: RiskManagementSettings, strategy_key: str) -> float:
    exact_multiplier = _multiplier_for_key(settings.strategy_risk_multipliers, strategy_key)
    if exact_multiplier is not None:
        return exact_multiplier

    alias_key = _STRATEGY_RISK_ALIAS_FALLBACKS.get(strategy_key)
    if alias_key is None:
        return 1.0
    alias_multiplier = _multiplier_for_key(settings.strategy_risk_multipliers, alias_key)
    return 1.0 if alias_multiplier is None else alias_multiplier


def _multiplier_for_key(multipliers: Mapping[str, float], strategy_key: str) -> float | None:
    if strategy_key in multipliers:
        return multipliers[strategy_key]
    for raw_key, multiplier in multipliers.items():
        if _normalize_strategy_key(raw_key) == strategy_key:
            return multiplier
    return None


def _strategy_key(strategy: str) -> str:
    value = _normalize_strategy_key(strategy)
    if value == "trend_pullback":
        return "trend_following"
    return value


def _normalize_strategy_key(strategy: str) -> str:
    value = strategy.strip().lower().replace("-", "_").replace(" ", "_")
    return value or "unknown"


def _futures_liquidation_buffer_required(settings: RiskManagementSettings) -> bool:
    return (
        settings.liquidation_buffer_required
        and settings.futures_liquidation_buffer_required
        and _limit_enabled(settings.min_liquidation_buffer_percent)
    )


def _edge_gate_blockers(
    settings: RiskManagementSettings,
    signal_edge: SignalEdgeSnapshot | None,
) -> list[str]:
    if not settings.real_requires_positive_edge:
        return []
    if signal_edge is None:
        return ["Signal edge is missing; real execution requires positive historical edge."]

    blockers: list[str] = []
    if signal_edge.status == "unknown":
        blockers.append("Signal edge is unknown; real execution requires positive historical edge.")
    elif signal_edge.status == "insufficient_sample":
        blockers.append("Signal edge has insufficient sample size for real execution.")
    elif signal_edge.status != "positive":
        blockers.append("Signal edge is negative; real execution is blocked.")

    if signal_edge.sample_size < settings.edge_min_sample_size and (
        "Signal edge has insufficient sample size for real execution." not in blockers
    ):
        blockers.append("Signal edge has insufficient sample size for real execution.")

    expectancy_after_costs = signal_edge.expectancy_after_costs_r
    if (
        expectancy_after_costs is None
        or expectancy_after_costs <= settings.min_expectancy_after_costs_r
    ):
        blockers.append("Signal expectancy after costs is below the configured minimum.")
    return blockers


def _signal_score_multiplier(signal_score: float) -> tuple[float, bool, bool]:
    if signal_score >= 90:
        return 1.0, True, False
    if signal_score >= 75:
        return 0.75, True, False
    if signal_score >= 60:
        return 0.5, True, True
    return 0.0, False, True


def _validate_side_and_entry(side: str, entry_price: float) -> None:
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    if entry_price <= 0:
        raise ValueError("entry_price must be greater than zero")


def _stop_matches_side(entry_price: float, stop_loss_price: float, side: str) -> bool:
    if side == "long":
        return stop_loss_price < entry_price
    return stop_loss_price > entry_price


def _fixed_percent_stop(*, entry_price: float, side: str, percent: float) -> float:
    distance = entry_price * percent / 100
    return entry_price - distance if side == "long" else entry_price + distance


def _take_profit_target(
    *,
    label: str,
    r_multiple: float,
    entry_price: float,
    risk_per_unit: float,
    side: str,
    close_percent: float,
    action: str,
    partial_enabled: bool,
) -> TakeProfitTarget:
    distance = risk_per_unit * r_multiple
    price = entry_price + distance if side == "long" else entry_price - distance
    if price <= 0:
        raise ValueError("calculated take_profit price must be greater than zero")
    if not partial_enabled:
        close_percent = 100.0 if label == "TP3" else 0.0
        action = "full_close" if label == "TP3" else "observe"
    return TakeProfitTarget(
        label=label,
        r_multiple=r_multiple,
        price=price,
        close_percent=close_percent,
        action=action,
    )


def _validate_trade_plan_stop(
    *,
    trade_plan: TradePlan,
    entry_price: float,
    side: str,
    errors: list[str],
) -> None:
    stop_loss = trade_plan.stop_loss
    if stop_loss is None and trade_plan.invalidation is not None:
        stop_loss = trade_plan.invalidation.hard_stop or trade_plan.invalidation.price
    if stop_loss is None:
        return
    if stop_loss <= 0:
        errors.append("TradePlan stop_loss must be greater than zero.")
        return
    if not _stop_matches_side(entry_price, stop_loss, side):
        direction = "below" if side == "long" else "above"
        errors.append(f"TradePlan stop_loss must be {direction} entry for {side} trades.")


def _trade_plan_target_label(
    target: TradePlanTarget,
    errors: list[str],
) -> str | None:
    label = target.label.strip().upper()
    if label in _TAKE_PROFIT_LABELS:
        return label
    errors.append(f"TradePlan target label {target.label!r} is not supported.")
    return None


def _is_unpriced_runner_target(target: TradePlanTarget) -> bool:
    action = (target.action or "").strip().lower()
    close_percent = str(target.close_percent or "").strip().lower()
    return "runner" in action or close_percent == "runner"


def _target_matches_side(entry_price: float, target_price: float, side: str) -> bool:
    if side == "long":
        return target_price > entry_price
    return target_price < entry_price


def _target_reward_per_unit(
    *,
    entry_price: float,
    target_price: float,
    side: str,
) -> float:
    return target_price - entry_price if side == "long" else entry_price - target_price


def _trade_plan_close_percent(
    *,
    target: TradePlanTarget,
    label: str,
    settings: RiskManagementSettings,
    used_close_percent: float,
    errors: list[str],
) -> float | None:
    raw_close_percent = target.close_percent
    if raw_close_percent is None:
        return _settings_close_percent(label, settings)
    if isinstance(raw_close_percent, str):
        normalized = raw_close_percent.strip().lower()
        if normalized == "runner":
            return max(100.0 - used_close_percent, 0.0)
        try:
            return float(normalized)
        except ValueError:
            errors.append(f"TradePlan target {label} close_percent is malformed.")
            return None
    return float(raw_close_percent)


def _settings_close_percent(label: str, settings: RiskManagementSettings) -> float:
    if label == "TP1":
        return settings.tp1_close_percent
    if label == "TP2":
        return settings.tp2_close_percent
    return settings.tp3_close_percent


def _trade_plan_take_profit_action(target: TradePlanTarget, label: str) -> str:
    action = (target.action or "").strip().lower()
    if action in {"move_stop_to_breakeven", "trailing_stop", "full_close", "observe"}:
        return action
    if action == "partial_close":
        return "move_stop_to_breakeven"
    if action == "reduce_and_keep_runner":
        return "trailing_stop"
    if "trailing" in action:
        return "trailing_stop"
    if "runner" in action or label == "TP3":
        return "full_close"
    if label == "TP1":
        return "move_stop_to_breakeven"
    if label == "TP2":
        return "trailing_stop"
    return "full_close"


def _selected_take_profit_target(
    *,
    targets: list[TakeProfitTarget],
    selected_rr_target: str | None,
    errors: list[str],
) -> TakeProfitTarget | None:
    if not targets:
        return None
    if selected_rr_target is None:
        return targets[-1]

    normalized = selected_rr_target.strip().lower().replace("_", " ")
    if normalized in {"final", "planned final target"}:
        return targets[-1]
    if normalized in {"nearest", "first", "nearest target", "nearest valid target"}:
        return targets[0]

    label = selected_rr_target.strip().upper()
    if label in _TAKE_PROFIT_LABELS:
        for target in targets:
            if target.label == label:
                return target
        errors.append(f"TradePlan selected_rr_target {selected_rr_target!r} has no executable target.")
        return None

    errors.append(f"TradePlan selected_rr_target {selected_rr_target!r} is not supported.")
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


def get_user_risk_management_settings(user_id: str = "demo_user") -> RiskManagementSettings:
    from app.services.user_service import user_service

    profile = user_service.get_profile(user_id)
    return RiskManagementSettings.model_validate(profile.settings["risk_management"])
