from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from app.domain.signal_status import is_execution_candidate_status
from app.schemas.market import AlphaMarketContext, Features
from app.schemas.signal import (
    MarketQualitySnapshot,
    MarketRegimeSnapshot,
    NoTradeFilterResult,
    SignalConfirmationSnapshot,
    SignalExitPlanSnapshot,
    SignalInvalidationSnapshot,
    SignalLayerCheck,
    SignalTriggerSnapshot,
    StrategySetupSnapshot,
    StrategySignal,
)
from app.schemas.risk import StrategyExecutionSettings
from app.schemas.trade_plan import (
    TargetThesis,
    TradePlan,
    TradePlanTarget,
)
from app.services.no_trade_filter import NoTradeFilterService
from app.services.auto_entry_eligibility import AutoEntryEligibilityService
from app.services.market_context import MarketContextService, MarketContextSnapshot
from app.services.market_regime import MarketQualityInput, MarketRegimeService, MarketWideRegimeContext
from app.services.risk_reward_assessment import (
    RiskRewardAssessment,
    RiskRewardAssessmentService,
    risk_reward_metadata,
)
from app.services.risk_reward_plan import risk_reward_plan_service
from app.services.signal_status_resolver import SignalStatusResolver
from app.services.support_resistance import SupportResistanceSnapshot
from app.services.target_resolver import TargetResolverService
from app.services.trade_plan_enrichment import TradePlanEnrichmentService
from app.services.trade_plan_completeness import trade_plan_completeness_service
from app.services.signal_decision import signal_decision_service
from app.services.signal_execution_gate import signal_execution_gate_service
from app.strategies.common import ACTIONABLE_SCORE, WATCHLIST_SCORE, score_from_breakdown

MAJOR_BASE_ASSETS = {"BTC", "ETH", "SOL", "BNB", "XRP"}
LOW_LIQUIDITY_BASE_ASSETS = {"1000PEPE", "PEPE", "SHIB", "FLOKI", "BONK", "WIF"}
TREND_STRATEGIES = {"trend_pullback_continuation"}

CONTEXT_TIMEFRAME_BY_SIGNAL: dict[str, str] = {
    "1m": "15m",
    "5m": "1h",
    "15m": "1h",
    "1h": "4h",
    "4h": "1d",
}

MACRO_CONTEXT_TIMEFRAME_BY_SIGNAL: dict[str, str] = {
    "5m": "4h",
    "15m": "4h",
    "1h": "1d",
    "4h": "1d",
}

MIN_CONTEXT_HISTORY = 50
CONTEXT_OBSTACLE_MIN_ATR = 1.0
CONTEXT_LEVEL_MIN_STRENGTH = 25.0

CONTEXT_OBSTACLE_MIN_ATR_BY_STRATEGY: dict[str, float] = {
    "trend_pullback_continuation": 0.8,
    "volatility_squeeze_breakout": 1.2,
    "liquidity_sweep_reversal": 0.7,
}

MIN_HISTORY_BY_STRATEGY: dict[str, int] = {
    "trend_pullback_continuation": 200,
    "volatility_squeeze_breakout": 60,
    "liquidity_sweep_reversal": 30,
}

MAX_BODY_ATR_BY_STRATEGY: dict[str, float] = {
    "trend_pullback_continuation": 2.0,
    "volatility_squeeze_breakout": 2.5,
    "liquidity_sweep_reversal": 2.0,
}

MAX_RANGE_ATR_BY_STRATEGY: dict[str, float] = {
    "trend_pullback_continuation": 3.0,
    "volatility_squeeze_breakout": 3.5,
    "liquidity_sweep_reversal": 3.8,
}

MIN_DYNAMIC_BODY_ATR = 1.7
IMPULSE_BODY_RATIO = 0.7
EXTREME_CLOSE_LOCATION = 0.8
REJECTION_WICK_RATIO = 0.45

QUALITY_DEFAULTS_BY_TIER: dict[str, dict[str, float]] = {
    "major": {"min_24h_volume_quote": 25_000_000.0, "max_spread_bps": 15.0, "rough_chart_fail": 5.0},
    "mid_alt": {"min_24h_volume_quote": 10_000_000.0, "max_spread_bps": 25.0, "rough_chart_fail": 4.5},
    "low_liquidity": {"min_24h_volume_quote": 5_000_000.0, "max_spread_bps": 35.0, "rough_chart_fail": 4.0},
    "unknown": {"min_24h_volume_quote": 10_000_000.0, "max_spread_bps": 25.0, "rough_chart_fail": 4.5},
}


@dataclass(frozen=True)
class StrategyEvaluationContext:
    signal_features: Features
    alpha_context: AlphaMarketContext | None = None
    context_features: Features | None = None
    context_features_by_timeframe: Mapping[str, Features] = field(default_factory=dict)
    support_resistance_by_timeframe: Mapping[str, SupportResistanceSnapshot] = field(default_factory=dict)
    strategy_params: Mapping[str, Any] = field(default_factory=dict)
    execution_settings: StrategyExecutionSettings = field(default_factory=StrategyExecutionSettings)
    pipeline_settings: Mapping[str, Any] = field(default_factory=dict)
    market_quality: MarketQualityInput | None = None
    market_context: MarketContextSnapshot | None = None
    market_wide_context: MarketWideRegimeContext | None = None
    pair_scope_configured: bool = False
    rr_guard_context: str = "discovery"


@dataclass(frozen=True)
class PullbackTarget:
    price: float | None
    label: str
    source: str
    entry_min: float | None = None
    entry_max: float | None = None


@dataclass(frozen=True)
class OverextensionAssessment:
    overextended: bool
    body_atr: float
    range_atr: float
    body_threshold: float
    range_threshold: float
    reason: str
    pullback_target: PullbackTarget


def context_timeframe_for(timeframe: str, strategy_params: Mapping[str, Any] | None = None) -> str | None:
    override = _context_timeframe_override(timeframe, strategy_params or {})
    if override is not None:
        return override
    return CONTEXT_TIMEFRAME_BY_SIGNAL.get(timeframe)


