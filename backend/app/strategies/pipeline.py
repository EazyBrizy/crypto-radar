from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.schemas.market import Features
from app.schemas.signal import (
    MarketQualitySnapshot,
    MarketRegimeSnapshot,
    SignalConfirmationSnapshot,
    SignalExitPlanSnapshot,
    SignalInvalidationSnapshot,
    SignalLayerCheck,
    StrategySetupSnapshot,
    StrategySignal,
)
from app.strategies.common import ACTIONABLE_SCORE, WATCHLIST_SCORE, score_from_breakdown

MAJOR_BASE_ASSETS = {"BTC", "ETH", "SOL", "BNB", "XRP"}
LOW_LIQUIDITY_BASE_ASSETS = {"1000PEPE", "PEPE", "SHIB", "FLOKI", "BONK", "WIF"}

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
    strategy_params: Mapping[str, Any] = field(default_factory=dict)
    market_quality: MarketQualityInput | None = None
    pair_scope_configured: bool = False


@dataclass(frozen=True)
class OverextensionAssessment:
    overextended: bool
    body_atr: float
    range_atr: float
    body_threshold: float
    range_threshold: float
    reason: str


@dataclass(frozen=True)
class RiskRewardAssessment:
    passed: bool
    rr: float | None
    min_rr: float
    target_label: str
    first_target_rr: float | None
    final_target_rr: float | None
    reason: str


def context_timeframe_for(timeframe: str) -> str | None:
    return CONTEXT_TIMEFRAME_BY_SIGNAL.get(timeframe)


