import unittest
from inspect import signature

from app.schemas.market import AlphaMarketContext, DeltaDivergence, Features
from app.schemas.signal import (
    MarketQualitySnapshot,
    MarketRegimeSnapshot,
    NoTradeFilterResult,
    SignalConfirmationSnapshot,
    SignalExitPlanSnapshot,
    SignalInvalidationSnapshot,
    StrategySetupSnapshot,
)
from app.schemas.trade_plan import TradePlan, TradePlanCompletenessResult, TradePlanEntry, TradePlanTarget
from app.services.auto_entry_eligibility import AutoEntryEligibilityService
from app.services.risk_reward_assessment import RiskRewardAssessmentService
from app.services.market_regime import MarketWideRegimeContext
from app.services.signal_status_resolver import SignalStatusResolver
from app.services.trade_plan_enrichment import TradePlanEnrichmentService
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

    def test_pipeline_attaches_market_target_thesis_to_legacy_targets(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "previous_day_high": _breakout_features().close + 2.0,
                "session_high": _breakout_features().close + 4.0,
            }
        )

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        targets = signal.trade_plan.targets if signal and signal.trade_plan else []
        self.assertIsNotNone(targets[0].thesis)
        self.assertEqual(targets[0].thesis.source if targets[0].thesis else None, "previous_day_high")
        self.assertEqual(targets[0].metadata.get("target_thesis_source"), "previous_day_high")

    def test_finalize_public_contract_is_preserved(self) -> None:
        method_signature = signature(StrategySignalPipeline.finalize)
        self.assertEqual(list(method_signature.parameters), ["self", "signal", "context"])

        features = _breakout_features()
        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.strategy if signal else None, "volatility_squeeze_breakout")
        self.assertIsNotNone(signal.trade_plan if signal else None)
        self.assertIsNotNone(signal.trigger if signal else None)
        self.assertTrue(signal.trigger.passed if signal and signal.trigger else False)

    def test_rr_assessment_service_matches_previous_rr_logic(self) -> None:
        features = _breakout_features()
        candidate = _quality_candidate(features)
        params = {"min_rr_ratio": 1.5, "rr_target": "final"}

        assessment = RiskRewardAssessmentService().assess(candidate, params)
        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params=params,
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.selected_rr_target if signal else None, assessment.target_key)
        self.assertAlmostEqual(signal.first_target_rr if signal and signal.first_target_rr else 0, assessment.first_target_rr or 0)
        self.assertAlmostEqual(signal.final_target_rr if signal and signal.final_target_rr else 0, assessment.final_target_rr or 0)
        self.assertAlmostEqual(signal.selected_rr if signal and signal.selected_rr else 0, assessment.rr or 0)
        rr_check = next(
            check
            for check in (signal.confirmation.checks if signal and signal.confirmation else [])
            if check.name == "risk_reward_guard"
        )
        self.assertEqual(rr_check.status, assessment.status)
        self.assertEqual(rr_check.reason, assessment.reason)
        self.assertEqual(rr_check.metadata.get("selected_rr_target"), assessment.target_key)

    def test_status_resolver_blocks_incomplete_trade_plan(self) -> None:
        features = _breakout_features()
        candidate = _quality_candidate(features)
        assert candidate.trade_plan is not None
        assessment = RiskRewardAssessmentService().assess(
            candidate,
            {"min_rr_ratio": 1.5, "rr_target": "final"},
        )

        decision = SignalStatusResolver().resolve(
            signal=candidate,
            params={},
            quality=MarketQualitySnapshot(passed=True, tier="major", score=100),
            regime=MarketRegimeSnapshot(alignment="aligned", strength="normal"),
            confirmation=SignalConfirmationSnapshot(passed=True),
            setup=StrategySetupSnapshot(name=candidate.strategy, stage="confirmed"),
            risk_reward=assessment,
            no_trade_filter=NoTradeFilterResult(enabled=True, blocked=False),
            completeness=TradePlanCompletenessResult(
                complete=False,
                missing=["structural_target"],
                warnings=["Trade plan is incomplete: structural_target."],
            ),
            trade_plan=candidate.trade_plan,
            candle_state="closed",
            production_mode=True,
            actionable_score=70,
        )

        self.assertEqual(decision.status, "watchlist")
        self.assertIn("Trade plan incomplete", decision.status_reason)
        self.assertFalse(decision.trade_plan.metadata.get("open_candle_preview"))

    def test_status_resolver_blocks_forming_candle(self) -> None:
        features = _breakout_features().model_copy(update={"candle_state": "open"})
        candidate = _quality_candidate(features).model_copy(update={"candle_state": "open"})
        assert candidate.trade_plan is not None
        assessment = RiskRewardAssessmentService().assess(
            candidate,
            {"min_rr_ratio": 1.5, "rr_target": "final"},
        )

        decision = SignalStatusResolver().resolve(
            signal=candidate,
            params={},
            quality=MarketQualitySnapshot(passed=True, tier="major", score=100),
            regime=MarketRegimeSnapshot(alignment="aligned", strength="normal"),
            confirmation=SignalConfirmationSnapshot(passed=True),
            setup=StrategySetupSnapshot(name=candidate.strategy, stage="confirmed"),
            risk_reward=assessment,
            no_trade_filter=NoTradeFilterResult(enabled=True, blocked=False),
            completeness=TradePlanCompletenessResult(complete=True),
            trade_plan=candidate.trade_plan,
            candle_state="open",
            production_mode=False,
            actionable_score=70,
        )

        self.assertEqual(decision.status, "watchlist")
        self.assertIn("forming_candle", decision.status_reason)
        self.assertEqual(decision.actionability_block_reason, "forming_candle")
        self.assertEqual(decision.setup.stage, "forming")
        candle_check = next(check for check in decision.confirmation.checks if check.name == "candle_state_gate")
        self.assertEqual(candle_check.status, "warning")
        self.assertFalse(decision.trade_plan.metadata.get("signal_actionable"))

    def test_auto_entry_service_disabled_on_no_trade_or_incomplete(self) -> None:
        features = _breakout_features()
        candidate = _quality_candidate(features)
        assessment = RiskRewardAssessmentService().assess(
            candidate,
            {"min_rr_ratio": 1.5, "rr_target": "final"},
        )
        incomplete = TradePlanCompletenessResult(
            complete=False,
            missing=["structural_stop"],
        )

        no_trade_snapshot = AutoEntryEligibilityService().evaluate(
            signal=candidate,
            risk_reward=assessment,
            completeness=TradePlanCompletenessResult(complete=True),
            no_trade_result=NoTradeFilterResult(
                enabled=True,
                blocked=True,
                blockers=["Spread 84.0 bps is above entry limit 25.0 bps"],
            ),
            candle_state="closed",
            mode="discovery",
            status_reason="No-trade hard block: Spread 84.0 bps is above entry limit 25.0 bps",
        )
        incomplete_snapshot = AutoEntryEligibilityService().evaluate(
            signal=candidate,
            risk_reward=assessment,
            completeness=incomplete,
            no_trade_result=NoTradeFilterResult(enabled=True, blocked=False),
            candle_state="closed",
            mode="production",
            status_reason="Trade plan incomplete: structural_stop; production actionability is blocked.",
        )

        self.assertIsNotNone(no_trade_snapshot)
        self.assertFalse(no_trade_snapshot.enabled if no_trade_snapshot else True)
        self.assertIn("No-trade hard block", no_trade_snapshot.message if no_trade_snapshot else "")
        self.assertIsNotNone(incomplete_snapshot)
        self.assertFalse(incomplete_snapshot.enabled if incomplete_snapshot else True)
        self.assertIn("Trade plan incomplete", incomplete_snapshot.message if incomplete_snapshot else "")

    def test_trade_plan_enrichment_preserves_targets(self) -> None:
        features = _breakout_features()
        candidate = _quality_candidate(features)
        original_targets = [
            TradePlanTarget(label="TP1", price=103.2, source="structural_test"),
            TradePlanTarget(label="TP2", price=104.2, source="structural_test"),
        ]
        trade_plan = TradePlan(
            entry=TradePlanEntry(price=features.close, min_price=features.close, max_price=features.close),
            stop_loss=features.close - 1.0,
            targets=original_targets,
        )
        candidate = candidate.model_copy(update={"trade_plan": trade_plan})
        assessment = RiskRewardAssessmentService().assess(
            candidate,
            {"min_rr_ratio": 1.5, "rr_target": "final"},
        )

        enriched = TradePlanEnrichmentService().enrich(
            signal=candidate,
            exit_plan=SignalExitPlanSnapshot(targets=[]),
            invalidation=SignalInvalidationSnapshot(
                price=features.close - 1.0,
                hard_stop=features.close - 1.0,
                conditions=["test invalidation"],
            ),
            risk_reward=assessment,
        )

        self.assertEqual([target.model_dump() for target in enriched.targets], [target.model_dump() for target in original_targets])
        self.assertEqual(enriched.risk_rules.selected_rr_target, "final")

    def test_research_mode_keeps_fallback_trade_plan_visible_with_warning(self) -> None:
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
            reasons=["Research fallback setup"],
            entry=features.close,
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "watchlist")
        self.assertTrue(signal.trade_plan.metadata.get("fallback_used") if signal and signal.trade_plan else False)
        self.assertFalse(signal.trade_plan.metadata.get("execution_allowed_virtual") if signal and signal.trade_plan else True)
        check = next(
            item
            for item in (signal.confirmation.checks if signal and signal.confirmation else [])
            if item.name == "trade_plan_completeness"
        )
        self.assertEqual(check.status, "failed")
        self.assertTrue(check.metadata.get("research_mode"))
        self.assertFalse(check.metadata.get("execution_allowed_virtual"))

    def test_production_mode_blocks_fallback_trade_plan_actionability(self) -> None:
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
            reasons=["Production fallback setup"],
            entry=features.close,
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"production_mode": True},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "watchlist")
        self.assertIn("Trade plan incomplete", signal.status_reason or "")
        self.assertIsNotNone(signal.auto_entry)
        self.assertFalse(signal.auto_entry.enabled if signal and signal.auto_entry else True)
        self.assertFalse(signal.trade_plan.metadata.get("signal_actionable") if signal and signal.trade_plan else True)
        self.assertFalse(signal.trade_plan.metadata.get("execution_allowed_virtual") if signal and signal.trade_plan else True)
        self.assertFalse(signal.trade_plan.metadata.get("execution_allowed_real") if signal and signal.trade_plan else True)
        check = next(
            item
            for item in (signal.confirmation.checks if signal and signal.confirmation else [])
            if item.name == "trade_plan_completeness"
        )
        self.assertEqual(check.status, "failed")
        self.assertTrue(check.metadata.get("production_mode"))

    def test_production_mode_allows_complete_structural_trade_plan(self) -> None:
        features = _breakout_features()

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"production_mode": True},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "actionable")
        self.assertTrue(signal.trade_plan.metadata.get("trade_plan_complete") if signal and signal.trade_plan else False)
        check = next(
            item
            for item in (signal.confirmation.checks if signal and signal.confirmation else [])
            if item.name == "trade_plan_completeness"
        )
        self.assertEqual(check.status, "passed")

    def test_pipeline_blocks_open_candle_actionable_by_default(self) -> None:
        features = _breakout_features().model_copy(update={"candle_state": "open"})
        candidate = _quality_candidate(features).model_copy(update={"status": "actionable"})

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.5, "rr_target": "final"},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.candle_state if signal else None, "open")
        self.assertEqual(signal.status if signal else None, "watchlist")
        self.assertIn("forming_candle", signal.status_reason if signal else "")
        self.assertFalse(signal.auto_entry.enabled if signal and signal.auto_entry else True)
        self.assertIn("forming candle preview", " ".join(signal.explanation if signal else []))
        self.assertFalse(signal.trade_plan.metadata.get("signal_actionable") if signal and signal.trade_plan else True)
        self.assertEqual(signal.trade_plan.metadata.get("candle_state") if signal and signal.trade_plan else None, "open")
        check = next(
            item
            for item in (signal.confirmation.checks if signal and signal.confirmation else [])
            if item.name == "candle_state_gate"
        )
        self.assertEqual(check.status, "warning")
        self.assertEqual(check.metadata.get("reason_code"), "forming_candle")

    def test_pipeline_blocks_open_candle_execution_even_when_legacy_allow_flag_is_set(self) -> None:
        features = _breakout_features().model_copy(update={"candle_state": "open"})
        candidate = _quality_candidate(features).model_copy(update={"status": "actionable"})

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={
                    "allow_open_candle_actionable": True,
                    "min_rr_ratio": 1.5,
                    "rr_target": "final",
                },
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status if signal else None, "ready")
        self.assertIn("trigger_not_confirmed", signal.status_reason if signal else "")
        self.assertIsNotNone(signal.trigger if signal else None)
        self.assertFalse(signal.trigger.passed if signal and signal.trigger else True)
        self.assertFalse(signal.execution_gate.can_show_in_execution_feed if signal and signal.execution_gate else True)
        self.assertFalse(
            signal.trade_plan.metadata.get("actionable_from_open_candle")
            if signal and signal.trade_plan
            else True
        )
        candle_check = next(
            item
            for item in (signal.confirmation.checks if signal and signal.confirmation else [])
            if item.name == "candle_state_gate"
        )
        self.assertEqual(candle_check.status, "passed")
        self.assertFalse(candle_check.metadata.get("actionable_from_open_candle"))
        trigger_check = next(
            item
            for item in (signal.confirmation.checks if signal and signal.confirmation else [])
            if item.name == "trigger_confirmation_gate"
        )
        self.assertEqual(trigger_check.status, "warning")
        self.assertEqual(trigger_check.metadata.get("reason_code"), "trigger_not_confirmed")

    def test_pipeline_blocks_lower_timeframe_trigger_actionable_by_default(self) -> None:
        features = _breakout_features()
        candidate = _quality_candidate(features).model_copy(update={"status": "actionable"})
        self.assertIsNotNone(candidate.trade_plan)
        assert candidate.trade_plan is not None
        trade_plan = candidate.trade_plan.model_copy(
            update={
                "metadata": {
                    **candidate.trade_plan.metadata,
                    "lower_timeframe_trigger": True,
                    "trigger_timeframe": "5m",
                }
            },
            deep=True,
        )
        candidate = candidate.model_copy(update={"trade_plan": trade_plan})

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.5, "rr_target": "final"},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status if signal else None, "ready")
        self.assertIn("lower_timeframe_trigger", signal.status_reason if signal else "")
        self.assertFalse(signal.auto_entry.enabled if signal and signal.auto_entry else True)
        self.assertFalse(signal.trade_plan.metadata.get("signal_actionable") if signal and signal.trade_plan else True)

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
        self.assertAlmostEqual(signal.final_target_rr or 0, 3.0)
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

    async def test_liquidity_sweep_obvious_liquidity_reclaim_absorption_long(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 98.8,
                "open": 99.2,
                "high": 100.5,
                "low": 96.2,
                "close": 98.8,
                "session_low": 98.0,
                "swing_low": 98.0,
                "swing_low_touch_count": 3,
                "swing_low_volume_score": 1.5,
                "lower_wick_ratio": 0.6,
                "upper_wick_ratio": 0.3,
                "volume_spike": 1.8,
            }
        )
        alpha_context = AlphaMarketContext(
            symbol="BTCUSDT",
            timeframe="15m",
            timestamp=features.timestamp,
            orderbook_imbalance=0.35,
            depth_wall_side="bid",
            absorption_score=0.72,
            data_quality={"missing_sources": ["liquidation_data"]},
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(
            features,
            {
                "alpha_context": alpha_context,
                "require_absorption": True,
                "min_absorption_score": 0.5,
            },
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "actionable")
        metadata = candidates[0].trade_plan.metadata if candidates[0].trade_plan else {}
        breakdown = metadata.get("liquidity_sweep_score_breakdown", {})
        self.assertTrue(metadata.get("alpha_context_used"))
        self.assertGreaterEqual(breakdown.get("absorption_score", 0), 0.7)
        self.assertGreaterEqual(breakdown.get("obvious_liquidity_score", 0), 0.7)

    async def test_liquidity_sweep_reclaim_cvd_divergence_short(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 103.7,
                "open": 104.5,
                "high": 105.0,
                "low": 103.0,
                "close": 103.7,
                "previous_high": 104.4,
                "swing_high": 104.0,
                "swing_high_touch_count": 2,
                "upper_wick_ratio": 0.62,
                "lower_wick_ratio": 0.12,
                "volume_spike": 1.8,
                "rsi_14": 68.0,
            }
        )
        alpha_context = AlphaMarketContext(
            symbol="BTCUSDT",
            timeframe="15m",
            timestamp=features.timestamp,
            delta_divergence="bearish_divergence",
            cvd_change=-120.0,
            aggressive_delta=-80.0,
            data_quality={"missing_sources": ["orderbook_l2", "liquidation_data"]},
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(
            features,
            {"alpha_context": alpha_context, "min_cvd_divergence_score": 0.8},
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].direction, "SHORT")
        self.assertEqual(candidates[0].status, "actionable")
        self.assertIn("CVD/delta divergence", " ".join(candidates[0].explanation))
        metadata = candidates[0].trade_plan.metadata if candidates[0].trade_plan else {}
        self.assertGreaterEqual(
            metadata.get("liquidity_sweep_score_breakdown", {}).get("cvd_divergence_score", 0),
            1.0,
        )

    async def test_liquidity_sweep_missing_alpha_context_uses_explicit_proxy_metadata(self) -> None:
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

        self.assertEqual(len(candidates), 1)
        metadata = candidates[0].trade_plan.metadata if candidates[0].trade_plan else {}
        self.assertFalse(metadata.get("alpha_context_used"))
        self.assertIn("alpha_context", metadata.get("missing_alpha_sources", []))
        self.assertIn("Alpha context unavailable", " ".join(candidates[0].risks))

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

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "rejected")
        self.assertIn("continued the breakout", candidates[0].status_reason or "")

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
        self.assertEqual(signal.status, "ready")
        self.assertFalse(signal.trigger.passed if signal and signal.trigger else True)
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

    def test_liquidity_sweep_without_reclaim_not_actionable(self) -> None:
        features = _breakout_features()
        candidate = _with_trade_plan_metadata(
            _liquidity_sweep_candidate(features),
            entry_metadata={
                "swept_level": features.close + 0.35,
                "requires_reclaim": True,
                "confirmation": False,
                "reclaim_score": 0.0,
                "absorption_score": 0.8,
                "oi_flush_score": 0.8,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIsNotNone(signal.trigger)
        self.assertFalse(signal.trigger.passed if signal.trigger else True)
        self.assertEqual(signal.trigger.trigger_type if signal.trigger else None, "liquidity_reclaim")
        self.assertIn("reclaim", signal.trigger.reason if signal.trigger else "")
        self.assertEqual(signal.status, "ready")

    def test_liquidity_sweep_with_reclaim_trigger_passes(self) -> None:
        features = _breakout_features()
        candidate = _with_trade_plan_metadata(
            _liquidity_sweep_candidate(features),
            entry_metadata={
                "swept_level": features.close - 0.35,
                "requires_reclaim": True,
                "confirmation": True,
                "reclaim_score": 0.85,
                "absorption_score": 0.8,
                "oi_flush_score": 0.8,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIsNotNone(signal.trigger)
        self.assertTrue(signal.trigger.passed if signal.trigger else False)
        self.assertEqual(signal.trigger.trigger_type if signal.trigger else None, "liquidity_reclaim")

    def test_breakout_large_candle_requires_retest(self) -> None:
        features = _breakout_features()
        candidate = _with_trade_plan_metadata(
            _quality_candidate(features),
            entry_metadata={
                "range_high": features.donchian_high_20,
                "range_low": features.donchian_low_20,
                "breakout_closed": True,
                "large_candle": True,
                "retest_required": True,
            },
            risk_metadata={
                "post_breakout_hold_score": 0.2,
                "retest_quality_score": 0.0,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIsNotNone(signal.trigger)
        self.assertFalse(signal.trigger.passed if signal.trigger else True)
        self.assertEqual(signal.trigger.trigger_type if signal.trigger else None, "breakout_retest")
        self.assertIn("breakout requires retest", signal.trigger.reason if signal.trigger else "")
        self.assertEqual(signal.status, "ready")

    def test_breakout_retest_trigger_passes(self) -> None:
        features = _breakout_features()
        candidate = _with_trade_plan_metadata(
            _quality_candidate(features),
            entry_metadata={
                "range_high": features.donchian_high_20,
                "range_low": features.donchian_low_20,
                "breakout_closed": True,
                "large_candle": True,
                "retest_required": True,
            },
            risk_metadata={
                "post_breakout_hold_score": 0.78,
                "retest_quality_score": 0.8,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIsNotNone(signal.trigger)
        self.assertTrue(signal.trigger.passed if signal.trigger else False)
        self.assertEqual(signal.trigger.trigger_type if signal.trigger else None, "breakout_retest")

    def test_trend_pullback_without_structural_zone_not_actionable(self) -> None:
        features = _breakout_features().model_copy(update={"history_length": 260})
        candidate = _with_trade_plan_metadata(
            _trend_pullback_candidate(features),
            metadata={
                "require_structural_zone": True,
                "structural_zone_ok": False,
                "structural_pullback_zone": None,
                "reclaimed_pullback_zone": False,
                "absorption_confirmed": False,
                "continuation_score": 0.2,
                "min_continuation_score": 0.45,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIsNotNone(signal.trigger)
        self.assertFalse(signal.trigger.passed if signal.trigger else True)
        self.assertIn(signal.status, {"ready", "watchlist", "wait_for_pullback"})
        self.assertIn("structural zone", signal.trigger.reason if signal.trigger else "")

    def test_trend_pullback_required_htf_alignment_blocks_trigger(self) -> None:
        features = _breakout_features().model_copy(update={"history_length": 260})
        candidate = _with_trade_plan_metadata(
            _trend_pullback_candidate(features),
            metadata={
                "require_structural_zone": True,
                "structural_zone_ok": True,
                "reclaimed_pullback_zone": True,
                "absorption_confirmed": True,
                "continuation_score": 0.8,
                "min_continuation_score": 0.45,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bearish_context_features(),
                strategy_params={"min_rr_ratio": 1.5, "require_htf_alignment": True},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.regime.alignment if signal.regime else None, "against")
        self.assertIsNotNone(signal.trigger)
        self.assertFalse(signal.trigger.passed if signal.trigger else True)
        self.assertIn("higher timeframe alignment", signal.trigger.reason if signal.trigger else "")
        self.assertIn(signal.status, {"ready", "watchlist", "wait_for_pullback"})

    def test_trend_pullback_blocked_in_chop(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "history_length": 260,
                "close": 100.4,
                "price": 100.4,
                "open": 100.1,
                "high": 100.7,
                "low": 99.9,
                "ema_20": 100.2,
                "ema_50": 100.1,
                "ema_200": 100.0,
                "ema_200_chop_score": 58.0,
                "ema_200_cross_count_50": 3,
                "ema_200_near_ratio_50": 0.42,
                "ema_200_slope_atr_20": 0.05,
                "adx": 12.0,
                "adx_rising": False,
                "range_20_atr": 2.2,
            }
        )
        candidate = _with_trade_plan_metadata(
            _trend_pullback_candidate(features),
            metadata={
                "require_structural_zone": True,
                "structural_zone_ok": True,
                "reclaimed_pullback_zone": True,
                "absorption_confirmed": True,
                "continuation_score": 0.8,
                "min_continuation_score": 0.45,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=features.model_copy(update={"timeframe": "1h"}),
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.regime.regime_type if signal.regime else None, "chop")
        self.assertFalse(signal.regime.compatibility.get("compatible") if signal.regime else True)
        self.assertIn("strategy_regime_incompatible", signal.status_reason or "")

    def test_liquidity_sweep_against_strong_trend_requires_absorption(self) -> None:
        features = _breakout_features()
        candidate = _with_trade_plan_metadata(
            build_signal(
                features=features,
                strategy="liquidity_sweep_reversal",
                direction="SHORT",
                scoring=score_breakdown(
                    trend_score=35,
                    volume_score=20,
                    liquidity_score=20,
                    orderbook_score=10,
                    risk_reward_score=15,
                ),
                reasons=["Liquidity sweep short setup"],
                entry=features.close,
                stop_loss=features.close + 1.0,
                take_profit_1=features.close - 2.0,
                take_profit_2=features.close - 3.0,
            ),
            entry_metadata={
                "swept_level": features.close + 0.4,
                "requires_reclaim": True,
                "confirmation": True,
                "reclaim_score": 0.85,
            },
            risk_metadata={
                "absorption_score": 0.0,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.regime.alignment if signal.regime else None, "against")
        self.assertEqual(
            signal.regime.compatibility.get("reason_code") if signal.regime else None,
            "strategy_regime_incompatible",
        )
        self.assertFalse(signal.regime.compatibility.get("compatible") if signal.regime else True)

    def test_breakout_requires_compression(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "bb_width_percentile": 62.0,
                "atr_14": 1.4,
                "atr_sma_50": 1.0,
                "range_20": 7.2,
                "range_50_average": 6.0,
                "range_20_atr": 7.2,
            }
        )
        candidate = _with_trade_plan_metadata(
            _quality_candidate(features),
            entry_metadata={
                "range_high": features.donchian_high_20,
                "range_low": features.donchian_low_20,
                "breakout_closed": True,
                "large_candle": False,
                "retest_required": False,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.regime.regime_type if signal.regime else None, "trend_up")
        self.assertFalse(signal.regime.compatibility.get("compatible") if signal.regime else True)
        self.assertIn("compression", signal.regime.compatibility.get("reason", "") if signal.regime else "")

    def test_liquidity_vacuum_creates_no_trade_blocker(self) -> None:
        features = _breakout_features()
        alpha_context = AlphaMarketContext(
            symbol=features.symbol,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            orderbook_imbalance=0.92,
            bid_depth_usd=12_000.0,
            ask_depth_usd=9_000.0,
            sweep_through_book=True,
        )

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                alpha_context=alpha_context,
                market_quality=MarketQualityInput(volume_24h_quote=450_000.0, spread_bps=88.0),
                strategy_params={"min_rr_ratio": 1.5, "no_trade_filters_enabled": True},
                pipeline_settings={"no_trade_filters_enabled": True},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIn("liquidity_vacuum", signal.regime.event_labels if signal.regime else [])
        self.assertTrue(signal.no_trade_filter.blocked if signal.no_trade_filter else False)
        self.assertIn("liquidity_vacuum", signal.no_trade_filter.metadata.get("blocker_codes", []) if signal.no_trade_filter else [])

    def test_news_pump_signal_is_not_actionable(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "open": 100.0,
                "high": 108.5,
                "low": 99.6,
                "close": 108.0,
                "price": 108.0,
                "volume_spike": 6.5,
                "volume": 650.0,
                "oi_change": 0.22,
            }
        )
        alpha_context = AlphaMarketContext(
            symbol=features.symbol,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            aggressive_delta=0.78,
            cvd_change=450_000.0,
            oi_delta_5m=0.18,
            funding_pressure=0.08,
        )

        signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                alpha_context=alpha_context,
                market_quality=MarketQualityInput(volume_24h_quote=200_000_000.0, spread_bps=42.0),
                strategy_params={"min_rr_ratio": 1.5, "no_trade_filters_enabled": True},
                pipeline_settings={"no_trade_filters_enabled": True},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIn("news_pump", signal.regime.event_labels if signal.regime else [])
        self.assertFalse(signal.decision.signal_actionable if signal.decision else True)
        self.assertTrue(any(reason.code == "news_pump_mode" for reason in (signal.decision.blockers if signal.decision else [])))

    def test_compression_boosts_volatility_squeeze_breakout(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 100.4,
                "open": 100.2,
                "high": 100.7,
                "low": 99.9,
                "close": 100.4,
                "bb_width_percentile": 8.0,
                "atr_14": 0.55,
                "atr_sma_50": 1.0,
                "range_20": 3.0,
                "range_50_average": 6.0,
                "volume_spike": 0.9,
            }
        )
        candidate = _quality_candidate(features)

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIn("volatility_compression", signal.regime.labels if signal.regime else [])
        self.assertGreaterEqual(signal.score, candidate.score + 10)

    def test_risk_off_blocks_long_but_not_automatically_short_if_liquidity_is_ok(self) -> None:
        features = _breakout_features()
        risk_off_context = MarketWideRegimeContext(
            exchange="bybit",
            timeframe=features.timeframe,
            majors={
                "BTCUSDT": _bearish_context_features().model_copy(update={"symbol": "BTCUSDT", "timeframe": features.timeframe}),
                "ETHUSDT": _bearish_context_features().model_copy(update={"symbol": "ETHUSDT", "timeframe": features.timeframe}),
            },
        )
        long_signal = StrategySignalPipeline().finalize(
            _quality_candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                market_wide_context=risk_off_context,
                market_quality=MarketQualityInput(volume_24h_quote=200_000_000.0, spread_bps=5.0),
                strategy_params={"min_rr_ratio": 1.5, "no_trade_filters_enabled": True},
                pipeline_settings={"no_trade_filters_enabled": True},
            ),
        )
        short_candidate = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="SHORT",
            scoring=score_breakdown(
                trend_score=35,
                volume_score=20,
                volatility_score=20,
                risk_reward_score=15,
            ),
            reasons=["Risk-off short setup"],
            entry=features.close,
            stop_loss=features.close + 1.0,
            take_profit_1=features.close - 2.0,
            take_profit_2=features.close - 3.0,
        )
        short_signal = StrategySignalPipeline().finalize(
            short_candidate,
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bearish_context_features(),
                market_wide_context=risk_off_context,
                market_quality=MarketQualityInput(volume_24h_quote=200_000_000.0, spread_bps=5.0),
                strategy_params={"min_rr_ratio": 1.5, "no_trade_filters_enabled": True},
                pipeline_settings={"no_trade_filters_enabled": True},
            ),
        )

        self.assertIsNotNone(long_signal)
        self.assertIn(
            "market_wide_risk_off",
            long_signal.no_trade_filter.metadata.get("blocker_codes", []) if long_signal and long_signal.no_trade_filter else [],
        )
        self.assertIsNotNone(short_signal)
        self.assertNotIn(
            "market_wide_risk_off",
            short_signal.no_trade_filter.metadata.get("blocker_codes", []) if short_signal and short_signal.no_trade_filter else [],
        )

    def test_score_90_without_trigger_not_execution_signal(self) -> None:
        features = _breakout_features()
        candidate = _with_trade_plan_metadata(
            _liquidity_sweep_candidate(features),
            entry_metadata={
                "swept_level": features.close + 0.35,
                "requires_reclaim": True,
                "confirmation": False,
                "reclaim_score": 0.0,
                "absorption_score": 0.8,
                "oi_flush_score": 0.8,
            },
        )

        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                strategy_params={"min_rr_ratio": 1.5},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIsNotNone(signal.execution_gate)
        self.assertFalse(signal.execution_gate.can_show_in_execution_feed if signal.execution_gate else True)
        self.assertIn(
            "trigger_not_confirmed",
            {reason.code for reason in signal.execution_gate.reasons} if signal.execution_gate else set(),
        )

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

    def test_strategy_pipeline_ignores_hide_low_rr_flag_and_blocks_execution(self) -> None:
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

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.status, "ready")
        self.assertIn("Risk/reward blocked", signal.status_reason or "")
        self.assertIsNotNone(signal.decision)
        assert signal.decision is not None
        self.assertTrue(
            any(reason.source == "rr" and reason.code == "blocked_by_rr" for reason in signal.decision.blockers)
        )
        self.assertFalse(signal.decision.signal_actionable)
        self.assertFalse(signal.decision.execution_allowed_virtual)
        self.assertIsNotNone(signal.auto_entry)
        self.assertFalse(signal.auto_entry.enabled if signal.auto_entry else True)
        self.assertEqual(signal.auto_entry.status if signal.auto_entry else None, "cancelled")
        rr_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "risk_reward_guard"
        )
        self.assertEqual(rr_check.status, "failed")
        self.assertEqual(rr_check.metadata.get("rr_status"), "failed")
        self.assertAlmostEqual(rr_check.metadata.get("rr_value") or 0, signal.selected_rr or 0)
        self.assertEqual(rr_check.metadata.get("blocker_codes"), ["blocked_by_rr"])
        self.assertFalse(rr_check.metadata.get("auto_entry_allowed"))
        legacy_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "legacy_pipeline_display_filter"
        )
        self.assertTrue(legacy_check.metadata.get("ignored"))
        self.assertTrue(legacy_check.metadata.get("rr_filter_would_have_hidden"))
        self.assertEqual(
            signal.trade_plan.metadata.get("execution_block_reason") if signal.trade_plan else None,
            "blocked_by_rr",
        )

    def test_strategy_pipeline_ignores_show_only_active_setups_flag(self) -> None:
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

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.status, "watchlist")
        legacy_check = next(
            check
            for check in (signal.confirmation.checks if signal.confirmation else [])
            if check.name == "legacy_pipeline_display_filter"
        )
        self.assertTrue(legacy_check.metadata.get("ignored"))
        self.assertTrue(legacy_check.metadata.get("active_only_filter_would_have_hidden"))

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
        self.assertEqual(candidates[0].trade_plan.entry.source if candidates[0].trade_plan else None, "breakout_retest")
        self.assertTrue(candidates[0].trade_plan.metadata.get("retest_required") if candidates[0].trade_plan else False)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "wait_for_pullback")
        self.assertTrue(
            any(
                reason.code == "retest_required_after_large_breakout"
                for reason in (signal.decision.warnings if signal and signal.decision else [])
            )
        )

    async def test_breakout_accepted_with_hold_delta_and_oi_is_actionable(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "open": 101.0,
                "high": 101.6,
                "low": 100.9,
                "close": 101.4,
                "price": 101.4,
                "previous_close": 101.0,
                "volume_spike": 2.0,
                "oi_change": 0.02,
            }
        )
        alpha_context = _breakout_alpha_context(features)

        candidates = await VolatilitySqueezeBreakoutStrategy().evaluate(
            features,
            {
                "alpha_context": alpha_context,
                "require_delta_expansion": True,
                "require_oi_expansion": True,
            },
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "actionable")
        metadata = candidates[0].trade_plan.metadata if candidates[0].trade_plan else {}
        self.assertTrue(metadata.get("alpha_context_used"))
        self.assertGreater(metadata.get("accepted_breakout_score") or 0.0, 0.75)
        self.assertLess(metadata.get("fakeout_risk_score") or 1.0, 0.25)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                alpha_context=alpha_context,
                strategy_params={
                    "alpha_context": alpha_context,
                    "require_delta_expansion": True,
                    "require_oi_expansion": True,
                },
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.status, "actionable")
        self.assertEqual(signal.trade_plan.entry.metadata.get("entry_model") if signal and signal.trade_plan else None, "aggressive_breakout")

    async def test_breakout_wick_close_back_inside_is_high_fakeout_not_actionable(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "open": 100.4,
                "high": 101.2,
                "low": 100.0,
                "close": 100.8,
                "price": 100.8,
                "upper_wick_ratio": 0.30,
                "volume_spike": 1.8,
            }
        )

        candidates = await VolatilitySqueezeBreakoutStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertNotEqual(candidates[0].status, "actionable")
        metadata = candidates[0].trade_plan.metadata if candidates[0].trade_plan else {}
        self.assertGreaterEqual(metadata.get("fakeout_risk_score") or 0.0, 0.55)
        self.assertTrue(metadata.get("retest_required"))

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertNotEqual(signal.status, "actionable")

    async def test_breakout_missing_alpha_context_records_warning_metadata(self) -> None:
        features = _breakout_features()

        candidates = await VolatilitySqueezeBreakoutStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        metadata = candidates[0].trade_plan.metadata if candidates[0].trade_plan else {}
        self.assertFalse(metadata.get("alpha_context_used"))
        self.assertIn("alpha_context", metadata.get("missing_alpha_sources") or [])
        self.assertIn("AlphaMarketContext is unavailable", " ".join(candidates[0].risks))

    async def test_breakout_trade_plan_invalidation_includes_failed_breakout_structure(self) -> None:
        features = _breakout_features()
        candidates = await VolatilitySqueezeBreakoutStrategy().evaluate(features)

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        conditions = signal.trade_plan.invalidation.conditions if signal and signal.trade_plan and signal.trade_plan.invalidation else []
        self.assertIn("Close returns inside the previous Donchian range", conditions)
        self.assertIn("Failed retest accepts price back inside the previous range", conditions)
        self.assertIn("Loss of breakout level", conditions)
        self.assertIn("Delta/OI reversal against continuation when available", conditions)

    async def test_breakout_aggressive_vs_conservative_params_change_entry_model(self) -> None:
        features = _breakout_features()

        aggressive = await VolatilitySqueezeBreakoutStrategy().evaluate(
            features,
            {"allow_aggressive_entry": True},
        )
        conservative = await VolatilitySqueezeBreakoutStrategy().evaluate(
            features,
            {"allow_aggressive_entry": False},
        )

        self.assertEqual(aggressive[0].trade_plan.entry.metadata.get("entry_model") if aggressive[0].trade_plan else None, "aggressive_breakout")
        self.assertEqual(conservative[0].trade_plan.entry.metadata.get("entry_model") if conservative[0].trade_plan else None, "conservative_retest")
        self.assertEqual(conservative[0].trade_plan.entry.source if conservative[0].trade_plan else None, "conservative_breakout")

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

    async def test_trend_pullback_vwap_reclaim_with_delta_confirmation_is_actionable(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.6,
                "price": 100.6,
                "open": 100.1,
                "high": 100.8,
                "low": 99.8,
                "vwap": 100.0,
                "ema_20": 99.2,
                "ema_50": 98.8,
                "ema_200": 95.0,
                "rsi_14": 50.0,
                "volume_spike": 1.25,
                "volume_ma_20": 70.0,
                "previous_high": 100.5,
                "previous_volume": 60.0,
                "history_length": 220,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
            alpha_context=_trend_alpha_context(features),
            strategy_configs={
                "trend_pullback_continuation": type(
                    "RuntimeConfig",
                    (),
                    {
                        "params": {
                            "require_structural_zone": True,
                            "require_delta_confirmation": True,
                        },
                        "risk_settings": {"min_rr_ratio": 1.0, "rr_target": "final"},
                        "pair_scope_configured": False,
                    },
                )(),
            },
        )

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.status, "actionable")
        self.assertEqual(signal.trade_plan.entry.source if signal.trade_plan else None, "vwap_deviation_pullback_zone")
        metadata = signal.trade_plan.metadata if signal.trade_plan else {}
        self.assertEqual(metadata.get("structural_zone_source"), "vwap_deviation")
        self.assertTrue(metadata.get("delta_confirmed"))
        self.assertIn(
            "Close loses the structural pullback zone",
            signal.trade_plan.invalidation.conditions if signal.trade_plan and signal.trade_plan.invalidation else [],
        )

    async def test_trend_pullback_ema_only_is_watchlist_when_structural_zone_required(self) -> None:
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
                        "params": {"require_structural_zone": True},
                        "risk_settings": {"min_rr_ratio": 1.0, "rr_target": "final"},
                        "pair_scope_configured": False,
                    },
                )(),
            },
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].status, "watchlist")
        self.assertLess(signals[0].score_breakdown.overheat_penalty, 100)
        self.assertTrue(
            any(
                check.name == "trend_structural_zone" and check.status == "failed"
                for check in (signals[0].confirmation.checks if signals[0].confirmation else [])
            )
        )

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

    async def test_trend_pullback_marks_extreme_funding_without_hard_block_by_default(self) -> None:
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

        self.assertEqual(len(candidates), 1)
        self.assertIn("Funding pressure", " ".join(candidates[0].risks))
        self.assertGreater(candidates[0].score_breakdown.overheat_penalty, 0)

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

    async def test_trend_pullback_high_exhaustion_blocks_actionable(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.9,
                "price": 100.9,
                "open": 99.7,
                "high": 101.0,
                "low": 99.6,
                "vwap": 100.0,
                "ema_20": 99.6,
                "ema_50": 98.8,
                "ema_200": 95.0,
                "rsi_14": 52.0,
                "volume_spike": 4.0,
                "previous_high": 100.5,
                "previous_volume": 60.0,
                "history_length": 220,
            }
        )

        signals = await StrategyEngine().generate_signals(
            features,
            context_features=_bullish_context_features(),
            alpha_context=_trend_alpha_context(
                features,
                aggressive_delta=-20.0,
                cvd_change=-10.0,
                delta_divergence="bearish_divergence",
            ),
            strategy_configs={
                "trend_pullback_continuation": type(
                    "RuntimeConfig",
                    (),
                    {
                        "params": {"max_exhaustion_score": 0.50},
                        "risk_settings": {"min_rr_ratio": 1.0, "rr_target": "final"},
                        "pair_scope_configured": False,
                    },
                )(),
            },
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].status, "watchlist")
        self.assertTrue(
            any(reason.code == "trend_exhaustion" for reason in (signals[0].decision.blockers if signals[0].decision else []))
        )
        self.assertGreater(signals[0].score_breakdown.overheat_penalty, 0)

    async def test_trend_pullback_crowded_funding_oi_penalizes_decision(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.6,
                "price": 100.6,
                "open": 100.1,
                "high": 100.8,
                "low": 99.8,
                "vwap": 100.0,
                "ema_20": 99.2,
                "ema_50": 98.8,
                "ema_200": 95.0,
                "rsi_14": 50.0,
                "volume_spike": 1.2,
                "previous_high": 100.5,
                "previous_volume": 60.0,
                "history_length": 220,
            }
        )

        clean = await TrendPullbackContinuationStrategy().evaluate(
            features,
            {"alpha_context": _trend_alpha_context(features)},
        )
        crowded = await TrendPullbackContinuationStrategy().evaluate(
            features,
            {
                "crowded_oi_penalty": 80,
                "alpha_context": _trend_alpha_context(
                    features,
                    funding_rate=0.0018,
                    funding_pressure=1.2,
                    oi_delta_15m=0.04,
                )
            },
        )

        self.assertEqual(len(clean), 1)
        self.assertEqual(len(crowded), 1)
        self.assertLess(crowded[0].score, clean[0].score)
        self.assertGreater(crowded[0].score_breakdown.overheat_penalty, clean[0].score_breakdown.overheat_penalty)

        signal = StrategySignalPipeline().finalize(
            crowded[0],
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_bullish_context_features(),
                strategy_params={"min_rr_ratio": 1.0, "rr_target": "final"},
            ),
        )

        self.assertIsNotNone(signal)
        self.assertTrue(
            any(reason.code == "trend_crowded_trade" for reason in (signal.decision.warnings if signal and signal.decision else []))
        )

    async def test_trend_pullback_missing_alpha_context_does_not_crash(self) -> None:
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

        candidates = await TrendPullbackContinuationStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].trade_plan.metadata.get("alpha_context_used"), False)
        self.assertIn("alpha_context", candidates[0].trade_plan.metadata.get("missing_alpha_sources", []))

    async def test_trend_pullback_htf_target_too_close_warns_and_blocks_actionable(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "close": 100.6,
                "price": 100.6,
                "open": 100.1,
                "high": 100.8,
                "low": 99.8,
                "vwap": 100.0,
                "ema_20": 99.2,
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
            alpha_context=_trend_alpha_context(features),
            strategy_configs={
                "trend_pullback_continuation": type(
                    "RuntimeConfig",
                    (),
                    {
                        "params": {"min_htf_target_distance_r": 0.75},
                        "risk_settings": {"min_rr_ratio": 1.0, "rr_target": "final"},
                        "pair_scope_configured": False,
                    },
                )(),
            },
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].status, "watchlist")
        self.assertIsNotNone(signals[0].trade_plan.metadata.get("nearest_htf_target_distance_r"))
        self.assertTrue(
            any(reason.code == "trend_htf_target_room" for reason in (signals[0].decision.warnings if signals[0].decision else []))
        )

    async def test_strategies_accept_missing_oi_context(self) -> None:
        features = _breakout_features().model_copy(update={"history_length": 220, "oi_change": None})

        for strategy in (
            VolatilitySqueezeBreakoutStrategy(),
            LiquiditySweepReversalStrategy(),
            TrendPullbackContinuationStrategy(),
        ):
            candidates = await strategy.evaluate(features)
            self.assertIsInstance(candidates, list)

    async def test_strategy_evaluate_does_not_receive_execution_profile_fields(self) -> None:
        class CapturingStrategy:
            name = "volatility_squeeze_breakout"

            def __init__(self) -> None:
                self.params = {}

            async def evaluate(self, features: Features, params=None):
                self.params = dict(params or {})
                return [_quality_candidate(features)]

        strategy = CapturingStrategy()
        engine = StrategyEngine()
        engine._strategies = [strategy]

        signals = await engine.generate_signals(
            _breakout_features(),
            strategy_configs={
                "volatility_squeeze_breakout": type(
                    "RuntimeConfig",
                    (),
                    {
                        "params": {
                            "min_history": 50,
                            "risk_mode": "fixed",
                            "account_balance": 1_000,
                            "leverage": 5,
                        },
                        "risk_settings": {
                            "risk_mode": "fixed",
                            "fixed_risk_amount": 25,
                            "leverage": 5,
                            "min_rr_ratio": 1.5,
                            "radar_display_mode": "execution_ready",
                        },
                        "pair_scope_configured": False,
                    },
                )(),
            },
        )

        self.assertTrue(signals)
        self.assertNotIn("risk_mode", strategy.params)
        self.assertNotIn("fixed_risk_amount", strategy.params)
        self.assertNotIn("account_balance", strategy.params)
        self.assertNotIn("leverage", strategy.params)
        self.assertNotIn("radar_display_mode", strategy.params)
        self.assertNotIn("min_rr_ratio", strategy.params)

    async def test_engine_passes_execution_settings_to_pipeline_not_strategy_params(self) -> None:
        class CapturingStrategy:
            name = "volatility_squeeze_breakout"

            def __init__(self) -> None:
                self.params: dict[str, object] = {}

            async def evaluate(self, features: Features, params=None):
                self.params = dict(params or {})
                return [_quality_candidate(features)]

        class CapturingPipeline:
            def __init__(self) -> None:
                self.context: StrategyEvaluationContext | None = None

            def finalize(self, signal, context: StrategyEvaluationContext):
                self.context = context
                return signal

        strategy = CapturingStrategy()
        pipeline = CapturingPipeline()
        engine = StrategyEngine()
        engine._strategies = [strategy]
        engine._pipeline = pipeline

        signals = await engine.generate_signals(
            _breakout_features(),
            strategy_configs={
                "volatility_squeeze_breakout": type(
                    "RuntimeConfig",
                    (),
                    {
                        "params": {
                            "min_history": 50,
                            "risk_percent": 99,
                            "fixed_risk_amount": 999,
                            "leverage": 25,
                        },
                        "risk_settings": {
                            "risk_percent": 1.25,
                            "fixed_risk_amount": 50,
                            "leverage": 3,
                            "rr_guard_mode": "hard",
                            "min_rr_ratio": 2.5,
                            "rr_target": "nearest",
                        },
                        "pair_scope_configured": False,
                    },
                )(),
            },
        )

        self.assertTrue(signals)
        for forbidden_key in ("risk_percent", "fixed_risk_amount", "leverage"):
            self.assertNotIn(forbidden_key, strategy.params)
        self.assertEqual(strategy.params["min_history"], 50)

        self.assertIsNotNone(pipeline.context)
        context = pipeline.context
        assert context is not None
        for forbidden_key in ("risk_percent", "fixed_risk_amount", "leverage"):
            self.assertNotIn(forbidden_key, context.strategy_params)
        self.assertEqual(str(context.execution_settings.risk_percent), "1.25")
        self.assertEqual(str(context.execution_settings.fixed_risk_amount), "50")
        self.assertEqual(str(context.execution_settings.leverage), "3")
        self.assertEqual(context.execution_settings.rr_guard_mode, "hard")
        self.assertEqual(float(context.pipeline_settings["min_rr_ratio"]), 2.5)
        self.assertEqual(context.pipeline_settings["rr_guard_mode"], "hard")
        self.assertEqual(context.pipeline_settings["rr_target"], "nearest")

    async def test_liquidity_sweep_without_reclaim_is_not_actionable(self) -> None:
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
        self.assertIn("waiting for reclaim", candidates[0].status_reason or "")

        signal = StrategySignalPipeline().finalize(
            candidates[0],
            StrategyEvaluationContext(signal_features=features, context_features=_bullish_context_features()),
        )

        self.assertIsNotNone(signal)
        self.assertNotEqual(signal.status, "actionable")

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
        self.assertEqual(targets[0].metadata.get("market_target_source"), "range_midpoint")
        self.assertEqual(targets[1].metadata.get("market_target_source"), "swing_high")
        self.assertEqual(candidates[0].trade_plan.metadata.get("market_target_source"), "range_midpoint")

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
        no_oi_candidates = await LiquiditySweepReversalStrategy().evaluate(
            features.model_copy(update={"oi_change": None})
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertIn("Open interest flush score", " ".join(candidates[0].explanation))
        self.assertGreater(candidates[0].score, no_oi_candidates[0].score)

    async def test_liquidity_sweep_blocks_when_market_target_room_is_too_small(self) -> None:
        features = _breakout_features().model_copy(
            update={
                "price": 98.8,
                "open": 99.2,
                "high": 99.4,
                "low": 97.5,
                "close": 98.8,
                "session_high": 99.2,
                "swing_low": 98.0,
                "swing_high": None,
                "donchian_high_20": None,
                "lower_wick_ratio": 0.6,
                "upper_wick_ratio": 0.3,
                "volume_spike": 1.8,
            }
        )

        candidates = await LiquiditySweepReversalStrategy().evaluate(
            features,
            {"min_target_distance_r": 0.75},
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "watchlist")
        self.assertIn("Nearest market target", candidates[0].status_reason or "")

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

        candidates = await LiquiditySweepReversalStrategy().evaluate(
            features,
            {"require_absorption": True, "min_absorption_score": 0.5},
        )

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


def _liquidity_sweep_candidate(features: Features):
    return build_signal(
        features=features,
        strategy="liquidity_sweep_reversal",
        direction="LONG",
        scoring=score_breakdown(
            trend_score=35,
            volume_score=20,
            liquidity_score=20,
            orderbook_score=10,
            risk_reward_score=15,
        ),
        reasons=["Liquidity sweep setup"],
        entry=features.close,
        stop_loss=features.close - 1.0,
        take_profit_1=features.close + 2.0,
        take_profit_2=features.close + 3.0,
    )


def _trend_pullback_candidate(features: Features):
    return build_signal(
        features=features,
        strategy="trend_pullback_continuation",
        direction="LONG",
        scoring=score_breakdown(
            trend_score=45,
            volume_score=20,
            volatility_score=10,
            risk_reward_score=15,
        ),
        reasons=["Trend pullback setup"],
        entry=features.close,
        stop_loss=features.close - 1.0,
        take_profit_1=features.close + 2.0,
        take_profit_2=features.close + 3.0,
    )


def _with_trade_plan_metadata(
    candidate,
    *,
    entry_metadata: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    risk_metadata: dict[str, object] | None = None,
):
    trade_plan = candidate.trade_plan
    assert trade_plan is not None
    entry = trade_plan.entry.model_copy(
        update={"metadata": {**trade_plan.entry.metadata, **(entry_metadata or {})}},
    )
    risk_rules = trade_plan.risk_rules.model_copy(
        update={"metadata": {**trade_plan.risk_rules.metadata, **(risk_metadata or {})}},
    )
    trade_plan = trade_plan.model_copy(
        update={
            "entry": entry,
            "metadata": {**trade_plan.metadata, **(metadata or {})},
            "risk_rules": risk_rules,
        },
        deep=True,
    )
    return candidate.model_copy(update={"trade_plan": trade_plan})


def _breakout_alpha_context(features: Features) -> AlphaMarketContext:
    return AlphaMarketContext(
        symbol=features.symbol,
        timeframe=features.timeframe,
        timestamp=features.timestamp,
        buy_volume=140.0,
        sell_volume=60.0,
        aggressive_delta=80.0,
        cvd=80.0,
        cvd_change=40.0,
        oi_delta_5m=0.02,
        oi_delta_15m=0.03,
        funding_rate=0.0002,
        funding_pressure=0.1,
        sweep_through_book=False,
        vwap_acceptance="above_vwap",
        data_quality={"available_sources": ["recent_trades", "derivative_snapshot"], "missing_sources": []},
    )


def _trend_alpha_context(
    features: Features,
    *,
    aggressive_delta: float = 80.0,
    cvd_change: float = 40.0,
    delta_divergence: DeltaDivergence | None = None,
    funding_rate: float = 0.0002,
    funding_pressure: float = 0.1,
    oi_delta_15m: float = 0.01,
) -> AlphaMarketContext:
    return AlphaMarketContext(
        symbol=features.symbol,
        timeframe=features.timeframe,
        timestamp=features.timestamp,
        buy_volume=140.0,
        sell_volume=60.0,
        aggressive_delta=aggressive_delta,
        cvd=80.0,
        cvd_change=cvd_change,
        delta_divergence=delta_divergence,
        oi_delta_5m=oi_delta_15m,
        oi_delta_15m=oi_delta_15m,
        funding_rate=funding_rate,
        funding_pressure=funding_pressure,
        orderbook_imbalance=0.25,
        depth_wall_side="bid",
        depth_wall_price=100.0,
        absorption_score=0.60,
        vwap_acceptance="above_vwap",
        vwap_deviation=0.001,
        data_quality={"available_sources": ["recent_trades", "derivative_snapshot"], "missing_sources": []},
    )


if __name__ == "__main__":
    unittest.main()
