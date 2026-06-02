from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.schemas.market import Features
from app.schemas.signal import (
    MarketQualitySnapshot,
    MarketRegimeSnapshot,
    NoTradeFilterResult,
    SignalAutoEntrySnapshot,
    SignalConfirmationSnapshot,
    SignalExitPlanSnapshot,
    SignalInvalidationSnapshot,
    SignalLayerCheck,
    StrategySetupSnapshot,
    StrategySignal,
)
from app.schemas.trade_plan import (
    TradePlan,
    TradePlanCompletenessResult,
    TradePlanInvalidation,
    TradePlanTarget,
    build_trade_plan_from_legacy_fields,
)
from app.services.no_trade_filter import NoTradeFilterService
from app.services.risk_management import resolve_rr_guard_mode
from app.services.support_resistance import SupportResistanceSnapshot
from app.services.trade_plan_completeness import TradePlanCompletenessCheck
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
DEFAULT_MIN_RR_RATIO = 2.0
RR_TARGET_BY_STRATEGY: dict[str, str] = {
    "trend_pullback_continuation": "final",
    "volatility_squeeze_breakout": "final",
    "liquidity_sweep_reversal": "nearest",
}

QUALITY_DEFAULTS_BY_TIER: dict[str, dict[str, float]] = {
    "major": {"min_24h_volume_quote": 25_000_000.0, "max_spread_bps": 15.0, "rough_chart_fail": 5.0},
    "mid_alt": {"min_24h_volume_quote": 10_000_000.0, "max_spread_bps": 25.0, "rough_chart_fail": 4.5},
    "low_liquidity": {"min_24h_volume_quote": 5_000_000.0, "max_spread_bps": 35.0, "rough_chart_fail": 4.0},
    "unknown": {"min_24h_volume_quote": 10_000_000.0, "max_spread_bps": 25.0, "rough_chart_fail": 4.5},
}


@dataclass(frozen=True)
class MarketQualityInput:
    volume_24h_quote: float | None = None
    spread_bps: float | None = None
    source: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyEvaluationContext:
    signal_features: Features
    context_features: Features | None = None
    context_features_by_timeframe: Mapping[str, Features] = field(default_factory=dict)
    support_resistance_by_timeframe: Mapping[str, SupportResistanceSnapshot] = field(default_factory=dict)
    strategy_params: Mapping[str, Any] = field(default_factory=dict)
    market_quality: MarketQualityInput | None = None
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