def context_timeframes_for(timeframe: str, strategy_params: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    result: list[str] = []
    for candidate in (
        context_timeframe_for(timeframe, strategy_params),
        MACRO_CONTEXT_TIMEFRAME_BY_SIGNAL.get(timeframe),
    ):
        if candidate and candidate not in result:
            result.append(candidate)
    return tuple(result)


class StrategySignalPipeline:
    def finalize(
        self,
        signal: StrategySignal,
        context: StrategyEvaluationContext,
    ) -> StrategySignal | None:
        trade_plan_enrichment = TradePlanEnrichmentService()
        signal = trade_plan_enrichment.ensure_trade_plan(signal)
        candle_state = _effective_candle_state(signal, context.signal_features)
        if signal.candle_state != candle_state:
            signal = signal.model_copy(update={"candle_state": candle_state})
        quality = MarketQualityFilter().evaluate(signal, context)
        pipeline_settings = _pipeline_settings(context)
        no_trade_enabled = _bool_param(pipeline_settings, "no_trade_filters_enabled", False)
        if not quality.passed and not no_trade_enabled:
            return None

        regime = MarketRegimeFilter().evaluate(signal, context)
        if _has_severe_ema200_chop(regime) and signal.strategy == "trend_pullback_continuation":
            return None
        signal = signal.model_copy(update={"regime": regime})
        market_context = context.market_context or MarketContextService().build_snapshot(
            features=context.signal_features,
            direction=signal.direction,
            alpha_context=context.alpha_context,
            market_quality=context.market_quality,
            market_wide_context=context.market_wide_context,
            settings=pipeline_settings,
        )
        signal = _apply_regime_score(signal, regime)
        setup = StrategySetupLayer().evaluate(signal)
        invalidation = InvalidationLayer().build(signal, context)
        exit_management = ExitManagementLayer()
        exit_plan = exit_management.build(signal, context)
        trade_plan, risk_reward, signal_for_layers = _enrich_trade_plan_with_final_risk_reward(
            signal=signal,
            exit_plan=exit_plan,
            invalidation=invalidation,
            params=pipeline_settings,
            rr_guard_context=context.rr_guard_context,
            trade_plan_enrichment=trade_plan_enrichment,
        )
        signal_for_layers = signal_for_layers.model_copy(
            update={
                "quality": quality,
                "regime": regime,
                "invalidation": invalidation,
                "exit_plan": exit_plan,
            },
            deep=True,
        )
        confirmation = ConfirmationLayer().evaluate(signal_for_layers, context, risk_reward)
        trigger = TriggerLayer().evaluate(signal_for_layers, context, confirmation)
        no_trade = NoTradeFilterService().evaluate(
            signal=signal_for_layers,
            features=context.signal_features,
            context={
                "quality": quality,
                "regime": regime,
                "confirmation": confirmation,
                "market_quality": context.market_quality,
                "market_context": market_context,
            },
            settings=pipeline_settings,
        )
        no_trade = _no_trade_with_market_context(no_trade, market_context)
        confirmation = _confirmation_with_no_trade_check(confirmation, no_trade)
        if not quality.passed and not no_trade.blocked:
            return None
        production_mode = _is_production_mode(pipeline_settings)
        completeness_context = {
            "quality": quality,
            "regime": regime,
            "setup": setup,
            "confirmation": confirmation,
            "market_quality": context.market_quality,
            "market_context": market_context,
            "alpha_context": context.alpha_context,
            "context_features": context.context_features,
            "context_features_by_timeframe": context.context_features_by_timeframe,
            "support_resistance_by_timeframe": context.support_resistance_by_timeframe,
        }
        completeness = trade_plan_completeness_service.assess(
            signal_for_layers,
            trade_plan,
            settings=pipeline_settings,
            context=completeness_context,
            production_mode=production_mode,
        )
        trade_plan = trade_plan_enrichment.attach_completeness_metadata(
            trade_plan=trade_plan,
            completeness=completeness,
            production_mode=production_mode,
        )
        confirmation = trade_plan_enrichment.annotate_confirmation_completeness(
            confirmation=confirmation,
            completeness=completeness,
            production_mode=production_mode,
        )

        signal_for_status = signal_for_layers.model_copy(
            update={
                "trade_plan": trade_plan,
                "confirmation": confirmation,
                "trigger": trigger,
                "no_trade_filter": no_trade,
            },
            deep=True,
        )
        status_decision = SignalStatusResolver().resolve(
            signal=signal_for_status,
            params=pipeline_settings,
            quality=quality,
            regime=regime,
            confirmation=confirmation,
            setup=setup,
            risk_reward=risk_reward,
            no_trade_filter=no_trade,
            completeness=completeness,
            trade_plan=trade_plan,
            candle_state=candle_state,
            trigger=trigger,
            production_mode=production_mode,
            actionable_score=ACTIONABLE_SCORE,
        )
        status = status_decision.status
        status_reason = status_decision.status_reason
        confirmation = status_decision.confirmation
        setup = status_decision.setup
        trade_plan = status_decision.trade_plan
        entry_updates: dict[str, Any] = {}
        if status == "wait_for_pullback":
            overextension = _overextension_check(confirmation)
            target = _pullback_target_from_check(overextension)
            if target is not None:
                entry_updates = {
                    "entry_min": target.entry_min,
                    "entry_max": target.entry_max,
                }
                trade_plan = _sync_trade_plan_entry(
                    trade_plan=trade_plan,
                    entry_min=target.entry_min,
                    entry_max=target.entry_max,
                )
                signal_for_layers = signal_for_layers.model_copy(
                    update={**entry_updates, "trade_plan": trade_plan},
                    deep=True,
                )
                exit_plan = exit_management.build(signal_for_layers, context)
                trade_plan, risk_reward, signal_for_layers = _enrich_trade_plan_with_final_risk_reward(
                    signal=signal_for_layers,
                    exit_plan=exit_plan,
                    invalidation=invalidation,
                    params=pipeline_settings,
                    rr_guard_context=context.rr_guard_context,
                    trade_plan_enrichment=trade_plan_enrichment,
                )
                confirmation = ConfirmationLayer().evaluate(signal_for_layers, context, risk_reward)
                trigger = TriggerLayer().evaluate(signal_for_layers, context, confirmation)
                no_trade = NoTradeFilterService().evaluate(
                    signal=signal_for_layers,
                    features=context.signal_features,
                    context={
                        "quality": quality,
                        "regime": regime,
                        "confirmation": confirmation,
                        "market_quality": context.market_quality,
                        "market_context": market_context,
                    },
                    settings=pipeline_settings,
                )
                no_trade = _no_trade_with_market_context(no_trade, market_context)
                confirmation = _confirmation_with_no_trade_check(confirmation, no_trade)
                completeness_context["confirmation"] = confirmation
                completeness = trade_plan_completeness_service.assess(
                    signal_for_layers,
                    trade_plan,
                    settings=pipeline_settings,
                    context=completeness_context,
                    production_mode=production_mode,
                )
                trade_plan = trade_plan_enrichment.attach_completeness_metadata(
                    trade_plan=trade_plan,
                    completeness=completeness,
                    production_mode=production_mode,
                )
                confirmation = trade_plan_enrichment.annotate_confirmation_completeness(
                    confirmation=confirmation,
                    completeness=completeness,
                    production_mode=production_mode,
                )
                signal_for_status = signal_for_layers.model_copy(
                    update={
                        "quality": quality,
                        "regime": regime,
                        "invalidation": invalidation,
                        "exit_plan": exit_plan,
                        "trade_plan": trade_plan,
                        "confirmation": confirmation,
                        "trigger": trigger,
                        "no_trade_filter": no_trade,
                    },
                    deep=True,
                )
                status_decision = SignalStatusResolver().resolve(
                    signal=signal_for_status,
                    params=pipeline_settings,
                    quality=quality,
                    regime=regime,
                    confirmation=confirmation,
                    setup=setup,
                    risk_reward=risk_reward,
                    no_trade_filter=no_trade,
                    completeness=completeness,
                    trade_plan=trade_plan,
                    candle_state=candle_state,
                    trigger=trigger,
                    production_mode=production_mode,
                    actionable_score=ACTIONABLE_SCORE,
                )
                status = status_decision.status
                status_reason = status_decision.status_reason
                confirmation = status_decision.confirmation
                setup = status_decision.setup
                trade_plan = status_decision.trade_plan
        trade_plan = _trade_plan_with_risk_reward_metadata(trade_plan, risk_reward)
        trade_plan = _trade_plan_with_market_context(trade_plan, market_context)
        legacy_display_note = _legacy_display_filter_note(
            pipeline_settings,
            risk_reward=risk_reward,
            status=status,
        )
        if legacy_display_note is not None:
            confirmation = _confirmation_with_legacy_display_filter_note(
                confirmation,
                legacy_display_note,
            )
            trade_plan = _trade_plan_with_legacy_display_filter_note(
                trade_plan,
                legacy_display_note,
            )

        auto_entry = AutoEntryEligibilityService().evaluate(
            signal=signal,
            risk_reward=risk_reward,
            completeness=completeness,
            no_trade_result=no_trade,
            candle_state=candle_state,
            mode="production" if production_mode else context.rr_guard_context,
            status_reason=status_reason,
            actionability_block_reason=status_decision.actionability_block_reason,
            actionability_block_message=status_decision.actionability_block_message,
        )
        explanation = [
            f"Status: {status_reason}",
            *status_decision.explanation,
            *signal.explanation,
        ]
        risks = list(signal.risks)
        for reason in status_decision.risks:
            if reason not in risks:
                risks.append(reason)
        for warning in quality.warnings:
            if warning not in risks:
                risks.append(warning)
        if _has_strong_regime_conflict(regime):
            risks.append("Signal is against a strong higher-timeframe regime")
        if _has_context_obstacle(regime):
            risks.append("Signal is too close to higher-timeframe support/resistance")
        if _has_borderline_ema200_chop(regime):
            risks.append("Price is chopping around EMA200; trend-continuation setups are less reliable")
        if risk_reward.warning and risk_reward.warning_reason:
            risks.append(risk_reward.warning_reason)
        if risk_reward.blocked:
            risks.append(risk_reward.reason)
        for warning in completeness.warnings:
            if warning not in risks:
                risks.append(warning)
        for reason in [*no_trade.blockers, *no_trade.warnings]:
            if reason not in risks:
                risks.append(reason)
        for blocker in market_context.blockers:
            if blocker.message not in risks:
                risks.append(blocker.message)

        updates: dict[str, Any] = {
            "status": status,
            "status_reason": status_reason,
            "quality": quality,
            "regime": regime,
            "setup": setup,
            "confirmation": confirmation,
            "trigger": trigger,
            "no_trade_filter": no_trade,
            "invalidation": invalidation,
            "exit_plan": exit_plan,
            "first_target_rr": risk_reward.first_target_rr,
            "final_target_rr": risk_reward.final_target_rr,
            "selected_rr": risk_reward.rr,
            "selected_rr_target": risk_reward.target_key,
            "min_rr_ratio": risk_reward.min_rr,
            "explanation": explanation,
            "risks": risks,
            "candle_state": candle_state,
            **entry_updates,
        }
        updates["decision"] = signal_decision_service.from_pipeline_outputs(
            signal=signal,
            quality=quality,
            confirmation=confirmation,
            risk_reward=risk_reward,
            no_trade_filter=no_trade,
            completeness=completeness,
            trade_plan=trade_plan,
            candle_state=candle_state,
            production_mode=production_mode,
            status=status,
            rr_guard_context=context.rr_guard_context,
            regime=regime,
        )
        if auto_entry is not None:
            updates["auto_entry"] = auto_entry
        updates["trade_plan"] = trade_plan
        gate_input = signal.model_copy(update=updates)
        updates["execution_gate"] = signal_execution_gate_service.evaluate(
            gate_input,
            strict_edge_mode=_bool_param(pipeline_settings, "strict_edge_mode", False),
        )

        return signal.model_copy(update=updates)


class MarketQualityFilter:
    def evaluate(
        self,
        signal: StrategySignal,
        context: StrategyEvaluationContext,
    ) -> MarketQualitySnapshot:
        features = context.signal_features
        min_history = int(
            context.strategy_params.get(
                "min_history",
                MIN_HISTORY_BY_STRATEGY.get(signal.strategy, 50),
            )
        )
        tier = _pair_tier(features.symbol)
        profile = _quality_profile(tier, context.strategy_params)
        market_quality = context.market_quality
        manual_pair_scope = context.pair_scope_configured
        checks: list[SignalLayerCheck] = []
        warnings: list[str] = []
        score = 100

        if manual_pair_scope:
            checks.append(
                SignalLayerCheck(
                    name="manual_pair_scope",
                    status="passed",
                    reason="Strategy has explicit pair scope; market quality is informative and does not filter out the setup",
                )
            )

        history_ok = features.history_length >= min_history
        checks.append(
            SignalLayerCheck(
                name="candle_history",
                status="passed" if history_ok else "failed",
                score=features.history_length,
                reason=f"{features.history_length}/{min_history} candles available",
            )
        )
        if not history_ok:
            score -= 45

        volume_ok = features.volume > 0 and features.volume_ma_20 > 0
        checks.append(
            SignalLayerCheck(
                name="volume_presence",
                status="passed" if volume_ok else "failed",
                score=features.volume,
                reason="Latest candle has usable volume",
            )
        )
        if not volume_ok:
            score -= 35

        if tier == "low_liquidity":
            if manual_pair_scope:
                warnings.append("Low-liquidity asset is allowed by explicit strategy pair scope")
                score -= 10
                checks.append(
                    SignalLayerCheck(
                        name="low_liquidity_mode",
                        status="warning",
                        reason="Manual pair scope bypasses automatic low-liquidity exclusion",
                    )
                )
            elif _bool_param(context.strategy_params, "allow_low_liquidity", False):
                warnings.append("Low-liquidity asset tier is explicitly enabled for this strategy")
                score -= 10
                checks.append(
                    SignalLayerCheck(
                        name="low_liquidity_mode",
                        status="warning",
                        reason="Low-liquidity strategy scope is enabled; inefficiency search is not implemented yet",
                    )
                )
            else:
                warnings.append("Low-liquidity asset tier is excluded from regular MVP strategies")
                score -= 50
                checks.append(
                    SignalLayerCheck(
                        name="low_liquidity_mode",
                        status="failed",
                        reason="Enable low-liquidity mode only after inefficiency strategy support exists",
                    )
                )

        rough_chart_score = _rough_chart_score(features)
        rough_fail = float(profile["rough_chart_fail"])
        if rough_chart_score >= rough_fail:
            rough_status = "warning" if manual_pair_scope else "failed"
        elif rough_chart_score >= 3:
            rough_status = "warning"
        else:
            rough_status = "passed"
        if rough_status == "failed":
            warnings.append("Candle is extremely wide relative to ATR")
            score -= 30
        elif rough_status == "warning":
            warnings.append("Candle is unusually wide relative to ATR")
            score -= 10
        checks.append(
            SignalLayerCheck(
                name="rough_chart",
                status=rough_status,
                score=round(rough_chart_score, 3),
            )
        )

        gap_or_pump = _has_gap_or_illiquid_pump(features)
        if gap_or_pump:
            warnings.append("Move looks extended without enough volume confirmation")
            score -= 35
        checks.append(
            SignalLayerCheck(
                name="gap_or_pump",
                status="warning" if manual_pair_scope and gap_or_pump else "failed" if gap_or_pump else "passed",
                score=abs(features.price_change_1m),
            )
        )

        spread_bps = market_quality.spread_bps if market_quality is not None else None
        max_spread_bps = float(profile["max_spread_bps"])
        if spread_bps is None:
            warnings.append("Spread snapshot is unavailable for market-quality filter")
            score -= 10
            checks.append(
                SignalLayerCheck(
                    name="spread",
                    status="warning",
                    reason="Spread snapshot is unavailable; strategy classification is less reliable",
                )
            )
        else:
            spread_ok = spread_bps <= max_spread_bps
            if not spread_ok:
                warnings.append(f"Spread {spread_bps:.1f} bps is above {max_spread_bps:.1f} bps limit")
                score -= 35
            checks.append(
                SignalLayerCheck(
                    name="spread",
                    status="passed" if spread_ok else "warning" if manual_pair_scope else "failed",
                    score=round(spread_bps, 3),
                    reason=f"Limit {max_spread_bps:.1f} bps for {tier}",
                )
            )

        volume_24h_quote = market_quality.volume_24h_quote if market_quality is not None else None
        min_24h_volume_quote = float(profile["min_24h_volume_quote"])
        if volume_24h_quote is None:
            warnings.append("24h quote volume snapshot is unavailable for market-quality filter")
            score -= 10
            checks.append(
                SignalLayerCheck(
                    name="24h_volume",
                    status="warning",
                    reason="24h quote volume is unavailable; strategy classification is less reliable",
                )
            )
        else:
            volume_24h_ok = volume_24h_quote >= min_24h_volume_quote
            if not volume_24h_ok:
                warnings.append(
                    f"24h quote volume {volume_24h_quote:.0f} is below {min_24h_volume_quote:.0f} minimum"
                )
                score -= 35
            checks.append(
                SignalLayerCheck(
                    name="24h_volume",
                    status="passed" if volume_24h_ok else "warning" if manual_pair_scope else "failed",
                    score=round(volume_24h_quote, 3),
                    reason=f"Minimum {min_24h_volume_quote:.0f} quote volume for {tier}",
                )
            )
        if market_quality is not None:
            warnings.extend(warning for warning in market_quality.warnings if warning not in warnings)
        checks.append(
            SignalLayerCheck(
                name="quality_source",
                status="passed" if market_quality is not None and market_quality.source else "warning",
                reason=market_quality.source if market_quality is not None and market_quality.source else "No external quality source",
            )
        )

        failed = any(check.status == "failed" for check in checks)
        return MarketQualitySnapshot(
            passed=(history_ok and volume_ok) if manual_pair_scope else score >= 50 and history_ok and volume_ok and not failed,
            tier=tier,
            score=max(0, min(100, score)),
            volume_24h_quote=volume_24h_quote,
            spread_bps=spread_bps,
            history_ok=history_ok,
            rough_chart_score=round(rough_chart_score, 3),
            checks=checks,
            warnings=warnings,
        )


class MarketRegimeFilter:
    def evaluate(
        self,
        signal: StrategySignal,
        context: StrategyEvaluationContext,
    ) -> MarketRegimeSnapshot:
        signal_features = context.signal_features
        primary_features = _primary_context_features(context)
        expected_context_timeframe = context_timeframe_for(signal_features.timeframe, context.strategy_params)
        settings_map = {
            **dict(context.strategy_params or {}),
            **dict(_pipeline_settings(context)),
        }
        regime = MarketRegimeService().evaluate_for_signal(
            signal=signal,
            signal_features=signal_features,
            context_features=primary_features,
            context_features_by_timeframe=context.context_features_by_timeframe,
            alpha_context=context.alpha_context,
            market_quality=context.market_quality,
            market_wide_context=context.market_wide_context,
            settings=settings_map,
        )
        adjustment = regime.score_adjustment
        checks: list[SignalLayerCheck] = list(regime.checks)

        if primary_features is None:
            checks.append(
                SignalLayerCheck(
                    name="context_timeframe",
                    status="skipped",
                    reason=f"Expected {expected_context_timeframe or 'none'} context; using signal timeframe only",
                )
            )
        else:
            checks.append(
                SignalLayerCheck(
                    name="context_timeframe",
                    status="passed",
                    reason=f"Using {primary_features.timeframe} context for {signal_features.timeframe} signal",
                )
            )
            min_context_history = int(context.strategy_params.get("min_context_history", MIN_CONTEXT_HISTORY))
            history_ok = primary_features.history_length >= min_context_history
            checks.append(
                SignalLayerCheck(
                    name="context_history",
                    status="passed" if history_ok else "warning",
                    score=primary_features.history_length,
                    reason=f"{primary_features.history_length}/{min_context_history} context candles available",
                )
            )

        macro_features = _macro_context_features(context)
        if macro_features is None:
            macro_timeframe = MACRO_CONTEXT_TIMEFRAME_BY_SIGNAL.get(signal_features.timeframe)
            if macro_timeframe and macro_timeframe != regime.context_timeframe:
                checks.append(
                    SignalLayerCheck(
                        name="macro_regime_alignment",
                        status="skipped",
                        reason=f"{macro_timeframe} macro context is not warm enough",
                    )
                )
        elif primary_features is None or macro_features.timeframe != primary_features.timeframe:
            macro_direction = _trend_direction(macro_features)
            macro_strength = _trend_strength(macro_features)
            macro_alignment = _alignment(signal.direction.lower(), macro_direction)
            adjustment += _macro_regime_score_adjustment(signal.strategy, macro_alignment, macro_strength)
            checks.append(
                SignalLayerCheck(
                    name="macro_regime_alignment",
                    status="warning" if macro_alignment == "against" else "passed",
                    reason=(
                        f"{signal.direction.lower()} vs {macro_direction} "
                        f"{macro_features.timeframe} macro context ({macro_strength})"
                    ),
                )
            )

        if primary_features is not None:
            support_resistance = _primary_support_resistance(context)
            obstacle_check, obstacle_adjustment = _context_obstacle_check(
                signal=signal,
                signal_features=signal_features,
                context_features=primary_features,
                support_resistance=support_resistance,
                min_atr=float(
                    context.strategy_params.get(
                        "context_obstacle_min_atr",
                        CONTEXT_OBSTACLE_MIN_ATR_BY_STRATEGY.get(signal.strategy, CONTEXT_OBSTACLE_MIN_ATR),
                    )
                ),
                min_strength=float(
                    context.strategy_params.get(
                        "context_level_min_strength",
                        CONTEXT_LEVEL_MIN_STRENGTH,
                    )
                ),
                max_obstacle_distance_r=_optional_positive_float(
                    context.strategy_params.get("max_obstacle_distance_r")
                ),
            )
            checks.append(obstacle_check)
            adjustment += obstacle_adjustment
            if signal.strategy == "liquidity_sweep_reversal":
                level_check, level_adjustment = _liquidity_sweep_context_level_check(
                    signal=signal,
                    signal_features=signal_features,
                    context_features=primary_features,
                    support_resistance=support_resistance,
                    tolerance_atr=float(context.strategy_params.get("sweep_level_confluence_atr", 0.5)),
                    min_strength=float(
                        context.strategy_params.get(
                            "context_level_min_strength",
                            CONTEXT_LEVEL_MIN_STRENGTH,
                        )
                    ),
                )
                checks.append(level_check)
                adjustment += level_adjustment
        compatibility_check = next(
            (check for check in checks if check.name == "strategy_regime_compatibility"),
            None,
        )
        compatibility = dict(regime.compatibility)
        if compatibility_check is not None:
            compatibility = {
                **compatibility_check.metadata,
                "status": compatibility_check.status,
                "reason": compatibility_check.reason,
            }
        return regime.model_copy(
            update={
                "score_adjustment": adjustment,
                "checks": checks,
                "compatibility": compatibility,
                "regime_key": f"{regime.primary_label}:{regime.strength}:{regime.alignment}",
            }
        )


class StrategySetupLayer:
    def evaluate(self, signal: StrategySignal) -> StrategySetupSnapshot:
        if signal.status == "watchlist":
            stage = "forming"
        elif signal.status in {"ready", "wait_for_pullback"}:
            stage = "ready"
        else:
            stage = "confirmed" if signal.score >= ACTIONABLE_SCORE else "ready"
        return StrategySetupSnapshot(
            name=signal.strategy,
            stage=stage,
            checks=[
                SignalLayerCheck(
                    name="strategy_setup",
                    status="passed",
                    score=signal.score,
                    reason=f"Strategy-specific setup returned a {stage} candidate",
                )
            ],
        )


class ConfirmationLayer:
    def evaluate(
        self,
        signal: StrategySignal,
        context: StrategyEvaluationContext,
        risk_reward: RiskRewardAssessment,
    ) -> SignalConfirmationSnapshot:
        features = context.signal_features
        overextension = _assess_overextension(signal, features, context.strategy_params)
        checks = [
            SignalLayerCheck(
                name="score_threshold",
                status="passed" if signal.score >= WATCHLIST_SCORE else "failed",
                score=signal.score,
                reason=f"Minimum visible setup score is {WATCHLIST_SCORE}",
            ),
            SignalLayerCheck(
                name="strategy_stage",
                status="warning" if signal.status in {"watchlist", "ready"} else "passed",
                reason=f"Strategy emitted {signal.status} stage",
            ),
            SignalLayerCheck(
                name="overextension_guard",
                status="warning" if overextension.overextended else "passed",
                score=round(overextension.body_atr, 3),
                reason=overextension.reason,
                metadata=_overextension_metadata(overextension),
            ),
            SignalLayerCheck(
                name="risk_reward_guard",
                status=risk_reward.status,
                score=None if risk_reward.rr is None else round(risk_reward.rr, 3),
                reason=risk_reward.reason,
                metadata=risk_reward_metadata(risk_reward),
            ),
            SignalLayerCheck(
                name="volume_confirmation",
                status="passed" if features.volume_spike >= 1 else "warning",
                score=round(features.volume_spike, 3),
            ),
        ]
        checks.extend(_breakout_classifier_checks(signal, context.strategy_params))
        checks.extend(_trend_pullback_checks(signal, context.strategy_params))
        return SignalConfirmationSnapshot(
            passed=all(check.status != "failed" for check in checks),
            checks=checks,
        )


class TriggerLayer:
    def evaluate(
        self,
        signal: StrategySignal,
        context: StrategyEvaluationContext,
        confirmation: SignalConfirmationSnapshot,
    ) -> SignalTriggerSnapshot:
        if signal.strategy == "liquidity_sweep_reversal":
            return _liquidity_sweep_trigger(signal, context, confirmation)
        if signal.strategy == "volatility_squeeze_breakout":
            return _breakout_trigger(signal, context, confirmation)
        if signal.strategy == "trend_pullback_continuation":
            return _trend_pullback_trigger(signal, context, confirmation)
        return _fallback_current_trigger(signal, context, confirmation)


def _fallback_current_trigger(
    signal: StrategySignal,
    context: StrategyEvaluationContext,
    confirmation: SignalConfirmationSnapshot,
) -> SignalTriggerSnapshot:
    trigger_type = _trigger_type_for_strategy(signal)
    closed_candle = signal.candle_state == "closed"
    passed = confirmation.passed and closed_candle
    reason = (
        "Trigger confirmed on closed candle."
        if passed
        else "Trigger requires a closed candle."
        if not closed_candle
        else "Strategy confirmation has not passed."
    )
    failed_checks = _trigger_failed_checks(
        {
            "closed_candle": closed_candle,
            "confirmation_passed": confirmation.passed,
        }
    )
    return _trigger_snapshot(
        signal,
        context,
        confirmation,
        trigger_type=trigger_type,
        passed=passed,
        reason=reason,
        check_name="trigger_confirmation",
        evidence={
            "closed_candle": closed_candle,
            "confirmation_passed": confirmation.passed,
        },
        failed_checks=failed_checks,
        source="confirmation_layer",
    )


def _liquidity_sweep_trigger(
    signal: StrategySignal,
    context: StrategyEvaluationContext,
    confirmation: SignalConfirmationSnapshot,
) -> SignalTriggerSnapshot:
    features = context.signal_features
    direction = signal.direction.lower()
    closed_candle = signal.candle_state == "closed"
    swept_level = _trade_plan_metadata_number(signal, "swept_level")
    if swept_level is None:
        swept_level = _trade_plan_metadata_number(signal, "level")
    requires_reclaim = _trade_plan_metadata_bool(signal, "requires_reclaim")
    if requires_reclaim is None:
        requires_reclaim = _trade_plan_metadata_bool(signal, "require_reclaim")
    if requires_reclaim is None:
        requires_reclaim = True
    confirmation_candle = bool(_trade_plan_metadata_bool(signal, "confirmation"))
    reclaim_score = _trade_plan_metadata_number(signal, "reclaim_score") or 0.0
    reclaimed_by_close = (
        swept_level is not None
        and (
            (direction == "long" and features.close > swept_level)
            or (direction == "short" and features.close < swept_level)
        )
    )
    reclaim_ok = reclaimed_by_close and (not requires_reclaim or confirmation_candle or reclaim_score >= 0.5)

    require_absorption = _bool_param(context.strategy_params, "require_absorption", False)
    min_absorption = _strategy_numeric_param(context.strategy_params, "min_absorption_score", signal.strategy, 0.35)
    absorption_score = _trade_plan_metadata_number(signal, "absorption_score")
    absorption_ok = not require_absorption or (
        absorption_score is not None and absorption_score >= min_absorption
    )

    require_oi_flush = _bool_param(context.strategy_params, "require_oi_flush", False)
    min_oi_flush = _strategy_numeric_param(context.strategy_params, "min_oi_flush_score", signal.strategy, 0.01)
    oi_flush_score = _trade_plan_metadata_number(signal, "oi_flush_score")
    oi_flush_ok = not require_oi_flush or (oi_flush_score is not None and oi_flush_score >= min_oi_flush)

    evidence = {
        "closed_candle": closed_candle,
        "confirmation_passed": confirmation.passed,
        "swept_level_exists": swept_level is not None,
        "reclaim_close_confirmed": reclaim_ok,
        "requires_reclaim": requires_reclaim,
        "confirmation_candle": confirmation_candle,
        "reclaim_score": reclaim_score,
        "absorption_required": require_absorption,
        "absorption_ok": absorption_ok,
        "absorption_score": absorption_score,
        "oi_flush_required": require_oi_flush,
        "oi_flush_ok": oi_flush_ok,
        "oi_flush_score": oi_flush_score,
        "close": features.close,
        "swept_level": swept_level,
    }
    failed_checks = _trigger_failed_checks(
        {
            "closed_candle": closed_candle,
            "confirmation_passed": confirmation.passed,
            "swept_level_exists": swept_level is not None,
            "reclaim_close_confirmed": reclaim_ok,
            "absorption_ok": absorption_ok,
            "oi_flush_ok": oi_flush_ok,
        }
    )
    passed = not failed_checks
    reason = _first_trigger_reason(
        failed_checks,
        {
            "closed_candle": "Trigger requires a closed candle.",
            "confirmation_passed": "Strategy confirmation has not passed.",
            "swept_level_exists": "Liquidity sweep trigger requires a swept level.",
            "reclaim_close_confirmed": "Sweep detected but reclaim close is not confirmed",
            "absorption_ok": "Absorption required but missing",
            "oi_flush_ok": "OI flush required but unavailable/failed",
        },
        success="Liquidity sweep reclaim trigger confirmed.",
    )
    reason_code = _first_trigger_reason_code(
        failed_checks,
        {
            "closed_candle": "forming_candle",
            "confirmation_passed": "trigger_not_confirmed",
            "swept_level_exists": "liquidity_sweep_level_missing",
            "reclaim_close_confirmed": "liquidity_reclaim_missing",
            "absorption_ok": "liquidity_absorption_missing",
            "oi_flush_ok": "liquidity_oi_flush_missing",
        },
    )
    return _trigger_snapshot(
        signal,
        context,
        confirmation,
        trigger_type="liquidity_reclaim",
        passed=passed,
        reason=reason,
        check_name="liquidity_sweep_trigger",
        evidence=evidence,
        failed_checks=failed_checks,
        source="strategy_trigger_layer",
        reason_code=reason_code,
    )


def _breakout_trigger(
    signal: StrategySignal,
    context: StrategyEvaluationContext,
    confirmation: SignalConfirmationSnapshot,
) -> SignalTriggerSnapshot:
    features = context.signal_features
    direction = signal.direction.lower()
    closed_candle = signal.candle_state == "closed"
    range_high = _trade_plan_metadata_number(signal, "range_high")
    if range_high is None:
        range_high = features.donchian_high_20
    range_low = _trade_plan_metadata_number(signal, "range_low")
    if range_low is None:
        range_low = features.donchian_low_20

    compression_ok = _breakout_compression_ok(signal, context)
    outside_level = (
        (direction == "long" and range_high is not None and features.close > range_high)
        or (direction == "short" and range_low is not None and features.close < range_low)
    )
    breakout_closed = _trade_plan_metadata_bool(signal, "breakout_closed")
    if breakout_closed is None:
        breakout_closed = outside_level
    large_candle = bool(_trade_plan_metadata_bool(signal, "large_candle"))
    retest_required = bool(_trade_plan_metadata_bool(signal, "retest_required"))
    post_hold_score = _trade_plan_metadata_number(signal, "post_breakout_hold_score") or 0.0
    retest_quality_score = _trade_plan_metadata_number(signal, "retest_quality_score") or 0.0
    retest_passed = max(post_hold_score, retest_quality_score) >= 0.65
    retest_ok = not retest_required or retest_passed
    trigger_type = "breakout_retest" if retest_required else "closed_candle"

    evidence = {
        "closed_candle": closed_candle,
        "confirmation_passed": confirmation.passed,
        "compression_existed": compression_ok,
        "closed_outside_breakout_level": bool(outside_level),
        "breakout_closed": bool(breakout_closed),
        "large_candle": large_candle,
        "retest_required": retest_required,
        "retest_passed": retest_passed,
        "post_breakout_hold_score": post_hold_score,
        "retest_quality_score": retest_quality_score,
        "range_high": range_high,
        "range_low": range_low,
        "close": features.close,
    }
    failed_checks = _trigger_failed_checks(
        {
            "closed_candle": closed_candle,
            "confirmation_passed": confirmation.passed,
            "compression_existed": compression_ok,
            "closed_outside_breakout_level": bool(outside_level),
            "breakout_closed": bool(breakout_closed),
            "retest_ok": retest_ok,
        }
    )
    passed = not failed_checks
    reason = _first_trigger_reason(
        failed_checks,
        {
            "closed_candle": "Trigger requires a closed candle.",
            "confirmation_passed": "Strategy confirmation has not passed.",
            "compression_existed": "Breakout trigger requires prior volatility compression.",
            "closed_outside_breakout_level": "Breakout trigger requires a close outside the breakout level.",
            "breakout_closed": "Breakout close is not confirmed.",
            "retest_ok": "breakout requires retest" if large_candle or retest_required else "Breakout retest is not confirmed.",
        },
        success="Breakout trigger confirmed.",
    )
    reason_code = _first_trigger_reason_code(
        failed_checks,
        {
            "closed_candle": "forming_candle",
            "confirmation_passed": "trigger_not_confirmed",
            "compression_existed": "breakout_compression_missing",
            "closed_outside_breakout_level": "breakout_level_not_closed",
            "breakout_closed": "breakout_close_missing",
            "retest_ok": "breakout_retest_required",
        },
    )
    return _trigger_snapshot(
        signal,
        context,
        confirmation,
        trigger_type=trigger_type,
        passed=passed,
        reason=reason,
        check_name="breakout_trigger",
        evidence=evidence,
        failed_checks=failed_checks,
        source="strategy_trigger_layer",
        reason_code=reason_code,
    )


def _trend_pullback_trigger(
    signal: StrategySignal,
    context: StrategyEvaluationContext,
    confirmation: SignalConfirmationSnapshot,
) -> SignalTriggerSnapshot:
    features = context.signal_features
    closed_candle = signal.candle_state == "closed"
    require_structural_zone = bool(_trade_plan_metadata_bool(signal, "require_structural_zone"))
    structural_zone_ok = _trade_plan_metadata_bool(signal, "structural_zone_ok")
    structural_ok = not require_structural_zone or structural_zone_ok is True
    reclaimed_zone = bool(_trade_plan_metadata_bool(signal, "reclaimed_pullback_zone"))
    absorption_confirmed = bool(_trade_plan_metadata_bool(signal, "absorption_confirmed"))
    continuation_score = _trade_plan_metadata_number(signal, "continuation_score") or 0.0
    min_continuation_score = _trade_plan_metadata_number(signal, "min_continuation_score")
    if min_continuation_score is None:
        min_continuation_score = _strategy_numeric_param(
            context.strategy_params,
            "min_continuation_score",
            signal.strategy,
            0.45,
        )
    continuation_ok = continuation_score >= min_continuation_score
    require_htf_alignment = _bool_param(context.strategy_params, "require_htf_alignment", False)
    htf_alignment = signal.regime.alignment if signal.regime is not None else "unknown"
    htf_alignment_ok = not require_htf_alignment or htf_alignment == "aligned"
    ema_chop_blocked = _features_have_severe_ema200_chop(features)
    pullback_held = reclaimed_zone or absorption_confirmed or continuation_ok
    trigger_type = "reclaim" if reclaimed_zone or absorption_confirmed else "pullback_touch"

    evidence = {
        "closed_candle": closed_candle,
        "confirmation_passed": confirmation.passed,
        "require_structural_zone": require_structural_zone,
        "structural_zone_ok": structural_zone_ok,
        "structural_ok": structural_ok,
        "reclaimed_pullback_zone": reclaimed_zone,
        "absorption_confirmed": absorption_confirmed,
        "continuation_score": continuation_score,
        "min_continuation_score": min_continuation_score,
        "require_htf_alignment": require_htf_alignment,
        "htf_alignment": htf_alignment,
        "htf_alignment_ok": htf_alignment_ok,
        "pullback_held_or_reclaimed": pullback_held,
        "ema200_chop_blocked": ema_chop_blocked,
    }
    failed_checks = _trigger_failed_checks(
        {
            "closed_candle": closed_candle,
            "structural_ok": structural_ok,
            "htf_alignment_ok": htf_alignment_ok,
            "pullback_held_or_reclaimed": pullback_held,
            "ema200_chop_clear": not ema_chop_blocked,
            "confirmation_passed": confirmation.passed,
        }
    )
    passed = not failed_checks
    reason = _first_trigger_reason(
        failed_checks,
        {
            "closed_candle": "Trigger requires a closed candle.",
            "structural_ok": "Trend pullback requires a structural zone before trigger.",
            "htf_alignment_ok": "Trend pullback trigger requires higher timeframe alignment.",
            "pullback_held_or_reclaimed": "Trend pullback trigger requires the structural zone to hold or reclaim.",
            "ema200_chop_clear": "Trend pullback trigger is blocked by EMA200 chop.",
            "confirmation_passed": "Strategy confirmation has not passed.",
        },
        success="Trend pullback trigger confirmed.",
    )
    reason_code = _first_trigger_reason_code(
        failed_checks,
        {
            "closed_candle": "forming_candle",
            "structural_ok": "trend_structural_zone_missing",
            "htf_alignment_ok": "trend_htf_alignment_missing",
            "pullback_held_or_reclaimed": "trend_pullback_hold_missing",
            "ema200_chop_clear": "trend_chop_blocked",
            "confirmation_passed": "trigger_not_confirmed",
        },
    )
    return _trigger_snapshot(
        signal,
        context,
        confirmation,
        trigger_type=trigger_type,
        passed=passed,
        reason=reason,
        check_name="trend_pullback_trigger",
        evidence=evidence,
        failed_checks=failed_checks,
        source="strategy_trigger_layer",
        reason_code=reason_code,
    )


def _trigger_snapshot(
    signal: StrategySignal,
    context: StrategyEvaluationContext,
    confirmation: SignalConfirmationSnapshot,
    *,
    trigger_type: str,
    passed: bool,
    reason: str,
    check_name: str,
    evidence: dict[str, Any],
    failed_checks: list[str],
    source: str,
    reason_code: str | None = None,
) -> SignalTriggerSnapshot:
    confirmed_at = _signal_timestamp_datetime(signal.timestamp) if passed else None
    trigger_candle_state = signal.candle_state
    confirmed_on_closed_candle = bool(passed and trigger_candle_state == "closed")
    metadata = {
        "strategy": signal.strategy,
        "timeframe": signal.timeframe,
        "source": source,
        "trigger_type": trigger_type,
        "failed_checks": failed_checks,
        "confirmation_passed": confirmation.passed,
        "candle_state": signal.candle_state,
        "trigger_candle_state": trigger_candle_state,
        "confirmed_on_closed_candle": confirmed_on_closed_candle,
        "trigger_confirmed_at": confirmed_at.isoformat() if confirmed_at is not None else None,
        "reason_code": None if passed else reason_code,
        **evidence,
    }
    check = SignalLayerCheck(
        name=check_name,
        status="passed" if passed else "failed",
        reason=reason,
        metadata=metadata,
    )
    return SignalTriggerSnapshot(
        trigger_type=trigger_type,
        passed=passed,
        price=_entry_price(signal) or context.signal_features.close,
        candle_state=signal.candle_state,
        confirmed_at=confirmed_at,
        reason=reason,
        checks=[check],
        metadata=metadata,
    )


def _trigger_failed_checks(checks: Mapping[str, bool]) -> list[str]:
    return [name for name, passed in checks.items() if not passed]


def _first_trigger_reason(
    failed_checks: list[str],
    reasons: Mapping[str, str],
    *,
    success: str,
) -> str:
    if not failed_checks:
        return success
    return reasons.get(failed_checks[0], "Strategy trigger is not confirmed.")


def _first_trigger_reason_code(
    failed_checks: list[str],
    reason_codes: Mapping[str, str],
) -> str | None:
    if not failed_checks:
        return None
    return reason_codes.get(failed_checks[0], "trigger_not_confirmed")


def _breakout_compression_ok(signal: StrategySignal, context: StrategyEvaluationContext) -> bool:
    features = context.signal_features
    bb_squeeze = _trade_plan_metadata_bool(signal, "bb_squeeze")
    if bb_squeeze is None:
        threshold = _strategy_numeric_param(
            context.strategy_params,
            "bb_width_percentile_threshold",
            signal.strategy,
            20.0,
        )
        bb_squeeze = features.bb_width_percentile is not None and features.bb_width_percentile < threshold
    atr_compressed = _trade_plan_metadata_bool(signal, "atr_compressed")
    if atr_compressed is None:
        atr_compressed = (
            features.atr_14 is not None
            and features.atr_sma_50 is not None
            and features.atr_14 < features.atr_sma_50
        )
    range_contracting = _trade_plan_metadata_bool(signal, "range_contracting")
    if range_contracting is None:
        range_contracting = (
            features.range_20 is not None
            and features.range_50_average is not None
            and features.range_20 < features.range_50_average
        )
    return bool(bb_squeeze and atr_compressed and range_contracting)


def _features_have_severe_ema200_chop(features: Features) -> bool:
    score = features.ema_200_chop_score
    crosses = features.ema_200_cross_count_50 or 0
    return bool((score is not None and score >= 70) or crosses >= 4)


class InvalidationLayer:
    def build(
        self,
        signal: StrategySignal,
        context: StrategyEvaluationContext,
    ) -> SignalInvalidationSnapshot:
        features = context.signal_features
        direction = signal.direction.lower()
        entry = _entry_price(signal)
        conditions: list[str]
        metadata: dict[str, Any] = {
            "strategy": signal.strategy,
            "direction": direction,
            "timeframe": signal.timeframe,
            "signal_timestamp": signal.timestamp,
            "signal_open": features.open,
            "signal_close": features.close,
            "signal_high": features.high,
            "signal_low": features.low,
            "signal_volume_spike": features.volume_spike,
            "entry_price": entry,
            "stop_loss": signal.stop_loss,
            "swing_high": features.swing_high,
            "swing_low": features.swing_low,
            "ema_50": features.ema_50,
            "vwap": features.vwap,
            "rsi_14": features.rsi_14,
            "donchian_high_20": features.donchian_high_20,
            "donchian_low_20": features.donchian_low_20,
        }

        if signal.strategy == "trend_pullback_continuation":
            time_stop_bars = _optional_positive_int(context.strategy_params.get("time_stop_bars"))
            structural_zone = _trade_plan_metadata_dict(signal, "structural_pullback_zone")
            metadata.update(
                {
                    "source": "structural_pullback_invalidation",
                    "structural_invalidation": True,
                    "structural_pullback_zone": structural_zone,
                    "structural_zone_source": _trade_plan_metadata_string(signal, "structural_zone_source"),
                    "structural_zone_price": _trade_plan_metadata_number(signal, "structural_zone_price"),
                    "structural_zone_quality_score": _trade_plan_metadata_number(signal, "structural_zone_quality_score"),
                    "continuation_score": _trade_plan_metadata_number(signal, "continuation_score"),
                    "exhaustion_score": _trade_plan_metadata_number(signal, "exhaustion_score"),
                    "nearest_htf_target": _trade_plan_metadata_number(signal, "nearest_htf_target"),
                    "nearest_htf_target_source": _trade_plan_metadata_string(signal, "nearest_htf_target_source"),
                    "nearest_htf_target_distance_r": _trade_plan_metadata_number(signal, "nearest_htf_target_distance_r"),
                    "rsi_long_min": 45.0,
                    "rsi_short_max": 55.0,
                    "trend_invalidation_level": features.swing_low if direction == "long" else features.swing_high,
                    "time_stop_bars": time_stop_bars,
                    "time_stop": "no_progress_to_TP1" if time_stop_bars is not None else None,
                }
            )
            if direction == "long":
                conditions = [
                    "Close loses the structural pullback zone",
                    "Close accepts below VWAP/zone after reclaim",
                    "Close below EMA50",
                    "Break below last swing low",
                    "RSI loses the 45 zone",
                ]
            else:
                conditions = [
                    "Close reclaims above the structural pullback zone",
                    "Close accepts above VWAP/zone after rejection",
                    "Close above EMA50",
                    "Break above last swing high",
                    "RSI reclaims the 55 zone",
                ]
            if time_stop_bars is not None:
                conditions.append(f"No progress toward TP1 within {time_stop_bars} bars")
        elif signal.strategy == "volatility_squeeze_breakout":
            breakout_level = features.donchian_high_20 if direction == "long" else features.donchian_low_20
            range_high = features.donchian_high_20
            range_low = features.donchian_low_20
            range_height = (
                range_high - range_low
                if range_high is not None and range_low is not None and range_high > range_low
                else None
            )
            measured_move_target = None
            if range_height is not None:
                measured_move_target = (
                    range_high + range_height
                    if direction == "long" and range_high is not None
                    else range_low - range_height if range_low is not None else None
                )
            retest_zone = _entry_zone_around_level(breakout_level, features.atr_14)
            metadata.update(
                {
                    "range_high": range_high,
                    "range_low": range_low,
                    "source": "breakout_structure",
                    "structural_invalidation": True,
                    "range_height": range_height,
                    "range_20": features.range_20,
                    "range_50_average": features.range_50_average,
                    "range_20_atr": features.range_20_atr,
                    "breakout_level": breakout_level,
                    "aggressive_entry": features.close,
                    "conservative_entry": breakout_level,
                    "conservative_entry_min": retest_zone[0],
                    "conservative_entry_max": retest_zone[1],
                    "entry_model": _trade_plan_entry_model(signal),
                    "measured_move_target": measured_move_target,
                    "bb_width_percentile": features.bb_width_percentile,
                    "atr_sma_50": features.atr_sma_50,
                    "close_position": _directional_close_location(signal.direction, features),
                    "rejection_wick_ratio": _rejection_wick_ratio(signal.direction, features),
                    "volume_disappears_below": 1.0,
                    "accepted_breakout_score": _trade_plan_metadata_number(signal, "accepted_breakout_score"),
                    "fakeout_risk_score": _trade_plan_metadata_number(signal, "fakeout_risk_score"),
                    "post_breakout_hold_score": _trade_plan_metadata_number(signal, "post_breakout_hold_score"),
                    "retest_quality_score": _trade_plan_metadata_number(signal, "retest_quality_score"),
                    "delta_expansion_score": _trade_plan_metadata_number(signal, "delta_expansion_score"),
                    "oi_expansion_score": _trade_plan_metadata_number(signal, "oi_expansion_score"),
                    "volume_acceptance_score": _trade_plan_metadata_number(signal, "volume_acceptance_score"),
                    "failed_breakout_invalidation": _trade_plan_metadata_bool(
                        signal,
                        "failed_breakout_invalidation",
                    ),
                    "retest_required": _trade_plan_metadata_bool(signal, "retest_required"),
                    "alpha_context_used": _trade_plan_metadata_bool(signal, "alpha_context_used"),
                    "missing_alpha_sources": _trade_plan_metadata_list(signal, "missing_alpha_sources"),
                }
            )
            if direction == "long":
                conditions = [
                    "Close returns inside the previous Donchian range",
                    "Loss of breakout level",
                    "Failed retest accepts price back inside the previous range",
                    "Breakout candle is fully retraced",
                    "Volume disappears after breakout",
                    "Delta/OI reversal against continuation when available",
                ]
            else:
                conditions = [
                    "Close returns inside the previous Donchian range",
                    "Loss of breakout level",
                    "Failed retest accepts price back inside the previous range",
                    "Breakdown candle is fully retraced",
                    "Volume disappears after breakdown",
                    "Delta/OI reversal against continuation when available",
                ]
        elif signal.strategy == "liquidity_sweep_reversal":
            strategy_swept_level = _trade_plan_metadata_number(signal, "swept_level")
            swept_level = strategy_swept_level or (features.swing_low if direction == "long" else features.swing_high)
            strategy_sweep_extreme = _trade_plan_metadata_number(signal, "sweep_extreme")
            conservative_trigger = features.high if direction == "long" else features.low
            conservative_zone = _entry_zone_around_level(conservative_trigger, features.atr_14)
            wick_ratio = features.lower_wick_ratio if direction == "long" else features.upper_wick_ratio
            touch_count = features.swing_low_touch_count if direction == "long" else features.swing_high_touch_count
            level_volume_score = features.swing_low_volume_score if direction == "long" else features.swing_high_volume_score
            level_age = features.swing_low_age_candles if direction == "long" else features.swing_high_age_candles
            target_midpoint, target_boundary = _liquidity_sweep_range_targets(signal)
            metadata.update(
                {
                    "swept_low": features.swing_low,
                    "swept_high": features.swing_high,
                    "swept_level": swept_level,
                    "reclaim_level": swept_level if direction == "long" else None,
                    "rejection_level": swept_level if direction == "short" else None,
                    "sweep_extreme": strategy_sweep_extreme or (features.low if direction == "long" else features.high),
                    "wick_ratio": wick_ratio,
                    "level_touch_count": touch_count,
                    "level_volume_score": level_volume_score,
                    "level_age_candles": level_age,
                    "aggressive_entry": features.close,
                    "conservative_trigger": conservative_trigger,
                    "conservative_entry_min": conservative_zone[0],
                    "conservative_entry_max": conservative_zone[1],
                    "micro_bos_trigger": features.previous_high if direction == "long" else features.previous_low,
                    "close_position": _directional_close_location(signal.direction, features),
                    "volume_disappears_below": 1.0,
                    "target_midpoint": target_midpoint,
                    "target_opposite_boundary": target_boundary,
                    "requires_reclaim": _bool_param(context.strategy_params, "require_reclaim", True),
                }
            )
            if direction == "long":
                conditions = [
                    "Close returns below swept low",
                    "Sweep low is broken again",
                    "Next candles fail to hold reclaim",
                    "Volume disappears after reclaim",
                    "Price cannot reach range midpoint after reclaim",
                ]
            else:
                conditions = [
                    "Close returns above swept high",
                    "Sweep high is broken again",
                    "Next candles fail to hold rejection",
                    "Volume disappears after rejection",
                    "Price cannot reach range midpoint after rejection",
                ]
        else:
            conditions = ["Signal stop is reached", "Setup expires before confirmation"]

        return SignalInvalidationSnapshot(
            price=signal.stop_loss,
            hard_stop=signal.stop_loss,
            conditions=conditions,
            metadata=metadata,
        )


class ExitManagementLayer:
    def build(
        self,
        signal: StrategySignal,
        context: StrategyEvaluationContext,
    ) -> SignalExitPlanSnapshot:
        entry = _entry_price(signal)
        targets: list[dict[str, Any]] = []
        planned_targets = _planned_targets_by_label(signal)
        resolved_targets = TargetResolverService().resolve(
            direction=signal.direction,
            entry=entry,
            stop_loss=signal.stop_loss,
            features=context.signal_features,
            alpha_context=context.alpha_context,
            support_resistance_by_timeframe=context.support_resistance_by_timeframe,
            strategy_metadata=_target_strategy_metadata(signal),
            allow_r_multiple_fallback=_allow_r_multiple_fallback(context.strategy_params),
        )
        for label, price in (("TP1", signal.take_profit_1), ("TP2", signal.take_profit_2)):
            if price is None:
                continue
            r_multiple = _target_rr(signal, price)
            if r_multiple is None:
                continue
            action = "partial_close" if label == "TP1" else "reduce_and_keep_runner"
            close_percent = 40 if label == "TP1" else 30
            planned = planned_targets.get(label)
            metadata = dict(planned.metadata) if planned is not None else {}
            source = planned.source if planned is not None else None
            target_source = _target_source_for_resolver(
                source,
                metadata.get("market_target_source"),
                metadata.get("target_source"),
            )
            thesis = TargetResolverService().thesis_for_target(
                target_price=price,
                target_source=target_source,
                direction=signal.direction,
                entry=entry,
                stop_loss=signal.stop_loss,
                resolved=resolved_targets,
                close_percent=float(close_percent),
            )
            if thesis is not None:
                metadata = _metadata_with_target_thesis(metadata, thesis)
            targets.append(
                {
                    "label": label,
                    "price": price,
                    "r_multiple": r_multiple,
                    "action": action,
                    "close_percent": close_percent,
                    "source": source or (thesis.source if thesis is not None else None),
                    "thesis": thesis.model_dump(mode="json") if thesis is not None else None,
                    "metadata": metadata,
                }
            )
        if not targets:
            targets.extend(
                _exit_targets_from_resolved_theses(
                    theses=resolved_targets,
                    signal=signal,
                    entry=entry,
                )
            )
        if signal.strategy == "trend_pullback_continuation":
            if _strong_trend_for_runner(context.signal_features, context.context_features):
                runner_thesis = _runner_thesis(
                    signal=signal,
                    entry=entry,
                    stop_loss=signal.stop_loss,
                    resolved_targets=resolved_targets,
                )
                targets.append(
                    {
                        "label": "Runner",
                        "price": None,
                        "r_multiple": None,
                        "action": "runner_trailing",
                        "close_percent": "runner",
                        "source": "EMA20" if context.signal_features.ema_20 is not None else "ATR",
                        "thesis": runner_thesis.model_dump(mode="json") if runner_thesis is not None else None,
                        "metadata": _metadata_with_target_thesis(
                            {
                                "enabled_when": "strong_trend",
                                "runner_instruction": "trail_after_structure_continuation",
                                "trailing_source": "swing_or_vwap_structure"
                                if context.signal_features.vwap is not None
                                else "atr_fallback",
                                "fallback_trailing_used": context.signal_features.vwap is None,
                            },
                            runner_thesis,
                        ),
                    }
                )
        elif signal.strategy == "volatility_squeeze_breakout":
            measured_target = _measured_move_target(signal, context.signal_features)
            if (
                _bool_param(context.strategy_params, "measured_move_target_enabled", True)
                and measured_target is not None
            ):
                r_multiple = _target_rr(signal, measured_target)
                if r_multiple is not None:
                    thesis = TargetResolverService().thesis_for_target(
                        target_price=measured_target,
                        target_source="measured_move",
                        direction=signal.direction,
                        entry=entry,
                        stop_loss=signal.stop_loss,
                        resolved=resolved_targets,
                        close_percent=None,
                    )
                    targets.append(
                        {
                            "label": "Measured Move",
                            "price": measured_target,
                            "r_multiple": r_multiple,
                            "action": "measured_move_runner",
                            "close_percent": "runner",
                            "source": "range_measured_move",
                            "thesis": thesis.model_dump(mode="json") if thesis is not None else None,
                            "metadata": {
                                "range_high": context.signal_features.donchian_high_20,
                                "range_low": context.signal_features.donchian_low_20,
                                "entry_model": _trade_plan_entry_model(signal),
                                **_metadata_with_target_thesis({}, thesis),
                            },
                        }
                    )
        elif signal.strategy == "liquidity_sweep_reversal":
            runner_thesis = _runner_thesis(
                signal=signal,
                entry=entry,
                stop_loss=signal.stop_loss,
                resolved_targets=resolved_targets,
            )
            targets.append(
                {
                    "label": "Runner",
                    "price": None,
                    "r_multiple": None,
                    "action": "runner_trailing",
                    "close_percent": "runner",
                    "source": "micro_BOS_or_ATR_trailing",
                    "thesis": runner_thesis.model_dump(mode="json") if runner_thesis is not None else None,
                    "metadata": _metadata_with_target_thesis(
                        {
                            "runner_instruction": "trail_after_micro_bos_or_range_reclaim",
                            "trailing_source": "micro_bos_or_range_boundary",
                        },
                        runner_thesis,
                    ),
                }
            )

        breakeven = {}
        if entry is not None and targets:
            first_target = targets[0]
            breakeven = {
                "after": first_target.get("label", "TP1"),
                "stop_price": entry,
                "close_percent_before_move": first_target.get("close_percent", 40),
            }

        trailing = {
            "enabled_after": "TP1" if signal.strategy != "volatility_squeeze_breakout" else "ATR expansion",
            "source": (
                "EMA20"
                if signal.strategy == "trend_pullback_continuation" and context.signal_features.ema_20 is not None
                else "ATR" if context.signal_features.atr_14 is not None else "structure"
            ),
        }
        return SignalExitPlanSnapshot(targets=targets, breakeven=breakeven, trailing=trailing)

def _effective_candle_state(signal: StrategySignal, features: Features) -> str:
    if signal.candle_state == "open" or features.candle_state == "open":
        return "open"
    return "closed"


def _enrich_trade_plan_with_final_risk_reward(
    *,
    signal: StrategySignal,
    exit_plan: SignalExitPlanSnapshot,
    invalidation: SignalInvalidationSnapshot,
    params: Mapping[str, Any],
    rr_guard_context: str,
    trade_plan_enrichment: TradePlanEnrichmentService,
) -> tuple[TradePlan, RiskRewardAssessment, StrategySignal]:
    rr_service = RiskRewardAssessmentService()
    draft_risk_reward = rr_service.assess(signal, params, rr_guard_context)
    trade_plan = trade_plan_enrichment.enrich(
        signal=signal,
        exit_plan=exit_plan,
        invalidation=invalidation,
        risk_reward=draft_risk_reward,
    )
    signal_with_trade_plan = signal.model_copy(update={"trade_plan": trade_plan}, deep=True)
    risk_reward_signal = _signal_for_risk_reward_assessment(
        signal=signal,
        trade_plan=trade_plan,
    )
    risk_reward = rr_service.assess(risk_reward_signal, params, rr_guard_context)
    trade_plan = trade_plan_enrichment.enrich(
        signal=signal_with_trade_plan,
        exit_plan=exit_plan,
        invalidation=invalidation,
        risk_reward=risk_reward,
    )
    signal_with_trade_plan = signal_with_trade_plan.model_copy(
        update={"trade_plan": trade_plan},
        deep=True,
    )
    return trade_plan, risk_reward, signal_with_trade_plan


def _signal_for_risk_reward_assessment(
    *,
    signal: StrategySignal,
    trade_plan: TradePlan,
) -> StrategySignal:
    legacy_target_labels = {
        label
        for label, price in (
            ("TP1", signal.take_profit_1),
            ("TP2", signal.take_profit_2),
        )
        if price is not None
    }
    if not legacy_target_labels:
        return signal.model_copy(
            update={"trade_plan": _trade_plan_with_priced_rr_targets(trade_plan)},
            deep=True,
        )
    legacy_targets = [
        target
        for target in (signal.trade_plan.targets if signal.trade_plan is not None else [])
        if target.label.strip().upper() in legacy_target_labels
        and target.source == "legacy_fields"
    ]
    if not legacy_targets:
        return signal.model_copy(
            update={"trade_plan": _trade_plan_with_priced_rr_targets(trade_plan)},
            deep=True,
        )
    rr_trade_plan = trade_plan.model_copy(update={"targets": legacy_targets}, deep=True)
    return signal.model_copy(update={"trade_plan": rr_trade_plan}, deep=True)


def _trade_plan_with_priced_rr_targets(trade_plan: TradePlan) -> TradePlan:
    priced_targets = [target for target in trade_plan.targets if target.price is not None]
    if not priced_targets or len(priced_targets) == len(trade_plan.targets):
        return trade_plan
    return trade_plan.model_copy(update={"targets": priced_targets}, deep=True)


def _sync_trade_plan_entry(
    *,
    trade_plan: TradePlan,
    entry_min: float | None,
    entry_max: float | None,
) -> TradePlan:
    entry = trade_plan.entry.model_copy(
        update={
            "price": _entry_price_from_bounds(entry_min, entry_max),
            "min_price": entry_min,
            "max_price": entry_max,
        }
    )
    return trade_plan.model_copy(update={"entry": entry}, deep=True)


def _entry_price_from_bounds(entry_min: float | None, entry_max: float | None) -> float | None:
    if entry_min is not None and entry_max is not None:
        return (entry_min + entry_max) / 2
    return entry_min if entry_min is not None else entry_max


def _planned_targets_by_label(signal: StrategySignal) -> dict[str, TradePlanTarget]:
    if signal.trade_plan is None:
        return {}
    return {target.label: target for target in signal.trade_plan.targets}


def _target_strategy_metadata(signal: StrategySignal) -> dict[str, Any]:
    if signal.trade_plan is None:
        return {}
    metadata = {
        **signal.trade_plan.metadata,
        **signal.trade_plan.entry.metadata,
        **signal.trade_plan.risk_rules.metadata,
    }
    if signal.trade_plan.invalidation is not None:
        metadata.update(signal.trade_plan.invalidation.metadata)
    return metadata


def _allow_r_multiple_fallback(params: Mapping[str, Any]) -> bool:
    return _bool_param(params, "allow_r_multiple_fallback", False)


def _target_source_for_resolver(*values: Any) -> str | None:
    for value in values:
        if value is not None:
            return str(value)
    return None


def _metadata_with_target_thesis(
    metadata: dict[str, Any],
    thesis: TargetThesis | None,
) -> dict[str, Any]:
    if thesis is None:
        return metadata
    enriched = dict(metadata)
    thesis_payload = thesis.model_dump(mode="json")
    enriched["target_thesis"] = thesis_payload
    enriched["target_thesis_source"] = thesis.source
    enriched["market_target_source"] = thesis.source
    enriched["target_source"] = thesis.source
    enriched["target_confidence"] = thesis.confidence
    enriched["target_priority"] = thesis.priority
    if thesis.invalidation_hint is not None:
        enriched["target_invalidation_hint"] = thesis.invalidation_hint
    if thesis.source == "risk_multiple_fallback":
        enriched["fallback_target_used"] = True
        enriched["fallback_target_source"] = "r_multiple"
    return enriched


def _exit_targets_from_resolved_theses(
    *,
    theses: list[TargetThesis],
    signal: StrategySignal,
    entry: float | None,
) -> list[dict[str, Any]]:
    if entry is None:
        return []
    priced = [thesis for thesis in theses if thesis.price is not None]
    if not priced:
        return []
    selected = priced[:2]
    targets: list[dict[str, Any]] = []
    for index, thesis in enumerate(selected, start=1):
        label = f"TP{index}"
        action = _target_action_from_thesis(thesis, is_final=index == len(selected))
        close_percent = _target_close_percent_from_thesis(thesis, is_final=index == len(selected))
        targets.append(
            {
                "label": label,
                "price": thesis.price,
                "r_multiple": _target_rr(signal, thesis.price),
                "action": action,
                "close_percent": close_percent,
                "source": thesis.source,
                "thesis": thesis.model_dump(mode="json"),
                "metadata": _metadata_with_target_thesis(
                    {
                        "generated_by": "target_resolver",
                        "exit_policy": "market_targets",
                    },
                    thesis.model_copy(update={"close_percent": float(close_percent)}),
                ),
            }
        )
    return targets


def _runner_thesis(
    *,
    signal: StrategySignal,
    entry: float | None,
    stop_loss: float | None,
    resolved_targets: list[TargetThesis],
) -> TargetThesis | None:
    if entry is None:
        return None
    priced = [thesis for thesis in resolved_targets if thesis.price is not None]
    if not priced:
        return None
    furthest = max(
        priced,
        key=lambda thesis: float(thesis.metadata.get("distance") or 0.0),
    )
    metadata = {
        **furthest.metadata,
        "runner_used": True,
        "runner_source": furthest.source,
        "stop_loss_for_r": stop_loss,
        "strategy": signal.strategy,
    }
    return furthest.model_copy(update={"close_percent": None, "metadata": metadata})


def _target_action_from_thesis(thesis: TargetThesis, *, is_final: bool) -> str:
    if thesis.source in {"nearest_liquidity_pool", "range_midpoint"}:
        return "partial_close"
    if thesis.source in {"measured_move", "htf_support", "htf_resistance"}:
        return "full_close" if is_final else "reduce_and_keep_runner"
    if thesis.source in {"previous_day_high", "previous_day_low", "range_opposite_boundary"}:
        return "reduce_and_keep_runner"
    return "full_close" if is_final else "partial_close"


def _target_close_percent_from_thesis(thesis: TargetThesis, *, is_final: bool) -> float:
    if thesis.close_percent is not None:
        return thesis.close_percent
    if thesis.source in {"nearest_liquidity_pool", "range_midpoint"}:
        return 40.0
    if thesis.source in {"session_high", "session_low"}:
        return 50.0 if is_final else 35.0
    if thesis.source in {"previous_day_high", "previous_day_low", "range_opposite_boundary"}:
        return 60.0 if is_final else 40.0
    if thesis.source in {"htf_support", "htf_resistance"}:
        return 70.0 if is_final else 50.0
    if thesis.source == "measured_move":
        return 100.0 if is_final else 30.0
    return 60.0 if is_final else 40.0


def _trade_plan_entry_model(signal: StrategySignal) -> str | None:
    if signal.trade_plan is None:
        return None
    raw = signal.trade_plan.entry.metadata.get("entry_model")
    return str(raw) if raw is not None else None


def _breakout_classifier_checks(
    signal: StrategySignal,
    params: Mapping[str, Any],
) -> list[SignalLayerCheck]:
    if signal.strategy != "volatility_squeeze_breakout" or signal.trade_plan is None:
        return []

    accepted_score = _trade_plan_metadata_number(signal, "accepted_breakout_score")
    fakeout_score = _trade_plan_metadata_number(signal, "fakeout_risk_score")
    if accepted_score is None and fakeout_score is None:
        return []

    accepted_min = _strategy_numeric_param(
        params,
        "accepted_breakout_min_score",
        signal.strategy,
        0.55,
    )
    fakeout_max = _strategy_numeric_param(
        params,
        "fakeout_risk_max_score",
        signal.strategy,
        0.55,
    )
    retest_required = _trade_plan_metadata_bool(signal, "retest_required")
    metadata = {
        "accepted_breakout_score": accepted_score,
        "fakeout_risk_score": fakeout_score,
        "post_breakout_hold_score": _trade_plan_metadata_number(signal, "post_breakout_hold_score"),
        "retest_quality_score": _trade_plan_metadata_number(signal, "retest_quality_score"),
        "delta_expansion_score": _trade_plan_metadata_number(signal, "delta_expansion_score"),
        "oi_expansion_score": _trade_plan_metadata_number(signal, "oi_expansion_score"),
        "volume_acceptance_score": _trade_plan_metadata_number(signal, "volume_acceptance_score"),
        "failed_breakout_invalidation": _trade_plan_metadata_bool(signal, "failed_breakout_invalidation"),
        "retest_required": retest_required,
        "entry_model": _trade_plan_entry_model(signal),
        "entry_source": _trade_plan_metadata_string(signal, "entry_source"),
        "alpha_context_used": _trade_plan_metadata_bool(signal, "alpha_context_used"),
        "missing_alpha_sources": _trade_plan_metadata_list(signal, "missing_alpha_sources"),
        "accepted_breakout_min_score": accepted_min,
        "fakeout_risk_max_score": fakeout_max,
    }
    accepted_ok = accepted_score is None or accepted_score >= accepted_min
    fakeout_ok = fakeout_score is None or fakeout_score <= fakeout_max
    classifier_status = "passed" if accepted_ok and fakeout_ok else "warning"
    classifier_reason = (
        "Breakout acceptance classifier passed"
        if classifier_status == "passed"
        else "Breakout acceptance classifier requires more evidence before immediate entry"
    )
    checks = [
        SignalLayerCheck(
            name="breakout_acceptance_classifier",
            status=classifier_status,
            score=round(float(accepted_score or 0.0), 4),
            reason=classifier_reason,
            metadata=metadata,
        )
    ]
    if retest_required:
        checks.append(
            SignalLayerCheck(
                name="retest_required_after_large_breakout",
                status="warning",
                score=round(float(fakeout_score or 0.0), 4),
                reason=(
                    "Retest required after large or fakeout-prone breakout; "
                    "immediate breakout entry is not actionable"
                ),
                metadata={
                    **metadata,
                    "reason_code": "retest_required_after_large_breakout",
                    "source": "setup",
                    "scope": "discovery",
                },
            )
        )
    return checks


def _trend_pullback_checks(
    signal: StrategySignal,
    params: Mapping[str, Any],
) -> list[SignalLayerCheck]:
    if signal.strategy != "trend_pullback_continuation" or signal.trade_plan is None:
        return []

    structural_zone = _trade_plan_metadata_dict(signal, "structural_pullback_zone")
    continuation_score = _trade_plan_metadata_number(signal, "continuation_score")
    min_continuation_score = _trade_plan_metadata_number(signal, "min_continuation_score")
    if min_continuation_score is None:
        min_continuation_score = _strategy_numeric_param(
            params,
            "min_continuation_score",
            signal.strategy,
            0.45,
        )
    exhaustion_score = _trade_plan_metadata_number(signal, "exhaustion_score")
    max_exhaustion_score = _trade_plan_metadata_number(signal, "max_exhaustion_score")
    if max_exhaustion_score is None:
        max_exhaustion_score = _strategy_numeric_param(
            params,
            "max_exhaustion_score",
            signal.strategy,
            0.70,
        )
    crowded_score = _trade_plan_metadata_number(signal, "crowded_trade_score")
    htf_distance_r = _trade_plan_metadata_number(signal, "nearest_htf_target_distance_r")
    min_htf_distance_r = _trade_plan_metadata_number(signal, "min_htf_target_distance_r")
    if min_htf_distance_r is None:
        min_htf_distance_r = _strategy_numeric_param(
            params,
            "min_htf_target_distance_r",
            signal.strategy,
            0.0,
        )
    require_structural_zone = bool(_trade_plan_metadata_bool(signal, "require_structural_zone"))
    structural_zone_ok = _trade_plan_metadata_bool(signal, "structural_zone_ok")
    delta_confirmed = _trade_plan_metadata_bool(signal, "delta_confirmed")
    absorption_confirmed = _trade_plan_metadata_bool(signal, "absorption_confirmed")
    reclaimed_zone = _trade_plan_metadata_bool(signal, "reclaimed_pullback_zone")
    crowded_hard_block = bool(_trade_plan_metadata_bool(signal, "crowded_trade_hard_block"))

    checks: list[SignalLayerCheck] = []
    structural_failed = require_structural_zone and structural_zone_ok is False
    if structural_zone is not None or require_structural_zone:
        checks.append(
            SignalLayerCheck(
                name="trend_structural_zone",
                status="failed" if structural_failed else "passed",
                score=_number_or_none(structural_zone.get("quality_score")) if structural_zone else None,
                reason=(
                    "Trend pullback requires VWAP/liquidity/HTF structure; EMA-only fallback is not enough"
                    if structural_failed
                    else "Trend pullback structural zone is available"
                ),
                metadata={
                    "reason_code": "trend_structural_zone",
                    "source": "setup",
                    "scope": "discovery",
                    "structural_pullback_zone": structural_zone,
                    "require_structural_zone": require_structural_zone,
                    "structural_zone_ok": structural_zone_ok,
                },
            )
        )

    if continuation_score is not None:
        continuation_ok = continuation_score >= min_continuation_score
        checks.append(
            SignalLayerCheck(
                name="trend_continuation_confirmation",
                status="passed" if continuation_ok else "warning",
                score=round(continuation_score, 4),
                reason=(
                    "Trend pullback continuation confirmation passed"
                    if continuation_ok
                    else "Trend pullback continuation needs stronger reclaim, absorption, delta or volume evidence"
                ),
                metadata={
                    "reason_code": "trend_continuation_confirmation",
                    "source": "setup",
                    "scope": "discovery",
                    "continuation_score": continuation_score,
                    "min_continuation_score": min_continuation_score,
                    "delta_confirmed": delta_confirmed,
                    "absorption_confirmed": absorption_confirmed,
                    "reclaimed_pullback_zone": reclaimed_zone,
                    "missing_alpha_sources": _trade_plan_metadata_list(signal, "missing_alpha_sources"),
                },
            )
        )

    if exhaustion_score is not None:
        exhaustion_failed = exhaustion_score > max_exhaustion_score
        checks.append(
            SignalLayerCheck(
                name="trend_exhaustion",
                status="failed" if exhaustion_failed else "passed",
                score=round(exhaustion_score, 4),
                reason=(
                    f"Trend exhaustion score {exhaustion_score:.2f} exceeds {max_exhaustion_score:.2f}"
                    if exhaustion_failed
                    else "Trend exhaustion filter passed"
                ),
                metadata={
                    "reason_code": "trend_exhaustion",
                    "source": "setup",
                    "scope": "discovery",
                    "exhaustion_score": exhaustion_score,
                    "max_exhaustion_score": max_exhaustion_score,
                    "exhaustion_reasons": _trade_plan_metadata_list(signal, "exhaustion_reasons"),
                },
            )
        )

    if crowded_score is not None and crowded_score > 0:
        checks.append(
            SignalLayerCheck(
                name="trend_crowded_trade",
                status="failed" if crowded_hard_block else "warning",
                score=round(crowded_score, 4),
                reason=(
                    "Crowded funding/OI pressure is configured as a hard trend-pullback block"
                    if crowded_hard_block
                    else "Crowded funding/OI pressure penalizes trend continuation quality"
                ),
                metadata={
                    "reason_code": "trend_crowded_trade",
                    "source": "risk",
                    "scope": "discovery",
                    "crowded_trade_score": crowded_score,
                    "crowded_trade_reasons": _trade_plan_metadata_list(signal, "crowded_trade_reasons"),
                    "funding_pressure": _trade_plan_metadata_number(signal, "funding_pressure"),
                    "funding_rate": _trade_plan_metadata_number(signal, "funding_rate"),
                    "oi_delta": _trade_plan_metadata_number(signal, "oi_delta"),
                },
            )
        )

    if htf_distance_r is not None and min_htf_distance_r > 0:
        target_too_close = htf_distance_r < min_htf_distance_r
        hard_block = _bool_param(params, "block_near_htf_target", False)
        checks.append(
            SignalLayerCheck(
                name="trend_htf_target_room",
                status="failed" if target_too_close and hard_block else "warning" if target_too_close else "passed",
                score=round(htf_distance_r, 4),
                reason=(
                    f"Nearest HTF/liquidity target is {htf_distance_r:.2f}R away, below {min_htf_distance_r:.2f}R"
                    if target_too_close
                    else "HTF/liquidity target room is sufficient"
                ),
                metadata={
                    "reason_code": "trend_htf_target_room",
                    "source": "setup",
                    "scope": "discovery",
                    "nearest_htf_target_distance_r": htf_distance_r,
                    "min_htf_target_distance_r": min_htf_distance_r,
                    "nearest_htf_target": _trade_plan_metadata_number(signal, "nearest_htf_target"),
                    "nearest_htf_target_source": _trade_plan_metadata_string(signal, "nearest_htf_target_source"),
                },
            )
        )
    return checks


def _trade_plan_metadata_number(signal: StrategySignal, key: str) -> float | None:
    if signal.trade_plan is None:
        return None
    for metadata in _trade_plan_metadata_sources(signal):
        value = _number_or_none(metadata.get(key))
        if value is not None:
            return value
    return None


def _trade_plan_metadata_dict(signal: StrategySignal, key: str) -> dict[str, Any] | None:
    for metadata in _trade_plan_metadata_sources(signal):
        value = metadata.get(key)
        if isinstance(value, dict):
            return dict(value)
    return None


def _trade_plan_metadata_bool(signal: StrategySignal, key: str) -> bool | None:
    for metadata in _trade_plan_metadata_sources(signal):
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return None


def _trade_plan_metadata_list(signal: StrategySignal, key: str) -> list[Any]:
    for metadata in _trade_plan_metadata_sources(signal):
        value = metadata.get(key)
        if isinstance(value, list):
            return list(value)
    return []


def _trade_plan_metadata_string(signal: StrategySignal, key: str) -> str | None:
    for metadata in _trade_plan_metadata_sources(signal):
        value = metadata.get(key)
        if value is not None:
            return str(value)
    return None


def _trade_plan_metadata_sources(signal: StrategySignal) -> list[dict[str, Any]]:
    if signal.trade_plan is None:
        return []
    metadata_sources = [
        signal.trade_plan.entry.metadata,
        signal.trade_plan.metadata,
        signal.trade_plan.risk_rules.metadata,
    ]
    if signal.trade_plan.invalidation is not None:
        metadata_sources.append(signal.trade_plan.invalidation.metadata)
    return metadata_sources


def _liquidity_sweep_range_targets(signal: StrategySignal) -> tuple[float | None, float | None]:
    if signal.trade_plan is None:
        return signal.take_profit_1, signal.take_profit_2
    midpoint = None
    boundary = None
    for target in signal.trade_plan.targets:
        source = target.source or ""
        if source == "range_midpoint" and midpoint is None:
            midpoint = target.price
        if source not in {"range_midpoint", "legacy_fields"} and boundary is None:
            boundary = target.price
    return midpoint or signal.take_profit_1, boundary or signal.take_profit_2


def _strong_trend_for_runner(
    signal_features: Features,
    context_features: Features | None,
) -> bool:
    features = context_features or signal_features
    if features.adx is not None and features.adx >= 30:
        return True
    return bool(features.adx_rising and features.ema_50 is not None and features.ema_200 is not None)


def _apply_regime_score(signal: StrategySignal, regime: MarketRegimeSnapshot) -> StrategySignal:
    if regime.score_adjustment == 0:
        return signal
    breakdown = signal.score_breakdown
    if regime.score_adjustment > 0:
        breakdown = breakdown.model_copy(
            update={"trend_score": breakdown.trend_score + regime.score_adjustment}
        )
    else:
        breakdown = breakdown.model_copy(
            update={"overheat_penalty": breakdown.overheat_penalty + abs(regime.score_adjustment)}
        )
    score = score_from_breakdown(breakdown)
    return signal.model_copy(
        update={
            "score": score,
            "confidence": min(1.0, max(0.0, score / 100)),
            "score_breakdown": breakdown.model_copy(update={"total": score}),
        }
    )


def _pair_tier(symbol: str) -> str:
    base = _base_asset(symbol)
    if base in MAJOR_BASE_ASSETS:
        return "major"
    if base in LOW_LIQUIDITY_BASE_ASSETS:
        return "low_liquidity"
    return "mid_alt"


def _base_asset(symbol: str) -> str:
    value = symbol.replace("/", "").replace(":PERP", "").upper()
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if value.endswith(quote) and len(value) > len(quote):
            return value[: -len(quote)]
    return value


def _rough_chart_score(features: Features) -> float:
    atr = features.atr_14
    if atr is None or atr <= 0:
        return 0.0
    candle_range = max(features.high - features.low, 0.0)
    wick_pressure = (features.upper_wick_ratio or 0.0) + (features.lower_wick_ratio or 0.0)
    return candle_range / atr + max(0.0, wick_pressure - 1.1)


def _has_gap_or_illiquid_pump(features: Features) -> bool:
    return abs(features.price_change_1m) > 0.08 and features.volume_spike < 1.2


def _quality_profile(tier: str, params: Mapping[str, Any]) -> dict[str, float]:
    profile = dict(QUALITY_DEFAULTS_BY_TIER.get(tier, QUALITY_DEFAULTS_BY_TIER["unknown"]))
    tier_overrides = params.get("quality_tiers")
    if isinstance(tier_overrides, Mapping):
        override = tier_overrides.get(tier)
        if isinstance(override, Mapping):
            profile.update(_numeric_mapping(override))
    profile.update(
        _numeric_mapping(
            {
                "min_24h_volume_quote": params.get("min_24h_volume_quote"),
                "max_spread_bps": params.get("max_spread_bps"),
                "rough_chart_fail": params.get("rough_chart_fail"),
            }
        )
    )
    return profile


def _numeric_mapping(values: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in values.items():
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            result[key] = number
    return result


def _bool_param(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _pipeline_settings(context: StrategyEvaluationContext) -> Mapping[str, Any]:
    return context.pipeline_settings or context.strategy_params


def _is_production_mode(params: Mapping[str, Any]) -> bool:
    if _bool_param(params, "production_mode", False):
        return True
    signal_mode = params.get("signal_mode")
    if isinstance(signal_mode, str):
        return signal_mode.strip().lower() == "production"
    return False


def _optional_positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _optional_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _primary_context_features(context: StrategyEvaluationContext) -> Features | None:
    expected = context_timeframe_for(context.signal_features.timeframe, context.strategy_params)
    if expected:
        features = context.context_features_by_timeframe.get(expected)
        if features is not None:
            return features
    return context.context_features


def _primary_support_resistance(context: StrategyEvaluationContext) -> SupportResistanceSnapshot | None:
    expected = context_timeframe_for(context.signal_features.timeframe, context.strategy_params)
    if expected:
        snapshot = context.support_resistance_by_timeframe.get(expected)
        if snapshot is not None:
            return snapshot
    if context.context_features is not None:
        return context.support_resistance_by_timeframe.get(context.context_features.timeframe)
    return None


def _macro_context_features(context: StrategyEvaluationContext) -> Features | None:
    expected = MACRO_CONTEXT_TIMEFRAME_BY_SIGNAL.get(context.signal_features.timeframe)
    if expected:
        return context.context_features_by_timeframe.get(expected)
    return None


def _context_timeframe_override(timeframe: str, strategy_params: Mapping[str, Any]) -> str | None:
    raw_map = strategy_params.get("context_timeframe_map")
    if not isinstance(raw_map, Mapping):
        return None
    raw_value = raw_map.get(timeframe)
    if raw_value is None:
        return None
    value = str(raw_value).strip().lower()
    if value in {"", "default"}:
        return None
    allowed_timeframes = (
        set(CONTEXT_TIMEFRAME_BY_SIGNAL)
        | set(CONTEXT_TIMEFRAME_BY_SIGNAL.values())
        | set(MACRO_CONTEXT_TIMEFRAME_BY_SIGNAL.values())
    )
    if value in allowed_timeframes:
        return value
    return None


def _regime_score_adjustment(strategy: str, alignment: str, strength: str) -> int:
    if strategy == "trend_pullback_continuation":
        if alignment == "aligned":
            return 10
        if alignment == "against" and strength == "strong":
            return -25
        if alignment == "against":
            return -20
        return 0
    if alignment == "aligned" and strength == "strong":
        return 8
    if alignment == "aligned":
        return 5
    if alignment == "against" and strength == "strong":
        return -25
    if alignment == "against":
        return -12
    return 0


def _liquidity_sweep_context_level_check(
    *,
    signal: StrategySignal,
    signal_features: Features,
    context_features: Features,
    support_resistance: SupportResistanceSnapshot | None,
    tolerance_atr: float,
    min_strength: float,
) -> tuple[SignalLayerCheck, int]:
    direction = signal.direction.lower()
    swept_level = signal_features.swing_low if direction == "long" else signal_features.swing_high
    if swept_level is None:
        return (
            SignalLayerCheck(
                name="sweep_htf_level_confluence",
                status="skipped",
                reason="Swept level is unavailable for higher-timeframe confluence",
            ),
            0,
        )
    atr = signal_features.atr_14 or context_features.atr_14
    if atr is None or atr <= 0:
        return (
            SignalLayerCheck(
                name="sweep_htf_level_confluence",
                status="skipped",
                reason="ATR is unavailable for higher-timeframe level confluence",
            ),
            0,
        )

    tolerance = max(atr * tolerance_atr, abs(swept_level) * 0.0005)
    level_kind = "support" if direction == "long" else "resistance"
    if support_resistance is not None:
        matches = [
            level
            for level in support_resistance.levels
            if level.kind == level_kind
            and level.strength >= min_strength
            and abs(level.price - swept_level) <= tolerance
        ]
        if matches:
            level = max(matches, key=lambda item: (item.strength, item.retest_count))
            return (
                SignalLayerCheck(
                    name="sweep_htf_level_confluence",
                    status="passed",
                    score=round(level.strength, 3),
                    reason=(
                        f"Swept level {swept_level:.8f} aligns with {support_resistance.timeframe} "
                        f"S/R {level_kind} {level.price:.8f}; strength {level.strength:.0f}, "
                        f"retests {level.retest_count}, volume x{level.volume_score:.2f}"
                    ),
                    metadata={
                        "swept_level": swept_level,
                        "context_level": level.price,
                        "context_timeframe": support_resistance.timeframe,
                        "strength": level.strength,
                        "retests": level.retest_count,
                    },
                ),
                10,
            )

    fallback_levels = (
        (context_features.swing_low, context_features.donchian_low_20)
        if direction == "long"
        else (context_features.swing_high, context_features.donchian_high_20)
    )
    confluence_levels = [level for level in fallback_levels if level is not None and abs(level - swept_level) <= tolerance]
    if confluence_levels:
        level = min(confluence_levels, key=lambda value: abs(value - swept_level))
        return (
            SignalLayerCheck(
                name="sweep_htf_level_confluence",
                status="passed",
                score=round(abs(level - swept_level) / atr, 3),
                reason=(
                    f"Swept level {swept_level:.8f} aligns with {context_features.timeframe} "
                    f"{level_kind} {level:.8f}"
                ),
                metadata={
                    "swept_level": swept_level,
                    "context_level": level,
                    "context_timeframe": context_features.timeframe,
                },
            ),
            10,
        )

    return (
        SignalLayerCheck(
            name="sweep_htf_level_confluence",
            status="skipped",
            reason=f"No higher-timeframe {level_kind} confluence near swept level {swept_level:.8f}",
        ),
        0,
    )


def _macro_regime_score_adjustment(strategy: str, alignment: str, strength: str) -> int:
    if strategy == "trend_pullback_continuation":
        if alignment == "against" and strength == "strong":
            return -12
        if alignment == "against":
            return -6
        return 0
    if alignment == "aligned" and strength == "strong":
        return 3
    if alignment == "against" and strength == "strong":
        return -12
    if alignment == "against":
        return -6
    return 0


def _context_obstacle_check(
    *,
    signal: StrategySignal,
    signal_features: Features,
    context_features: Features,
    support_resistance: SupportResistanceSnapshot | None,
    min_atr: float,
    min_strength: float,
    max_obstacle_distance_r: float | None = None,
) -> tuple[SignalLayerCheck, int]:
    entry = _entry_price(signal) or signal_features.close
    atr = signal_features.atr_14 or context_features.atr_14
    if atr is None or atr <= 0:
        return (
            SignalLayerCheck(
                name="context_obstacle",
                status="skipped",
                reason="ATR is unavailable for context support/resistance distance",
            ),
            0,
        )

    if support_resistance is not None:
        check_name = "context_resistance" if signal.direction.lower() == "long" else "context_support"
        level_kind = "resistance" if signal.direction.lower() == "long" else "support"
        level = support_resistance.nearest_obstacle_between(
            direction=signal.direction,
            entry=entry,
            target=signal.take_profit_1,
            min_strength=min_strength,
        ) or support_resistance.nearest_obstacle(
            direction=signal.direction,
            entry=entry,
            min_strength=min_strength,
        )
        if level is None:
            return (
                SignalLayerCheck(
                    name=check_name,
                    status="passed",
                    reason=(
                        f"No {support_resistance.timeframe} S/R {level_kind} near entry "
                        f"with strength >= {min_strength:.0f}"
                    ),
                ),
                0,
            )
        distance_atr = (
            (level.price - entry) / atr
            if signal.direction.lower() == "long"
            else (entry - level.price) / atr
        )
        before_target = _level_before_target(signal, entry, level.price)
        distance_r = _distance_r(signal, entry, level.price)
        status = _obstacle_status(
            distance_atr=distance_atr,
            min_atr=min_atr,
            distance_r=distance_r,
            max_obstacle_distance_r=max_obstacle_distance_r,
            before_target=before_target,
        )
        target_context = " before TP1" if before_target else ""
        distance_r_context = "" if distance_r is None else f", {distance_r:.2f}R"
        return (
            SignalLayerCheck(
                name=check_name,
                status=status,
                score=round(distance_atr, 3),
                reason=(
                    f"{support_resistance.timeframe} S/R {level_kind} {level.price:.8f} "
                    f"is {distance_atr:.2f} ATR{distance_r_context} from entry{target_context}; "
                    f"strength {level.strength:.0f}, "
                    f"retests {level.retest_count}, age {level.age_candles} candles, "
                    f"volume x{level.volume_score:.2f}"
                ),
                metadata={
                    "level": level.price,
                    "distance_atr": round(distance_atr, 4),
                    "distance_r": None if distance_r is None else round(distance_r, 4),
                    "before_tp1": before_target,
                },
            ),
            -8 if status == "warning" else 0,
        )

    if signal.direction.lower() == "long":
        levels = _levels_above(
            entry,
            context_features.swing_high,
            context_features.donchian_high_20,
        )
        if not levels:
            return (
                SignalLayerCheck(
                    name="context_resistance",
                    status="passed",
                    reason=f"No higher-timeframe resistance above entry in {context_features.timeframe}",
                ),
                0,
            )
        level = min(levels)
        distance_atr = (level - entry) / atr
        before_target = _level_before_target(signal, entry, level)
        distance_r = _distance_r(signal, entry, level)
        status = _obstacle_status(
            distance_atr=distance_atr,
            min_atr=min_atr,
            distance_r=distance_r,
            max_obstacle_distance_r=max_obstacle_distance_r,
            before_target=before_target,
        )
        target_context = " before TP1" if before_target else ""
        return (
            SignalLayerCheck(
                name="context_resistance",
                status=status,
                score=round(distance_atr, 3),
                reason=(
                    f"{context_features.timeframe} resistance is {distance_atr:.2f} ATR above entry{target_context}"
                ),
                metadata={
                    "level": level,
                    "distance_atr": round(distance_atr, 4),
                    "distance_r": None if distance_r is None else round(distance_r, 4),
                    "before_tp1": before_target,
                },
            ),
            -8 if status == "warning" else 0,
        )

    levels = _levels_below(
        entry,
        context_features.swing_low,
        context_features.donchian_low_20,
    )
    if not levels:
        return (
            SignalLayerCheck(
                name="context_support",
                status="passed",
                reason=f"No higher-timeframe support below entry in {context_features.timeframe}",
            ),
            0,
        )
    level = max(levels)
    distance_atr = (entry - level) / atr
    before_target = _level_before_target(signal, entry, level)
    distance_r = _distance_r(signal, entry, level)
    status = _obstacle_status(
        distance_atr=distance_atr,
        min_atr=min_atr,
        distance_r=distance_r,
        max_obstacle_distance_r=max_obstacle_distance_r,
        before_target=before_target,
    )
    target_context = " before TP1" if before_target else ""
    return (
        SignalLayerCheck(
            name="context_support",
            status=status,
            score=round(distance_atr, 3),
            reason=f"{context_features.timeframe} support is {distance_atr:.2f} ATR below entry{target_context}",
            metadata={
                "level": level,
                "distance_atr": round(distance_atr, 4),
                "distance_r": None if distance_r is None else round(distance_r, 4),
                "before_tp1": before_target,
            },
        ),
        -8 if status == "warning" else 0,
    )


def _levels_above(entry: float, *levels: float | None) -> list[float]:
    return [level for level in levels if level is not None and level > entry]


def _levels_below(entry: float, *levels: float | None) -> list[float]:
    return [level for level in levels if level is not None and level < entry]


def _level_before_target(signal: StrategySignal, entry: float, level: float) -> bool:
    target = signal.take_profit_1
    if target is None:
        return False
    if signal.direction.lower() == "long":
        return entry < level <= target
    return target <= level < entry


def _distance_r(signal: StrategySignal, entry: float, level: float) -> float | None:
    if signal.stop_loss is None:
        return None
    risk = abs(entry - signal.stop_loss)
    if risk <= 0:
        return None
    if level == entry:
        return 0.0
    side = "long" if level >= entry else "short"
    synthetic_stop = entry - risk if side == "long" else entry + risk
    return risk_reward_plan_service.calculate_rr(
        entry,
        synthetic_stop,
        level,
        side,
    ).rr_value


def _obstacle_status(
    *,
    distance_atr: float,
    min_atr: float,
    distance_r: float | None,
    max_obstacle_distance_r: float | None,
    before_target: bool,
) -> str:
    if before_target:
        return "warning"
    if distance_atr <= min_atr:
        return "warning"
    if (
        max_obstacle_distance_r is not None
        and distance_r is not None
        and distance_r <= max_obstacle_distance_r
    ):
        return "warning"
    return "passed"


def _has_strong_regime_conflict(regime: MarketRegimeSnapshot) -> bool:
    if regime.alignment == "against" and regime.strength == "strong":
        return True
    return any(
        check.name == "macro_regime_alignment"
        and check.status == "warning"
        and check.reason is not None
        and "strong" in check.reason
        for check in regime.checks
    )


def _has_context_obstacle(regime: MarketRegimeSnapshot) -> bool:
    return any(
        check.name in {"context_resistance", "context_support"}
        and check.status == "warning"
        for check in regime.checks
    )


def _has_severe_ema200_chop(regime: MarketRegimeSnapshot) -> bool:
    return any(check.name == "ema200_chop" and check.status == "failed" for check in regime.checks)


def _has_borderline_ema200_chop(regime: MarketRegimeSnapshot) -> bool:
    return any(check.name == "ema200_chop" and check.status == "warning" for check in regime.checks)


def _ema200_chop_check(signal: StrategySignal, features: Features) -> tuple[SignalLayerCheck, int]:
    score = features.ema_200_chop_score
    if score is None:
        return (
            SignalLayerCheck(
                name="ema200_chop",
                status="skipped",
                reason="EMA200 chop metrics are unavailable",
            ),
            0,
        )

    severe = score >= 70 or features.ema_200_cross_count_50 >= 4
    borderline = score >= 45 or features.ema_200_cross_count_50 >= 3
    status = "failed" if severe else "warning" if borderline else "passed"
    reason = (
        f"EMA200 chop score {score:.1f}: {features.ema_200_cross_count_50} crosses in 50 candles, "
        f"near-ratio {_format_optional_ratio(features.ema_200_near_ratio_50)}, "
        f"slope {_format_optional_float(features.ema_200_slope_atr_20)} ATR"
    )
    adjustment = 0
    if signal.strategy in TREND_STRATEGIES:
        if severe:
            adjustment = -20
        elif borderline:
            adjustment = -15
    return (
        SignalLayerCheck(
            name="ema200_chop",
            status=status,
            score=round(score, 3),
            reason=reason,
            metadata={
                "cross_count_50": features.ema_200_cross_count_50,
                "near_ratio_50": features.ema_200_near_ratio_50,
                "slope_atr_20": features.ema_200_slope_atr_20,
                "chop_score": score,
                "strategy_adjustment": adjustment,
            },
        ),
        adjustment,
    )


def _format_optional_ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _format_optional_float(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _trend_direction(features: Features) -> str:
    if features.ema_50 is None or features.ema_200 is None:
        return "unknown"
    if features.close > features.ema_200 and features.ema_50 >= features.ema_200:
        return "bullish"
    if features.close < features.ema_200 and features.ema_50 <= features.ema_200:
        return "bearish"
    return "range"


def _trend_strength(features: Features) -> str:
    if features.adx is None and features.atr_14 is None:
        return "unknown"
    strong_by_adx = features.adx is not None and features.adx >= 30
    strong_by_ema_distance = False
    if features.ema_50 is not None and features.ema_200 is not None and features.atr_14:
        strong_by_ema_distance = abs(features.ema_50 - features.ema_200) >= features.atr_14
    if strong_by_adx or (features.adx_rising and strong_by_ema_distance):
        return "strong"
    if features.adx is not None and features.adx < 15:
        return "weak"
    return "normal"


def _alignment(side: str, direction: str) -> str:
    if direction == "unknown":
        return "unknown"
    if direction == "range":
        return "mixed"
    if side == "long" and direction == "bullish":
        return "aligned"
    if side == "short" and direction == "bearish":
        return "aligned"
    return "against"


def _assess_overextension(
    signal: StrategySignal,
    features: Features,
    params: Mapping[str, Any],
) -> OverextensionAssessment:
    atr = features.atr_14
    body_threshold = _dynamic_body_atr_threshold(signal, features, params)
    range_threshold = _dynamic_range_atr_threshold(signal, features, params)
    if atr is None or atr <= 0:
        return OverextensionAssessment(
            overextended=False,
            body_atr=0.0,
            range_atr=0.0,
            body_threshold=body_threshold,
            range_threshold=range_threshold,
            reason="ATR is unavailable; overextension guard skipped",
            pullback_target=PullbackTarget(
                price=None,
                label="ATR unavailable",
                source="unavailable",
            ),
        )

    candle_range = max(features.high - features.low, 0.0)
    body = abs(features.close - features.open)
    body_atr = body / atr
    range_atr = candle_range / atr if candle_range > 0 else 0.0
    body_ratio = body / candle_range if candle_range > 0 else 0.0
    close_location = _directional_close_location(signal.direction, features)
    directional_body = _is_directional_body(signal.direction, features)
    rejection_wick = _rejection_wick_ratio(signal.direction, features)
    pullback_target = _pullback_target(signal, features)

    body_overextended = directional_body and body_atr > body_threshold
    impulse_range_overextended = (
        range_atr > range_threshold
        and body_ratio >= 0.55
        and close_location >= EXTREME_CLOSE_LOCATION
    )
    rejection_wick_overextended = (
        rejection_wick >= REJECTION_WICK_RATIO
        and range_atr > max(2.2, range_threshold * 0.75)
    )

    if body_overextended:
        reason = (
            f"Signal candle body is {body_atr:.2f} ATR, above dynamic limit "
            f"{body_threshold:.2f} ATR; wait for pullback to {pullback_target.label}"
        )
    elif impulse_range_overextended:
        reason = (
            f"Signal candle range is {range_atr:.2f} ATR with an impulse close near the extreme; "
            f"wait for retest of {pullback_target.label}"
        )
    elif rejection_wick_overextended:
        reason = (
            f"Signal candle has a {rejection_wick:.0%} rejection wick and {range_atr:.2f} ATR range; "
            f"wait for fresh reclaim or pullback to {pullback_target.label}"
        )
    else:
        reason = (
            f"Overextension guard passed: body {body_atr:.2f} ATR, "
            f"range {range_atr:.2f} ATR"
        )

    return OverextensionAssessment(
        overextended=body_overextended or impulse_range_overextended or rejection_wick_overextended,
        body_atr=body_atr,
        range_atr=range_atr,
        body_threshold=body_threshold,
        range_threshold=range_threshold,
        reason=reason,
        pullback_target=pullback_target,
    )


def _dynamic_body_atr_threshold(
    signal: StrategySignal,
    features: Features,
    params: Mapping[str, Any],
) -> float:
    base = _strategy_numeric_param(
        params,
        "max_body_atr",
        signal.strategy,
        MAX_BODY_ATR_BY_STRATEGY.get(signal.strategy, 2.5),
    )
    threshold = base
    atr_pct = _atr_percent(features)
    _, body_ratio = _candle_shape(features)

    if atr_pct >= 0.025:
        threshold -= 0.25
    elif atr_pct >= 0.015:
        threshold -= 0.15
    elif atr_pct <= 0.004:
        threshold += 0.1

    if features.atr_increasing:
        threshold -= 0.1
    if features.volume_spike >= 2.5:
        threshold -= 0.15
    if (
        body_ratio >= IMPULSE_BODY_RATIO
        and _directional_close_location(signal.direction, features) >= EXTREME_CLOSE_LOCATION
    ):
        threshold -= 0.2
    if _is_liquidity_absorption_pattern(signal, features):
        threshold += 0.2

    return max(MIN_DYNAMIC_BODY_ATR, min(base + 0.25, threshold))


def _dynamic_range_atr_threshold(
    signal: StrategySignal,
    features: Features,
    params: Mapping[str, Any],
) -> float:
    base = _strategy_numeric_param(
        params,
        "max_range_atr",
        signal.strategy,
        MAX_RANGE_ATR_BY_STRATEGY.get(signal.strategy, 3.5),
    )
    threshold = base
    atr_pct = _atr_percent(features)
    if atr_pct >= 0.025:
        threshold -= 0.25
    elif atr_pct >= 0.015:
        threshold -= 0.15
    if features.atr_increasing and features.volume_spike >= 2.5:
        threshold -= 0.15
    if _is_liquidity_absorption_pattern(signal, features):
        threshold += 0.6
    return max(2.5, threshold)


def _strategy_numeric_param(
    params: Mapping[str, Any],
    key: str,
    strategy: str,
    default: float,
) -> float:
    value = params.get(key)
    if isinstance(value, Mapping):
        value = value.get(strategy, value.get("default"))
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _atr_percent(features: Features) -> float:
    if features.atr_14 is None or features.atr_14 <= 0 or features.close == 0:
        return 0.0
    return features.atr_14 / abs(features.close)


def _candle_shape(features: Features) -> tuple[float, float]:
    candle_range = max(features.high - features.low, 0.0)
    if candle_range <= 0:
        return 0.0, 0.0
    body = abs(features.close - features.open)
    return candle_range, body / candle_range


def _is_directional_body(direction: str, features: Features) -> bool:
    side = direction.lower()
    if side == "long":
        return features.close > features.open
    if side == "short":
        return features.close < features.open
    return False


def _directional_close_location(direction: str, features: Features) -> float:
    candle_range = max(features.high - features.low, 0.0)
    if candle_range <= 0:
        return 0.0
    if direction.lower() == "long":
        return max(0.0, min(1.0, (features.close - features.low) / candle_range))
    if direction.lower() == "short":
        return max(0.0, min(1.0, (features.high - features.close) / candle_range))
    return 0.0


def _rejection_wick_ratio(direction: str, features: Features) -> float:
    candle_range = max(features.high - features.low, 0.0)
    if candle_range <= 0:
        return 0.0
    if direction.lower() == "long":
        return features.upper_wick_ratio if features.upper_wick_ratio is not None else (
            features.high - max(features.open, features.close)
        ) / candle_range
    if direction.lower() == "short":
        return features.lower_wick_ratio if features.lower_wick_ratio is not None else (
            min(features.open, features.close) - features.low
        ) / candle_range
    return 0.0


def _is_liquidity_absorption_pattern(signal: StrategySignal, features: Features) -> bool:
    if signal.strategy != "liquidity_sweep_reversal":
        return False
    if signal.direction.lower() == "long":
        return (features.lower_wick_ratio or 0.0) >= 0.45
    if signal.direction.lower() == "short":
        return (features.upper_wick_ratio or 0.0) >= 0.45
    return False


def _overextension_metadata(overextension: OverextensionAssessment) -> dict[str, Any]:
    target = overextension.pullback_target
    return {
        "body_atr": overextension.body_atr,
        "range_atr": overextension.range_atr,
        "body_threshold": overextension.body_threshold,
        "range_threshold": overextension.range_threshold,
        "pullback_target_price": target.price,
        "pullback_target_label": target.label,
        "pullback_target_source": target.source,
        "pullback_entry_min": target.entry_min,
        "pullback_entry_max": target.entry_max,
    }


def _confirmation_with_no_trade_check(
    confirmation: SignalConfirmationSnapshot,
    no_trade: NoTradeFilterResult,
) -> SignalConfirmationSnapshot:
    if not no_trade.enabled:
        status = "skipped"
        reason = "No-trade filters are disabled by settings"
    elif no_trade.blocked:
        status = "failed"
        reason = "; ".join(no_trade.blockers)
    elif no_trade.warnings:
        status = "warning"
        reason = "; ".join(no_trade.warnings)
    else:
        status = "passed"
        reason = "No-trade filters passed"
    return confirmation.model_copy(
        update={
            "passed": confirmation.passed and status != "failed",
            "checks": [
                *confirmation.checks,
                SignalLayerCheck(
                    name="no_trade_filter",
                    status=status,
                    reason=reason,
                    metadata=no_trade.model_dump(mode="json"),
                ),
            ],
        }
    )


def _no_trade_with_market_context(
    no_trade: NoTradeFilterResult,
    market_context: MarketContextSnapshot,
) -> NoTradeFilterResult:
    context_payload = market_context.model_dump(mode="json")
    blockers = [blocker for blocker in market_context.blockers if blocker.severity == "blocker"]
    warnings = [warning for warning in market_context.warnings if warning.severity != "blocker"]
    if not blockers and not warnings:
        metadata = dict(no_trade.metadata)
        metadata["market_context"] = context_payload
        return no_trade.model_copy(update={"metadata": metadata}, deep=True)

    metadata = dict(no_trade.metadata)
    metadata["market_context"] = context_payload
    metadata["blocker_codes"] = _dedupe_values(
        [
            *(str(value) for value in metadata.get("blocker_codes", []) if value),
            *(blocker.code for blocker in blockers),
        ]
    )
    metadata["warning_codes"] = _dedupe_values(
        [
            *(str(value) for value in metadata.get("warning_codes", []) if value),
            *(warning.code for warning in warnings),
        ]
    )
    checks = [
        *no_trade.checks,
        *[
            SignalLayerCheck(
                name=blocker.code,
                status="failed",
                reason=blocker.message,
                metadata=blocker.model_dump(mode="json"),
            )
            for blocker in blockers
        ],
        *[
            SignalLayerCheck(
                name=warning.code,
                status="warning",
                reason=warning.message,
                metadata=warning.model_dump(mode="json"),
            )
            for warning in warnings
        ],
    ]
    return no_trade.model_copy(
        update={
            "blocked": no_trade.blocked or bool(blockers),
            "hard_block": no_trade.hard_block or bool(blockers),
            "blockers": _dedupe_values([*no_trade.blockers, *(blocker.message for blocker in blockers)]),
            "warnings": _dedupe_values([*no_trade.warnings, *(warning.message for warning in warnings)]),
            "checks": checks,
            "metadata": metadata,
        },
        deep=True,
    )


def _trade_plan_with_market_context(
    trade_plan: TradePlan,
    market_context: MarketContextSnapshot,
) -> TradePlan:
    context_payload = market_context.model_dump(mode="json")
    context_updates = {
        "market_context": context_payload,
        "market_context_reason_codes": list(market_context.reason_codes),
        "market_context_risk_off": market_context.risk_off,
    }
    metadata = dict(trade_plan.metadata)
    metadata.update(context_updates)
    risk_metadata = dict(trade_plan.risk_rules.metadata)
    risk_metadata.update(context_updates)
    return trade_plan.model_copy(
        update={
            "metadata": metadata,
            "risk_rules": trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata}),
        },
        deep=True,
    )


def _dedupe_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _overextension_check(confirmation: SignalConfirmationSnapshot) -> SignalLayerCheck | None:
    for check in confirmation.checks:
        if check.name == "overextension_guard":
            return check
    return None


def _pullback_target_from_check(check: SignalLayerCheck | None) -> PullbackTarget | None:
    if check is None:
        return None
    metadata = check.metadata
    price = _number_or_none(metadata.get("pullback_target_price"))
    entry_min = _number_or_none(metadata.get("pullback_entry_min"))
    entry_max = _number_or_none(metadata.get("pullback_entry_max"))
    if price is None and entry_min is None and entry_max is None:
        return None
    label = str(metadata.get("pullback_target_label") or "pullback target")
    source = str(metadata.get("pullback_target_source") or "unknown")
    return PullbackTarget(
        price=price,
        label=label,
        source=source,
        entry_min=entry_min,
        entry_max=entry_max,
    )


def _pullback_target(signal: StrategySignal, features: Features) -> PullbackTarget:
    direction = signal.direction.lower()
    atr = features.atr_14 if features.atr_14 is not None and features.atr_14 > 0 else None
    if signal.strategy == "volatility_squeeze_breakout":
        if direction == "long" and features.donchian_high_20 is not None:
            return _target_from_price(
                features.donchian_high_20,
                "breakout_level",
                f"breakout level {features.donchian_high_20:.8f}",
                atr,
            )
        if direction == "short" and features.donchian_low_20 is not None:
            return _target_from_price(
                features.donchian_low_20,
                "breakdown_level",
                f"breakdown level {features.donchian_low_20:.8f}",
                atr,
            )
        return _target_from_price(None, "breakout_trigger", "the breakout trigger level", atr)
    if signal.strategy == "trend_pullback_continuation":
        candidates = [
            ("ema_20", features.ema_20),
            ("ema_50", features.ema_50),
            ("vwap", features.vwap),
        ]
        usable = [(source, value) for source, value in candidates if value is not None]
        if usable:
            source, target = min(usable, key=lambda item: abs(features.close - item[1]))
            label = f"{source.upper().replace('_', '')} pullback zone {target:.8f}" if source.startswith("ema") else f"VWAP pullback zone {target:.8f}"
            return _target_from_price(target, source, label, atr)
        return _target_from_price(None, "ema_vwap_zone", "the EMA/VWAP pullback zone", atr)
    if signal.strategy == "liquidity_sweep_reversal":
        if direction == "long" and features.swing_low is not None:
            return _target_from_price(features.swing_low, "swept_low", f"swept low {features.swing_low:.8f}", atr)
        if direction == "short" and features.swing_high is not None:
            return _target_from_price(features.swing_high, "swept_high", f"swept high {features.swing_high:.8f}", atr)
        return _target_from_price(None, "swept_liquidity", "the swept liquidity level", atr)
    fallback_price = features.vwap
    if fallback_price is not None:
        return _target_from_price(fallback_price, "vwap", f"VWAP {fallback_price:.8f}", atr)
    return _target_from_price(None, "trigger_or_vwap", "the trigger level or VWAP", atr)


def _target_from_price(price: float | None, source: str, label: str, atr: float | None) -> PullbackTarget:
    if price is None:
        return PullbackTarget(price=None, label=label, source=source)
    buffer = max((atr or 0.0) * 0.1, abs(price) * 0.0005)
    return PullbackTarget(
        price=price,
        label=label,
        source=source,
        entry_min=price - buffer,
        entry_max=price + buffer,
    )


def _entry_zone_around_level(level: float | None, atr: float | None) -> tuple[float | None, float | None]:
    if level is None:
        return None, None
    buffer = max((atr or 0.0) * 0.1, abs(level) * 0.0005)
    return level - buffer, level + buffer


def _measured_move_target(signal: StrategySignal, features: Features) -> float | None:
    range_high = features.donchian_high_20
    range_low = features.donchian_low_20
    if range_high is None or range_low is None or range_high <= range_low:
        return None
    range_height = range_high - range_low
    if signal.direction.lower() == "long":
        return range_high + range_height
    return range_low - range_height


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _target_rr(signal: StrategySignal, target: float | None) -> float | None:
    entry = _entry_price(signal)
    calculation = risk_reward_plan_service.calculate_rr(
        entry,
        signal.stop_loss,
        target,
        signal.direction,
    )
    return calculation.rr_value


def _trade_plan_with_risk_reward_metadata(
    trade_plan: TradePlan,
    risk_reward: RiskRewardAssessment,
) -> TradePlan:
    rr_metadata = risk_reward_metadata(risk_reward)
    metadata = dict(trade_plan.metadata)
    risk_metadata = dict(trade_plan.risk_rules.metadata)
    _merge_risk_reward_metadata(metadata, rr_metadata, risk_reward=risk_reward)
    _merge_risk_reward_metadata(risk_metadata, rr_metadata, risk_reward=risk_reward)
    if risk_reward.blocked:
        blocked_updates = {
            "signal_actionable": False,
            "execution_allowed_virtual": False,
            "execution_allowed_real": False,
            "auto_entry_allowed": False,
            "auto_entry_enabled": False,
            "execution_block_reason": "blocked_by_rr",
        }
        metadata.update(blocked_updates)
        risk_metadata.update(blocked_updates)
        metadata.setdefault("actionability_block_reason", "blocked_by_rr")
        risk_metadata.setdefault("actionability_block_reason", "blocked_by_rr")
    risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})
    return trade_plan.model_copy(
        update={
            "metadata": metadata,
            "risk_rules": risk_rules,
        },
        deep=True,
    )


