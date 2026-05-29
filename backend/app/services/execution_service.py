from typing import Any

from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, RealExecutionResult
from app.services.risk_audit import RiskAuditService, risk_audit_service
from app.services.risk_fee_rate import RiskFeeRateService, risk_fee_rate_service
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.risk_management import get_user_risk_management_settings
from app.services.risk_market_data import RiskMarketDataService, risk_market_data_service
from app.services.risk_state import RiskStateService, risk_state_service


class RealExecutionService:
    """Real-order boundary stub.

    The exchange adapter is not connected yet, but every real attempt already
    goes through the backend risk gate and is written to the risk audit trail.
    """

    def __init__(
        self,
        risk_context_service: RiskContextService | None = None,
        risk_gate_service: RiskGateService | None = None,
        risk_audit: RiskAuditService | None = risk_audit_service,
        risk_state: RiskStateService | None = risk_state_service,
        market_data_service: RiskMarketDataService | None = risk_market_data_service,
        fee_rate_service: RiskFeeRateService | None = risk_fee_rate_service,
    ) -> None:
        self._risk_context_service = risk_context_service or RiskContextService()
        self._risk_gate_service = risk_gate_service or RiskGateService()
        self._risk_audit = risk_audit
        self._risk_state = risk_state
        self._market_data_service = market_data_service
        self._fee_rate_service = fee_rate_service

    async def place_order(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> RealExecutionResult:
        risk_settings = get_user_risk_management_settings(request.user_id)
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
        return RealExecutionResult(
            exchange=signal.exchange,
            symbol=signal.symbol,
            message=(
                "Real trade execution is not implemented yet. "
                "For MVP, use virtual trading."
            ),
            risk_decision=risk_decision,
            risk_decision_id=risk_decision_id,
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


real_execution_service = RealExecutionService()
