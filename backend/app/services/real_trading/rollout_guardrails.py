from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.config import settings


RealTradingRolloutMode = Literal[
    "disabled",
    "dry_run_orders",
    "testnet_real_orders",
    "mainnet_small_size",
    "mainnet_scaled",
]
RealTradingOrderPlacementMode = Literal[
    "disabled",
    "dry_run",
    "dry_run_orders",
    "testnet_real_orders",
    "mainnet_small_size",
    "mainnet_scaled",
    "live",
]

REAL_TRADING_ROLLOUT_MODES: set[str] = {
    "disabled",
    "dry_run_orders",
    "testnet_real_orders",
    "mainnet_small_size",
    "mainnet_scaled",
}
ORDER_PLACEMENT_MODES: set[str] = {
    "disabled",
    "dry_run",
    "dry_run_orders",
    "testnet_real_orders",
    "mainnet_small_size",
    "mainnet_scaled",
    "live",
}
MAINNET_MODES = {"mainnet_small_size", "mainnet_scaled"}
DRY_RUN_MODES = {"dry_run", "dry_run_orders"}

REAL_TRADING_MODE_DISABLED_REASON_CODE = "real_trading_mode_disabled"
REAL_TRADING_DRY_RUN_ONLY_REASON_CODE = "real_trading_dry_run_only"
REAL_TRADING_TESTNET_ONLY_REASON_CODE = "real_trading_testnet_only"
REAL_TRADING_MODE_MISMATCH_REASON_CODE = "real_trading_mode_mismatch"
MAINNET_PROTECTIVE_STOP_REQUIRED_REASON_CODE = "mainnet_protective_stop_required"
MAINNET_KILL_SWITCH_NOT_HEALTHY_REASON_CODE = "mainnet_kill_switch_not_healthy"
MAINNET_PORTFOLIO_RISK_BLOCKED_REASON_CODE = "mainnet_portfolio_risk_blocked"
MAINNET_CALIBRATION_NOT_POSITIVE_REASON_CODE = "mainnet_calibration_not_positive"
MAINNET_SIZE_CAP_EXCEEDED_REASON_CODE = "mainnet_size_cap_exceeded"


@dataclass(frozen=True)
class RealTradingRolloutContext:
    environment: Literal["testnet", "mainnet"] | None
    order_placement_mode: str | None
    adapter_is_dry_run: bool
    requested_notional: float | None
    has_protective_stop: bool
    kill_switch_state: str | None
    portfolio_risk_passed: bool
    edge_status: str | None
    explicit_unlock: bool


@dataclass(frozen=True)
class RealTradingRolloutDecision:
    allowed: bool
    mode: RealTradingRolloutMode
    reason_codes: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RealTradingRolloutGuard:
    """Staged real-order rollout contract.

    This gate is deliberately separate from exchange adapters. Adapters still
    protect HTTP boundaries, while this service decides whether a real-order
    intent is allowed for the configured rollout stage.
    """

    def __init__(self, settings_obj: Any = settings) -> None:
        self._settings = settings_obj

    def evaluate(self, context: RealTradingRolloutContext) -> RealTradingRolloutDecision:
        mode = _real_trading_mode(self._settings)
        blockers: list[str] = []
        reason_codes: list[str] = []
        warnings: list[str] = []

        if context.adapter_is_dry_run:
            return RealTradingRolloutDecision(
                allowed=True,
                mode=mode,
                warnings=[],
                metadata=_metadata(mode, context),
            )

        if mode == "disabled":
            _add(
                reason_codes,
                blockers,
                REAL_TRADING_MODE_DISABLED_REASON_CODE,
                "Real trading rollout mode is disabled.",
            )
        elif mode == "dry_run_orders":
            _add(
                reason_codes,
                blockers,
                REAL_TRADING_DRY_RUN_ONLY_REASON_CODE,
                "Real trading rollout mode only permits dry-run order intents.",
            )
        elif mode == "testnet_real_orders":
            if context.environment != "testnet":
                _add(
                    reason_codes,
                    blockers,
                    REAL_TRADING_TESTNET_ONLY_REASON_CODE,
                    "Real trading rollout mode only permits testnet real orders.",
                )
            elif not _mode_matches(context.order_placement_mode, mode, context.environment):
                _add(
                    reason_codes,
                    blockers,
                    REAL_TRADING_MODE_MISMATCH_REASON_CODE,
                    "Exchange connection order mode does not match testnet real-order rollout.",
                )
        elif mode in MAINNET_MODES:
            if context.environment != "mainnet":
                _add(
                    reason_codes,
                    blockers,
                    REAL_TRADING_MODE_MISMATCH_REASON_CODE,
                    "Mainnet rollout mode requires a mainnet exchange connection.",
                )
            if not _mode_matches(context.order_placement_mode, mode, context.environment):
                _add(
                    reason_codes,
                    blockers,
                    REAL_TRADING_MODE_MISMATCH_REASON_CODE,
                    "Exchange connection order mode does not match configured mainnet rollout.",
                )
            if not _explicit_unlock(self._settings, context):
                _add(
                    reason_codes,
                    blockers,
                    "real_trading_unlock_required",
                    "Mainnet real trading requires explicit rollout unlock.",
                )
            if not context.has_protective_stop:
                _add(
                    reason_codes,
                    blockers,
                    MAINNET_PROTECTIVE_STOP_REQUIRED_REASON_CODE,
                    "Mainnet entry requires a protective stop before placement.",
                )
            if context.kill_switch_state != "healthy":
                _add(
                    reason_codes,
                    blockers,
                    MAINNET_KILL_SWITCH_NOT_HEALTHY_REASON_CODE,
                    "Mainnet entry requires a healthy kill-switch state.",
                )
            if not context.portfolio_risk_passed:
                _add(
                    reason_codes,
                    blockers,
                    MAINNET_PORTFOLIO_RISK_BLOCKED_REASON_CODE,
                    "Mainnet entry requires portfolio risk to pass.",
                )
            if context.edge_status != "positive":
                _add(
                    reason_codes,
                    blockers,
                    MAINNET_CALIBRATION_NOT_POSITIVE_REASON_CODE,
                    "Mainnet entry requires positive published calibration.",
                )
            if mode == "mainnet_small_size" and _exceeds_small_size_cap(self._settings, context.requested_notional):
                _add(
                    reason_codes,
                    blockers,
                    MAINNET_SIZE_CAP_EXCEEDED_REASON_CODE,
                    "Mainnet small-size rollout cap is exceeded.",
                )

        return RealTradingRolloutDecision(
            allowed=not blockers,
            mode=mode,
            reason_codes=reason_codes,
            blockers=blockers,
            warnings=warnings,
            metadata=_metadata(mode, context),
        )


