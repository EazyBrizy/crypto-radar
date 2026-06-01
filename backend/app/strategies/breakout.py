from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Mapping, Optional

from app.schemas.market import Features
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
        breakout_closed = not wick_returned_inside
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

        if wick_returned_inside:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "ready"
            reason = f"{action} only wicked outside the range and closed back inside; wait for a real candle close"
        elif large_candle and require_retest_after_large_candle:
            action = "Breakout" if direction == "LONG" else "Breakdown"
            status = "wait_for_pullback"
            reason = (
                f"{action} candle body is {body_atr:.2f} ATR, above configured large-candle limit "
                f"{large_candle_threshold:.2f} ATR; wait for conservative retest entry"
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
    ) -> _SqueezeState:
        side_text = "upper" if direction == "LONG" else "lower"
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
        entry_metadata.update(
            {
                "entry_model": setup.entry_model,
                "entry_type": setup.entry_model,
                "range_high": setup.range_high,
                "range_low": setup.range_low,
                "large_candle": setup.large_candle,
                "body_atr": setup.body_atr,
            }
        )
        entry = trade_plan.entry.model_copy(
            update={
                "source": setup.entry_model,
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
                        },
                    )
                )
        enriched_plan = trade_plan.model_copy(
            update={
                "entry": entry,
                "targets": targets,
                "metadata": {
                    **trade_plan.metadata,
                    "entry_model": setup.entry_model,
                    "measured_move_target_enabled": measured_move_enabled,
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
