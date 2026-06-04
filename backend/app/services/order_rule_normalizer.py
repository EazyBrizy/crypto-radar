from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from typing import Any

from app.schemas.trade import ExecutionPlannedOrder, RealExecutionPlan


@dataclass(frozen=True)
class OrderRuleAdjustment:
    order_client_id: str
    role: str
    field: str
    requested: float | None
    normalized: float | None
    rule: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_client_id": self.order_client_id,
            "role": self.role,
            "field": self.field,
            "requested": self.requested,
            "normalized": self.normalized,
            "rule": self.rule,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OrderRuleNormalizationResult:
    plan: RealExecutionPlan
    adjustments: list[OrderRuleAdjustment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _OrderRules:
    qty_step: Decimal | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    min_notional: Decimal | None = None
    price_tick: Decimal | None = None
    price_precision: int | None = None
    reduce_only_supported: bool | None = None
    margin_mode: str | None = None
    allowed_margin_modes: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "qty_step": _float_or_none(self.qty_step),
            "min_qty": _float_or_none(self.min_qty),
            "max_qty": _float_or_none(self.max_qty),
            "min_notional": _float_or_none(self.min_notional),
            "price_tick": _float_or_none(self.price_tick),
            "price_precision": self.price_precision,
            "reduce_only_supported": self.reduce_only_supported,
            "margin_mode": self.margin_mode,
            "allowed_margin_modes": list(self.allowed_margin_modes),
        }


class OrderRuleNormalizer:
    """Normalizes real execution order plans by exchange filters before validation."""

    def normalize_order_plan(
        self,
        plan: RealExecutionPlan,
        exchange_rules: Any,
    ) -> OrderRuleNormalizationResult:
        rules = _extract_rules(exchange_rules)
        adjustments: list[OrderRuleAdjustment] = []
        warnings = _rule_warnings(exchange_rules, rules)
        errors: list[str] = []

        normalized_orders: list[ExecutionPlannedOrder] = []
        for order in plan.planned_orders:
            normalized_order, order_adjustments, order_errors = _normalize_order(order, rules)
            normalized_orders.append(normalized_order)
            adjustments.extend(order_adjustments)
            errors.extend(order_errors)

        margin_mode = _normalize_margin_mode(plan.margin_mode or rules.margin_mode)
        if rules.allowed_margin_modes and margin_mode is not None and margin_mode not in rules.allowed_margin_modes:
            errors.append(f"Execution plan margin mode {margin_mode!r} is not allowed by exchange rules.")

        if rules.reduce_only_supported is False and any(order.reduce_only for order in normalized_orders):
            errors.append("Exchange rules do not allow reduce-only protective orders.")

        entry_order = next((order for order in normalized_orders if order.role == "entry"), None)
        requested_quantity = _decimal_or_none(plan.requested_quantity or plan.quantity)
        requested_entry_price = _decimal_or_none(plan.requested_entry_price or plan.entry_price)
        requested_notional = _decimal_or_none(plan.requested_notional or plan.notional)
        normalized_quantity = _decimal_or_none(entry_order.quantity if entry_order is not None else plan.quantity)
        normalized_entry_price = _decimal_or_none(
            (
                entry_order.price
                if entry_order is not None and entry_order.price is not None
                else plan.entry_price
            )
        )
        normalized_notional = _multiply(normalized_quantity, normalized_entry_price)

        if normalized_quantity is not None:
            if rules.min_qty is not None and normalized_quantity < rules.min_qty:
                errors.append("Execution plan normalized quantity is below exchange minimum order size.")
            if rules.max_qty is not None and normalized_quantity > rules.max_qty:
                errors.append("Execution plan normalized quantity is above exchange maximum order size.")
        if (
            normalized_notional is not None
            and rules.min_notional is not None
            and normalized_notional < rules.min_notional
        ):
            errors.append("Execution plan normalized notional is below exchange minimum notional.")

        normalized_plan = plan.model_copy(
            update={
                "entry_price": _float_or_original(normalized_entry_price, plan.entry_price),
                "quantity": _float_or_original(normalized_quantity, plan.quantity),
                "notional": _float_or_original(normalized_notional, plan.notional),
                "requested_quantity": _float_or_none(requested_quantity),
                "normalized_quantity": _float_or_none(normalized_quantity),
                "requested_entry_price": _float_or_none(requested_entry_price),
                "normalized_entry_price": _float_or_none(normalized_entry_price),
                "requested_notional": _float_or_none(requested_notional),
                "normalized_notional": _float_or_none(normalized_notional),
                "margin_mode": margin_mode,
                "planned_orders": normalized_orders,
                "metadata": {
                    **plan.metadata,
                    "order_rule_normalization": {
                        "source": "OrderRuleNormalizer",
                        "rules": rules.to_metadata(),
                        "adjustments": [adjustment.to_dict() for adjustment in adjustments],
                        "warnings": warnings,
                        "errors": _dedupe(errors),
                        "risk_trace": _risk_trace(
                            plan=plan,
                            normalized_orders=normalized_orders,
                            requested_quantity=requested_quantity,
                            normalized_quantity=normalized_quantity,
                            requested_entry_price=requested_entry_price,
                            normalized_entry_price=normalized_entry_price,
                            requested_notional=requested_notional,
                            normalized_notional=normalized_notional,
                        ),
                    },
                },
            }
        )
        return OrderRuleNormalizationResult(
            plan=normalized_plan,
            adjustments=adjustments,
            warnings=warnings,
            errors=_dedupe(errors),
        )


