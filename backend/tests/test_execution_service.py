import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.exchanges.bybit import (
    BYBIT_MAINNET_ORDER_PLACEMENT_DISABLED_REASON,
    LIVE_ORDER_PLACEMENT_DISABLED_REASON,
    BybitRealExecutionAdapter,
)
from app.schemas.risk import (
    AccountRiskSnapshot,
    BreakevenPlan,
    FuturesRiskPlan,
    PositionSizingResult,
    RiskAdjustmentPlan,
    RiskCheckResult,
    RiskDecision,
    StopLossPlan,
    TakeProfitPlan,
    TakeProfitTarget,
    TrailingStopPlan,
)
from app.schemas.decision import SignalDecisionSnapshot
from app.schemas.signal import NoTradeFilterResult, RadarSignal
from app.schemas.trade import ExecutionPlannedOrder, ManualConfirmRequest, RealExecutionPlan
from app.schemas.trade_plan import (
    TargetThesis,
    TradePlan,
    TradePlanEntry,
    TradePlanInvalidation,
    TradePlanTarget,
)
from app.schemas.user import RiskManagementSettings
from app.services.execution_service import RealExecutionService
from app.services.real_execution_readiness import RealExecutionReadinessService
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.risk_market_data import RiskMarketDataSnapshot


class _FakeRiskGateService:
    def __init__(self, decision: RiskDecision) -> None:
        self.decision = decision
        self.calls = 0
        self.contexts = []

    def evaluate(self, *args, **kwargs) -> RiskDecision:
        self.calls += 1
        self.contexts.append(kwargs.get("context"))
        return self.decision


