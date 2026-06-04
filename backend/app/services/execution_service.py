import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.exchanges.base import (
    DryRunExecutionAdapter,
    ExchangeExecutionAdapter,
    exchange_execution_capabilities,
    protective_order_strategy_for_adapter,
)
from app.schemas.lifecycle import LifecycleTrace
from app.schemas.risk import AccountRiskSnapshot, RiskDecision
from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    ExecutionPlannedOrder,
    ManualConfirmRequest,
    RealExecutionPlan,
    RealExecutionResult,
    RealExecutionStatus,
)
from app.schemas.user import RiskManagementSettings
from app.services.risk_audit import RiskAuditService, risk_audit_service
from app.services.risk_fee_rate import RiskFeeRateService, risk_fee_rate_service
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.risk_management import (
    execution_profile_resolver,
    get_user_risk_management_settings,
    request_risk_override_to_execution_settings,
    resolved_risk_profile_source,
)
from app.services.risk_market_data import RiskMarketDataService, risk_market_data_service
from app.services.order_rule_normalizer import (
    OrderRuleNormalizer,
    order_rule_normalizer,
)
from app.services.real_execution_readiness import (
    RealExecutionReadinessService,
    RealExecutionReadinessResult,
    real_execution_readiness_service,
)
from app.services.exchange_account_snapshot import exchange_account_snapshot_service
from app.services.risk_state import RiskStateService, risk_state_service
from app.services.strategy_config_service import strategy_config_service


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
        readiness_service: RealExecutionReadinessService | None = real_execution_readiness_service,
        order_plan_normalizer: OrderRuleNormalizer | None = order_rule_normalizer,
        execution_adapter: ExchangeExecutionAdapter | None | object = _DEFAULT_EXECUTION_ADAPTER,
        risk_settings_provider: RiskSettingsProvider | None = None,
        account_snapshot_provider: Any | None = None,
    ) -> None:
        self._risk_context_service = risk_context_service or RiskContextService()
        self._risk_gate_service = risk_gate_service or RiskGateService()
        self._risk_audit = risk_audit
        self._risk_state = risk_state
        self._market_data_service = market_data_service
        self._fee_rate_service = fee_rate_service
        self._readiness_service = readiness_service or RealExecutionReadinessService()
        self._order_plan_normalizer = order_plan_normalizer or OrderRuleNormalizer()
        self._execution_adapter = (
            DryRunExecutionAdapter()
            if execution_adapter is _DEFAULT_EXECUTION_ADAPTER
            else execution_adapter
        )
        self._risk_settings_provider = risk_settings_provider or get_user_risk_management_settings
        if account_snapshot_provider is not None:
            self._account_snapshot_provider = account_snapshot_provider
        elif self._risk_state is not None:
            self._account_snapshot_provider = self._risk_state
        else:
            self._account_snapshot_provider = exchange_account_snapshot_service

    async def place_order(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> RealExecutionResult:
        backend_configuration_blocker = _adapter_live_order_placement_safety_reason(
            self._execution_adapter
        )
        if backend_configuration_blocker is not None:
            lifecycle_trace = _request_lifecycle_trace(signal, request)
            return RealExecutionResult(
                status="not_implemented",
                signal_valid=True,
                execution_allowed=False,
                exchange=signal.exchange,
                symbol=signal.symbol,
                message=backend_configuration_blocker,
                adapter=getattr(self._execution_adapter, "name", None),
                validation_errors=[backend_configuration_blocker],
                lifecycle_trace=lifecycle_trace,
            )

        risk_settings = self._risk_settings_provider(request.user_id)
        instrument_type = "futures" if _request_profile_leverage(request) > 1 else "spot"
        strategy_risk_settings, strategy_risk_settings_source = _strategy_risk_settings(
            signal,
            user_id=request.user_id,
        )
        execution_profile = execution_profile_resolver.resolve(
            user_risk_settings=risk_settings,
            strategy_execution_settings=strategy_risk_settings,
            request_override=request_risk_override_to_execution_settings(request.risk_override),
            mode="real",
            instrument_type=instrument_type,
            strategy=signal.strategy,
        )
        risk_profile_source = resolved_risk_profile_source(execution_profile)
        risk_settings = execution_profile_resolver.apply_to_risk_settings(
            risk_settings,
            execution_profile,
        )
        request = request.model_copy(update={"leverage": int(execution_profile.leverage)})
        instrument_type = execution_profile.instrument_type
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
        not_implemented_reason = _adapter_not_implemented_reason(self._execution_adapter)
        live_adapter = (
            self._execution_adapter is not None
            and not bool(getattr(self._execution_adapter, "is_dry_run", False))
            and not_implemented_reason is None
        )
        account_snapshot = self._get_real_account_snapshot(
            user_id=request.user_id,
            exchange=signal.exchange,
            mode="real",
            live_adapter=live_adapter,
            request_account_balance=request.account_balance,
            reference=reference,
        )
        account_snapshot_blockers = _live_account_snapshot_blockers(account_snapshot) if live_adapter else []
        if account_snapshot_blockers:
            lifecycle_trace = _request_lifecycle_trace(signal, request)
            return RealExecutionResult(
                status="risk_failed",
                signal_valid=True,
                execution_allowed=False,
                exchange=signal.exchange,
                symbol=signal.symbol,
                message="Real execution account snapshot failed: " + "; ".join(account_snapshot_blockers),
                validation_errors=account_snapshot_blockers,
                lifecycle_trace=lifecycle_trace,
            )
        risk_decision = self._risk_gate_service.evaluate(
            context=self._risk_context_service.build_real_context(
                signal=signal,
                request=request,
                entry_price=entry_price,
                account_snapshot=account_snapshot,
                allow_request_account_balance=not live_adapter,
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
                instrument_rules=(
                    getattr(reference, "exchange_instrument_rules", None)
                    if reference is not None
                    else None
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
                orderbook_snapshot=market_data.orderbook_snapshot if market_data is not None else None,
                market_data_status=market_data.market_data_status if market_data is not None else "unknown",
                market_data_source=market_data.market_data_source if market_data is not None else None,
                market_data_warnings=list(market_data.warnings) if market_data is not None else [],
                fee_rate_source=fee_rate.source if fee_rate is not None else None,
                maker_fee_rate=fee_rate.maker_fee_rate if fee_rate is not None else None,
                taker_fee_rate=fee_rate.taker_fee_rate if fee_rate is not None else None,
                fee_rate_warnings=list(fee_rate.warnings) if fee_rate is not None else [],
                risk_profile_source=risk_profile_source,
                execution_profile_sources=execution_profile.sources,
                execution_profile=execution_profile,
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
        risk_decision_id = self._record_real_attempt(
            signal,
            request,
            risk_decision,
            execution_profile=execution_profile,
            strategy_risk_settings_source=strategy_risk_settings_source,
            account_snapshot=account_snapshot,
        )
        lifecycle_trace = _execution_lifecycle_trace(risk_decision, risk_decision_id)
        if not risk_decision.can_enter:
            message = _risk_rejection_message(risk_decision)
            return RealExecutionResult(
                status="risk_failed",
                signal_valid=True,
                execution_allowed=False,
                exchange=signal.exchange,
                symbol=signal.symbol,
                message=message,
                risk_decision=risk_decision,
                risk_decision_id=risk_decision_id,
                lifecycle_trace=lifecycle_trace,
            )
        execution_plan = _build_execution_plan(
            signal=signal,
            request=request,
            risk_decision=risk_decision,
            lifecycle_trace=lifecycle_trace,
            adapter=self._execution_adapter,
            account_snapshot=account_snapshot,
        )
        normalization = self._order_plan_normalizer.normalize_order_plan(
            execution_plan,
            reference,
        )
        execution_plan = normalization.plan
        validation_errors = _validate_execution_plan(
            plan=execution_plan,
            risk_decision=risk_decision,
            reference=reference,
        )
        validation_errors = _dedupe([*normalization.errors, *validation_errors])
        if validation_errors:
            return RealExecutionResult(
                status="risk_failed",
                signal_valid=True,
                execution_allowed=False,
                exchange=signal.exchange,
                symbol=signal.symbol,
                message="Execution plan validation failed: " + "; ".join(validation_errors),
                risk_decision=risk_decision,
                risk_decision_id=risk_decision_id,
                execution_plan=execution_plan,
                planned_orders=execution_plan.planned_orders,
                idempotency_key=execution_plan.idempotency_key,
                warnings=normalization.warnings,
                validation_errors=validation_errors,
                lifecycle_trace=execution_plan.lifecycle_trace,
            )
        if not_implemented_reason is not None:
            return RealExecutionResult(
                status="not_implemented",
                signal_valid=True,
                execution_allowed=True,
                exchange=signal.exchange,
                symbol=signal.symbol,
                message=not_implemented_reason,
                risk_decision=risk_decision,
                risk_decision_id=risk_decision_id,
                execution_plan=execution_plan,
                planned_orders=execution_plan.planned_orders,
                idempotency_key=execution_plan.idempotency_key,
                adapter=getattr(self._execution_adapter, "name", None),
                warnings=normalization.warnings,
                lifecycle_trace=execution_plan.lifecycle_trace,
            )

        readiness = self._readiness_service.evaluate(
            signal=signal,
            request=request,
            risk_decision=risk_decision,
            execution_plan=execution_plan,
            risk_settings=risk_settings,
            reference=reference,
            fee_rate=fee_rate,
            account_snapshot=account_snapshot,
            adapter=self._execution_adapter,
        )
        execution_plan = _execution_plan_with_readiness(execution_plan, readiness)
        if not readiness.ready:
            return RealExecutionResult(
                status="readiness_failed",
                signal_valid=True,
                execution_allowed=False,
                exchange=signal.exchange,
                symbol=signal.symbol,
                message=_readiness_rejection_message(readiness.blockers),
                risk_decision=risk_decision,
                risk_decision_id=risk_decision_id,
                execution_plan=execution_plan,
                planned_orders=execution_plan.planned_orders,
                idempotency_key=execution_plan.idempotency_key,
                warnings=_dedupe([*normalization.warnings, *readiness.warnings]),
                validation_errors=readiness.blockers,
                lifecycle_trace=execution_plan.lifecycle_trace,
            )

        planned_orders = await _place_execution_plan(
            execution_plan,
            self._execution_adapter,
        )
        adapter_name = getattr(self._execution_adapter, "name", "unknown")
        result_status = _real_execution_status_from_orders(
            adapter_is_dry_run=getattr(self._execution_adapter, "is_dry_run", False),
            planned_orders=planned_orders,
        )
        execution_plan = _execution_plan_with_placed_orders(
            execution_plan,
            planned_orders=planned_orders,
            adapter_is_dry_run=getattr(self._execution_adapter, "is_dry_run", False),
        )
        lifecycle_trace = execution_plan.lifecycle_trace
        return RealExecutionResult(
            status=result_status,
            signal_valid=True,
            execution_allowed=True,
            exchange=signal.exchange,
            symbol=signal.symbol,
            message=_real_execution_message(result_status),
            risk_decision=risk_decision,
            risk_decision_id=risk_decision_id,
            execution_plan=execution_plan,
            planned_orders=planned_orders,
            idempotency_key=execution_plan.idempotency_key,
            adapter=adapter_name,
            warnings=_dedupe([*normalization.warnings, *readiness.warnings]),
            lifecycle_trace=lifecycle_trace,
        )

    def _record_real_attempt(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        risk_decision: Any,
        execution_profile: Any,
        strategy_risk_settings_source: str,
        account_snapshot: AccountRiskSnapshot | None,
    ) -> str | None:
        if self._risk_audit is None:
            return None
        record_id = self._risk_audit.record_decision(
            decision=risk_decision,
            user_id=request.user_id,
            signal_id=signal.id,
            pending_entry_intent_id=risk_decision.lifecycle_trace.pending_entry_intent_id,
            input_snapshot={
                "flow": "real_order.attempt",
                "lifecycle_trace": risk_decision.lifecycle_trace.model_dump(mode="json", exclude_none=True),
                "request": request.model_dump(mode="json"),
                "signal": signal.model_dump(mode="json"),
                "execution_profile": execution_profile.model_dump(mode="json"),
                "account_snapshot": (
                    account_snapshot.model_dump(mode="json")
                    if account_snapshot is not None
                    else None
                ),
                "risk_profile_source": resolved_risk_profile_source(execution_profile),
                "strategy_risk_settings_source": strategy_risk_settings_source,
            },
        )
        return str(record_id)

    def _get_real_account_snapshot(
        self,
        *,
        user_id: str,
        exchange: str,
        mode: str,
        live_adapter: bool,
        request_account_balance: float,
        reference: Any,
    ) -> AccountRiskSnapshot:
        provider = self._account_snapshot_provider
        if hasattr(provider, "get_real_account_snapshot"):
            return provider.get_real_account_snapshot(
                user_id=user_id,
                exchange=exchange,
                mode=mode,
                live_adapter=live_adapter,
                request_account_balance=request_account_balance,
                reference=reference,
            )
        if live_adapter and hasattr(provider, "get_snapshot"):
            return provider.get_snapshot(
                user_id=user_id,
                exchange=exchange,
                mode="real",
            )
        return RiskStateService().get_real_account_snapshot(
            user_id=user_id,
            exchange=exchange,
            mode=mode,
            live_adapter=live_adapter,
            request_account_balance=request_account_balance,
            reference=reference,
        )


def _entry_price(signal: RadarSignal) -> float:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    if signal.entry_max is not None:
        return signal.entry_max
    raise ValueError("Signal has no entry zone")


def _request_profile_leverage(request: ManualConfirmRequest) -> int:
    if request.risk_override is not None and request.risk_override.leverage is not None:
        return int(request.risk_override.leverage)
    return request.leverage


def _request_lifecycle_trace(signal: RadarSignal, request: ManualConfirmRequest) -> LifecycleTrace:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    raw_trace = metadata.get("lifecycle_trace")
    if isinstance(raw_trace, LifecycleTrace):
        trace = raw_trace
    elif isinstance(raw_trace, dict):
        try:
            trace = LifecycleTrace.model_validate(raw_trace)
        except ValueError:
            trace = LifecycleTrace()
    else:
        trace = LifecycleTrace()
    return trace.model_copy(
        update={
            "signal_id": signal.id,
            "pending_entry_intent_id": (
                metadata.get("pending_entry_intent_id")
                or trace.pending_entry_intent_id
            ),
        }
    )


def _execution_lifecycle_trace(
    risk_decision: RiskDecision,
    risk_decision_id: str | None,
) -> LifecycleTrace:
    return risk_decision.lifecycle_trace.model_copy(
        update={
            "risk_decision_id": risk_decision_id,
            "audit_id": risk_decision_id,
        }
    )


def _strategy_risk_settings(signal: RadarSignal, *, user_id: str) -> tuple[dict[str, Any], str]:
    try:
        configs = strategy_config_service.list_configs(user_id=user_id)
    except Exception as exc:
        return {}, f"unavailable:{exc.__class__.__name__}"
    signal_exchange = signal.exchange.strip().lower()
    signal_symbol = signal.symbol.strip().upper()
    for config in configs:
        if config.strategy_code != signal.strategy:
            continue
        if config.timeframes and signal.timeframe not in config.timeframes:
            continue
        if config.pairs:
            pairs = {
                (pair.exchange.strip().lower(), pair.symbol.strip().upper())
                for pair in config.pairs
            }
            if (signal_exchange, signal_symbol) not in pairs:
                continue
        elif config.exchanges and signal_exchange not in {exchange.strip().lower() for exchange in config.exchanges}:
            continue
        return config.risk_settings.to_legacy_dict(), "strategy_config"
    return {}, "not_configured"


def _risk_rejection_message(risk_decision: RiskDecision) -> str:
    rr_reason = risk_decision.risk_check.risk_reward_block_reason
    if rr_reason:
        return rr_reason
    if risk_decision.blockers:
        return "Execution not allowed by risk gate: " + "; ".join(risk_decision.blockers)
    return "Real execution rejected by risk policy."


def _live_account_snapshot_blockers(account_snapshot: AccountRiskSnapshot | None) -> list[str]:
    if account_snapshot is None:
        return ["Fresh exchange account snapshot is required before live entry."]
    blockers: list[str] = []
    if account_snapshot.status != "fresh":
        blockers.append("Fresh exchange account snapshot is required before live entry.")
    if account_snapshot.source != "exchange":
        blockers.append("Live entry requires source=exchange account snapshot.")
    if account_snapshot.account_equity is None or account_snapshot.account_equity <= 0:
        blockers.append("Exchange account equity is missing.")
    if account_snapshot.available_balance is None or account_snapshot.available_balance <= 0:
        blockers.append("Exchange available balance is insufficient.")
    return _dedupe(blockers)


def _readiness_rejection_message(blockers: list[str]) -> str:
    if blockers:
        return "Real execution readiness failed: " + "; ".join(blockers)
    return "Real execution readiness failed."


def _adapter_not_implemented_reason(adapter: Any | None) -> str | None:
    if adapter is None:
        return "Real trade execution adapter is not configured. No exchange order was sent."
    if bool(getattr(adapter, "is_dry_run", False)):
        return None
    safety_reason = _adapter_live_order_placement_safety_reason(adapter)
    if safety_reason is not None:
        return safety_reason
    implemented = getattr(adapter, "live_order_placement_implemented", None)
    if implemented is False:
        adapter_name = getattr(adapter, "name", "unknown")
        return (
            f"Live real execution adapter {adapter_name!r} is not implemented. "
            "No exchange order was sent."
        )
    return None


def _adapter_live_order_placement_safety_reason(adapter: Any | None) -> str | None:
    if adapter is None or bool(getattr(adapter, "is_dry_run", False)):
        return None
    checker = getattr(adapter, "live_order_placement_safety_reason", None)
    reason = checker() if callable(checker) else checker
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return None


def _real_execution_status_from_orders(
    *,
    adapter_is_dry_run: bool,
    planned_orders: list[ExecutionPlannedOrder],
) -> RealExecutionStatus:
    if adapter_is_dry_run:
        return "dry_run"
    if any(_order_is_failed(order) for order in planned_orders):
        return "failed"
    if any(_order_is_partially_filled(order) for order in planned_orders):
        return "partially_filled"
    return "submitted"


def _real_execution_message(result_status: RealExecutionStatus) -> str:
    if result_status == "dry_run":
        return "Dry-run real execution plan built. No exchange order was sent."
    if result_status == "partially_filled":
        return "Real execution adapter returned a partial fill; reconciliation is required."
    if result_status == "failed":
        return "Real execution adapter returned a failed order placement result."
    return "Real execution adapter submitted the order plan."


def _order_is_partially_filled(order: ExecutionPlannedOrder) -> bool:
    return (
        order.status == "partially_filled"
        or (
            order.filled_qty is not None
            and order.filled_qty > 0
            and order.remaining_qty is not None
            and order.remaining_qty > 0
        )
    )


def _order_is_failed(order: ExecutionPlannedOrder) -> bool:
    return order.status in {"cancelled", "canceled", "rejected", "expired", "unknown"}


def _build_execution_plan(
    *,
    signal: RadarSignal,
    request: ManualConfirmRequest,
    risk_decision: RiskDecision,
    lifecycle_trace: LifecycleTrace,
    adapter: Any | None,
    account_snapshot: AccountRiskSnapshot | None = None,
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
    plan_version = "real_execution_plan_v1"
    protective_order_strategy = protective_order_strategy_for_adapter(adapter)
    adapter_capabilities = exchange_execution_capabilities(adapter)
    idempotency_key = f"real-exec:{digest}"
    client_order_id = f"cr-{digest[:20]}"
    entry_client_order_id = _order_client_id(digest, "entry")
    stop_client_order_id = _order_client_id(digest, "protective_stop")
    plan_trace = lifecycle_trace.model_copy(
        update={
            "signal_id": signal.id,
            "real_order_id": entry_client_order_id,
        }
    )
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
            lifecycle_trace=plan_trace.model_copy(update={"real_order_id": entry_client_order_id}),
            metadata={
                "signal_id": signal.id,
                "lifecycle_trace": plan_trace.model_copy(
                    update={"real_order_id": entry_client_order_id}
                ).model_dump(mode="json", exclude_none=True),
                "plan_version": plan_version,
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
            lifecycle_trace=plan_trace.model_copy(update={"real_order_id": stop_client_order_id}),
            metadata={
                "signal_id": signal.id,
                "lifecycle_trace": plan_trace.model_copy(
                    update={"real_order_id": stop_client_order_id}
                ).model_dump(mode="json", exclude_none=True),
                "plan_version": plan_version,
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
                lifecycle_trace=plan_trace.model_copy(update={"real_order_id": tp_client_order_id}),
                metadata={
                    "signal_id": signal.id,
                    "lifecycle_trace": plan_trace.model_copy(
                        update={"real_order_id": tp_client_order_id}
                    ).model_dump(mode="json", exclude_none=True),
                    "plan_version": plan_version,
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
        requested_quantity=sizing.position_size_base,
        requested_entry_price=sizing.entry_price,
        requested_notional=sizing.notional,
        margin_mode=account_snapshot.margin_mode if account_snapshot is not None else None,
        leverage=sizing.leverage,
        idempotency_key=idempotency_key,
        client_order_id=client_order_id,
        protective_order_strategy=protective_order_strategy,
        planned_orders=orders,
        lifecycle_trace=plan_trace,
        metadata={
            "signal_id": signal.id,
            "lifecycle_trace": plan_trace.model_dump(mode="json", exclude_none=True),
            "plan_version": plan_version,
            "strategy": signal.strategy,
            "timeframe": signal.timeframe,
            "risk_status": risk_decision.status,
            "protective_order_strategy": protective_order_strategy,
            "margin_mode": account_snapshot.margin_mode if account_snapshot is not None else None,
            "risk_trace": {
                "requested_quantity": sizing.position_size_base,
                "requested_entry_price": sizing.entry_price,
                "requested_notional": sizing.notional,
                "requested_risk_amount": sizing.risk_amount,
                "effective_risk_amount": sizing.effective_risk_amount,
                "effective_risk_per_unit": sizing.effective_risk_per_unit,
                "stop_loss_price": risk_decision.stop_loss_plan.stop_loss_price,
            },
            "adapter_capabilities": {
                "supports_bracket_orders": adapter_capabilities.supports_bracket_orders,
                "supports_oco": adapter_capabilities.supports_oco,
                "guarantees_protective_after_entry": adapter_capabilities.guarantees_protective_after_entry,
                "supports_reduce_only": adapter_capabilities.supports_reduce_only,
            },
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
    min_order_size = _reference_number(reference, "exchange_min_order_size", "min_order_size")
    max_order_size = _reference_number(reference, "exchange_max_order_size", "max_order_size")
    min_notional = _reference_number(reference, "exchange_min_notional", "min_notional")
    if min_order_size is not None:
        for order in plan.planned_orders:
            if order.quantity < min_order_size:
                errors.append(f"Order {order.client_order_id} quantity is below exchange minimum order size.")
    if max_order_size is not None:
        for order in plan.planned_orders:
            if order.quantity > max_order_size:
                errors.append(f"Order {order.client_order_id} quantity is above exchange maximum order size.")
    if min_notional is not None and plan.notional < min_notional:
        errors.append("Execution plan notional is below exchange minimum notional.")
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
    placement_blockers = _live_placement_safety_blockers(plan, adapter)
    if placement_blockers:
        raise ValueError("; ".join(placement_blockers))
    placed: list[ExecutionPlannedOrder] = []
    for order in plan.planned_orders:
        existing = await adapter.get_order(
            exchange=order.exchange,
            symbol=order.symbol,
            client_order_id=order.client_order_id,
        )
        if existing is not None and _same_idempotent_order(existing, order):
            placed.append(
                existing.model_copy(
                    update={
                        "metadata": {
                            **existing.metadata,
                            "idempotent_replay": True,
                        }
                    }
                )
            )
            continue
        if order.role == "entry":
            placed.append(await adapter.place_order(order))
        elif order.role == "protective_stop":
            placed.append(await adapter.place_protective_stop(order))
        else:
            placed.append(await adapter.place_take_profit(order))
    return placed


def _live_placement_safety_blockers(plan: RealExecutionPlan, adapter: ExchangeExecutionAdapter) -> list[str]:
    if bool(getattr(adapter, "is_dry_run", False)):
        return []
    capabilities = exchange_execution_capabilities(adapter)
    blockers: list[str] = []
    stop_orders = [order for order in plan.planned_orders if order.role == "protective_stop"]
    take_profit_orders = [order for order in plan.planned_orders if order.role == "take_profit"]
    if not any(order.stop_price is not None for order in stop_orders):
        blockers.append("Live execution plan must include a protective stop before entry.")
    if not take_profit_orders:
        blockers.append("Live execution plan must include take-profit orders before entry.")
    if plan.protective_order_strategy not in {"bracket", "oco"}:
        blockers.append("Live execution plan must use bracket/OCO/protective guarantee before entry.")
    if not capabilities.has_live_protective_guarantee:
        blockers.append("Live adapter lacks bracket/OCO/protective guarantee.")
    if not capabilities.supports_reduce_only:
        blockers.append("Live adapter must support reduce-only protective orders.")
    return _dedupe(blockers)


def _same_idempotent_order(existing: ExecutionPlannedOrder, requested: ExecutionPlannedOrder) -> bool:
    return (
        existing.idempotency_key == requested.idempotency_key
        and existing.status not in {"cancelled", "canceled", "rejected", "expired"}
    )


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


def _execution_plan_with_readiness(
    plan: RealExecutionPlan,
    readiness: RealExecutionReadinessResult,
) -> RealExecutionPlan:
    return plan.model_copy(
        update={
            "metadata": {
                **plan.metadata,
                "readiness": {
                    "ready": readiness.ready,
                    **readiness.metadata,
                },
            }
        }
    )


def _execution_plan_with_placed_orders(
    plan: RealExecutionPlan,
    *,
    planned_orders: list[ExecutionPlannedOrder],
    adapter_is_dry_run: bool,
) -> RealExecutionPlan:
    planned_orders = [_order_with_placement_trace(order) for order in planned_orders]
    entry_order = next((order for order in planned_orders if order.role == "entry"), None)
    real_order_id = (
        entry_order.exchange_order_id
        if entry_order is not None and entry_order.exchange_order_id
        else entry_order.client_order_id
        if entry_order is not None
        else plan.lifecycle_trace.real_order_id
    )
    lifecycle_trace = plan.lifecycle_trace.model_copy(update={"real_order_id": real_order_id})
    partial_orders = [
        order
        for order in planned_orders
        if order.status == "partially_filled"
        or (order.filled_qty is not None and order.remaining_qty is not None and order.remaining_qty > 0)
    ]
    metadata = {
        **plan.metadata,
        "lifecycle_trace": lifecycle_trace.model_dump(mode="json", exclude_none=True),
        "post_adapter_order_statuses": {
            order.client_order_id: order.status for order in planned_orders
        },
    }
    if partial_orders:
        metadata["reconciliation_required"] = True
        metadata["reconciliation_state"] = {
            "reason": "partial_fill",
            "adapter_is_dry_run": adapter_is_dry_run,
            "orders": [
                {
                    "role": order.role,
                    "client_order_id": order.client_order_id,
                    "exchange_order_id": order.exchange_order_id,
                    "status": order.status,
                    "filled_qty": order.filled_qty,
                    "remaining_qty": order.remaining_qty,
                    "avg_fill_price": order.avg_fill_price,
                    "fees": order.fees,
                }
                for order in partial_orders
            ],
        }
    elif not adapter_is_dry_run:
        metadata["reconciliation_required"] = True
        metadata["reconciliation_state"] = {
            "reason": "post_submission_sync",
            "adapter_is_dry_run": False,
            "orders": [
                {
                    "role": order.role,
                    "client_order_id": order.client_order_id,
                    "exchange_order_id": order.exchange_order_id,
                    "status": order.status,
                }
                for order in planned_orders
            ],
        }
    else:
        metadata["reconciliation_required"] = False
    return plan.model_copy(
        update={
            "planned_orders": planned_orders,
            "metadata": metadata,
            "lifecycle_trace": lifecycle_trace,
        }
    )


def _order_with_placement_trace(order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
    real_order_id = order.exchange_order_id or order.client_order_id
    lifecycle_trace = order.lifecycle_trace.model_copy(update={"real_order_id": real_order_id})
    return order.model_copy(
        update={
            "lifecycle_trace": lifecycle_trace,
            "metadata": {
                **order.metadata,
                "lifecycle_trace": lifecycle_trace.model_dump(mode="json", exclude_none=True),
            },
        }
    )


real_execution_service = RealExecutionService()
