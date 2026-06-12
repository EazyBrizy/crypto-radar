from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


ExecutionPolicyMode = Literal["limit", "market", "pending_retest", "late_entry", "probe", "skip"]
ExecutionSide = Literal["long", "short"]


@dataclass(frozen=True)
class ExecutionPolicyContext:
    side: ExecutionSide
    current_price: float
    entry_min: float | None = None
    entry_max: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    min_rr_ratio: float = 0.0
    preferred_mode: ExecutionPolicyMode | None = None
    allow_pending_retest: bool = True
    allow_probe: bool = False
    max_late_entry_deviation_bps: float = 100.0
    max_probe_deviation_bps: float = 10.0
    slippage_bps: float = 0.0
    max_slippage_bps: float = 0.0
    spread_bps: float | None = None
    max_spread_bps: float = 0.0
    orderbook_depth_usd: float | None = None
    requested_size_usd: float = 0.0
    min_depth_to_size_ratio: float = 1.0


@dataclass(frozen=True)
class ExecutionPolicyDecision:
    mode: ExecutionPolicyMode
    can_execute: bool
    should_wait: bool
    reason_code: str
    reason_codes: list[str] = field(default_factory=list)
    message: str = ""
    price_deviation_bps: float = 0.0
    recalculated_rr: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ExecutionPolicyResolver:
    def resolve(self, context: ExecutionPolicyContext) -> ExecutionPolicyDecision:
        side = _side(context.side)
        current_price = max(0.0, float(context.current_price or 0.0))
        entry_min, entry_max = _entry_zone(context.entry_min, context.entry_max)
        if current_price <= 0:
            return _decision(
                mode="skip",
                can_execute=False,
                reason_code="execution_price_unavailable",
                message="Execution price is unavailable.",
            )

        zone_state = _zone_state(
            side=side,
            current_price=current_price,
            entry_min=entry_min,
            entry_max=entry_max,
        )
        deviation_bps = _price_deviation_bps(current_price, entry_min, entry_max)

        if zone_state == "before":
            if context.allow_pending_retest:
                return _decision(
                    mode="pending_retest",
                    can_execute=False,
                    should_wait=True,
                    reason_code="entry_zone_not_reached_wait_for_retest",
                    message="Price has not reached the entry zone; wait for retest.",
                    price_deviation_bps=deviation_bps,
                )
            market_block = _market_quality_block(context)
            if market_block is not None:
                return market_block
            return _decision(
                mode="limit" if context.preferred_mode == "limit" else "market",
                can_execute=True,
                reason_code=f"execution_policy_{'limit' if context.preferred_mode == 'limit' else 'market'}",
                message="Price has not reached the entry zone, but no retest wait policy is enabled.",
                price_deviation_bps=deviation_bps,
            )

        if zone_state == "in_zone":
            market_block = _market_quality_block(context)
            if market_block is not None:
                return market_block
            preferred = context.preferred_mode if context.preferred_mode in {"limit", "market"} else None
            return _decision(
                mode=preferred or "market",
                can_execute=True,
                reason_code=f"execution_policy_{preferred or 'market'}",
                message="Price is inside the entry zone.",
                price_deviation_bps=0.0,
            )

        if context.allow_pending_retest:
            return _decision(
                mode="pending_retest",
                can_execute=False,
                should_wait=True,
                reason_code="entry_zone_missed_wait_for_retest",
                message="Price moved past the entry zone; wait for a retest.",
                price_deviation_bps=deviation_bps,
            )

        rr = _recalculated_rr(
            side=side,
            current_price=current_price,
            stop_loss=context.stop_loss,
            take_profit=context.take_profit,
        )
        if rr is None:
            return _decision(
                mode="skip",
                can_execute=False,
                reason_code="late_entry_rr_recalculation_required",
                message="Late entry requires stop, target, and recalculated RR.",
                price_deviation_bps=deviation_bps,
            )
        if context.min_rr_ratio > 0 and rr < context.min_rr_ratio:
            return _decision(
                mode="skip",
                can_execute=False,
                reason_code="late_entry_rr_below_min",
                message="Late entry recalculated RR is below the required minimum.",
                price_deviation_bps=deviation_bps,
                recalculated_rr=rr,
            )

        market_block = _market_quality_block(context)
        if market_block is not None:
            return market_block
        if deviation_bps > context.max_late_entry_deviation_bps:
            return _decision(
                mode="skip",
                can_execute=False,
                reason_code="late_entry_price_deviation_exceeded",
                message="Price moved too far from the entry zone.",
                price_deviation_bps=deviation_bps,
                recalculated_rr=rr,
            )
        if context.allow_probe and deviation_bps <= context.max_probe_deviation_bps:
            return _decision(
                mode="probe",
                can_execute=True,
                reason_code="probe_entry_rr_recalculated",
                message="Small price deviation allows a probe entry after RR recalculation.",
                price_deviation_bps=deviation_bps,
                recalculated_rr=rr,
            )
        return _decision(
            mode="late_entry",
            can_execute=True,
            reason_code="late_entry_rr_recalculated",
            message="Late entry is allowed after RR and execution-cost recalculation.",
            price_deviation_bps=deviation_bps,
            recalculated_rr=rr,
        )


