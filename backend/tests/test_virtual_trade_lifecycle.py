import unittest
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import patch

from app.api.v1.trades import close_market_trade
from app.schemas.signal import RadarSignal
from app.schemas.trade import CloseMarketTradeRequest, ManualConfirmRequest, RealTrade, TradeJournalEntry, VirtualTrade
from app.schemas.user import RiskManagementSettings
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.trade_service import TradeService


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


class CapturingFeeRateService:
    def __init__(self) -> None:
        self.instrument_types: list[str] = []

    def resolve(self, *, instrument_type: str, **_kwargs) -> RiskFeeRateSnapshot:
        self.instrument_types.append(instrument_type)
        return RiskFeeRateSnapshot(
            fee_rate=0.0007,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0007,
            source="cached",
        )


class CapturingBroker:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


class RealOnlyTradeRepository(EphemeralTradeRepository):
    def __init__(self, real_trade: RealTrade) -> None:
        super().__init__()
        self._real_trade = real_trade

    def get_real_trade(self, trade_id: str) -> Optional[RealTrade]:
        if trade_id == self._real_trade.id:
            return self._real_trade
        return None

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[RealTrade]:
        if signal_id is not None:
            return []
        if status is not None and status != self._real_trade.status:
            return []
        return [self._real_trade]


class VirtualTradeLifecycleTest(unittest.TestCase):
    def test_long_position_closes_on_take_profit_and_updates_account(self) -> None:
        service = TradeService(repository=EphemeralTradeRepository())
        trade = service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )

        self.assertEqual(trade.risk_amount, 7.5)
        self.assertEqual(trade.take_profit, [110.0, 120.0, 130.0])

        updated = service.update_market_price("bybit", "BTCUSDT", 130.0)

        self.assertEqual(updated[0].status, "closed")
        self.assertEqual(updated[0].close_reason, "take_profit")
        entry_fee_rate = trade.fees / trade.size_usd
        expected_pnl = (130.0 - trade.entry_price) * trade.quantity
        expected_pnl -= trade.fees + trade.quantity * 130.0 * entry_fee_rate
        self.assertAlmostEqual(updated[0].pnl or 0.0, expected_pnl)

        account = service.get_virtual_account()
        self.assertAlmostEqual(account.balance, 100 + expected_pnl)
        self.assertAlmostEqual(account.realized_pnl, expected_pnl)
        self.assertEqual(account.wins, 1)

    def test_long_position_closes_on_stop_loss_and_updates_account(self) -> None:
        service = TradeService(repository=EphemeralTradeRepository())
        service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )

        updated = service.update_market_price("bybit", "BTCUSDT", 90.0)

        self.assertEqual(updated[0].status, "closed")
        self.assertEqual(updated[0].close_reason, "stop_loss")
        self.assertAlmostEqual(updated[0].pnl or 0.0, -7.5)

        account = service.get_virtual_account()
        self.assertAlmostEqual(account.balance, 92.5)
        self.assertAlmostEqual(account.realized_pnl, -7.5)
        self.assertEqual(account.losses, 1)

    def test_virtual_trade_uses_risk_profile_position_sizing(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(
                risk_profile="balanced",
                risk_per_trade_percent=1.0,
                min_rr_ratio=2.0,
                max_daily_loss_percent=3.0,
                max_account_drawdown_percent=10.0,
                max_open_risk_percent=5.0,
                stop_loss_mode="structure",
            ),
        )
        trade = service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(fee_rate=0.001, slippage_bps=10),
        )

        self.assertIsNotNone(trade.execution)
        assert trade.execution is not None
        self.assertIsNotNone(trade.execution.position_sizing)
        assert trade.execution.position_sizing is not None
        self.assertIsNotNone(trade.execution.stop_loss_plan)
        self.assertIsNotNone(trade.execution.take_profit_plan)
        self.assertIsNotNone(trade.execution.breakeven_plan)
        self.assertIsNotNone(trade.execution.trailing_stop_plan)
        self.assertIsNotNone(trade.execution.futures_risk_plan)
        self.assertLess(trade.size_usd, 10.0)
        self.assertAlmostEqual(trade.execution.position_sizing.risk_amount, 0.75)
        self.assertAlmostEqual(
            trade.execution.position_sizing.effective_risk_per_unit,
            10.4802,
        )
        self.assertLess(trade.execution.position_sizing.position_size_base, 0.1)

    def test_virtual_trade_can_use_fixed_percent_stop_from_user_settings(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(
                risk_profile="balanced",
                risk_per_trade_percent=1.0,
                min_rr_ratio=2.0,
                max_daily_loss_percent=3.0,
                max_account_drawdown_percent=10.0,
                max_open_risk_percent=5.0,
                stop_loss_mode="fixed_percent",
                default_stop_loss_percent=1.5,
            ),
        )
        trade = service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )

        self.assertAlmostEqual(trade.stop_loss, 98.5)
        self.assertEqual(trade.take_profit, [101.5, 103.0, 104.5])

    def test_virtual_trade_rejects_leverage_above_user_max(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(
                risk_profile="balanced",
                risk_per_trade_percent=1.0,
                min_rr_ratio=2.0,
                max_daily_loss_percent=3.0,
                max_account_drawdown_percent=10.0,
                max_open_risk_percent=5.0,
                stop_loss_mode="structure",
                max_leverage=3,
            ),
        )

        with self.assertRaises(ValueError):
            service.open_virtual_trade(
                self._signal(direction="long", stop_loss=90.0),
                ManualConfirmRequest(leverage=5),
            )

    def test_virtual_trade_rejects_liquidation_before_stop(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(
                risk_profile="balanced",
                risk_per_trade_percent=1.0,
                min_rr_ratio=2.0,
                max_daily_loss_percent=3.0,
                max_account_drawdown_percent=10.0,
                max_open_risk_percent=5.0,
                stop_loss_mode="structure",
                max_leverage=3,
            ),
        )

        with self.assertRaises(ValueError):
            service.open_virtual_trade(
                self._signal(direction="long", stop_loss=90.0),
                ManualConfirmRequest(leverage=3, liquidation_price=95.0),
            )

    def test_virtual_fee_cache_uses_spot_or_futures_from_leverage(self) -> None:
        spot_fee_service = CapturingFeeRateService()
        TradeService(
            repository=EphemeralTradeRepository(),
            fee_rate_service=spot_fee_service,
        ).open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(leverage=1),
        )

        futures_fee_service = CapturingFeeRateService()
        TradeService(
            repository=EphemeralTradeRepository(),
            fee_rate_service=futures_fee_service,
        ).open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(leverage=3, liquidation_price=80.0),
        )

        self.assertEqual(spot_fee_service.instrument_types, ["spot"])
        self.assertEqual(futures_fee_service.instrument_types, ["futures"])

    @staticmethod
    def _signal(direction: str, stop_loss: float) -> RadarSignal:
        now = datetime.now(timezone.utc)
        return RadarSignal(
            id=f"sig_{direction}",
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction=direction,
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
            created_at=now,
            updated_at=now,
        )


