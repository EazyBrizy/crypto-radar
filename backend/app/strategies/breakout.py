from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Mapping, Optional

from app.schemas.market import AlphaMarketContext, Features
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.schemas.trade_plan import TradePlanTarget
from app.strategies.common import build_signal, has_minimum_market_data, score_breakdown

STRATEGY_NAME = "volatility_squeeze_breakout"
MIN_VISIBLE_SETUP_SCORE = 45

DEFAULT_MIN_HISTORY = 60
DEFAULT_BB_WIDTH_PERCENTILE_THRESHOLD = 20.0
DEFAULT_VOLUME_SPIKE_MULTIPLIER = 1.5
DEFAULT_MIN_CLOSE_POSITION = 0.7
DEFAULT_MAX_REJECTION_WICK_RATIO = 0.35
DEFAULT_MAX_SQUEEZE_RANGE_ATR = 5.0
DEFAULT_WATCHLIST_DISTANCE_ATR = 0.6
DEFAULT_STOP_ATR_MULTIPLIER = 1.0
DEFAULT_NARROW_RANGE_STOP_ATR_MULTIPLIER = 0.5
NARROW_RANGE_ATR = 2.0
MAX_BREAKOUT_BODY_ATR = 2.5
DEFAULT_ALLOW_AGGRESSIVE_ENTRY = True
DEFAULT_REQUIRE_RETEST_AFTER_LARGE_CANDLE = True
DEFAULT_MEASURED_MOVE_TARGET_ENABLED = True
DEFAULT_OI_EXPANSION_THRESHOLD = 0.01
DEFAULT_OI_EXPANSION_BONUS = 5
DEFAULT_OI_NO_EXPANSION_PENALTY = 10
DEFAULT_REQUIRE_DELTA_EXPANSION = False
DEFAULT_REQUIRE_OI_EXPANSION = False
DEFAULT_MIN_DELTA_EXPANSION_SCORE = 0.45
DEFAULT_MIN_OI_EXPANSION_SCORE = 0.45
DEFAULT_ACCEPTED_BREAKOUT_MIN_SCORE = 0.55
DEFAULT_FAKEOUT_RISK_MAX_SCORE = 0.55
DEFAULT_FUNDING_PRESSURE_THRESHOLD = 1.0


@dataclass(frozen=True)
class _SqueezeState:
    direction: Literal["LONG", "SHORT"]
    status: str
    reason: str
    range_high: float
    range_low: float
    range_size: float
    range_size_atr: float
    bb_squeeze: bool
    atr_compressed: bool
    range_contracting: bool
    breakout_closed: bool
    wick_returned_inside: bool
    volume_confirmed: bool
    strong_close: bool
    atr_expanding: bool
    close_position: float
    rejection_wick_ratio: float
    entry_model: Literal["aggressive_breakout", "conservative_retest"]
    large_candle: bool
    body_atr: float
    measured_move_target: float | None
    accepted_breakout_score: float
    fakeout_risk_score: float
    post_breakout_hold_score: float
    retest_quality_score: float
    delta_expansion_score: float
    oi_expansion_score: float
    volume_acceptance_score: float
    failed_breakout_invalidation: bool
    retest_required: bool
    alpha_context_used: bool
    missing_alpha_sources: list[str]


