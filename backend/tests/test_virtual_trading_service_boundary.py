import unittest
from datetime import datetime, timezone
from typing import Any, Optional

from app.schemas.signal import (
    NoTradeFilterResult,
    RadarSignal,
    SignalConfirmationSnapshot,
    SignalLayerCheck,
)
from app.schemas.trade import (
    ManualConfirmRequest,
    OrderBookLevel,
    RealTrade,
    TradeJournalEntry,
    VirtualMarketSnapshot,
    VirtualTrade,
)
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
from app.schemas.user import RiskManagementSettings
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.risk_market_data import RiskMarketDataSnapshot
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
from app.services.trade_service import trade_service as compatibility_trade_service
from app.services.virtual_trading import (
    VirtualExecutionEngine,
    VirtualExecutionRejected,
    VirtualTradingService,
    get_virtual_simulation_model_info,
    virtual_trading_service,
)


class VirtualTradingServiceBoundaryTest(unittest.TestCase):
    def test_virtual_trading_package_is_primary_service_entrypoint(self) -> None:
        self.assertIsInstance(virtual_trading_service, VirtualTradingService)
        self.assertIs(compatibility_trade_service, virtual_trading_service)

    def test_virtual_trading_package_exports_execution_dependencies(self) -> None:
        self.assertIsNotNone(VirtualExecutionEngine)
        model_info = get_virtual_simulation_model_info()
        self.assertEqual(model_info.current_tier, "advanced")
        self.assertTrue(any(
            capability.code == "orderbook_depth_simulation"
            for capability in model_info.active_capabilities
        ))

    def test_low_rr_virtual_confirm_and_open_continue_in_soft_mode_with_warning(self) -> None:
        service = _service(
            RiskManagementSettings(
                virtual_rr_guard_mode="soft",
                max_price_deviation_bps=0,
            )
        )
        request = _request()

        confirmed_signal, confirmed_trade = service.confirm_signal(
            _low_rr_signal("sig_low_rr_confirm"),
            request,
        )
        opened_trade = service.open_virtual_trade(
            _low_rr_signal("sig_low_rr_open"),
            request,
        )

        self.assertEqual(confirmed_signal.status, "confirmed")
        self.assertEqual(confirmed_trade.status, "open")
        self.assertEqual(opened_trade.status, "open")
        self.assertIsNotNone(opened_trade.execution)
        assert opened_trade.execution is not None
        warning_text = " ".join([
            *opened_trade.execution.notes,
            *(opened_trade.execution.risk_decision.warnings if opened_trade.execution.risk_decision else []),
        ])
        self.assertIn("Risk/reward warning", warning_text)
        self.assertNotIn("blocked", warning_text.lower())

    def test_risk_gate_block_prevents_virtual_trade_creation(self) -> None:
        repository = _EphemeralTradeRepository()
        service = _service(
            RiskManagementSettings(max_price_deviation_bps=0),
            repository=repository,
            risk_gate_service=_StaticRiskGateService(
                _risk_decision(
                    can_enter=False,
                    status="failed",
                    blockers=["RiskGate blocked this virtual entry."],
                )
            ),
        )

        with self.assertRaises(ValueError) as exc:
            service.open_virtual_trade(_signal("sig_risk_gate_block"), _request())

        self.assertIn("RiskGate blocked this virtual entry.", str(exc.exception))
        self.assertEqual(repository.list_virtual_trades(), [])

    def test_risk_gate_block_trace_includes_signal_and_intent_id(self) -> None:
        repository = _EphemeralTradeRepository()
        audit = _FakeRiskAuditService()
        service = _service(
            RiskManagementSettings(max_price_deviation_bps=0),
            repository=repository,
            risk_gate_service=_TraceRiskGateService(),
            risk_audit=audit,
        )
        signal = _signal("sig_pending_block_trace")
        request = _request().model_copy(
            update={
                "metadata": {
                    "pending_entry_intent_id": "intent-abc",
                    "lifecycle_trace": {
                        "signal_id": signal.id,
                        "pending_entry_intent_id": "intent-abc",
                    },
                }
            }
        )

        with self.assertRaises(ValueError) as exc:
            service.open_virtual_trade(signal, request)

        self.assertIn("RiskGate blocked pending entry.", str(exc.exception))
        self.assertEqual(repository.list_virtual_trades(), [])
        self.assertEqual(len(audit.calls), 1)
        call = audit.calls[0]
        self.assertEqual(call["pending_entry_intent_id"], "intent-abc")
        self.assertEqual(call["decision"].lifecycle_trace.signal_id, signal.id)
        self.assertEqual(call["decision"].lifecycle_trace.pending_entry_intent_id, "intent-abc")
        self.assertEqual(call["input_snapshot"]["lifecycle_trace"]["signal_id"], signal.id)
        self.assertEqual(
            call["input_snapshot"]["lifecycle_trace"]["pending_entry_intent_id"],
            "intent-abc",
        )

    def test_pending_entry_origin_is_preserved_on_virtual_trade_and_journal(self) -> None:
        service = _service(RiskManagementSettings(max_price_deviation_bps=0))
        signal = _signal("sig_pending_origin")
        request = _request().model_copy(
            update={
                "metadata": {
                    "pending_entry_intent_id": "intent-origin-123",
                    "accepted_trade_plan_hash": "sha256:accepted-plan",
                    "trigger_source": "pending_entry",
                    "lifecycle_trace": {
                        "signal_id": signal.id,
                        "pending_entry_intent_id": "intent-origin-123",
                    },
                    "pending_entry_trigger": {
                        "trigger_price": "100.0",
                        "trigger_reason": "entry_zone_touched",
                        "touch_price_source": "ask",
                        "warnings": [],
                    },
                }
            }
        )

        trade = service.open_virtual_trade(signal, request)
        journal = service.list_trade_journal(mode="virtual")

        self.assertEqual(trade.pending_entry_intent_id, "intent-origin-123")
        self.assertEqual(trade.accepted_trade_plan_hash, "sha256:accepted-plan")
        self.assertEqual(trade.trigger_source, "pending_entry")
        self.assertIsNotNone(trade.origin)
        assert trade.origin is not None
        self.assertEqual(trade.origin.signal_id, signal.id)
        self.assertEqual(trade.origin.pending_entry_intent_id, "intent-origin-123")
        self.assertEqual(trade.origin.strategy, signal.strategy)
        self.assertEqual(trade.origin.mode, "virtual")
        self.assertEqual(trade.origin.accepted_trade_plan_hash, "sha256:accepted-plan")
        self.assertTrue(any(
            event.event_type == "created_from_pending_entry"
            and event.pending_entry_intent_id == "intent-origin-123"
            and event.metadata["accepted_trade_plan_hash"] == "sha256:accepted-plan"
            for event in trade.lifecycle_events
        ))
        self.assertEqual(journal[0].pending_entry_intent_id, "intent-origin-123")
        self.assertEqual(journal[0].accepted_trade_plan_hash, "sha256:accepted-plan")
        self.assertEqual(journal[0].trigger_source, "pending_entry")
        self.assertIsNotNone(journal[0].origin)
        assert journal[0].origin is not None
        self.assertEqual(journal[0].origin.pending_entry_intent_id, "intent-origin-123")

    def test_manual_virtual_trade_flow_stays_compatible_without_pending_entry_origin(self) -> None:
        service = _service(RiskManagementSettings(max_price_deviation_bps=0))

        trade = service.open_virtual_trade(_signal("sig_manual_origin"), _request())
        journal = service.list_trade_journal(mode="virtual")

        self.assertIsNone(trade.pending_entry_intent_id)
        self.assertIsNone(trade.accepted_trade_plan_hash)
        self.assertEqual(trade.trigger_source, "manual")
        self.assertIsNotNone(trade.origin)
        assert trade.origin is not None
        self.assertIsNone(trade.origin.pending_entry_intent_id)
        self.assertEqual(trade.origin.trigger_source, "manual")
        self.assertIsNone(journal[0].pending_entry_intent_id)
        self.assertEqual(journal[0].trigger_source, "manual")

    def test_rejected_virtual_execution_prevents_trade_creation(self) -> None:
        repository = _EphemeralTradeRepository()
        service = _service(
            RiskManagementSettings(max_price_deviation_bps=0),
            repository=repository,
        )

        with self.assertRaises(VirtualExecutionRejected) as exc:
            service.open_virtual_trade(
                _signal("sig_virtual_execution_rejected"),
                ManualConfirmRequest(
                    simulation_mode="impact_aware",
                    size_usd=4_000.0,
                    market_snapshot=_snapshot(),
                    max_virtual_slippage_bps=0,
                    min_fill_ratio=0.9,
                ),
            )

        self.assertEqual(exc.exception.report.status, "rejected_virtual_execution")
        self.assertIsNone(exc.exception.report.average_price)
        self.assertEqual(repository.list_virtual_trades(), [])

    def test_execution_quality_block_prevents_virtual_trade_creation(self) -> None:
        repository = _EphemeralTradeRepository()
        service = _service(
            RiskManagementSettings(max_price_deviation_bps=0),
            repository=repository,
        )

        with self.assertRaises(VirtualExecutionRejected) as exc:
            service.open_virtual_trade(
                _signal("sig_quality_gate_block"),
                ManualConfirmRequest(
                    simulation_mode="impact_aware",
                    size_usd=1_000.0,
                    market_snapshot=_thin_snapshot(),
                    max_virtual_slippage_bps=300,
                ),
            )

        self.assertEqual(repository.list_virtual_trades(), [])
        self.assertEqual(exc.exception.report.status, "rejected_virtual_execution")
        self.assertEqual(exc.exception.report.fill_result.status if exc.exception.report.fill_result else None, "blocked")
        self.assertIn(
            exc.exception.report.rejected_reason,
            {"spread_above_entry_limit", "position_above_50_percent_depth_1"},
        )

    def test_no_trade_signal_blocks_virtual_confirm_and_open(self) -> None:
        service = _service(RiskManagementSettings(max_price_deviation_bps=0))
        request = _request()

        with self.assertRaises(StrategyRiskRewardBlocked) as confirm_exc:
            service.confirm_signal(_no_trade_signal("sig_no_trade_confirm"), request)
        with self.assertRaises(StrategyRiskRewardBlocked) as open_exc:
            service.open_virtual_trade(_no_trade_signal("sig_no_trade_open"), request)

        self.assertIn("Spread 84.0 bps", confirm_exc.exception.reason)
        self.assertIn("Spread 84.0 bps", open_exc.exception.reason)

    def test_hard_virtual_rr_guard_rejects_low_rr_before_virtual_execution(self) -> None:
        service = _service(
            RiskManagementSettings(
                virtual_rr_guard_mode="hard",
                max_price_deviation_bps=0,
            )
        )

        with self.assertRaises(StrategyRiskRewardBlocked) as exc:
            service.open_virtual_trade(_low_rr_signal("sig_low_rr_hard"), _request())

        self.assertIn("Execution RR policy rejected", exc.exception.reason)
        self.assertEqual(service.list_virtual_trades(), [])

    def test_off_virtual_rr_guard_keeps_low_rr_metadata_without_warning(self) -> None:
        service = _service(
            RiskManagementSettings(
                virtual_rr_guard_mode="off",
                max_price_deviation_bps=0,
            )
        )

        trade = service.open_virtual_trade(_low_rr_signal("sig_low_rr_off"), _request())

        self.assertIsNotNone(trade.execution)
        assert trade.execution is not None
        self.assertIsNotNone(trade.execution.risk_decision)
        assert trade.execution.risk_decision is not None
        warning_text = " ".join([
            *trade.execution.notes,
            *trade.execution.risk_decision.warnings,
        ])
        self.assertNotIn("Risk/reward warning", warning_text)
        self.assertFalse(trade.execution.risk_decision.risk_check.risk_reward_warning)
        self.assertFalse(trade.execution.risk_decision.risk_check.risk_reward_blocked)
        self.assertEqual(trade.execution.risk_decision.risk_check.risk_reward_guard_mode, "off")

    def test_legacy_failed_rr_guard_metadata_is_soft_warning_for_virtual_execution(self) -> None:
        service = _service(
            RiskManagementSettings(
                virtual_rr_guard_mode="soft",
                max_price_deviation_bps=0,
            )
        )

        trade = service.open_virtual_trade(_legacy_rr_failed_signal(), _request())

        self.assertIsNotNone(trade.execution)
        assert trade.execution is not None
        self.assertIsNotNone(trade.execution.risk_decision)
        assert trade.execution.risk_decision is not None
        warning_text = " ".join([
            *trade.execution.notes,
            *trade.execution.risk_decision.warnings,
        ])
        self.assertIn("Risk/reward warning", warning_text)
        self.assertNotIn("blocked", warning_text.lower())