def _normalize_order(
    order: ExecutionPlannedOrder,
    rules: _OrderRules,
) -> tuple[ExecutionPlannedOrder, list[OrderRuleAdjustment], list[str]]:
    adjustments: list[OrderRuleAdjustment] = []
    errors: list[str] = []
    reasons: list[str] = []

    requested_quantity = _decimal_or_none(order.requested_quantity or order.quantity)
    normalized_quantity = requested_quantity
    if requested_quantity is not None and rules.qty_step is not None:
        normalized_quantity = _round_down_to_step(requested_quantity, rules.qty_step)
        if normalized_quantity != requested_quantity:
            reason = f"quantity rounded down to qty_step {rules.qty_step}"
            reasons.append(reason)
            adjustments.append(
                _adjustment(
                    order=order,
                    field="quantity",
                    requested=requested_quantity,
                    normalized=normalized_quantity,
                    rule="qty_step",
                    reason=reason,
                )
            )
    if normalized_quantity is not None:
        if normalized_quantity <= 0:
            errors.append(f"Order {order.client_order_id} normalized quantity is not positive.")
        if rules.min_qty is not None and normalized_quantity < rules.min_qty:
            errors.append(f"Order {order.client_order_id} normalized quantity is below exchange minimum order size.")
        if rules.max_qty is not None and normalized_quantity > rules.max_qty:
            errors.append(f"Order {order.client_order_id} normalized quantity is above exchange maximum order size.")

    requested_price = _decimal_or_none(order.requested_price or order.price)
    normalized_price = _normalize_price_value(
        order=order,
        field="price",
        value=requested_price,
        rules=rules,
        adjustments=adjustments,
        reasons=reasons,
    )
    requested_stop_price = _decimal_or_none(order.requested_stop_price or order.stop_price)
    normalized_stop_price = _normalize_price_value(
        order=order,
        field="stop_price",
        value=requested_stop_price,
        rules=rules,
        adjustments=adjustments,
        reasons=reasons,
    )

    rounding_reason = "; ".join(_dedupe(reasons)) if reasons else order.rounding_reason
    metadata = {
        **order.metadata,
        "requested_qty": _float_or_none(requested_quantity),
        "normalized_qty": _float_or_none(normalized_quantity),
        "requested_price": _float_or_none(requested_price),
        "normalized_price": _float_or_none(normalized_price),
        "requested_stop_price": _float_or_none(requested_stop_price),
        "normalized_stop_price": _float_or_none(normalized_stop_price),
        "rounding_reason": rounding_reason,
    }
    normalized_order = order.model_copy(
        update={
            "quantity": _float_or_original(normalized_quantity, order.quantity),
            "price": _float_or_none(normalized_price),
            "stop_price": _float_or_none(normalized_stop_price),
            "requested_quantity": _float_or_none(requested_quantity),
            "normalized_quantity": _float_or_none(normalized_quantity),
            "requested_price": _float_or_none(requested_price),
            "normalized_price": _float_or_none(normalized_price),
            "requested_stop_price": _float_or_none(requested_stop_price),
            "normalized_stop_price": _float_or_none(normalized_stop_price),
            "rounding_reason": rounding_reason,
            "metadata": metadata,
        }
    )
    return normalized_order, adjustments, errors


