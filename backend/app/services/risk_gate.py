from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.schemas.lifecycle import LifecycleTrace
from app.schemas.market import OrderBookSnapshot
from app.schemas.risk import (
    AccountRiskSnapshot,
    LEGACY_VIRTUAL_INSTRUMENT_WARNING,
    ResolvedExecutionProfile,
    RiskContext,
    RiskDecision,
    TakeProfitPlan,
    TakeProfitTarget,
    TradeInstrumentType,
    normalize_instrument_type,
)
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, VirtualAccount, VirtualTrade
from app.schemas.trade_plan import TradePlanCompletenessResult
from app.schemas.user import RiskManagementSettings
from app.services.risk_management import (
    TradePlanValidationError,
    calculate_breakeven_plan,
    calculate_futures_risk_plan,
    calculate_position_sizing,
    calculate_risk_check_result,
    calculate_stop_loss_plan,
    calculate_take_profit_plan,
    calculate_take_profit_plan_from_trade_plan,
    calculate_trade_risk_adjustment,
    calculate_trailing_stop_plan,
    position_sizing_for_notional,
)
from app.services.risk_reward_plan import risk_reward_plan_service
from app.services.trade_plan_completeness import (
    MISSING_CONTEXT_POLICY_KEY,
    MISSING_SCORE_POLICY_KEY,
    trade_plan_completeness_service,
)


