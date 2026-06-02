from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.schemas.trade_plan import TradePlan


RR_TARGET_ALIASES: dict[str, str] = {
    "first": "nearest",
    "tp1": "nearest",
    "nearest target": "nearest",
    "nearest valid target": "nearest",
    "planned final target": "final",
}


@dataclass(frozen=True)
class RiskRewardTarget:
    key: str
    label: str
    price: float | None
    source: str | None = None
    raw: Any = None


@dataclass(frozen=True)
class RiskRewardCalculation:
    rr_value: float | None
    risk_per_unit: float | None
    reward_per_unit: float | None
    reason: str


@dataclass(frozen=True)
class RiskRewardPlanResult:
    selected_target: RiskRewardTarget | None
    selected_target_key: str
    selected_target_label: str
    rr_value: float | None
    first_target_rr: float | None
    final_target_rr: float | None
    reason: str
    first_target: RiskRewardTarget | None = None
    final_target: RiskRewardTarget | None = None
    invalid_target_labels: tuple[str, ...] = ()


class RiskRewardPlanService:
    """Single target-basis and R:R calculation helper for pipeline and RiskGate."""

    def select_rr_target(
        self,
        trade_plan: TradePlan | None = None,
        policy: str | None = "final",
        *,
        entry: float | None = None,
        stop: float | None = None,
        targets: Sequence[Any] | None = None,
        side: str | None = None,
    ) -> RiskRewardPlanResult:
        return self.resolve(
            trade_plan=trade_plan,
            policy=policy,
            entry=entry,
            stop=stop,
            targets=targets,
            side=side,
        )

    def resolve(
        self,
        *,
        trade_plan: TradePlan | None = None,
        policy: str | None = "final",
        entry: float | None = None,
        stop: float | None = None,
        targets: Sequence[Any] | None = None,
        side: str | None = None,
    ) -> RiskRewardPlanResult:
        entry_price = _number_or_none(entry)
        if entry_price is None and trade_plan is not None:
            entry_price = _trade_plan_entry_price(trade_plan)
        stop_price = _number_or_none(stop)
        if stop_price is None and trade_plan is not None:
            stop_price = _trade_plan_stop_price(trade_plan)

        normalized_targets = _normalize_targets(
            trade_plan.targets if targets is None and trade_plan is not None else targets or []
        )
        normalized_policy = normalize_rr_target_policy(policy)
        first_target = normalized_targets[0] if normalized_targets else None
        final_target = normalized_targets[-1] if normalized_targets else None
        first_calculation = self.calculate_rr(
            entry_price,
            stop_price,
            first_target,
            side,
        )
        final_calculation = self.calculate_rr(
            entry_price,
            stop_price,
            final_target,
            side,
        )
        valid_targets = [
            (target, self.calculate_rr(entry_price, stop_price, target, side))
            for target in normalized_targets
        ]
        valid_targets = [
            (target, calculation)
            for target, calculation in valid_targets
            if calculation.rr_value is not None
        ]
        invalid_labels = tuple(
            target.label
            for target in normalized_targets
            if self.calculate_rr(entry_price, stop_price, target, side).rr_value is None
        )

        selected_target: RiskRewardTarget | None = None
        selected_calculation: RiskRewardCalculation | None = None
        selected_target_key = normalized_policy
        selected_target_label = _target_label_for_policy(normalized_policy)
        reason = "selected_target_resolved"

        if normalized_policy == "nearest":
            if valid_targets:
                selected_target, selected_calculation = valid_targets[0]
                selected_target_label = (
                    "nearest target"
                    if selected_target == first_target
                    else "nearest valid target"
                )
            else:
                reason = _incomplete_reason(entry_price, stop_price, normalized_targets)
        elif normalized_policy == "final":
            selected_target = final_target
            selected_calculation = final_calculation
            if final_target is None:
                reason = _incomplete_reason(entry_price, stop_price, normalized_targets)
            elif selected_calculation.rr_value is None:
                reason = selected_calculation.reason
        else:
            selected_target = _target_by_key(normalized_targets, normalized_policy)
            selected_target_key = normalized_policy.upper()
            selected_target_label = selected_target_key
            selected_calculation = self.calculate_rr(
                entry_price,
                stop_price,
                selected_target,
                side,
            )
            if selected_target is None:
                reason = "selected_target_not_found"
            elif selected_calculation.rr_value is None:
                reason = selected_calculation.reason

        if selected_calculation is None:
            selected_calculation = RiskRewardCalculation(
                rr_value=None,
                risk_per_unit=None,
                reward_per_unit=None,
                reason=reason,
            )
        elif selected_calculation.rr_value is None and reason == "selected_target_resolved":
            reason = selected_calculation.reason

        return RiskRewardPlanResult(
            selected_target=selected_target if selected_calculation.rr_value is not None else selected_target,
            selected_target_key=selected_target_key,
            selected_target_label=selected_target_label,
            rr_value=selected_calculation.rr_value,
            first_target_rr=first_calculation.rr_value,
            final_target_rr=final_calculation.rr_value,
            reason=reason,
            first_target=first_target,
            final_target=final_target,
            invalid_target_labels=invalid_labels,
        )

    def calculate_rr(
        self,
        entry: float | None,
        stop: float | None,
        selected_target: Any,
        side: str | None,
    ) -> RiskRewardCalculation:
        entry_price = _number_or_none(entry)
        stop_price = _number_or_none(stop)
        target = _normalize_target(selected_target, index=0)
        target_price = target.price if target is not None else None
        normalized_side = _normalize_side(side)

        if entry_price is None:
            return RiskRewardCalculation(None, None, None, "missing_entry")
        if stop_price is None:
            return RiskRewardCalculation(None, None, None, "missing_stop")
        if target_price is None:
            return RiskRewardCalculation(None, None, None, "missing_target")
        if normalized_side is None:
            return RiskRewardCalculation(None, None, None, "missing_side")

        risk_per_unit = abs(entry_price - stop_price)
        if risk_per_unit <= 0:
            return RiskRewardCalculation(None, risk_per_unit, None, "invalid_risk")

        reward_per_unit = (
            target_price - entry_price
            if normalized_side == "long"
            else entry_price - target_price
        )
        if reward_per_unit <= 0:
            return RiskRewardCalculation(
                None,
                risk_per_unit,
                reward_per_unit,
                "target_not_beyond_entry",
            )
        return RiskRewardCalculation(
            rr_value=round(reward_per_unit / risk_per_unit, 4),
            risk_per_unit=risk_per_unit,
            reward_per_unit=reward_per_unit,
            reason="calculated",
        )