class VolatilitySqueezeBreakoutStrategy:
    name = STRATEGY_NAME
    version = "1.0"
    required_data = [
        "bb_width_percentile",
        "atr_sma_50",
        "range_20",
        "range_50_average",
        "donchian_high_20",
        "donchian_low_20",
        "volume_spike",
        "atr_14",
        "rsi_14",
    ]

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> List[StrategySignal]:
        strategy_params = params or {}
        min_history = int(_numeric_param(strategy_params, "min_history", DEFAULT_MIN_HISTORY))
        if not has_minimum_market_data(features, min_history=min_history):
            return []

        setup = self._setup_state(features, strategy_params)
        if setup is None:
            return []

        scoring, reasons, risks = self._score(features, setup, strategy_params)
        atr = self._atr(features)
        stop_multiplier = _numeric_param(
            strategy_params,
            "narrow_range_stop_atr",
            DEFAULT_NARROW_RANGE_STOP_ATR_MULTIPLIER,
        ) if setup.range_size_atr <= NARROW_RANGE_ATR else _numeric_param(
            strategy_params,
            "breakout_stop_atr",
            DEFAULT_STOP_ATR_MULTIPLIER,
        )
        breakout_level = setup.range_high if setup.direction == "LONG" else setup.range_low
        if setup.direction == "LONG":
            stop_loss = breakout_level - atr * stop_multiplier
        else:
            stop_loss = breakout_level + atr * stop_multiplier

        entry = features.close if setup.entry_model == "aggressive_breakout" else breakout_level
        risk = abs(entry - stop_loss)
        if risk <= 0:
            risk = max(atr, abs(entry) * 0.001, 1e-8)
        if setup.direction == "LONG":
            take_profit_1 = entry + risk * 1.5
            take_profit_2 = entry + risk * 2.5
            measured_target = setup.range_high + setup.range_size
        else:
            take_profit_1 = entry - risk * 1.5
            take_profit_2 = entry - risk * 2.5
            measured_target = setup.range_low - setup.range_size
        measured_move_enabled = _bool_param(
            strategy_params,
            "measured_move_target_enabled",
            DEFAULT_MEASURED_MOVE_TARGET_ENABLED,
        )
        if measured_move_enabled:
            reasons.append(f"Measured move target: {measured_target:.8f}")

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
        if setup.status == "actionable" and setup.entry_model == "aggressive_breakout":
            signal = signal.model_copy(update={"entry_min": entry, "entry_max": entry})
        signal = self._enrich_trade_plan(
            signal=signal,
            setup=setup,
            measured_move_enabled=measured_move_enabled,
        )
        if signal.score < MIN_VISIBLE_SETUP_SCORE:
            return []
        return [signal.model_copy(update={"status": setup.status, "status_reason": setup.reason})]

    def _direction(self, features: Features) -> Optional[Literal["LONG", "SHORT"]]:
        setup = self._setup_state(features, {})
        return setup.direction if setup is not None else None

    def _setup_state(
        self,
        features: Features,
        params: Mapping[str, Any],
    ) -> _SqueezeState | None:
        range_high = features.donchian_high_20
        range_low = features.donchian_low_20
        if range_high is None or range_low is None or range_high <= range_low:
            return None

        atr = self._atr(features)
        range_size = range_high - range_low
        range_size_atr = range_size / atr if atr > 0 else 0.0
        max_range_atr = _numeric_param(params, "max_squeeze_range_atr", DEFAULT_MAX_SQUEEZE_RANGE_ATR)
        range_tight = range_size_atr <= max_range_atr
        if not range_tight:
            return None

        bb_squeeze = self._bb_squeeze(features, params)
        atr_compressed = self._atr_compressed(features)
        range_contracting = self._range_contracting(features, fallback_range=range_size)
        if not (bb_squeeze and atr_compressed and range_contracting):
            return None

        long_closed = features.close > range_high
        short_closed = features.close < range_low
        long_wick_returned = features.high > range_high and features.close <= range_high
        short_wick_returned = features.low < range_low and features.close >= range_low
        long_failed_hold = (
            features.previous_close is not None
            and features.previous_close > range_high
            and features.close <= range_high
        )
        short_failed_hold = (
            features.previous_close is not None
            and features.previous_close < range_low
            and features.close >= range_low
        )

        if long_closed:
            return self._breakout_state(
                features=features,
                direction="LONG",
                range_high=range_high,
                range_low=range_low,
                range_size=range_size,
                range_size_atr=range_size_atr,
                bb_squeeze=bb_squeeze,
                atr_compressed=atr_compressed,
                range_contracting=range_contracting,
                wick_returned_inside=False,
                failed_breakout_invalidation=False,
                params=params,
            )
        if short_closed:
            return self._breakout_state(
                features=features,
                direction="SHORT",
                range_high=range_high,
                range_low=range_low,
                range_size=range_size,
                range_size_atr=range_size_atr,
                bb_squeeze=bb_squeeze,
                atr_compressed=atr_compressed,
                range_contracting=range_contracting,
                wick_returned_inside=False,
                failed_breakout_invalidation=False,
                params=params,
            )
        if long_failed_hold:
            return self._breakout_state(
                features=features,
                direction="LONG",
                range_high=range_high,
                range_low=range_low,
                range_size=range_size,
                range_size_atr=range_size_atr,
                bb_squeeze=bb_squeeze,
                atr_compressed=atr_compressed,
                range_contracting=range_contracting,
                wick_returned_inside=True,
                failed_breakout_invalidation=True,
                params=params,
            )
        if short_failed_hold:
            return self._breakout_state(
                features=features,
                direction="SHORT",
                range_high=range_high,
                range_low=range_low,
                range_size=range_size,
                range_size_atr=range_size_atr,
                bb_squeeze=bb_squeeze,
                atr_compressed=atr_compressed,
                range_contracting=range_contracting,
                wick_returned_inside=True,
                failed_breakout_invalidation=True,
                params=params,
            )
        if long_wick_returned:
            return self._breakout_state(
                features=features,
                direction="LONG",
                range_high=range_high,
                range_low=range_low,
                range_size=range_size,
                range_size_atr=range_size_atr,
                bb_squeeze=bb_squeeze,
                atr_compressed=atr_compressed,
                range_contracting=range_contracting,
                wick_returned_inside=True,
                failed_breakout_invalidation=False,
                params=params,
            )
        if short_wick_returned:
            return self._breakout_state(
                features=features,
                direction="SHORT",
                range_high=range_high,
                range_low=range_low,
                range_size=range_size,
                range_size_atr=range_size_atr,
                bb_squeeze=bb_squeeze,
                atr_compressed=atr_compressed,
                range_contracting=range_contracting,
                wick_returned_inside=True,
                failed_breakout_invalidation=False,
                params=params,
            )

        watchlist_distance_atr = _numeric_param(
            params,
            "watchlist_distance_atr",
            DEFAULT_WATCHLIST_DISTANCE_ATR,
        )
        if 0 <= range_high - features.close <= atr * watchlist_distance_atr:
            return self._watchlist_state(
                features=features,
                direction="LONG",
                range_high=range_high,
                range_low=range_low,
                range_size=range_size,
                range_size_atr=range_size_atr,
                bb_squeeze=bb_squeeze,
                atr_compressed=atr_compressed,
                range_contracting=range_contracting,
                params=params,
            )
        if 0 <= features.close - range_low <= atr * watchlist_distance_atr:
            return self._watchlist_state(
                features=features,
                direction="SHORT",
                range_high=range_high,
                range_low=range_low,
                range_size=range_size,
                range_size_atr=range_size_atr,
                bb_squeeze=bb_squeeze,
                atr_compressed=atr_compressed,
                range_contracting=range_contracting,
                params=params,
            )
        return None

    def _breakout_state(
        self,
        *,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        range_high: float,
        range_low: float,
        range_size: float,
        range_size_atr: float,
        bb_squeeze: bool,
        atr_compressed: bool,
        range_contracting: bool,
        wick_returned_inside: bool,
        failed_breakout_invalidation: bool,
        params: Mapping[str, Any],
    ) -> _SqueezeState:
        volume_threshold = _numeric_param(params, "volume_spike_multiplier", DEFAULT_VOLUME_SPIKE_MULTIPLIER)
        min_close_position = _numeric_param(params, "min_close_position", DEFAULT_MIN_CLOSE_POSITION)
        max_rejection_wick = _numeric_param(
            params,
            "max_breakout_wick_ratio",
            DEFAULT_MAX_REJECTION_WICK_RATIO,
        )
        close_position = _directional_close_position(direction, features)
        rejection_wick = _rejection_wick_ratio(direction, features)
        volume_confirmed = features.volume_spike >= volume_threshold
        strong_close = close_position >= min_close_position
        wick_ok = rejection_wick <= max_rejection_wick
        breakout_closed = not wick_returned_inside and not failed_breakout_invalidation
        atr_expanding = features.atr_increasing
        body_atr = _body_atr(features)
        large_candle_threshold = _numeric_param(
            params,
            "large_candle_body_atr",
            _numeric_param(params, "max_body_atr", MAX_BREAKOUT_BODY_ATR),
        )
        large_candle = body_atr > large_candle_threshold
        require_retest_after_large_candle = _bool_param(
            params,
            "require_retest_after_large_candle",
            DEFAULT_REQUIRE_RETEST_AFTER_LARGE_CANDLE,
        )
        allow_aggressive_entry = _bool_param(params, "allow_aggressive_entry", DEFAULT_ALLOW_AGGRESSIVE_ENTRY)
        entry_model: Literal["aggressive_breakout", "conservative_retest"] = "conservative_retest"
        measured_target = range_high + range_size if direction == "LONG" else range_low - range_size
        alpha_context = _alpha_context_from_params(params)
        missing_alpha_sources = _missing_alpha_sources(alpha_context)
        breakout_level = range_high if direction == "LONG" else range_low
        post_breakout_hold_score = _post_breakout_hold_score(direction, features, breakout_level)
        retest_quality_score = _retest_quality_score(direction, features, breakout_level)
        delta_expansion_score = _delta_expansion_score(direction, alpha_context)
        oi_expansion_score = _oi_expansion_score(features, alpha_context, params)
        volume_acceptance_score = _volume_acceptance_score(direction, features, alpha_context, volume_threshold)
        accepted_breakout_score = _accepted_breakout_score(
            breakout_closed=breakout_closed,
            close_position=close_position,
            body_quality_score=_body_quality_score(direction, features, close_position, rejection_wick),
            volume_acceptance_score=volume_acceptance_score,
            atr_expansion_score=1.0 if atr_expanding else 0.0,
            delta_expansion_score=delta_expansion_score,
            oi_expansion_score=oi_expansion_score,
            post_breakout_hold_score=post_breakout_hold_score,
            retest_quality_score=retest_quality_score,
        )
        fakeout_risk_score = _fakeout_risk_score(
            direction=direction,
            features=features,
            alpha_context=alpha_context,
            wick_returned_inside=wick_returned_inside,
            failed_breakout_invalidation=failed_breakout_invalidation,
            large_candle=large_candle,
            post_breakout_hold_score=post_breakout_hold_score,
            delta_expansion_score=delta_expansion_score,
            oi_expansion_score=oi_expansion_score,
            volume_acceptance_score=volume_acceptance_score,
            params=params,
        )
        accepted_min_score = _numeric_param(
            params,
            "accepted_breakout_min_score",
            DEFAULT_ACCEPTED_BREAKOUT_MIN_SCORE,
        )
        fakeout_max_score = _numeric_param(
            params,
            "fakeout_risk_max_score",
            DEFAULT_FAKEOUT_RISK_MAX_SCORE,
        )
        require_delta_expansion = _bool_param(
            params,
            "require_delta_expansion",
            DEFAULT_REQUIRE_DELTA_EXPANSION,
        )
        require_oi_expansion = _bool_param(
            params,
            "require_oi_expansion",
            DEFAULT_REQUIRE_OI_EXPANSION,
        )
        min_delta_expansion_score = _numeric_param(
            params,
            "min_delta_expansion_score",
            DEFAULT_MIN_DELTA_EXPANSION_SCORE,
        )
        min_oi_expansion_score = _numeric_param(
            params,
            "min_oi_expansion_score",
            DEFAULT_MIN_OI_EXPANSION_SCORE,
        )
        retest_required = (
            (large_candle and require_retest_after_large_candle)
            or fakeout_risk_score > fakeout_max_score
        )

        if failed_breakout_invalidation:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "ready"
            reason = (
                f"{action} failed to hold the broken level on the next evaluation; "
                f"fakeout risk {fakeout_risk_score:.2f} requires fresh acceptance or retest"
            )
        elif wick_returned_inside:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "ready"
            reason = (
                f"{action} only wicked outside the range and closed back inside; "
                f"fakeout risk {fakeout_risk_score:.2f} requires a real candle close"
            )
        elif large_candle and require_retest_after_large_candle:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "wait_for_pullback"
            reason = (
                f"{action} candle body is {body_atr:.2f} ATR, above configured large-candle limit "
                f"{large_candle_threshold:.2f} ATR; wait for conservative retest entry"
            )
        elif fakeout_risk_score > fakeout_max_score:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "wait_for_pullback"
            reason = (
                f"{action} fakeout risk is {fakeout_risk_score:.2f}, above configured max "
                f"{fakeout_max_score:.2f}; wait for conservative retest acceptance"
            )
        elif accepted_breakout_score < accepted_min_score:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "ready"
            reason = (
                f"{action} acceptance score is {accepted_breakout_score:.2f}, below configured minimum "
                f"{accepted_min_score:.2f}; wait for stronger acceptance"
            )
        elif require_delta_expansion and delta_expansion_score < min_delta_expansion_score:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "ready"
            reason = (
                f"{action} lacks required delta expansion: {delta_expansion_score:.2f} "
                f"vs {min_delta_expansion_score:.2f}"
            )
        elif require_oi_expansion and oi_expansion_score < min_oi_expansion_score:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "ready"
            reason = (
                f"{action} lacks required open-interest expansion: {oi_expansion_score:.2f} "
                f"vs {min_oi_expansion_score:.2f}"
            )
        elif volume_confirmed and strong_close and atr_expanding and wick_ok:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            if allow_aggressive_entry:
                status = "actionable"
                entry_model = "aggressive_breakout"
                reason = f"{action} closed outside the compressed range with volume, strong close and ATR expansion"
            else:
                status = "ready"
                reason = f"{action} is confirmed, but strategy config requires a conservative retest entry"
        else:
            missing: list[str] = []
            if not volume_confirmed:
                missing.append("volume")
            if not strong_close:
                missing.append("close strength")
            if not atr_expanding:
                missing.append("ATR expansion")
            if not wick_ok:
                missing.append("clean wick profile")
            status = "ready"
            reason = "Breakout closed outside the range, but confirmation is incomplete: " + ", ".join(missing)

        return _SqueezeState(
            direction=direction,
            status=status,
            reason=reason,
            range_high=range_high,
            range_low=range_low,
            range_size=range_size,
            range_size_atr=range_size_atr,
            bb_squeeze=bb_squeeze,
            atr_compressed=atr_compressed,
            range_contracting=range_contracting,
            breakout_closed=breakout_closed,
            wick_returned_inside=wick_returned_inside,
            volume_confirmed=volume_confirmed,
            strong_close=strong_close,
            atr_expanding=atr_expanding,
            close_position=close_position,
            rejection_wick_ratio=rejection_wick,
            entry_model=entry_model,
            large_candle=large_candle,
            body_atr=body_atr,
            measured_move_target=measured_target,
            accepted_breakout_score=round(accepted_breakout_score, 4),
            fakeout_risk_score=round(fakeout_risk_score, 4),
            post_breakout_hold_score=round(post_breakout_hold_score, 4),
            retest_quality_score=round(retest_quality_score, 4),
            delta_expansion_score=round(delta_expansion_score, 4),
            oi_expansion_score=round(oi_expansion_score, 4),
            volume_acceptance_score=round(volume_acceptance_score, 4),
            failed_breakout_invalidation=failed_breakout_invalidation,
            retest_required=retest_required,
            alpha_context_used=alpha_context is not None,
            missing_alpha_sources=missing_alpha_sources,
        )

    def _watchlist_state(
        self,
        *,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        range_high: float,
        range_low: float,
        range_size: float,
        range_size_atr: float,
        bb_squeeze: bool,
        atr_compressed: bool,
        range_contracting: bool,
        params: Mapping[str, Any],
    ) -> _SqueezeState:
        side_text = "upper" if direction == "LONG" else "lower"
        alpha_context = _alpha_context_from_params(params)
        return _SqueezeState(
            direction=direction,
            status="watchlist",
            reason=(
                f"Volatility is compressed and price is near the {side_text} Donchian boundary; "
                "waiting for breakout volume and a candle close outside the range"
            ),
            range_high=range_high,
            range_low=range_low,
            range_size=range_size,
            range_size_atr=range_size_atr,
            bb_squeeze=bb_squeeze,
            atr_compressed=atr_compressed,
            range_contracting=range_contracting,
            breakout_closed=False,
            wick_returned_inside=False,
            volume_confirmed=False,
            strong_close=False,
            atr_expanding=features.atr_increasing,
            close_position=_directional_close_position(direction, features),
            rejection_wick_ratio=_rejection_wick_ratio(direction, features),
            entry_model="conservative_retest",
            large_candle=False,
            body_atr=_body_atr(features),
            measured_move_target=range_high + range_size if direction == "LONG" else range_low - range_size,
            accepted_breakout_score=0.0,
            fakeout_risk_score=0.0,
            post_breakout_hold_score=0.0,
            retest_quality_score=0.0,
            delta_expansion_score=0.0,
            oi_expansion_score=0.0,
            volume_acceptance_score=0.0,
            failed_breakout_invalidation=False,
            retest_required=False,
            alpha_context_used=alpha_context is not None,
            missing_alpha_sources=_missing_alpha_sources(alpha_context),
        )

    def _score(
        self,
        features: Features,
        setup: _SqueezeState,
        params: Mapping[str, Any],
    ) -> tuple[SignalScoreBreakdown, list[str], list[str]]:
        trend_score = 0
        volume_score = 0
        liquidity_score = 0
        volatility_score = 0
        overheat_penalty = 0
        reasons: list[str] = []
        risks: list[str] = []

        if setup.bb_squeeze:
            volatility_score += 20
            reasons.append(
                f"BB width percentile is compressed below {_numeric_param(params, 'bb_width_percentile_threshold', DEFAULT_BB_WIDTH_PERCENTILE_THRESHOLD):.0f}"
            )
        if setup.atr_compressed:
            volatility_score += 15
            reasons.append("ATR is below its 50-candle average")
        if setup.range_contracting:
            volatility_score += 10
            reasons.append("20-candle range is below its recent average")

        if setup.breakout_closed:
            trend_score += 20
            level_name = "range high" if setup.direction == "LONG" else "range low"
            reasons.append(f"Close finished outside the Donchian {level_name}")
        elif setup.wick_returned_inside:
            trend_score += 8
            risks.append("Price pierced the range but closed back inside")
            overheat_penalty += 20
        else:
            trend_score += 10
            reasons.append("Price is pressing the Donchian boundary before confirmation")

        if setup.volume_confirmed:
            volume_score += 15
            reasons.append(f"Breakout volume is {features.volume_spike:.2f}x average")
        elif setup.status != "watchlist":
            risks.append("Breakout volume is below the configured confirmation multiplier")

        if setup.breakout_closed and features.oi_change is not None:
            oi_expansion_threshold = _numeric_param(
                params,
                "oi_expansion_threshold",
                DEFAULT_OI_EXPANSION_THRESHOLD,
            )
            if features.oi_change >= oi_expansion_threshold:
                oi_bonus = int(_numeric_param(params, "oi_expansion_bonus", DEFAULT_OI_EXPANSION_BONUS))
                liquidity_score += oi_bonus
                reasons.append(f"Open interest expanded with breakout: {features.oi_change:.2%}")
            else:
                oi_penalty = int(
                    _numeric_param(
                        params,
                        "oi_no_expansion_penalty",
                        DEFAULT_OI_NO_EXPANSION_PENALTY,
                    )
                )
                overheat_penalty += oi_penalty
                risks.append(
                    "Breakout lacks open-interest expansion: "
                    f"{features.oi_change:.2%} vs {oi_expansion_threshold:.2%} threshold"
                )

        if setup.accepted_breakout_score > 0:
            reasons.append(f"Accepted breakout score: {setup.accepted_breakout_score:.2f}")
        if setup.fakeout_risk_score >= _numeric_param(params, "fakeout_risk_max_score", DEFAULT_FAKEOUT_RISK_MAX_SCORE):
            risks.append(f"Fakeout risk score is elevated: {setup.fakeout_risk_score:.2f}")
            overheat_penalty += 10
        if setup.retest_required:
            risks.append("Conservative retest is required before immediate entry")
        if setup.delta_expansion_score > 0:
            reasons.append(f"Delta expansion score: {setup.delta_expansion_score:.2f}")
        elif setup.breakout_closed:
            risks.append("Delta expansion is unavailable or not confirming continuation")
        if setup.oi_expansion_score > 0 and setup.breakout_closed:
            reasons.append(f"Open-interest expansion score: {setup.oi_expansion_score:.2f}")
        if setup.volume_acceptance_score > 0:
            reasons.append(f"Volume acceptance score: {setup.volume_acceptance_score:.2f}")
        if not setup.alpha_context_used:
            risks.append("AlphaMarketContext is unavailable; breakout classifier used candle/volume proxy evidence")

        if setup.strong_close:
            liquidity_score += 10
            reasons.append(f"Close is in the directional part of the candle: {setup.close_position:.0%}")
        elif setup.status != "watchlist":
            risks.append("Close is not strong enough inside the breakout candle")

        if setup.atr_expanding:
            volatility_score += 10
            reasons.append("ATR is expanding after compression")
        elif setup.status != "watchlist":
            risks.append("ATR has not started expanding yet")

        if setup.range_size_atr >= 3:
            risks.append(f"Squeeze range uses {setup.range_size_atr:.2f} ATR; wider ranges are less clean")

        body_atr = setup.body_atr
        large_candle_threshold = _numeric_param(
            params,
            "large_candle_body_atr",
            _numeric_param(params, "max_body_atr", MAX_BREAKOUT_BODY_ATR),
        )
        if setup.large_candle:
            risks.append(f"Breakout candle body is {body_atr:.2f} ATR")
            overheat_penalty += 15
            if setup.entry_model == "conservative_retest":
                risks.append(f"Configured retest required above {large_candle_threshold:.2f} ATR breakout body")

        max_rejection_wick = _numeric_param(
            params,
            "max_breakout_wick_ratio",
            DEFAULT_MAX_REJECTION_WICK_RATIO,
        )
        if setup.rejection_wick_ratio > max_rejection_wick:
            risks.append(f"Rejection wick is {setup.rejection_wick_ratio:.0%} of the candle range")
            overheat_penalty += 15

        if setup.direction == "LONG":
            if features.rsi_14 is not None and 55 <= features.rsi_14 <= 70:
                reasons.append(f"RSI {features.rsi_14:.1f} supports upside momentum without extreme heat")
            elif features.rsi_14 is not None and features.rsi_14 > 75:
                risks.append("RSI above 75: late long breakout risk")
                overheat_penalty += 10
        else:
            if features.rsi_14 is not None and 30 <= features.rsi_14 <= 45:
                reasons.append(f"RSI {features.rsi_14:.1f} supports downside momentum without extreme heat")
            elif features.rsi_14 is not None and features.rsi_14 < 25:
                risks.append("RSI below 25: late short breakdown risk")
                overheat_penalty += 10

        return (
            score_breakdown(
                trend_score=trend_score,
                volume_score=volume_score,
                liquidity_score=liquidity_score,
                volatility_score=volatility_score,
                overheat_penalty=overheat_penalty,
            ),
            reasons,
            risks,
        )

    def _enrich_trade_plan(
        self,
        *,
        signal: StrategySignal,
        setup: _SqueezeState,
        measured_move_enabled: bool,
    ) -> StrategySignal:
        trade_plan = signal.trade_plan
        if trade_plan is None:
            return signal
        entry_metadata = dict(trade_plan.entry.metadata)
        entry_source = _entry_source(setup)
        entry_metadata.update(
            {
                "entry_model": setup.entry_model,
                "entry_source": entry_source,
                "legacy_entry_model": setup.entry_model,
                "entry_type": setup.entry_model,
                "range_high": setup.range_high,
                "range_low": setup.range_low,
                "large_candle": setup.large_candle,
                "body_atr": setup.body_atr,
                "retest_required": setup.retest_required,
                "accepted_breakout_score": setup.accepted_breakout_score,
                "fakeout_risk_score": setup.fakeout_risk_score,
            }
        )
        entry = trade_plan.entry.model_copy(
            update={
                "source": entry_source,
                "metadata": entry_metadata,
            }
        )
        targets = [
            target.model_copy(
                update={
                    "source": (
                        target.source
                        if target.source not in {None, "legacy_fields"}
                        else "breakout_momentum_rr" if target.label == "TP1" else "breakout_expansion_rr"
                    ),
                    "metadata": {
                        **target.metadata,
                        "entry_model": setup.entry_model,
                        "entry_source": entry_source,
                    },
                }
            )
            for target in trade_plan.targets
        ]
        measured_target = setup.measured_move_target
        measured_reward = (
            _target_reward(setup.direction, trade_plan.entry.price or signal.entry_min or signal.entry_max or 0.0, measured_target)
            if measured_target is not None
            else 0.0
        )
        if measured_move_enabled and measured_target is not None and measured_reward > 0:
            existing_prices = {target.price for target in targets}
            if round(measured_target, 8) not in existing_prices:
                targets.append(
                    TradePlanTarget(
                        label="Measured Move",
                        price=round(measured_target, 8),
                        action="measured_move_runner",
                        close_percent="runner",
                        source="range_measured_move",
                        metadata={
                            "range_high": setup.range_high,
                            "range_low": setup.range_low,
                            "range_size": setup.range_size,
                            "entry_model": setup.entry_model,
                            "entry_source": entry_source,
                        },
                    )
                )
        classifier_metadata = {
            "accepted_breakout_score": setup.accepted_breakout_score,
            "fakeout_risk_score": setup.fakeout_risk_score,
            "post_breakout_hold_score": setup.post_breakout_hold_score,
            "retest_quality_score": setup.retest_quality_score,
            "delta_expansion_score": setup.delta_expansion_score,
            "oi_expansion_score": setup.oi_expansion_score,
            "volume_acceptance_score": setup.volume_acceptance_score,
            "failed_breakout_invalidation": setup.failed_breakout_invalidation,
            "retest_required": setup.retest_required,
            "alpha_context_used": setup.alpha_context_used,
            "missing_alpha_sources": list(setup.missing_alpha_sources),
        }
        risk_metadata = dict(trade_plan.risk_rules.metadata)
        risk_metadata.update(classifier_metadata)
        risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})
        invalidation = trade_plan.invalidation
        if invalidation is not None:
            invalidation_metadata = dict(invalidation.metadata)
            invalidation_metadata.update(classifier_metadata)
            invalidation = invalidation.model_copy(update={"metadata": invalidation_metadata})
        enriched_plan = trade_plan.model_copy(
            update={
                "entry": entry,
                "targets": targets,
                "invalidation": invalidation,
                "risk_rules": risk_rules,
                "metadata": {
                    **trade_plan.metadata,
                    "entry_model": setup.entry_model,
                    "entry_source": entry_source,
                    "measured_move_target_enabled": measured_move_enabled,
                    **classifier_metadata,
                },
            },
            deep=True,
        )
        return signal.model_copy(update={"trade_plan": enriched_plan})

    def _bb_squeeze(self, features: Features, params: Mapping[str, Any]) -> bool:
        threshold = _numeric_param(
            params,
            "bb_width_percentile_threshold",
            DEFAULT_BB_WIDTH_PERCENTILE_THRESHOLD,
        )
        return bool(features.bb_width_percentile is not None and features.bb_width_percentile < threshold)

    def _atr_compressed(self, features: Features) -> bool:
        return bool(
            features.atr_14 is not None
            and features.atr_sma_50 is not None
            and features.atr_14 < features.atr_sma_50
        )

    def _range_contracting(self, features: Features, *, fallback_range: float) -> bool:
        range_20 = features.range_20 if features.range_20 is not None else fallback_range
        return bool(features.range_50_average is not None and range_20 < features.range_50_average)

    def _atr(self, features: Features) -> float:
        return features.atr_14 or max(abs(features.close) * 0.002, 1e-8)


