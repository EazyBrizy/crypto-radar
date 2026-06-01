import unittest
from datetime import datetime, timezone
from typing import Optional

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
from app.schemas.user import RiskManagementSettings
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.risk_market_data import RiskMarketDataSnapshot
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
from app.services.trade_service import trade_service as compatibility_trade_service
from app.services.virtual_trading import (
    VirtualExecutionEngine,
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


def _service(risk_settings: RiskManagementSettings) -> VirtualTradingService:
    return VirtualTradingService(
        repository=_EphemeralTradeRepository(),
        risk_settings_provider=lambda _user_id: risk_settings,
        market_data_service=_StaticMarketDataService(),
        fee_rate_service=_ZeroFeeRateService(),
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


if __name__ == "__main__":
    unittest.main()