class RiskContextService:
    """Builds normalized risk-gate context from app-specific trade flows."""

    def build_virtual_context(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        account: VirtualAccount,
        entry_price: float,
        open_positions: list[VirtualTrade],
        requested_notional: float | None = None,
        stage: str = "preview",
        signal_stop_loss_price: float | None = None,
        atr_value: float | None = None,
        manual_take_profit_price: float | None = None,
        exchange_min_order_size: float | None = None,
        exchange_max_order_size: float | None = None,
        exchange_min_notional: float | None = None,
        exchange_max_leverage: int | None = None,
        exchange_rule_status: str = "unknown",
        exchange_rule_age_seconds: float | None = None,
        exchange_rule_ttl_seconds: int | None = None,
        instrument_rules: dict[str, Any] | None = None,
        margin_mode: str | None = None,
        liquidation_price: float | None = None,
        funding_buffer_per_unit: float = 0.0,
        best_bid: float | None = None,
        best_ask: float | None = None,
        mark_price: float | None = None,
        funding_rate: float | None = None,
        spread_percent: float | None = None,
        spread_bps: float | None = None,
        orderbook_depth_usd: float | None = None,
        orderbook_snapshot: OrderBookSnapshot | None = None,
        market_data_status: str = "unknown",
        market_data_source: str | None = None,
        market_data_warnings: list[str] | None = None,
        daily_loss_amount: float = 0.0,
        correlated_open_risk_amount: float = 0.0,
        correlation_group: str | None = None,
        protection_state: str = "normal",
        protection_reason: str | None = None,
        account_drawdown_percent: float | None = None,
        max_account_drawdown_percent: float = 0.0,
        user_mode_multiplier: float = 1.0,
        fee_rate_source: str | None = None,
        maker_fee_rate: float | None = None,
        taker_fee_rate: float | None = None,
        fee_rate_warnings: list[str] | None = None,
        rr_guard_context: str | None = None,
        risk_profile_source: str = "unknown",
        execution_profile_sources: dict[str, str] | None = None,
        execution_profile: ResolvedExecutionProfile | None = None,
        instrument_type: TradeInstrumentType | None = None,
    ) -> RiskContext:
        account_equity = account.equity if account.equity > 0 else request.account_balance
        resolved_instrument_type, normalization_warnings = _resolve_context_instrument_type(
            explicit_instrument_type=instrument_type,
            request=request,
            execution_profile=execution_profile,
        )
        lifecycle_trace = _lifecycle_trace_from_request(signal, request)
        return RiskContext(
            mode="virtual",
            rr_guard_context=rr_guard_context,
            stage=stage,
            user_id=request.user_id,
            signal_id=str(signal.id),
            pending_entry_intent_id=lifecycle_trace.pending_entry_intent_id,
            lifecycle_trace=lifecycle_trace,
            risk_profile_source=risk_profile_source,
            execution_profile_sources=execution_profile_sources or {},
            execution_profile=execution_profile,
            normalization_warnings=normalization_warnings,
            exchange=signal.exchange,
            symbol=signal.symbol,
            instrument_type=resolved_instrument_type,
            side=signal.direction,
            strategy=signal.strategy,
            signal_score=float(signal.score),
            account_equity=account_equity,
            available_balance=account_equity,
            account_margin_mode=margin_mode,
            account_snapshot=None,
            entry_price=entry_price,
            signal_entry_price=_signal_entry_price(signal),
            signal_stop_loss_price=signal_stop_loss_price or signal.stop_loss,
            atr_value=atr_value,
            current_price=entry_price,
            leverage=request.leverage,
            liquidation_price=liquidation_price or request.liquidation_price,
            fee_rate=request.fee_rate,
            fee_rate_source=fee_rate_source,
            maker_fee_rate=maker_fee_rate,
            taker_fee_rate=taker_fee_rate,
            fee_rate_warnings=fee_rate_warnings or [],
            slippage_bps=request.slippage_bps,
            funding_buffer_per_unit=funding_buffer_per_unit,
            best_bid=best_bid,
            best_ask=best_ask,
            mark_price=mark_price,
            funding_rate=funding_rate,
            spread_percent=spread_percent,
            spread_bps=spread_bps,
            orderbook_depth_usd=orderbook_depth_usd,
            orderbook_snapshot=orderbook_snapshot,
            market_data_status=market_data_status,
            market_data_source=market_data_source,
            market_data_warnings=market_data_warnings or [],
            requested_notional=requested_notional,
            open_risk_amount=sum(trade.risk_amount for trade in open_positions),
            correlated_open_risk_amount=correlated_open_risk_amount,
            daily_loss_amount=daily_loss_amount,
            exchange_min_order_size=exchange_min_order_size,
            exchange_max_order_size=exchange_max_order_size,
            exchange_min_notional=exchange_min_notional,
            exchange_max_leverage=exchange_max_leverage,
            exchange_rule_status=exchange_rule_status,
            exchange_rule_age_seconds=exchange_rule_age_seconds,
            exchange_rule_ttl_seconds=exchange_rule_ttl_seconds,
            instrument_rules=instrument_rules,
            correlation_group=correlation_group,
            protection_state=protection_state,
            protection_reason=protection_reason,
            account_drawdown_percent=account_drawdown_percent,
            max_account_drawdown_percent=max_account_drawdown_percent,
            user_mode_multiplier=user_mode_multiplier,
            manual_take_profit_price=manual_take_profit_price,
            trade_plan=signal.trade_plan,
            signal_edge=signal.edge,
            no_trade_filter=signal.no_trade_filter,
        )

    def build_real_context(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        entry_price: float,
        account_snapshot: AccountRiskSnapshot | None = None,
        requested_notional: float | None = None,
        instrument_type: TradeInstrumentType | None = None,
        stage: str = "preview",
        allow_request_account_balance: bool = False,
        signal_stop_loss_price: float | None = None,
        atr_value: float | None = None,
        manual_take_profit_price: float | None = None,
        exchange_min_order_size: float | None = None,
        exchange_max_order_size: float | None = None,
        exchange_min_notional: float | None = None,
        exchange_max_leverage: int | None = None,
        exchange_rule_status: str = "unknown",
        exchange_rule_age_seconds: float | None = None,
        exchange_rule_ttl_seconds: int | None = None,
        instrument_rules: dict[str, Any] | None = None,
        liquidation_price: float | None = None,
        funding_buffer_per_unit: float = 0.0,
        best_bid: float | None = None,
        best_ask: float | None = None,
        mark_price: float | None = None,
        funding_rate: float | None = None,
        spread_percent: float | None = None,
        spread_bps: float | None = None,
        orderbook_depth_usd: float | None = None,
        orderbook_snapshot: OrderBookSnapshot | None = None,
        market_data_status: str = "unknown",
        market_data_source: str | None = None,
        market_data_warnings: list[str] | None = None,
        open_risk_amount: float = 0.0,
        correlated_open_risk_amount: float = 0.0,
        daily_loss_amount: float = 0.0,
        correlation_group: str | None = None,
        protection_state: str = "normal",
        protection_reason: str | None = None,
        account_drawdown_percent: float | None = None,
        max_account_drawdown_percent: float = 0.0,
        user_mode_multiplier: float = 1.0,
        fee_rate_source: str | None = None,
        maker_fee_rate: float | None = None,
        taker_fee_rate: float | None = None,
        fee_rate_warnings: list[str] | None = None,
        risk_profile_source: str = "unknown",
        execution_profile_sources: dict[str, str] | None = None,
        execution_profile: ResolvedExecutionProfile | None = None,
    ) -> RiskContext:
        resolved_instrument_type, normalization_warnings = _resolve_context_instrument_type(
            explicit_instrument_type=instrument_type,
            request=request,
            execution_profile=execution_profile,
        )
        snapshot = account_snapshot or (
            _request_account_snapshot(request) if allow_request_account_balance else None
        )
        account_equity, available_balance, snapshot = _account_values_from_snapshot(
            snapshot,
            allow_request_account_balance=allow_request_account_balance,
        )
        snapshot_warnings = list(snapshot.warnings)
        context_warnings = _dedupe([*normalization_warnings, *snapshot_warnings])
        open_risk_for_context = (
            float(snapshot.open_risk_amount)
            if snapshot.source == "exchange"
            else open_risk_amount
        )
        lifecycle_trace = _lifecycle_trace_from_request(signal, request)
        return RiskContext(
            mode="real",
            stage=stage,
            user_id=request.user_id,
            signal_id=str(signal.id),
            pending_entry_intent_id=lifecycle_trace.pending_entry_intent_id,
            lifecycle_trace=lifecycle_trace,
            risk_profile_source=risk_profile_source,
            execution_profile_sources=execution_profile_sources or {},
            execution_profile=execution_profile,
            normalization_warnings=context_warnings,
            exchange=signal.exchange,
            symbol=signal.symbol,
            instrument_type=resolved_instrument_type,
            side=signal.direction,
            strategy=signal.strategy,
            signal_score=float(signal.score),
            account_equity=account_equity,
            available_balance=available_balance,
            account_snapshot_status=snapshot.status,
            account_snapshot_source=snapshot.source,
            account_snapshot_fetched_at=snapshot.fetched_at,
            account_margin_mode=snapshot.margin_mode,
            account_snapshot=snapshot,
            account_snapshot_warnings=snapshot_warnings,
            entry_price=entry_price,
            signal_entry_price=_signal_entry_price(signal),
            signal_stop_loss_price=signal_stop_loss_price or signal.stop_loss,
            atr_value=atr_value,
            current_price=entry_price,
            leverage=request.leverage,
            liquidation_price=liquidation_price or request.liquidation_price,
            fee_rate=request.fee_rate,
            fee_rate_source=fee_rate_source,
            maker_fee_rate=maker_fee_rate,
            taker_fee_rate=taker_fee_rate,
            fee_rate_warnings=fee_rate_warnings or [],
            slippage_bps=request.slippage_bps,
            funding_buffer_per_unit=funding_buffer_per_unit,
            best_bid=best_bid,
            best_ask=best_ask,
            mark_price=mark_price,
            funding_rate=funding_rate,
            spread_percent=spread_percent,
            spread_bps=spread_bps,
            orderbook_depth_usd=orderbook_depth_usd,
            orderbook_snapshot=orderbook_snapshot,
            market_data_status=market_data_status,
            market_data_source=market_data_source,
            market_data_warnings=market_data_warnings or [],
            requested_notional=requested_notional or request.size_usd,
            open_risk_amount=open_risk_for_context,
            correlated_open_risk_amount=correlated_open_risk_amount,
            daily_loss_amount=daily_loss_amount,
            exchange_min_order_size=exchange_min_order_size,
            exchange_max_order_size=exchange_max_order_size,
            exchange_min_notional=exchange_min_notional,
            exchange_max_leverage=exchange_max_leverage,
            exchange_rule_status=exchange_rule_status,
            exchange_rule_age_seconds=exchange_rule_age_seconds,
            exchange_rule_ttl_seconds=exchange_rule_ttl_seconds,
            instrument_rules=instrument_rules,
            correlation_group=correlation_group,
            protection_state=protection_state,
            protection_reason=protection_reason,
            account_drawdown_percent=account_drawdown_percent,
            max_account_drawdown_percent=max_account_drawdown_percent,
            user_mode_multiplier=user_mode_multiplier,
            manual_take_profit_price=manual_take_profit_price,
            trade_plan=signal.trade_plan,
            signal_edge=signal.edge,
            no_trade_filter=signal.no_trade_filter,
        )


