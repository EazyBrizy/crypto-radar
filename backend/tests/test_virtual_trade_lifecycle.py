import unittest
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import patch

from app.api.v1.trades import close_market_trade
from app.schemas.risk import RiskOverride
from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    CloseMarketTradeRequest,
    ManualConfirmRequest,
    RealTrade,
    TradeJournalEntry,
    VirtualTrade,
    VirtualTradeLifecycleEvent,
    VirtualTradeTargetState,
)
from app.schemas.user import RiskManagementSettings
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.risk_market_data import RiskMarketDataSnapshot
from app.services.trade_service import TradeService
from app.services.virtual_trade_lifecycle import (
    apply_virtual_trade_candle,
    apply_virtual_trade_market_price,
)


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


class StableMarketDataService:
    def build_snapshot(
        self,
        *,
        exchange: str,
        symbol: str,
        fallback_entry_price: float,
        manual_slippage_bps: float = 0.0,
        **_kwargs,
    ) -> RiskMarketDataSnapshot:
        return RiskMarketDataSnapshot(
            exchange=exchange,
            symbol=symbol,
            category=None,
            entry_price=fallback_entry_price,
            slippage_bps=manual_slippage_bps,
            market_data_status="missing",
            market_data_source="test",
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
    def test_final_take_profit_closes_remaining_position_and_updates_account(self) -> None:
        service = self._service()
        trade = service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )

        self.assertEqual(trade.risk_amount, 7.5)
        self.assertEqual(trade.take_profit, [110.0, 120.0, 130.0])

        updated = service.update_market_price("bybit", "BTCUSDT", 130.0)

        self.assertEqual(updated[0].status, "closed")
        self.assertEqual(updated[0].close_reason, "take_profit")
        expected_pnl = sum(
            event.realized_pnl or 0.0
            for event in updated[0].lifecycle_events
            if event.reason in {"partial_take_profit", "take_profit"}
        )
        self.assertAlmostEqual(updated[0].pnl or 0.0, expected_pnl)
        self.assertAlmostEqual(updated[0].remaining_quantity or 0.0, 0.0)
        self.assertAlmostEqual(updated[0].closed_quantity, trade.initial_quantity or trade.quantity)
        self.assertTrue(all(target.hit for target in updated[0].target_states))

        account = service.get_virtual_account()
        self.assertAlmostEqual(account.balance, 100 + expected_pnl)
        self.assertAlmostEqual(account.realized_pnl, expected_pnl)
        self.assertEqual(account.wins, 1)

    def test_tp1_partially_closes_position(self) -> None:
        service = self._service()
        trade = service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )

        updated = service.update_market_price("bybit", "BTCUSDT", 110.0)[0]

        self.assertEqual(updated.status, "open")
        self.assertEqual(updated.close_reason, "partial_take_profit")
        expected_closed_quantity = (trade.initial_quantity or trade.quantity) * 0.30
        self.assertAlmostEqual(updated.closed_quantity, expected_closed_quantity)
        self.assertAlmostEqual(
            updated.remaining_quantity or 0.0,
            (trade.initial_quantity or trade.quantity) - expected_closed_quantity,
        )
        self.assertTrue(updated.target_states[0].hit)
        self.assertFalse(updated.target_states[1].hit)
        account = service.get_virtual_account()
        self.assertAlmostEqual(account.realized_pnl, updated.realized_pnl)
        self.assertAlmostEqual(account.equity, 100 + updated.realized_pnl + updated.unrealized_pnl)

    def test_tp1_moves_stop_to_breakeven_when_target_action_says_so(self) -> None:
        service = self._service()
        trade = service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )
        assert trade.execution is not None
        assert trade.execution.breakeven_plan is not None

        updated = service.update_market_price("bybit", "BTCUSDT", 110.0)[0]

        self.assertTrue(updated.stop_moved_to_breakeven)
        self.assertAlmostEqual(
            updated.current_stop_loss or 0.0,
            trade.execution.breakeven_plan.breakeven_stop_price,
        )
        self.assertEqual(
            updated.lifecycle_events[-1].event_type,
            "stop_moved_to_breakeven",
        )

    def test_breakeven_stop_closes_remaining_position(self) -> None:
        service = self._service()
        service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )
        after_tp1 = service.update_market_price("bybit", "BTCUSDT", 110.0)[0]

        updated = service.update_market_price(
            "bybit",
            "BTCUSDT",
            after_tp1.current_stop_loss or after_tp1.entry_price,
        )[0]

        self.assertEqual(updated.status, "closed")
        self.assertEqual(updated.close_reason, "breakeven_stop")
        self.assertAlmostEqual(updated.remaining_quantity or 0.0, 0.0)
        self.assertGreater(updated.realized_pnl, 0.0)

    def test_partial_fees_are_accounted(self) -> None:
        service = self._service()
        trade = service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(fee_rate=0.001),
        )
        target = trade.target_states[0]
        initial_quantity = trade.initial_quantity or trade.quantity
        initial_size = trade.initial_size_usd or trade.size_usd
        close_quantity = initial_quantity * target.close_percent / 100
        entry_fee_rate = trade.fees / initial_size

        updated = service.update_market_price("bybit", "BTCUSDT", target.price)[0]

        expected_exit_fee = close_quantity * target.price * entry_fee_rate
        expected_entry_fee = trade.fees * target.close_percent / 100
        expected_realized = (target.price - trade.entry_price) * close_quantity
        expected_realized -= expected_entry_fee + expected_exit_fee
        self.assertAlmostEqual(updated.exit_fees, expected_exit_fee)
        self.assertAlmostEqual(updated.fees, trade.fees + expected_exit_fee)
        self.assertAlmostEqual(updated.realized_pnl, expected_realized)

    def test_long_position_closes_on_stop_loss_and_updates_account(self) -> None:
        service = self._service()
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

    def test_legacy_virtual_trade_without_target_states_still_works(self) -> None:
        repository = EphemeralTradeRepository()
        now = datetime.now(timezone.utc)
        repository.save_virtual_trade(
            VirtualTrade(
                id="legacy_trade",
                user_id="demo_user",
                signal_id="legacy_signal",
                exchange="bybit",
                symbol="BTCUSDT",
                strategy="legacy",
                timeframe="15m",
                side="long",
                entry_price=100.0,
                current_price=100.0,
                size_usd=100.0,
                quantity=1.0,
                leverage=1,
                risk_percent=1.0,
                risk_amount=10.0,
                stop_loss=90.0,
                take_profit=[110.0, 120.0],
                status="open",
                opened_at=now,
                updated_at=now,
            )
        )
        service = self._service(repository=repository)

        updated = service.update_market_price("bybit", "BTCUSDT", 120.0)[0]

        self.assertEqual(updated.status, "closed")
        self.assertEqual(updated.close_reason, "take_profit")
        self.assertEqual(updated.take_profit, [110.0, 120.0])
        self.assertEqual(updated.target_states[0].label, "TP2")
        self.assertAlmostEqual(updated.pnl or 0.0, 20.0)

    def test_time_stop_hook_closes_when_armed(self) -> None:
        repository = EphemeralTradeRepository()
        now = datetime.now(timezone.utc)
        repository.save_virtual_trade(
            VirtualTrade(
                id="time_stop_trade",
                user_id="demo_user",
                signal_id="time_stop_signal",
                exchange="bybit",
                symbol="BTCUSDT",
                strategy="legacy",
                timeframe="15m",
                side="long",
                entry_price=100.0,
                current_price=100.0,
                size_usd=100.0,
                quantity=1.0,
                leverage=1,
                risk_percent=1.0,
                risk_amount=10.0,
                stop_loss=90.0,
                take_profit=[120.0],
                status="open",
                opened_at=now,
                updated_at=now,
                lifecycle_events=[
                    VirtualTradeLifecycleEvent(
                        event_type="time_stop_armed",
                        created_at=now,
                        metadata={"max_holding_seconds": 0},
                    )
                ],
            )
        )
        service = self._service(repository=repository)

        updated = service.update_market_price("bybit", "BTCUSDT", 101.0)[0]

        self.assertEqual(updated.status, "closed")
        self.assertEqual(updated.close_reason, "time_stop")
        self.assertAlmostEqual(updated.exit_price or 0.0, 101.0)

    def test_virtual_trade_uses_risk_profile_position_sizing(self) -> None:
        service = self._service(
            risk_settings_provider=lambda _user_id: RiskManagementSettings(
                risk_profile="balanced",
                risk_per_trade_percent=1.0,
                min_rr_ratio=2.0,
                max_daily_loss_percent=3.0,
                max_account_drawdown_percent=10.0,
                max_open_risk_percent=5.0,
                stop_loss_mode="structure",
                virtual_starting_balance=100.0,
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
        self.assertIsNone(trade.execution.futures_risk_plan)
        self.assertLess(trade.size_usd, 10.0)
        self.assertAlmostEqual(trade.execution.position_sizing.risk_amount, 0.75)
        self.assertAlmostEqual(
            trade.execution.position_sizing.effective_risk_per_unit,
            10.4802,
        )
        self.assertLess(trade.execution.position_sizing.position_size_base, 0.1)

    def test_virtual_trade_can_use_fixed_percent_stop_from_user_settings(self) -> None:
        service = self._service(
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
        service = self._service(
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
                ManualConfirmRequest(
                    risk_override=RiskOverride(
                        risk_mode="percent",
                        risk_percent=1.0,
                        leverage=5,
                    )
                ),
            )

    def test_virtual_trade_rejects_liquidation_before_stop(self) -> None:
        service = self._service(
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
        self._service(
            fee_rate_service=spot_fee_service,
        ).open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(leverage=1),
        )

        futures_fee_service = CapturingFeeRateService()
        self._service(
            fee_rate_service=futures_fee_service,
        ).open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(leverage=3, liquidation_price=80.0),
        )

        self.assertEqual(spot_fee_service.instrument_types, ["spot"])
        self.assertEqual(futures_fee_service.instrument_types, ["futures"])

    def test_long_trailing_stop_moves_only_upward(self) -> None:
        now = datetime.now(timezone.utc)
        trade = self._lifecycle_trade(
            side="long",
            stop_loss=90.0,
            current_stop_loss=95.0,
            trailing_active=True,
            trailing_distance=5.0,
            highest_price_after_trailing=100.0,
            now=now,
        )

        moved = apply_virtual_trade_market_price(trade, 110.0, now).trade
        unchanged = apply_virtual_trade_market_price(moved, 108.0, now).trade

        self.assertAlmostEqual(moved.current_stop_loss or 0.0, 105.0)
        self.assertAlmostEqual(moved.highest_price_after_trailing or 0.0, 110.0)
        self.assertEqual(moved.lifecycle_events[-1].event_type, "trailing_stop_updated")
        self.assertEqual(moved.lifecycle_events[-1].metadata["old_stop"], 95.0)
        self.assertEqual(moved.lifecycle_events[-1].metadata["new_stop"], 105.0)
        self.assertEqual(moved.lifecycle_events[-1].metadata["reference_price"], 110.0)
        self.assertAlmostEqual(unchanged.current_stop_loss or 0.0, 105.0)
        self.assertEqual(len(unchanged.lifecycle_events), len(moved.lifecycle_events))

    def test_short_trailing_stop_moves_only_downward(self) -> None:
        now = datetime.now(timezone.utc)
        trade = self._lifecycle_trade(
            side="short",
            stop_loss=110.0,
            current_stop_loss=105.0,
            trailing_active=True,
            trailing_distance=5.0,
            lowest_price_after_trailing=100.0,
            now=now,
        )

        moved = apply_virtual_trade_market_price(trade, 90.0, now).trade
        unchanged = apply_virtual_trade_market_price(moved, 94.0, now).trade

        self.assertAlmostEqual(moved.current_stop_loss or 0.0, 95.0)
        self.assertAlmostEqual(moved.lowest_price_after_trailing or 0.0, 90.0)
        self.assertEqual(moved.lifecycle_events[-1].event_type, "trailing_stop_updated")
        self.assertEqual(moved.lifecycle_events[-1].metadata["old_stop"], 105.0)
        self.assertEqual(moved.lifecycle_events[-1].metadata["new_stop"], 95.0)
        self.assertEqual(moved.lifecycle_events[-1].metadata["reference_price"], 90.0)
        self.assertAlmostEqual(unchanged.current_stop_loss or 0.0, 95.0)
        self.assertEqual(len(unchanged.lifecycle_events), len(moved.lifecycle_events))

    def test_updated_trailing_stop_closes_with_actual_close_price_pnl(self) -> None:
        now = datetime.now(timezone.utc)
        trade = self._lifecycle_trade(
            side="long",
            stop_loss=90.0,
            current_stop_loss=105.0,
            trailing_active=True,
            trailing_distance=5.0,
            highest_price_after_trailing=110.0,
            now=now,
        )

        result = apply_virtual_trade_market_price(trade, 104.0, now)

        self.assertTrue(result.closed)
        self.assertEqual(result.trade.status, "closed")
        self.assertEqual(result.trade.close_reason, "trailing_stop")
        self.assertAlmostEqual(result.trade.exit_price or 0.0, 104.0)
        self.assertAlmostEqual(result.trade.pnl or 0.0, 4.0)

    def test_partial_take_profit_then_trailing_keeps_remaining_quantity(self) -> None:
        now = datetime.now(timezone.utc)
        trade = self._lifecycle_trade(
            side="long",
            quantity=2.0,
            size_usd=200.0,
            stop_loss=90.0,
            current_stop_loss=90.0,
            trailing_distance=5.0,
            now=now,
            target_states=[
                VirtualTradeTargetState(
                    label="TP1",
                    price=110.0,
                    close_percent=50.0,
                    action="trailing_stop",
                )
            ],
        )

        after_target = apply_virtual_trade_market_price(trade, 110.0, now).trade
        after_trailing_update = apply_virtual_trade_market_price(after_target, 112.0, now).trade

        self.assertTrue(after_target.trailing_active)
        self.assertAlmostEqual(after_target.remaining_quantity or 0.0, 1.0)
        self.assertAlmostEqual(after_target.closed_quantity, 1.0)
        self.assertAlmostEqual(after_target.current_stop_loss or 0.0, 105.0)
        self.assertAlmostEqual(after_trailing_update.remaining_quantity or 0.0, 1.0)
        self.assertAlmostEqual(after_trailing_update.closed_quantity, 1.0)
        self.assertAlmostEqual(after_trailing_update.current_stop_loss or 0.0, 107.0)

    def test_long_ambiguous_candle_default_stop_first_closes_loss(self) -> None:
        now = datetime.now(timezone.utc)
        trade = self._lifecycle_trade(
            side="long",
            stop_loss=90.0,
            now=now,
            target_states=[
                VirtualTradeTargetState(
                    label="TP1",
                    price=110.0,
                    close_percent=100.0,
                    action="full_close",
                )
            ],
        )

        result = apply_virtual_trade_candle(
            trade,
            high=112.0,
            low=89.0,
            close=105.0,
            now=now,
            candle_open_time=1,
            candle_close_time=2,
        )

        self.assertTrue(result.closed)
        self.assertEqual(result.trade.status, "closed")
        self.assertEqual(result.trade.close_reason, "stop_loss")
        self.assertAlmostEqual(result.trade.pnl or 0.0, -10.0)
        ambiguity = result.trade.lifecycle_events[0]
        self.assertEqual(ambiguity.event_type, "intrabar_ambiguous")
        self.assertEqual(ambiguity.metadata["policy"], "conservative_stop_first")
        self.assertEqual(ambiguity.metadata["action"], "stop")

    def test_long_ambiguous_candle_target_first_closes_profit(self) -> None:
        now = datetime.now(timezone.utc)
        trade = self._lifecycle_trade(
            side="long",
            stop_loss=90.0,
            now=now,
            target_states=[
                VirtualTradeTargetState(
                    label="TP1",
                    price=110.0,
                    close_percent=100.0,
                    action="full_close",
                )
            ],
        )

        result = apply_virtual_trade_candle(
            trade,
            high=112.0,
            low=89.0,
            close=105.0,
            now=now,
            ambiguity_policy="target_first",
        )

        self.assertTrue(result.closed)
        self.assertEqual(result.trade.status, "closed")
        self.assertEqual(result.trade.close_reason, "take_profit")
        self.assertAlmostEqual(result.trade.pnl or 0.0, 10.0)
        self.assertTrue(result.trade.target_states[0].hit)
        self.assertEqual(result.trade.lifecycle_events[0].metadata["action"], "target")

    def test_long_ambiguous_candle_intrabar_unknown_stays_open_with_metadata(self) -> None:
        now = datetime.now(timezone.utc)
        trade = self._lifecycle_trade(
            side="long",
            stop_loss=90.0,
            now=now,
            target_states=[
                VirtualTradeTargetState(
                    label="TP1",
                    price=110.0,
                    close_percent=100.0,
                    action="full_close",
                )
            ],
        )

        result = apply_virtual_trade_candle(
            trade,
            high=112.0,
            low=89.0,
            close=105.0,
            now=now,
            ambiguity_policy="intrabar_unknown",
        )

        self.assertFalse(result.closed)
        self.assertEqual(result.trade.status, "open")
        self.assertIsNone(result.trade.close_reason)
        self.assertAlmostEqual(result.trade.current_price, 105.0)
        self.assertFalse(result.trade.target_states[0].hit)
        ambiguity = result.trade.lifecycle_events[-1]
        self.assertEqual(ambiguity.event_type, "intrabar_ambiguous")
        self.assertEqual(ambiguity.metadata["policy"], "intrabar_unknown")
        self.assertEqual(ambiguity.metadata["action"], "unknown")

    def test_tick_update_keeps_simple_last_price_logic(self) -> None:
        now = datetime.now(timezone.utc)
        trade = self._lifecycle_trade(
            side="long",
            stop_loss=90.0,
            now=now,
            target_states=[
                VirtualTradeTargetState(
                    label="TP1",
                    price=110.0,
                    close_percent=100.0,
                    action="full_close",
                )
            ],
        )

        result = apply_virtual_trade_market_price(trade, 110.0, now)

        self.assertTrue(result.closed)
        self.assertEqual(result.trade.close_reason, "take_profit")
        self.assertFalse(
            any(event.event_type == "intrabar_ambiguous" for event in result.trade.lifecycle_events)
        )

    @staticmethod
    def _service(
        repository: EphemeralTradeRepository | None = None,
        **kwargs,
    ) -> TradeService:
        return TradeService(
            repository=repository or EphemeralTradeRepository(),
            market_data_service=StableMarketDataService(),
            **kwargs,
        )

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

    @staticmethod
    def _lifecycle_trade(
        *,
        side: str,
        stop_loss: float,
        now: datetime,
        quantity: float = 1.0,
        size_usd: float = 100.0,
        current_stop_loss: float | None = None,
        trailing_active: bool = False,
        trailing_distance: float | None = None,
        highest_price_after_trailing: float | None = None,
        lowest_price_after_trailing: float | None = None,
        target_states: list[VirtualTradeTargetState] | None = None,
    ) -> VirtualTrade:
        return VirtualTrade(
            id=f"lifecycle_{side}",
            user_id="demo_user",
            signal_id=f"signal_{side}",
            exchange="bybit",
            symbol="BTCUSDT",
            strategy="test_strategy",
            timeframe="15m",
            side=side,
            entry_price=100.0,
            current_price=100.0,
            size_usd=size_usd,
            quantity=quantity,
            leverage=1,
            risk_percent=1.0,
            risk_amount=abs(100.0 - stop_loss) * quantity,
            stop_loss=stop_loss,
            current_stop_loss=current_stop_loss,
            trailing_active=trailing_active,
            trailing_distance=trailing_distance,
            highest_price_after_trailing=highest_price_after_trailing,
            lowest_price_after_trailing=lowest_price_after_trailing,
            take_profit=[],
            status="open",
            opened_at=now,
            updated_at=now,
            target_states=target_states or [],
        )


class TradeApiMarketCloseTest(unittest.IsolatedAsyncioTestCase):
    async def test_market_close_endpoint_closes_virtual_trade_at_current_price(self) -> None:
        service = VirtualTradeLifecycleTest._service()
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

    async def test_market_close_endpoint_preserves_invalidation_close_reason(self) -> None:
        service = VirtualTradeLifecycleTest._service()
        trade = service.open_virtual_trade(
            VirtualTradeLifecycleTest._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(fee_rate=0.001),
        )
        service.update_market_price("bybit", "BTCUSDT", 95.0)
        broker = CapturingBroker()

        with (
            patch("app.api.v1.trades.virtual_trading_service", service),
            patch("app.api.v1.trades.realtime_event_broker", broker),
        ):
            result = await close_market_trade(trade.id, CloseMarketTradeRequest(reason="invalidation"))

        self.assertEqual(result.status, "closed")
        self.assertIsNotNone(result.trade)
        assert result.trade is not None
        self.assertEqual(result.trade.close_reason, "invalidation")
        self.assertIn("invalidated", result.message)

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
        service = VirtualTradeLifecycleTest._service(repository=RealOnlyTradeRepository(real_trade))
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
