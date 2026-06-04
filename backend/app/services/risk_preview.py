from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from app.schemas.risk import (
    InstrumentType,
    RiskDecision,
    RiskPreviewRequest,
    RiskPreviewResponse,
    RiskStateResponse,
    normalize_instrument_type,
)
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, VirtualAccount, VirtualTrade
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
from app.services.risk_state import RiskStateService, risk_state_service
from app.services.signal_service import SignalService, signal_service
from app.services.strategy_config_service import strategy_config_service
from app.services.virtual_trading import virtual_trading_service


@dataclass(frozen=True)
class _RiskPreviewEvaluation:
    decision: RiskDecision
    state: RiskStateResponse
    user_id: str
    signal_id: str
    input_snapshot: dict[str, Any]


class RiskPreviewService:
    def __init__(
        self,
        *,
        signal_provider: SignalService = signal_service,
        risk_context_service: RiskContextService | None = None,
        risk_gate_service: RiskGateService | None = None,
        state_service: RiskStateService = risk_state_service,
        audit_service: RiskAuditService = risk_audit_service,
        market_data_service: RiskMarketDataService = risk_market_data_service,
        fee_rate_service: RiskFeeRateService = risk_fee_rate_service,
    ) -> None:
        self._signal_provider = signal_provider
        self._risk_context_service = risk_context_service or RiskContextService()
        self._risk_gate_service = risk_gate_service or RiskGateService()
        self._state_service = state_service
        self._audit_service = audit_service
        self._market_data_service = market_data_service
        self._fee_rate_service = fee_rate_service

    def preview(
        self,
        request: RiskPreviewRequest,
        *,
        record_audit: bool = True,
    ) -> RiskPreviewResponse:
        evaluation = self._evaluate(request, read_only=not record_audit)
        risk_decision_id = (
            str(self._record_audit(evaluation))
            if record_audit
            else None
        )
        return RiskPreviewResponse(
            decision=evaluation.decision,
            state=evaluation.state,
            risk_decision_id=risk_decision_id,
        )

    def evaluate(
        self,
        request: RiskPreviewRequest,
        *,
        record_audit: bool = True,
    ) -> RiskDecision:
        evaluation = self._evaluate(request, read_only=not record_audit)
        if record_audit:
            self._record_audit(evaluation)
        return evaluation.decision

    def _evaluate(
        self,
        request: RiskPreviewRequest,
        *,
        read_only: bool,
    ) -> _RiskPreviewEvaluation:
        signal = self._signal_provider.get_signal(request.signal_id)
        if signal is None:
            raise LookupError("Signal is not found")
        manual_request = _manual_request(request)
        fallback_entry_price = _entry_price(signal)
        risk_settings = get_user_risk_management_settings(request.user_id)
        instrument_type = _instrument_type(request, manual_request)
        strategy_risk_settings, strategy_risk_settings_source = strategy_risk_settings_for_signal(
            signal,
            user_id=request.user_id,
        )
        execution_profile = execution_profile_resolver.resolve(
            user_risk_settings=risk_settings,
            strategy_execution_settings=strategy_risk_settings,
            request_override=request_risk_override_to_execution_settings(request.risk_override),
            mode=request.mode,
            instrument_type=_profile_instrument_type(instrument_type),
            strategy=signal.strategy,
        )
        risk_profile_source = resolved_risk_profile_source(execution_profile)
        risk_settings = execution_profile_resolver.apply_to_risk_settings(
            risk_settings,
            execution_profile,
        )
        manual_request = manual_request.model_copy(
            update={"leverage": int(execution_profile.leverage)}
        )
        instrument_type = execution_profile.instrument_type
        market_data = self._market_data_service.build_snapshot(
            exchange=signal.exchange,
            symbol=signal.symbol,
            side=signal.direction,
            mode=request.mode,
            instrument_type=instrument_type,
            fallback_entry_price=fallback_entry_price,
            manual_entry_price=request.entry_price,
            manual_slippage_bps=request.slippage_bps,
            user_id=request.user_id,
        )
        fee_rate = self._fee_rate_service.resolve(
            user_id=request.user_id,
            exchange=signal.exchange,
            mode=request.mode,
            instrument_type=instrument_type,
            symbol=signal.symbol,
            risk_settings=risk_settings,
            requested_fee_rate=request.fee_rate,
        )
        manual_request = manual_request.model_copy(
            update={
                "fee_rate": fee_rate.fee_rate,
                "slippage_bps": market_data.slippage_bps,
                "liquidation_price": request.liquidation_price or market_data.liquidation_price,
            }
        )
        entry_price = market_data.entry_price
        reference = self._state_service.get_reference(
            user_id=request.user_id,
            mode=request.mode,
            exchange=signal.exchange,
            symbol=signal.symbol,
            side=signal.direction,
            instrument_type=instrument_type,
            read_only=read_only,
        )
        account_snapshot = None
        if request.mode == "virtual":
            account = virtual_trading_service.get_virtual_account(request.user_id)
            open_positions = [
                trade
                for trade in virtual_trading_service.list_virtual_trades(status="open")
                if trade.user_id == request.user_id and trade.status == "open"
            ]
            context = self._risk_context_service.build_virtual_context(
                signal=signal,
                request=manual_request,
                account=account,
                entry_price=entry_price,
                open_positions=open_positions,
                requested_notional=request.size_usd,
                stage="preview",
                signal_stop_loss_price=request.stop_loss_price,
                atr_value=request.atr_value,
                manual_take_profit_price=request.take_profit_price,
                exchange_min_order_size=reference.exchange_min_order_size,
                exchange_max_order_size=reference.exchange_max_order_size,
                exchange_min_notional=reference.exchange_min_notional,
                exchange_max_leverage=reference.exchange_max_leverage,
                exchange_rule_status=reference.exchange_rule_status,
                exchange_rule_age_seconds=reference.exchange_rule_age_seconds,
                exchange_rule_ttl_seconds=reference.exchange_rule_ttl_seconds,
                liquidation_price=market_data.liquidation_price,
                funding_buffer_per_unit=market_data.funding_buffer_per_unit,
                best_bid=market_data.best_bid,
                best_ask=market_data.best_ask,
                mark_price=market_data.mark_price,
                funding_rate=market_data.funding_rate,
                spread_percent=market_data.spread_percent,
                spread_bps=market_data.spread_bps,
                orderbook_depth_usd=market_data.orderbook_depth_usd,
                orderbook_snapshot=market_data.orderbook_snapshot,
                market_data_status=market_data.market_data_status,
                market_data_source=market_data.market_data_source,
                market_data_warnings=list(market_data.warnings),
                fee_rate_source=fee_rate.source,
                maker_fee_rate=fee_rate.maker_fee_rate,
                taker_fee_rate=fee_rate.taker_fee_rate,
                fee_rate_warnings=list(fee_rate.warnings),
                risk_profile_source=risk_profile_source,
                execution_profile_sources=execution_profile.sources,
                execution_profile=execution_profile,
                instrument_type=instrument_type,
                daily_loss_amount=reference.daily_loss_amount,
                correlated_open_risk_amount=reference.correlated_open_risk_amount,
                correlation_group=reference.correlation_group,
                protection_state=reference.protection_state,
                protection_reason=reference.protection_reason,
                account_drawdown_percent=reference.account_drawdown_percent,
                max_account_drawdown_percent=reference.max_account_drawdown_percent,
                user_mode_multiplier=reference.user_mode_multiplier,
            )
        else:
            account_snapshot_provider = (
                self._state_service
                if hasattr(self._state_service, "get_real_account_snapshot")
                else RiskStateService()
            )
            account_snapshot = account_snapshot_provider.get_real_account_snapshot(
                user_id=request.user_id,
                exchange=signal.exchange,
                mode=request.mode,
                live_adapter=False,
                request_account_balance=request.account_balance,
                reference=reference,
            )
            context = self._risk_context_service.build_real_context(
                signal=signal,
                request=manual_request,
                entry_price=entry_price,
                account_snapshot=account_snapshot,
                allow_request_account_balance=True,
                requested_notional=request.size_usd,
                instrument_type=instrument_type,
                stage="preview",
                signal_stop_loss_price=request.stop_loss_price,
                atr_value=request.atr_value,
                manual_take_profit_price=request.take_profit_price,
                exchange_min_order_size=reference.exchange_min_order_size,
                exchange_max_order_size=reference.exchange_max_order_size,
                exchange_min_notional=reference.exchange_min_notional,
                exchange_max_leverage=reference.exchange_max_leverage,
                exchange_rule_status=reference.exchange_rule_status,
                exchange_rule_age_seconds=reference.exchange_rule_age_seconds,
                exchange_rule_ttl_seconds=reference.exchange_rule_ttl_seconds,
                liquidation_price=market_data.liquidation_price,
                funding_buffer_per_unit=market_data.funding_buffer_per_unit,
                best_bid=market_data.best_bid,
                best_ask=market_data.best_ask,
                mark_price=market_data.mark_price,
                funding_rate=market_data.funding_rate,
                spread_percent=market_data.spread_percent,
                spread_bps=market_data.spread_bps,
                orderbook_depth_usd=market_data.orderbook_depth_usd,
                orderbook_snapshot=market_data.orderbook_snapshot,
                market_data_status=market_data.market_data_status,
                market_data_source=market_data.market_data_source,
                market_data_warnings=list(market_data.warnings),
                fee_rate_source=fee_rate.source,
                maker_fee_rate=fee_rate.maker_fee_rate,
                taker_fee_rate=fee_rate.taker_fee_rate,
                fee_rate_warnings=list(fee_rate.warnings),
                risk_profile_source=risk_profile_source,
                execution_profile_sources=execution_profile.sources,
                execution_profile=execution_profile,
                open_risk_amount=reference.open_risk_amount,
                correlated_open_risk_amount=reference.correlated_open_risk_amount,
                daily_loss_amount=reference.daily_loss_amount,
                correlation_group=reference.correlation_group,
                protection_state=reference.protection_state,
                protection_reason=reference.protection_reason,
                account_drawdown_percent=reference.account_drawdown_percent,
                max_account_drawdown_percent=reference.max_account_drawdown_percent,
                user_mode_multiplier=reference.user_mode_multiplier,
            )
        decision = self._risk_gate_service.evaluate(
            context=context,
            risk_settings=risk_settings,
        )
        return _RiskPreviewEvaluation(
            decision=decision,
            state=reference.state,
            user_id=request.user_id,
            signal_id=signal.id,
            input_snapshot={
                "flow": "risk.preview",
                "request": request.model_dump(mode="json"),
                "signal": signal.model_dump(mode="json"),
                "market_data": _market_data_snapshot_payload(market_data),
                "fee_rate": asdict(fee_rate),
                "account_snapshot": (
                    account_snapshot.model_dump(mode="json")
                    if account_snapshot is not None
                    else None
                ),
                "risk_state": reference.state.model_dump(mode="json"),
                "execution_profile": execution_profile.model_dump(mode="json"),
                "risk_profile_source": risk_profile_source,
                "strategy_risk_settings_source": strategy_risk_settings_source,
            },
        )

    def _record_audit(self, evaluation: _RiskPreviewEvaluation) -> UUID:
        return self._audit_service.record_decision(
            decision=evaluation.decision,
            user_id=evaluation.user_id,
            signal_id=evaluation.signal_id,
            pending_entry_intent_id=evaluation.decision.lifecycle_trace.pending_entry_intent_id,
            input_snapshot=evaluation.input_snapshot,
        )