class RiskGateService:
    """Mandatory backend risk gate for real and virtual trade entry decisions."""

    def evaluate(
        self,
        *,
        context: RiskContext,
        risk_settings: RiskManagementSettings,
    ) -> RiskDecision:
        stop_loss_plan = calculate_stop_loss_plan(
            entry_price=context.entry_price,
            side=context.side,
            risk_settings=risk_settings,
            signal_stop_loss_price=context.signal_stop_loss_price,
            atr_value=context.atr_value,
            structure_stop_loss_price=context.structure_stop_loss_price,
        )
        take_profit_blockers: list[str] = []
        take_profit_plan = self._take_profit_plan(
            context=context,
            stop_loss_price=stop_loss_plan.stop_loss_price,
            risk_settings=risk_settings,
            blockers=take_profit_blockers,
        )
        breakeven_plan = calculate_breakeven_plan(
            entry_price=context.entry_price,
            stop_loss_price=stop_loss_plan.stop_loss_price,
            side=context.side,
            risk_settings=risk_settings,
        )
        trailing_stop_plan = calculate_trailing_stop_plan(
            entry_price=context.entry_price,
            current_price=context.current_price or context.entry_price,
            side=context.side,
            risk_settings=risk_settings,
            atr_value=context.atr_value,
        )
        risk_adjustment = calculate_trade_risk_adjustment(
            account_equity=context.account_equity,
            risk_settings=risk_settings,
            instrument_type=context.instrument_type,
            execution_mode=context.mode,
            strategy=context.strategy,
            signal_score=context.signal_score,
            execution_profile=context.execution_profile,
            volatility_multiplier=context.volatility_multiplier,
            user_mode_multiplier=context.user_mode_multiplier,
        )
        position_sizing = calculate_position_sizing(
            account_equity=context.account_equity,
            risk_settings=risk_settings,
            entry_price=context.entry_price,
            stop_loss_price=stop_loss_plan.stop_loss_price,
            side=context.side,
            leverage=context.leverage,
            fee_rate=context.fee_rate,
            slippage_bps=context.slippage_bps,
            funding_buffer_per_unit=context.funding_buffer_per_unit,
            risk_adjustment=risk_adjustment,
        )
        checked_position_sizing = (
            position_sizing_for_notional(
                position_sizing,
                notional=context.requested_notional,
                entry_price=context.entry_price,
                leverage=context.leverage,
            )
            if context.requested_notional is not None
            else position_sizing
        )
        futures_risk_plan = None
        if context.instrument_type == "futures" or context.leverage > 1:
            futures_risk_plan = calculate_futures_risk_plan(
                entry_price=context.entry_price,
                stop_loss_price=stop_loss_plan.stop_loss_price,
                side=context.side,
                leverage=context.leverage,
                risk_settings=risk_settings,
                liquidation_price=context.liquidation_price,
                quantity=checked_position_sizing.position_size_base,
                margin_mode=context.account_margin_mode,
                account_snapshot=context.account_snapshot,
                instrument_rules=context.instrument_rules,
                fee_rate=context.fee_rate,
            )
        risk_check = calculate_risk_check_result(
            risk_settings=risk_settings,
            risk_adjustment=risk_adjustment,
            position_sizing=checked_position_sizing,
            execution_profile=context.execution_profile,
            take_profit_plan=take_profit_plan,
            futures_risk_plan=futures_risk_plan,
            available_balance=context.available_balance,
            open_risk_amount=context.open_risk_amount,
            daily_loss_amount=context.daily_loss_amount,
            exchange_min_order_size=context.exchange_min_order_size,
            exchange_max_order_size=context.exchange_max_order_size,
            exchange_min_notional=context.exchange_min_notional,
            exchange_max_leverage=context.exchange_max_leverage,
            exchange_rule_status=context.exchange_rule_status,
            exchange_rule_age_seconds=context.exchange_rule_age_seconds,
            exchange_rule_ttl_seconds=context.exchange_rule_ttl_seconds,
            market_data_status=context.market_data_status,
            market_data_warnings=context.market_data_warnings,
            fee_rate_source=context.fee_rate_source,
            maker_fee_rate=context.maker_fee_rate,
            taker_fee_rate=context.taker_fee_rate,
            fee_rate_warnings=context.fee_rate_warnings,
            best_bid=context.best_bid,
            best_ask=context.best_ask,
            mark_price=context.mark_price,
            funding_rate=context.funding_rate,
            spread_percent=context.spread_percent,
            spread_bps=context.spread_bps,
            orderbook_depth_usd=context.orderbook_depth_usd,
            orderbook_snapshot=context.orderbook_snapshot,
            signal_entry_price=context.signal_entry_price,
            correlated_open_risk_amount=context.correlated_open_risk_amount,
            correlation_group=context.correlation_group,
            protection_state=context.protection_state,
            protection_reason=context.protection_reason,
            account_drawdown_percent=context.account_drawdown_percent,
            max_account_drawdown_percent=context.max_account_drawdown_percent,
            execution_mode=context.rr_guard_context or context.mode,
            strategy=context.strategy,
            signal_edge=context.signal_edge,
        )
        profile_warnings = (
            list(context.execution_profile.warnings)
            if context.execution_profile is not None
            else []
        )
        context_warnings = _dedupe([*context.normalization_warnings, *profile_warnings])
        if context_warnings:
            risk_check = risk_check.model_copy(
                update={
                    "status": "warning" if risk_check.status == "passed" else risk_check.status,
                    "warnings": _dedupe([*risk_check.warnings, *context_warnings]),
                }
            )
        production_context = _is_trade_plan_production_context(context)
        completeness = (
            trade_plan_completeness_service.assess_or_restore(
                None,
                context.trade_plan,
                settings={
                    MISSING_SCORE_POLICY_KEY: "off",
                    MISSING_CONTEXT_POLICY_KEY: "off",
                },
                production_mode=production_context,
            )
            if context.trade_plan is not None
            else None
        )
        completeness_blockers, completeness_warnings = _trade_plan_completeness_policy(
            context=context,
            completeness=completeness,
        )
        if completeness_blockers or completeness_warnings:
            completeness_status = (
                "failed"
                if completeness_blockers
                else "warning" if risk_check.status == "passed" else risk_check.status
            )
            risk_check = risk_check.model_copy(
                update={
                    "status": completeness_status,
                    "blockers": _dedupe([*risk_check.blockers, *completeness_blockers]),
                    "warnings": _dedupe([*risk_check.warnings, *completeness_warnings]),
                }
            )
        no_trade_blockers = _no_trade_blockers(context)
        no_trade_warnings = _no_trade_warnings(context)
        if no_trade_blockers or no_trade_warnings:
            no_trade_status = "failed" if no_trade_blockers else "warning" if risk_check.status == "passed" else risk_check.status
            risk_check = risk_check.model_copy(
                update={
                    "status": no_trade_status,
                    "blockers": _dedupe([*risk_check.blockers, *no_trade_blockers]),
                    "warnings": _dedupe([*risk_check.warnings, *no_trade_warnings]),
                }
            )
        if take_profit_blockers:
            risk_check = risk_check.model_copy(
                update={
                    "status": "failed",
                    "blockers": _dedupe([*risk_check.blockers, *take_profit_blockers]),
                }
            )
        warnings = [
            *stop_loss_plan.warnings,
            *trailing_stop_plan.warnings,
            *(futures_risk_plan.warnings if futures_risk_plan is not None else []),
            *risk_check.warnings,
        ]
        notes = _dedupe([*warnings, *take_profit_plan.notes, *take_profit_blockers])
        return RiskDecision(
            mode=context.mode,
            stage=context.stage,
            status=risk_check.status,
            can_enter=risk_check.status != "failed",
            lifecycle_trace=_decision_trace(context),
            risk_profile_source=context.risk_profile_source,
            execution_profile_sources=context.execution_profile_sources,
            blockers=risk_check.blockers,
            warnings=_dedupe(warnings),
            exchange=context.exchange,
            symbol=context.symbol,
            instrument_type=context.instrument_type,
            requested_notional=context.requested_notional,
            risk_adjustment_plan=risk_adjustment,
            position_sizing=position_sizing,
            checked_position_sizing=checked_position_sizing,
            risk_check=risk_check,
            stop_loss_plan=stop_loss_plan,
            take_profit_plan=take_profit_plan,
            breakeven_plan=breakeven_plan,
            trailing_stop_plan=trailing_stop_plan,
            futures_risk_plan=futures_risk_plan,
            notes=notes,
        )

    def _take_profit_plan(
        self,
        *,
        context: RiskContext,
        stop_loss_price: float,
        risk_settings: RiskManagementSettings,
        blockers: list[str],
    ) -> TakeProfitPlan:
        if context.manual_take_profit_price is not None:
            return _manual_take_profit_plan(
                entry_price=context.entry_price,
                stop_loss_price=stop_loss_price,
                take_profit_price=context.manual_take_profit_price,
                side=context.side,
            )
        if context.trade_plan is not None:
            try:
                return calculate_take_profit_plan_from_trade_plan(
                    trade_plan=context.trade_plan,
                    entry_price=context.entry_price,
                    stop_loss_price=stop_loss_price,
                    side=context.side,
                    risk_settings=risk_settings,
                )
            except TradePlanValidationError as exc:
                blockers.extend(exc.errors)
                return _invalid_trade_plan_take_profit_plan(
                    entry_price=context.entry_price,
                    stop_loss_price=stop_loss_price,
                    side=context.side,
                    notes=exc.errors,
                )
        return calculate_take_profit_plan(
            entry_price=context.entry_price,
            stop_loss_price=stop_loss_price,
            side=context.side,
            risk_settings=risk_settings,
        )


