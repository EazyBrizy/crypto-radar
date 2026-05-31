import unittest

from app.schemas.market import Features
from app.strategies.breakout import VolatilitySqueezeBreakoutStrategy
from app.strategies.common import build_signal, score_breakdown
from app.strategies.engine import StrategyEngine
from app.strategies.liquidity_sweep import LiquiditySweepReversalStrategy
from app.strategies.pipeline import MarketQualityInput, StrategyEvaluationContext, StrategySignalPipeline
from app.strategies.trend_pullback import TrendPullbackContinuationStrategy
from app.services.support_resistance import SupportResistanceLevel, SupportResistanceSnapshot


class StrategySignalPipelineTest(unittest.IsolatedAsyncioTestCase):
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

    def test_strategy_pipeline_keeps_low_rr_card_but_not_actionable(self) -> None:
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
        self.assertEqual(signal.status, "ready")
        self.assertIn("Risk/reward blocked", signal.status_reason or "")
        self.assertIn("configured minimum", " ".join(signal.risks if signal else []))

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
        self.assertEqual(signal.selected_rr_target, "nearest")
        self.assertAlmostEqual(signal.first_target_rr or 0, 1.0)
        self.assertAlmostEqual(signal.final_target_rr or 0, 3.0)
        self.assertAlmostEqual(signal.selected_rr or 0, 1.0)
        self.assertIn("nearest target", signal.status_reason or "")

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
                strategy_params={"hide_failed_rr_signals": True},
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
        self.assertEqual(trend_signal.entry_min, 100.6)
        self.assertEqual(trend_signal.entry_max, 100.6)
        self.assertGreaterEqual(trend_signal.score, 75)
        self.assertEqual(trend_signal.exit_plan.trailing.get("source") if trend_signal.exit_plan else None, "EMA20")

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
        adx=28.0,
        adx_rising=True,
        bb_width_percentile=12.0,
        donchian_high_20=100.8,
        donchian_low_20=95.0,
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