class _FakeExecutionAdapter:
    name = "fake"
    is_dry_run = False
    supports_bracket_orders = True
    supports_oco = False
    guarantees_protective_after_entry = True
    supports_reduce_only = True
    protective_order_guarantee = True
    position_reconciliation_enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, ExecutionPlannedOrder]] = []
        self.orders: dict[tuple[str, str, str], ExecutionPlannedOrder] = {}

    async def place_order(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self.calls.append(("entry", order))
        return self._record(order, status="submitted")

    async def place_protective_stop(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self.calls.append(("protective_stop", order))
        return self._record(order, status="submitted")

    async def place_take_profit(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self.calls.append(("take_profit", order))
        return self._record(order, status="submitted")

    async def cancel_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        order = await self.get_order(exchange=exchange, symbol=symbol, client_order_id=client_order_id)
        if order is None:
            return None
        cancelled = order.model_copy(update={"status": "cancelled"})
        self.orders[_order_key(cancelled)] = cancelled
        return cancelled

    async def replace_order(
        self,
        *,
        current_client_order_id: str,
        replacement: ExecutionPlannedOrder,
    ) -> ExecutionPlannedOrder:
        current = await self.get_order(
            exchange=replacement.exchange,
            symbol=replacement.symbol,
            client_order_id=current_client_order_id,
        )
        if current is None:
            raise ValueError("missing current order")
        if current.role != replacement.role:
            raise ValueError("role mismatch")
        await self.cancel_order(
            exchange=current.exchange,
            symbol=current.symbol,
            client_order_id=current.client_order_id,
        )
        return self._record(replacement, status="submitted")

    async def get_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        return self.orders.get((exchange.strip().lower(), symbol.strip().upper(), client_order_id))

    async def get_open_orders(
        self,
        *,
        exchange: str,
        symbol: str,
    ) -> list[ExecutionPlannedOrder]:
        return [
            order
            for key, order in self.orders.items()
            if key[0] == exchange.strip().lower()
            and key[1] == symbol.strip().upper()
            and order.status not in {"cancelled", "canceled", "rejected", "expired"}
        ]

    async def get_position(
        self,
        *,
        exchange: str,
        symbol: str,
    ) -> dict | None:
        return None

    def _record(self, order: ExecutionPlannedOrder, *, status: str) -> ExecutionPlannedOrder:
        recorded = order.model_copy(
            update={
                "status": status,
                "exchange_order_id": f"ex-{order.client_order_id}",
            }
        )
        self.orders[_order_key(recorded)] = recorded
        return recorded


class _PartialFillExecutionAdapter(_FakeExecutionAdapter):
    async def place_order(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self.calls.append(("entry", order))
        recorded = order.model_copy(
            update={
                "status": "partially_filled",
                "exchange_order_id": f"ex-{order.client_order_id}",
                "filled_qty": order.quantity / 2,
                "remaining_qty": order.quantity / 2,
                "avg_fill_price": order.price,
                "fees": 0.1,
            }
        )
        self.orders[_order_key(recorded)] = recorded
        return recorded


class _DryReadinessAdapter:
    name = "dry_readiness"
    is_dry_run = True


class _NotImplementedLiveAdapter(_FakeExecutionAdapter):
    name = "not_implemented_live"
    live_order_placement_implemented = False


class _NoProtectiveGuaranteeAdapter(_FakeExecutionAdapter):
    name = "no_protective_guarantee"
    supports_bracket_orders = False
    supports_oco = False
    guarantees_protective_after_entry = False
    supports_reduce_only = True
    protective_order_guarantee = False


@dataclass(frozen=True)
class _LiveTradingSettings:
    enable_live_trading: bool = False
    enable_bybit_live_order_placement: bool = False
    enable_bybit_mainnet_order_placement: bool = False
    require_protective_stop_for_live_entry: bool = True


def _order_key(order: ExecutionPlannedOrder) -> tuple[str, str, str]:
    return (
        order.exchange.strip().lower(),
        order.symbol.strip().upper(),
        order.client_order_id,
    )


@dataclass(frozen=True)
class _Reference:
    exchange_min_order_size: float | None = None
    exchange_max_order_size: float | None = None
    exchange_min_notional: float | None = 10.0
    exchange_max_leverage: int | None = None
    exchange_qty_step: float | None = 0.0001
    exchange_tick_size: float | None = 0.01
    exchange_rule_status: str = "fresh"
    exchange_rule_age_seconds: float | None = None
    exchange_rule_ttl_seconds: int | None = None
    real_account_snapshot_status: str = "fresh"
    real_account_snapshot_source: str = "exchange"
    real_account_equity: float | None = 1_000.0
    real_available_balance: float | None = 1_000.0
    position_reconciliation_enabled: bool = True
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

    def get_real_account_snapshot(self, *args, **kwargs) -> AccountRiskSnapshot:
        return AccountRiskSnapshot(
            status=self.reference.real_account_snapshot_status,
            fetched_at=datetime.now(timezone.utc)
            if self.reference.real_account_snapshot_status == "fresh"
            else None,
            account_equity=self.reference.real_account_equity,
            available_balance=self.reference.real_available_balance,
            margin_mode="spot",
            open_risk_amount=self.reference.open_risk_amount,
            source=self.reference.real_account_snapshot_source,
        )


class _FakeMarketDataService:
    def build_snapshot(self, *args, **kwargs) -> RiskMarketDataSnapshot:
        entry_price = float(kwargs["fallback_entry_price"])
        return RiskMarketDataSnapshot(
            exchange=kwargs["exchange"],
            symbol=kwargs["symbol"],
            category="spot",
            entry_price=entry_price,
            slippage_bps=kwargs.get("manual_slippage_bps", 0.0),
            best_bid=entry_price - 0.05,
            best_ask=entry_price + 0.05,
            mark_price=entry_price,
            spread_percent=0.1,
            spread_bps=10.0,
            orderbook_depth_usd=100_000.0,
            market_data_status="fresh",
            market_data_source="test",
        )


class _FakeFeeRateService:
    def __init__(self, *, fetched_at: datetime | None = None, source: str = "exchange_cache") -> None:
        self.fetched_at = fetched_at or datetime.now(timezone.utc)
        self.source = source

    def resolve(self, *args, **kwargs) -> RiskFeeRateSnapshot:
        return RiskFeeRateSnapshot(
            fee_rate=0.00055,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.00055,
            source=self.source,
            exchange=kwargs["exchange"],
            category="spot" if kwargs["instrument_type"] == "spot" else "linear",
            symbol=kwargs["symbol"],
            fetched_at=self.fetched_at,
        )


class _TrackingMarketDataService(_FakeMarketDataService):
    def __init__(self) -> None:
        self.calls = 0

    def build_snapshot(self, *args, **kwargs) -> RiskMarketDataSnapshot:
        self.calls += 1
        return super().build_snapshot(*args, **kwargs)


class _TrackingFeeRateService(_FakeFeeRateService):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def resolve(self, *args, **kwargs) -> RiskFeeRateSnapshot:
        self.calls += 1
        return super().resolve(*args, **kwargs)


class RealExecutionServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_returns_full_order_plan(self) -> None:
        service = _service(_decision())

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "dry_run")
        self.assertTrue(result.signal_valid)
        self.assertTrue(result.execution_allowed)
        self.assertEqual(result.adapter, "dry_run")
        self.assertIsNotNone(result.idempotency_key)
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        self.assertEqual(result.execution_plan.protective_order_strategy, "sequential_dry_run")
        self.assertTrue(
            any("Dry-run simulates entry" in warning for warning in result.warnings)
        )
        self.assertEqual(
            [order.role for order in result.planned_orders],
            ["entry", "protective_stop", "take_profit", "take_profit"],
        )
        self.assertTrue(all(order.status == "dry_run" for order in result.planned_orders))
        for order in result.planned_orders:
            self.assertEqual(order.metadata["role"], order.role)
            self.assertEqual(order.metadata["client_order_id"], order.client_order_id)
            self.assertEqual(order.metadata["reduce_only"], order.reduce_only)

    async def test_no_adapter_returns_not_implemented_without_placing_order(self) -> None:
        service = _service(_decision(), execution_adapter=None)

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "not_implemented")
        self.assertTrue(result.signal_valid)
        self.assertTrue(result.execution_allowed)
        self.assertEqual(
            [order.role for order in result.planned_orders],
            ["entry", "protective_stop", "take_profit", "take_profit"],
        )
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        self.assertEqual(result.execution_plan.protective_order_strategy, "unsupported")
        self.assertTrue(all(order.status == "planned" for order in result.planned_orders))

    async def test_unimplemented_live_adapter_returns_not_implemented_before_adapter_call(self) -> None:
        adapter = _NotImplementedLiveAdapter()
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "not_implemented")
        self.assertTrue(result.signal_valid)
        self.assertTrue(result.execution_allowed)
        self.assertIn("not implemented", result.message)
        self.assertEqual(adapter.calls, [])

    async def test_bybit_live_order_flags_default_block_before_http_boundaries(self) -> None:
        adapter = BybitRealExecutionAdapter(
            connection_metadata={"testnet": True},
            settings_override=_LiveTradingSettings(),
        )
        gate = _FakeRiskGateService(_decision())
        market_data = _TrackingMarketDataService()
        fee_rates = _TrackingFeeRateService()
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(_Reference()),
            market_data_service=market_data,
            fee_rate_service=fee_rates,
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "not_implemented")
        self.assertFalse(result.execution_allowed)
        self.assertEqual(result.message, LIVE_ORDER_PLACEMENT_DISABLED_REASON)
        self.assertEqual(result.validation_errors, [LIVE_ORDER_PLACEMENT_DISABLED_REASON])
        self.assertEqual(result.planned_orders, [])
        self.assertEqual(gate.calls, 0)
        self.assertEqual(market_data.calls, 0)
        self.assertEqual(fee_rates.calls, 0)

    async def test_bybit_testnet_live_flags_reach_adapter_implementation_blocker(self) -> None:
        adapter = BybitRealExecutionAdapter(
            connection_metadata={"testnet": True},
            settings_override=_LiveTradingSettings(
                enable_live_trading=True,
                enable_bybit_live_order_placement=True,
            ),
        )
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "not_implemented")
        self.assertTrue(result.execution_allowed)
        self.assertIn("not implemented", result.message)
        self.assertNotEqual(result.message, LIVE_ORDER_PLACEMENT_DISABLED_REASON)

    async def test_bybit_mainnet_live_order_flag_blocks_before_http_boundaries(self) -> None:
        adapter = BybitRealExecutionAdapter(
            connection_metadata={"testnet": False},
            settings_override=_LiveTradingSettings(
                enable_live_trading=True,
                enable_bybit_live_order_placement=True,
            ),
        )
        gate = _FakeRiskGateService(_decision())
        market_data = _TrackingMarketDataService()
        fee_rates = _TrackingFeeRateService()
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(_Reference()),
            market_data_service=market_data,
            fee_rate_service=fee_rates,
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "not_implemented")
        self.assertFalse(result.execution_allowed)
        self.assertEqual(result.message, BYBIT_MAINNET_ORDER_PLACEMENT_DISABLED_REASON)
        self.assertEqual(result.validation_errors, [BYBIT_MAINNET_ORDER_PLACEMENT_DISABLED_REASON])
        self.assertEqual(result.planned_orders, [])
        self.assertEqual(gate.calls, 0)
        self.assertEqual(market_data.calls, 0)
        self.assertEqual(fee_rates.calls, 0)

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

    async def test_real_execution_blocks_without_structural_stop(self) -> None:
        service = _service(_decision())

        result = await service.place_order(
            _signal(trade_plan=_missing_structural_trade_plan(), decision=_real_allowed_decision(trade_plan_valid=False)),
            _request(),
        )

        self.assertEqual(result.status, "readiness_failed")
        self.assertFalse(result.execution_allowed)
        self.assertIn("structural stop", result.message)

    async def test_real_execution_blocks_fallback_stop(self) -> None:
        service = _service(_decision())

        result = await service.place_order(_signal(trade_plan=_fallback_stop_trade_plan()), _request())

        self.assertEqual(result.status, "readiness_failed")
        self.assertFalse(result.execution_allowed)
        self.assertIn("fallback stop", result.message)

    async def test_real_execution_blocks_without_protective_orders(self) -> None:
        service = _service(_decision(protective_orders_allowed=False))

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertFalse(result.execution_allowed)
        self.assertIn("Protective orders are not allowed", result.message)

    async def test_real_execution_requires_idempotency_key(self) -> None:
        request = _request()
        plan = RealExecutionPlan.model_construct(
            exchange="bybit",
            symbol="BTCUSDT",
            side="long",
            entry_price=100.0,
            quantity=1.0,
            notional=100.0,
            leverage=1,
            idempotency_key="",
            client_order_id="plan-client",
            planned_orders=[
                ExecutionPlannedOrder.model_construct(
                    role="entry",
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="buy",
                    order_type="market",
                    quantity=1.0,
                    price=100.0,
                    reduce_only=False,
                    client_order_id="entry-client",
                    idempotency_key="",
                    status="planned",
                    metadata={},
                ),
                ExecutionPlannedOrder.model_construct(
                    role="protective_stop",
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="sell",
                    order_type="stop",
                    quantity=1.0,
                    stop_price=95.0,
                    reduce_only=True,
                    client_order_id="stop-client",
                    idempotency_key="stop-key",
                    status="planned",
                    metadata={},
                ),
                ExecutionPlannedOrder.model_construct(
                    role="take_profit",
                    exchange="bybit",
                    symbol="BTCUSDT",
                    side="sell",
                    order_type="take_profit",
                    quantity=1.0,
                    price=110.0,
                    reduce_only=True,
                    close_percent=100.0,
                    client_order_id="tp-client",
                    idempotency_key="tp-key",
                    status="planned",
                    metadata={},
                ),
            ],
            metadata={},
        )

        result = RealExecutionReadinessService().evaluate(
            signal=_signal(),
            request=request,
            risk_decision=_decision(),
            execution_plan=plan,
            risk_settings=_risk_settings(),
            reference=None,
            fee_rate=None,
            adapter=_DryReadinessAdapter(),
        )

        self.assertFalse(result.ready)
        self.assertIn("Real execution plan idempotency key is required.", result.blockers)
        self.assertIn("entry order idempotency_key is required.", result.blockers)

    async def test_duplicate_real_execution_request_does_not_duplicate_orders(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )
        signal = _signal()
        request = _request()

        first = await service.place_order(signal, request)
        second = await service.place_order(signal, request)

        self.assertEqual(first.status, "submitted")
        self.assertEqual(second.status, "submitted")
        self.assertEqual(len(adapter.calls), 4)
        self.assertTrue(all(order.metadata.get("idempotent_replay") for order in second.planned_orders))

    async def test_live_adapter_without_protective_guarantee_blocks_before_entry(self) -> None:
        adapter = _NoProtectiveGuaranteeAdapter()
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "readiness_failed")
        self.assertFalse(result.execution_allowed)
        self.assertIn("protective", result.message.lower())
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        self.assertEqual(result.execution_plan.protective_order_strategy, "unsupported")
        self.assertEqual(adapter.calls, [])

    async def test_partial_fill_creates_reconciliation_state(self) -> None:
        adapter = _PartialFillExecutionAdapter()
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "partially_filled")
        self.assertEqual(result.planned_orders[0].status, "partially_filled")
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        self.assertTrue(result.execution_plan.metadata["reconciliation_required"])
        self.assertEqual(result.execution_plan.metadata["reconciliation_state"]["reason"], "partial_fill")

    async def test_real_execution_feature_flag_default_false(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "readiness_failed")
        self.assertFalse(result.execution_allowed)
        self.assertIn("real_execution_enabled=false", result.message)
        self.assertEqual(adapter.calls, [])

    async def test_fake_adapter_receives_validated_plan_when_live_readiness_passes(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "submitted")
        self.assertTrue(result.signal_valid)
        self.assertTrue(result.execution_allowed)
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        self.assertEqual(result.execution_plan.protective_order_strategy, "bracket")
        self.assertEqual(
            [role for role, _order in adapter.calls],
            ["entry", "protective_stop", "take_profit", "take_profit"],
        )
        self.assertTrue(all(order.status == "submitted" for order in result.planned_orders))
        self.assertTrue(result.execution_plan.metadata["reconciliation_required"])

    async def test_live_missing_take_profit_blocks_before_adapter_call(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(targets=[]),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertFalse(result.execution_allowed)
        self.assertIn("take-profit", result.message)
        self.assertEqual(adapter.calls, [])

    async def test_live_missing_stop_blocks_before_adapter_call(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision_without_stop_loss(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertFalse(result.execution_allowed)
        self.assertIn("Protective stop order must include stop_price", result.message)
        self.assertEqual(adapter.calls, [])

    async def test_exchange_rule_normalization_rounds_qty_down_before_submit(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(quantity=1.0),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference(exchange_qty_step=0.3, exchange_tick_size=0.5)),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "submitted")
        self.assertEqual(
            [role for role, _order in adapter.calls],
            ["entry", "protective_stop", "take_profit", "take_profit"],
        )
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        self.assertEqual(result.execution_plan.requested_quantity, 1.0)
        self.assertAlmostEqual(result.execution_plan.normalized_quantity or 0.0, 0.9)
        self.assertAlmostEqual(result.execution_plan.quantity, 0.9)
        entry_order = result.planned_orders[0]
        self.assertEqual(entry_order.requested_quantity, 1.0)
        self.assertAlmostEqual(entry_order.normalized_quantity or 0.0, 0.9)
        self.assertIn("qty_step", entry_order.rounding_reason or "")
        normalization = result.execution_plan.metadata["order_rule_normalization"]
        self.assertEqual(normalization["risk_trace"]["requested_quantity"], 1.0)
        self.assertAlmostEqual(normalization["risk_trace"]["normalized_quantity"], 0.9)
        self.assertAlmostEqual(normalization["risk_trace"]["normalized_risk_amount"], 4.5)

    async def test_exchange_rule_normalization_rounds_price_to_tick_before_submit(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(
                targets=[
                    TakeProfitTarget(label="TP1", r_multiple=1.0, price=105.2, close_percent=50.0, action="observe"),
                    TakeProfitTarget(label="TP2", r_multiple=2.0, price=110.2, close_percent=50.0, action="full_close"),
                ]
            ),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference(exchange_tick_size=0.5)),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "submitted")
        take_profits = [order for order in result.planned_orders if order.role == "take_profit"]
        self.assertEqual([order.requested_price for order in take_profits], [105.2, 110.2])
        self.assertEqual([order.normalized_price for order in take_profits], [105.0, 110.0])
        self.assertEqual([order.price for order in take_profits], [105.0, 110.0])
        self.assertTrue(all("tick_size" in (order.rounding_reason or "") for order in take_profits))

    async def test_exchange_rule_normalization_blocks_rounded_qty_below_min_qty(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(quantity=0.11),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(
                _Reference(
                    exchange_min_order_size=0.15,
                    exchange_qty_step=0.1,
                    exchange_tick_size=0.01,
                )
            ),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertIn("normalized quantity is below exchange minimum order size", result.message)
        self.assertEqual(adapter.calls, [])
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        self.assertAlmostEqual(result.execution_plan.normalized_quantity or 0.0, 0.1)

    async def test_exchange_rule_normalization_blocks_rounded_notional_below_min_notional(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(quantity=1.0),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(
                _Reference(
                    exchange_qty_step=0.3,
                    exchange_tick_size=0.5,
                    exchange_min_notional=250.0,
                )
            ),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertNotIn("not aligned to qty_step", result.message)
        self.assertIn("normalized notional is below exchange minimum notional", result.message)
        self.assertEqual(adapter.calls, [])
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        self.assertAlmostEqual(result.execution_plan.normalized_notional or 0.0, 90.0)

    async def test_order_rule_normalization_preserves_reduce_only_protective_flags(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(quantity=1.0),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference(exchange_qty_step=0.3, exchange_tick_size=0.5)),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "submitted")
        flags_by_role = [
            (order.role, order.reduce_only, order.metadata["reduce_only"])
            for order in result.planned_orders
        ]
        self.assertEqual(
            flags_by_role,
            [
                ("entry", False, False),
                ("protective_stop", True, True),
                ("take_profit", True, True),
                ("take_profit", True, True),
            ],
        )

    async def test_real_balance_required_not_virtual_equity(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(
                _Reference(
                    real_account_snapshot_status="missing",
                    real_account_equity=None,
                    real_available_balance=None,
                )
            ),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertIn("Fresh exchange account snapshot is required before live entry.", result.message)
        self.assertIn("Exchange account equity is missing.", result.message)
        self.assertIn("Exchange available balance is insufficient.", result.message)
        self.assertEqual(adapter.calls, [])

    async def test_live_stale_account_snapshot_blocks_before_risk_gate_and_adapter(self) -> None:
        adapter = _FakeExecutionAdapter()
        gate = _FakeRiskGateService(_decision())
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(
                _Reference(
                    real_account_snapshot_status="stale",
                    real_account_equity=1_000.0,
                    real_available_balance=1_000.0,
                )
            ),
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=_FakeFeeRateService(),
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertIn("Fresh exchange account snapshot is required before live entry.", result.message)
        self.assertEqual(gate.calls, 0)
        self.assertEqual(adapter.calls, [])

    async def test_live_missing_account_snapshot_blocks_before_risk_gate_and_adapter(self) -> None:
        adapter = _FakeExecutionAdapter()
        gate = _FakeRiskGateService(_decision())
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(
                _Reference(
                    real_account_snapshot_status="missing",
                    real_account_equity=None,
                    real_available_balance=None,
                )
            ),
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=_FakeFeeRateService(),
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertIn("Fresh exchange account snapshot is required before live entry.", result.message)
        self.assertEqual(gate.calls, 0)
        self.assertEqual(adapter.calls, [])

    async def test_live_request_account_balance_without_exchange_snapshot_blocks_entry(self) -> None:
        adapter = _FakeExecutionAdapter()
        gate = _FakeRiskGateService(_decision(account_equity=999_999.0))
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(
                _Reference(
                    real_account_snapshot_status="missing",
                    real_account_equity=None,
                    real_available_balance=None,
                )
            ),
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=_FakeFeeRateService(),
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request(account_balance=999_999.0))

        self.assertEqual(result.status, "risk_failed")
        self.assertIn("Fresh exchange account snapshot is required before live entry.", result.message)
        self.assertIn("Exchange account equity is missing.", result.message)
        self.assertEqual(gate.calls, 0)
        self.assertEqual(adapter.calls, [])

    async def test_live_request_source_snapshot_blocks_before_risk_gate_and_adapter(self) -> None:
        adapter = _FakeExecutionAdapter()
        gate = _FakeRiskGateService(_decision())
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(
                _Reference(
                    real_account_snapshot_source="request",
                    real_account_equity=1_000.0,
                    real_available_balance=1_000.0,
                )
            ),
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=_FakeFeeRateService(),
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request(account_balance=1_000.0))

        self.assertEqual(result.status, "risk_failed")
        self.assertIn("Live entry requires source=exchange account snapshot.", result.message)
        self.assertEqual(gate.calls, 0)
        self.assertEqual(adapter.calls, [])

    async def test_live_zero_available_balance_blocks_before_risk_gate_and_adapter(self) -> None:
        adapter = _FakeExecutionAdapter()
        gate = _FakeRiskGateService(_decision())
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(
                _Reference(
                    real_account_equity=1_000.0,
                    real_available_balance=0.0,
                )
            ),
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=_FakeFeeRateService(),
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "risk_failed")
        self.assertIn("Exchange available balance is insufficient.", result.message)
        self.assertEqual(gate.calls, 0)
        self.assertEqual(adapter.calls, [])

    async def test_live_fresh_snapshot_is_used_for_risk_gate_sizing_context(self) -> None:
        adapter = _FakeExecutionAdapter()
        gate = _FakeRiskGateService(_decision(account_equity=2_500.0))
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(
                _Reference(
                    real_account_equity=2_500.0,
                    real_available_balance=2_400.0,
                )
            ),
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=_FakeFeeRateService(),
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request(account_balance=999_999.0))

        self.assertEqual(result.status, "submitted")
        self.assertEqual(gate.calls, 1)
        context = gate.contexts[0]
        self.assertEqual(context.account_equity, 2_500.0)
        self.assertEqual(context.available_balance, 2_400.0)
        self.assertEqual(context.account_snapshot_source, "exchange")

    async def test_request_account_balance_cannot_override_fresh_exchange_snapshot(self) -> None:
        adapter = _FakeExecutionAdapter()
        gate = _FakeRiskGateService(_decision(account_equity=3_000.0))
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=_FakeRiskState(
                _Reference(
                    real_account_equity=3_000.0,
                    real_available_balance=2_750.0,
                )
            ),
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=_FakeFeeRateService(),
            execution_adapter=adapter,
            risk_settings_provider=lambda _user_id: _risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request(account_balance=25_000.0))

        self.assertEqual(result.status, "submitted")
        context = gate.contexts[0]
        self.assertEqual(context.account_equity, 3_000.0)
        self.assertNotEqual(context.account_equity, 25_000.0)

    async def test_dry_run_uses_demo_request_balance_with_warning_source(self) -> None:
        gate = _FakeRiskGateService(_decision())
        service = RealExecutionService(
            risk_gate_service=gate,
            risk_audit=None,
            risk_state=None,
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings_provider=lambda _user_id: _risk_settings(),
        )

        result = await service.place_order(_signal(), _request(account_balance=1_234.0))

        self.assertEqual(result.status, "dry_run")
        context = gate.contexts[0]
        self.assertEqual(context.account_equity, 1_234.0)
        self.assertIn(context.account_snapshot_source, {"demo", "dry_run"})
        self.assertTrue(any("Dry-run real execution uses request/demo" in warning for warning in context.account_snapshot_warnings))

    async def test_fee_rate_ttl_required(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(
                fetched_at=datetime.now(timezone.utc) - timedelta(days=2)
            ),
            risk_settings=_risk_settings(real_execution_enabled=True, real_fee_rate_ttl_seconds=60),
        )

        result = await service.place_order(_signal(), _request())

        self.assertEqual(result.status, "readiness_failed")
        self.assertIn("Fee-rate snapshot is stale", result.message)
        self.assertEqual(adapter.calls, [])

    async def test_liquidation_projection_required_for_derivatives(self) -> None:
        adapter = _FakeExecutionAdapter()
        service = _service(
            _decision(instrument_type="futures", leverage=2, futures_risk_plan=None),
            execution_adapter=adapter,
            risk_state=_FakeRiskState(_Reference()),
            fee_rate_service=_FakeFeeRateService(),
            risk_settings=_risk_settings(real_execution_enabled=True),
        )

        result = await service.place_order(_signal(), _request(leverage=2))

        self.assertEqual(result.status, "readiness_failed")
        self.assertIn("liquidation projection", result.message)
        self.assertEqual(adapter.calls, [])

    async def test_low_rr_hard_real_policy_blocks_execution_not_signal(self) -> None:
        service = _service(
            None,
            market_data_service=_FakeMarketDataService(),
            risk_settings=_risk_settings(
                min_rr_ratio=2.0,
                real_rr_guard_mode="hard",
                tp1_r_multiple=0.5,
                tp2_r_multiple=1.0,
                tp3_r_multiple=1.5,
            ),
        )

        result = await service.place_order(
            _signal(trade_plan=_low_rr_trade_plan()),
            _request(),
        )

        self.assertEqual(result.status, "risk_failed")
        self.assertTrue(result.signal_valid)
        self.assertFalse(result.execution_allowed)
        self.assertIn("Real execution RR policy rejected", result.message)
        self.assertIn("selected R:R 1.50R is below minimum 2.00R", result.message)
        self.assertNotIn("signal rejected", result.message.lower())
        self.assertNotIn("invalid signal", result.message.lower())
        self.assertIsNotNone(result.risk_decision)
        assert result.risk_decision is not None
        self.assertTrue(
            any("Real execution RR policy rejected" in blocker for blocker in result.risk_decision.blockers)
        )
        self.assertTrue(result.risk_decision.risk_check.risk_reward_blocked)

    async def test_low_rr_soft_real_policy_warns_and_allows_execution(self) -> None:
        service = _service(
            None,
            market_data_service=_FakeMarketDataService(),
            risk_settings=_risk_settings(
                min_rr_ratio=2.0,
                real_rr_guard_mode="soft",
                tp1_r_multiple=0.5,
                tp2_r_multiple=1.0,
                tp3_r_multiple=1.5,
            ),
        )

        result = await service.place_order(
            _signal(trade_plan=_low_rr_trade_plan()),
            _request(),
        )

        self.assertEqual(result.status, "dry_run")
        self.assertTrue(result.signal_valid)
        self.assertTrue(result.execution_allowed)
        self.assertIsNotNone(result.risk_decision)
        assert result.risk_decision is not None
        self.assertFalse(
            any("Real execution RR policy rejected" in blocker for blocker in result.risk_decision.blockers)
        )
        self.assertTrue(
            any("Risk/reward warning" in warning for warning in result.risk_decision.warnings)
        )
        self.assertTrue(result.risk_decision.risk_check.risk_reward_warning)

    async def test_no_trade_signal_blocks_execution_not_signal_validity(self) -> None:
        no_trade_reason = "No-trade policy blocks real execution during scheduled news."
        service = _service(
            None,
            market_data_service=_FakeMarketDataService(),
            risk_settings=_risk_settings(min_rr_ratio=1.0, real_rr_guard_mode="hard"),
        )

        result = await service.place_order(
            _signal(no_trade_filter=NoTradeFilterResult(blocked=True, hard_block=True, blockers=[no_trade_reason])),
            _request(),
        )

        self.assertEqual(result.status, "risk_failed")
        self.assertTrue(result.signal_valid)
        self.assertFalse(result.execution_allowed)
        self.assertIn("Execution not allowed by risk gate", result.message)
        self.assertIsNotNone(result.risk_decision)
        assert result.risk_decision is not None
        self.assertIn(no_trade_reason, result.risk_decision.blockers)