def _trade_plan_completeness_policy(
    *,
    context: RiskContext,
    completeness: TradePlanCompletenessResult | None,
) -> tuple[list[str], list[str]]:
    if completeness is None:
        return [], []
    if context.mode == "real":
        if completeness.execution_allowed_real:
            return [], list(completeness.warnings)
        return _completeness_blockers(completeness), []
    if completeness.execution_allowed_virtual:
        return [], list(completeness.warnings)
    return _completeness_blockers(completeness), []


def _trade_plan_completeness_message(completeness: TradePlanCompletenessResult) -> str:
    missing = (
        ", ".join(completeness.missing_fields)
        if completeness.missing_fields
        else ", ".join(completeness.missing)
        if completeness.missing
        else "structural trade plan"
    )
    return f"Trade plan incomplete: {missing}; execution is blocked."


def _completeness_blockers(completeness: TradePlanCompletenessResult) -> list[str]:
    if completeness.blockers:
        return list(completeness.blockers)
    return [_trade_plan_completeness_message(completeness)]


def _is_trade_plan_production_context(context: RiskContext) -> bool:
    if context.mode == "real":
        return True
    if context.rr_guard_context in {"real", "production", "production_like"}:
        return True
    if context.trade_plan is None:
        return False
    metadata = context.trade_plan.metadata
    if _truthy_metadata_value(metadata, "production_mode"):
        return True
    signal_mode = metadata.get("signal_mode")
    return isinstance(signal_mode, str) and signal_mode.strip().lower() == "production"