def _decision(
    *,
    mode: ExecutionPolicyMode,
    can_execute: bool,
    reason_code: str,
    message: str,
    should_wait: bool = False,
    price_deviation_bps: float = 0.0,
    recalculated_rr: float | None = None,
) -> ExecutionPolicyDecision:
    return ExecutionPolicyDecision(
        mode=mode,
        can_execute=can_execute,
        should_wait=should_wait,
        reason_code=reason_code,
        reason_codes=[reason_code],
        message=message,
        price_deviation_bps=max(0.0, price_deviation_bps),
        recalculated_rr=recalculated_rr,
    )


def _market_quality_block(context: ExecutionPolicyContext) -> ExecutionPolicyDecision | None:
    if context.max_slippage_bps > 0 and context.slippage_bps > context.max_slippage_bps:
        return _decision(
            mode="skip",
            can_execute=False,
            reason_code="execution_slippage_limit_exceeded",
            message="Expected slippage exceeds execution policy.",
        )
    if (
        context.spread_bps is not None
        and context.max_spread_bps > 0
        and context.spread_bps > context.max_spread_bps
    ):
        return _decision(
            mode="skip",
            can_execute=False,
            reason_code="execution_spread_limit_exceeded",
            message="Spread exceeds execution policy.",
        )
    if (
        context.orderbook_depth_usd is not None
        and context.requested_size_usd > 0
        and context.min_depth_to_size_ratio > 0
        and context.orderbook_depth_usd < context.requested_size_usd * context.min_depth_to_size_ratio
    ):
        return _decision(
            mode="skip",
            can_execute=False,
            reason_code="execution_depth_insufficient",
            message="Orderbook depth is insufficient for requested size.",
        )
    return None


def _side(value: str) -> ExecutionSide:
    return "short" if str(value).lower() == "short" else "long"


def _entry_zone(entry_min: float | None, entry_max: float | None) -> tuple[float | None, float | None]:
    if entry_min is None and entry_max is None:
        return None, None
    if entry_min is None:
        return entry_max, entry_max
    if entry_max is None:
        return entry_min, entry_min
    return (entry_min, entry_max) if entry_min <= entry_max else (entry_max, entry_min)


def _zone_state(
    *,
    side: ExecutionSide,
    current_price: float,
    entry_min: float | None,
    entry_max: float | None,
) -> Literal["before", "in_zone", "past"]:
    if entry_min is None or entry_max is None:
        return "in_zone"
    if entry_min <= current_price <= entry_max:
        return "in_zone"
    if side == "long":
        return "past" if current_price > entry_max else "before"
    return "past" if current_price < entry_min else "before"


def _price_deviation_bps(
    current_price: float,
    entry_min: float | None,
    entry_max: float | None,
) -> float:
    if entry_min is None or entry_max is None:
        return 0.0
    if entry_min <= current_price <= entry_max:
        return 0.0
    boundary = entry_max if current_price > entry_max else entry_min
    if boundary <= 0:
        return 0.0
    return abs(current_price - boundary) / boundary * 10_000


def _recalculated_rr(
    *,
    side: ExecutionSide,
    current_price: float,
    stop_loss: float | None,
    take_profit: float | None,
) -> float | None:
    if stop_loss is None or take_profit is None:
        return None
    if side == "long":
        risk = current_price - stop_loss
        reward = take_profit - current_price
    else:
        risk = stop_loss - current_price
        reward = current_price - take_profit
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


execution_policy_resolver = ExecutionPolicyResolver()
