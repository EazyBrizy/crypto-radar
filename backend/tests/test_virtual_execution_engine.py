import unittest
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.schemas.signal import RadarSignal
from app.schemas.trade_plan import TradePlan, TradePlanEntry, TradePlanTarget
from app.schemas.trade import (
    CloseVirtualTradeRequest,
    ManualConfirmRequest,
    OrderBookLevel,
    RealTrade,
    TradeJournalEntry,
    VirtualMarketSnapshot,
    VirtualTrade,
)
from app.schemas.user import RiskManagementSettings
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.risk_market_data import RiskMarketDataSnapshot
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
from app.services.trade_service import TradeService
from app.services.virtual_execution_engine import VirtualExecutionEngine


class EphemeralTradeRepository:
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

    def delete_virtual_trade(self, trade_id: str) -> None:
        self._virtual_trades.pop(trade_id, None)

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


class CapturingMarketDataService:
    def __init__(self) -> None:
        self.manual_entry_price: float | None = None

    def build_snapshot(self, **kwargs) -> RiskMarketDataSnapshot:
        self.manual_entry_price = kwargs.get("manual_entry_price")
        return RiskMarketDataSnapshot(
            exchange=kwargs["exchange"],
            symbol=kwargs["symbol"],
            category=None,
            entry_price=self.manual_entry_price or kwargs["fallback_entry_price"],
            slippage_bps=kwargs.get("manual_slippage_bps", 0.0),
            market_data_status="fresh",
            market_data_source="test",
        )


class ZeroFeeRateService:
    def resolve(self, **kwargs) -> RiskFeeRateSnapshot:
        return RiskFeeRateSnapshot(
            fee_rate=0.0,
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            source="test",
        )