def _normalize_price_value(
    *,
    order: ExecutionPlannedOrder,
    field: str,
    value: Decimal | None,
    rules: _OrderRules,
    adjustments: list[OrderRuleAdjustment],
    reasons: list[str],
) -> Decimal | None:
    if value is None:
        return None
    normalized = value
    field_rules: list[str] = []
    if rules.price_tick is not None:
        tick_normalized = _round_to_tick(normalized, rules.price_tick)
        if tick_normalized != normalized:
            field_rules.append(f"{field} rounded to tick_size {rules.price_tick}")
        normalized = tick_normalized
    if rules.price_precision is not None:
        precision_normalized = _round_to_precision(normalized, rules.price_precision)
        if precision_normalized != normalized:
            field_rules.append(f"{field} rounded to price_precision {rules.price_precision}")
        normalized = precision_normalized
    if field_rules:
        reason = "; ".join(field_rules)
        reasons.append(reason)
        adjustments.append(
            _adjustment(
                order=order,
                field=field,
                requested=value,
                normalized=normalized,
                rule="price_tick",
                reason=reason,
            )
        )
    return normalized


def _extract_rules(exchange_rules: Any) -> _OrderRules:
    return _OrderRules(
        qty_step=_positive_decimal_attr(
            exchange_rules,
            "exchange_qty_step",
            "qty_step",
            "quantity_step",
            "lot_size",
        ),
        min_qty=_positive_decimal_attr(
            exchange_rules,
            "exchange_min_order_size",
            "min_order_size",
            "min_qty",
            "minQty",
        ),
        max_qty=_positive_decimal_attr(
            exchange_rules,
            "exchange_max_order_size",
            "max_order_size",
            "max_qty",
            "maxQty",
        ),
        min_notional=_positive_decimal_attr(
            exchange_rules,
            "exchange_min_notional",
            "min_notional",
            "minNotional",
        ),
        price_tick=_positive_decimal_attr(
            exchange_rules,
            "exchange_tick_size",
            "tick_size",
            "price_tick",
            "price_tick_size",
        ),
        price_precision=_price_precision(exchange_rules),
        reduce_only_supported=_optional_bool_attr(
            exchange_rules,
            "exchange_supports_reduce_only",
            "supports_reduce_only",
            "reduce_only_supported",
        ),
        margin_mode=_normalize_margin_mode(
            _first_attr(exchange_rules, "account_margin_mode", "real_margin_mode", "margin_mode")
        ),
        allowed_margin_modes=_allowed_margin_modes(exchange_rules),
    )


def _rule_warnings(exchange_rules: Any, rules: _OrderRules) -> list[str]:
    warnings: list[str] = []
    if exchange_rules is None:
        warnings.append("Exchange rules are unavailable; missing filters kept requested order values unchanged.")
    if rules.qty_step is None:
        warnings.append("Exchange qty_step is unavailable; quantities were not rounded.")
    if rules.price_tick is None and rules.price_precision is None:
        warnings.append("Exchange tick_size and price_precision are unavailable; prices were not rounded.")
    return warnings


