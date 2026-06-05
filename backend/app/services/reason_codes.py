from __future__ import annotations

import re
from collections.abc import Iterable


KNOWN_REASON_CODES = {
    "account_snapshot_unavailable",
    "adapter_not_implemented",
    "available_balance_unavailable",
    "bybit_api_credentials_required",
    "cancelled_by_user",
    "daily_loss_limit_exceeded",
    "deterministic_test_fill",
    "enable_bybit_live_order_placement_false",
    "enable_bybit_mainnet_order_placement_false",
    "enable_live_trading_false",
    "entry_zone_shifted",
    "exchange_adapter_unsupported",
    "exchange_connection_exchange_mismatch",
    "exchange_connection_forbidden",
    "exchange_connection_inactive",
    "exchange_connection_not_found",
    "exchange_connection_required",
    "exchange_credentials_unavailable",
    "exchange_rules_missing",
    "exchange_rules_stale",
    "execution_plan_validation_failed",
    "expected_slippage_above_0_5_percent",
    "expected_slippage_above_1_5_percent",
    "filled",
    "futures_liquidation_buffer_required",
    "futures_liquidation_before_stop",
    "futures_risk_blocked",
    "futures_risk_passed",
    "insufficient_liquidity",
    "leverage_exceeds_exchange_max",
    "live_adapter_lacks_protective_guarantee",
    "live_protective_guarantee_required",
    "live_protective_stop_required",
    "live_reduce_only_required",
    "live_safety_pending",
    "live_take_profit_required",
    "low_liquidity_not_allowed",
    "low_liquidity_tier_relaxed_warning",
    "mainnet_connection_not_explicitly_enabled",
    "margin_exceeds_balance",
    "market_data_incomplete",
    "market_data_missing",
    "market_data_missing_relaxed_fallback",
    "market_data_stale",
    "market_data_stale_relaxed_fallback",
    "market_data_unavailable",
    "market_entry_price_moved_rr",
    "max_account_drawdown_exceeded",
    "max_correlated_risk_exceeded",
    "max_open_risk_exceeded",
    "no_backend_reason",
    "order_placement_disabled",
    "order_placement_dry_run",
    "orderbook_liquidity_empty",
    "orderbook_liquidity_insufficient",
    "orderbook_missing_relaxed_fallback",
    "orderbook_unavailable",
    "orderbook_vwap_slippage_above_max",
    "partial_filled",
    "partially_filled",
    "pending_entry_expired_before_touch",
    "pending_entry_live_signal_changed_no_material_impact",
    "pending_entry_material_change_requires_review",
    "pending_entry_reconfirmed",
    "pending_entry_signal_missing",
    "pending_real_trigger_not_enabled",
    "position_above_10_percent_volume_5m",
    "position_above_20_percent_depth_0_5",
    "position_above_30_percent_volume_5m",
    "position_above_50_percent_depth_1",
    "position_notional_below_exchange_min",
    "position_size_above_exchange_max",
    "position_size_below_exchange_min",
    "price_moved_from_signal_entry",
    "protective_stop_required",
    "real_entries_disabled",
    "real_execution_dry_run",
    "real_execution_failed",
    "real_execution_partially_filled",
    "real_execution_submitted",
    "real_pending_not_implemented",
    "readiness_failed",
    "reduce_only_required",
    "requested_notional_above_safe_size",
    "risk_gate_blocked",
    "risk_profile_restricted",
    "risk_reward_below_minimum",
    "risk_reward_soft_warning",
    "slippage_above_configured_max",
    "spread_above_0_3_percent",
    "spread_above_1_percent_market_order_blocked",
    "spread_above_configured_max",
    "stop_loss_shifted",
    "take_profit_required",
    "take_profit_targets_shifted",
    "ticker_bid_ask_unavailable",
    "trade_plan_reconfirmation_required",
    "triggered_pending_entry_missing_before_fill",
    "virtual_entries_disabled",
}

_REASON_ALIASES = {
    "account drawdown limit is exceeded": "max_account_drawdown_exceeded",
    "available balance is unavailable": "available_balance_unavailable",
    "calculated position would consume more than half of visible orderbook depth": "position_above_50_percent_depth_1",
    "daily loss limit would be exceeded": "daily_loss_limit_exceeded",
    "futures liquidation buffer is required": "futures_liquidation_buffer_required",
    "futures liquidation would occur before stop-loss": "futures_liquidation_before_stop",
    "max correlated risk would be exceeded": "max_correlated_risk_exceeded",
    "max open risk would be exceeded": "max_open_risk_exceeded",
    "orderbook depth cannot fill calculated position size": "orderbook_liquidity_insufficient",
    "orderbook liquidity is empty for the entry side": "orderbook_liquidity_empty",
    "orderbook liquidity is insufficient for calculated position size": "orderbook_liquidity_insufficient",
    "orderbook liquidity is unavailable": "orderbook_unavailable",
    "pending entry intent expired before entry touch": "pending_entry_expired_before_touch",
    "pending entry signal is missing": "pending_entry_signal_missing",
    "real entries are disabled by the active risk protection state": "real_entries_disabled",
    "required margin exceeds available balance": "margin_exceeds_balance",
    "risk-reward ratio is below the configured minimum": "risk_reward_below_minimum",
    "risk-reward ratio is below the soft warning threshold": "risk_reward_soft_warning",
    "spot position size exceeds the configured maximum": "position_size_above_exchange_max",
    "take-profit plan is required": "take_profit_required",
    "virtual entries are disabled by the active risk protection state": "virtual_entries_disabled",
}


def normalize_reason_code(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    canonical = _slug(text)
    if canonical in KNOWN_REASON_CODES:
        return canonical
    alias_key = re.sub(r"\s+", " ", text).strip().rstrip(".").lower()
    if alias_key.startswith("signal is terminal at trigger time"):
        return "signal_terminal_at_trigger"
    return _REASON_ALIASES.get(alias_key)


def normalize_reason_codes(values: Iterable[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in _split_reason_value(value):
            code = normalize_reason_code(part)
            if code is None or code in seen:
                continue
            seen.add(code)
            result.append(code)
    return result


def _split_reason_value(value: str | None) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r";\s*", text) if part.strip()]


def _slug(value: str) -> str:
    return re.sub(r"(^_+|_+$)", "", re.sub(r"[^A-Za-z0-9]+", "_", value).lower())
