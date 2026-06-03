import unittest
from datetime import datetime, timezone
from typing import Optional

from app.schemas.signal import RadarSignal, SignalEdgeSnapshot
from app.schemas.trade_plan import TradePlan, TradePlanEntry, TradePlanInvalidation, TradePlanRiskRules, TradePlanTarget
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
                risk_profile_source="user_profile",
                execution_profile_sources={"risk_percent": "user.risk_per_trade_percent"},
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
        self.assertEqual(decision.risk_profile_source, "user_profile")
        self.assertEqual(decision.execution_profile_sources["risk_percent"], "user.risk_per_trade_percent")

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

    def test_real_gate_blocks_virtual_only_signal_score(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(score=65),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Signal score is virtual-only; real execution is blocked.", decision.blockers)

    def test_real_gate_blocks_missing_edge(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(edge=None),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn(
            "Signal edge is missing; real execution requires positive historical edge.",
            decision.blockers,
        )

    def test_real_gate_blocks_insufficient_edge_sample(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(edge=_edge(status="insufficient_sample", sample_size=20, expectancy_after_costs_r=0.25)),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Signal edge has insufficient sample size for real execution.", decision.blockers)

    def test_real_gate_blocks_negative_edge_expectancy(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(edge=_edge(status="negative", sample_size=75, expectancy_after_costs_r=-0.05)),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Signal edge is negative; real execution is blocked.", decision.blockers)

    def test_real_gate_allows_positive_edge_with_enough_sample(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(edge=_edge(status="positive", sample_size=75, expectancy_after_costs_r=0.12)),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "passed")
        self.assertTrue(decision.can_enter)

    def test_virtual_gate_allows_unknown_edge_with_warning(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(edge=_edge(status="unknown", sample_size=0, expectancy_after_costs_r=None)),
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
        self.assertIn("Edge is insufficient/unknown; virtual-only recommended.", decision.warnings)

    def test_virtual_gate_does_not_hard_block_virtual_only_signal_score(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(score=65),
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
        self.assertNotIn("Signal score is virtual-only; real execution is blocked.", decision.blockers)

    def test_real_futures_gate_blocks_unknown_liquidation_when_buffer_required(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(),
                request=ManualConfirmRequest(leverage=2),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Liquidation price is unavailable; exact futures liquidation risk is not checked.", decision.blockers)

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

    def test_risk_gate_uses_signal_trade_plan_targets(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(
                    trade_plan=_trade_plan(
                        targets=[
                            TradePlanTarget(label="TP1", price=115.0),
                            TradePlanTarget(label="TP2", price=127.0),
                            TradePlanTarget(label="TP3", price=140.0),
                        ],
                    )
                ),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.take_profit_plan.source, "trade_plan")
        self.assertEqual(
            [target.price for target in decision.take_profit_plan.targets],
            [115.0, 127.0, 140.0],
        )
        self.assertAlmostEqual(decision.take_profit_plan.targets[-1].r_multiple, 4.0)

    def test_risk_gate_falls_back_without_trade_plan(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(trade_plan=None),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.take_profit_plan.source, "risk_settings")
        self.assertEqual(
            [target.price for target in decision.take_profit_plan.targets],
            [110.0, 120.0, 130.0],
        )

    def test_real_gate_blocks_fallback_trade_plan(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(
                    trade_plan=_trade_plan(
                        targets=[
                            TradePlanTarget(
                                label="TP1",
                                price=112.0,
                                close_percent=100,
                                source="r_multiple_fallback",
                                metadata={"fallback_target_used": True},
                            )
                        ],
                        metadata={
                            "fallback_used": True,
                            "fallback_targets_used": True,
                            "fallback_target_source": "r_multiple",
                        },
                    )
                ),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings().model_copy(
                update={
                    "real_requires_positive_edge": False,
                    "real_requires_fresh_market_data": False,
                }
            ),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Trade plan incomplete", " ".join(decision.blockers))

    def test_invalid_long_trade_plan_target_below_entry_is_blocked(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(
                    trade_plan=_trade_plan(
                        targets=[TradePlanTarget(label="TP1", price=99.0)]
                    )
                ),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn(
            "TradePlan target TP1 must be above entry for long trades.",
            decision.blockers,
        )
        self.assertEqual(decision.take_profit_plan.source, "trade_plan_invalid")

    def test_invalid_short_trade_plan_target_above_entry_is_blocked(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(
                    direction="short",
                    stop_loss=110.0,
                    take_profit_1=90.0,
                    take_profit_2=80.0,
                    trade_plan=_trade_plan(
                        stop_loss=110.0,
                        targets=[TradePlanTarget(label="TP1", price=101.0)],
                    ),
                ),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn(
            "TradePlan target TP1 must be below entry for short trades.",
            decision.blockers,
        )

    def test_measured_move_tp3_target_survives_risk_gate(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(
                    trade_plan=_trade_plan(
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
        self.assertEqual(decision.take_profit_plan.targets[-1].label, "TP3")
        self.assertEqual(decision.take_profit_plan.targets[-1].price, 145.0)
        self.assertAlmostEqual(decision.take_profit_plan.targets[-1].r_multiple, 4.5)
        self.assertEqual(decision.take_profit_plan.targets[-1].close_percent, 30.0)

    def test_trade_plan_selected_rr_target_is_respected(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(
                    trade_plan=_trade_plan(
                        targets=[
                            TradePlanTarget(label="TP1", price=112.0, close_percent=40),
                            TradePlanTarget(label="TP2", price=125.0, close_percent=30),
                            TradePlanTarget(label="TP3", price=140.0, close_percent=30),
                        ],
                        selected_rr_target="nearest",
                    )
                ),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="preview",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.take_profit_plan.selected_rr_target, "nearest")
        self.assertAlmostEqual(decision.risk_check.rr or 0, 1.2)
        self.assertEqual(decision.status, "warning")
        self.assertTrue(decision.can_enter)
        self.assertFalse(any("R:R is below" in blocker for blocker in decision.blockers))
        self.assertTrue(any("Risk/reward warning" in warning for warning in decision.warnings))

    def test_virtual_low_rr_soft_guard_warns_without_blocking(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(trade_plan=_low_rr_trade_plan()),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="pre_execution",
            ),
            risk_settings=_risk_settings().model_copy(update={"virtual_rr_guard_mode": "soft"}),
        )

        self.assertEqual(decision.status, "warning")
        self.assertTrue(decision.can_enter)
        self.assertFalse(_has_rr_policy_blocker(decision))
        self.assertTrue(_has_rr_warning(decision))
        self.assertTrue(decision.risk_check.risk_reward_warning)
        self.assertFalse(decision.risk_check.risk_reward_blocked)
        self.assertEqual(decision.risk_check.risk_reward_guard_mode, "soft")
        self.assertAlmostEqual(decision.risk_check.rr or 0, 1.2)
        self.assertEqual(decision.risk_check.min_rr_ratio, 2.0)

    def test_backtest_rr_context_uses_backtest_guard_instead_of_virtual_guard(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(trade_plan=_low_rr_trade_plan()),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="pre_execution",
                rr_guard_context="backtest",
            ),
            risk_settings=_risk_settings().model_copy(
                update={
                    "virtual_rr_guard_mode": "hard",
                    "backtest_rr_guard_mode": "soft",
                }
            ),
        )

        self.assertEqual(decision.status, "warning")
        self.assertTrue(decision.can_enter)
        self.assertFalse(_has_rr_policy_blocker(decision))
        self.assertTrue(_has_rr_warning(decision))
        self.assertTrue(decision.risk_check.risk_reward_warning)
        self.assertFalse(decision.risk_check.risk_reward_blocked)
        self.assertEqual(decision.risk_check.risk_reward_guard_mode, "soft")

    def test_backtest_rr_context_can_hard_block_when_backtest_guard_is_hard(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(trade_plan=_low_rr_trade_plan()),
                request=ManualConfirmRequest(),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="pre_execution",
                rr_guard_context="backtest",
            ),
            risk_settings=_risk_settings().model_copy(
                update={
                    "virtual_rr_guard_mode": "soft",
                    "backtest_rr_guard_mode": "hard",
                }
            ),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertTrue(_has_rr_policy_blocker(decision))
        self.assertFalse(_has_rr_warning(decision))
        self.assertTrue(decision.risk_check.risk_reward_blocked)
        self.assertFalse(decision.risk_check.risk_reward_warning)
        self.assertEqual(decision.risk_check.risk_reward_guard_mode, "hard")

    def test_real_low_rr_hard_guard_blocks_execution(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(trade_plan=_low_rr_trade_plan()),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings().model_copy(
                update={
                    "real_rr_guard_mode": "hard",
                    "real_requires_positive_edge": False,
                    "real_requires_fresh_market_data": False,
                }
            ),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertTrue(_has_rr_policy_blocker(decision))
        self.assertTrue(decision.risk_check.risk_reward_blocked)
        self.assertFalse(decision.risk_check.risk_reward_warning)
        self.assertEqual(decision.risk_check.risk_reward_guard_mode, "hard")
        self.assertAlmostEqual(decision.risk_check.rr or 0, 1.2)

    def test_real_low_rr_soft_guard_warns_and_allows_execution(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(trade_plan=_low_rr_trade_plan()),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=_risk_settings().model_copy(
                update={
                    "real_rr_guard_mode": "soft",
                    "real_requires_positive_edge": False,
                    "real_requires_fresh_market_data": False,
                }
            ),
        )

        self.assertEqual(decision.status, "warning")
        self.assertTrue(decision.can_enter)
        self.assertFalse(_has_rr_policy_blocker(decision))
        self.assertTrue(_has_rr_warning(decision))
        self.assertTrue(decision.risk_check.risk_reward_warning)
        self.assertFalse(decision.risk_check.risk_reward_blocked)
        self.assertEqual(decision.risk_check.risk_reward_guard_mode, "soft")

    def test_virtual_low_rr_off_guard_keeps_rr_metrics_without_warning(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(trade_plan=_low_rr_trade_plan()),
                request=ManualConfirmRequest(liquidation_price=80),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="pre_execution",
            ),
            risk_settings=_risk_settings().model_copy(update={"virtual_rr_guard_mode": "off"}),
        )

        self.assertEqual(decision.status, "passed")
        self.assertTrue(decision.can_enter)
        self.assertFalse(_has_rr_policy_blocker(decision))
        self.assertFalse(_has_rr_warning(decision))
        self.assertFalse(decision.risk_check.risk_reward_warning)
        self.assertFalse(decision.risk_check.risk_reward_blocked)
        self.assertEqual(decision.risk_check.risk_reward_guard_mode, "off")
        self.assertAlmostEqual(decision.risk_check.rr or 0, 1.2)
        self.assertEqual(decision.risk_check.min_rr_ratio, 2.0)

    def test_take_profit_required_still_blocks_when_no_tp_plan_exists(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(trade_plan=_trade_plan(targets=[])),
                request=ManualConfirmRequest(liquidation_price=80),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="pre_execution",
            ),
            risk_settings=_risk_settings().model_copy(update={"take_profit_required": True}),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertIn("Take-profit plan is required.", decision.blockers)
        self.assertTrue(any("Trade plan incomplete" in blocker for blocker in decision.blockers))

    def test_virtual_gate_blocks_missing_trade_plan_stop(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(trade_plan=_trade_plan(stop_loss=None, targets=[
                    TradePlanTarget(label="TP1", price=120.0, close_percent=100)
                ])),
                request=ManualConfirmRequest(liquidation_price=80),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="pre_execution",
            ),
            risk_settings=_risk_settings(),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertTrue(any("stop" in blocker and "execution is blocked" in blocker for blocker in decision.blockers))

    def test_virtual_gate_blocks_missing_trade_plan_target(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_signal(trade_plan=_trade_plan(targets=[])),
                request=ManualConfirmRequest(liquidation_price=80),
                account=_account(),
                entry_price=100,
                open_positions=[],
                stage="pre_execution",
            ),
            risk_settings=_risk_settings().model_copy(update={"take_profit_required": False}),
        )

        self.assertEqual(decision.status, "failed")
        self.assertFalse(decision.can_enter)
        self.assertTrue(any("target" in blocker and "execution is blocked" in blocker for blocker in decision.blockers))

    def test_strategy_rr_guard_override_uses_original_signal_strategy(self) -> None:
        decision = RiskGateService().evaluate(
            context=RiskContextService().build_real_context(
                signal=_signal(
                    trade_plan=_trade_plan(
                        targets=[TradePlanTarget(label="TP1", price=112.0, close_percent=100)],
                        selected_rr_target="nearest",
                    )
                ),
                request=ManualConfirmRequest(),
                entry_price=100,
                stage="pre_execution",
                best_bid=99.95,
                best_ask=100.05,
                orderbook_depth_usd=10_000,
                market_data_status="fresh",
            ),
            risk_settings=RiskManagementSettings(
                risk_profile="balanced",
                risk_per_trade_percent=1.0,
                min_rr_ratio=2.0,
                real_rr_guard_mode="soft",
                strategy_rr_guard_modes={"trend_pullback_continuation": "hard"},
                max_daily_loss_percent=3.0,
                max_account_drawdown_percent=10.0,
                max_open_risk_percent=5.0,
                stop_loss_mode="structure",
                real_requires_positive_edge=False,
                real_requires_fresh_market_data=False,
            ),
        )

        self.assertEqual(decision.status, "failed")
        self.assertEqual(decision.risk_check.risk_reward_guard_mode, "hard")
        self.assertTrue(any("Real execution RR policy rejected" in blocker for blocker in decision.blockers))


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


def _signal(
    *,
    score: float = 78,
    strategy: str = "trend_pullback_continuation",
    direction: str = "long",
    stop_loss: float = 90.0,
    take_profit_1: float = 120.0,
    take_profit_2: float = 130.0,
    trade_plan: TradePlan | None = None,
    edge: SignalEdgeSnapshot | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_risk_gate",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy=strategy,
        direction=direction,
        confidence=0.8,
        risk_reward=3.0,
        urgency="medium",
        score=score,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        explanation=[],
        risks=[],
        trade_plan=trade_plan,
        edge=edge,
        created_at=now,
        updated_at=now,
    )


def _edge(
    *,
    status: str,
    sample_size: int,
    expectancy_after_costs_r: float | None,
) -> SignalEdgeSnapshot:
    return SignalEdgeSnapshot(
        status=status,
        sample_size=sample_size,
        min_sample_size=50,
        winrate=0.55,
        avg_win_r=1.2,
        avg_loss_r=-1.0,
        expectancy_r=0.21,
        expectancy_after_costs_r=expectancy_after_costs_r,
        profit_factor=1.4,
        confidence_score=0.8,
        source="outcome" if status != "unknown" else "none",
        score_bucket="70-79",
    )


def _trade_plan(
    *,
    targets: list[TradePlanTarget],
    stop_loss: float | None = 90.0,
    selected_rr_target: str | None = None,
    metadata: dict[str, object] | None = None,
) -> TradePlan:
    normalized_targets = [
        target.model_copy(update={"source": target.source or "test_structure"})
        for target in targets
    ]
    return TradePlan(
        entry=TradePlanEntry(price=100.0, min_price=100.0, max_price=100.0),
        stop_loss=stop_loss,
        targets=normalized_targets,
        invalidation=TradePlanInvalidation(
            price=stop_loss,
            hard_stop=stop_loss,
            conditions=["Close beyond test structure"],
            metadata={"source": "test_structure"},
        ),
        risk_rules=TradePlanRiskRules(selected_rr_target=selected_rr_target),
        metadata=metadata or {},
    )


def _low_rr_trade_plan() -> TradePlan:
    return _trade_plan(
        targets=[TradePlanTarget(label="TP1", price=112.0, close_percent=100)],
        selected_rr_target="nearest",
    )


def _has_rr_policy_blocker(decision) -> bool:
    return any("RR policy rejected" in blocker for blocker in decision.blockers)


def _has_rr_warning(decision) -> bool:
    return any("Risk/reward warning" in warning for warning in decision.warnings)


if __name__ == "__main__":
    unittest.main()