class _EphemeralTradeRepository:
    def __init__(self) -> None:
        self._virtual_trades: dict[str, VirtualTrade] = {}

    def save_virtual_trade(self, trade: VirtualTrade) -> VirtualTrade:
        self._virtual_trades[trade.id] = trade
        return trade

    def get_virtual_trade(self, trade_id: str) -> Optional[VirtualTrade]:
        return self._virtual_trades.get(trade_id)

    def list_virtual_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[VirtualTrade]:
        trades = list(self._virtual_trades.values())
        if status is not None:
            trades = [trade for trade in trades if trade.status == status]
        if signal_id is not None:
            trades = [trade for trade in trades if trade.signal_id == signal_id]
        return sorted(trades, key=lambda trade: trade.opened_at, reverse=True)

    def save_real_trade(self, trade: RealTrade) -> RealTrade:
        raise NotImplementedError

    def get_real_trade(self, trade_id: str) -> Optional[RealTrade]:
        return None

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[RealTrade]:
        return []

    def list_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        if mode == "real":
            return []
        return [
            TradeJournalEntry.model_validate(trade.model_dump())
            for trade in self.list_virtual_trades(status=status, signal_id=signal_id)
        ]


class _StaticMarketDataService:
    def build_snapshot(self, **kwargs) -> RiskMarketDataSnapshot:
        return RiskMarketDataSnapshot(
            exchange=kwargs["exchange"],
            symbol=kwargs["symbol"],
            category=None,
            entry_price=kwargs.get("manual_entry_price") or kwargs["fallback_entry_price"],
            slippage_bps=kwargs.get("manual_slippage_bps", 0.0),
            market_data_status="fresh",
            market_data_source="test",
        )