def _market_data_snapshot_payload(market_data: Any) -> dict[str, Any]:
    payload = asdict(market_data)
    orderbook_snapshot = getattr(market_data, "orderbook_snapshot", None)
    payload["orderbook_snapshot"] = (
        orderbook_snapshot.model_dump(mode="json")
        if orderbook_snapshot is not None
        else None
    )
    return payload


def _manual_request(request: RiskPreviewRequest) -> ManualConfirmRequest:
    metadata = _preview_metadata(request)
    return ManualConfirmRequest(
        mode=request.mode,
        user_id=request.user_id,
        account_balance=request.account_balance,
        risk_percent=request.risk_percent,
        risk_override=request.risk_override,
        execution_profile=request.execution_profile,
        leverage=request.leverage,
        liquidation_price=request.liquidation_price,
        size_usd=request.size_usd,
        fee_rate=request.fee_rate,
        slippage_bps=request.slippage_bps,
        metadata=metadata,
    )


def _preview_metadata(request: RiskPreviewRequest) -> dict[str, Any]:
    trace = {
        "signal_id": request.signal_id,
        "pending_entry_intent_id": request.pending_entry_intent_id,
    }
    trace = {key: value for key, value in trace.items() if value is not None}
    metadata: dict[str, Any] = {"lifecycle_trace": trace}
    if request.pending_entry_intent_id is not None:
        metadata["pending_entry_intent_id"] = request.pending_entry_intent_id
    return metadata


