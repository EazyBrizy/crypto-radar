from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.schemas.signal import StrategySignal
from app.services.risk_management import resolve_rr_guard_mode


DEFAULT_MIN_RR_RATIO = 2.0
RR_TARGET_BY_STRATEGY: dict[str, str] = {
    "trend_pullback_continuation": "final",
    "volatility_squeeze_breakout": "final",
    "liquidity_sweep_reversal": "nearest",
}


@dataclass(frozen=True)
class RiskRewardAssessment:
    passed: bool
    rr: float | None
    min_rr: float
    guard_mode: str
    status: str
    meets_min_rr: bool
    blocked: bool
    warning: bool
    warning_reason: str | None
    block_reason: str | None
    target_key: str
    target_label: str
    first_target_rr: float | None
    final_target_rr: float | None
    reason: str


class RiskRewardAssessmentService:
    """Measures signal R:R without deciding the final signal status."""

    def assess(
        self,
        signal: StrategySignal,
        params: Mapping[str, Any],
        rr_guard_context: str = "discovery",
    ) -> RiskRewardAssessment:
        min_rr = _strategy_numeric_param(
            params,
            "min_rr_ratio",
            signal.strategy,
            DEFAULT_MIN_RR_RATIO,
        )
        guard_mode = resolve_rr_guard_mode(
            params,
            context=rr_guard_context,
            strategy=signal.strategy,
            strategy_risk_settings=params,
        )
        if min_rr <= 0:
            return RiskRewardAssessment(
                passed=True,
                rr=signal.risk_reward,
                min_rr=min_rr,
                guard_mode=guard_mode,
                status="skipped",
                meets_min_rr=True,
                blocked=False,
                warning=False,
                warning_reason=None,
                block_reason=None,
                target_key="disabled",
                target_label="disabled",
                first_target_rr=_target_rr(signal, signal.take_profit_1),
                final_target_rr=_target_rr(signal, signal.take_profit_2 or signal.take_profit_1),
                reason="Risk/reward guard is disabled for this strategy",
            )

        first_target_rr = _target_rr(signal, signal.take_profit_1)
        final_target_rr = _target_rr(signal, signal.take_profit_2 or signal.take_profit_1)
        rr_target = _rr_target_key(params, signal.strategy)
        if rr_target == "nearest":
            selected_rr = first_target_rr if first_target_rr is not None else final_target_rr
            target_label = "nearest target" if first_target_rr is not None else "nearest valid target"
        else:
            selected_rr = final_target_rr if final_target_rr is not None else signal.risk_reward
            target_label = "planned final target"

        if selected_rr is None:
            reason = "Risk/reward blocked: entry, stop or target is missing"
            if _has_unusable_profit_target(signal):
                reason = "Risk/reward blocked: no planned target is beyond the entry price"
            return RiskRewardAssessment(
                passed=False,
                rr=None,
                min_rr=min_rr,
                guard_mode=guard_mode,
                status="failed",
                meets_min_rr=False,
                blocked=True,
                warning=False,
                warning_reason=None,
                block_reason=reason,
                target_key=rr_target,
                target_label=target_label,
                first_target_rr=first_target_rr,
                final_target_rr=final_target_rr,
                reason=reason,
            )

        if selected_rr < min_rr:
            nearest_text = (
                "not beyond entry"
                if first_target_rr is None and signal.take_profit_1 is not None
                else "-" if first_target_rr is None else f"{first_target_rr:.2f}R"
            )
            final_text = "-" if final_target_rr is None else f"{final_target_rr:.2f}R"
            target_context = (
                f"(TP1 {nearest_text}, final {final_text})"
                if rr_target == "nearest" and first_target_rr is None and signal.take_profit_1 is not None
                else f"(nearest {nearest_text}, final {final_text})"
            )
            threshold_reason = (
                f"Risk/reward blocked: {target_label} is {selected_rr:.2f}R, "
                f"below configured minimum {min_rr:.2f}R "
                f"{target_context}"
            )
            if guard_mode == "hard":
                return RiskRewardAssessment(
                    passed=False,
                    rr=selected_rr,
                    min_rr=min_rr,
                    guard_mode=guard_mode,
                    status="failed",
                    meets_min_rr=False,
                    blocked=True,
                    warning=False,
                    warning_reason=None,
                    block_reason=threshold_reason,
                    target_key=rr_target,
                    target_label=target_label,
                    first_target_rr=first_target_rr,
                    final_target_rr=final_target_rr,
                    reason=threshold_reason,
                )
            if guard_mode == "soft":
                warning_reason = threshold_reason.replace("Risk/reward blocked:", "Risk/reward warning:", 1)
                return RiskRewardAssessment(
                    passed=True,
                    rr=selected_rr,
                    min_rr=min_rr,
                    guard_mode=guard_mode,
                    status="warning",
                    meets_min_rr=False,
                    blocked=False,
                    warning=True,
                    warning_reason=warning_reason,
                    block_reason=None,
                    target_key=rr_target,
                    target_label=target_label,
                    first_target_rr=first_target_rr,
                    final_target_rr=final_target_rr,
                    reason=warning_reason,
                )
            return RiskRewardAssessment(
                passed=True,
                rr=selected_rr,
                min_rr=min_rr,
                guard_mode=guard_mode,
                status="skipped",
                meets_min_rr=False,
                blocked=False,
                warning=False,
                warning_reason=None,
                block_reason=None,
                target_key=rr_target,
                target_label=target_label,
                first_target_rr=first_target_rr,
                final_target_rr=final_target_rr,
                reason=(
                    f"Risk/reward guard is off: {target_label} is {selected_rr:.2f}R, "
                    f"minimum for reporting is {min_rr:.2f}R {target_context}"
                ),
            )

        return RiskRewardAssessment(
            passed=True,
            rr=selected_rr,
            min_rr=min_rr,
            guard_mode=guard_mode,
            status="skipped" if guard_mode == "off" else "passed",
            meets_min_rr=True,
            blocked=False,
            warning=False,
            warning_reason=None,
            block_reason=None,
            target_key=rr_target,
            target_label=target_label,
            first_target_rr=first_target_rr,
            final_target_rr=final_target_rr,
            reason=(
                f"Risk/reward passed: {target_label} is {selected_rr:.2f}R, minimum {min_rr:.2f}R"
                if guard_mode != "off"
                else f"Risk/reward guard is off: {target_label} is {selected_rr:.2f}R"
            ),
        )


