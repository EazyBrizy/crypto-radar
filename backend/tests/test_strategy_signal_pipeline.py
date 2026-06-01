import unittest

from app.schemas.market import Features
from app.schemas.trade_plan import TradePlan, TradePlanEntry, TradePlanTarget
from app.strategies.breakout import VolatilitySqueezeBreakoutStrategy
from app.strategies.common import build_signal, score_breakdown
from app.strategies.engine import StrategyEngine
from app.strategies.liquidity_sweep import LiquiditySweepReversalStrategy
from app.strategies.pipeline import MarketQualityInput, StrategyEvaluationContext, StrategySignalPipeline
from app.strategies.trend_pullback import TrendPullbackContinuationStrategy
from app.services.support_resistance import SupportResistanceLevel, SupportResistanceSnapshot


class StrategySignalPipelineTest(unittest.IsolatedAsyncioTestCase):
    def test_strategy_signal_has_trade_plan_from_legacy_fields(self) -> None:
        features = _breakout_features()

        signal = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=20,
                risk_reward_score=15,
            ),
            reasons=["Breakout setup"],
            entry=features.close,
            stop_loss=100.2,
            take_profit_1=102.2,
            take_profit_2=104.2,
        )

        self.assertIsNotNone(signal.trade_plan)
        self.assertEqual(signal.trade_plan.entry.min_price if signal.trade_plan else None, signal.entry_min)
        self.assertEqual(signal.trade_plan.entry.max_price if signal.trade_plan else None, signal.entry_max)
        self.assertEqual(signal.trade_plan.stop_loss if signal.trade_plan else None, signal.stop_loss)
        self.assertEqual(
            [target.price for target in signal.trade_plan.targets] if signal.trade_plan else [],
            [signal.take_profit_1, signal.take_profit_2],
        )

    def test_pipeline_creates_trade_plan_when_missing(self) -> None:
        features = _breakout_features()
        candidate = _quality_candidate(features).model_copy(update={"trade_plan": None})

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertIsNotNone(signal.trade_plan if signal else None)
        self.assertEqual(signal.trade_plan.stop_loss if signal and signal.trade_plan else None, signal.stop_loss)
        self.assertEqual(
            [target.label for target in signal.trade_plan.targets[:2]] if signal and signal.trade_plan else [],
            ["TP1", "TP2"],
        )
        self.assertEqual(signal.trade_plan.targets[0].action if signal and signal.trade_plan else None, "partial_close")

    def test_pipeline_enriches_existing_trade_plan_targets(self) -> None:
        features = _breakout_features()
        candidate = _quality_candidate(features).model_copy(
            update={
                "trade_plan": TradePlan(
                    entry=TradePlanEntry(
                        price=features.close,
                        min_price=features.close,
                        max_price=features.close,
                        source="test",
                    ),
                    stop_loss=features.close - 1.0,
                    targets=[
                        TradePlanTarget(label="TP1", price=features.close + 2.0, source="test"),
                        TradePlanTarget(label="TP2", price=features.close + 3.0, source="test"),
                    ],
                )
            }
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertIsNotNone(signal.trade_plan if signal else None)
        targets = signal.trade_plan.targets if signal and signal.trade_plan else []
        self.assertEqual(targets[0].action, "partial_close")
        self.assertEqual(targets[0].close_percent, 40)
        self.assertEqual(targets[-1].source, "range_measured_move")

    async def test_breakout_signal_is_enriched_with_six_layers(self) -> None:
        signals = await StrategyEngine().generate_signals(
            _breakout_features(),
            context_features=_bullish_context_features(),
        )

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.strategy, "volatility_squeeze_breakout")
        self.assertEqual(signal.status, "actionable")
        self.assertIsNotNone(signal.status_reason)
        self.assertIsNotNone(signal.quality)
        self.assertIsNotNone(signal.regime)
        self.assertIsNotNone(signal.setup)
        self.assertIsNotNone(signal.confirmation)
        self.assertIsNotNone(signal.invalidation)
        self.assertIsNotNone(signal.exit_plan)
        self.assertEqual(signal.invalidation.metadata.get("breakout_level") if signal.invalidation else None, 100.8)
        self.assertEqual(signal.invalidation.metadata.get("signal_open") if signal.invalidation else None, 100.6)
        self.assertEqual(signal.invalidation.metadata.get("conservative_entry") if signal.invalidation else None, 100.8)
        self.assertEqual(signal.exit_plan.targets[-1].get("source") if signal.exit_plan else None, "range_measured_move")
        measured_targets = [
            target for target in (signal.trade_plan.targets if signal.trade_plan else [])
            if target.source == "range_measured_move"
        ]
        self.assertEqual(len(measured_targets), 1)
        self.assertAlmostEqual(measured_targets[0].price or 0, 105.4)
        self.assertAlmostEqual(signal.first_target_rr or 0, 1.5)
        self.assertAlmostEqual(signal.final_target_rr or 0, 2.5)
        self.assertEqual(signal.regime.context_timeframe if signal.regime else None, "1h")
        self.assertEqual(signal.regime.alignment if signal.regime else None, "aligned")
        self.assertTrue(signal.explanation[0].startswith("Status:"))

    async def test_overextended_signal_waits_for_pullback(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 103.0,
                "open": 100.0,
                "high": 103.4,
                "low": 99.8,
                "close": 103.0,
                "donchian_high_20": 102.0,
                "donchian_low_20": 98.0,
                "range_20": 4.0,
                "range_20_atr": 4.0,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
        )

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.status, "wait_for_pullback")
        self.assertIn("ATR", signal.status_reason or "")
        self.assertIsNotNone(signal.invalidation)
        self.assertGreaterEqual(len(signal.exit_plan.targets if signal.exit_plan else []), 1)

    async def test_impulse_breakout_below_static_limit_still_waits_for_pullback(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 102.35,
                "open": 100.0,
                "high": 102.4,
                "low": 100.0,
                "close": 102.35,
                "volume_spike": 2.8,
                "donchian_high_20": 101.0,
                "upper_wick_ratio": 0.02,
                "lower_wick_ratio": 0.0,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
        )

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.status, "wait_for_pullback")
        self.assertIn("dynamic limit", signal.status_reason or "")
        self.assertIn("breakout level", signal.status_reason or "")
        overextension_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "overextension_guard"
        )
        self.assertEqual(overextension_check.metadata.get("pullback_target_source"), "breakout_level")
        self.assertAlmostEqual(overextension_check.metadata.get("pullback_target_price"), 101.0)
        self.assertIsNotNone(signal.entry_min)
        self.assertIsNotNone(signal.entry_max)
        self.assertLess(signal.entry_min or 0, 101.0)
        self.assertGreater(signal.entry_max or 0, 101.0)

    async def test_rejection_wick_waits_for_fresh_reclaim(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 101.4,
                "open": 100.9,
                "high": 104.2,
                "low": 100.8,
                "close": 101.4,
                "donchian_high_20": 100.8,
                "volume_spike": 1.9,
                "upper_wick_ratio": 0.82,
                "lower_wick_ratio": 0.03,
                "swing_high": 110.0,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
        )

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.status, "wait_for_pullback")
        self.assertIn("rejection wick", signal.status_reason or "")

    async def test_liquidity_sweep_absorption_wick_is_not_fomo_overextension(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 98.8,
                "open": 99.2,
                "high": 100.5,
                "low": 96.2,
                "close": 98.8,
                "swing_low": 98.0,
                "lower_wick_ratio": 0.6,
                "upper_wick_ratio": 0.3,
                "volume_spike": 1.8,
            }
        )
        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                pair_scope_configured=True,
                strategy_params={"min_rr_ratio": 1.5, "rr_target": "final"},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "actionable")
        self.assertNotIn("wait for pullback", signal.status_reason or "")

    async def test_liquidity_sweep_current_reclaim_scores_level_quality(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 98.8,
                "open": 99.2,
                "high": 100.5,
                "low": 96.2,
                "close": 98.8,
                "swing_low": 98.0,
                "swing_low_touch_count": 3,
                "swing_low_volume_score": 1.4,
                "lower_wick_ratio": 0.6,
                "upper_wick_ratio": 0.3,
                "volume_spike": 1.8,
            }
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "actionable")
        self.assertGreaterEqual(candidates[0].score, 80)
        self.assertIn("recent touches", " ".join(candidates[0].explanation))

    async def test_liquidity_sweep_confirmation_candle_can_be_actionable(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 99.3,
                "open": 98.7,
                "high": 99.5,
                "low": 98.4,
                "close": 99.3,
                "previous_high": 99.0,
                "previous_low": 96.8,
                "previous_close": 98.3,
                "swing_low": 98.0,
                "swing_low_touch_count": 2,
                "volume_spike": 1.2,
                "lower_wick_ratio": 0.2,
            }
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "actionable")
        self.assertIn("Conservative confirmation", " ".join(candidates[0].explanation))

    async def test_liquidity_sweep_breakout_continuation_is_hidden(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 94.9,
                "open": 95.4,
                "high": 95.7,
                "low": 94.8,
                "close": 94.9,
                "previous_low": 95.4,
                "previous_close": 95.7,
                "swing_low": 96.0,
                "lower_wick_ratio": 0.2,
                "volume_spike": 1.9,
            }
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        self.assertEqual(candidates, [])

    def test_strategy_pipeline_warns_on_low_rr_without_blocking_discovery_by_default(self) -> None:
        features = _breakout_features()
        candidate = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=20,
                risk_reward_score=1,
            ),
            reasons=["Breakout setup is classified by strategy layer"],
            entry=features.close,
            stop_loss=100.7,
            take_profit_1=101.4,
            take_profit_2=101.5,
        ).model_copy(update={"risk_reward": 0.8})

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "actionable")
        self.assertNotIn("Risk/reward blocked", signal.status_reason or "")
        self.assertIn("configured minimum", " ".join(signal.risks if signal else []))
        self.assertIsNone(signal.auto_entry)
        rr_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "risk_reward_guard"
        )
        self.assertEqual(rr_check.status, "warning")
        self.assertEqual(rr_check.metadata.get("risk_reward_guard_mode"), "soft")
        self.assertTrue(rr_check.metadata.get("risk_reward_warning"))
        self.assertFalse(rr_check.metadata.get("risk_reward_blocked"))
        self.assertIn("Risk/reward warning", rr_check.metadata.get("risk_reward_warning_reason", ""))

    def test_strategy_pipeline_hard_rr_guard_blocks_actionable_status(self) -> None:
        features = _breakout_features()
        candidate = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=20,
                risk_reward_score=1,
            ),
            reasons=["Breakout setup is classified by strategy layer"],
            entry=features.close,
            stop_loss=100.7,
            take_profit_1=101.4,
            take_profit_2=101.5,
        ).model_copy(update={"risk_reward": 0.8})

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"rr_guard_mode": "hard"},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "ready")
        self.assertIn("Risk/reward blocked", signal.status_reason or "")
        self.assertIsNotNone(signal.auto_entry)
        rr_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "risk_reward_guard"
        )
        self.assertEqual(rr_check.status, "failed")
        self.assertEqual(rr_check.metadata.get("risk_reward_guard_mode"), "hard")
        self.assertTrue(rr_check.metadata.get("risk_reward_blocked"))

    def test_risk_reward_guard_exposes_first_final_and_selected_rr(self) -> None:
        features = _breakout_features()
        candidate = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=20,
                risk_reward_score=15,
            ),
            reasons=["Breakout setup is classified by strategy layer"],
            entry=features.close,
            stop_loss=100.2,
            take_profit_1=102.2,
            take_profit_2=104.2,
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                strategy_params={"min_rr_ratio": 1.5, "rr_target": "final"},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.selected_rr_target, "final")
        self.assertEqual(
            signal.trade_plan.risk_rules.selected_rr_target if signal.trade_plan else None,
            "final",
        )
        self.assertAlmostEqual(signal.first_target_rr or 0, 1.0)
        self.assertAlmostEqual(signal.final_target_rr or 0, 3.0)
        self.assertAlmostEqual(signal.selected_rr or 0, 3.0)
        rr_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "risk_reward_guard"
        )
        self.assertEqual(rr_check.metadata.get("selected_rr_target"), "final")
        self.assertAlmostEqual(rr_check.metadata.get("first_target_rr"), 1.0)
        self.assertAlmostEqual(rr_check.metadata.get("final_target_rr"), 3.0)

    def test_sweep_defaults_to_nearest_rr_target(self) -> None:
        features = _breakout_features()
        candidate = build_signal(
            features=features,
            strategy="liquidity_sweep_reversal",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=15,
                risk_reward_score=15,
            ),
            reasons=["Liquidity sweep setup is classified by strategy layer"],
            entry=features.close,
            stop_loss=100.2,
            take_profit_1=102.2,
            take_profit_2=104.2,
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "actionable")
        self.assertEqual(signal.selected_rr_target, "nearest")
        self.assertEqual(
            signal.trade_plan.risk_rules.selected_rr_target if signal.trade_plan else None,
            "nearest",
        )
        self.assertAlmostEqual(signal.first_target_rr or 0, 1.0)
        self.assertAlmostEqual(signal.final_target_rr or 0, 3.0)
        self.assertAlmostEqual(signal.selected_rr or 0, 1.0)
        rr_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "risk_reward_guard"
        )
        self.assertEqual(rr_check.status, "warning")
        self.assertIn("nearest target", rr_check.reason or "")

    def test_sweep_ignores_nearest_target_that_is_behind_entry(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 82.63,
                "price": 82.63,
                "open": 82.63,
                "high": 82.64,
                "low": 82.62,
                "swing_high": 82.66,
                "swing_low": 82.62,
                "atr_14": 0.21,
            }
        )
        candidate = build_signal(
            features=features,
            strategy="liquidity_sweep_reversal",
            direction="SHORT",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                liquidity_score=15,
                risk_reward_score=15,
            ),
            reasons=["Liquidity sweep short setup"],
            entry=82.63,
            stop_loss=82.66078571,
            take_profit_1=82.64,
            take_profit_2=82.62,
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertIsNone(signal.first_target_rr)
        self.assertAlmostEqual(signal.final_target_rr or 0, 0.3248)
        self.assertAlmostEqual(signal.selected_rr or 0, 0.3248)
        rr_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "risk_reward_guard"
        )
        self.assertEqual(rr_check.status, "warning")
        self.assertIn("nearest valid target", rr_check.reason or "")
        self.assertIn("TP1 not beyond entry", rr_check.reason or "")
        self.assertEqual([target.get("label") for target in signal.exit_plan.targets[:1]] if signal and signal.exit_plan else [], ["TP2"])

    def test_short_signal_reward_is_directional_not_absolute(self) -> None:
        features = _breakout_features().model_copy(update={"close": 100.0, "price": 100.0})
        candidate = build_signal(
            features=features,
            strategy="liquidity_sweep_reversal",
            direction="SHORT",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                liquidity_score=15,
            ),
            reasons=["Liquidity sweep short setup"],
            entry=100.0,
            stop_loss=101.0,
            take_profit_1=100.5,
            take_profit_2=100.5,
        )

        self.assertEqual(candidate.risk_reward, 0)
        self.assertEqual(candidate.score_breakdown.risk_reward_score, 0)

    def test_strategy_pipeline_can_hide_low_rr_cards_by_strategy_setting(self) -> None:
        features = _breakout_features()
        candidate = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=20,
                risk_reward_score=1,
            ),
            reasons=["Breakout setup is classified by strategy layer"],
            entry=features.close,
            stop_loss=100.7,
            take_profit_1=101.4,
            take_profit_2=101.5,
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"hide_failed_rr_signals": True, "rr_guard_mode": "hard"},
            ),
        )

        self.assertIsNone(signal)

    def test_strategy_pipeline_can_show_only_active_setups_by_strategy_setting(self) -> None:
        features = _breakout_features()
        candidate = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=25,
                volume_score=20,
                liquidity_score=15,
                orderbook_score=10,
                risk_reward_score=15,
                volatility_score=15,
            ),
            reasons=["Breakout setup is still forming"],
            entry=features.close,
            stop_loss=100.0,
            take_profit_1=104.0,
            take_profit_2=106.0,
        ).model_copy(update={"status": "watchlist"})

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"show_only_active_setups": True},
            ),
        )

        self.assertIsNone(signal)

    def test_market_quality_blocks_low_liquidity_in_all_pairs_scope(self) -> None:
        features = _breakout_features().model_copy(update={"symbol": "1000PEPEUSDT"})

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(signal_features=features),
        )

        self.assertIsNone(signal)

    def test_manual_pair_scope_bypasses_market_quality_exclusion(self) -> None:
        features = _breakout_features().model_copy(update={"symbol": "1000PEPEUSDT"})

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                market_quality=MarketQualityInput(volume_24h_quote=100_000.0, spread_bps=120.0),
                pair_scope_configured=True,
            ),
        )

        self.assertIsNotNone(signal)
        self.assertTrue(signal.quality.passed if signal and signal.quality else False)
        self.assertIn("Low-liquidity asset is allowed", " ".join(signal.risks if signal else []))

    def test_market_quality_blocks_bad_mid_alt_in_all_pairs_scope(self) -> None:
        features = _breakout_features().model_copy(update={"symbol": "AVAXUSDT"})

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                market_quality=MarketQualityInput(volume_24h_quote=100_000.0, spread_bps=120.0),
            ),
        )

        self.assertIsNone(signal)

    def test_no_trade_high_spread_disables_auto_entry(self) -> None:
        features = _breakout_features()

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                market_quality=MarketQualityInput(volume_24h_quote=50_000_000.0, spread_bps=84.0),
                strategy_params={
                    "no_trade_filters_enabled": True,
                    "max_spread_bps_for_entry": 25.0,
                    "min_rr_ratio": 1.5,
                    "rr_target": "final",
                },
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "ready")
        self.assertIn("No-trade hard block", signal.status_reason or "")
        self.assertTrue(signal.no_trade_filter.blocked if signal and signal.no_trade_filter else False)
        self.assertIn("high_spread", signal.no_trade_filter.metadata.get("blocker_codes") if signal and signal.no_trade_filter else [])
        self.assertFalse(signal.auto_entry.enabled if signal and signal.auto_entry else True)
        self.assertEqual(signal.auto_entry.status if signal and signal.auto_entry else None, "cancelled")
        self.assertTrue(
            any(
                check.name == "no_trade_filter" and check.status == "failed"
                for check in (signal.confirmation.checks if signal and signal.confirmation else [])
            )
        )

    async def test_squeeze_pre_breakout_is_watchlist(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.5,
                "price": 100.5,
                "high": 100.7,
                "donchian_high_20": 100.8,
            }
        )
        candidates = await VolatilitySqueezeBreakoutStrategy().evaluate(features)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "watchlist")
        self.assertEqual(signal.setup.stage if signal and signal.setup else None, "forming")
        self.assertIn("waiting for breakout volume", signal.status_reason or "")

    async def test_squeeze_breakout_without_volume_confirmation_is_ready(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "volume_spike": 1.4,
                "atr_increasing": True,
            }
        )
        candidates = await VolatilitySqueezeBreakoutStrategy().evaluate(features)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "ready")
        self.assertEqual(signal.setup.stage if signal and signal.setup else None, "ready")

    async def test_squeeze_breakout_requires_full_compression(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "atr_sma_50": 0.8,
                "range_20": 5.0,
                "range_50_average": 4.0,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
        )

        self.assertEqual(signals, [])

    async def test_squeeze_breakout_weak_close_stays_ready(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "open": 100.9,
                "high": 103.2,
                "low": 100.7,
                "close": 101.1,
                "price": 101.1,
                "upper_wick_ratio": 0.84,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].status, "ready")
        self.assertIn("close strength", signals[0].status_reason or "")

    async def test_breakout_large_candle_chooses_retest_wait(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "open": 100.0,
                "high": 103.4,
                "low": 99.8,
                "close": 103.1,
                "price": 103.1,
                "volume_spike": 2.2,
            }
        )

        candidates = await VolatilitySqueezeBreakoutStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "wait_for_pullback")
        self.assertIn("conservative retest", candidates[0].status_reason or "")
        self.assertEqual(candidates[0].trade_plan.entry.source if candidates[0].trade_plan else None, "conservative_retest")

    async def test_squeeze_settings_can_raise_volume_confirmation_threshold(self) -> None:
        features = _breakout_features()

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
            strategy_configs={
                "volatility_squeeze_breakout": type(
                    "RuntimeConfig",
                    (),
                    {
                        "params": {"volume_spike_multiplier": 2.0},
                        "risk_settings": {"min_rr_ratio": 1.5, "rr_target": "final"},
                        "pair_scope_configured": False,
                    },
                )(),
            },
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].status, "ready")
        self.assertIn("volume", signals[0].status_reason or "")

    async def test_squeeze_breakout_records_oi_expansion_when_available(self) -> None:
        features = _breakout_features().model_copy(update={"oi_change": 0.03})

        candidates = await VolatilitySqueezeBreakoutStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertIn("Open interest expanded", " ".join(candidates[0].explanation))

    async def test_trend_pullback_approach_is_watchlist(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.8,
                "price": 100.8,
                "high": 101.0,
                "low": 100.6,
                "history_length": 220,
                "candle_bullish": False,
            }
        )
        candidates = await TrendPullbackContinuationStrategy().evaluate(features)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "watchlist")
        self.assertEqual(signal.setup.stage if signal and signal.setup else None, "forming")

    async def test_trend_pullback_trigger_is_actionable_after_healthy_pullback(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.6,
                "price": 100.6,
                "open": 100.1,
                "high": 100.8,
                "low": 99.8,
                "ema_20": 100.0,
                "ema_50": 98.8,
                "ema_200": 95.0,
                "rsi_14": 50.0,
                "volume_spike": 1.2,
                "volume_ma_20": 70.0,
                "previous_high": 100.5,
                "previous_volume": 60.0,
                "history_length": 220,
                "candle_bullish": True,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
        )

        trend_signal = next(signal for signal in signals if signal.strategy == "trend_pullback_continuation")
        self.assertEqual(trend_signal.status, "actionable")
        self.assertLess(trend_signal.entry_min or 0, 100.0)
        self.assertGreater(trend_signal.entry_max or 0, 100.0)
        self.assertEqual(trend_signal.trade_plan.entry.source if trend_signal.trade_plan else None, "ema20_ema50_pullback_zone")
        self.assertEqual(
            trend_signal.trade_plan.risk_rules.metadata.get("time_stop_bars") if trend_signal.trade_plan else None,
            8,
        )
        self.assertGreaterEqual(trend_signal.score, 75)
        self.assertEqual(trend_signal.exit_plan.trailing.get("source") if trend_signal.exit_plan else None, "EMA20")

    async def test_trend_pullback_actionable_with_required_htf_alignment(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.6,
                "price": 100.6,
                "open": 100.1,
                "high": 100.8,
                "low": 99.8,
                "ema_20": 100.0,
                "ema_50": 98.8,
                "ema_200": 95.0,
                "rsi_14": 50.0,
                "volume_spike": 1.2,
                "previous_high": 100.5,
                "previous_volume": 60.0,
                "history_length": 220,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
            strategy_configs={
                "trend_pullback_continuation": type(
                    "RuntimeConfig",
                    (),
                    {
                        "params": {"require_htf_alignment": True},
                        "risk_settings": {"min_rr_ratio": 1.5, "rr_target": "final"},
                        "pair_scope_configured": False,
                    },
                )(),
            },
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].status, "actionable")
        self.assertEqual(signals[0].regime.alignment if signals[0].regime else None, "aligned")

    async def test_trend_pullback_far_from_ema_waits_for_new_pullback(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 102.0,
                "price": 102.0,
                "open": 101.2,
                "high": 102.2,
                "low": 101.0,
                "ema_20": 100.0,
                "ema_50": 98.8,
                "ema_200": 95.0,
                "rsi_14": 58.0,
                "history_length": 220,
            }
        )

        candidates = await TrendPullbackContinuationStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "wait_for_pullback")
        self.assertIn("entry is late", candidates[0].status_reason or "")
        self.assertEqual(candidates[0].trade_plan.entry.source if candidates[0].trade_plan else None, "ema20_ema50_pullback_zone")

    async def test_trend_pullback_blocks_extreme_positive_funding_for_long(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.6,
                "price": 100.6,
                "open": 100.1,
                "high": 100.8,
                "low": 99.8,
                "ema_20": 100.0,
                "ema_50": 98.8,
                "ema_200": 95.0,
                "rsi_14": 50.0,
                "volume_spike": 1.2,
                "previous_high": 100.5,
                "previous_volume": 60.0,
                "funding_rate": 0.0016,
                "history_length": 220,
            }
        )

        candidates = await TrendPullbackContinuationStrategy().evaluate(features)

        self.assertEqual(candidates, [])

    async def test_trend_pullback_penalizes_extreme_funding_with_crowded_oi(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.6,
                "price": 100.6,
                "open": 100.1,
                "high": 100.8,
                "low": 99.8,
                "ema_20": 100.0,
                "ema_50": 98.8,
                "ema_200": 95.0,
                "rsi_14": 50.0,
                "volume_spike": 1.2,
                "previous_high": 100.5,
                "previous_volume": 60.0,
                "funding_rate": 0.0016,
                "oi_change": 0.03,
                "history_length": 220,
            }
        )

        candidates = await TrendPullbackContinuationStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertIn("crowded open interest", " ".join(candidates[0].risks))

    async def test_strategies_accept_missing_oi_context(self) -> None:
        features = _breakout_features().model_copy(update={"history_length": 220, "oi_change": None})

        for strategy in (
            VolatilitySqueezeBreakoutStrategy(),
            LiquiditySweepReversalStrategy(),
            TrendPullbackContinuationStrategy(),
        ):
            candidates = await strategy.evaluate(features)
            self.assertIsInstance(candidates, list)

    async def test_liquidity_sweep_without_reclaim_is_ready(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 95.5,
                "price": 95.5,
                "open": 96.4,
                "low": 95.0,
                "high": 96.8,
                "swing_low": 96.0,
                "lower_wick_ratio": 0.5,
                "volume_spike": 1.8,
            }
        )
        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "ready")
        self.assertIn("waiting for reclaim", signal.status_reason or "")

    async def test_liquidity_sweep_targets_midpoint_and_opposite_boundary(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 98.8,
                "open": 99.2,
                "high": 100.5,
                "low": 96.2,
                "close": 98.8,
                "swing_low": 98.0,
                "swing_high": 104.0,
                "lower_wick_ratio": 0.6,
                "upper_wick_ratio": 0.3,
                "volume_spike": 1.8,
            }
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        targets = candidates[0].trade_plan.targets if candidates[0].trade_plan else []
        self.assertEqual(targets[0].source, "range_midpoint")
        self.assertEqual(targets[1].source, "swing_high")
        self.assertAlmostEqual(targets[0].price or 0, 101.0)
        self.assertAlmostEqual(targets[1].price or 0, 104.0)

    async def test_liquidity_sweep_records_oi_flush_when_available(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 98.8,
                "open": 99.2,
                "high": 100.5,
                "low": 96.2,
                "close": 98.8,
                "swing_low": 98.0,
                "lower_wick_ratio": 0.6,
                "upper_wick_ratio": 0.3,
                "volume_spike": 1.8,
                "oi_change": -0.04,
            }
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertIn("Open interest flushed", " ".join(candidates[0].explanation))

    async def test_liquidity_sweep_blocks_against_strong_trend_without_confirmation(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 98.2,
                "open": 98.1,
                "high": 98.6,
                "low": 95.5,
                "close": 98.2,
                "swing_low": 96.0,
                "ema_50": 98.0,
                "ema_200": 100.0,
                "adx": 36.0,
                "lower_wick_ratio": 0.25,
                "upper_wick_ratio": 0.1,
                "volume_spike": 1.0,
            }
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        self.assertEqual(candidates, [])

    async def test_liquidity_sweep_gets_higher_timeframe_level_confluence(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 98.8,
                "open": 99.2,
                "high": 100.5,
                "low": 96.2,
                "close": 98.8,
                "swing_low": 98.0,
                "swing_low_touch_count": 2,
                "lower_wick_ratio": 0.6,
                "upper_wick_ratio": 0.3,
                "volume_spike": 1.8,
            }
        )
        support = SupportResistanceLevel(
            kind="support",
            price=98.1,
            retest_count=3,
            age_candles=5,
            first_seen_index=10,
            last_seen_index=45,
            volume_score=1.6,
            freshness_score=0.9,
            strength=82.0,
        )
        snapshot = SupportResistanceSnapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            atr=2.0,
            levels=(support,),
        )
        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                support_resistance_by_timeframe={"1h": snapshot},
                pair_scope_configured=True,
                strategy_params={"min_rr_ratio": 1.5, "rr_target": "final"},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertTrue(
            any(
                check.name == "sweep_htf_level_confluence" and check.status == "passed"
                for check in (signal.regime.checks if signal and signal.regime else [])
            )
        )
        self.assertEqual(signal.exit_plan.targets[-1].get("source") if signal and signal.exit_plan else None, "micro_BOS_or_ATR_trailing")

    def test_pipeline_preserves_invalidated_strategy_stage(self) -> None:
        features = _breakout_features()
        candidate = _quality_candidate(features).model_copy(
            update={"status": "invalidated", "status_reason": "Breakout returned inside the previous range"}
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "invalidated")
        self.assertIn("previous range", signal.status_reason or "")

    def test_strong_higher_timeframe_against_signal_becomes_watchlist(self) -> None:
        features = _breakout_features()

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bearish_context_features(),
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "watchlist")
        self.assertLess(signal.regime.score_adjustment if signal and signal.regime else 0, 0)
        self.assertIn("higher-timeframe", " ".join(signal.risks if signal else []))

    def test_aligned_higher_timeframe_adds_score(self) -> None:
        features = _breakout_features().model_copy(update={"history_length": 220})
        candidate = build_signal(
            features=features,
            strategy="trend_pullback_continuation",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=10,
                risk_reward_score=10,
            ),
            reasons=["Trend pullback setup"],
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.regime.alignment if signal and signal.regime else None, "aligned")
        self.assertGreater(signal.score if signal else 0, candidate.score)

    def test_trend_pullback_severe_ema200_chop_is_hidden(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "history_length": 260,
                "ema_200_chop_score": 78.0,
                "ema_200_cross_count_50": 4,
                "ema_200_near_ratio_50": 0.4,
                "ema_200_slope_atr_20": 0.1,
            }
        )
        candidate = build_signal(
            features=features,
            strategy="trend_pullback_continuation",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=45,
                volume_score=15,
                volatility_score=15,
                risk_reward_score=15,
            ),
            reasons=["Trend pullback setup"],
            entry=features.close,
            stop_loss=features.close - 1.0,
            take_profit_1=features.close + 1.0,
            take_profit_2=features.close + 2.0,
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(signal_features=features),
        )

        self.assertIsNone(signal)

    def test_trend_pullback_borderline_ema200_chop_becomes_watchlist(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "history_length": 260,
                "ema_200_chop_score": 52.0,
                "ema_200_cross_count_50": 3,
                "ema_200_near_ratio_50": 0.32,
                "ema_200_slope_atr_20": 0.2,
            }
        )
        candidate = build_signal(
            features=features,
            strategy="trend_pullback_continuation",
            direction="LONG",
            scoring=score_breakdown(
                trend_score=45,
                volume_score=15,
                volatility_score=15,
                risk_reward_score=15,
            ),
            reasons=["Trend pullback setup"],
            entry=features.close,
            stop_loss=features.close - 1.0,
            take_profit_1=features.close + 1.0,
            take_profit_2=features.close + 2.0,
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(signal_features=features),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "watchlist")
        self.assertLess(signal.score if signal else 100, candidate.score)
        self.assertTrue(
            any(check.name == "ema200_chop" and check.status == "warning" for check in (signal.regime.checks if signal and signal.regime else []))
        )

    def test_breakout_near_context_resistance_is_not_actionable(self) -> None:
        features = _breakout_features()
        context = _bullish_context_features().model_copy(
            update={
                "swing_high": 101.6,
                "donchian_high_20": 101.6,
            }
        )

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(signal_features=features, context_features=context),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "ready")
        self.assertTrue(
            any(
                check.name == "context_resistance" and check.status == "warning"
                for check in (signal.regime.checks if signal and signal.regime else [])
            )
        )

    def test_breakout_uses_support_resistance_snapshot_for_context_obstacle(self) -> None:
        features = _breakout_features()
        context = _bullish_context_features().model_copy(
            update={
                "swing_high": 110.0,
                "donchian_high_20": 112.0,
            }
        )
        resistance = SupportResistanceLevel(
            kind="resistance",
            price=101.55,
            retest_count=3,
            age_candles=4,
            first_seen_index=10,
            last_seen_index=46,
            volume_score=1.4,
            freshness_score=0.9,
            strength=78.0,
        )
        snapshot = SupportResistanceSnapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            atr=2.0,
            levels=(resistance,),
        )

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=context,
                support_resistance_by_timeframe={"1h": snapshot},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "ready")
        self.assertTrue(
            any(
                check.name == "context_resistance"
                and check.status == "warning"
                and "S/R resistance" in (check.reason or "")
                for check in (signal.regime.checks if signal and signal.regime else [])
            )
        )

    def test_context_timeframe_can_be_overridden_per_strategy(self) -> None:
        features = _breakout_features()
        default_context = _bearish_context_features()
        override_context = _bullish_context_features().model_copy(update={"timeframe": "4h"})

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=default_context,
                context_features_by_timeframe={"1h": default_context, "4h": override_context},
                strategy_params={"context_timeframe_map": {"15m": "4h"}},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.regime.context_timeframe if signal and signal.regime else None, "4h")
        self.assertEqual(signal.regime.alignment if signal and signal.regime else None, "aligned")

    def test_macro_context_can_block_liquidity_sweep_countertrend_short(self) -> None:
        features = _breakout_features()
        primary = _bearish_context_features()
        macro = _bullish_context_features().model_copy(update={"timeframe": "4h"})
        candidate = build_signal(
            features=features,
            strategy="liquidity_sweep_reversal",
            direction="SHORT",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=15,
                risk_reward_score=15,
            ),
            reasons=["Liquidity sweep short setup"],
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=primary,
                context_features_by_timeframe={"1h": primary, "4h": macro},
                strategy_params={"rr_target": "final"},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "watchlist")
        self.assertTrue(
            any(
                check.name == "macro_regime_alignment" and check.status == "warning"
                for check in (signal.regime.checks if signal and signal.regime else [])
            )
        )