def _numeric_param(params: Mapping[str, Any], key: str, default: float) -> float:
    try:
        value = params.get(key)
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _bool_param(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _directional_close_position(direction: Literal["LONG", "SHORT"], features: Features) -> float:
    candle_range = max(features.high - features.low, 0.0)
    if candle_range <= 0:
        return 0.0
    if direction == "LONG":
        return max(0.0, min(1.0, (features.close - features.low) / candle_range))
    return max(0.0, min(1.0, (features.high - features.close) / candle_range))


def _rejection_wick_ratio(direction: Literal["LONG", "SHORT"], features: Features) -> float:
    if direction == "LONG":
        return features.upper_wick_ratio or 0.0
    return features.lower_wick_ratio or 0.0


def _body_atr(features: Features) -> float:
    atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
    return abs(features.close - features.open) / atr if atr > 0 else 0.0


def _target_reward(direction: Literal["LONG", "SHORT"], entry: float, target: float) -> float:
    if direction == "LONG":
        return target - entry
    return entry - target


def _entry_source(setup: _SqueezeState) -> str:
    if setup.entry_model == "aggressive_breakout":
        return "aggressive_breakout"
    if setup.retest_required:
        return "breakout_retest"
    return "conservative_breakout"


def _alpha_context_from_params(params: Mapping[str, Any]) -> AlphaMarketContext | None:
    value = params.get("alpha_context")
    return value if isinstance(value, AlphaMarketContext) else None


def _missing_alpha_sources(alpha_context: AlphaMarketContext | None) -> list[str]:
    if alpha_context is None:
        return ["alpha_context"]
    quality_missing = alpha_context.data_quality.get("missing_sources")
    missing = [str(item) for item in quality_missing] if isinstance(quality_missing, list) else []
    if alpha_context.aggressive_delta is None and alpha_context.cvd_change is None:
        missing.append("delta")
    if alpha_context.oi_delta_5m is None and alpha_context.oi_delta_15m is None:
        missing.append("open_interest")
    if alpha_context.vwap_acceptance is None and alpha_context.vwap_deviation is None:
        missing.append("vwap_acceptance")
    if alpha_context.sweep_through_book is None:
        missing.append("orderbook_sweep_acceptance")
    return list(dict.fromkeys(missing))


def _accepted_breakout_score(
    *,
    breakout_closed: bool,
    close_position: float,
    body_quality_score: float,
    volume_acceptance_score: float,
    atr_expansion_score: float,
    delta_expansion_score: float,
    oi_expansion_score: float,
    post_breakout_hold_score: float,
    retest_quality_score: float,
) -> float:
    return _clamp01(
        (1.0 if breakout_closed else 0.0) * 0.18
        + close_position * 0.12
        + body_quality_score * 0.13
        + volume_acceptance_score * 0.13
        + atr_expansion_score * 0.10
        + delta_expansion_score * 0.10
        + oi_expansion_score * 0.10
        + post_breakout_hold_score * 0.10
        + retest_quality_score * 0.04
    )


def _fakeout_risk_score(
    *,
    direction: Literal["LONG", "SHORT"],
    features: Features,
    alpha_context: AlphaMarketContext | None,
    wick_returned_inside: bool,
    failed_breakout_invalidation: bool,
    large_candle: bool,
    post_breakout_hold_score: float,
    delta_expansion_score: float,
    oi_expansion_score: float,
    volume_acceptance_score: float,
    params: Mapping[str, Any],
) -> float:
    require_delta = _bool_param(params, "require_delta_expansion", DEFAULT_REQUIRE_DELTA_EXPANSION)
    require_oi = _bool_param(params, "require_oi_expansion", DEFAULT_REQUIRE_OI_EXPANSION)
    no_delta_risk = 1.0 - delta_expansion_score if alpha_context is not None or require_delta else 0.10
    oi_available = (
        features.oi_change is not None
        or (alpha_context is not None and (alpha_context.oi_delta_5m is not None or alpha_context.oi_delta_15m is not None))
    )
    no_oi_risk = 1.0 - oi_expansion_score if oi_available or require_oi else 0.10
    large_without_hold = 1.0 if large_candle and post_breakout_hold_score < 0.65 else 0.0
    sweep_without_acceptance = (
        1.0
        if alpha_context is not None
        and alpha_context.sweep_through_book is True
        and volume_acceptance_score < 0.55
        else 0.0
    )
    crowded_pressure = _crowded_pressure_score(direction, features, alpha_context)
    return _clamp01(
        (0.55 if wick_returned_inside else 0.0)
        + (0.55 if failed_breakout_invalidation else 0.0)
        + no_delta_risk * 0.15
        + no_oi_risk * 0.12
        + (1.0 - volume_acceptance_score) * 0.18
        + large_without_hold * 0.20
        + crowded_pressure * 0.15
        + sweep_without_acceptance * 0.12
    )


def _post_breakout_hold_score(
    direction: Literal["LONG", "SHORT"],
    features: Features,
    breakout_level: float,
) -> float:
    if direction == "LONG":
        if features.close <= breakout_level:
            return 0.0
        if features.previous_close is not None and features.previous_close > breakout_level:
            return 1.0
        if features.low >= breakout_level:
            return 0.80
        if features.low <= breakout_level < features.close:
            return 0.65
        return 0.50
    if features.close >= breakout_level:
        return 0.0
    if features.previous_close is not None and features.previous_close < breakout_level:
        return 1.0
    if features.high <= breakout_level:
        return 0.80
    if features.high >= breakout_level > features.close:
        return 0.65
    return 0.50


def _retest_quality_score(
    direction: Literal["LONG", "SHORT"],
    features: Features,
    breakout_level: float,
) -> float:
    if direction == "LONG":
        if features.close <= breakout_level:
            return 0.0
        return 1.0 if features.low <= breakout_level else 0.50
    if features.close >= breakout_level:
        return 0.0
    return 1.0 if features.high >= breakout_level else 0.50


def _delta_expansion_score(
    direction: Literal["LONG", "SHORT"],
    alpha_context: AlphaMarketContext | None,
) -> float:
    if alpha_context is None:
        return 0.0
    directional_delta = _directional_value(direction, alpha_context.aggressive_delta)
    if directional_delta is None and alpha_context.cvd_change is not None:
        directional_delta = _directional_value(direction, alpha_context.cvd_change)
    if directional_delta is None or directional_delta <= 0:
        return 0.0
    total_volume = (alpha_context.buy_volume or 0.0) + (alpha_context.sell_volume or 0.0)
    if total_volume > 0:
        return _clamp01((directional_delta / total_volume) / 0.35)
    return 0.70


def _oi_expansion_score(
    features: Features,
    alpha_context: AlphaMarketContext | None,
    params: Mapping[str, Any],
) -> float:
    oi_delta = None
    if alpha_context is not None:
        oi_delta = alpha_context.oi_delta_5m if alpha_context.oi_delta_5m is not None else alpha_context.oi_delta_15m
    if oi_delta is None:
        oi_delta = features.oi_change
    if oi_delta is None or oi_delta <= 0:
        return 0.0
    threshold = max(
        _numeric_param(params, "oi_expansion_threshold", DEFAULT_OI_EXPANSION_THRESHOLD),
        1e-8,
    )
    return _clamp01(oi_delta / threshold)


def _volume_acceptance_score(
    direction: Literal["LONG", "SHORT"],
    features: Features,
    alpha_context: AlphaMarketContext | None,
    volume_threshold: float,
) -> float:
    if volume_threshold <= 1.0:
        volume_score = 1.0 if features.volume_spike >= volume_threshold else 0.0
    else:
        volume_score = _clamp01((features.volume_spike - 1.0) / (volume_threshold - 1.0))
    vwap_score = _vwap_acceptance_score(direction, features, alpha_context)
    if vwap_score is None:
        return volume_score
    return _clamp01(volume_score * 0.70 + vwap_score * 0.30)


def _vwap_acceptance_score(
    direction: Literal["LONG", "SHORT"],
    features: Features,
    alpha_context: AlphaMarketContext | None,
) -> float | None:
    acceptance = alpha_context.vwap_acceptance if alpha_context is not None else None
    if acceptance is not None:
        if direction == "LONG":
            return 1.0 if acceptance == "above_vwap" else 0.50 if acceptance == "at_vwap" else 0.0
        return 1.0 if acceptance == "below_vwap" else 0.50 if acceptance == "at_vwap" else 0.0
    if features.vwap is None or features.vwap <= 0:
        return None
    if direction == "LONG":
        return 1.0 if features.close > features.vwap else 0.50 if abs(features.close - features.vwap) / features.vwap <= 0.001 else 0.0
    return 1.0 if features.close < features.vwap else 0.50 if abs(features.close - features.vwap) / features.vwap <= 0.001 else 0.0


def _body_quality_score(
    direction: Literal["LONG", "SHORT"],
    features: Features,
    close_position: float,
    rejection_wick_ratio: float,
) -> float:
    candle_range = max(features.high - features.low, 0.0)
    body = abs(features.close - features.open)
    body_ratio = body / candle_range if candle_range > 0 else 0.0
    directional_body = (
        features.close > features.open
        if direction == "LONG"
        else features.close < features.open
    )
    direction_factor = 1.0 if directional_body else 0.35
    return _clamp01(
        direction_factor * 0.25
        + close_position * 0.45
        + body_ratio * 0.20
        + (1.0 - rejection_wick_ratio) * 0.10
    )


def _crowded_pressure_score(
    direction: Literal["LONG", "SHORT"],
    features: Features,
    alpha_context: AlphaMarketContext | None,
) -> float:
    pressure = alpha_context.funding_pressure if alpha_context is not None else None
    if pressure is not None:
        directional_pressure = pressure if direction == "LONG" else -pressure
        return _clamp01(max(directional_pressure, 0.0) / DEFAULT_FUNDING_PRESSURE_THRESHOLD)
    funding = features.funding_rate
    if funding is None:
        return 0.0
    directional_funding = funding if direction == "LONG" else -funding
    return _clamp01(max(directional_funding, 0.0) / 0.0015)


def _directional_value(direction: Literal["LONG", "SHORT"], value: float | None) -> float | None:
    if value is None:
        return None
    return value if direction == "LONG" else -value


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
