import unittest
from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.risk import (
    BreakevenPlan,
    PositionSizingResult,
    RiskAdjustmentPlan,
    RiskCheckResult,
    RiskDecision,
    StopLossPlan,
    TakeProfitPlan,
    TakeProfitTarget,
    TrailingStopPlan,
)
from app.schemas.signal import RadarSignal
from app.schemas.trade import ExecutionPlannedOrder, ManualConfirmRequest
from app.schemas.user import RiskManagementSettings
from app.services.execution_service import RealExecutionService


class _FakeRiskGateService:
    def __init__(self, decision: RiskDecision) -> None:
        self.decision = decision
        self.calls = 0

    def evaluate(self, *args, **kwargs) -> RiskDecision:
        self.calls += 1
        return self.decision


class _FakeExecutionAdapter:
    name = "fake"
    is_dry_run = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, ExecutionPlannedOrder]] = []

    async def place_order(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self.calls.append(("entry", order))
        return order.model_copy(update={"status": "submitted"})

    async def place_protective_stop(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self.calls.append(("protective_stop", order))
        return order.model_copy(update={"status": "submitted"})

    async def place_take_profit(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self.calls.append(("take_profit", order))
        return order.model_copy(update={"status": "submitted"})

    async def cancel_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        return None

    async def get_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        return None

    async def get_position(
        self,
        *,
        exchange: str,
        symbol: str,
    ) -> dict | None:
        return None


@dataclass(frozen=True)
class _Reference:
    exchange_min_order_size: float | None = None
    exchange_max_order_size: float | None = None
    exchange_min_notional: float | None = None
    exchange_max_leverage: int | None = None
    exchange_qty_step: float | None = None
    exchange_tick_size: float | None = None
    exchange_rule_status: str = "fresh"
    exchange_rule_age_seconds: float | None = None
    exchange_rule_ttl_seconds: int | None = None
    open_risk_amount: float = 0.0
    correlated_open_risk_amount: float = 0.0
    daily_loss_amount: float = 0.0
    correlation_group: str | None = None
    protection_state: str = "normal"
    protection_reason: str | None = None
    user_mode_multiplier: float = 1.0


class _FakeRiskState:
    def __init__(self, reference: _Reference) -> None:
        self.reference = reference

    def get_reference(self, *args, **kwargs) -> _Reference:
        return self.reference


class RealExecutionServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_returns_full_order_plan(self) -> None:
        service = _service(_decision())

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.adapter, "dry_run")
        self.assertIsNotNone(result.idempotency_key)
        self.assertEqual(
            [order.role for order in result.planned_orders],
            ["entry", "protective_stop", "take_profit", "take_profit"],
        )
        self.assertTrue(all(order.status == "dry_run" for order in result.planned_orders))

    async def test_no_adapter_returns_not_implemented_without_placing_order(self) -> None:
        service = _service(_decision(), execution_adapter=None)

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "not_implemented")
        self.assertEqual(
            [order.role for order in result.planned_orders],
            ["entry", "protective_stop", "take_profit", "take_profit"],
        )
        self.assertTrue(all(order.status == "planned" for order in result.planned_orders))

    async def test_protective_stop_is_included_and_reduce_only(self) -> None:
        service = _service(_decision())

        result = await service.place_order(_signal(), _request())

        stops = [order for order in result.planned_orders if order.role == "protective_stop"]
        self.assertEqual(len(stops), 1)
        self.assertTrue(stops[0].reduce_only)
        self.assertEqual(stops[0].stop_price, 95.0)

    async def test_take_profit_orders_are_included_from_risk_gate(self) -> None:
        service = _service(
            _decision(
                targets=[
                    TakeProfitTarget(label="TP1", r_multiple=1.0, price=105.0, close_percent=25.0, action="observe"),
                    TakeProfitTarget(label="TP2", r_multiple=2.0, price=110.0, close_percent=75.0, action="full_close"),
                ]
            )
        )

        result = await service.place_order(_signal(), _request())

        take_profits = [order for order in result.planned_orders if order.role == "take_profit"]
        self.assertEqual([order.price for order in take_profits], [105.0, 110.0])
        self.assertEqual([order.close_percent for order in take_profits], [25.0, 75.0])
        self.assertTrue(all(order.reduce_only for order in take_profits))

    async def test_idempotency_key_is_stable_for_same_signal_order_intent(self) -> None:
        service = _service(_decision())
        signal = _signal()
        request = _request()

        first = await service.place_order(signal, request)
        second = await service.place_order(signal, request)

        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(
            [order.client_order_id for order in first.planned_orders],
            [order.client_order_id for order in second.planned_orders],
        )
        self.assertEqual(
            [order.idempotency_key for order in first.planned_orders],
            [order.idempotency_key for order in second.planned_orders],
        )

    async def test_fake_adapter_receives_validated_plan(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(_decision(), execution_adapter=adapter)

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "submitted")
        self.assertEqual([role for role, _order in adapter.calls], ["entry", "protective_stop", "take_profit", "take_profit"])
        self.assertTrue(all(order.status == "submitted" for order in result.planned_orders))

    async def test_exchange_rule_step_validation_blocks_adapter_call(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(quantity=1.0),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference(exchange_qty_step=0.3, exchange_tick_size=0.5)),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertIn("quantity is not aligned to qty_step", result.message)
        self.assertEqual(adapter.calls, [])


def _service(
    decision: RiskDecision,
    *,
    execution_adapter=...,
    risk_state=None,
) -> RealExecutionService:
    kwargs = {}
    if execution_adapter is not ...:
        kwargs["execution_adapter"] = execution_adapter
    return RealExecutionService(
        risk_gate_service=_FakeRiskGateService(decision),
        risk_audit=None,
        risk_state=risk_state,
        market_data_service=None,
        fee_rate_service=None,
        risk_settings_provider=lambda _user_id: _risk_settings(),
        **kwargs,
    )


def _signal() -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_real_execution",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.8,
        risk_reward=2.0,
        score=80,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=95.0,
        take_profit_1=105.0,
        take_profit_2=110.0,
        created_at=now,
        updated_at=now,
    )