class _ZeroFeeRateService:
    def resolve(self, **kwargs) -> RiskFeeRateSnapshot:
        return RiskFeeRateSnapshot(
            fee_rate=0.0,
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            source="test",
        )


class _StaticRiskGateService:
    def __init__(self, decision: RiskDecision) -> None:
        self.decision = decision

    def evaluate(self, **kwargs) -> RiskDecision:
        return self.decision


class _TraceRiskGateService:
    def evaluate(self, **kwargs) -> RiskDecision:
        context = kwargs["context"]
        return _risk_decision(
            can_enter=False,
            status="failed",
            blockers=["RiskGate blocked pending entry."],
        ).model_copy(update={"lifecycle_trace": context.lifecycle_trace})


class _FakeRiskAuditService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record_decision(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "risk-audit-id"


def _service(
    risk_settings: RiskManagementSettings,
    *,
    repository: _EphemeralTradeRepository | None = None,
    risk_gate_service: Any | None = None,
    risk_audit: Any | None = None,
) -> VirtualTradingService:
    return VirtualTradingService(
        repository=repository or _EphemeralTradeRepository(),
        risk_settings_provider=lambda _user_id: risk_settings,
        market_data_service=_StaticMarketDataService(),
        fee_rate_service=_ZeroFeeRateService(),
        risk_gate_service=risk_gate_service,
        risk_audit=risk_audit,
    )


def _request() -> ManualConfirmRequest:
    return ManualConfirmRequest(
        simulation_mode="impact_aware",
        size_usd=100.0,
        market_snapshot=_snapshot(),
        max_virtual_slippage_bps=300,
    )


def _signal(signal_id: str = "sig_virtual_boundary") -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=signal_id,
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        risk_reward=3.0,
        status="entry_touched",
        score=82,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=90.0,
        take_profit_1=120.0,
        take_profit_2=130.0,
        created_at=now,
        updated_at=now,
    )