def context_timeframes_for(timeframe: str) -> tuple[str, ...]:
    result: list[str] = []
    for candidate in (
        CONTEXT_TIMEFRAME_BY_SIGNAL.get(timeframe),
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
        quality = MarketQualityFilter().evaluate(signal, context)
        if not quality.passed:
            return None

        regime = MarketRegimeFilter().evaluate(signal, context)
        signal = _apply_regime_score(signal, regime)
        setup = StrategySetupLayer().evaluate(signal)
        risk_reward = _assess_risk_reward(signal, context.strategy_params)
        if not risk_reward.passed and _hide_failed_rr_signals(context.strategy_params):
            return None
        confirmation = ConfirmationLayer().evaluate(signal, context, risk_reward)
        invalidation = InvalidationLayer().build(signal, context)
        exit_plan = ExitManagementLayer().build(signal, context)

        status, status_reason = RiskInvalidationLayer().status(
            signal=signal,
            context=context,
            quality=quality,
            regime=regime,
            confirmation=confirmation,
            risk_reward=risk_reward,
        )

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
        if not risk_reward.passed:
            risks.append(risk_reward.reason)

        return signal.model_copy(
            update={
                "status": status,
                "status_reason": status_reason,
                "quality": quality,
                "regime": regime,
                "setup": setup,
                "confirmation": confirmation,
                "invalidation": invalidation,
                "exit_plan": exit_plan,
                "explanation": explanation,
                "risks": risks,
            }
        )


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
        expected_context_timeframe = context_timeframe_for(signal_features.timeframe)
        context_timeframe = features.timeframe if primary_features is not None else expected_context_timeframe
        direction = _trend_direction(features)
        strength = _trend_strength(features)
        alignment = _alignment(signal.direction.lower(), direction)
        adjustment = _regime_score_adjustment(alignment, strength)
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
            adjustment += _macro_regime_score_adjustment(macro_alignment, macro_strength)
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
            obstacle_check, obstacle_adjustment = _context_obstacle_check(
                signal=signal,
                signal_features=signal_features,
                context_features=primary_features,
                min_atr=float(
                    context.strategy_params.get(
                        "context_obstacle_min_atr",
                        CONTEXT_OBSTACLE_MIN_ATR,
                    )
                ),
            )
            checks.append(obstacle_check)
            adjustment += obstacle_adjustment

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
        elif signal.status == "ready":
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
            ),
            SignalLayerCheck(
                name="risk_reward_guard",
                status="passed" if risk_reward.passed else "failed",
                score=None if risk_reward.rr is None else round(risk_reward.rr, 3),
                reason=risk_reward.reason,
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
    ) -> tuple[str, str]:
        if signal.status == "invalidated":
            return ("invalidated", signal.status_reason or "Strategy idea is invalidated")

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
            "rsi_14": features.rsi_14,
            "donchian_high_20": features.donchian_high_20,
            "donchian_low_20": features.donchian_low_20,
        }

        if signal.strategy == "trend_pullback_continuation":
            metadata.update(
                {
                    "rsi_long_min": 45.0,
                    "rsi_short_max": 55.0,
                    "trend_invalidation_level": features.swing_low if direction == "long" else features.swing_high,
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
        elif signal.strategy == "volatility_squeeze_breakout":
            breakout_level = features.donchian_high_20 if direction == "long" else features.donchian_low_20
            metadata.update(
                {
                    "range_high": features.donchian_high_20,
                    "range_low": features.donchian_low_20,
                    "breakout_level": breakout_level,
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
            metadata.update(
                {
                    "swept_low": features.swing_low,
                    "swept_high": features.swing_high,
                    "swept_level": swept_level,
                    "reclaim_level": swept_level if direction == "long" else None,
                    "rejection_level": swept_level if direction == "short" else None,
                }
            )
            if direction == "long":
                conditions = [
                    "Close returns below swept low",
                    "Sweep low is broken again",
                    "Next candles fail to hold reclaim",
                ]
            else:
                conditions = [
                    "Close returns above swept high",
                    "Sweep high is broken again",
                    "Next candles fail to hold rejection",
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
        risk = abs(entry - signal.stop_loss) if entry is not None and signal.stop_loss is not None else None
        targets: list[dict[str, Any]] = []
        for label, price in (("TP1", signal.take_profit_1), ("TP2", signal.take_profit_2)):
            if price is None:
                continue
            r_multiple = abs(price - entry) / risk if entry is not None and risk and risk > 0 else None
            targets.append({"label": label, "price": price, "r_multiple": r_multiple})

        breakeven = {}
        if entry is not None and targets:
            breakeven = {"after": "TP1", "stop_price": entry}

        trailing = {
            "enabled_after": "TP1" if signal.strategy != "volatility_squeeze_breakout" else "ATR expansion",
            "source": "ATR" if context.signal_features.atr_14 is not None else "structure",
        }
        return SignalExitPlanSnapshot(targets=targets, breakeven=breakeven, trailing=trailing)


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


def _primary_context_features(context: StrategyEvaluationContext) -> Features | None:
    expected = context_timeframe_for(context.signal_features.timeframe)
    if expected:
        features = context.context_features_by_timeframe.get(expected)
        if features is not None:
            return features
    return context.context_features


def _macro_context_features(context: StrategyEvaluationContext) -> Features | None:
    expected = MACRO_CONTEXT_TIMEFRAME_BY_SIGNAL.get(context.signal_features.timeframe)
    if expected:
        return context.context_features_by_timeframe.get(expected)
    return None


def _regime_score_adjustment(alignment: str, strength: str) -> int:
    if alignment == "aligned" and strength == "strong":
        return 8
    if alignment == "aligned":
        return 5
    if alignment == "against" and strength == "strong":
        return -25
    if alignment == "against":
        return -12
    return 0


def _macro_regime_score_adjustment(alignment: str, strength: str) -> int:
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
    min_atr: float,
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
        status = "warning" if distance_atr <= min_atr else "passed"
        return (
            SignalLayerCheck(
                name="context_resistance",
                status=status,
                score=round(distance_atr, 3),
                reason=(
                    f"{context_features.timeframe} resistance is {distance_atr:.2f} ATR above entry"
                ),
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
    status = "warning" if distance_atr <= min_atr else "passed"
    return (
        SignalLayerCheck(
            name="context_support",
            status=status,
            score=round(distance_atr, 3),
            reason=f"{context_features.timeframe} support is {distance_atr:.2f} ATR below entry",
        ),
        -8 if status == "warning" else 0,
    )


def _levels_above(entry: float, *levels: float | None) -> list[float]:
    return [level for level in levels if level is not None and level > entry]


def _levels_below(entry: float, *levels: float | None) -> list[float]:
    return [level for level in levels if level is not None and level < entry]


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


def _trend_direction(features: Features) -> str:
    if features.ema_50 is None or features.ema_200 is None:
        return "unknown"
    if features.close > features.ema_200 and features.ema_50 > features.ema_200:
        return "bullish"
    if features.close < features.ema_200 and features.ema_50 < features.ema_200:
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
            f"{body_threshold:.2f} ATR; wait for pullback to {pullback_target}"
        )
    elif impulse_range_overextended:
        reason = (
            f"Signal candle range is {range_atr:.2f} ATR with an impulse close near the extreme; "
            f"wait for retest of {pullback_target}"
        )
    elif rejection_wick_overextended:
        reason = (
            f"Signal candle has a {rejection_wick:.0%} rejection wick and {range_atr:.2f} ATR range; "
            f"wait for fresh reclaim or pullback to {pullback_target}"
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


def _pullback_target(signal: StrategySignal, features: Features) -> str:
    direction = signal.direction.lower()
    if signal.strategy == "volatility_squeeze_breakout":
        if direction == "long" and features.donchian_high_20 is not None:
            return f"breakout level {features.donchian_high_20:.8f}"
        if direction == "short" and features.donchian_low_20 is not None:
            return f"breakdown level {features.donchian_low_20:.8f}"
        return "the breakout trigger level"
    if signal.strategy == "trend_pullback_continuation":
        ema_levels = [level for level in (features.ema_20, features.ema_50) if level is not None]
        if ema_levels:
            target = min(ema_levels, key=lambda level: abs(features.close - level))
            return f"EMA pullback zone {target:.8f}"
        return "the EMA/VWAP pullback zone"
    if signal.strategy == "liquidity_sweep_reversal":
        if direction == "long" and features.swing_low is not None:
            return f"swept low {features.swing_low:.8f}"
        if direction == "short" and features.swing_high is not None:
            return f"swept high {features.swing_high:.8f}"
        return "the swept liquidity level"
    return "the trigger level or VWAP"


def _assess_risk_reward(signal: StrategySignal, params: Mapping[str, Any]) -> RiskRewardAssessment:
    min_rr = _strategy_numeric_param(params, "min_rr_ratio", signal.strategy, DEFAULT_MIN_RR_RATIO)
    if min_rr <= 0:
        return RiskRewardAssessment(
            passed=True,
            rr=signal.risk_reward,
            min_rr=min_rr,
            target_label="disabled",
            first_target_rr=_target_rr(signal, signal.take_profit_1),
            final_target_rr=_target_rr(signal, signal.take_profit_2 or signal.take_profit_1),
            reason="Risk/reward guard is disabled for this strategy",
        )

    first_target_rr = _target_rr(signal, signal.take_profit_1)
    final_target_rr = _target_rr(signal, signal.take_profit_2 or signal.take_profit_1)
    rr_target = str(params.get("rr_target") or "final").strip().lower()
    if rr_target in {"first", "nearest", "tp1"}:
        selected_rr = first_target_rr
        target_label = "nearest target"
    else:
        selected_rr = final_target_rr if final_target_rr is not None else signal.risk_reward
        target_label = "planned final target"

    if selected_rr is None:
        return RiskRewardAssessment(
            passed=False,
            rr=None,
            min_rr=min_rr,
            target_label=target_label,
            first_target_rr=first_target_rr,
            final_target_rr=final_target_rr,
            reason="Risk/reward blocked: entry, stop or target is missing",
        )

    if selected_rr < min_rr:
        nearest_text = "-" if first_target_rr is None else f"{first_target_rr:.2f}R"
        final_text = "-" if final_target_rr is None else f"{final_target_rr:.2f}R"
        return RiskRewardAssessment(
            passed=False,
            rr=selected_rr,
            min_rr=min_rr,
            target_label=target_label,
            first_target_rr=first_target_rr,
            final_target_rr=final_target_rr,
            reason=(
                f"Risk/reward blocked: {target_label} is {selected_rr:.2f}R, "
                f"below configured minimum {min_rr:.2f}R "
                f"(nearest {nearest_text}, final {final_text})"
            ),
        )

    return RiskRewardAssessment(
        passed=True,
        rr=selected_rr,
        min_rr=min_rr,
        target_label=target_label,
        first_target_rr=first_target_rr,
        final_target_rr=final_target_rr,
        reason=f"Risk/reward passed: {target_label} is {selected_rr:.2f}R, minimum {min_rr:.2f}R",
    )


def _target_rr(signal: StrategySignal, target: float | None) -> float | None:
    entry = _entry_price(signal)
    stop = signal.stop_loss
    if entry is None or stop is None or target is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    if signal.direction.lower() == "long":
        reward = target - entry
    else:
        reward = entry - target
    return round(reward / risk, 4)


def _hide_failed_rr_signals(params: Mapping[str, Any]) -> bool:
    return bool(params.get("hide_failed_rr_signals") or params.get("hide_low_rr_signals"))


def _entry_price(signal: StrategySignal) -> float | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    return signal.entry_max