def normalize_rr_target_policy(policy: str | None) -> str:
    value = str(policy or "final").strip().lower().replace("_", " ")
    return RR_TARGET_ALIASES.get(value, value)


def _normalize_targets(targets: Sequence[Any]) -> list[RiskRewardTarget]:
    normalized: list[RiskRewardTarget] = []
    for index, target in enumerate(targets):
        normalized_target = _normalize_target(target, index=index)
        if normalized_target is not None:
            normalized.append(normalized_target)
    return normalized


def _normalize_target(target: Any, *, index: int) -> RiskRewardTarget | None:
    if target is None:
        return None
    if isinstance(target, RiskRewardTarget):
        return target
    if isinstance(target, (int, float)):
        label = f"TP{index + 1}"
        return RiskRewardTarget(
            key=label.upper(),
            label=label.upper(),
            price=float(target),
            raw=target,
        )
    if isinstance(target, Mapping):
        label = str(target.get("label") or f"TP{index + 1}").strip() or f"TP{index + 1}"
        return RiskRewardTarget(
            key=label.upper(),
            label=label.upper(),
            price=_number_or_none(target.get("price")),
            source=str(target["source"]) if target.get("source") is not None else None,
            raw=target,
        )

    label = str(getattr(target, "label", None) or f"TP{index + 1}").strip() or f"TP{index + 1}"
    return RiskRewardTarget(
        key=label.upper(),
        label=label.upper(),
        price=_number_or_none(getattr(target, "price", None)),
        source=str(getattr(target, "source")) if getattr(target, "source", None) is not None else None,
        raw=target,
    )


def _trade_plan_entry_price(trade_plan: TradePlan) -> float | None:
    entry = trade_plan.entry
    if entry.price is not None:
        return entry.price
    if entry.min_price is not None and entry.max_price is not None:
        return (entry.min_price + entry.max_price) / 2
    return entry.min_price if entry.min_price is not None else entry.max_price


def _trade_plan_stop_price(trade_plan: TradePlan) -> float | None:
    if trade_plan.stop_loss is not None:
        return trade_plan.stop_loss
    if trade_plan.invalidation is None:
        return None
    return trade_plan.invalidation.hard_stop or trade_plan.invalidation.price


def _target_by_key(
    targets: Sequence[RiskRewardTarget],
    key: str,
) -> RiskRewardTarget | None:
    normalized_key = key.strip().upper()
    for target in targets:
        if target.key == normalized_key or target.label == normalized_key:
            return target
    return None


def _target_label_for_policy(policy: str) -> str:
    if policy == "nearest":
        return "nearest target"
    if policy == "final":
        return "planned final target"
    return policy.upper()


def _incomplete_reason(
    entry: float | None,
    stop: float | None,
    targets: Sequence[RiskRewardTarget],
) -> str:
    if entry is None:
        return "missing_entry"
    if stop is None:
        return "missing_stop"
    if not targets:
        return "missing_target"
    return "no_planned_target_beyond_entry"


def _normalize_side(side: str | None) -> str | None:
    value = str(side or "").strip().lower()
    if value in {"long", "buy"}:
        return "long"
    if value in {"short", "sell"}:
        return "short"
    return None


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


risk_reward_plan_service = RiskRewardPlanService()