def _low_rr_signal(signal_id: str = "sig_low_rr") -> RadarSignal:
    return _signal(signal_id).model_copy(
        update={
            "selected_rr": 0.8,
            "selected_rr_target": "nearest",
            "min_rr_ratio": 1.5,
        }
    )


def _legacy_rr_failed_signal() -> RadarSignal:
    return _signal("sig_legacy_rr_failed").model_copy(
        update={
            "confirmation": SignalConfirmationSnapshot(
                passed=False,
                checks=[
                    SignalLayerCheck(
                        name="risk_reward_guard",
                        status="failed",
                        reason="Risk/reward blocked: nearest target is below minimum",
                        metadata={"risk_reward_blocked": True},
                    )
                ],
            )
        }
    )


def _no_trade_signal(signal_id: str) -> RadarSignal:
    return _signal(signal_id).model_copy(
        update={
            "no_trade_filter": NoTradeFilterResult(
                enabled=True,
                blocked=True,
                hard_block=True,
                blockers=["Spread 84.0 bps is above entry limit 25.0 bps"],
            )
        }
    )


def _snapshot() -> VirtualMarketSnapshot:
    return VirtualMarketSnapshot(
        best_bid=99.95,
        best_ask=100.0,
        bids=[
            OrderBookLevel(price=99.95, notional_usd=1_000),
            OrderBookLevel(price=99.8, notional_usd=2_000),
        ],
        asks=[
            OrderBookLevel(price=100.0, notional_usd=1_000),
            OrderBookLevel(price=100.1, notional_usd=2_000),
        ],
        volume_1m_usd=5_000,
        volume_5m_usd=30_000,
        volume_15m_usd=120_000,
        average_trade_size_usd=250,
        volatility_1m_percent=0.4,
    )