def _merge_risk_reward_metadata(
    metadata: dict[str, Any],
    rr_metadata: Mapping[str, Any],
    *,
    risk_reward: RiskRewardAssessment,
) -> None:
    existing_actionability = {
        key: metadata.get(key)
        for key in (
            "signal_actionable",
            "execution_allowed_virtual",
            "execution_allowed_real",
            "auto_entry_allowed",
            "auto_entry_enabled",
            "actionability_block_reason",
        )
        if key in metadata
    }
    metadata.update(dict(rr_metadata))
    if risk_reward.blocked:
        return
    for key, value in existing_actionability.items():
        metadata[key] = value


def _legacy_display_filter_note(
    params: Mapping[str, Any],
    *,
    risk_reward: RiskRewardAssessment,
    status: str,
) -> dict[str, Any] | None:
    rr_flags = _truthy_flags(params, ("hide_failed_rr_signals", "hide_low_rr_signals"))
    active_only_flags = _truthy_flags(params, ("show_only_active_setups", "only_active_setups"))
    ignored_flags = [*rr_flags, *active_only_flags]
    if not ignored_flags:
        return None
    return {
        "reason_code": "legacy_pipeline_display_filter_ignored",
        "ignored": True,
        "ignored_flags": ignored_flags,
        "message": (
            "Legacy pipeline display filters are ignored; Radar service resolves "
            "all_market_opportunities versus execution_ready visibility."
        ),
        "rr_filter_requested": bool(rr_flags),
        "rr_filter_would_have_hidden": bool(rr_flags and risk_reward.blocked),
        "active_only_filter_requested": bool(active_only_flags),
        "active_only_filter_would_have_hidden": bool(
            active_only_flags and not is_execution_candidate_status(status)
        ),
        "signal_status": status,
        "risk_reward_blocked": risk_reward.blocked,
    }