class VirtualExecutionEngineTest(unittest.TestCase):
    def test_impact_aware_entry_walks_orderbook_and_calculates_slippage(self) -> None:
        report = VirtualExecutionEngine().simulate_entry(
            signal=_signal(),
            request=ManualConfirmRequest(
                simulation_mode="impact_aware",
                market_snapshot=_snapshot(),
                max_virtual_slippage_bps=200,
            ),
            reference_price=100.0,
            requested_size_usd=1_000.0,
        )

        self.assertEqual(report.mode, "impact_aware")
        self.assertEqual(report.status, "filled")
        self.assertGreater(report.average_price or 0, 100.0)
        self.assertGreater(report.entry_slippage_bps, 0)
        self.assertGreater(report.market_impact_percent, 0)
        self.assertGreater(report.liquidity.spread_percent, 0)
        self.assertIsNotNone(report.simulated_path)
        assert report.simulated_path is not None
        self.assertEqual(report.simulation_tier, "advanced")
        self.assertIn("orderbook_depth_simulation", report.active_capabilities)
        self.assertIn("impact_decay", report.active_capabilities)
        self.assertIn("monte_carlo_execution_simulation", report.planned_capabilities)
        self.assertGreater(report.simulated_path.post_trade_price, report.average_price or 0)
        self.assertGreater(report.simulated_path.points[0].effective_price, report.simulated_path.points[-1].effective_price)
        self.assertGreater(report.simulated_path.points[-1].effective_price, report.reference_price)

    def test_impact_aware_entry_can_partially_fill_available_liquidity(self) -> None:
        report = VirtualExecutionEngine().simulate_entry(
            signal=_signal(),
            request=ManualConfirmRequest(
                simulation_mode="impact_aware",
                market_snapshot=_partial_snapshot(),
                max_virtual_slippage_bps=30,
                min_fill_ratio=0.25,
            ),
            reference_price=100.0,
            requested_size_usd=1_000.0,
        )

        self.assertEqual(report.status, "partially_filled")
        self.assertAlmostEqual(report.filled_size_usd, 500.0)
        self.assertAlmostEqual(report.unfilled_size_usd, 500.0)
        self.assertEqual(report.quality_gate.status, "warning")
        self.assertEqual(report.liquidity.impact_risk, "medium")

    def test_impact_aware_entry_rejects_below_minimum_fill_ratio(self) -> None:
        report = VirtualExecutionEngine().simulate_entry(
            signal=_signal(),
            request=ManualConfirmRequest(
                simulation_mode="impact_aware",
                market_snapshot=_partial_snapshot(),
                max_virtual_slippage_bps=30,
                min_fill_ratio=0.75,
            ),
            reference_price=100.0,
            requested_size_usd=1_000.0,
        )

        self.assertEqual(report.status, "rejected_virtual_execution")
        self.assertEqual(report.rejected_reason, "insufficient_liquidity")
        self.assertEqual(report.quality_gate.status, "blocked")

    def test_quality_gate_flags_trade_and_suggests_realistic_max_size(self) -> None:
        report = VirtualExecutionEngine().simulate_entry(
            signal=_signal(),
            request=ManualConfirmRequest(
                simulation_mode="impact_aware",
                market_snapshot=_example_rejected_snapshot(),
                max_virtual_slippage_bps=500,
            ),
            reference_price=0.012,
            requested_size_usd=2_000.0,
        )

        self.assertEqual(report.status, "filled")
        self.assertIsNone(report.rejected_reason)
        self.assertEqual(report.quality_gate.status, "blocked")
        self.assertIn("position_above_50_percent_depth_1", report.quality_gate.blockers)
        self.assertIn("position_above_30_percent_volume_5m", report.quality_gate.blockers)
        self.assertIn("expected_slippage_above_1_5_percent", report.quality_gate.blockers)
        self.assertGreater(report.entry_slippage_bps, 150)
        self.assertAlmostEqual(report.quality_gate.suggested_max_size_usd or 0, 450.0)
        self.assertIn("$2,000.00", report.quality_gate.message or "")
        self.assertIn("$450.00", report.quality_gate.message or "")

    def test_trade_service_opens_trade_when_quality_gate_flags_simulation(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=_loose_virtual_risk_settings,
        )

        trade = service.open_virtual_trade(
            _signal(),
            ManualConfirmRequest(
                simulation_mode="impact_aware",
                size_usd=1_000.0,
                leverage=10,
                market_snapshot=_thin_snapshot(),
                max_virtual_slippage_bps=300,
            ),
        )

        self.assertEqual(trade.status, "open")
        self.assertEqual(trade.execution_status, "filled")
        self.assertIsNotNone(trade.execution)
        assert trade.execution is not None
        self.assertEqual(trade.execution.quality_gate.status, "blocked")
        self.assertIn("position_above_50_percent_depth_1", trade.execution.quality_gate.blockers)
        self.assertIn(
            "Execution Quality Gate flagged severe simulated execution risk.",
            trade.execution.notes,
        )

    def test_trade_service_persists_partial_execution_snapshot(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(
                risk_profile="balanced",
                risk_per_trade_percent=10.0,
                min_rr_ratio=2.0,
                max_daily_loss_percent=50.0,
                max_account_drawdown_percent=90.0,
                max_open_risk_percent=100.0,
                stop_loss_mode="fixed_percent",
                default_stop_loss_percent=0.2,
                max_leverage=10,
                futures_max_leverage=10,
            ),
        )
        trade = service.open_virtual_trade(
            _signal(),
            ManualConfirmRequest(
                simulation_mode="impact_aware",
                size_usd=1_000.0,
                leverage=10,
                market_snapshot=_partial_snapshot(),
                max_virtual_slippage_bps=30,
            ),
        )

        self.assertEqual(trade.execution_status, "partially_filled")
        self.assertEqual(trade.simulation_mode, "impact_aware")
        self.assertAlmostEqual(trade.filled_size_usd or 0.0, 500.0)
        self.assertAlmostEqual(trade.unfilled_size_usd, 500.0)
        self.assertIsNotNone(trade.execution)
        assert trade.execution is not None
        self.assertIsNotNone(trade.execution.simulated_path)

    def test_trade_service_marks_private_impact_price_without_mutating_market_price(self) -> None:
        repository = EphemeralTradeRepository()
        service = TradeService(
            repository=repository,
            risk_settings_provider=_loose_virtual_risk_settings,
        )
        trade = service.open_virtual_trade(
            _signal(),
            ManualConfirmRequest(
                simulation_mode="impact_aware",
                size_usd=300.0,
                leverage=3,
                market_snapshot=_snapshot(),
                max_virtual_slippage_bps=300,
            ),
        )
        assert trade.execution is not None
        assert trade.execution.simulated_path is not None
        old_trade = trade.model_copy(
            update={"opened_at": datetime.now(timezone.utc) - timedelta(seconds=60)}
        )
        repository.save_virtual_trade(old_trade)

        updated = service.update_market_price("bybit", "LOWCAPUSDT", 100.0)[0]

        self.assertGreater(updated.current_price, 100.0)
        self.assertLess(
            updated.current_price - 100.0,
            trade.execution.simulated_path.initial_impact_delta,
        )

    def test_trade_service_previews_execution_without_persisting_trade(self) -> None:
        repository = EphemeralTradeRepository()
        service = TradeService(repository=repository)

        report = service.preview_virtual_execution(
            _signal(),
            ManualConfirmRequest(
                simulation_mode="impact_aware",
                size_usd=1_000.0,
                market_snapshot=_partial_snapshot(),
                max_virtual_slippage_bps=30,
            ),
        )

        self.assertEqual(report.status, "partially_filled")
        self.assertEqual(repository.list_virtual_trades(), [])

    def test_trade_service_uses_request_snapshot_as_preview_reference_price(self) -> None:
        market_data = CapturingMarketDataService()
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=_loose_virtual_risk_settings,
            market_data_service=market_data,
            fee_rate_service=ZeroFeeRateService(),
        )

        report = service.preview_virtual_execution(
            _signal(),
            ManualConfirmRequest(
                simulation_mode="impact_aware",
                size_usd=100.0,
                market_snapshot=_snapshot(),
                max_virtual_slippage_bps=300,
            ),
        )

        self.assertAlmostEqual(market_data.manual_entry_price or 0.0, 99.975)
        self.assertAlmostEqual(report.reference_price, 99.975)
        self.assertIsNotNone(report.simulated_path)

    def test_trade_service_open_virtual_trade_allows_low_rr_signal_in_soft_virtual_mode(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(max_price_deviation_bps=0),
            market_data_service=CapturingMarketDataService(),
            fee_rate_service=ZeroFeeRateService(),
        )

        trade = service.open_virtual_trade(
            _low_selected_rr_signal(),
            ManualConfirmRequest(
                simulation_mode="impact_aware",
                size_usd=100.0,
                market_snapshot=_snapshot(),
                max_virtual_slippage_bps=300,
            ),
        )

        self.assertEqual(trade.status, "open")

    def test_trade_service_open_virtual_trade_blocks_low_rr_signal_when_virtual_guard_is_hard(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(
                virtual_rr_guard_mode="hard",
                max_price_deviation_bps=0,
            ),
            market_data_service=CapturingMarketDataService(),
            fee_rate_service=ZeroFeeRateService(),
        )

        with self.assertRaises(StrategyRiskRewardBlocked):
            service.open_virtual_trade(
                _low_selected_rr_signal(),
                ManualConfirmRequest(
                    simulation_mode="impact_aware",
                    size_usd=100.0,
                    market_snapshot=_snapshot(),
                ),
            )

    def test_stop_loss_exit_uses_impact_aware_exit_slippage(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=_loose_virtual_risk_settings,
        )
        trade = service.open_virtual_trade(
            _signal(stop_loss=95.0),
            ManualConfirmRequest(
                simulation_mode="impact_aware",
                size_usd=300.0,
                leverage=3,
                market_snapshot=_snapshot(),
                max_virtual_slippage_bps=300,
            ),
        )

        closed = service.close_virtual_trade(
            trade.id,
            CloseVirtualTradeRequest(exit_price=95.0, reason="stop_loss"),
        )

        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertLess(closed.exit_price or 95.0, 95.0)
        self.assertEqual(closed.close_reason, "stop_loss")

    def test_trade_service_persists_trade_plan_tp3_target(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=_loose_virtual_risk_settings,
        )

        trade = service.open_virtual_trade(
            _signal(
                trade_plan=TradePlan(
                    entry=TradePlanEntry(price=100.0, min_price=100.0, max_price=100.0),
                    stop_loss=90.0,
                    targets=[
                        TradePlanTarget(label="TP1", price=112.0, close_percent=40),
                        TradePlanTarget(label="TP2", price=125.0, close_percent=30),
                        TradePlanTarget(
                            label="TP3",
                            price=145.0,
                            action="measured_move_runner",
                            close_percent="runner",
                            source="range_measured_move",
                        ),
                    ],
                )
            ),
            ManualConfirmRequest(
                simulation_mode="impact_aware",
                size_usd=300.0,
                leverage=3,
                market_snapshot=_snapshot(),
                max_virtual_slippage_bps=300,
            ),
        )

        self.assertEqual(trade.take_profit[-1], 145.0)
        self.assertIsNotNone(trade.execution)
        assert trade.execution is not None
        self.assertIsNotNone(trade.execution.take_profit_plan)
        assert trade.execution.take_profit_plan is not None
        self.assertEqual(trade.execution.take_profit_plan.source, "trade_plan")
        self.assertEqual(trade.execution.take_profit_plan.targets[-1].price, 145.0)


