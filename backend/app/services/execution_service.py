import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.exchanges.base import DryRunExecutionAdapter, ExchangeExecutionAdapter
from app.schemas.risk import RiskDecision
from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    ExecutionPlannedOrder,
    ManualConfirmRequest,
    RealExecutionPlan,
    RealExecutionResult,
)
from app.schemas.user import RiskManagementSettings
from app.services.risk_audit import RiskAuditService, risk_audit_service
from app.services.risk_fee_rate import RiskFeeRateService, risk_fee_rate_service
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.risk_management import get_user_risk_management_settings
from app.services.risk_market_data import RiskMarketDataService, risk_market_data_service
from app.services.risk_state import RiskStateService, risk_state_service
from app.services.signal_risk_reward import strategy_rr_block_reason


_DEFAULT_EXECUTION_ADAPTER = object()
RiskSettingsProvider = Callable[[str], RiskManagementSettings]


class RealExecutionService:
    """Real-order boundary.

    Every real attempt goes through the backend risk gate before an execution
    plan reaches the configured exchange adapter. The default adapter is dry-run
    and never sends exchange orders.
    """

    def __init__(
        self,
        risk_context_service: RiskContextService | None = None,
        risk_gate_service: RiskGateService | None = None,
        risk_audit: RiskAuditService | None = risk_audit_service,
        risk_state: RiskStateService | None = risk_state_service,
        market_data_service: RiskMarketDataService | None = risk_market_data_service,
        fee_rate_service: RiskFeeRateService | None = risk_fee_rate_service,
        execution_adapter: ExchangeExecutionAdapter | None | object = _DEFAULT_EXECUTION_ADAPTER,
        risk_settings_provider: RiskSettingsProvider | None = None,
    ) -> None:
        self._risk_context_service = risk_context_service or RiskContextService()
        self._risk_gate_service = risk_gate_service or RiskGateService()
        self._risk_audit = risk_audit
        self._risk_state = risk_state
        self._market_data_service = market_data_service
        self._fee_rate_service = fee_rate_service
        self._execution_adapter = (
            DryRunExecutionAdapter()
            if execution_adapter is _DEFAULT_EXECUTION_ADAPTER
            else execution_adapter
        )
        self._risk_settings_provider = risk_settings_provider or get_user_risk_management_settings

    async def place_order(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> RealExecutionResult:
        rr_block_reason = strategy_rr_block_reason(signal)
        if rr_block_reason is not None:
            return RealExecutionResult(
                status="risk_failed",
                exchange=signal.exchange,
                symbol=signal.symbol,
                message=f"Strategy risk/reward blocked real order: {rr_block_reason}",
            )

        risk_settings = self._risk_settings_provider(request.user_id)
        instrument_type = "futures" if request.leverage > 1 else "spot"
        fallback_entry_price = _entry_price(signal)
        market_data = (
            self._market_data_service.build_snapshot(
                exchange=signal.exchange,
                symbol=signal.symbol,
                side=signal.direction,
                mode="real",
                instrument_type=instrument_type,
                fallback_entry_price=fallback_entry_price,
                manual_slippage_bps=request.slippage_bps,
                user_id=request.user_id,
            )
            if self._market_data_service is not None
            else None
        )
        if market_data is not None:
            fee_rate = (
                self._fee_rate_service.resolve(
                    user_id=request.user_id,
                    exchange=signal.exchange,
                    mode="real",
                    instrument_type=instrument_type,
                    symbol=signal.symbol,
                    risk_settings=risk_settings,
                    requested_fee_rate=request.fee_rate,
                )
                if self._fee_rate_service is not None
                else None
            )
            request = request.model_copy(
                update={
                    "fee_rate": fee_rate.fee_rate if fee_rate is not None else request.fee_rate,
                    "slippage_bps": market_data.slippage_bps,
                    "liquidation_price": request.liquidation_price or market_data.liquidation_price,
                }
            )
        else:
            fee_rate = (
                self._fee_rate_service.resolve(
                    user_id=request.user_id,
                    exchange=signal.exchange,
                    mode="real",
                    instrument_type=instrument_type,
                    symbol=signal.symbol,
                    risk_settings=risk_settings,
                    requested_fee_rate=request.fee_rate,
                )
                if self._fee_rate_service is not None
                else None
            )
            if fee_rate is not None:
                request = request.model_copy(update={"fee_rate": fee_rate.fee_rate})
        entry_price = market_data.entry_price if market_data is not None else fallback_entry_price
        reference = (
            self._risk_state.get_reference(
                user_id=request.user_id,
                mode="real",
                exchange=signal.exchange,
                symbol=signal.symbol,
                side=signal.direction,
                instrument_type=instrument_type,
            )
            if self._risk_state is not None
            else None
        )
        risk_decision = self._risk_gate_service.evaluate(
            context=self._risk_context_service.build_real_context(
                signal=signal,
                request=request,
                entry_price=entry_price,
                requested_notional=request.size_usd,
                instrument_type=instrument_type,
                stage="pre_execution",
                exchange_min_order_size=(
                    reference.exchange_min_order_size if reference is not None else None
                ),
                exchange_max_order_size=(
                    reference.exchange_max_order_size if reference is not None else None
                ),
                exchange_min_notional=(
                    reference.exchange_min_notional if reference is not None else None
                ),
                exchange_max_leverage=(
                    reference.exchange_max_leverage if reference is not None else None
                ),
                exchange_rule_status=(
                    reference.exchange_rule_status if reference is not None else "unknown"
                ),
                exchange_rule_age_seconds=(
                    reference.exchange_rule_age_seconds if reference is not None else None
                ),
                exchange_rule_ttl_seconds=(
                    reference.exchange_rule_ttl_seconds if reference is not None else None
                ),
                liquidation_price=market_data.liquidation_price if market_data is not None else None,
                funding_buffer_per_unit=market_data.funding_buffer_per_unit if market_data is not None else 0.0,
                best_bid=market_data.best_bid if market_data is not None else None,
                best_ask=market_data.best_ask if market_data is not None else None,
                mark_price=market_data.mark_price if market_data is not None else None,
                funding_rate=market_data.funding_rate if market_data is not None else None,
                spread_percent=market_data.spread_percent if market_data is not None else None,
                spread_bps=market_data.spread_bps if market_data is not None else None,
                orderbook_depth_usd=market_data.orderbook_depth_usd if market_data is not None else None,
                market_data_status=market_data.market_data_status if market_data is not None else "unknown",
                market_data_source=market_data.market_data_source if market_data is not None else None,
                market_data_warnings=list(market_data.warnings) if market_data is not None else [],
                fee_rate_source=fee_rate.source if fee_rate is not None else None,
                maker_fee_rate=fee_rate.maker_fee_rate if fee_rate is not None else None,
                taker_fee_rate=fee_rate.taker_fee_rate if fee_rate is not None else None,
                fee_rate_warnings=list(fee_rate.warnings) if fee_rate is not None else [],
                open_risk_amount=reference.open_risk_amount if reference is not None else 0.0,
                correlated_open_risk_amount=(
                    reference.correlated_open_risk_amount if reference is not None else 0.0
                ),
                daily_loss_amount=reference.daily_loss_amount if reference is not None else 0.0,
                correlation_group=reference.correlation_group if reference is not None else None,
                protection_state=reference.protection_state if reference is not None else "normal",
                protection_reason=reference.protection_reason if reference is not None else None,
                user_mode_multiplier=reference.user_mode_multiplier if reference is not None else 1.0,
            ),
            risk_settings=risk_settings,
        )
        risk_decision_id = self._record_real_attempt(signal, request, risk_decision)
        if not risk_decision.can_enter:
            return RealExecutionResult(
                status="risk_failed",
                exchange=signal.exchange,
                symbol=signal.symbol,
                message="Risk gate blocked real order: " + "; ".join(risk_decision.blockers),
                risk_decision=risk_decision,
                risk_decision_id=risk_decision_id,
            )
        execution_plan = _build_execution_plan(
            signal=signal,
            request=request,
            risk_decision=risk_decision,
        )
        validation_errors = _validate_execution_plan(
            plan=execution_plan,
            risk_decision=risk_decision,
            reference=reference,
        )
        if validation_errors:
            return RealExecutionResult(
                status="risk_failed",
                exchange=signal.exchange,
                symbol=signal.symbol,
                message="Execution plan validation failed: " + "; ".join(validation_errors),
                risk_decision=risk_decision,
                risk_decision_id=risk_decision_id,
                execution_plan=execution_plan,
                planned_orders=execution_plan.planned_orders,
                idempotency_key=execution_plan.idempotency_key,
                validation_errors=validation_errors,
            )
        if self._execution_adapter is None:
            return RealExecutionResult(
                exchange=signal.exchange,
                symbol=signal.symbol,
                message=(
                    "Real trade execution adapter is not configured. "
                    "No exchange order was sent."
                ),
                risk_decision=risk_decision,
                risk_decision_id=risk_decision_id,
                execution_plan=execution_plan,
                planned_orders=execution_plan.planned_orders,
                idempotency_key=execution_plan.idempotency_key,
            )

        planned_orders = await _place_execution_plan(
            execution_plan,
            self._execution_adapter,
        )
        adapter_name = getattr(self._execution_adapter, "name", "unknown")
        status = "dry_run" if getattr(self._execution_adapter, "is_dry_run", False) else "submitted"
        execution_plan = execution_plan.model_copy(update={"planned_orders": planned_orders})
        return RealExecutionResult(
            status=status,
            exchange=signal.exchange,
            symbol=signal.symbol,
            message=(
                "Dry-run real execution plan built. No exchange order was sent."
                if status == "dry_run"
                else "Real execution adapter submitted the order plan."
            ),
            risk_decision=risk_decision,
            risk_decision_id=risk_decision_id,
            execution_plan=execution_plan,
            planned_orders=planned_orders,
            idempotency_key=execution_plan.idempotency_key,
            adapter=adapter_name,
        )

    def _record_real_attempt(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        risk_decision: Any,
    ) -> str | None:
        if self._risk_audit is None:
            return None
        record_id = self._risk_audit.record_decision(
            decision=risk_decision,
            user_id=request.user_id,
            signal_id=signal.id,
            input_snapshot={
                "flow": "real_order.attempt",
                "request": request.model_dump(mode="json"),
                "signal": signal.model_dump(mode="json"),
            },
        )
        return str(record_id)


def _entry_price(signal: RadarSignal) -> float:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    if signal.entry_max is not None:
        return signal.entry_max
    raise ValueError("Signal has no entry zone")


def _build_execution_plan(
    *,
    signal: RadarSignal,
    request: ManualConfirmRequest,
    risk_decision: RiskDecision,
) -> RealExecutionPlan:
    sizing = risk_decision.checked_position_sizing
    side = signal.direction
    entry_side = _entry_order_side(side)
    exit_side = _exit_order_side(side)
    digest = _execution_intent_digest(
        signal=signal,
        request=request,
        risk_decision=risk_decision,
    )
    idempotency_key = f"real-exec:{digest}"
    client_order_id = f"cr-{digest[:20]}"
    entry_client_order_id = _order_client_id(digest, "entry")
    stop_client_order_id = _order_client_id(digest, "sl")
    orders = [
        ExecutionPlannedOrder(
            role="entry",
            exchange=signal.exchange,
            symbol=signal.symbol,
            side=entry_side,
            order_type="market",
            quantity=sizing.position_size_base,
            price=sizing.entry_price,
            reduce_only=False,
            client_order_id=entry_client_order_id,
            idempotency_key=f"{idempotency_key}:entry",
            metadata={
                "signal_id": signal.id,
                "strategy": signal.strategy,
                "timeframe": signal.timeframe,
                "role": "entry",
                "client_order_id": entry_client_order_id,
                "reduce_only": False,
            },
        ),
        ExecutionPlannedOrder(
            role="protective_stop",
            exchange=signal.exchange,
            symbol=signal.symbol,
            side=exit_side,
            order_type="stop",
            quantity=sizing.position_size_base,
            stop_price=risk_decision.stop_loss_plan.stop_loss_price,
            reduce_only=True,
            client_order_id=stop_client_order_id,
            idempotency_key=f"{idempotency_key}:sl",
            metadata={
                "signal_id": signal.id,
                "stop_loss_source": risk_decision.stop_loss_plan.source,
                "role": "protective_stop",
                "client_order_id": stop_client_order_id,
                "reduce_only": True,
            },
        ),
    ]
    for index, target in enumerate(risk_decision.take_profit_plan.targets, start=1):
        if target.close_percent <= 0:
            continue
        tp_client_order_id = _order_client_id(digest, f"tp{index}")
        orders.append(
            ExecutionPlannedOrder(
                role="take_profit",
                exchange=signal.exchange,
                symbol=signal.symbol,
                side=exit_side,
                order_type="take_profit",
                quantity=sizing.position_size_base * target.close_percent / 100,
                price=target.price,
                reduce_only=True,
                close_percent=target.close_percent,
                client_order_id=tp_client_order_id,
                idempotency_key=f"{idempotency_key}:tp{index}",
                metadata={
                    "signal_id": signal.id,
                    "target_label": target.label,
                    "r_multiple": target.r_multiple,
                    "action": target.action,
                    "take_profit_source": risk_decision.take_profit_plan.source,
                    "role": "take_profit",
                    "client_order_id": tp_client_order_id,
                    "reduce_only": True,
                },
            )
        )
    return RealExecutionPlan(
        exchange=signal.exchange,
        symbol=signal.symbol,
        side=side,
        entry_price=sizing.entry_price,
        quantity=sizing.position_size_base,
        notional=sizing.notional,
        leverage=sizing.leverage,
        idempotency_key=idempotency_key,
        client_order_id=client_order_id,
        planned_orders=orders,
        metadata={
            "signal_id": signal.id,
            "strategy": signal.strategy,
            "timeframe": signal.timeframe,
            "risk_status": risk_decision.status,
        },
    )


def _validate_execution_plan(
    *,
    plan: RealExecutionPlan,
    risk_decision: RiskDecision,
    reference: Any,
) -> list[str]:
    errors: list[str] = []
    entry_orders = [order for order in plan.planned_orders if order.role == "entry"]
    stop_orders = [order for order in plan.planned_orders if order.role == "protective_stop"]
    take_profit_orders = [order for order in plan.planned_orders if order.role == "take_profit"]
    if len(entry_orders) != 1:
        errors.append("Execution plan must contain exactly one entry order.")
    if not stop_orders:
        errors.append("Execution plan must contain a protective stop order.")
    if not take_profit_orders:
        errors.append("Execution plan must contain at least one take-profit order.")
    if not risk_decision.risk_check.protective_orders_allowed:
        errors.append("Protective orders are not allowed by the current risk state.")

    for order in stop_orders:
        if not order.reduce_only:
            errors.append("Protective stop order must be reduce-only.")
        if order.stop_price is None:
            errors.append("Protective stop order must include stop_price.")
            continue
        if plan.side == "long" and order.stop_price >= plan.entry_price:
            errors.append("Protective stop must be below entry for long trades.")
        if plan.side == "short" and order.stop_price <= plan.entry_price:
            errors.append("Protective stop must be above entry for short trades.")

    for order in take_profit_orders:
        if not order.reduce_only:
            errors.append("Take-profit order must be reduce-only.")
        if order.close_percent is None or order.close_percent <= 0:
            errors.append("Take-profit order must include a positive close_percent.")
        if order.price is None:
            errors.append("Take-profit order must include price.")
            continue
        if plan.side == "long" and order.price <= plan.entry_price:
            errors.append("Take-profit order must be above entry for long trades.")
        if plan.side == "short" and order.price >= plan.entry_price:
            errors.append("Take-profit order must be below entry for short trades.")

    qty_step = _reference_number(reference, "exchange_qty_step", "qty_step")
    tick_size = _reference_number(reference, "exchange_tick_size", "tick_size")
    if qty_step is not None:
        for order in plan.planned_orders:
            if not _is_step_aligned(order.quantity, qty_step):
                errors.append(f"Order {order.client_order_id} quantity is not aligned to qty_step.")
    if tick_size is not None:
        for order in plan.planned_orders:
            for field_name, value in (("price", order.price), ("stop_price", order.stop_price)):
                if value is not None and not _is_step_aligned(value, tick_size):
                    errors.append(
                        f"Order {order.client_order_id} {field_name} is not aligned to tick_size."
                    )
    return _dedupe(errors)


async def _place_execution_plan(
    plan: RealExecutionPlan,
    adapter: ExchangeExecutionAdapter,
) -> list[ExecutionPlannedOrder]:
    placed: list[ExecutionPlannedOrder] = []
    for order in plan.planned_orders:
        if order.role == "entry":
            placed.append(await adapter.place_order(order))
        elif order.role == "protective_stop":
            placed.append(await adapter.place_protective_stop(order))
        else:
            placed.append(await adapter.place_take_profit(order))
    return placed


def _execution_intent_digest(
    *,
    signal: RadarSignal,
    request: ManualConfirmRequest,
    risk_decision: RiskDecision,
) -> str:
    sizing = risk_decision.checked_position_sizing
    intent = {
        "version": "real_execution_plan_v1",
        "user_id": request.user_id,
        "signal_id": signal.id,
        "exchange": signal.exchange.strip().lower(),
        "symbol": signal.symbol.strip().upper(),
        "side": signal.direction,
        "entry_price": sizing.entry_price,
        "quantity": sizing.position_size_base,
        "notional": sizing.notional,
        "leverage": sizing.leverage,
        "stop_loss": risk_decision.stop_loss_plan.stop_loss_price,
        "targets": [
            {
                "label": target.label,
                "price": target.price,
                "close_percent": target.close_percent,
            }
            for target in risk_decision.take_profit_plan.targets
            if target.close_percent > 0
        ],
    }
    payload = json.dumps(intent, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _order_client_id(digest: str, suffix: str) -> str:
    return f"cr-{digest[:18]}-{suffix}"


def _entry_order_side(side: str) -> str:
    return "buy" if side == "long" else "sell"


def _exit_order_side(side: str) -> str:
    return "sell" if side == "long" else "buy"


def _reference_number(reference: Any, *names: str) -> float | None:
    if reference is None:
        return None
    for name in names:
        value = getattr(reference, name, None)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _is_step_aligned(value: float, step: float) -> bool:
    try:
        value_decimal = Decimal(str(value))
        step_decimal = Decimal(str(step))
    except (InvalidOperation, ValueError):
        return False
    if step_decimal <= 0:
        return True
    quotient = value_decimal / step_decimal
    nearest = quotient.to_integral_value()
    return abs(quotient - nearest) <= Decimal("0.00000001")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


real_execution_service = RealExecutionService()
