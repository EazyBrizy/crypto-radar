from __future__ import annotations

from app.schemas.signal import RadarSignal


def strategy_rr_block_reason(signal: RadarSignal) -> str | None:
    selected_rr = signal.selected_rr
    min_rr = signal.min_rr_ratio
    failed_check_reason = _failed_rr_check_reason(signal)
    if selected_rr is not None and min_rr is not None and min_rr > 0:
        if selected_rr < min_rr:
            return failed_check_reason or (
                f"Risk/reward blocked: {_rr_target_label(signal)} is {selected_rr:.2f}R, "
                f"below configured minimum {min_rr:.2f}R"
            )
        return None
    return failed_check_reason


def _failed_rr_check_reason(signal: RadarSignal) -> str | None:
    if signal.confirmation is None:
        return None
    for check in signal.confirmation.checks:
        if check.name == "risk_reward_guard" and check.status == "failed":
            return check.reason or "Risk/reward blocked by strategy guard"
    return None


def _rr_target_label(signal: RadarSignal) -> str:
    target = (signal.selected_rr_target or "selected target").replace("_", " ")
    if target == "nearest":
        return "nearest target"
    if target == "final":
        return "planned final target"
    return target