@dataclass(frozen=True)
class RiskRewardAssessment:
    passed: bool
    rr: float | None
    min_rr: float
    guard_mode: str
    status: str
    meets_min_rr: bool
    blocked: bool
    warning: bool
    warning_reason: str | None
    block_reason: str | None
    target_key: str
    target_label: str
    first_target_rr: float | None
    final_target_rr: float | None
    reason: str


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
        signal = _ensure_trade_plan(signal)
        quality = MarketQualityFilter().evaluate(signal, context)
        no_trade_enabled = _bool_param(context.strategy_params, "no_trade_filters_enabled", False)
        if not quality.passed and not no_trade_enabled:
            return None

        regime = MarketRegimeFilter().evaluate(signal, context)
        if _has_severe_ema200_chop(regime) and signal.strategy == "trend_pullback_continuation":
            return None
        signal = _apply_regime_score(signal, regime)
        setup = StrategySetupLayer().evaluate(signal)
        risk_reward = _assess_risk_reward(signal, context.strategy_params, context.rr_guard_context)
        if risk_reward.blocked and _hide_failed_rr_signals(context.strategy_params):
            return None
        confirmation = ConfirmationLayer().evaluate(signal, context, risk_reward)
        no_trade = NoTradeFilterService().evaluate(
            signal=signal,
            features=context.signal_features,
            context={
                "quality": quality,
                "regime": regime,
                "confirmation": confirmation,
                "market_quality": context.market_quality,
            },
            settings=context.strategy_params,
        )
        confirmation = _confirmation_with_no_trade_check(confirmation, no_trade)
        if not quality.passed and not no_trade.blocked:
            return None
        invalidation = InvalidationLayer().build(signal, context)
        exit_management = ExitManagementLayer()
        exit_plan = exit_management.build(signal, context)
        trade_plan = exit_management.enrich_trade_plan(
            signal=signal,
            exit_plan=exit_plan,
            invalidation=invalidation,
            risk_reward=risk_reward,
        )
        production_mode = _is_production_mode(context.strategy_params)
        completeness = TradePlanCompletenessCheck().evaluate(trade_plan)
        trade_plan = _trade_plan_with_completeness_metadata(
            trade_plan=trade_plan,
            completeness=completeness,
            production_mode=production_mode,
        )
        confirmation = _confirmation_with_trade_plan_completeness(
            confirmation=confirmation,
            completeness=completeness,
            production_mode=production_mode,
        )

        status, status_reason = RiskInvalidationLayer().status(
            signal=signal,
            context=context,
            quality=quality,
            regime=regime,
            confirmation=confirmation,
            risk_reward=risk_reward,
            no_trade_filter=no_trade,
        )
        if production_mode and not completeness.complete:
            status = "watchlist"
            status_reason = _trade_plan_incomplete_status_reason(completeness)
        if _show_only_active_setups(context.strategy_params) and not _is_active_setup_status(status):
            return None

        explanation = [
            f"Status: {status_reason}",
            *signal.explanation,
        ]
        risks = list(signal.risks)
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

        updates: dict[str, Any] = {
            "status": status,
            "status_reason": status_reason,
            "quality": quality,
            "regime": regime,
            "setup": setup,
            "confirmation": confirmation,
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
        }
        if status == "wait_for_pullback":
            overextension = _overextension_check(confirmation)
            target = _pullback_target_from_check(overextension)
            if target is not None:
                updates["entry_min"] = target.entry_min
                updates["entry_max"] = target.entry_max
                trade_plan = _sync_trade_plan_entry(
                    trade_plan=trade_plan,
                    entry_min=target.entry_min,
                    entry_max=target.entry_max,
                )
        if risk_reward.blocked:
            updates["auto_entry"] = SignalAutoEntrySnapshot(
                enabled=False,
                status="cancelled",
                message=risk_reward.reason,
            )
        if production_mode and not completeness.complete:
            updates["auto_entry"] = SignalAutoEntrySnapshot(
                enabled=False,
                status="cancelled",
                message=status_reason,
            )
        if no_trade.blocked:
            updates["auto_entry"] = SignalAutoEntrySnapshot(
                enabled=False,
                status="cancelled",
                message=status_reason,
            )
        updates["trade_plan"] = trade_plan

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
        features = primary_features or signal_features
        expected_context_timeframe = context_timeframe_for(signal_features.timeframe, context.strategy_params)
        context_timeframe = features.timeframe if primary_features is not None else expected_context_timeframe
        direction = _trend_direction(features)
        strength = _trend_strength(features)
        alignment = _alignment(signal.direction.lower(), direction)
        adjustment = _regime_score_adjustment(signal.strategy, alignment, strength)
        checks: list[SignalLayerCheck] = []

        if primary_features is None:
            checks.append(
                SignalLayerCheck(
                    name="context_timeframe",
                    status="skipped",
                    reason=f"Expected {expected_context_timeframe or 'none'} context; using signal timeframe only",
                )
            )
            alignment = "unknown" if direction == "unknown" else alignment
        else:
            checks.append(
                SignalLayerCheck(
                    name="context_timeframe",
                    status="passed",
                    reason=f"Using {features.timeframe} context for {signal_features.timeframe} signal",
                )
            )
            min_context_history = int(context.strategy_params.get("min_context_history", MIN_CONTEXT_HISTORY))
            history_ok = features.history_length >= min_context_history
            checks.append(
                SignalLayerCheck(
                    name="context_history",
                    status="passed" if history_ok else "warning",
                    score=features.history_length,
                    reason=f"{features.history_length}/{min_context_history} context candles available",
                )
            )

        checks.append(
            SignalLayerCheck(
                name="regime_alignment",
                status="warning" if alignment == "against" else "passed",
                reason=f"{signal.direction.lower()} vs {direction} {context_timeframe or 'context'} ({strength})",
            )
        )
        checks.append(
            SignalLayerCheck(
                name="regime_strength",
                status="warning" if alignment == "against" and strength == "strong" else "passed",
                reason=f"Higher timeframe trend strength is {strength}",
            )
        )
        chop_check, chop_adjustment = _ema200_chop_check(signal, signal_features)
        checks.append(chop_check)
        adjustment += chop_adjustment

        macro_features = _macro_context_features(context)
        if macro_features is None:
            macro_timeframe = MACRO_CONTEXT_TIMEFRAME_BY_SIGNAL.get(signal_features.timeframe)
            if macro_timeframe and macro_timeframe != context_timeframe:
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

        return MarketRegimeSnapshot(
            signal_timeframe=signal_features.timeframe,
            context_timeframe=context_timeframe,
            direction=direction,
            strength=strength,
            alignment=alignment,
            score_adjustment=adjustment,
            checks=checks,
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
                metadata=_risk_reward_metadata(risk_reward),
            ),
            SignalLayerCheck(
                name="volume_confirmation",
                status="passed" if features.volume_spike >= 1 else "warning",
                score=round(features.volume_spike, 3),
            ),
        ]
        return SignalConfirmationSnapshot(
            passed=all(check.status != "failed" for check in checks),
            checks=checks,
        )


