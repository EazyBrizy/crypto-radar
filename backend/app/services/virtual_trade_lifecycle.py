from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas.trade import (
    CloseReason,
    TradeResult,
    VirtualTrade,
    VirtualTradeLifecycleEvent,
    VirtualTradeTargetState,
)

_EPSILON = 1e-9


@dataclass(frozen=True)
class VirtualTradeLifecycleResult:
    trade: VirtualTrade
    realized_pnl_delta: float = 0.0
    closed: bool = False


def initialize_virtual_trade_lifecycle(trade: VirtualTrade) -> VirtualTrade:
    initial_quantity = _initial_quantity(trade)
    remaining_quantity = _remaining_quantity(trade, initial_quantity)
    closed_quantity = max(trade.closed_quantity, initial_quantity - remaining_quantity)
    initial_size_usd = _initial_size_usd(trade)
    remaining_size_usd = _size_for_quantity(trade.entry_price, remaining_quantity)
    realized_pnl = trade.realized_pnl
    if trade.status == "closed" and trade.pnl is not None and abs(realized_pnl) <= _EPSILON:
        realized_pnl = trade.pnl
    unrealized_pnl = (
        0.0
        if trade.status == "closed"
        else _gross_pnl(
            side=trade.side,
            entry_price=trade.entry_price,
            exit_price=trade.current_price,
            quantity=remaining_quantity,
        )
    )
    current_stop_loss = trade.current_stop_loss
    if current_stop_loss is None and trade.stop_loss > 0:
        current_stop_loss = trade.stop_loss
    return trade.model_copy(
        update={
            "initial_quantity": initial_quantity,
            "remaining_quantity": remaining_quantity,
            "closed_quantity": closed_quantity,
            "initial_size_usd": initial_size_usd,
            "remaining_size_usd": remaining_size_usd,
            "current_stop_loss": current_stop_loss,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "exit_fees": trade.exit_fees,
            "target_states": trade.target_states or _target_states_from_trade(trade),
        }
    )


def arm_virtual_trade_time_stop(
    trade: VirtualTrade,
    metadata: dict[str, Any] | None,
    now: datetime,
) -> VirtualTrade:
    if not metadata or _time_stop_event(trade) is not None:
        return trade
    time_stop_metadata = _time_stop_metadata(metadata)
    if not time_stop_metadata:
        return trade
    return _append_event(
        trade,
        VirtualTradeLifecycleEvent(
            event_type="time_stop_armed",
            created_at=now,
            metadata=time_stop_metadata,
        ),
    )


def apply_virtual_trade_market_price(
    trade: VirtualTrade,
    price: float,
    now: datetime,
) -> VirtualTradeLifecycleResult:
    updated = _mark_price(initialize_virtual_trade_lifecycle(trade), price, now)
    if updated.status != "open":
        return VirtualTradeLifecycleResult(trade=updated)

    if _time_stop_reached(updated, now):
        return _close_remaining(updated, price, "time_stop", now)

    stop_price = updated.current_stop_loss or updated.stop_loss
    if _stop_reached(updated.side, price, stop_price):
        return _close_remaining(updated, stop_price, _stop_reason(updated, stop_price), now)

    realized_delta = 0.0
    working = updated
    for index, target in enumerate(working.target_states):
        if target.hit or not _target_reached(working.side, price, target.price):
            continue

        target_result = _hit_target(working, index, target, now)
        working = target_result.trade
        realized_delta += target_result.realized_pnl_delta
        if target_result.closed:
            return VirtualTradeLifecycleResult(
                trade=working,
                realized_pnl_delta=realized_delta,
                closed=True,
            )

    return VirtualTradeLifecycleResult(
        trade=working,
        realized_pnl_delta=realized_delta,
        closed=False,
    )


def close_virtual_trade_lifecycle(
    trade: VirtualTrade,
    exit_price: float,
    reason: CloseReason,
    now: datetime,
) -> VirtualTradeLifecycleResult:
    updated = _mark_price(initialize_virtual_trade_lifecycle(trade), exit_price, now)
    if updated.status != "open":
        return VirtualTradeLifecycleResult(trade=updated)
    return _close_remaining(updated, exit_price, reason, now)


