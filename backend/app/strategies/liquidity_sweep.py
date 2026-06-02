from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, List, Literal, Mapping, Optional

from app.schemas.market import AlphaMarketContext, Features, LiquidityPoolFeatures
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.services.risk_reward_plan import risk_reward_plan_service
from app.services.support_resistance import SupportResistanceSnapshot
from app.strategies.common import build_signal, has_minimum_market_data, score_breakdown

STRATEGY_NAME = "liquidity_sweep_reversal"
MIN_VISIBLE_SETUP_SCORE = 45
DEFAULT_MIN_SWEEP_WICK_RATIO = 0.45
DEFAULT_SWEEP_VOLUME_SPIKE_MULTIPLIER = 1.3
DEFAULT_CONFIRMATION_VOLUME_SPIKE = 1.1
DEFAULT_WATCHLIST_DISTANCE_ATR = 0.6
DEFAULT_SWEEP_STOP_ATR = 0.3
DEFAULT_AGGRESSIVE_CLOSE_POSITION = 0.6
DEFAULT_MIN_LEVEL_RETESTS = 2
DEFAULT_OI_FLUSH_THRESHOLD = -0.01
DEFAULT_OI_FLUSH_BONUS = 8
DEFAULT_LIQUIDATION_FLUSH_BONUS = 6
DEFAULT_REQUIRE_ABSORPTION = False
DEFAULT_MIN_ABSORPTION_SCORE = 0.35
DEFAULT_MIN_CVD_DIVERGENCE_SCORE = 0.0
DEFAULT_MIN_OI_FLUSH_SCORE = 0.0
DEFAULT_MIN_OBVIOUS_LIQUIDITY_SCORE = 0.45
DEFAULT_MIN_TARGET_DISTANCE_R = 0.0
DEFAULT_ALPHA_MISSING_SOURCES = (
    "alpha_context",
    "recent_trades",
    "orderbook_l2",
    "derivative_history",
    "liquidation_data",
)


@dataclass(frozen=True)
class ObviousLiquidityLevel:
    price: float
    name: str
    source: str
    score: float
    touch_count: int = 0
    volume_score: float | None = None
    thesis: str = "visible liquidity"


@dataclass(frozen=True)
class MarketTarget:
    price: float
    source: str
    thesis: str
    priority: int


@dataclass(frozen=True)
class SweepTargets:
    take_profit_1: float | None
    take_profit_2: float | None
    target_sources: Mapping[str, str]
    target_thesis: str
    market_target_source: str | None
    htf_target_distance_r: float | None


@dataclass(frozen=True)
class SweepSetup:
    direction: Literal["LONG", "SHORT"]
    status: str
    status_reason: str
    level: float
    level_name: str
    swept: bool
    reclaimed: bool
    wick_ratio: float
    close_position: float
    volume_ok: bool
    strong_wick: bool
    confirmation: bool
    micro_bos: bool
    close_settled_beyond_level: bool
    continued_breakout: bool
    strong_trend_against: bool
    touch_count: int
    level_volume_score: float | None
    sweep_extreme: float
    require_reclaim: bool
    obvious_liquidity_score: float
    reclaim_score: float
    absorption_score: float
    cvd_divergence_score: float
    oi_flush_score: float
    liquidation_flush_score: float
    failed_continuation_score: float
    htf_target_distance_r: float | None
    market_target_source: str | None
    alpha_context_used: bool
    missing_alpha_sources: tuple[str, ...]