def _signal(
    stop_loss: float = 90.0,
    trade_plan: TradePlan | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_execution",
        symbol="LOWCAPUSDT",
        exchange="bybit",
        strategy="liquidity_sweep_reversal",
        direction="long",
        confidence=0.8,
        risk_reward=3.0,
        urgency="medium",
        score=78,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=stop_loss,
        take_profit_1=120.0,
        take_profit_2=130.0,
        explanation=[],
        risks=[],
        trade_plan=trade_plan,
        created_at=now,
        updated_at=now,
    )


def _low_selected_rr_signal() -> RadarSignal:
    return _signal().model_copy(
        update={
            "selected_rr": 0.8,
            "selected_rr_target": "nearest",
            "min_rr_ratio": 1.5,
        }
    )


def _loose_virtual_risk_settings(_user_id: str) -> RiskManagementSettings:
    return RiskManagementSettings(
        risk_profile="balanced",
        risk_per_trade_percent=10.0,
        min_rr_ratio=2.0,
        max_daily_loss_percent=50.0,
        max_account_drawdown_percent=90.0,
        max_open_risk_percent=100.0,
        stop_loss_mode="fixed_percent",
        default_stop_loss_percent=0.2,
        max_leverage=10,
        futures_max_leverage=10,
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
            OrderBookLevel(price=100.0, notional_usd=200),
            OrderBookLevel(price=100.1, notional_usd=300),
            OrderBookLevel(price=100.3, notional_usd=500),
            OrderBookLevel(price=100.8, notional_usd=1_000),
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


def _partial_snapshot() -> VirtualMarketSnapshot:
    return VirtualMarketSnapshot(
        best_bid=99.95,
        best_ask=100.0,
        bids=[
            OrderBookLevel(price=99.95, notional_usd=1_500),
            OrderBookLevel(price=99.6, notional_usd=1_500),
        ],
        asks=[
            OrderBookLevel(price=100.0, notional_usd=200),
            OrderBookLevel(price=100.2, notional_usd=300),
            OrderBookLevel(price=100.6, notional_usd=1_000),
            OrderBookLevel(price=100.9, notional_usd=1_000),
        ],
        volume_1m_usd=2_500,
        volume_5m_usd=12_000,
        volume_15m_usd=30_000,
        average_trade_size_usd=180,
        volatility_1m_percent=0.7,
    )


def _example_rejected_snapshot() -> VirtualMarketSnapshot:
    return VirtualMarketSnapshot(
        best_bid=0.011952,
        best_ask=0.012048,
        bids=[
            OrderBookLevel(price=0.011952, notional_usd=600),
            OrderBookLevel(price=0.01188, notional_usd=800),
        ],
        asks=[
            OrderBookLevel(price=0.012048, notional_usd=600),
            OrderBookLevel(price=0.01212, notional_usd=800),
            OrderBookLevel(price=0.01256, notional_usd=1_000),
        ],
        volume_1m_usd=1_200,
        volume_5m_usd=5_000,
        volume_15m_usd=14_000,
        average_trade_size_usd=100,
        volatility_1m_percent=1.2,
    )


if __name__ == "__main__":
    unittest.main()