def _instrument_type(
    request: RiskPreviewRequest,
    manual_request: ManualConfirmRequest,
) -> InstrumentType:
    if request.instrument_type is not None:
        leverage = (
            request.risk_override.leverage
            if request.risk_override is not None and request.risk_override.leverage is not None
            else request.execution_profile.leverage
            if request.execution_profile is not None and request.execution_profile.leverage is not None
            else manual_request.leverage
        )
        return normalize_instrument_type(request.instrument_type, leverage=leverage)[0]
    if request.execution_profile is not None and request.execution_profile.instrument_type is not None:
        return request.execution_profile.instrument_type
    if request.risk_override is not None and request.risk_override.leverage is not None:
        return "futures" if request.risk_override.leverage > 1 else "spot"
    return "futures" if manual_request.leverage > 1 else "spot"


def _profile_instrument_type(instrument_type: InstrumentType | str) -> InstrumentType:
    return normalize_instrument_type(instrument_type)[0]


def strategy_risk_settings_for_signal(signal: RadarSignal, *, user_id: str) -> tuple[dict[str, Any], str]:
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


_strategy_risk_settings = strategy_risk_settings_for_signal


def _entry_price(signal: RadarSignal) -> float:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    if signal.entry_max is not None:
        return signal.entry_max
    raise ValueError("Signal has no entry zone")


risk_preview_service = RiskPreviewService()