def _real_trading_mode(settings_obj: Any) -> RealTradingRolloutMode:
    raw = str(getattr(settings_obj, "real_trading_mode", "") or "").strip().lower()
    if raw in REAL_TRADING_ROLLOUT_MODES:
        return raw  # type: ignore[return-value]
    return _legacy_rollout_mode(settings_obj)


def _legacy_rollout_mode(settings_obj: Any) -> RealTradingRolloutMode:
    if not _truthy_setting(settings_obj, "enable_live_trading"):
        return "disabled"
    if not _truthy_setting(settings_obj, "enable_bybit_live_order_placement"):
        return "dry_run_orders"
    if _truthy_setting(settings_obj, "enable_bybit_mainnet_order_placement"):
        return "mainnet_small_size"
    return "testnet_real_orders"


def normalize_order_placement_mode(value: str | None, *, environment: str | None = None) -> RealTradingOrderPlacementMode:
    normalized = str(value or "").strip().lower()
    if normalized in ORDER_PLACEMENT_MODES:
        return normalized  # type: ignore[return-value]
    if normalized == "live":
        return _legacy_live_mode(environment)
    return "dry_run"


def rollout_mode_for_order_placement(
    value: str | None,
    *,
    environment: str | None = None,
) -> RealTradingRolloutMode:
    mode = normalize_order_placement_mode(value, environment=environment)
    if mode == "disabled":
        return "disabled"
    if mode in DRY_RUN_MODES:
        return "dry_run_orders"
    if mode == "testnet_real_orders":
        return "testnet_real_orders"
    if mode in MAINNET_MODES:
        return mode  # type: ignore[return-value]
    return _legacy_live_mode(environment)


def _legacy_live_mode(environment: str | None) -> RealTradingRolloutMode:
    return "mainnet_small_size" if environment == "mainnet" else "testnet_real_orders"


def _mode_matches(order_mode: str | None, rollout_mode: RealTradingRolloutMode, environment: str | None) -> bool:
    normalized = normalize_order_placement_mode(order_mode, environment=environment)
    if normalized == "live":
        normalized = _legacy_live_mode(environment)
    if rollout_mode == "testnet_real_orders":
        return normalized == "testnet_real_orders"
    if rollout_mode in MAINNET_MODES:
        return normalized == rollout_mode
    if rollout_mode == "dry_run_orders":
        return normalized in DRY_RUN_MODES
    return rollout_mode == "disabled" and normalized == "disabled"


def _explicit_unlock(settings_obj: Any, context: RealTradingRolloutContext) -> bool:
    if hasattr(settings_obj, "real_trading_explicit_unlock"):
        return bool(getattr(settings_obj, "real_trading_explicit_unlock", False))
    return bool(context.explicit_unlock)


def _exceeds_small_size_cap(settings_obj: Any, requested_notional: float | None) -> bool:
    cap = float(getattr(settings_obj, "real_trading_mainnet_small_size_cap_usd", 50.0) or 0.0)
    if cap <= 0 or requested_notional is None:
        return False
    return requested_notional > cap


def _truthy_setting(settings_obj: Any, name: str) -> bool:
    value = getattr(settings_obj, name, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _add(reason_codes: list[str], blockers: list[str], code: str, message: str) -> None:
    if code not in reason_codes:
        reason_codes.append(code)
    if message not in blockers:
        blockers.append(message)


def _metadata(mode: RealTradingRolloutMode, context: RealTradingRolloutContext) -> dict[str, Any]:
    return {
        "mode": mode,
        "environment": context.environment,
        "order_placement_mode": context.order_placement_mode,
        "adapter_is_dry_run": context.adapter_is_dry_run,
        "requested_notional": context.requested_notional,
        "kill_switch_state": context.kill_switch_state,
        "edge_status": context.edge_status,
    }


real_trading_rollout_guard = RealTradingRolloutGuard()