def _hit_target(
    trade: VirtualTrade,
    target_index: int,
    target: VirtualTradeTargetState,
    now: datetime,
) -> VirtualTradeLifecycleResult:
    initial_quantity = _initial_quantity(trade)
    remaining_quantity = _remaining_quantity(trade, initial_quantity)
    full_close = target.action == "full_close"
    close_quantity = remaining_quantity if full_close else initial_quantity * target.close_percent / 100
    close_quantity = min(max(close_quantity, 0.0), remaining_quantity)
    if close_quantity <= _EPSILON:
        updated = _set_target_state(
            trade,
            target_index,
            target.model_copy(update={"hit": True, "hit_at": now}),
        )
        updated = _apply_target_action(updated, target, now)
        return VirtualTradeLifecycleResult(trade=updated)

    reason: CloseReason = (
        "take_profit"
        if full_close or remaining_quantity - close_quantity <= _EPSILON
        else "partial_take_profit"
    )
    close_result = _close_quantity(
        trade=trade,
        exit_price=target.price,
        reason=reason,
        quantity=close_quantity,
        now=now,
        target_label=target.label,
    )
    updated_target = target.model_copy(
        update={
            "hit": True,
            "hit_at": now,
            "closed_quantity": close_quantity,
            "closed_size_usd": _size_for_quantity(trade.entry_price, close_quantity),
            "realized_pnl": close_result.realized_pnl_delta,
            "exit_fee": _last_exit_fee(close_result.trade),
        }
    )
    updated = _set_target_state(close_result.trade, target_index, updated_target)
    if updated.status == "open":
        updated = _apply_target_action(updated, target, now)
    return VirtualTradeLifecycleResult(
        trade=updated,
        realized_pnl_delta=close_result.realized_pnl_delta,
        closed=close_result.closed,
    )


def _close_remaining(
    trade: VirtualTrade,
    exit_price: float,
    reason: CloseReason,
    now: datetime,
) -> VirtualTradeLifecycleResult:
    initial_quantity = _initial_quantity(trade)
    remaining_quantity = _remaining_quantity(trade, initial_quantity)
    if remaining_quantity <= _EPSILON:
        closed = trade.model_copy(
            update={
                "status": "closed",
                "remaining_quantity": 0.0,
                "remaining_size_usd": 0.0,
                "unrealized_pnl": 0.0,
                "updated_at": now,
                "closed_at": now,
            }
        )
        return VirtualTradeLifecycleResult(trade=closed, closed=True)
    return _close_quantity(
        trade=trade,
        exit_price=exit_price,
        reason=reason,
        quantity=remaining_quantity,
        now=now,
        target_label=None,
    )


def _close_quantity(
    *,
    trade: VirtualTrade,
    exit_price: float,
    reason: CloseReason,
    quantity: float,
    now: datetime,
    target_label: str | None,
) -> VirtualTradeLifecycleResult:
    initial_quantity = _initial_quantity(trade)
    remaining_before = _remaining_quantity(trade, initial_quantity)
    close_quantity = min(max(quantity, 0.0), remaining_before)
    slipped_exit = _apply_exit_slippage(
        exit_price,
        trade.side,
        _exit_slippage_bps_for_trade(trade, reason),
    )
    entry_fee_total = _entry_fee_total(trade)
    fee_rate = entry_fee_total / _initial_size_usd(trade) if _initial_size_usd(trade) else 0.0
    allocated_entry_fee = (
        entry_fee_total * close_quantity / initial_quantity if initial_quantity else 0.0
    )
    exit_fee = close_quantity * slipped_exit * fee_rate
    gross_pnl = _gross_pnl(
        side=trade.side,
        entry_price=trade.entry_price,
        exit_price=slipped_exit,
        quantity=close_quantity,
    )
    realized_delta = gross_pnl - allocated_entry_fee - exit_fee
    remaining_after = max(remaining_before - close_quantity, 0.0)
    closed_quantity = min(trade.closed_quantity + close_quantity, initial_quantity)
    exit_fees = trade.exit_fees + exit_fee
    realized_pnl = trade.realized_pnl + realized_delta
    fees = entry_fee_total + exit_fees
    event = VirtualTradeLifecycleEvent(
        event_type=reason,
        reason=reason,
        target_label=target_label,
        price=slipped_exit,
        quantity=close_quantity,
        size_usd=_size_for_quantity(trade.entry_price, close_quantity),
        realized_pnl=realized_delta,
        exit_fee=exit_fee,
        stop_loss=trade.current_stop_loss or trade.stop_loss,
        created_at=now,
        metadata={
            "gross_pnl": gross_pnl,
            "allocated_entry_fee": allocated_entry_fee,
            "trigger_price": exit_price,
        },
    )
    updates: dict[str, Any] = {
        "current_price": slipped_exit,
        "remaining_quantity": remaining_after,
        "closed_quantity": closed_quantity,
        "remaining_size_usd": _size_for_quantity(trade.entry_price, remaining_after),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": 0.0
        if remaining_after <= _EPSILON
        else _gross_pnl(
            side=trade.side,
            entry_price=trade.entry_price,
            exit_price=slipped_exit,
            quantity=remaining_after,
        ),
        "exit_fees": exit_fees,
        "fees": fees,
        "close_reason": reason,
        "updated_at": now,
        "lifecycle_events": [*trade.lifecycle_events, event],
    }
    closed = remaining_after <= _EPSILON
    if closed:
        updates.update(
            {
                "exit_price": slipped_exit,
                "status": "closed",
                "result": _result(realized_pnl),
                "pnl": realized_pnl,
                "pnl_percent": realized_pnl / _initial_size_usd(trade) * 100
                if _initial_size_usd(trade)
                else 0.0,
                "closed_at": now,
            }
        )
    updated = trade.model_copy(update=updates)
    return VirtualTradeLifecycleResult(
        trade=_mark_extremes(updated),
        realized_pnl_delta=realized_delta,
        closed=closed,
    )