def _service(
    decision: RiskDecision | None,
    *,
    execution_adapter=...,
    risk_state=None,
    market_data_service=None,
    fee_rate_service=None,
    risk_settings: RiskManagementSettings | None = None,
) -> RealExecutionService:
    kwargs = {}
    if execution_adapter is not ...:
        kwargs["execution_adapter"] = execution_adapter
    risk_gate_service = _FakeRiskGateService(decision) if decision is not None else None
    return RealExecutionService(
        risk_gate_service=risk_gate_service,
        risk_audit=None,
        risk_state=risk_state,
        market_data_service=market_data_service,
        fee_rate_service=fee_rate_service,
        risk_settings_provider=lambda _user_id: risk_settings or _risk_settings(),
        **kwargs,
    )


def _signal(
    *,
    no_trade_filter: NoTradeFilterResult | None = None,
    trade_plan: TradePlan | None = None,
    decision: SignalDecisionSnapshot | None = None,
    status: str = "actionable",
) -> RadarSignal:
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
        status=status,
        trade_plan=trade_plan if trade_plan is not None else _structural_trade_plan(),
        decision=decision if decision is not None else _real_allowed_decision(),
        no_trade_filter=no_trade_filter,
        created_at=now,
        updated_at=now,
    )


def _real_allowed_decision(
    *,
    signal_actionable: bool = True,
    execution_allowed_real: bool | None = True,
    trade_plan_valid: bool = True,
) -> SignalDecisionSnapshot:
    return SignalDecisionSnapshot(
        setup_valid=True,
        trade_plan_valid=trade_plan_valid,
        market_context_score=90.0,
        signal_actionable=signal_actionable,
        execution_allowed_virtual=True,
        execution_allowed_real=execution_allowed_real,
    )


