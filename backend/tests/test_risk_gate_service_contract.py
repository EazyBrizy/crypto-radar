import unittest
from datetime import datetime, timezone
from typing import Optional

from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, RealTrade, TradeJournalEntry, VirtualAccount, VirtualTrade
from app.schemas.user import RiskManagementSettings
from app.services.risk_gate import RiskContextService, RiskGateService
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
        return trades

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
        return []


class RiskGateServiceContractTest(unittest.TestCase):
    def test_virtual_gate_returns_single_entry_decision(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertNotEqual(decision.status, "failed")
        self.assertTrue(decision.can_enter)
        self.assertEqual(decision.mode, "virtual")
        self.assertEqual(decision.stage, "preview")
        self.assertAlmostEqual(decision.risk_adjustment_plan.adjusted_risk_amount, 0.75)
        self.assertAlmostEqual(decision.position_sizing.risk_amount, 0.75)
        self.assertAlmostEqual(decision.checked_position_sizing.risk_amount, 0.75)
        self.assertEqual(decision.risk_check.effective_risk_amount, decision.checked_position_sizing.risk_amount)

    def test_virtual_gate_blocks_manual_notional_above_adjusted_risk(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(),
                request=ManualConfirmRequest(size_usd=1_000),
                account=_account(),
                entry_price=100,
                open_positions=[],
                requested_notional=1_000,
                stage="pre_execution",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Risk per trade exceeds the adjusted risk limit.", decision.blockers)
        self.assertGreater(decision.checked_position_sizing.risk_amount, decision.risk_adjustment_plan.adjusted_risk_amount)

    def test_correlated_risk_requires_resolved_group(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
                correlated_open_risk_amount=3,
                correlation_group=None,
            ),
            risk_settings=_risk_settings(),
        )

        self.assertNotIn("Max correlated risk would be exceeded.", decision.blockers)
        self.assertIsNone(decision.risk_check.correlated_risk_used_percent)

    def test_correlated_risk_blocks_when_group_limit_is_exceeded(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
                correlated_open_risk_amount=3,
                correlation_group="majors",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertIn("Max correlated risk would be exceeded.", decision.blockers)
        self.assertGreater(decision.risk_check.correlated_risk_used_percent or 0, 3)

    def test_virtual_gate_warns_when_exchange_rules_are_missing(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
                exchange_rule_status="missing",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "warning")
        self.assertTrue(decision.can_enter)
        self.assertIn("Exchange instrument rules are missing.", decision.warnings)

    def test_real_gate_blocks_when_exchange_rules_are_missing(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                exchange_rule_status="missing",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Exchange instrument rules are missing.", decision.blockers)

    def test_real_gate_blocks_when_exchange_rules_are_stale(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                exchange_rule_status="stale",
                exchange_rule_age_seconds=90_000,
                exchange_rule_ttl_seconds=86_400,
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Exchange instrument rules are stale.", decision.blockers)
        self.assertEqual(decision.risk_check.exchange_rule_status, "stale")

    def test_market_spread_and_funding_are_included_in_effective_risk(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(),
                request=ManualConfirmRequest(slippage_bps=10, liquidation_price=80),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
                funding_buffer_per_unit=0.25,
                best_bid=99.95,
                best_ask=100.05,
                mark_price=100,
                funding_rate=0.0025,
                spread_percent=0.1,
                spread_bps=10,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "passed")
        self.assertEqual(decision.position_sizing.funding_buffer_per_unit, 0.25)
        self.assertGreater(decision.position_sizing.effective_risk_per_unit, 10)
        self.assertGreater(decision.risk_check.funding_buffer_amount, 0)
        self.assertEqual(decision.risk_check.market_data_status, "fresh")
        self.assertEqual(decision.risk_check.spread_bps, 10)

    def test_orderbook_depth_blocks_insufficient_liquidity(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
                orderbook_depth_usd=1,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Orderbook liquidity is insufficient for calculated position size.", decision.blockers)
        self.assertFalse(decision.risk_check.orderbook_can_fill)

    def test_spread_slippage_and_price_move_are_hard_blockers(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(),
                request=ManualConfirmRequest(slippage_bps=100),
                entry_price=102,
                stage="pre_execution",
                best_bid=101.8,
                best_ask=102,
                spread_bps=75,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=RiskManagementSettings(
                risk_profile="balanced",
                risk_per_trade_percent=1.0,
                min_rr_ratio=2.0,
                max_daily_loss_percent=3.0,
                max_account_drawdown_percent=10.0,
                max_open_risk_percent=5.0,
                max_slippage_bps=80.0,
                stop_loss_mode="structure",
            ),
        )

        self.assertEqual(decision.status, "failed")
        self.assertIn("Spread is above the configured maximum.", decision.blockers)
        self.assertIn("Expected slippage is above the configured maximum.", decision.blockers)
        self.assertIn("Price moved too far from the signal entry.", decision.blockers)
        self.assertGreater(decision.risk_check.price_deviation_bps or 0, 100)

    def test_virtual_only_protection_makes_real_entries_close_only(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                protection_state="virtual_only",
                protection_reason="Daily drawdown reached the virtual-only protection threshold.",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertTrue(decision.risk_check.close_only)
        self.assertFalse(decision.risk_check.real_entries_allowed)
        self.assertTrue(decision.risk_check.virtual_entries_allowed)
        self.assertTrue(decision.risk_check.reduce_only_allowed)
        self.assertTrue(decision.risk_check.protective_orders_allowed)

    def test_fee_rate_warning_is_exposed_in_risk_decision(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(),
                request=ManualConfirmRequest(fee_rate=0.001),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
                fee_rate_source="conservative_fallback",
                maker_fee_rate=0.001,
                taker_fee_rate=0.001,
                fee_rate_warnings=["Cached fee-rate is unavailable; using conservative fallback fee rate."],
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "warning")
        self.assertEqual(decision.risk_check.fee_rate_source, "conservative_fallback")
        self.assertEqual(decision.risk_check.taker_fee_rate, 0.001)
        self.assertIn("Cached fee-rate is unavailable; using conservative fallback fee rate.", decision.warnings)

    def test_virtual_execution_preview_exposes_backend_risk_decision(self) -> None:
        service = TradeService(
            repository=EphemeralTradeRepository(),
            risk_settings_provider=lambda _user_id: _risk_settings(),
        )

        report = service.preview_virtual_execution(_signal(), ManualConfirmRequest())

        self.assertIsNotNone(report.risk_decision)
        assert report.risk_decision is not None
        self.assertEqual(report.risk_check, report.risk_decision.risk_check)
        self.assertEqual(report.risk_decision.status, report.risk_check.status)


def _risk_settings() -> RiskManagementSettings:
    return RiskManagementSettings(
        risk_profile="balanced",
        risk_per_trade_percent=1.0,
        min_rr_ratio=2.0,
        max_daily_loss_percent=3.0,
        max_account_drawdown_percent=10.0,
        max_open_risk_percent=5.0,
        stop_loss_mode="structure",
    )


def _account() -> VirtualAccount:
    return VirtualAccount(
        user_id="demo_user",
        starting_balance=100,
        balance=100,
        equity=100,
        realized_pnl=0,
        unrealized_pnl=0,
        updated_at=datetime.now(timezone.utc),
    )


def _signal() -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_risk_gate",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.8,
        risk_reward=3.0,
        urgency="medium",
        score=78,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=90.0,
        take_profit_1=120.0,
        take_profit_2=130.0,
        explanation=[],
        risks=[],
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