def risk_reward_metadata(risk_reward: RiskRewardAssessment) -> dict[str, Any]:
    blockers = [risk_reward.block_reason or risk_reward.reason] if risk_reward.blocked else []
    warnings = [risk_reward.warning_reason or risk_reward.reason] if risk_reward.warning else []
    return {
        "first_target_rr": risk_reward.first_target_rr,
        "final_target_rr": risk_reward.final_target_rr,
        "selected_rr": risk_reward.rr,
        "rr_value": risk_reward.rr,
        "rr_status": risk_reward.status,
        "selected_rr_target": risk_reward.target_key,
        "selected_rr_label": risk_reward.target_label,
        "min_rr_ratio": risk_reward.min_rr,
        "risk_reward_guard_mode": risk_reward.guard_mode,
        "signal_actionable": not risk_reward.blocked,
        "auto_entry_allowed": not risk_reward.blocked,
        "execution_allowed_virtual": not risk_reward.blocked,
        "execution_allowed_real": False if risk_reward.blocked else None,
        "blockers": blockers,
        "warnings": warnings,
        "blocker_codes": ["blocked_by_rr"] if risk_reward.blocked else [],
        "warning_codes": ["rr_warning"] if risk_reward.warning else [],
        "risk_reward_warning": risk_reward.warning,
        "risk_reward_warning_reason": risk_reward.warning_reason,
        "risk_reward_blocked": risk_reward.blocked,
        "risk_reward_block_reason": risk_reward.block_reason,
    }


def _rr_target_key(params: Mapping[str, Any], strategy: str) -> str:
    raw_target = str(params.get("rr_target") or RR_TARGET_BY_STRATEGY.get(strategy, "final")).strip().lower()
    if raw_target in {"first", "nearest", "tp1"}:
        return "nearest"
    return "final"


def _target_rr(signal: StrategySignal, target: float | None) -> float | None:
    entry = _entry_price(signal)
    stop = signal.stop_loss
    if entry is None or stop is None or target is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    reward = _target_reward(signal, target, entry)
    if reward <= 0:
        return None
    return round(reward / risk, 4)


def _target_reward(signal: StrategySignal, target: float, entry: float | None = None) -> float:
    entry = _entry_price(signal) if entry is None else entry
    if entry is None:
        return 0.0
    if signal.direction.lower() == "long":
        return target - entry
    return entry - target


def _has_unusable_profit_target(signal: StrategySignal) -> bool:
    entry = _entry_price(signal)
    if entry is None or signal.stop_loss is None:
        return False
    return any(
        target is not None and _target_reward(signal, target, entry) <= 0
        for target in (signal.take_profit_1, signal.take_profit_2)
    )


def _entry_price(signal: StrategySignal) -> float | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    return signal.entry_max


def _strategy_numeric_param(
    params: Mapping[str, Any],
    key: str,
    strategy: str,
    default: float,
) -> float:
    value = params.get(key)
    if isinstance(value, Mapping):
        value = value.get(strategy, value.get("default"))
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


risk_reward_assessment_service = RiskRewardAssessmentService()