def _structural_trade_plan() -> TradePlan:
    return TradePlan(
        entry=TradePlanEntry(price=100.0, min_price=100.0, max_price=100.0, source="test_structure"),
        stop_loss=95.0,
        targets=[
            TradePlanTarget(
                label="TP1",
                price=105.0,
                r_multiple=1.0,
                close_percent=50.0,
                source="range_midpoint",
                thesis=TargetThesis(
                    source="range_midpoint",
                    price=105.0,
                    direction="LONG",
                    confidence=0.8,
                    priority=1,
                    close_percent=50.0,
                    requires_acceptance=False,
                ),
            ),
            TradePlanTarget(
                label="TP2",
                price=110.0,
                r_multiple=2.0,
                close_percent=50.0,
                source="htf_resistance",
                thesis=TargetThesis(
                    source="htf_resistance",
                    price=110.0,
                    direction="LONG",
                    confidence=0.75,
                    priority=2,
                    close_percent=50.0,
                    requires_acceptance=False,
                ),
            ),
        ],
        invalidation=TradePlanInvalidation(
            price=95.0,
            hard_stop=95.0,
            conditions=["Close below pullback structure invalidates continuation."],
            metadata={"source": "structure"},
        ),
        metadata={"source": "test_structure", "target_source": "structural"},
    )


