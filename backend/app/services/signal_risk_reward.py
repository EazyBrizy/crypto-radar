from __future__ import annotations

from app.schemas.signal import RadarSignal
from app.services.risk_management import normalize_rr_guard_mode


class StrategyRiskRewardBlocked(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def strategy_rr_block_reason(signal: RadarSignal, guard_mode: str = "hard") -> str | None:
    mode = normalize_rr_guard_mode(guard_mode, "hard")
    selected_rr = signal.selected_rr
    min_rr = signal.min_rr_ratio
    failed_check_reason = _failed_rr_check_reason(signal)
    if selected_rr is not None and min_rr is not None and min_rr > 0:
        if selected_rr < min_rr:
            if mode != "hard":
                return None
            return failed_check_reason or (
                f"Risk/reward blocked: {_rr_target_label(signal)} is {selected_rr:.2f}R, "
                f"below configured minimum {min_rr:.2f}R"
            )
        return None
    if failed_check_reason is None:
        return None
    return failed_check_reason if mode == "hard" or _rr_check_metadata_blocked(signal) else None


def ensure_strategy_rr_eligible(signal: RadarSignal, guard_mode: str = "hard") -> None:
    no_trade_reason = strategy_no_trade_block_reason(signal)
    if no_trade_reason is not None:
        raise StrategyRiskRewardBlocked(no_trade_reason)
    reason = strategy_rr_block_reason(signal, guard_mode=guard_mode)
    if reason is not None:
        raise StrategyRiskRewardBlocked(reason)


def strategy_no_trade_block_reason(signal: RadarSignal) -> str | None:
    result = signal.no_trade_filter
    if result is None or not result.blocked:
        return None
    return "; ".join(result.blockers) if result.blockers else "No-trade filter blocked this entry."


def _failed_rr_check_reason(signal: RadarSignal) -> str | None:
    if signal.confirmation is None:
        return None
    for check in signal.confirmation.checks:
        if check.name == "risk_reward_guard" and check.status == "failed":
            return check.reason or "Risk/reward blocked by strategy guard"
    return None


def _rr_check_metadata_blocked(signal: RadarSignal) -> bool:
    if signal.confirmation is None:
        return False
    for check in signal.confirmation.checks:
        if check.name == "risk_reward_guard":
            return check.metadata.get("risk_reward_blocked") is True
    return False


def _rr_target_label(signal: RadarSignal) -> str:
    target = (signal.selected_rr_target or "selected target").replace("_", " ")
    if target == "nearest":
        return "nearest target"
    if target == "final":
        return "planned final target"
    return target