def _apply_target_action(
    trade: VirtualTrade,
    target: VirtualTradeTargetState,
    now: datetime,
) -> VirtualTrade:
    updated = trade
    if target.action == "move_stop_to_breakeven":
        breakeven_stop = _breakeven_stop_price(updated)
        current_stop = updated.current_stop_loss or updated.stop_loss
        if _stop_improves(updated.side, current_stop, breakeven_stop):
            updated = _append_event(
                updated.model_copy(
                    update={
                        "current_stop_loss": breakeven_stop,
                        "stop_moved_to_breakeven": True,
                        "updated_at": now,
                    }
                ),
                VirtualTradeLifecycleEvent(
                    event_type="stop_moved_to_breakeven",
                    target_label=target.label,
                    stop_loss=breakeven_stop,
                    created_at=now,
                ),
            )
    if target.action == "trailing_stop" and not updated.trailing_active:
        trailing_stop = _trailing_stop_price(updated)
        update: dict[str, Any] = {"trailing_active": True, "updated_at": now}
        if trailing_stop is not None and _stop_improves(
            updated.side,
            updated.current_stop_loss or updated.stop_loss,
            trailing_stop,
        ):
            update["current_stop_loss"] = trailing_stop
        updated = _append_event(
            updated.model_copy(update=update),
            VirtualTradeLifecycleEvent(
                event_type="trailing_activated",
                target_label=target.label,
                stop_loss=update.get("current_stop_loss"),
                created_at=now,
            ),
        )
    return updated


def _mark_price(trade: VirtualTrade, price: float, now: datetime) -> VirtualTrade:
    initial_quantity = _initial_quantity(trade)
    remaining_quantity = _remaining_quantity(trade, initial_quantity)
    unrealized_pnl = (
        0.0
        if trade.status == "closed"
        else _gross_pnl(
            side=trade.side,
            entry_price=trade.entry_price,
            exit_price=price,
            quantity=remaining_quantity,
        )
    )
    marked = trade.model_copy(
        update={
            "current_price": price,
            "unrealized_pnl": unrealized_pnl,
            "remaining_size_usd": _size_for_quantity(trade.entry_price, remaining_quantity),
            "updated_at": now,
        }
    )
    return _mark_extremes(marked)


def _mark_extremes(trade: VirtualTrade) -> VirtualTrade:
    portfolio_pnl = trade.realized_pnl + trade.unrealized_pnl
    return trade.model_copy(
        update={
            "mfe": max(trade.mfe, portfolio_pnl),
            "mae": min(trade.mae, portfolio_pnl),
        }
    )


def _target_states_from_trade(trade: VirtualTrade) -> list[VirtualTradeTargetState]:
    take_profit_plan = trade.execution.take_profit_plan if trade.execution else None
    if take_profit_plan is not None and take_profit_plan.targets:
        return [
            VirtualTradeTargetState(
                label=target.label,
                price=target.price,
                close_percent=target.close_percent,
                action=target.action,
            )
            for target in take_profit_plan.targets
        ]
    if not trade.take_profit:
        return []
    final_index = len(trade.take_profit)
    return [
        VirtualTradeTargetState(
            label=f"TP{final_index}",
            price=trade.take_profit[-1],
            close_percent=100.0,
            action="full_close",
        )
    ]


def _set_target_state(
    trade: VirtualTrade,
    target_index: int,
    target: VirtualTradeTargetState,
) -> VirtualTrade:
    targets = list(trade.target_states)
    targets[target_index] = target
    return trade.model_copy(update={"target_states": targets})


def _append_event(
    trade: VirtualTrade,
    event: VirtualTradeLifecycleEvent,
) -> VirtualTrade:
    return trade.model_copy(update={"lifecycle_events": [*trade.lifecycle_events, event]})


