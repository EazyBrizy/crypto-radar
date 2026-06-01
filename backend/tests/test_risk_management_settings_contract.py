import unittest

from app.schemas.user import RiskManagementPatch
from app.services.risk_management import (
    apply_risk_management_patch,
    calculate_breakeven_plan,
    calculate_futures_risk_plan,
    calculate_position_sizing,
    calculate_risk_check_result,
    calculate_stop_loss_plan,
    calculate_take_profit_plan,
    calculate_trade_risk_adjustment,
    calculate_trailing_stop_plan,
    normalize_risk_management_settings,
)


class RiskManagementSettingsContractTest(unittest.TestCase):
    def test_defaults_use_balanced_profile(self) -> None:
        settings = normalize_risk_management_settings({}, None)

        self.assertEqual(settings["risk_profile"], "balanced")
        self.assertEqual(settings["risk_per_trade_percent"], 1.0)
        self.assertEqual(settings["min_rr_ratio"], 2.0)
        self.assertEqual(settings["max_daily_loss_percent"], 3.0)
        self.assertEqual(settings["max_weekly_loss_percent"], 7.0)
        self.assertEqual(settings["max_open_risk_percent"], 5.0)
        self.assertEqual(settings["max_correlated_risk_percent"], 3.0)
        self.assertEqual(settings["max_spread_bps"], 50.0)
        self.assertEqual(settings["max_slippage_bps"], 150.0)
        self.assertEqual(settings["max_price_deviation_bps"], 100.0)
        self.assertEqual(settings["max_orderbook_liquidity_ratio"], 1.0)
        self.assertTrue(settings["include_fees_in_risk"])
        self.assertTrue(settings["include_slippage_in_risk"])
        self.assertTrue(settings["stop_loss_required"])
        self.assertTrue(settings["take_profit_required"])
        self.assertEqual(settings["stop_loss_mode"], "fixed_percent")
        self.assertEqual(settings["default_stop_loss_percent"], 1.5)
        self.assertEqual(settings["atr_period"], 14)
        self.assertEqual(settings["atr_multiplier"], 2.0)
        self.assertEqual(settings["take_profit_mode"], "risk_multiple")
        self.assertEqual(settings["tp1_r_multiple"], 1.0)
        self.assertEqual(settings["tp2_r_multiple"], 2.0)
        self.assertEqual(settings["tp3_r_multiple"], 3.0)
        self.assertTrue(settings["partial_take_profit_enabled"])
        self.assertEqual(settings["tp1_close_percent"], 30.0)
        self.assertEqual(settings["tp2_close_percent"], 40.0)
        self.assertEqual(settings["tp3_close_percent"], 30.0)
        self.assertEqual(settings["move_sl_to_breakeven_after_r"], 1.0)
        self.assertEqual(settings["breakeven_offset_percent"], 0.05)
        self.assertTrue(settings["trailing_stop_enabled"])
        self.assertEqual(settings["trailing_mode"], "atr")
        self.assertEqual(settings["trailing_atr_multiplier"], 1.5)
        self.assertEqual(settings["trailing_stop_percent"], 0.5)
        self.assertEqual(settings["max_leverage"], 3)
        self.assertEqual(settings["min_liquidation_buffer_percent"], 2.0)
        self.assertEqual(settings["spot_risk_per_trade_percent"], 1.0)
        self.assertEqual(settings["spot_max_position_size_percent"], 20.0)
        self.assertTrue(settings["spot_stop_required"])
        self.assertEqual(settings["futures_risk_per_trade_percent"], 0.5)
        self.assertEqual(settings["futures_max_leverage"], 3)
        self.assertEqual(settings["futures_max_open_risk_percent"], 3.0)
        self.assertTrue(settings["futures_liquidation_buffer_required"])
        self.assertEqual(settings["virtual_risk_mode"], "same_as_real")
        self.assertEqual(settings["virtual_starting_balance"], 10_000.0)
        self.assertEqual(settings["virtual_slippage_model"], "spread_based")
        self.assertEqual(settings["virtual_fee_model"], "exchange_based")
        self.assertTrue(settings["real_requires_fresh_market_data"])
        self.assertTrue(settings["real_requires_positive_edge"])
        self.assertEqual(settings["edge_min_sample_size"], 50)
        self.assertEqual(settings["min_expectancy_after_costs_r"], 0.05)
        self.assertEqual(settings["strategy_risk_multipliers"]["trend_pullback_continuation"], 1.0)
        self.assertEqual(settings["strategy_risk_multipliers"]["volatility_squeeze_breakout"], 0.75)
        self.assertEqual(settings["strategy_risk_multipliers"]["liquidity_sweep_reversal"], 1.0)
        self.assertEqual(settings["strategy_risk_multipliers"]["trend_following"], 1.0)
        self.assertEqual(settings["strategy_risk_multipliers"]["breakout"], 0.75)
        self.assertEqual(settings["strategy_risk_multipliers"]["smart_money_setup"], 1.0)

    def test_preset_patch_replaces_custom_values(self) -> None:
        settings = apply_risk_management_patch(
            current_settings={
                "risk_profile": "custom",
                "risk_per_trade_percent": 0.4,
                "min_rr_ratio": 3.0,
                "max_daily_loss_percent": 1.0,
                "max_account_drawdown_percent": 5.0,
                "max_open_risk_percent": 2.0,
            },
            current_user_profile="custom",
            patch=None,
            risk_profile="balanced",
        )

        self.assertIsNotNone(settings)
        self.assertEqual(settings["risk_profile"], "balanced")
        self.assertEqual(settings["risk_per_trade_percent"], 1.0)

    def test_manual_values_force_custom_profile(self) -> None:
        settings = apply_risk_management_patch(
            current_settings={},
            current_user_profile="balanced",
            patch=RiskManagementPatch(
                risk_per_trade_percent=0.6,
                min_rr_ratio=2.5,
                max_daily_loss_percent=2.0,
                max_account_drawdown_percent=9.0,
                max_open_risk_percent=4.0,
                max_spread_bps=25.0,
                max_slippage_bps=80.0,
                max_price_deviation_bps=60.0,
                max_orderbook_liquidity_ratio=0.75,
                stop_loss_mode="atr",
                default_stop_loss_percent=2.0,
                atr_period=21,
                atr_multiplier=2.5,
                tp1_r_multiple=1.25,
                tp2_r_multiple=2.25,
                tp3_r_multiple=3.25,
                move_sl_to_breakeven_after_r=1.25,
                breakeven_offset_percent=0.1,
                trailing_stop_enabled=True,
                trailing_mode="percent",
                trailing_stop_percent=0.75,
                max_leverage=5,
                min_liquidation_buffer_percent=3.0,
                spot_risk_per_trade_percent=0.8,
                futures_risk_per_trade_percent=0.4,
                virtual_risk_mode="custom",
                virtual_risk_per_trade_percent=0.25,
                virtual_starting_balance=50_000,
                virtual_slippage_model="orderbook_based",
                virtual_fee_model="exchange_based",
                real_requires_fresh_market_data=False,
                real_requires_positive_edge=False,
                edge_min_sample_size=25,
                min_expectancy_after_costs_r=0.02,
                strategy_risk_multipliers={"scalping": 0.4},
            ),
            risk_profile=None,
        )

        self.assertIsNotNone(settings)
        self.assertEqual(settings["risk_profile"], "custom")
        self.assertEqual(settings["risk_per_trade_percent"], 0.6)
        self.assertEqual(settings["min_rr_ratio"], 2.5)
        self.assertEqual(settings["max_spread_bps"], 25.0)
        self.assertEqual(settings["max_slippage_bps"], 80.0)
        self.assertEqual(settings["max_price_deviation_bps"], 60.0)
        self.assertEqual(settings["max_orderbook_liquidity_ratio"], 0.75)
        self.assertEqual(settings["stop_loss_mode"], "atr")
        self.assertEqual(settings["atr_period"], 21)
        self.assertEqual(settings["atr_multiplier"], 2.5)
        self.assertEqual(settings["tp3_r_multiple"], 3.25)
        self.assertEqual(settings["move_sl_to_breakeven_after_r"], 1.25)
        self.assertEqual(settings["trailing_mode"], "percent")
        self.assertEqual(settings["max_leverage"], 5)
        self.assertEqual(settings["virtual_risk_mode"], "custom")
        self.assertEqual(settings["virtual_slippage_model"], "orderbook_based")
        self.assertFalse(settings["real_requires_fresh_market_data"])
        self.assertFalse(settings["real_requires_positive_edge"])
        self.assertEqual(settings["edge_min_sample_size"], 25)
        self.assertEqual(settings["min_expectancy_after_costs_r"], 0.02)
        self.assertEqual(settings["strategy_risk_multipliers"]["scalping"], 0.4)

    def test_zero_disables_optional_risk_limits(self) -> None:
        settings = apply_risk_management_patch(
            current_settings={},
            current_user_profile="balanced",
            patch=RiskManagementPatch(
                min_rr_ratio=0,
                max_daily_loss_percent=0,
                max_weekly_loss_percent=0,
                max_account_drawdown_percent=0,
                max_open_risk_percent=0,
                max_correlated_risk_percent=0,
                max_spread_bps=0,
                max_slippage_bps=0,
                max_price_deviation_bps=0,
                max_orderbook_liquidity_ratio=0,
                futures_max_open_risk_percent=0,
                spot_max_position_size_percent=0,
                min_liquidation_buffer_percent=0,
            ),
            risk_profile=None,
        )

        self.assertIsNotNone(settings)
        self.assertEqual(settings["max_daily_loss_percent"], 0)
        self.assertEqual(settings["max_open_risk_percent"], 0)
        self.assertEqual(settings["futures_max_open_risk_percent"], 0)
        self.assertEqual(settings["max_orderbook_liquidity_ratio"], 0)

    def test_fixed_percent_stop_loss_plan(self) -> None:
        stop_plan = calculate_stop_loss_plan(
            entry_price=100,
            side="long",
            risk_settings=normalize_risk_management_settings({}, "balanced"),
        )

        self.assertEqual(stop_plan.mode, "fixed_percent")
        self.assertAlmostEqual(stop_plan.stop_loss_price, 98.5)
        self.assertAlmostEqual(stop_plan.risk_per_unit, 1.5)

    def test_atr_stop_loss_plan_uses_multiplier(self) -> None:
        settings = normalize_risk_management_settings(
            {
                "risk_profile": "custom",
                "stop_loss_mode": "atr",
                "atr_period": 14,
                "atr_multiplier": 2,
            },
            "custom",
        )
        stop_plan = calculate_stop_loss_plan(
            entry_price=100,
            side="long",
            risk_settings=settings,
            atr_value=2,
        )

        self.assertEqual(stop_plan.mode, "atr")
        self.assertAlmostEqual(stop_plan.stop_loss_price, 96)
        self.assertAlmostEqual(stop_plan.risk_per_unit, 4)

    def test_structure_stop_loss_plan_uses_signal_stop(self) -> None:
        settings = normalize_risk_management_settings(
            {"risk_profile": "custom", "stop_loss_mode": "structure"},
            "custom",
        )
        stop_plan = calculate_stop_loss_plan(
            entry_price=100,
            side="short",
            risk_settings=settings,
            signal_stop_loss_price=104,
        )

        self.assertEqual(stop_plan.mode, "structure")
        self.assertEqual(stop_plan.source, "structure")
        self.assertAlmostEqual(stop_plan.stop_loss_price, 104)

    def test_take_profit_plan_uses_r_multiples_and_partial_close(self) -> None:
        take_profit_plan = calculate_take_profit_plan(
            entry_price=100,
            stop_loss_price=98,
            side="long",
            risk_settings=normalize_risk_management_settings({}, "balanced"),
        )

        self.assertEqual([target.label for target in take_profit_plan.targets], ["TP1", "TP2", "TP3"])
        self.assertEqual([target.price for target in take_profit_plan.targets], [102, 104, 106])
        self.assertEqual([target.close_percent for target in take_profit_plan.targets], [30, 40, 30])
        self.assertEqual(take_profit_plan.targets[0].action, "move_stop_to_breakeven")
        self.assertEqual(take_profit_plan.targets[1].action, "trailing_stop")
        self.assertEqual(take_profit_plan.targets[2].action, "full_close")

    def test_breakeven_plan_uses_r_trigger_and_fee_offset(self) -> None:
        plan = calculate_breakeven_plan(
            entry_price=100,
            stop_loss_price=98,
            side="long",
            risk_settings=normalize_risk_management_settings({}, "balanced"),
        )

        self.assertEqual(plan.trigger_price, 102)
        self.assertEqual(plan.breakeven_stop_price, 100.05)

    def test_trailing_stop_plan_supports_atr_and_percent_fallback(self) -> None:
        settings = normalize_risk_management_settings(
            {"risk_profile": "custom", "trailing_mode": "atr", "trailing_atr_multiplier": 1.5},
            "custom",
        )
        plan = calculate_trailing_stop_plan(
            entry_price=100,
            current_price=105,
            side="long",
            risk_settings=settings,
            atr_value=2,
        )

        self.assertEqual(plan.mode, "atr")
        self.assertEqual(plan.trailing_distance, 3)
        self.assertEqual(plan.trailing_stop_price, 102)

    def test_liquidation_guard_blocks_liquidation_before_stop(self) -> None:
        plan = calculate_futures_risk_plan(
            entry_price=100,
            stop_loss_price=98,
            side="long",
            leverage=3,
            liquidation_price=99,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
        )

        self.assertEqual(plan.status, "blocked")
        self.assertTrue(plan.liquidation_before_stop)

    def test_liquidation_guard_passes_with_buffer(self) -> None:
        plan = calculate_futures_risk_plan(
            entry_price=100,
            stop_loss_price=98,
            side="long",
            leverage=3,
            liquidation_price=95,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
        )

        self.assertEqual(plan.status, "passed")
        self.assertEqual(plan.liquidation_buffer_percent, 3)

    def test_leverage_guard_blocks_above_user_max(self) -> None:
        plan = calculate_futures_risk_plan(
            entry_price=100,
            stop_loss_price=98,
            side="long",
            leverage=10,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
        )

        self.assertEqual(plan.status, "blocked")
        self.assertFalse(plan.leverage_allowed)

    def test_position_sizing_uses_stop_distance_before_leverage(self) -> None:
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
            entry_price=50_000,
            stop_loss_price=49_500,
            side="long",
            leverage=5,
            fee_rate=0,
            slippage_bps=0,
        )

        self.assertEqual(sizing.risk_amount, 100)
        self.assertEqual(sizing.effective_risk_per_unit, 500)
        self.assertEqual(sizing.position_size_base, 0.2)
        self.assertEqual(sizing.notional, 10_000)
        self.assertEqual(sizing.required_margin, 2_000)

    def test_trade_risk_adjustment_uses_strategy_and_signal_multipliers(self) -> None:
        plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
            instrument_type="spot",
            strategy="breakout",
            signal_score=70,
        )

        self.assertEqual(plan.base_risk_percent, 1.0)
        self.assertEqual(plan.strategy_risk_multiplier, 0.75)
        self.assertEqual(plan.signal_score_multiplier, 0.5)
        self.assertAlmostEqual(plan.adjusted_risk_percent, 0.375)
        self.assertAlmostEqual(plan.adjusted_risk_amount, 37.5)

    def test_trade_risk_adjustment_uses_real_strategy_multiplier(self) -> None:
        plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
            instrument_type="spot",
            strategy="volatility_squeeze_breakout",
            signal_score=90,
        )

        self.assertEqual(plan.strategy_risk_multiplier, 0.75)
        self.assertAlmostEqual(plan.adjusted_risk_percent, 0.75)

    def test_trade_risk_adjustment_preserves_legacy_breakout_alias(self) -> None:
        plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
            instrument_type="spot",
            strategy="breakout",
            signal_score=90,
        )

        self.assertEqual(plan.strategy_risk_multiplier, 0.75)
        self.assertAlmostEqual(plan.adjusted_risk_percent, 0.75)

    def test_trade_risk_adjustment_falls_back_to_legacy_breakout_alias(self) -> None:
        settings = normalize_risk_management_settings(
            {
                "risk_profile": "custom",
                "strategy_risk_multipliers": {"breakout": 0.6},
            },
            "custom",
        )

        plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=settings,
            instrument_type="spot",
            strategy="volatility_squeeze_breakout",
            signal_score=90,
        )

        self.assertEqual(plan.strategy_risk_multiplier, 0.6)
        self.assertAlmostEqual(plan.adjusted_risk_percent, 0.6)

    def test_position_sizing_can_use_adjusted_risk_percent(self) -> None:
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
            entry_price=100,
            stop_loss_price=95,
            side="long",
            risk_per_trade_percent=0.375,
        )

        self.assertAlmostEqual(sizing.risk_amount, 37.5)
        self.assertAlmostEqual(sizing.notional, 750.0)

    def test_risk_check_fails_on_low_rr(self) -> None:
        settings = normalize_risk_management_settings({}, "balanced")
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=settings,
            instrument_type="spot",
            strategy="trend_following",
            signal_score=90,
        )
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=settings,
            entry_price=100,
            stop_loss_price=95,
            side="long",
            risk_per_trade_percent=risk_plan.adjusted_risk_percent,
        )
        tp_plan = calculate_take_profit_plan(
            entry_price=100,
            stop_loss_price=95,
            side="long",
            risk_settings={**settings, "tp1_r_multiple": 0.5, "tp2_r_multiple": 1.0, "tp3_r_multiple": 1.5},
        )
        result = calculate_risk_check_result(
            risk_settings=settings,
            risk_adjustment=risk_plan,
            position_sizing=sizing,
            take_profit_plan=tp_plan,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("R:R is below the configured minimum.", result.blockers)

    def test_zero_limits_do_not_block_risk_check(self) -> None:
        settings = normalize_risk_management_settings(
            {
                "risk_profile": "custom",
                "min_rr_ratio": 0,
                "max_daily_loss_percent": 0,
                "max_open_risk_percent": 0,
                "max_correlated_risk_percent": 0,
                "max_spread_bps": 0,
                "max_slippage_bps": 0,
                "max_price_deviation_bps": 0,
                "max_orderbook_liquidity_ratio": 0,
                "futures_max_open_risk_percent": 0,
            },
            "custom",
        )
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=settings,
            instrument_type="futures",
            strategy="trend_following",
            signal_score=90,
        )
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=settings,
            entry_price=110,
            stop_loss_price=100,
            side="long",
            leverage=3,
            risk_per_trade_percent=risk_plan.adjusted_risk_percent,
            slippage_bps=250,
        )
        tp_plan = calculate_take_profit_plan(
            entry_price=110,
            stop_loss_price=100,
            side="long",
            risk_settings={**settings, "tp1_r_multiple": 0.5, "tp2_r_multiple": 1.0, "tp3_r_multiple": 1.0},
        )
        result = calculate_risk_check_result(
            risk_settings=settings,
            risk_adjustment=risk_plan,
            position_sizing=sizing,
            take_profit_plan=tp_plan,
            open_risk_amount=9_000,
            daily_loss_amount=9_000,
            correlated_open_risk_amount=9_000,
            correlation_group="majors",
            signal_entry_price=100,
            spread_bps=500,
            orderbook_depth_usd=1,
        )

        self.assertNotIn("R:R is below the configured minimum.", result.blockers)
        self.assertNotIn("Daily loss limit would be exceeded.", result.blockers)
        self.assertNotIn("Max open risk would be exceeded.", result.blockers)
        self.assertNotIn("Max correlated risk would be exceeded.", result.blockers)
        self.assertNotIn("Spread is above the configured maximum.", result.blockers)
        self.assertNotIn("Expected slippage is above the configured maximum.", result.blockers)
        self.assertNotIn("Price moved too far from the signal entry.", result.blockers)
        self.assertNotIn("Orderbook liquidity is insufficient for calculated position size.", result.blockers)

    def test_risk_check_exposes_account_drawdown_context(self) -> None:
        settings = normalize_risk_management_settings({}, "balanced")
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=settings,
            instrument_type="virtual",
            strategy="trend_following",
            signal_score=90,
        )
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=settings,
            entry_price=100,
            stop_loss_price=95,
            side="long",
            risk_per_trade_percent=risk_plan.adjusted_risk_percent,
        )

        result = calculate_risk_check_result(
            risk_settings=settings,
            risk_adjustment=risk_plan,
            position_sizing=sizing,
            protection_state="blocked",
            protection_reason="Risk protection mode blocks entries after account drawdown.",
            account_drawdown_percent=37.19,
            max_account_drawdown_percent=15,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.account_drawdown_percent, 37.19)
        self.assertEqual(result.max_account_drawdown_percent, 15)
        self.assertIn("Risk protection mode blocks entries after account drawdown.", result.blockers)

    def test_risk_check_blocks_real_virtual_only_signal_score(self) -> None:
        settings = normalize_risk_management_settings({}, "balanced")
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=settings,
            instrument_type="spot",
            strategy="trend_pullback_continuation",
            signal_score=65,
        )
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=settings,
            entry_price=100,
            stop_loss_price=90,
            side="long",
            risk_per_trade_percent=risk_plan.adjusted_risk_percent,
        )
        tp_plan = calculate_take_profit_plan(
            entry_price=100,
            stop_loss_price=90,
            side="long",
            risk_settings=settings,
        )

        result = calculate_risk_check_result(
            risk_settings=settings,
            risk_adjustment=risk_plan,
            position_sizing=sizing,
            take_profit_plan=tp_plan,
            execution_mode="real",
            best_bid=99.95,
            best_ask=100.05,
            orderbook_depth_usd=100_000,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("Signal score is virtual-only; real execution is blocked.", result.blockers)

    def test_risk_check_does_not_hard_block_virtual_only_signal_score_for_virtual(self) -> None:
        settings = normalize_risk_management_settings({}, "balanced")
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=settings,
            instrument_type="spot",
            strategy="trend_pullback_continuation",
            signal_score=65,
        )
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=settings,
            entry_price=100,
            stop_loss_price=90,
            side="long",
            risk_per_trade_percent=risk_plan.adjusted_risk_percent,
        )
        tp_plan = calculate_take_profit_plan(
            entry_price=100,
            stop_loss_price=90,
            side="long",
            risk_settings=settings,
        )

        result = calculate_risk_check_result(
            risk_settings=settings,
            risk_adjustment=risk_plan,
            position_sizing=sizing,
            take_profit_plan=tp_plan,
            execution_mode="virtual",
        )

        self.assertNotEqual(result.status, "failed")
        self.assertNotIn("Signal score is virtual-only; real execution is blocked.", result.blockers)

    def test_risk_check_applies_spot_max_position_percent(self) -> None:
        settings = normalize_risk_management_settings({}, "balanced")
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=settings,
            instrument_type="spot",
            strategy="trend_pullback_continuation",
            signal_score=90,
        )
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=settings,
            entry_price=100,
            stop_loss_price=99,
            side="long",
            risk_per_trade_percent=risk_plan.adjusted_risk_percent,
        )
        tp_plan = calculate_take_profit_plan(
            entry_price=100,
            stop_loss_price=99,
            side="long",
            risk_settings=settings,
        )

        result = calculate_risk_check_result(
            risk_settings=settings,
            risk_adjustment=risk_plan,
            position_sizing=sizing,
            take_profit_plan=tp_plan,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("Spot position size exceeds the configured maximum.", result.blockers)

    def test_risk_check_blocks_real_futures_unknown_liquidation_when_required(self) -> None:
        settings = normalize_risk_management_settings({}, "balanced")
        risk_plan = calculate_trade_risk_adjustment(
            account_equity=10_000,
            risk_settings=settings,
            instrument_type="futures",
            strategy="trend_pullback_continuation",
            signal_score=90,
        )
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=settings,
            entry_price=100,
            stop_loss_price=90,
            side="long",
            leverage=2,
            risk_per_trade_percent=risk_plan.adjusted_risk_percent,
        )
        tp_plan = calculate_take_profit_plan(
            entry_price=100,
            stop_loss_price=90,
            side="long",
            risk_settings=settings,
        )
        futures_plan = calculate_futures_risk_plan(
            entry_price=100,
            stop_loss_price=90,
            side="long",
            leverage=2,
            liquidation_price=None,
            risk_settings=settings,
        )

        result = calculate_risk_check_result(
            risk_settings=settings,
            risk_adjustment=risk_plan,
            position_sizing=sizing,
            take_profit_plan=tp_plan,
            futures_risk_plan=futures_plan,
            execution_mode="real",
            best_bid=99.95,
            best_ask=100.05,
            orderbook_depth_usd=100_000,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("Liquidation price is unavailable; exact futures liquidation risk is not checked.", result.blockers)

    def test_position_sizing_includes_fee_and_slippage_buffers(self) -> None:
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
            entry_price=50_000,
            stop_loss_price=49_500,
            side="long",
            leverage=1,
            fee_rate=0.001,
            slippage_bps=10,
        )

        self.assertEqual(sizing.estimated_entry_fee_per_unit, 50)
        self.assertEqual(sizing.estimated_exit_fee_per_unit, 49.5)
        self.assertAlmostEqual(sizing.slippage_buffer_per_unit, 99.5)
        self.assertAlmostEqual(sizing.effective_risk_per_unit, 699.0)
        self.assertLess(sizing.position_size_base, 0.2)

    def test_position_sizing_includes_funding_buffer(self) -> None:
        sizing = calculate_position_sizing(
            account_equity=10_000,
            risk_settings=normalize_risk_management_settings({}, "balanced"),
            entry_price=50_000,
            stop_loss_price=49_500,
            side="long",
            leverage=3,
            funding_buffer_per_unit=5.0,
        )

        self.assertEqual(sizing.funding_buffer_per_unit, 5.0)
        self.assertAlmostEqual(sizing.effective_risk_per_unit, 505.0)
        self.assertLess(sizing.position_size_base, 0.2)


if __name__ == "__main__":
    unittest.main()