class LiquiditySweepReversalStrategy:
    name = STRATEGY_NAME
    version = "1.1"
    required_data = [
        "swing_high",
        "swing_low",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "volume_spike",
        "rsi_14",
        "atr_14",
    ]

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> List[StrategySignal]:
        params = params or {}
        min_history = int(_numeric_param(params, "min_history", 30))
        if not has_minimum_market_data(features, min_history=min_history):
            return []

        setup = self._setup_state(features, params)
        if setup is None:
            return []

        atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
        stop_atr = _numeric_param(params, "sweep_stop_atr", DEFAULT_SWEEP_STOP_ATR)
        entry = features.close
        if setup.direction == "LONG":
            stop_loss = setup.sweep_extreme - atr * stop_atr
        else:
            stop_loss = setup.sweep_extreme + atr * stop_atr
        targets = _select_sweep_targets(
            features=features,
            direction=setup.direction,
            swept_level=setup.level,
            entry=entry,
            stop_loss=stop_loss,
            alpha_context=_alpha_context_param(params),
            support_resistance_by_timeframe=_support_resistance_by_timeframe_param(params),
        )
        setup = replace(
            setup,
            htf_target_distance_r=targets.htf_target_distance_r,
            market_target_source=targets.market_target_source,
        )
        setup = _apply_target_room_gate(setup, params)

        scoring, reasons, risks = self._score(features, setup, params)
        take_profit_1 = targets.take_profit_1
        take_profit_2 = targets.take_profit_2

        reasons.append(f"Swept liquidity level: {setup.level:.8f}")
        if take_profit_1 is not None and take_profit_2 is not None:
            reasons.append(
                f"Range targets: midpoint {take_profit_1:.8f}, opposite boundary {take_profit_2:.8f}"
            )
        if targets.market_target_source is not None:
            reasons.append(f"Market target thesis: {targets.target_thesis}")
        if setup.htf_target_distance_r is not None:
            reasons.append(f"Nearest market target distance is {setup.htf_target_distance_r:.2f}R")
        if setup.touch_count >= DEFAULT_MIN_LEVEL_RETESTS:
            reasons.append(f"Level has {setup.touch_count} recent touches")
        if setup.confirmation:
            reasons.append("Conservative confirmation candle closed through micro structure")
        elif setup.micro_bos:
            reasons.append("Sweep candle also broke micro structure toward reversal")
        if not setup.alpha_context_used:
            risks.append("Alpha context unavailable; candle and volume proxy was used for orderflow evidence")
        if setup.missing_alpha_sources:
            risks.append(f"Missing alpha sources: {', '.join(setup.missing_alpha_sources)}")

        signal = build_signal(
            features=features,
            strategy=self.name,
            direction=setup.direction,
            scoring=scoring,
            reasons=reasons,
            risks=risks,
            entry=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
        )
        signal = self._enrich_trade_plan(signal, setup, targets)
        if signal.score < MIN_VISIBLE_SETUP_SCORE and setup.status != "rejected":
            return []
        return [
            signal.model_copy(
                update={
                    "status": setup.status,
                    "status_reason": setup.status_reason,
                }
            )
        ]

    def _direction(self, features: Features) -> Optional[Literal["LONG", "SHORT"]]:
        setup = self._setup_state(features, {})
        return setup.direction if setup is not None else None

    def _setup_state(
        self,
        features: Features,
        params: Mapping[str, Any],
    ) -> Optional[SweepSetup]:
        candidates = [
            candidate
            for candidate in (
                self._candidate(features, params, "LONG"),
                self._candidate(features, params, "SHORT"),
            )
            if candidate is not None
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        return max(candidates, key=_candidate_priority)

    def _candidate(
        self,
        features: Features,
        params: Mapping[str, Any],
        direction: Literal["LONG", "SHORT"],
    ) -> SweepSetup | None:
        alpha_context = _alpha_context_param(params)
        missing_alpha_sources = _missing_alpha_sources(alpha_context)
        atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
        min_wick_ratio = _numeric_param(params, "min_sweep_wick_ratio", DEFAULT_MIN_SWEEP_WICK_RATIO)
        volume_multiplier = _numeric_param(
            params,
            "sweep_volume_spike_multiplier",
            DEFAULT_SWEEP_VOLUME_SPIKE_MULTIPLIER,
        )
        confirmation_volume = _numeric_param(
            params,
            "confirmation_volume_spike",
            DEFAULT_CONFIRMATION_VOLUME_SPIKE,
        )
        watchlist_distance_atr = _numeric_param(
            params,
            "watchlist_distance_atr",
            DEFAULT_WATCHLIST_DISTANCE_ATR,
        )
        aggressive_close_position = _numeric_param(
            params,
            "sweep_aggressive_close_position",
            DEFAULT_AGGRESSIVE_CLOSE_POSITION,
        )
        require_reclaim = _bool_param(params, "require_reclaim", True)
        level = _select_obvious_liquidity_level(features, params, direction, alpha_context)
        if level is None:
            return None

        if direction == "LONG":
            swept = features.low < level.price
            reclaimed = features.close > level.price
            wick_ratio = features.lower_wick_ratio or 0.0
            close_position = _directional_close_position(direction, features)
            sweep_extreme = features.low
            previous_swept = features.previous_low is not None and features.previous_low < level.price
            previous_reclaimed = features.previous_close is not None and features.previous_close > level.price
            confirmation = (
                previous_swept
                and previous_reclaimed
                and features.previous_high is not None
                and features.close > features.previous_high
                and features.close > features.open
                and features.volume_spike >= confirmation_volume
            )
            micro_bos = features.previous_high is not None and features.close > features.previous_high
            close_settled_beyond_level = swept and not reclaimed
            continued_breakout = (
                previous_swept
                and not previous_reclaimed
                and features.previous_low is not None
                and features.close < level.price
                and features.low < features.previous_low
            )
            near_level = 0 <= features.close - level.price <= atr * watchlist_distance_atr
        else:
            swept = features.high > level.price
            reclaimed = features.close < level.price
            wick_ratio = features.upper_wick_ratio or 0.0
            close_position = _directional_close_position(direction, features)
            sweep_extreme = features.high
            previous_swept = features.previous_high is not None and features.previous_high > level.price
            previous_reclaimed = features.previous_close is not None and features.previous_close < level.price
            confirmation = (
                previous_swept
                and previous_reclaimed
                and features.previous_low is not None
                and features.close < features.previous_low
                and features.close < features.open
                and features.volume_spike >= confirmation_volume
            )
            micro_bos = features.previous_low is not None and features.close < features.previous_low
            close_settled_beyond_level = swept and not reclaimed
            continued_breakout = (
                previous_swept
                and not previous_reclaimed
                and features.previous_high is not None
                and features.close > level.price
                and features.high > features.previous_high
            )
            near_level = 0 <= level.price - features.close <= atr * watchlist_distance_atr

        volume_ok = features.volume_spike >= volume_multiplier
        strong_wick = wick_ratio >= min_wick_ratio
        strong_close = close_position >= aggressive_close_position
        strong_trend_against = _strong_trend_against(direction, features)
        reclaim_score = _reclaim_score(
            swept=swept,
            reclaimed=reclaimed,
            confirmation=confirmation,
            close_settled_beyond_level=close_settled_beyond_level,
            continued_breakout=continued_breakout,
        )
        absorption_score = _absorption_score(
            direction=direction,
            features=features,
            alpha_context=alpha_context,
            swept=swept,
            reclaimed=reclaimed,
            strong_wick=strong_wick,
            volume_ok=volume_ok,
            strong_close=strong_close,
        )
        cvd_divergence_score = _cvd_divergence_score(
            direction=direction,
            features=features,
            alpha_context=alpha_context,
            swept=swept,
        )
        oi_flush_score = _oi_flush_score(features, alpha_context, params)
        liquidation_flush_score = _liquidation_flush_score(
            direction=direction,
            level=level.price,
            features=features,
            alpha_context=alpha_context,
        )
        failed_continuation_score = _failed_continuation_score(
            swept=swept,
            reclaimed=reclaimed,
            confirmation=confirmation,
            micro_bos=micro_bos,
            continued_breakout=continued_breakout,
        )

        def build_setup(
            *,
            status: str,
            status_reason: str,
            swept_value: bool,
            reclaimed_value: bool,
            confirmation_value: bool,
            micro_bos_value: bool,
            close_settled_beyond_level_value: bool,
            continued_breakout_value: bool,
            sweep_extreme_value: float,
        ) -> SweepSetup:
            return SweepSetup(
                direction=direction,
                status=status,
                status_reason=status_reason,
                level=level.price,
                level_name=level.name,
                swept=swept_value,
                reclaimed=reclaimed_value,
                wick_ratio=wick_ratio,
                close_position=close_position,
                volume_ok=volume_ok,
                strong_wick=strong_wick,
                confirmation=confirmation_value,
                micro_bos=micro_bos_value,
                close_settled_beyond_level=close_settled_beyond_level_value,
                continued_breakout=continued_breakout_value,
                strong_trend_against=strong_trend_against,
                touch_count=level.touch_count,
                level_volume_score=level.volume_score,
                sweep_extreme=sweep_extreme_value,
                require_reclaim=require_reclaim,
                obvious_liquidity_score=level.score,
                reclaim_score=reclaim_score,
                absorption_score=absorption_score,
                cvd_divergence_score=cvd_divergence_score,
                oi_flush_score=oi_flush_score,
                liquidation_flush_score=liquidation_flush_score,
                failed_continuation_score=failed_continuation_score,
                htf_target_distance_r=None,
                market_target_source=None,
                alpha_context_used=alpha_context is not None,
                missing_alpha_sources=missing_alpha_sources,
            )

        if continued_breakout:
            return build_setup(
                status="rejected",
                status_reason="Sweep failed as a reversal because the next candle continued the breakout",
                swept_value=True,
                reclaimed_value=False,
                confirmation_value=False,
                micro_bos_value=micro_bos,
                close_settled_beyond_level_value=True,
                continued_breakout_value=True,
                sweep_extreme_value=sweep_extreme,
            )

        if (
            strong_trend_against
            and _bool_param(params, "require_absorption", DEFAULT_REQUIRE_ABSORPTION)
            and absorption_score < _numeric_param(params, "min_absorption_score", DEFAULT_MIN_ABSORPTION_SCORE)
        ):
            return build_setup(
                status="watchlist",
                status_reason="Strong trend is against the reversal and absorption evidence is below threshold",
                swept_value=swept,
                reclaimed_value=reclaimed,
                confirmation_value=False,
                micro_bos_value=micro_bos,
                close_settled_beyond_level_value=close_settled_beyond_level,
                continued_breakout_value=False,
                sweep_extreme_value=sweep_extreme,
            )

        if confirmation:
            status, status_reason = _actionable_status_from_thresholds(
                default_reason="Confirmation candle reclaimed micro structure after the liquidity sweep",
                setup_status="actionable",
                alpha_context=alpha_context,
                obvious_liquidity_score=level.score,
                absorption_score=absorption_score,
                cvd_divergence_score=cvd_divergence_score,
                oi_flush_score=oi_flush_score,
                params=params,
            )
            return build_setup(
                status=status,
                status_reason=status_reason,
                swept_value=True,
                reclaimed_value=True,
                confirmation_value=True,
                micro_bos_value=True,
                close_settled_beyond_level_value=False,
                continued_breakout_value=False,
                sweep_extreme_value=features.previous_low
                if direction == "LONG" and features.previous_low is not None
                else features.previous_high
                if direction == "SHORT" and features.previous_high is not None
                else sweep_extreme,
            )

        if swept and reclaimed:
            actionable = strong_wick and volume_ok and strong_close
            if actionable:
                status, status_reason = _actionable_status_from_thresholds(
                    default_reason="Swept level was reclaimed with a strong wick, close and volume",
                    setup_status="actionable",
                    alpha_context=alpha_context,
                    obvious_liquidity_score=level.score,
                    absorption_score=absorption_score,
                    cvd_divergence_score=cvd_divergence_score,
                    oi_flush_score=oi_flush_score,
                    params=params,
                )
            else:
                status = "ready"
                status_reason = "Swept level was reclaimed; waiting for stronger wick, volume or confirmation candle"
            return build_setup(
                status=status,
                status_reason=status_reason,
                swept_value=True,
                reclaimed_value=True,
                confirmation_value=False,
                micro_bos_value=micro_bos,
                close_settled_beyond_level_value=False,
                continued_breakout_value=False,
                sweep_extreme_value=sweep_extreme,
            )

        if swept:
            if level.source != "swing":
                return None
            return build_setup(
                status="ready",
                status_reason=(
                    f"{level.name} was swept; waiting for reclaim above the level"
                    if direction == "LONG" and require_reclaim
                    else f"{level.name} was swept; waiting for rejection below the level"
                    if direction == "SHORT" and require_reclaim
                    else "Liquidity was swept; reclaim is optional by config, but reversal confirmation is still incomplete"
                ),
                swept_value=True,
                reclaimed_value=False,
                confirmation_value=False,
                micro_bos_value=micro_bos,
                close_settled_beyond_level_value=True,
                continued_breakout_value=False,
                sweep_extreme_value=sweep_extreme,
            )

        if near_level:
            return build_setup(
                status="watchlist",
                status_reason=(
                    f"Price is testing {level.name}; waiting for liquidity sweep and reclaim"
                    if direction == "LONG"
                    else f"Price is testing {level.name}; waiting for liquidity sweep and rejection"
                ),
                swept_value=False,
                reclaimed_value=False,
                confirmation_value=False,
                micro_bos_value=False,
                close_settled_beyond_level_value=False,
                continued_breakout_value=False,
                sweep_extreme_value=sweep_extreme,
            )

        return None

    def _score(
        self,
        features: Features,
        setup: SweepSetup,
        params: Mapping[str, Any],
    ) -> tuple[SignalScoreBreakdown, list[str], list[str]]:
        trend_score = 0
        liquidity_score = 0
        volume_score = 0
        orderbook_score = 0
        overheat_penalty = 0
        reasons: list[str] = []
        risks: list[str] = []

        min_level_retests = int(_numeric_param(params, "min_level_retests", DEFAULT_MIN_LEVEL_RETESTS))

        liquidity_score += int(round(setup.obvious_liquidity_score * 30))
        reasons.append(
            f"Obvious liquidity score {setup.obvious_liquidity_score:.2f}: {setup.level_name}"
        )

        if setup.touch_count >= min_level_retests:
            liquidity_score += 10
            reasons.append("Level has equal-high/low style retests")

        if setup.level_volume_score is not None and setup.level_volume_score >= 1.2:
            liquidity_score += 5
            reasons.append(f"Volume accumulated near level: {setup.level_volume_score:.2f}x average")

        if setup.swept and setup.reclaimed:
            liquidity_score += int(round(setup.reclaim_score * 20))
            reasons.append("Price swept liquidity and closed back inside the range")
        elif setup.swept:
            liquidity_score += 10
            reasons.append("Price swept visible liquidity")
            risks.append("Sweep has not reclaimed the level yet")
        else:
            liquidity_score += 8
            reasons.append("Price is close to visible liquidity")

        if setup.absorption_score > 0:
            absorption_points = int(round(setup.absorption_score * 15))
            orderbook_score += absorption_points
            reasons.append(f"Absorption proxy score {setup.absorption_score:.2f}")
        elif _bool_param(params, "require_absorption", DEFAULT_REQUIRE_ABSORPTION):
            risks.append("Absorption evidence is below the configured threshold")

        if setup.cvd_divergence_score > 0:
            orderbook_score += int(round(setup.cvd_divergence_score * 10))
            reasons.append(f"CVD/delta divergence score {setup.cvd_divergence_score:.2f}")
        elif _numeric_param(params, "min_cvd_divergence_score", DEFAULT_MIN_CVD_DIVERGENCE_SCORE) > 0:
            risks.append("CVD divergence is below the configured threshold")

        if setup.oi_flush_score > 0:
            oi_bonus = int(_numeric_param(params, "oi_flush_bonus", DEFAULT_OI_FLUSH_BONUS))
            orderbook_score += int(round(setup.oi_flush_score * oi_bonus))
            reasons.append(f"Open interest flush score {setup.oi_flush_score:.2f}")
        elif _bool_param(params, "require_oi_flush", False):
            risks.append("Open-interest flush is required but was not confirmed")

        if setup.liquidation_flush_score > 0:
            liquidation_bonus = int(
                _numeric_param(params, "liquidation_flush_bonus", DEFAULT_LIQUIDATION_FLUSH_BONUS)
            )
            orderbook_score += int(round(setup.liquidation_flush_score * liquidation_bonus))
            reasons.append(f"Liquidation flush score {setup.liquidation_flush_score:.2f}")

        if setup.failed_continuation_score > 0:
            orderbook_score += int(round(setup.failed_continuation_score * 8))
            reasons.append(f"Failed-continuation score {setup.failed_continuation_score:.2f}")

        if setup.strong_wick:
            orderbook_score += 15
            reasons.append(f"Rejection wick ratio is {setup.wick_ratio:.0%}")
        elif setup.swept:
            risks.append(f"Wick ratio {setup.wick_ratio:.0%} is below the sweep threshold")

        if setup.volume_ok:
            volume_score += 10
            reasons.append(f"Sweep volume is {features.volume_spike:.2f}x average")
        elif setup.swept or setup.reclaimed:
            risks.append("Sweep lacks strong volume confirmation")

        if setup.confirmation:
            orderbook_score += 10
        if setup.micro_bos:
            orderbook_score += 10

        if features.adx is None or features.adx <= 30 or not setup.strong_trend_against:
            trend_score += 5
            reasons.append("ADX/context is not a strong local trend against the reversal")

        if setup.close_settled_beyond_level:
            overheat_penalty += 25
            risks.append("Close settled beyond the swept level; this may be a real breakout")
        if setup.continued_breakout:
            overheat_penalty += 20
            risks.append("Next candle continued the breakout instead of reversing")
        if setup.htf_target_distance_r is not None:
            min_distance = _numeric_param(params, "min_target_distance_r", DEFAULT_MIN_TARGET_DISTANCE_R)
            if setup.htf_target_distance_r < min_distance:
                overheat_penalty += 20
                risks.append(
                    f"Nearest market target is only {setup.htf_target_distance_r:.2f}R away; "
                    f"minimum is {min_distance:.2f}R"
                )
        if setup.strong_trend_against:
            overheat_penalty += 20
            risks.append("Sweep is against a strong local trend")

        if setup.direction == "LONG" and features.rsi_14 is not None and features.rsi_14 < 25:
            risks.append("RSI below 25: downside momentum may continue")
            overheat_penalty += 10
        if setup.direction == "SHORT" and features.rsi_14 is not None and features.rsi_14 > 75:
            risks.append("RSI above 75: upside momentum may continue")
            overheat_penalty += 10

        return (
            score_breakdown(
                trend_score=trend_score,
                volume_score=volume_score,
                liquidity_score=liquidity_score,
                orderbook_score=orderbook_score,
                overheat_penalty=overheat_penalty,
            ),
            reasons,
            risks,
        )

    def _enrich_trade_plan(
        self,
        signal: StrategySignal,
        setup: SweepSetup,
        targets: SweepTargets,
    ) -> StrategySignal:
        trade_plan = signal.trade_plan
        if trade_plan is None:
            return signal
        entry_metadata = dict(trade_plan.entry.metadata)
        entry_metadata.update(
            {
                "entry_model": "reclaim" if setup.reclaimed else "wait_for_reclaim",
                "swept_level": setup.level,
                "level_name": setup.level_name,
                "confirmation": setup.confirmation,
                "micro_bos": setup.micro_bos,
                "obvious_liquidity_score": setup.obvious_liquidity_score,
                "reclaim_score": setup.reclaim_score,
                "absorption_score": setup.absorption_score,
                "cvd_divergence_score": setup.cvd_divergence_score,
                "oi_flush_score": setup.oi_flush_score,
                "liquidation_flush_score": setup.liquidation_flush_score,
                "failed_continuation_score": setup.failed_continuation_score,
                "alpha_context_used": setup.alpha_context_used,
                "missing_alpha_sources": list(setup.missing_alpha_sources),
            }
        )
        entry = trade_plan.entry.model_copy(
            update={
                "source": "liquidity_reclaim" if setup.reclaimed else "liquidity_sweep_watch",
                "metadata": entry_metadata,
            }
        )
        enriched_targets = []
        for target in trade_plan.targets:
            market_source = targets.target_sources.get(target.label)
            target_metadata = {
                **target.metadata,
                "target_model": "range_midpoint_opposite_boundary",
                "target_thesis": targets.target_thesis,
                "swept_level": setup.level,
                "market_target_source": market_source or target.source,
                "htf_target_distance_r": setup.htf_target_distance_r,
            }
            update: dict[str, Any] = {"metadata": target_metadata}
            if market_source is not None and not target.metadata.get("fallback_target_used"):
                update["source"] = market_source
            enriched_targets.append(target.model_copy(update=update))
        invalidation = trade_plan.invalidation.model_copy(
            update={
                "conditions": [
                    *trade_plan.invalidation.conditions,
                    "Reclaim fails and price settles beyond swept level",
                    "Sweep extreme is broken again",
                ],
                "metadata": {
                    **trade_plan.invalidation.metadata,
                    "swept_level": setup.level,
                    "sweep_extreme": setup.sweep_extreme,
                    "requires_reclaim": setup.require_reclaim,
                    "continued_breakout": setup.continued_breakout,
                    "acceptance_failure": setup.close_settled_beyond_level,
                    "alpha_context_used": setup.alpha_context_used,
                    "missing_alpha_sources": list(setup.missing_alpha_sources),
                },
            }
        ) if trade_plan.invalidation is not None else None
        score_metadata = {
            "obvious_liquidity_score": setup.obvious_liquidity_score,
            "reclaim_score": setup.reclaim_score,
            "absorption_score": setup.absorption_score,
            "cvd_divergence_score": setup.cvd_divergence_score,
            "oi_flush_score": setup.oi_flush_score,
            "liquidation_flush_score": setup.liquidation_flush_score,
            "failed_continuation_score": setup.failed_continuation_score,
            "htf_target_distance_r": setup.htf_target_distance_r,
            "market_target_source": setup.market_target_source,
            "alpha_context_used": setup.alpha_context_used,
            "missing_alpha_sources": list(setup.missing_alpha_sources),
        }
        enriched_plan = trade_plan.model_copy(
            update={
                "entry": entry,
                "targets": enriched_targets,
                "invalidation": invalidation,
                "metadata": {
                    **trade_plan.metadata,
                    "target_model": "range_midpoint_opposite_boundary",
                    "target_source": targets.market_target_source,
                    "market_target_source": targets.market_target_source,
                    "target_thesis": targets.target_thesis,
                    "htf_target_distance_r": setup.htf_target_distance_r,
                    "strong_trend_against": setup.strong_trend_against,
                    "liquidity_sweep_score_breakdown": score_metadata,
                    "alpha_context_used": setup.alpha_context_used,
                    "missing_alpha_sources": list(setup.missing_alpha_sources),
                },
            },
            deep=True,
        )
        return signal.model_copy(update={"trade_plan": enriched_plan})


def _select_obvious_liquidity_level(
    features: Features,
    params: Mapping[str, Any],
    direction: Literal["LONG", "SHORT"],
    alpha_context: AlphaMarketContext | None,
) -> ObviousLiquidityLevel | None:
    atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
    watchlist_distance_atr = _numeric_param(
        params,
        "watchlist_distance_atr",
        DEFAULT_WATCHLIST_DISTANCE_ATR,
    )
    candidates = _obvious_liquidity_levels(features, direction, alpha_context)
    ranked: list[tuple[tuple[int, float, float], ObviousLiquidityLevel]] = []
    for level in candidates:
        state_rank = _level_state_rank(features, direction, level.price, atr, watchlist_distance_atr)
        if state_rank <= 0:
            continue
        if state_rank == 2 and level.source != "swing":
            continue
        distance = abs(features.close - level.price)
        ranked.append(((state_rank, level.score, -distance), level))
    if not ranked:
        return None
    return max(ranked, key=lambda item: item[0])[1]


def _obvious_liquidity_levels(
    features: Features,
    direction: Literal["LONG", "SHORT"],
    alpha_context: AlphaMarketContext | None,
) -> list[ObviousLiquidityLevel]:
    if direction == "LONG":
        raw_levels = (
            ("session_low", "session", features.session_low, 1, None, "session low liquidity"),
            ("previous_day_low", "previous_day", features.previous_day_low, 1, None, "previous day low liquidity"),
            ("range_low", "range", features.donchian_low_20, 1, None, "range low liquidity"),
            (
                "swing_low",
                "swing",
                features.swing_low,
                features.swing_low_touch_count,
                features.swing_low_volume_score,
                "swing/equal-low liquidity",
            ),
        )
        pool_side = "below"
    else:
        raw_levels = (
            ("session_high", "session", features.session_high, 1, None, "session high liquidity"),
            ("previous_day_high", "previous_day", features.previous_day_high, 1, None, "previous day high liquidity"),
            ("range_high", "range", features.donchian_high_20, 1, None, "range high liquidity"),
            (
                "swing_high",
                "swing",
                features.swing_high,
                features.swing_high_touch_count,
                features.swing_high_volume_score,
                "swing/equal-high liquidity",
            ),
        )
        pool_side = "above"

    levels: list[ObviousLiquidityLevel] = []
    for name, source, price, touch_count, volume_score, thesis in raw_levels:
        level = _liquidity_level_from_values(
            name=name,
            source=source,
            price=price,
            touch_count=touch_count,
            volume_score=volume_score,
            thesis=thesis,
        )
        if level is not None:
            levels.append(level)

    if alpha_context is not None:
        for pool in alpha_context.session_liquidity_pools:
            if pool.side != pool_side:
                continue
            level = _liquidity_level_from_pool(pool)
            if level is not None:
                levels.append(level)

    return _dedupe_liquidity_levels(levels)


def _liquidity_level_from_values(
    *,
    name: str,
    source: str,
    price: float | None,
    touch_count: int,
    volume_score: float | None,
    thesis: str,
) -> ObviousLiquidityLevel | None:
    if price is None or price <= 0:
        return None
    score = _obvious_liquidity_score(source=source, touch_count=touch_count, volume_score=volume_score)
    return ObviousLiquidityLevel(
        price=price,
        name=name,
        source=source,
        score=score,
        touch_count=touch_count,
        volume_score=volume_score,
        thesis=thesis,
    )


def _liquidity_level_from_pool(pool: LiquidityPoolFeatures) -> ObviousLiquidityLevel | None:
    if pool.price <= 0:
        return None
    strength = pool.strength
    touch_count = int(pool.metadata.get("touch_count") or 1)
    score = _obvious_liquidity_score(
        source=f"alpha_{pool.source}",
        touch_count=touch_count,
        volume_score=strength,
    )
    if strength is not None and strength > 10:
        score = max(score, min(1.0, 0.55 + strength / 200))
    return ObviousLiquidityLevel(
        price=pool.price,
        name=pool.name,
        source=f"alpha_{pool.source}",
        score=score,
        touch_count=touch_count,
        volume_score=strength,
        thesis=f"{pool.source} liquidity pool",
    )


def _obvious_liquidity_score(
    *,
    source: str,
    touch_count: int,
    volume_score: float | None,
) -> float:
    source_base = 0.55
    if "previous_day" in source:
        source_base = 0.82
    elif "session" in source:
        source_base = 0.76
    elif "alpha" in source:
        source_base = 0.72
    elif "range" in source:
        source_base = 0.68
    elif "swing" in source:
        source_base = 0.64

    touch_bonus = min(0.18, max(touch_count - 1, 0) * 0.06)
    volume_bonus = 0.0
    if volume_score is not None:
        if volume_score >= 10:
            volume_bonus = min(0.18, volume_score / 500)
        elif volume_score >= 1.2:
            volume_bonus = min(0.15, (volume_score - 1.0) * 0.1)
    return _clamp01(source_base + touch_bonus + volume_bonus)


def _dedupe_liquidity_levels(levels: list[ObviousLiquidityLevel]) -> list[ObviousLiquidityLevel]:
    best_by_price: dict[int, ObviousLiquidityLevel] = {}
    for level in levels:
        key = round(level.price * 100_000_000)
        existing = best_by_price.get(key)
        if existing is None or level.score > existing.score:
            best_by_price[key] = level
    return list(best_by_price.values())


def _level_state_rank(
    features: Features,
    direction: Literal["LONG", "SHORT"],
    price: float,
    atr: float,
    watchlist_distance_atr: float,
) -> int:
    if direction == "LONG":
        previous_swept = features.previous_low is not None and features.previous_low < price
        previous_reclaimed = features.previous_close is not None and features.previous_close > price
        confirms_previous = (
            previous_swept
            and previous_reclaimed
            and features.previous_high is not None
            and features.close > features.previous_high
        )
        if confirms_previous:
            return 3
        if features.low < price and features.close > price:
            return 3
        if features.low < price:
            return 2
        if 0 <= features.close - price <= atr * watchlist_distance_atr:
            return 1
        return 0
    previous_swept = features.previous_high is not None and features.previous_high > price
    previous_reclaimed = features.previous_close is not None and features.previous_close < price
    confirms_previous = (
        previous_swept
        and previous_reclaimed
        and features.previous_low is not None
        and features.close < features.previous_low
    )
    if confirms_previous:
        return 3
    if features.high > price and features.close < price:
        return 3
    if features.high > price:
        return 2
    if 0 <= price - features.close <= atr * watchlist_distance_atr:
        return 1
    return 0


def _reclaim_score(
    *,
    swept: bool,
    reclaimed: bool,
    confirmation: bool,
    close_settled_beyond_level: bool,
    continued_breakout: bool,
) -> float:
    if continued_breakout:
        return 0.0
    if confirmation:
        return 1.0
    if swept and reclaimed:
        return 0.9
    if swept and close_settled_beyond_level:
        return 0.15
    return 0.0


def _absorption_score(
    *,
    direction: Literal["LONG", "SHORT"],
    features: Features,
    alpha_context: AlphaMarketContext | None,
    swept: bool,
    reclaimed: bool,
    strong_wick: bool,
    volume_ok: bool,
    strong_close: bool,
) -> float:
    score = 0.0
    if swept and reclaimed and strong_wick and volume_ok:
        score = max(score, 0.45)
    if swept and reclaimed and strong_wick and volume_ok and strong_close:
        score = max(score, 0.62)
    if alpha_context is None:
        return score

    if alpha_context.absorption_score is not None:
        score = max(score, min(1.0, alpha_context.absorption_score))
    if alpha_context.sweep_through_book and reclaimed:
        score = max(score, 0.82)
    if _orderbook_supports_reversal(direction, alpha_context):
        score = max(score, 0.72)
    if _delta_does_not_confirm_extreme(direction, alpha_context):
        score = max(score, 0.68)
    return _clamp01(score)


def _orderbook_supports_reversal(
    direction: Literal["LONG", "SHORT"],
    alpha_context: AlphaMarketContext,
) -> bool:
    if direction == "LONG":
        if alpha_context.depth_wall_side == "bid":
            return True
        return alpha_context.orderbook_imbalance is not None and alpha_context.orderbook_imbalance > 0.15
    if alpha_context.depth_wall_side == "ask":
        return True
    return alpha_context.orderbook_imbalance is not None and alpha_context.orderbook_imbalance < -0.15


def _delta_does_not_confirm_extreme(
    direction: Literal["LONG", "SHORT"],
    alpha_context: AlphaMarketContext,
) -> bool:
    if direction == "LONG":
        if alpha_context.delta_divergence == "bullish_divergence":
            return True
        if alpha_context.cvd_change is not None and alpha_context.cvd_change >= 0:
            return True
        return alpha_context.aggressive_delta is not None and alpha_context.aggressive_delta >= 0
    if alpha_context.delta_divergence == "bearish_divergence":
        return True
    if alpha_context.cvd_change is not None and alpha_context.cvd_change <= 0:
        return True
    return alpha_context.aggressive_delta is not None and alpha_context.aggressive_delta <= 0


def _cvd_divergence_score(
    *,
    direction: Literal["LONG", "SHORT"],
    features: Features,
    alpha_context: AlphaMarketContext | None,
    swept: bool,
) -> float:
    if alpha_context is None or not swept:
        return 0.0
    if direction == "LONG":
        made_lower_low = features.previous_low is None or features.low < features.previous_low
        if alpha_context.delta_divergence == "bullish_divergence" and made_lower_low:
            return 1.0
        if made_lower_low and alpha_context.cvd_change is not None and alpha_context.cvd_change >= 0:
            return 0.75
        if made_lower_low and alpha_context.aggressive_delta is not None and alpha_context.aggressive_delta >= 0:
            return 0.55
    else:
        made_higher_high = features.previous_high is None or features.high > features.previous_high
        if alpha_context.delta_divergence == "bearish_divergence" and made_higher_high:
            return 1.0
        if made_higher_high and alpha_context.cvd_change is not None and alpha_context.cvd_change <= 0:
            return 0.75
        if made_higher_high and alpha_context.aggressive_delta is not None and alpha_context.aggressive_delta <= 0:
            return 0.55
    return 0.0


def _oi_flush_score(
    features: Features,
    alpha_context: AlphaMarketContext | None,
    params: Mapping[str, Any],
) -> float:
    threshold = _numeric_param(params, "oi_flush_threshold", DEFAULT_OI_FLUSH_THRESHOLD)
    values = [features.oi_change]
    if alpha_context is not None:
        values.extend([alpha_context.oi_delta_5m, alpha_context.oi_delta_15m])
    flush_values = [value for value in values if value is not None and value <= threshold]
    if not flush_values:
        return 0.0
    strongest = min(flush_values)
    if threshold >= 0:
        return 1.0
    return _clamp01(abs(strongest) / abs(threshold))


def _liquidation_flush_score(
    *,
    direction: Literal["LONG", "SHORT"],
    level: float,
    features: Features,
    alpha_context: AlphaMarketContext | None,
) -> float:
    if alpha_context is None:
        return 0.0
    score = 0.0
    proximity = alpha_context.liquidation_proximity
    if proximity is not None:
        if proximity <= 0.001:
            score = max(score, 1.0)
        elif proximity <= 0.005:
            score = max(score, 0.75)
        elif proximity <= 0.01:
            score = max(score, 0.5)
    clusters = alpha_context.liquidation_clusters or []
    atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
    for cluster in clusters:
        price = _cluster_price(cluster)
        if price is None:
            continue
        if abs(price - level) <= max(atr * 0.5, abs(level) * 0.001):
            side = str(cluster.get("side") or cluster.get("direction") or "").lower()
            if not side or _liquidation_side_matches(direction, side):
                score = max(score, 0.85)
    return _clamp01(score)


def _failed_continuation_score(
    *,
    swept: bool,
    reclaimed: bool,
    confirmation: bool,
    micro_bos: bool,
    continued_breakout: bool,
) -> float:
    if continued_breakout:
        return 0.0
    if confirmation:
        return 1.0
    if swept and reclaimed and micro_bos:
        return 0.85
    if swept and reclaimed:
        return 0.65
    return 0.0


def _actionable_status_from_thresholds(
    *,
    default_reason: str,
    setup_status: str,
    alpha_context: AlphaMarketContext | None,
    obvious_liquidity_score: float,
    absorption_score: float,
    cvd_divergence_score: float,
    oi_flush_score: float,
    params: Mapping[str, Any],
) -> tuple[str, str]:
    min_obvious = _numeric_param(
        params,
        "min_obvious_liquidity_score",
        DEFAULT_MIN_OBVIOUS_LIQUIDITY_SCORE,
    )
    if obvious_liquidity_score < min_obvious:
        return (
            "watchlist",
            f"Liquidity level score {obvious_liquidity_score:.2f} is below obvious-liquidity threshold {min_obvious:.2f}",
        )

    if _bool_param(params, "alpha_context_required", False) and alpha_context is None:
        return ("ready", "Alpha context is required before this sweep can be actionable")

    min_absorption = _numeric_param(params, "min_absorption_score", DEFAULT_MIN_ABSORPTION_SCORE)
    if _bool_param(params, "require_absorption", DEFAULT_REQUIRE_ABSORPTION) and absorption_score < min_absorption:
        return (
            "ready",
            f"Absorption score {absorption_score:.2f} is below threshold {min_absorption:.2f}",
        )

    min_cvd = _numeric_param(params, "min_cvd_divergence_score", DEFAULT_MIN_CVD_DIVERGENCE_SCORE)
    if min_cvd > 0 and cvd_divergence_score < min_cvd:
        return (
            "ready",
            f"CVD divergence score {cvd_divergence_score:.2f} is below threshold {min_cvd:.2f}",
        )

    min_oi = _numeric_param(params, "min_oi_flush_score", DEFAULT_MIN_OI_FLUSH_SCORE)
    if _bool_param(params, "require_oi_flush", False):
        min_oi = max(min_oi, 0.5)
    if min_oi > 0 and oi_flush_score < min_oi:
        return (
            "ready",
            f"OI flush score {oi_flush_score:.2f} is below threshold {min_oi:.2f}",
        )

    return setup_status, default_reason


def _apply_target_room_gate(setup: SweepSetup, params: Mapping[str, Any]) -> SweepSetup:
    min_distance = _numeric_param(params, "min_target_distance_r", DEFAULT_MIN_TARGET_DISTANCE_R)
    if setup.htf_target_distance_r is None or setup.htf_target_distance_r >= min_distance:
        return setup
    if setup.status == "rejected":
        return setup
    return replace(
        setup,
        status="watchlist",
        status_reason=(
            f"Nearest market target is only {setup.htf_target_distance_r:.2f}R away; "
            f"minimum target room is {min_distance:.2f}R"
        ),
    )


def _select_sweep_targets(
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    swept_level: float,
    entry: float,
    stop_loss: float,
    alpha_context: AlphaMarketContext | None,
    support_resistance_by_timeframe: Mapping[str, SupportResistanceSnapshot],
) -> SweepTargets:
    risk = abs(entry - stop_loss)
    target_candidates = _market_target_candidates(
        features=features,
        direction=direction,
        alpha_context=alpha_context,
        support_resistance_by_timeframe=support_resistance_by_timeframe,
    )
    directional_targets = [
        target
        for target in target_candidates
        if _target_reward(direction, entry, target.price) > 0
    ]
    boundary = _best_market_target(direction, entry, directional_targets)
    boundary_price = boundary.price if boundary is not None else None
    midpoint = _range_midpoint(swept_level, boundary_price)
    if midpoint is not None and _target_reward(direction, entry, midpoint) <= 0:
        midpoint = None

    target_sources: dict[str, str] = {}
    if midpoint is not None:
        target_sources["TP1"] = "range_midpoint"
    if boundary is not None:
        target_sources["TP2"] = boundary.source

    distance_targets = []
    if midpoint is not None:
        distance_targets.append(MarketTarget(midpoint, "range_midpoint", "range midpoint after reclaim", 100))
    if boundary is not None:
        distance_targets.append(boundary)
    nearest = _nearest_market_target(direction, entry, distance_targets)
    distance_r = _target_distance_r(direction, entry, nearest.price, risk) if nearest is not None else None
    thesis = (
        "No structural market target was available; R-multiple fallback remains explicit"
        if boundary is None and midpoint is None
        else _target_thesis(midpoint=midpoint, boundary=boundary)
    )
    return SweepTargets(
        take_profit_1=midpoint,
        take_profit_2=boundary_price,
        target_sources=target_sources,
        target_thesis=thesis,
        market_target_source=nearest.source if nearest is not None else None,
        htf_target_distance_r=distance_r,
    )


def _market_target_candidates(
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    alpha_context: AlphaMarketContext | None,
    support_resistance_by_timeframe: Mapping[str, SupportResistanceSnapshot],
) -> list[MarketTarget]:
    if direction == "LONG":
        raw = (
            ("session_high", features.session_high, "session high liquidity", 90),
            ("previous_day_high", features.previous_day_high, "previous day high liquidity", 88),
            ("swing_high", features.swing_high, "opposite swing high liquidity", 84),
            ("range_high", features.donchian_high_20, "range high liquidity", 82),
            ("previous_high", features.previous_high, "previous candle high", 50),
        )
        htf_kind = "resistance"
        pool_side = "above"
    else:
        raw = (
            ("session_low", features.session_low, "session low liquidity", 90),
            ("previous_day_low", features.previous_day_low, "previous day low liquidity", 88),
            ("swing_low", features.swing_low, "opposite swing low liquidity", 84),
            ("range_low", features.donchian_low_20, "range low liquidity", 82),
            ("previous_low", features.previous_low, "previous candle low", 50),
        )
        htf_kind = "support"
        pool_side = "below"

    targets = [
        MarketTarget(price=price, source=source, thesis=thesis, priority=priority)
        for source, price, thesis, priority in raw
        if price is not None and price > 0
    ]

    if alpha_context is not None:
        for pool in alpha_context.session_liquidity_pools:
            if pool.side != pool_side:
                continue
            targets.append(
                MarketTarget(
                    price=pool.price,
                    source=f"liquidity_pool_{pool.source}_{pool.name}",
                    thesis=f"{pool.source} liquidity pool target",
                    priority=84,
                )
            )

    for timeframe, snapshot in support_resistance_by_timeframe.items():
        for level in snapshot.levels:
            if level.kind != htf_kind:
                continue
            targets.append(
                MarketTarget(
                    price=level.price,
                    source=f"htf_{timeframe}_{level.kind}",
                    thesis=f"{timeframe} {level.kind} level",
                    priority=86 if level.strength >= 50 else 72,
                )
            )
    return _dedupe_targets(targets)


def _best_market_target(
    direction: Literal["LONG", "SHORT"],
    entry: float,
    targets: list[MarketTarget],
) -> MarketTarget | None:
    if not targets:
        return None
    return max(
        targets,
        key=lambda target: (
            target.priority,
            -_target_reward(direction, entry, target.price),
        ),
    )


def _nearest_market_target(
    direction: Literal["LONG", "SHORT"],
    entry: float,
    targets: list[MarketTarget],
) -> MarketTarget | None:
    if not targets:
        return None
    return min(targets, key=lambda target: _target_reward(direction, entry, target.price))


def _dedupe_targets(targets: list[MarketTarget]) -> list[MarketTarget]:
    best_by_price: dict[int, MarketTarget] = {}
    for target in targets:
        key = round(target.price * 100_000_000)
        existing = best_by_price.get(key)
        if existing is None or target.priority > existing.priority:
            best_by_price[key] = target
    return list(best_by_price.values())


def _target_thesis(*, midpoint: float | None, boundary: MarketTarget | None) -> str:
    parts: list[str] = []
    if midpoint is not None:
        parts.append("TP1 is the reclaimed range midpoint")
    if boundary is not None:
        parts.append(f"TP2 targets {boundary.thesis}")
    return "; ".join(parts) if parts else "Market target unavailable"


def _target_distance_r(
    direction: Literal["LONG", "SHORT"],
    entry: float,
    target: float,
    risk: float,
) -> float | None:
    if risk <= 0:
        return None
    synthetic_stop = entry - risk if direction == "LONG" else entry + risk
    return risk_reward_plan_service.calculate_rr(
        entry,
        synthetic_stop,
        target,
        direction,
    ).rr_value


def _cluster_price(cluster: Mapping[str, Any]) -> float | None:
    for key in ("price", "level", "min_price", "max_price"):
        value = cluster.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _liquidation_side_matches(direction: Literal["LONG", "SHORT"], side: str) -> bool:
    if direction == "LONG":
        return side in {"long", "sell", "bid", "below"}
    return side in {"short", "buy", "ask", "above"}


def _alpha_context_param(params: Mapping[str, Any]) -> AlphaMarketContext | None:
    value = params.get("alpha_context")
    return value if isinstance(value, AlphaMarketContext) else None


def _support_resistance_by_timeframe_param(
    params: Mapping[str, Any],
) -> Mapping[str, SupportResistanceSnapshot]:
    value = params.get("support_resistance_by_timeframe")
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, SupportResistanceSnapshot] = {}
    for key, snapshot in value.items():
        if isinstance(key, str) and isinstance(snapshot, SupportResistanceSnapshot):
            result[key] = snapshot
    return result