def _initial_quantity(trade: VirtualTrade) -> float:
    return trade.initial_quantity if trade.initial_quantity is not None else trade.quantity


def _remaining_quantity(trade: VirtualTrade, initial_quantity: float) -> float:
    if trade.remaining_quantity is not None:
        return trade.remaining_quantity
    return 0.0 if trade.status == "closed" else initial_quantity


def _initial_size_usd(trade: VirtualTrade) -> float:
    return trade.initial_size_usd if trade.initial_size_usd is not None else trade.size_usd


def _entry_fee_total(trade: VirtualTrade) -> float:
    return max(trade.fees - trade.exit_fees, 0.0)


def _last_exit_fee(trade: VirtualTrade) -> float:
    if not trade.lifecycle_events:
        return 0.0
    return trade.lifecycle_events[-1].exit_fee or 0.0


def _size_for_quantity(entry_price: float, quantity: float) -> float:
    return max(entry_price * quantity, 0.0)


def _gross_pnl(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
) -> float:
    if side == "long":
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def _target_reached(side: str, price: float, target_price: float) -> bool:
    if side == "long":
        return price >= target_price
    return price <= target_price


def _stop_reached(side: str, price: float, stop_price: float) -> bool:
    if side == "long":
        return price <= stop_price
    return price >= stop_price


def _stop_reason(trade: VirtualTrade, stop_price: float) -> CloseReason:
    breakeven_stop = _breakeven_stop_price(trade)
    if trade.trailing_active and abs(stop_price - breakeven_stop) > _EPSILON:
        return "trailing_stop"
    if trade.stop_moved_to_breakeven:
        return "breakeven_stop"
    return "stop_loss"


def _breakeven_stop_price(trade: VirtualTrade) -> float:
    breakeven_plan = trade.execution.breakeven_plan if trade.execution else None
    if breakeven_plan is not None:
        return breakeven_plan.breakeven_stop_price
    return trade.entry_price


def _trailing_stop_price(trade: VirtualTrade) -> float | None:
    trailing_plan = trade.execution.trailing_stop_plan if trade.execution else None
    if trailing_plan is None or not trailing_plan.enabled:
        return None
    return trailing_plan.trailing_stop_price


def _stop_improves(side: str, current_stop: float, next_stop: float) -> bool:
    if side == "long":
        return next_stop > current_stop + _EPSILON
    return next_stop < current_stop - _EPSILON


def _apply_exit_slippage(price: float, side: str, slippage_bps: float) -> float:
    multiplier = slippage_bps / 10_000
    return price * (1 - multiplier) if side == "long" else price * (1 + multiplier)


def _exit_slippage_bps_for_trade(trade: VirtualTrade, reason: CloseReason) -> float:
    if trade.execution is None:
        return trade.slippage_bps
    exit_slippage_bps = max(trade.execution.exit_slippage_bps, trade.slippage_bps)
    if reason == "stop_loss" and trade.execution.mode == "impact_aware":
        return exit_slippage_bps * 1.1
    return exit_slippage_bps


def _time_stop_reached(trade: VirtualTrade, now: datetime) -> bool:
    event = _time_stop_event(trade)
    if event is None:
        return False
    time_stop_at = _parse_datetime(
        event.metadata.get("time_stop_at")
        or event.metadata.get("expires_at")
        or event.metadata.get("at")
    )
    if time_stop_at is not None:
        return _as_utc(now) >= _as_utc(time_stop_at)
    max_holding_seconds = event.metadata.get("max_holding_seconds")
    if max_holding_seconds is None:
        return False
    try:
        seconds = float(max_holding_seconds)
    except (TypeError, ValueError):
        return False
    return _as_utc(now) >= _as_utc(trade.opened_at) + timedelta(seconds=seconds)


def _time_stop_event(trade: VirtualTrade) -> VirtualTradeLifecycleEvent | None:
    for event in trade.lifecycle_events:
        if event.event_type == "time_stop_armed":
            return event
    return None


def _time_stop_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("time_stop_at", "expires_at", "at", "max_holding_seconds"):
        if metadata.get(key) is not None:
            result[key] = metadata[key]
    nested = metadata.get("time_stop")
    if isinstance(nested, dict):
        for key in ("time_stop_at", "expires_at", "at", "max_holding_seconds"):
            if nested.get(key) is not None:
                result[key] = nested[key]
    return result


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _result(pnl: float) -> TradeResult:
    if pnl > 0:
        return "win"
    if pnl < 0:
        return "loss"
    return "breakeven"