def _truthy_metadata_value(metadata: dict[str, object], key: str) -> bool:
    value = metadata.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _request_account_snapshot(request: ManualConfirmRequest) -> AccountRiskSnapshot:
    balance = Decimal(str(request.account_balance))
    return AccountRiskSnapshot(
        status="fresh",
        fetched_at=datetime.now(timezone.utc),
        account_equity=balance,
        available_balance=balance,
        margin_mode=None,
        positions=[],
        open_risk_amount=Decimal("0"),
        source="request",
        warnings=[
            (
                "Manual real preview uses request.account_balance for sizing; "
                "live adapters require a fresh exchange account snapshot."
            )
        ],
    )


def _account_values_from_snapshot(
    snapshot: AccountRiskSnapshot | None,
    *,
    allow_request_account_balance: bool,
) -> tuple[float, float, AccountRiskSnapshot]:
    if snapshot is None:
        raise ValueError("AccountRiskSnapshot is required for real RiskGate context.")
    if snapshot.status != "fresh":
        raise ValueError("Fresh account risk snapshot is required for real RiskGate context.")
    if snapshot.source != "exchange" and not allow_request_account_balance:
        raise ValueError(
            "Live entry requires source=exchange account snapshot."
        )
    if snapshot.account_equity is None or snapshot.account_equity <= 0:
        raise ValueError("Exchange account equity is missing.")
    if snapshot.available_balance is None or snapshot.available_balance <= 0:
        raise ValueError("Exchange available balance is insufficient.")
    return (
        float(snapshot.account_equity),
        float(snapshot.available_balance),
        snapshot,
    )