def _thin_snapshot() -> VirtualMarketSnapshot:
    return VirtualMarketSnapshot(
        best_bid=99.5,
        best_ask=100.0,
        bids=[
            OrderBookLevel(price=99.5, notional_usd=600),
            OrderBookLevel(price=99.0, notional_usd=1_200),
        ],
        asks=[
            OrderBookLevel(price=100.0, notional_usd=500),
            OrderBookLevel(price=100.4, notional_usd=700),
            OrderBookLevel(price=101.0, notional_usd=600),
        ],
        volume_1m_usd=700,
        volume_5m_usd=7_300,
        volume_15m_usd=12_000,
        average_trade_size_usd=120,
        volatility_1m_percent=1.8,
    )


def _risk_decision(
    *,
    can_enter: bool = True,
    status: str = "passed",
    blockers: list[str] | None = None,
) -> RiskDecision:
    blockers = blockers or []
    sizing = PositionSizingResult(
        side="long",
        account_equity=10_000.0,
        risk_per_trade_percent=1.0,
        risk_amount=10.0,
        entry_price=100.0,
        stop_loss_price=90.0,
        stop_distance_per_unit=10.0,
        effective_risk_per_unit=10.0,
        position_size_base=1.0,
        notional=100.0,
        leverage=1,
        required_margin=100.0,
        fee_rate=0.0,
        slippage_bps=0.0,
    )
    risk_adjustment = RiskAdjustmentPlan(
        instrument_type="spot",
        strategy="trend_pullback_continuation",
        signal_score=82.0,
        account_equity=10_000.0,
        base_risk_percent=1.0,
        base_risk_amount=100.0,
        strategy_risk_multiplier=1.0,
        signal_score_multiplier=1.0,
        adjusted_risk_percent=1.0,
        adjusted_risk_amount=100.0,
        signal_trade_allowed=True,
    )
    risk_check = RiskCheckResult(
        status=status,
        blockers=blockers,
        warnings=[],
        rr=3.0,
        min_rr_ratio=2.0,
        account_equity=10_000.0,
        adjusted_risk_amount=100.0,
        adjusted_risk_percent=1.0,
        effective_risk_amount=10.0,
        position_notional=100.0,
        position_size_base=1.0,
        required_margin=100.0,
        max_daily_loss_percent=50.0,
        max_account_drawdown_percent=90.0,
        max_open_risk_percent=100.0,
        max_correlated_risk_percent=100.0,
        exchange_rule_status="fresh",
        market_data_status="fresh",
    )
    return RiskDecision(
        mode="virtual",
        stage="pre_execution",
        status=status,
        can_enter=can_enter,
        blockers=blockers,
        exchange="bybit",
        symbol="BTCUSDT",
        instrument_type="spot",
        requested_notional=None,
        risk_adjustment_plan=risk_adjustment,
        position_sizing=sizing,
        checked_position_sizing=sizing,
        risk_check=risk_check,
        stop_loss_plan=StopLossPlan(
            side="long",
            mode="structure",
            entry_price=100.0,
            stop_loss_price=90.0,
            risk_per_unit=10.0,
            source="signal",
            default_stop_loss_percent=1.5,
            atr_period=14,
            atr_multiplier=2.0,
        ),
        take_profit_plan=TakeProfitPlan(
            mode="risk_multiple",
            side="long",
            entry_price=100.0,
            stop_loss_price=90.0,
            risk_per_unit=10.0,
            partial_take_profit_enabled=True,
            targets=[
                TakeProfitTarget(
                    label="TP1",
                    r_multiple=1.0,
                    price=110.0,
                    close_percent=50.0,
                    action="observe",
                ),
                TakeProfitTarget(
                    label="TP2",
                    r_multiple=3.0,
                    price=130.0,
                    close_percent=50.0,
                    action="full_close",
                ),
            ],
            selected_rr=3.0,
        ),
        breakeven_plan=BreakevenPlan(
            side="long",
            entry_price=100.0,
            stop_loss_price=90.0,
            risk_per_unit=10.0,
            move_after_r=1.0,
            trigger_price=110.0,
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