def _breakout_features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=1_779_796_800_000,
        price=101.2,
        open=100.6,
        high=101.5,
        low=100.2,
        close=101.2,
        price_change_1m=0.01,
        volume=120.0,
        volume_spike=1.8,
        volume_ma_20=70.0,
        volatility=1.2,
        history_length=120,
        ema_20=99.4,
        ema_50=98.0,
        ema_200=95.0,
        rsi_14=60.0,
        atr_14=1.0,
        atr_sma_50=1.3,
        adx=28.0,
        adx_rising=True,
        bb_width_percentile=12.0,
        donchian_high_20=100.8,
        donchian_low_20=96.2,
        range_20=4.6,
        range_50_average=6.0,
        range_20_atr=4.6,
        swing_high=104.0,
        swing_low=96.0,
        candle_bullish=True,
        upper_wick_ratio=0.1,
        lower_wick_ratio=0.2,
        atr_increasing=True,
    )


def _bullish_context_features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=1_779_796_800_000,
        price=105.0,
        open=103.0,
        high=106.0,
        low=102.0,
        close=105.0,
        price_change_1m=0.01,
        volume=500.0,
        volume_spike=1.3,
        volume_ma_20=420.0,
        volatility=2.0,
        history_length=220,
        ema_20=104.0,
        ema_50=103.0,
        ema_200=100.0,
        rsi_14=61.0,
        atr_14=2.0,
        adx=35.0,
        adx_rising=True,
        candle_bullish=True,
    )


def _bearish_context_features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=1_779_796_800_000,
        price=95.0,
        open=97.0,
        high=98.0,
        low=94.0,
        close=95.0,
        price_change_1m=-0.01,
        volume=500.0,
        volume_spike=1.3,
        volume_ma_20=420.0,
        volatility=2.0,
        history_length=220,
        ema_20=96.0,
        ema_50=97.0,
        ema_200=100.0,
        rsi_14=39.0,
        atr_14=2.0,
        adx=35.0,
        adx_rising=True,
        candle_bullish=False,
    )


def _quality_candidate(features: Features):
    return build_signal(
        features=features,
        strategy="volatility_squeeze_breakout",
        direction="LONG",
        scoring=score_breakdown(
            trend_score=35,
            volume_score=20,
            volatility_score=20,
            risk_reward_score=15,
        ),
        reasons=["Quality filter test setup"],
        entry=features.close,
        stop_loss=features.close - 1.0,
        take_profit_1=features.close + 2.0,
        take_profit_2=features.close + 3.0,
    )


if __name__ == "__main__":
    unittest.main()