def _no_trade_blockers(context: RiskContext) -> list[str]:
    result = context.no_trade_filter
    if result is None or not result.blocked:
        return []
    return result.blockers or ["No-trade filter blocked this entry."]


def _no_trade_warnings(context: RiskContext) -> list[str]:
    result = context.no_trade_filter
    if result is None or result.blocked:
        return []
    return result.warnings


def _signal_entry_price(signal: RadarSignal) -> float | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    if signal.entry_max is not None:
        return signal.entry_max
    return None


def _manual_take_profit_plan(
    *,
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    side: str,
) -> TakeProfitPlan:
    rr_calculation = risk_reward_plan_service.calculate_rr(
        entry_price,
        stop_loss_price,
        take_profit_price,
        side,
    )
    risk_per_unit = rr_calculation.risk_per_unit or abs(entry_price - stop_loss_price)
    r_multiple = rr_calculation.rr_value if rr_calculation.rr_value is not None else 0.000001
    notes = ["Manual take-profit override is used instead of signal trade_plan targets."]
    if rr_calculation.rr_value is None:
        notes.append(f"Manual take-profit override RR calculation reason: {rr_calculation.reason}.")
    return TakeProfitPlan(
        mode="risk_multiple",
        side=side,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        risk_per_unit=risk_per_unit,
        partial_take_profit_enabled=False,
        targets=[
            TakeProfitTarget(
                label="TP3",
                r_multiple=r_multiple,
                price=take_profit_price,
                close_percent=100.0,
                action="full_close",
            )
        ],
        source="manual_override",
        selected_rr=r_multiple,
        selected_rr_target="manual",
        notes=notes,
    )