def _truthy_flags(params: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [key for key in keys if _bool_param(params, key, False)]


def _confirmation_with_legacy_display_filter_note(
    confirmation: SignalConfirmationSnapshot,
    metadata: Mapping[str, Any],
) -> SignalConfirmationSnapshot:
    check = SignalLayerCheck(
        name="legacy_pipeline_display_filter",
        status="warning",
        reason=str(metadata["message"]),
        metadata=dict(metadata),
    )
    return confirmation.model_copy(
        update={
            "checks": [*confirmation.checks, check],
        }
    )


def _trade_plan_with_legacy_display_filter_note(
    trade_plan: TradePlan,
    metadata: Mapping[str, Any],
) -> TradePlan:
    note = {"legacy_pipeline_display_filter": dict(metadata)}
    trade_plan_metadata = dict(trade_plan.metadata)
    trade_plan_metadata.update(note)
    risk_metadata = dict(trade_plan.risk_rules.metadata)
    risk_metadata.update(note)
    risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})
    return trade_plan.model_copy(
        update={
            "metadata": trade_plan_metadata,
            "risk_rules": risk_rules,
        },
        deep=True,
    )


def _entry_price(signal: StrategySignal) -> float | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    return signal.entry_max


def _trigger_type_for_strategy(signal: StrategySignal) -> str:
    if signal.strategy == "trend_pullback_continuation":
        return "reclaim"
    if signal.strategy == "volatility_squeeze_breakout":
        return "breakout_retest" if signal.status == "wait_for_pullback" else "closed_candle"
    if signal.strategy == "liquidity_sweep_reversal":
        return "liquidity_reclaim"
    return "closed_candle"


def _signal_timestamp_datetime(timestamp: int) -> datetime:
    seconds = timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
    return datetime.fromtimestamp(seconds, tz=timezone.utc)