class RiskInvalidationLayer:
    def status(
        self,
        *,
        signal: StrategySignal,
        context: StrategyEvaluationContext,
        quality: MarketQualitySnapshot,
        regime: MarketRegimeSnapshot,
        confirmation: SignalConfirmationSnapshot,
        risk_reward: RiskRewardAssessment,
        no_trade_filter: NoTradeFilterResult,
    ) -> tuple[str, str]:
        if signal.status == "invalidated":
            return ("invalidated", signal.status_reason or "Strategy idea is invalidated")

        if no_trade_filter.blocked:
            return ("ready", f"No-trade hard block: {'; '.join(no_trade_filter.blockers)}")

        overextension = _assess_overextension(signal, context.signal_features, context.strategy_params)
        if overextension.overextended:
            return ("wait_for_pullback", overextension.reason)

        if signal.status == "watchlist":
            return ("watchlist", signal.status_reason or "Strategy conditions are forming")

        if not risk_reward.passed:
            return ("ready", risk_reward.reason)

        if not confirmation.passed:
            return ("watchlist", "Strategy setup exists, but confirmation is incomplete")

        if _has_strong_regime_conflict(regime):
            return ("watchlist", "Higher timeframe is strongly against the signal direction")

        if (
            signal.strategy == "trend_pullback_continuation"
            and _bool_param(context.strategy_params, "require_htf_alignment", False)
            and regime.alignment != "aligned"
        ):
            return ("watchlist", "Trend pullback requires higher-timeframe alignment before actionable entry")

        if signal.strategy == "trend_pullback_continuation" and _has_borderline_ema200_chop(regime):
            return ("watchlist", "EMA200 chop is elevated; trend pullback stays on watchlist")

        if _has_context_obstacle(regime):
            return ("ready", "Higher timeframe support/resistance is too close")

        if signal.status == "ready":
            return ("ready", signal.status_reason or "Strategy setup exists; waiting for confirmation")

        if quality.tier == "low_liquidity" and signal.score < 85:
            return ("ready", "Low-liquidity asset needs a stronger strategy score before actionable classification")

        if signal.score >= ACTIONABLE_SCORE:
            return ("actionable", "Strategy classification passed; entry still requires risk/reward gate")

        return ("ready", "Setup is valid; waiting for stronger confirmation")


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
            metadata.update(
                {
                    "rsi_long_min": 45.0,
                    "rsi_short_max": 55.0,
                    "trend_invalidation_level": features.swing_low if direction == "long" else features.swing_high,
                    "time_stop_bars": time_stop_bars,
                    "time_stop": "no_progress_to_TP1" if time_stop_bars is not None else None,
                }
            )
            if direction == "long":
                conditions = [
                    "Close below EMA50",
                    "Break below last swing low",
                    "RSI loses the 45 zone",
                ]
            else:
                conditions = [
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
                }
            )
            if direction == "long":
                conditions = [
                    "Close returns inside the previous Donchian range",
                    "Breakout candle is fully retraced",
                    "Volume disappears after breakout",
                ]
            else:
                conditions = [
                    "Close returns inside the previous Donchian range",
                    "Breakdown candle is fully retraced",
                    "Volume disappears after breakdown",
                ]
        elif signal.strategy == "liquidity_sweep_reversal":
            swept_level = features.swing_low if direction == "long" else features.swing_high
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
                    "sweep_extreme": features.low if direction == "long" else features.high,
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
            targets.append(
                {
                    "label": label,
                    "price": price,
                    "r_multiple": r_multiple,
                    "action": action,
                    "close_percent": close_percent,
                    "source": planned.source if planned is not None else None,
                    "metadata": metadata,
                }
            )
        if signal.strategy == "trend_pullback_continuation":
            if _strong_trend_for_runner(context.signal_features, context.context_features):
                targets.append(
                    {
                        "label": "Runner",
                        "price": None,
                        "r_multiple": None,
                        "action": "runner_trailing",
                        "close_percent": "runner",
                        "source": "EMA20" if context.signal_features.ema_20 is not None else "ATR",
                        "metadata": {"enabled_when": "strong_trend"},
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
                    targets.append(
                        {
                            "label": "Measured Move",
                            "price": measured_target,
                            "r_multiple": r_multiple,
                            "action": "measured_move_runner",
                            "close_percent": "runner",
                            "source": "range_measured_move",
                            "metadata": {
                                "range_high": context.signal_features.donchian_high_20,
                                "range_low": context.signal_features.donchian_low_20,
                                "entry_model": _trade_plan_entry_model(signal),
                            },
                        }
                    )
        elif signal.strategy == "liquidity_sweep_reversal":
            targets.append(
                {
                    "label": "Runner",
                    "price": None,
                    "r_multiple": None,
                    "action": "runner_trailing",
                    "close_percent": "runner",
                    "source": "micro_BOS_or_ATR_trailing",
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

    def enrich_trade_plan(
        self,
        *,
        signal: StrategySignal,
        exit_plan: SignalExitPlanSnapshot,
        invalidation: SignalInvalidationSnapshot,
        risk_reward: RiskRewardAssessment,
    ) -> TradePlan:
        trade_plan = signal.trade_plan or _trade_plan_from_signal(signal)
        targets = [_trade_plan_target_from_exit_target(target) for target in exit_plan.targets]
        risk_metadata = dict(trade_plan.risk_rules.metadata)
        for key in ("time_stop_bars", "time_stop"):
            value = invalidation.metadata.get(key)
            if value is not None:
                risk_metadata[key] = value
        risk_rules = trade_plan.risk_rules.model_copy(
            update={
                "risk_reward": signal.risk_reward,
                "first_target_rr": risk_reward.first_target_rr,
                "final_target_rr": risk_reward.final_target_rr,
                "selected_rr": risk_reward.rr,
                "selected_rr_target": risk_reward.target_key,
                "min_rr_ratio": risk_reward.min_rr,
                "metadata": risk_metadata,
            }
        )
        enriched_invalidation = TradePlanInvalidation.model_validate(
            invalidation.model_dump(mode="json")
        )
        if trade_plan.invalidation is not None:
            enriched_invalidation = enriched_invalidation.model_copy(
                update={
                    "metadata": {
                        **trade_plan.invalidation.metadata,
                        **enriched_invalidation.metadata,
                    }
                }
            )
        return trade_plan.model_copy(
            update={
                "targets": targets or trade_plan.targets,
                "invalidation": enriched_invalidation,
                "risk_rules": risk_rules,
            },
            deep=True,
        )


def _ensure_trade_plan(signal: StrategySignal) -> StrategySignal:
    if signal.trade_plan is not None:
        return signal
    return signal.model_copy(update={"trade_plan": _trade_plan_from_signal(signal)})


def _trade_plan_from_signal(signal: StrategySignal) -> TradePlan:
    return build_trade_plan_from_legacy_fields(
        entry_min=signal.entry_min,
        entry_max=signal.entry_max,
        stop_loss=signal.stop_loss,
        take_profit_1=signal.take_profit_1,
        take_profit_2=signal.take_profit_2,
        risk_reward=signal.risk_reward,
        first_target_rr=signal.first_target_rr,
        final_target_rr=signal.final_target_rr,
        selected_rr=signal.selected_rr,
        selected_rr_target=signal.selected_rr_target,
        min_rr_ratio=signal.min_rr_ratio,
    )


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


def _trade_plan_target_from_exit_target(target: dict[str, Any]) -> TradePlanTarget:
    metadata = {
        key: value
        for key, value in target.items()
        if key not in {"label", "price", "r_multiple", "action", "close_percent", "source"}
    }
    existing_metadata = target.get("metadata")
    if isinstance(existing_metadata, dict):
        metadata.update(existing_metadata)
    return TradePlanTarget(
        label=str(target.get("label") or "target"),
        price=_number_or_none(target.get("price")),
        r_multiple=_number_or_none(target.get("r_multiple")),
        action=str(target["action"]) if target.get("action") is not None else None,
        close_percent=target.get("close_percent"),
        source=str(target["source"]) if target.get("source") is not None else None,
        metadata=metadata,
    )


def _planned_targets_by_label(signal: StrategySignal) -> dict[str, TradePlanTarget]:
    if signal.trade_plan is None:
        return {}
    return {target.label: target for target in signal.trade_plan.targets}


def _trade_plan_entry_model(signal: StrategySignal) -> str | None:
    if signal.trade_plan is None:
        return None
    raw = signal.trade_plan.entry.metadata.get("entry_model")
    return str(raw) if raw is not None else None


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
    return abs(level - entry) / risk


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


def _risk_reward_metadata(risk_reward: RiskRewardAssessment) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "first_target_rr": risk_reward.first_target_rr,
        "final_target_rr": risk_reward.final_target_rr,
        "selected_rr": risk_reward.rr,
        "selected_rr_target": risk_reward.target_key,
        "selected_rr_label": risk_reward.target_label,
        "min_rr_ratio": risk_reward.min_rr,
        "risk_reward_guard_mode": risk_reward.guard_mode,
        "risk_reward_warning": risk_reward.warning,
        "risk_reward_warning_reason": risk_reward.warning_reason,
        "risk_reward_blocked": risk_reward.blocked,
        "risk_reward_block_reason": risk_reward.block_reason,
    }
    return metadata


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


def _confirmation_with_trade_plan_completeness(
    *,
    confirmation: SignalConfirmationSnapshot,
    completeness: TradePlanCompletenessResult,
    production_mode: bool,
) -> SignalConfirmationSnapshot:
    if completeness.complete:
        status = "passed"
    elif production_mode:
        status = "failed"
    else:
        status = "warning"
    check = SignalLayerCheck(
        name="trade_plan_completeness",
        status=status,
        reason=_trade_plan_completeness_reason(completeness, production_mode),
        metadata=_trade_plan_completeness_metadata(completeness, production_mode),
    )
    return confirmation.model_copy(
        update={
            "passed": confirmation.passed and status != "failed",
            "checks": [*confirmation.checks, check],
        }
    )


def _trade_plan_with_completeness_metadata(
    *,
    trade_plan: TradePlan,
    completeness: TradePlanCompletenessResult,
    production_mode: bool,
) -> TradePlan:
    completeness_metadata = _trade_plan_completeness_metadata(completeness, production_mode)
    metadata = dict(trade_plan.metadata)
    metadata.update(completeness_metadata)
    metadata["trade_plan_completeness"] = completeness.model_dump(mode="json")
    risk_metadata = dict(trade_plan.risk_rules.metadata)
    risk_metadata.update(completeness_metadata)
    risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})
    return trade_plan.model_copy(
        update={
            "metadata": metadata,
            "risk_rules": risk_rules,
        },
        deep=True,
    )


def _trade_plan_completeness_metadata(
    completeness: TradePlanCompletenessResult,
    production_mode: bool,
) -> dict[str, Any]:
    return {
        "trade_plan_complete": completeness.complete,
        "fallback_used": completeness.fallback_used,
        "fallback_stop_used": completeness.fallback_stop_used,
        "fallback_targets_used": completeness.fallback_targets_used,
        "has_structural_stop": completeness.has_structural_stop,
        "has_invalidation_thesis": completeness.has_invalidation_thesis,
        "has_structural_target": completeness.has_structural_target,
        "missing": list(completeness.missing),
        "research_mode": not production_mode,
        "production_mode": production_mode,
        "signal_actionable": completeness.complete or not production_mode,
        "execution_allowed_virtual": completeness.complete or not production_mode,
        "execution_allowed_real": completeness.complete and production_mode,
        "decision_scope": "production" if production_mode else "research",
    }


def _trade_plan_completeness_reason(
    completeness: TradePlanCompletenessResult,
    production_mode: bool,
) -> str:
    if completeness.complete:
        return "Trade plan has structural stop, invalidation and target thesis."
    if production_mode:
        return _trade_plan_incomplete_status_reason(completeness)
    return "Trade plan is research-compatible but incomplete for production actionability."


def _trade_plan_incomplete_status_reason(completeness: TradePlanCompletenessResult) -> str:
    missing = ", ".join(completeness.missing) if completeness.missing else "structural trade plan"
    return f"Trade plan incomplete: {missing}; production actionability is blocked."


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


def _assess_risk_reward(
    signal: StrategySignal,
    params: Mapping[str, Any],
    rr_guard_context: str = "discovery",
) -> RiskRewardAssessment:
    min_rr = _strategy_numeric_param(params, "min_rr_ratio", signal.strategy, DEFAULT_MIN_RR_RATIO)
    guard_mode = resolve_rr_guard_mode(
        params,
        context=rr_guard_context,
        strategy=signal.strategy,
        strategy_risk_settings=params,
    )
    if min_rr <= 0:
        return RiskRewardAssessment(
            passed=True,
            rr=signal.risk_reward,
            min_rr=min_rr,
            guard_mode=guard_mode,
            status="skipped",
            meets_min_rr=True,
            blocked=False,
            warning=False,
            warning_reason=None,
            block_reason=None,
            target_key="disabled",
            target_label="disabled",
            first_target_rr=_target_rr(signal, signal.take_profit_1),
            final_target_rr=_target_rr(signal, signal.take_profit_2 or signal.take_profit_1),
            reason="Risk/reward guard is disabled for this strategy",
        )

    first_target_rr = _target_rr(signal, signal.take_profit_1)
    final_target_rr = _target_rr(signal, signal.take_profit_2 or signal.take_profit_1)
    rr_target = _rr_target_key(params, signal.strategy)
    if rr_target == "nearest":
        selected_rr = first_target_rr if first_target_rr is not None else final_target_rr
        target_label = "nearest target" if first_target_rr is not None else "nearest valid target"
    else:
        selected_rr = final_target_rr if final_target_rr is not None else signal.risk_reward
        target_label = "planned final target"

    if selected_rr is None:
        reason = "Risk/reward blocked: entry, stop or target is missing"
        if _has_unusable_profit_target(signal):
            reason = "Risk/reward blocked: no planned target is beyond the entry price"
        return RiskRewardAssessment(
            passed=False,
            rr=None,
            min_rr=min_rr,
            guard_mode=guard_mode,
            status="failed",
            meets_min_rr=False,
            blocked=True,
            warning=False,
            warning_reason=None,
            block_reason=reason,
            target_key=rr_target,
            target_label=target_label,
            first_target_rr=first_target_rr,
            final_target_rr=final_target_rr,
            reason=reason,
        )

    if selected_rr < min_rr:
        nearest_text = (
            "not beyond entry"
            if first_target_rr is None and signal.take_profit_1 is not None
            else "-" if first_target_rr is None else f"{first_target_rr:.2f}R"
        )
        final_text = "-" if final_target_rr is None else f"{final_target_rr:.2f}R"
        target_context = (
            f"(TP1 {nearest_text}, final {final_text})"
            if rr_target == "nearest" and first_target_rr is None and signal.take_profit_1 is not None
            else f"(nearest {nearest_text}, final {final_text})"
        )
        threshold_reason = (
            f"Risk/reward blocked: {target_label} is {selected_rr:.2f}R, "
            f"below configured minimum {min_rr:.2f}R "
            f"{target_context}"
        )
        if guard_mode == "hard":
            return RiskRewardAssessment(
                passed=False,
                rr=selected_rr,
                min_rr=min_rr,
                guard_mode=guard_mode,
                status="failed",
                meets_min_rr=False,
                blocked=True,
                warning=False,
                warning_reason=None,
                block_reason=threshold_reason,
                target_key=rr_target,
                target_label=target_label,
                first_target_rr=first_target_rr,
                final_target_rr=final_target_rr,
                reason=threshold_reason,
            )
        if guard_mode == "soft":
            warning_reason = threshold_reason.replace("Risk/reward blocked:", "Risk/reward warning:", 1)
            return RiskRewardAssessment(
                passed=True,
                rr=selected_rr,
                min_rr=min_rr,
                guard_mode=guard_mode,
                status="warning",
                meets_min_rr=False,
                blocked=False,
                warning=True,
                warning_reason=warning_reason,
                block_reason=None,
                target_key=rr_target,
                target_label=target_label,
                first_target_rr=first_target_rr,
                final_target_rr=final_target_rr,
                reason=warning_reason,
            )
        return RiskRewardAssessment(
            passed=True,
            rr=selected_rr,
            min_rr=min_rr,
            guard_mode=guard_mode,
            status="skipped",
            meets_min_rr=False,
            blocked=False,
            warning=False,
            warning_reason=None,
            block_reason=None,
            target_key=rr_target,
            target_label=target_label,
            first_target_rr=first_target_rr,
            final_target_rr=final_target_rr,
            reason=(
                f"Risk/reward guard is off: {target_label} is {selected_rr:.2f}R, "
                f"minimum for reporting is {min_rr:.2f}R {target_context}"
            ),
        )

    return RiskRewardAssessment(
        passed=True,
        rr=selected_rr,
        min_rr=min_rr,
        guard_mode=guard_mode,
        status="skipped" if guard_mode == "off" else "passed",
        meets_min_rr=True,
        blocked=False,
        warning=False,
        warning_reason=None,
        block_reason=None,
        target_key=rr_target,
        target_label=target_label,
        first_target_rr=first_target_rr,
        final_target_rr=final_target_rr,
        reason=(
            f"Risk/reward passed: {target_label} is {selected_rr:.2f}R, minimum {min_rr:.2f}R"
            if guard_mode != "off"
            else f"Risk/reward guard is off: {target_label} is {selected_rr:.2f}R"
        ),
    )


def _rr_target_key(params: Mapping[str, Any], strategy: str) -> str:
    raw_target = str(params.get("rr_target") or RR_TARGET_BY_STRATEGY.get(strategy, "final")).strip().lower()
    if raw_target in {"first", "nearest", "tp1"}:
        return "nearest"
    return "final"


def _target_rr(signal: StrategySignal, target: float | None) -> float | None:
    entry = _entry_price(signal)
    stop = signal.stop_loss
    if entry is None or stop is None or target is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    reward = _target_reward(signal, target, entry)
    if reward <= 0:
        return None
    return round(reward / risk, 4)


def _target_reward(signal: StrategySignal, target: float, entry: float | None = None) -> float:
    entry = _entry_price(signal) if entry is None else entry
    if entry is None:
        return 0.0
    if signal.direction.lower() == "long":
        return target - entry
    return entry - target


def _has_unusable_profit_target(signal: StrategySignal) -> bool:
    entry = _entry_price(signal)
    if entry is None or signal.stop_loss is None:
        return False
    return any(
        target is not None and _target_reward(signal, target, entry) <= 0
        for target in (signal.take_profit_1, signal.take_profit_2)
    )


def _hide_failed_rr_signals(params: Mapping[str, Any]) -> bool:
    return bool(params.get("hide_failed_rr_signals") or params.get("hide_low_rr_signals"))


def _show_only_active_setups(params: Mapping[str, Any]) -> bool:
    return bool(params.get("show_only_active_setups") or params.get("only_active_setups"))


def _is_active_setup_status(status: str) -> bool:
    return status in {"actionable", "active", "entry_touched"}


def _entry_price(signal: StrategySignal) -> float | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    return signal.entry_max