def _invalid_trade_plan_take_profit_plan(
    *,
    entry_price: float,
    stop_loss_price: float,
    side: str,
    notes: list[str],
) -> TakeProfitPlan:
    return TakeProfitPlan(
        mode="risk_multiple",
        side=side,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        risk_per_unit=abs(entry_price - stop_loss_price),
        partial_take_profit_enabled=False,
        targets=[],
        source="trade_plan_invalid",
        notes=notes,
    )


def _lifecycle_trace_from_request(signal: RadarSignal, request: ManualConfirmRequest) -> LifecycleTrace:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    trace = _parse_lifecycle_trace(metadata.get("lifecycle_trace"))
    pending_entry_intent_id = metadata.get("pending_entry_intent_id") or trace.pending_entry_intent_id
    return trace.model_copy(
        update={
            "signal_id": str(signal.id),
            "pending_entry_intent_id": _string_or_none(pending_entry_intent_id),
        }
    )


def _parse_lifecycle_trace(value: Any) -> LifecycleTrace:
    if isinstance(value, LifecycleTrace):
        return value
    if isinstance(value, dict):
        try:
            return LifecycleTrace.model_validate(value)
        except ValueError:
            return LifecycleTrace()
    return LifecycleTrace()


def _decision_trace(context: RiskContext) -> LifecycleTrace:
    return context.lifecycle_trace.model_copy(
        update={
            "signal_id": _string_or_none(context.signal_id) or context.lifecycle_trace.signal_id,
            "pending_entry_intent_id": (
                _string_or_none(context.pending_entry_intent_id)
                or context.lifecycle_trace.pending_entry_intent_id
            ),
        }
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


risk_context_service = RiskContextService()
risk_gate_service = RiskGateService()


def _resolve_context_instrument_type(
    *,
    explicit_instrument_type: TradeInstrumentType | str | None,
    request: ManualConfirmRequest,
    execution_profile: ResolvedExecutionProfile | None,
) -> tuple[TradeInstrumentType, list[str]]:
    if explicit_instrument_type is not None:
        return normalize_instrument_type(
            explicit_instrument_type,
            leverage=request.leverage,
        )
    if execution_profile is not None:
        return execution_profile.instrument_type, list(execution_profile.warnings)
    if request.execution_profile is not None and request.execution_profile.instrument_type is not None:
        warnings = []
        if request.execution_profile.legacy_instrument_type == "virtual":
            warnings.append(LEGACY_VIRTUAL_INSTRUMENT_WARNING)
        return request.execution_profile.instrument_type, warnings
    if request.risk_override is not None and request.risk_override.leverage is not None:
        return ("futures" if request.risk_override.leverage > 1 else "spot"), []
    return ("futures" if request.leverage > 1 else "spot"), []