def _missing_alpha_sources(alpha_context: AlphaMarketContext | None) -> tuple[str, ...]:
    if alpha_context is None:
        return DEFAULT_ALPHA_MISSING_SOURCES
    data_quality = alpha_context.data_quality or {}
    raw_missing = data_quality.get("missing_sources")
    missing = [str(item) for item in raw_missing] if isinstance(raw_missing, list) else []
    if alpha_context.delta_divergence is None and alpha_context.cvd_change is None and alpha_context.aggressive_delta is None:
        missing.append("delta_cvd")
    if alpha_context.orderbook_imbalance is None and alpha_context.depth_wall_side in {None, "none"}:
        missing.append("orderbook_l2")
    if alpha_context.oi_delta_5m is None and alpha_context.oi_delta_15m is None:
        missing.append("derivative_history")
    if alpha_context.liquidation_proximity is None and not alpha_context.liquidation_clusters:
        missing.append("liquidation_data")
    return tuple(dict.fromkeys(missing))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _candidate_priority(setup: SweepSetup) -> tuple[int, float, bool, int]:
    status_rank = {"actionable": 4, "ready": 3, "watchlist": 2, "rejected": 1}.get(setup.status, 0)
    return status_rank, setup.wick_ratio, setup.reclaimed, setup.touch_count