def _round_down_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _round_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        return value
    return (value / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


def _round_to_precision(value: Decimal, precision: int) -> Decimal:
    quant = Decimal("1").scaleb(-precision)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def _risk_trace(
    *,
    plan: RealExecutionPlan,
    normalized_orders: list[ExecutionPlannedOrder],
    requested_quantity: Decimal | None,
    normalized_quantity: Decimal | None,
    requested_entry_price: Decimal | None,
    normalized_entry_price: Decimal | None,
    requested_notional: Decimal | None,
    normalized_notional: Decimal | None,
) -> dict[str, Any]:
    metadata_trace = plan.metadata.get("risk_trace", {})
    effective_risk_per_unit = _decimal_or_none(metadata_trace.get("effective_risk_per_unit"))
    requested_risk_amount = _decimal_or_none(metadata_trace.get("requested_risk_amount"))
    if effective_risk_per_unit is not None and requested_quantity is not None:
        requested_risk_amount = requested_quantity * effective_risk_per_unit
    normalized_risk_amount = (
        normalized_quantity * effective_risk_per_unit
        if effective_risk_per_unit is not None and normalized_quantity is not None
        else None
    )
    return {
        "requested_quantity": _float_or_none(requested_quantity),
        "normalized_quantity": _float_or_none(normalized_quantity),
        "requested_entry_price": _float_or_none(requested_entry_price),
        "normalized_entry_price": _float_or_none(normalized_entry_price),
        "requested_notional": _float_or_none(requested_notional),
        "normalized_notional": _float_or_none(normalized_notional),
        "effective_risk_per_unit": _float_or_none(effective_risk_per_unit),
        "requested_risk_amount": _float_or_none(requested_risk_amount),
        "normalized_risk_amount": _float_or_none(normalized_risk_amount),
        "target_pnl_trace": _target_pnl_trace(
            side=plan.side,
            requested_entry_price=requested_entry_price,
            normalized_entry_price=normalized_entry_price,
            normalized_orders=normalized_orders,
        ),
    }


def _target_pnl_trace(
    *,
    side: str,
    requested_entry_price: Decimal | None,
    normalized_entry_price: Decimal | None,
    normalized_orders: list[ExecutionPlannedOrder],
) -> list[dict[str, Any]]:
    if requested_entry_price is None or normalized_entry_price is None:
        return []
    traces: list[dict[str, Any]] = []
    for order in normalized_orders:
        if order.role != "take_profit":
            continue
        requested_quantity = _decimal_or_none(order.requested_quantity)
        normalized_quantity = _decimal_or_none(order.normalized_quantity)
        requested_price = _decimal_or_none(order.requested_price)
        normalized_price = _decimal_or_none(order.normalized_price)
        requested_pnl = _gross_pnl(
            side=side,
            entry_price=requested_entry_price,
            target_price=requested_price,
            quantity=requested_quantity,
        )
        normalized_pnl = _gross_pnl(
            side=side,
            entry_price=normalized_entry_price,
            target_price=normalized_price,
            quantity=normalized_quantity,
        )
        traces.append(
            {
                "client_order_id": order.client_order_id,
                "target_label": order.metadata.get("target_label"),
                "requested_quantity": _float_or_none(requested_quantity),
                "normalized_quantity": _float_or_none(normalized_quantity),
                "requested_price": _float_or_none(requested_price),
                "normalized_price": _float_or_none(normalized_price),
                "requested_gross_pnl": _float_or_none(requested_pnl),
                "normalized_gross_pnl": _float_or_none(normalized_pnl),
            }
        )
    return traces


def _gross_pnl(
    *,
    side: str,
    entry_price: Decimal,
    target_price: Decimal | None,
    quantity: Decimal | None,
) -> Decimal | None:
    if target_price is None or quantity is None:
        return None
    if side == "short":
        return (entry_price - target_price) * quantity
    return (target_price - entry_price) * quantity


def _adjustment(
    *,
    order: ExecutionPlannedOrder,
    field: str,
    requested: Decimal | None,
    normalized: Decimal | None,
    rule: str,
    reason: str,
) -> OrderRuleAdjustment:
    return OrderRuleAdjustment(
        order_client_id=order.client_order_id,
        role=order.role,
        field=field,
        requested=_float_or_none(requested),
        normalized=_float_or_none(normalized),
        rule=rule,
        reason=reason,
    )


def _positive_decimal_attr(target: Any, *names: str) -> Decimal | None:
    value = _first_attr(target, *names)
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _optional_bool_attr(target: Any, *names: str) -> bool | None:
    value = _first_attr(target, *names)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled", "supported"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", "unsupported"}:
            return False
    return bool(value)


def _price_precision(target: Any) -> int | None:
    value = _first_attr(target, "exchange_price_precision", "price_precision", "pricePrecision")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return min(parsed, 18)


def _allowed_margin_modes(target: Any) -> tuple[str, ...]:
    value = _first_attr(target, "exchange_allowed_margin_modes", "allowed_margin_modes", "margin_modes")
    if value is None:
        return ()
    if isinstance(value, str):
        raw_values = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_values = [str(item).strip() for item in value]
    else:
        return ()
    return tuple(
        normalized
        for normalized in (_normalize_margin_mode(item) for item in raw_values)
        if normalized is not None
    )


def _normalize_margin_mode(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _first_attr(target: Any, *names: str) -> Any:
    if target is None:
        return None
    if isinstance(target, dict):
        for name in names:
            if name in target:
                return target[name]
        return None
    for name in names:
        if hasattr(target, name):
            return getattr(target, name)
    return None


def _multiply(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return left * right


def _float_or_none(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _float_or_original(value: Decimal | None, original: float) -> float:
    return float(value) if value is not None else original


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


order_rule_normalizer = OrderRuleNormalizer()
