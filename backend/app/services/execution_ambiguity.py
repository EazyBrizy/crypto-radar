from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VirtualExecutionAmbiguityPolicy = Literal[
    "conservative_stop_first",
    "target_first",
    "intrabar_unknown",
]
AmbiguityAction = Literal["none", "stop", "target", "unknown"]

DEFAULT_VIRTUAL_EXECUTION_AMBIGUITY_POLICY: VirtualExecutionAmbiguityPolicy = (
    "conservative_stop_first"
)
LEGACY_SAME_CANDLE_POLICY_ALIASES: dict[str, VirtualExecutionAmbiguityPolicy] = {
    "stop_first": "conservative_stop_first",
    "ignore_ambiguous": "intrabar_unknown",
}
CANONICAL_VIRTUAL_EXECUTION_AMBIGUITY_POLICIES: set[VirtualExecutionAmbiguityPolicy] = {
    "conservative_stop_first",
    "target_first",
    "intrabar_unknown",
}


@dataclass(frozen=True)
class StopTargetCandleTouch:
    stop_touched: bool
    target_touched: bool

    @property
    def ambiguous(self) -> bool:
        return self.stop_touched and self.target_touched


@dataclass(frozen=True)
class StopTargetAmbiguityDecision:
    policy: VirtualExecutionAmbiguityPolicy
    requested_policy: str | None
    touch: StopTargetCandleTouch
    action: AmbiguityAction

    @property
    def ambiguous(self) -> bool:
        return self.touch.ambiguous


def normalize_virtual_execution_ambiguity_policy(
    policy: str | None,
) -> VirtualExecutionAmbiguityPolicy:
    if policy is None or not str(policy).strip():
        return DEFAULT_VIRTUAL_EXECUTION_AMBIGUITY_POLICY

    normalized = str(policy).strip().lower().replace("-", "_")
    if normalized in CANONICAL_VIRTUAL_EXECUTION_AMBIGUITY_POLICIES:
        return normalized  # type: ignore[return-value]
    if normalized in LEGACY_SAME_CANDLE_POLICY_ALIASES:
        return LEGACY_SAME_CANDLE_POLICY_ALIASES[normalized]
    supported = sorted(
        [
            *CANONICAL_VIRTUAL_EXECUTION_AMBIGUITY_POLICIES,
            *LEGACY_SAME_CANDLE_POLICY_ALIASES,
        ]
    )
    raise ValueError(
        "unsupported_virtual_execution_ambiguity_policy: "
        f"{policy!r}; supported={supported}"
    )


def detect_stop_target_candle_touch(
    *,
    side: str,
    candle_high: float,
    candle_low: float,
    stop_price: float,
    target_price: float | None,
) -> StopTargetCandleTouch:
    stop_touched = stop_price > 0 and _stop_touched(
        side=side,
        candle_high=candle_high,
        candle_low=candle_low,
        stop_price=stop_price,
    )
    target_touched = (
        target_price is not None
        and target_price > 0
        and _target_touched(
            side=side,
            candle_high=candle_high,
            candle_low=candle_low,
            target_price=target_price,
        )
    )
    return StopTargetCandleTouch(
        stop_touched=stop_touched,
        target_touched=target_touched,
    )


def resolve_stop_target_ambiguity(
    *,
    touch: StopTargetCandleTouch,
    policy: str | None,
) -> StopTargetAmbiguityDecision:
    canonical_policy = normalize_virtual_execution_ambiguity_policy(policy)
    if touch.ambiguous:
        if canonical_policy == "intrabar_unknown":
            action: AmbiguityAction = "unknown"
        elif canonical_policy == "target_first":
            action = "target"
        else:
            action = "stop"
    elif touch.stop_touched:
        action = "stop"
    elif touch.target_touched:
        action = "target"
    else:
        action = "none"

    return StopTargetAmbiguityDecision(
        policy=canonical_policy,
        requested_policy=policy,
        touch=touch,
        action=action,
    )


def _stop_touched(
    *,
    side: str,
    candle_high: float,
    candle_low: float,
    stop_price: float,
) -> bool:
    if side == "long":
        return candle_low <= stop_price
    return candle_high >= stop_price


def _target_touched(
    *,
    side: str,
    candle_high: float,
    candle_low: float,
    target_price: float,
) -> bool:
    if side == "long":
        return candle_high >= target_price
    return candle_low <= target_price