def _directional_close_position(direction: Literal["LONG", "SHORT"], features: Features) -> float:
    candle_range = max(features.high - features.low, 0.0)
    if candle_range <= 0:
        return 0.0
    if direction == "LONG":
        return max(0.0, min(1.0, (features.close - features.low) / candle_range))
    return max(0.0, min(1.0, (features.high - features.close) / candle_range))


def _strong_trend_against(direction: Literal["LONG", "SHORT"], features: Features) -> bool:
    if features.adx is None or features.adx <= 30:
        return False
    if features.ema_50 is None or features.ema_200 is None:
        return False
    if direction == "LONG":
        return features.close < features.ema_200 and features.ema_50 <= features.ema_200
    return features.close > features.ema_200 and features.ema_50 >= features.ema_200


def _range_midpoint(low: float | None, high: float | None) -> float | None:
    if low is None or high is None:
        return None
    return (low + high) / 2


def _target_range(
    features: Features,
    direction: Literal["LONG", "SHORT"],
    swept_level: float,
) -> tuple[float | None, float | None, str]:
    if direction == "LONG":
        boundary = _first_directional_level(
            direction,
            features.close,
            (
                ("session_high", _feature_level(features, "session_high")),
                ("previous_day_high", _feature_level(features, "previous_day_high")),
                ("swing_high", features.swing_high),
                ("donchian_high_20", features.donchian_high_20),
                ("previous_high", features.previous_high),
            ),
        )
        return swept_level, boundary[1], boundary[0]
    boundary = _first_directional_level(
        direction,
        features.close,
        (
            ("session_low", _feature_level(features, "session_low")),
            ("previous_day_low", _feature_level(features, "previous_day_low")),
            ("swing_low", features.swing_low),
            ("donchian_low_20", features.donchian_low_20),
            ("previous_low", features.previous_low),
        ),
    )
    return boundary[1], swept_level, boundary[0]


def _first_directional_level(
    direction: Literal["LONG", "SHORT"],
    entry: float,
    candidates: tuple[tuple[str, float | None], ...],
) -> tuple[str, float | None]:
    valid = [
        (source, price)
        for source, price in candidates
        if price is not None and _target_reward(direction, entry, price) > 0
    ]
    if not valid:
        return "opposite_range_boundary", None
    return valid[0]


def _feature_level(features: Features, name: str) -> float | None:
    value = getattr(features, name, None)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _target_reward(direction: Literal["LONG", "SHORT"], entry: float, target: float) -> float:
    if direction == "LONG":
        return target - entry
    return entry - target


def _bool_param(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _numeric_param(params: Mapping[str, Any], key: str, default: float) -> float:
    value = params.get(key)
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