def _request() -> ManualConfirmRequest:
    return ManualConfirmRequest(
        mode="real",
        user_id="demo_user",
        account_balance=1_000.0,
        risk_percent=1.0,
        leverage=1,
    )


def _risk_settings() -> RiskManagementSettings:
    return RiskManagementSettings(
        risk_profile="balanced",
        risk_per_trade_percent=1.0,
        min_rr_ratio=1.0,
        max_daily_loss_percent=3.0,
        max_account_drawdown_percent=10.0,
        max_open_risk_percent=5.0,
        stop_loss_mode="structure",
        real_requires_fresh_market_data=False,
        real_requires_positive_edge=False,
    )


def _decision(
    *,
    quantity: float = 1.0,
    targets: list[TakeProfitTarget] | None = None,
) -> RiskDecision:
    targets = targets or [
        TakeProfitTarget(label="TP1", r_multiple=1.0, price=105.0, close_percent=50.0, action="observe"),
        TakeProfitTarget(label="TP2", r_multiple=2.0, price=110.0, close_percent=50.0, action="full_close"),
    ]
    sizing = PositionSizingResult(
        side="long",
        account_equity=1_000.0,
        risk_per_trade_percent=1.0,
        risk_amount=5.0 * quantity,
        entry_price=100.0,
        stop_loss_price=95.0,
        stop_distance_per_unit=5.0,
        effective_risk_per_unit=5.0,
        position_size_base=quantity,
        notional=100.0 * quantity,
        leverage=1,
        required_margin=100.0 * quantity,
        fee_rate=0.0,
        slippage_bps=0.0,
    )
    risk_adjustment = RiskAdjustmentPlan(
        instrument_type="spot",
        strategy="trend_pullback_continuation",
        signal_score=80.0,
        account_equity=1_000.0,
        base_risk_percent=1.0,
        base_risk_amount=10.0,
        strategy_risk_multiplier=1.0,
        signal_score_multiplier=1.0,
        adjusted_risk_percent=1.0,
        adjusted_risk_amount=10.0,
        signal_trade_allowed=True,
    )
    risk_check = RiskCheckResult(
        status="passed",
        blockers=[],
        warnings=[],
        rr=2.0,
        min_rr_ratio=1.0,
        account_equity=1_000.0,
        adjusted_risk_amount=10.0,
        adjusted_risk_percent=1.0,
        effective_risk_amount=5.0 * quantity,
        position_notional=100.0 * quantity,
        position_size_base=quantity,
        required_margin=100.0 * quantity,
        max_daily_loss_percent=3.0,
        max_account_drawdown_percent=10.0,
        max_open_risk_percent=5.0,
        max_correlated_risk_percent=3.0,
        exchange_rule_status="fresh",
        market_data_status="fresh",
    )
    stop_loss_plan = StopLossPlan(
        side="long",
        mode="structure",
        entry_price=100.0,
        stop_loss_price=95.0,
        risk_per_unit=5.0,
        source="signal",
        default_stop_loss_percent=1.5,
        atr_period=14,
        atr_multiplier=2.0,
    )
    take_profit_plan = TakeProfitPlan(
        mode="risk_multiple",
        side="long",
        entry_price=100.0,
        stop_loss_price=95.0,
        risk_per_unit=5.0,
        partial_take_profit_enabled=True,
        targets=targets,
        source="trade_plan",
        selected_rr=targets[-1].r_multiple,
    )
    return RiskDecision(
        mode="real",
        stage="pre_execution",
        status="passed",
        can_enter=True,
        exchange="bybit",
        symbol="BTCUSDT",
        instrument_type="spot",
        requested_notional=None,
        risk_adjustment_plan=risk_adjustment,
        position_sizing=sizing,
        checked_position_sizing=sizing,
        risk_check=risk_check,
        stop_loss_plan=stop_loss_plan,
        take_profit_plan=take_profit_plan,
        breakeven_plan=BreakevenPlan(
            side="long",
            entry_price=100.0,
            stop_loss_price=95.0,
            risk_per_unit=5.0,
            move_after_r=1.0,
            trigger_price=105.0,
            breakeven_stop_price=100.0,
        ),
        trailing_stop_plan=TrailingStopPlan(
            side="long",
            enabled=False,
            mode="percent",
            entry_price=100.0,
            current_price=100.0,
            trailing_percent=0.0,
            atr_multiplier=2.0,
            source="disabled",
        ),
    )


if __name__ == "__main__":
    unittest.main()