def _fallback_stop_trade_plan() -> TradePlan:
    plan = _structural_trade_plan()
    return plan.model_copy(
        update={
            "metadata": {**plan.metadata, "fallback_used": True, "fallback_stop_used": True},
        }
    )


def _low_rr_trade_plan() -> TradePlan:
    plan = _structural_trade_plan()
    targets = [
        plan.targets[0].model_copy(update={"price": 102.5, "r_multiple": 0.5}),
        plan.targets[1].model_copy(update={"price": 107.5, "r_multiple": 1.5}),
    ]
    return plan.model_copy(update={"targets": targets})


def _missing_structural_trade_plan() -> TradePlan:
    plan = _structural_trade_plan()
    return plan.model_copy(update={"stop_loss": None})


def _request(*, leverage: int = 1, account_balance: float = 1_000.0) -> ManualConfirmRequest:
    return ManualConfirmRequest(
        mode="real",
        user_id="demo_user",
        account_balance=account_balance,
        risk_percent=1.0,
        leverage=leverage,
    )


def _risk_settings(
    *,
    min_rr_ratio: float = 1.0,
    real_rr_guard_mode: str = "hard",
    tp1_r_multiple: float = 1.0,
    tp2_r_multiple: float = 2.0,
    tp3_r_multiple: float = 3.0,
    real_execution_enabled: bool = False,
    real_fee_rate_ttl_seconds: int = 86_400,
) -> RiskManagementSettings:
    return RiskManagementSettings(
        risk_profile="balanced",
        risk_per_trade_percent=1.0,
        min_rr_ratio=min_rr_ratio,
        real_rr_guard_mode=real_rr_guard_mode,
        max_daily_loss_percent=3.0,
        max_account_drawdown_percent=10.0,
        max_open_risk_percent=5.0,
        stop_loss_mode="structure",
        tp1_r_multiple=tp1_r_multiple,
        tp2_r_multiple=tp2_r_multiple,
        tp3_r_multiple=tp3_r_multiple,
        real_execution_enabled=real_execution_enabled,
        real_fee_rate_ttl_seconds=real_fee_rate_ttl_seconds,
        real_requires_fresh_market_data=False,
        real_requires_positive_edge=False,
    )