class TradeApiMarketCloseTest(unittest.IsolatedAsyncioTestCase):
    async def test_market_close_endpoint_closes_virtual_trade_at_current_price(self) -> None:
        service = TradeService(repository=EphemeralTradeRepository())
        trade = service.open_virtual_trade(
            VirtualTradeLifecycleTest._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(fee_rate=0.001),
        )
        service.update_market_price("bybit", "BTCUSDT", 105.0)
        broker = CapturingBroker()

        with (
            patch("app.api.v1.trades.virtual_trading_service", service),
            patch("app.api.v1.trades.realtime_event_broker", broker),
        ):
            result = await close_market_trade(trade.id, CloseMarketTradeRequest())

        self.assertEqual(result.mode, "virtual")
        self.assertEqual(result.status, "closed")
        self.assertIsNotNone(result.trade)
        assert result.trade is not None
        self.assertEqual(result.trade.close_reason, "manual_close")
        self.assertGreater(result.trade.fees, trade.fees)
        self.assertEqual([event["type"] for event in broker.events], ["trade.closed"])

    async def test_market_close_endpoint_keeps_real_trade_as_not_implemented_stub(self) -> None:
        real_trade = RealTrade(
            id="real_1",
            user_id="demo_user",
            signal_id=None,
            exchange="bybit",
            symbol="BTCUSDT",
            strategy="external_import",
            timeframe="trade",
            side="long",
            entry_price=100.0,
            current_price=101.0,
            exit_price=None,
            size_usd=100.0,
            quantity=1.0,
            leverage=1,
            risk_percent=0.0,
            stop_loss=0.0,
            status="open",
            opened_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        service = TradeService(repository=RealOnlyTradeRepository(real_trade))
        broker = CapturingBroker()

        with (
            patch("app.api.v1.trades.virtual_trading_service", service),
            patch("app.api.v1.trades.realtime_event_broker", broker),
        ):
            result = await close_market_trade(real_trade.id, CloseMarketTradeRequest())

        self.assertEqual(result.mode, "real")
        self.assertEqual(result.status, "not_implemented")
        self.assertIsNotNone(result.trade)
        assert result.trade is not None
        self.assertEqual(result.trade.id, real_trade.id)
        self.assertEqual(result.trade.mode, "real")
        self.assertEqual(broker.events, [])


if __name__ == "__main__":
    unittest.main()
