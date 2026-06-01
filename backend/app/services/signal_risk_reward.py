from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal, TypeAlias, cast

from app.schemas.signal import RadarSignal, SignalLayerCheck, StrategySignal
from app.services.risk_management import normalize_rr_guard_mode

SignalLike: TypeAlias = RadarSignal | StrategySignal
RRGuardMode: TypeAlias = Literal["off", "soft", "hard"]


class StrategyRiskRewardBlocked(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def signal_no_trade_block_reason(signal: SignalLike) -> str | None:
    result = signal.no_trade_filter
    if result is not None and result.blocked:
        if result.blockers:
            return "; ".join(result.blockers)
        check_reason = _check_reason(result.checks, statuses={"failed"})
        if check_reason is not None:
            return check_reason
        metadata_reason = _metadata_string(
            result.metadata,
            "no_trade_block_reason",
            "block_reason",
            "reason",
        )
        if metadata_reason is not None:
            return metadata_reason
        return "No-trade filter blocked this entry."

    check = _confirmation_check(signal, "no_trade_filter", statuses={"failed"})
    if check is None:
        return None

    metadata = check.metadata
    metadata_blockers = _metadata_strings(metadata, "blockers")
    if metadata_blockers:
        return "; ".join(metadata_blockers)
    metadata_reason = _metadata_string(
        metadata,
        "no_trade_block_reason",
        "block_reason",
        "reason",
    )
    return metadata_reason or check.reason or "No-trade filter blocked this entry."


def signal_rr_warning_reason(
    signal: SignalLike,
    *,
    respect_guard_mode: bool = True,
) -> str | None:
    check = _confirmation_check(signal, "risk_reward_guard")
    metadata = check.metadata if check is not None else {}
    guard_mode = _metadata_string(metadata, "risk_reward_guard_mode")
    if respect_guard_mode and guard_mode is not None and _normalize_rr_guard_mode(guard_mode, "soft") == "off":
        return None

    selected_rr = _first_number(
        metadata.get("selected_rr") if isinstance(metadata, Mapping) else None,
        signal.selected_rr,
    )
    min_rr = _first_number(
        metadata.get("min_rr_ratio") if isinstance(metadata, Mapping) else None,
        signal.min_rr_ratio,
    )
    if selected_rr is not None and min_rr is not None and min_rr > 0 and selected_rr < min_rr:
        return (
            f"Risk/reward warning: {_rr_target_label(signal)} is {selected_rr:.2f}R, "
            f"below configured minimum {min_rr:.2f}R"
        )

    metadata_warning_reason = _metadata_string(metadata, "risk_reward_warning_reason")
    if metadata_warning_reason is not None:
        return _as_rr_warning_reason(metadata_warning_reason)

    metadata_block_reason = _metadata_string(metadata, "risk_reward_block_reason")
    if metadata_block_reason is not None:
        return _as_rr_warning_reason(metadata_block_reason)

    if check is not None and check.status in {"warning", "failed"}:
        return _as_rr_warning_reason(check.reason) or "Risk/reward guard reported a warning."

    return None


def ensure_signal_research_eligible(signal: SignalLike) -> None:
    reason = signal_no_trade_block_reason(signal)
    if reason:
        raise StrategyRiskRewardBlocked(reason)


def ensure_signal_execution_eligible(
    signal: SignalLike,
    *,
    mode: Literal["virtual", "real"],
    rr_guard_mode: str | None,
) -> None:
    no_trade_reason = signal_no_trade_block_reason(signal)
    if no_trade_reason:
        raise StrategyRiskRewardBlocked(no_trade_reason)

    guard_mode = _normalize_rr_guard_mode(
        rr_guard_mode,
        "hard" if mode == "real" else "soft",
    )
    if guard_mode != "hard":
        return

    rr_reason = signal_rr_warning_reason(signal, respect_guard_mode=False)
    if rr_reason:
        raise StrategyRiskRewardBlocked(f"Execution RR policy rejected: {rr_reason}")


strategy_no_trade_block_reason = signal_no_trade_block_reason


def strategy_rr_block_reason(signal: SignalLike, guard_mode: str = "hard") -> str | None:
    if _normalize_rr_guard_mode(guard_mode, "hard") != "hard":
        return None
    return signal_rr_warning_reason(signal, respect_guard_mode=False)


def ensure_strategy_rr_eligible(signal: SignalLike, guard_mode: str = "hard") -> None:
    """Legacy execution guard; new code should use the signal_* eligibility APIs."""
    ensure_signal_execution_eligible(
        signal,
        mode="real" if _normalize_rr_guard_mode(guard_mode, "hard") == "hard" else "virtual",
        rr_guard_mode=guard_mode,
    )


def _normalize_rr_guard_mode(value: str | None, default: RRGuardMode = "soft") -> RRGuardMode:
    return cast(RRGuardMode, normalize_rr_guard_mode(value, default))


def _confirmation_check(
    signal: SignalLike,
    name: str,
    *,
    statuses: set[str] | None = None,
) -> SignalLayerCheck | None:
    if signal.confirmation is None:
        return None
    for check in signal.confirmation.checks:
        if check.name != name:
            continue
        if statuses is not None and check.status not in statuses:
            continue
        return check
    return None


def _check_reason(checks: Iterable[SignalLayerCheck], *, statuses: set[str]) -> str | None:
    for check in checks:
        if check.status in statuses:
            return check.reason or check.name
    return None


def _metadata_string(metadata: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metadata_strings(metadata: Mapping[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _rr_target_label(signal: SignalLike) -> str:
    target = (signal.selected_rr_target or "selected target").replace("_", " ")
    if target == "nearest":
        return "nearest target"
    if target == "final":
        return "planned final target"
    return target


def _as_rr_warning_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    value = reason.strip()
    if not value:
        return None
    lower = value.lower()
    if lower.startswith("risk/reward blocked:"):
        detail = value.split(":", 1)[1].strip()
        return (
            f"Risk/reward warning: {detail}"
            if detail
            else "Risk/reward warning: selected R:R is below configured reporting threshold."
        )
    if "blocked" in lower or "blocker" in lower:
        return "Risk/reward warning: selected R:R is below configured reporting threshold."
    return value