def _decision(
    *,
    quantity: float = 1.0,
    account_equity: float = 1_000.0,
    targets: list[TakeProfitTarget] | None = None,
    protective_orders_allowed: bool = True,
    stop_loss_source: str = "signal",
    take_profit_source: str = "trade_plan",
    instrument_type: str = "spot",
    leverage: int = 1,
    futures_risk_plan: FuturesRiskPlan | None = None,
) -> RiskDecision:
    if targets is None:
        targets = [
            TakeProfitTarget(label="TP1", r_multiple=1.0, price=105.0, close_percent=50.0, action="observe"),
            TakeProfitTarget(label="TP2", r_multiple=2.0, price=110.0, close_percent=50.0, action="full_close"),
        ]
    sizing = PositionSizingResult(
        side="long",
        account_equity=account_equity,
        risk_per_trade_percent=1.0,
        risk_amount=5.0 * quantity,
        entry_price=100.0,
        stop_loss_price=95.0,
        stop_distance_per_unit=5.0,
        effective_risk_per_unit=5.0,
        position_size_base=quantity,
        notional=100.0 * quantity,
        leverage=leverage,
        required_margin=100.0 * quantity / leverage,
        fee_rate=0.0,
        slippage_bps=0.0,
    )
    risk_adjustment = RiskAdjustmentPlan(
        instrument_type=instrument_type,
        strategy="trend_pullback_continuation",
        signal_score=80.0,
        account_equity=account_equity,
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
        account_equity=account_equity,
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
        protective_orders_allowed=protective_orders_allowed,
    )
    stop_loss_plan = StopLossPlan(
        side="long",
        mode="structure",
        entry_price=100.0,
        stop_loss_price=95.0,
        risk_per_unit=5.0,
        source=stop_loss_source,
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
        source=take_profit_source,
        selected_rr=targets[-1].r_multiple if targets else None,
    )
    return RiskDecision(
        mode="real",
        stage="pre_execution",
        status="passed",
        can_enter=True,
        exchange="bybit",
        symbol="BTCUSDT",
        instrument_type=instrument_type,
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
        futures_risk_plan=futures_risk_plan,
    )


def _decision_without_stop_loss() -> RiskDecision:
    decision = _decision()
    return decision.model_copy(
        update={
            "stop_loss_plan": decision.stop_loss_plan.model_copy(update={"stop_loss_price": None})
        }
    )


if __name__ == "__main__":
    unittest.main()
