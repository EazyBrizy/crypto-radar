from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Mapping, Optional

from app.schemas.market import Features
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
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

        scoring, reasons, risks = self._score(features, setup, params)

        atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
        stop_atr = _numeric_param(params, "sweep_stop_atr", DEFAULT_SWEEP_STOP_ATR)
        entry = features.close
        if setup.direction == "LONG":
            stop_loss = setup.sweep_extreme - atr * stop_atr
            range_low, range_high, boundary_source = _target_range(features, setup.direction, setup.level)
            take_profit_1 = _range_midpoint(range_low, range_high)
            take_profit_2 = range_high
        else:
            stop_loss = setup.sweep_extreme + atr * stop_atr
            range_low, range_high, boundary_source = _target_range(features, setup.direction, setup.level)
            take_profit_1 = _range_midpoint(range_low, range_high)
            take_profit_2 = range_low
        target_sources = {"TP1": "range_midpoint", "TP2": boundary_source}

        reasons.append(f"Swept liquidity level: {setup.level:.8f}")
        if take_profit_1 is not None and take_profit_2 is not None:
            reasons.append(
                f"Range targets: midpoint {take_profit_1:.8f}, opposite boundary {take_profit_2:.8f}"
            )
        if setup.touch_count >= DEFAULT_MIN_LEVEL_RETESTS:
            reasons.append(f"Level has {setup.touch_count} recent touches")
        if setup.confirmation:
            reasons.append("Conservative confirmation candle closed through micro structure")
        elif setup.micro_bos:
            reasons.append("Sweep candle also broke micro structure toward reversal")

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
        signal = self._enrich_trade_plan(signal, setup, target_sources)
        if signal.score < MIN_VISIBLE_SETUP_SCORE:
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

        if direction == "LONG":
            level = features.swing_low
            if level is None:
                return None
            swept = features.low < level
            reclaimed = features.close > level
            wick_ratio = features.lower_wick_ratio or 0.0
            close_position = _directional_close_position(direction, features)
            touch_count = features.swing_low_touch_count
            level_volume_score = features.swing_low_volume_score
            sweep_extreme = features.low
            previous_swept = features.previous_low is not None and features.previous_low < level
            previous_reclaimed = features.previous_close is not None and features.previous_close > level
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
                and features.close < level
                and features.low < features.previous_low
            )
            near_level = 0 <= features.close - level <= atr * watchlist_distance_atr
            level_name = "swing_low"
        else:
            level = features.swing_high
            if level is None:
                return None
            swept = features.high > level
            reclaimed = features.close < level
            wick_ratio = features.upper_wick_ratio or 0.0
            close_position = _directional_close_position(direction, features)
            touch_count = features.swing_high_touch_count
            level_volume_score = features.swing_high_volume_score
            sweep_extreme = features.high
            previous_swept = features.previous_high is not None and features.previous_high > level
            previous_reclaimed = features.previous_close is not None and features.previous_close < level
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
                and features.close > level
                and features.high > features.previous_high
            )
            near_level = 0 <= level - features.close <= atr * watchlist_distance_atr
            level_name = "swing_high"

        if continued_breakout:
            return SweepSetup(
                direction=direction,
                status="ready",
                status_reason="Sweep candidate is weak because the next candle continued the breakout",
                level=level,
                level_name=level_name,
                swept=swept,
                reclaimed=False,
                wick_ratio=wick_ratio,
                close_position=close_position,
                volume_ok=features.volume_spike >= volume_multiplier,
                strong_wick=wick_ratio >= min_wick_ratio,
                confirmation=False,
                micro_bos=micro_bos,
                close_settled_beyond_level=True,
                continued_breakout=True,
                strong_trend_against=_strong_trend_against(direction, features),
                touch_count=touch_count,
                level_volume_score=level_volume_score,
                sweep_extreme=sweep_extreme,
                require_reclaim=require_reclaim,
            )

        volume_ok = features.volume_spike >= volume_multiplier
        strong_wick = wick_ratio >= min_wick_ratio
        strong_close = close_position >= aggressive_close_position
        strong_trend_against = _strong_trend_against(direction, features)
        absorption_or_flush = (
            confirmation
            or (swept and reclaimed and strong_wick and volume_ok and strong_close)
            or (micro_bos and strong_wick and volume_ok)
        )
        if (
            strong_trend_against
            and _bool_param(params, "require_absorption", True)
            and not absorption_or_flush
        ):
            return None

        if confirmation:
            return SweepSetup(
                direction=direction,
                status="actionable",
                status_reason="Confirmation candle reclaimed micro structure after the liquidity sweep",
                level=level,
                level_name=level_name,
                swept=True,
                reclaimed=True,
                wick_ratio=wick_ratio,
                close_position=close_position,
                volume_ok=True,
                strong_wick=strong_wick,
                confirmation=True,
                micro_bos=True,
                close_settled_beyond_level=False,
                continued_breakout=False,
                strong_trend_against=strong_trend_against,
                touch_count=touch_count,
                level_volume_score=level_volume_score,
                sweep_extreme=features.previous_low if direction == "LONG" and features.previous_low is not None else features.previous_high if direction == "SHORT" and features.previous_high is not None else sweep_extreme,
                require_reclaim=require_reclaim,
            )

        if swept and reclaimed:
            actionable = strong_wick and volume_ok and strong_close
            return SweepSetup(
                direction=direction,
                status="actionable" if actionable else "ready",
                status_reason=(
                    "Swept level was reclaimed with a strong wick, close and volume"
                    if actionable
                    else "Swept level was reclaimed; waiting for stronger wick, volume or confirmation candle"
                ),
                level=level,
                level_name=level_name,
                swept=True,
                reclaimed=True,
                wick_ratio=wick_ratio,
                close_position=close_position,
                volume_ok=volume_ok,
                strong_wick=strong_wick,
                confirmation=False,
                micro_bos=micro_bos,
                close_settled_beyond_level=False,
                continued_breakout=False,
                strong_trend_against=strong_trend_against,
                touch_count=touch_count,
                level_volume_score=level_volume_score,
                sweep_extreme=sweep_extreme,
                require_reclaim=require_reclaim,
            )

        if swept:
            return SweepSetup(
                direction=direction,
                status="ready",
                status_reason=(
                    "Previous swing low was swept; waiting for reclaim above the level"
                    if direction == "LONG" and require_reclaim
                    else "Previous swing high was swept; waiting for rejection below the level"
                    if direction == "SHORT" and require_reclaim
                    else "Liquidity was swept; reclaim is optional by config, but reversal confirmation is still incomplete"
                ),
                level=level,
                level_name=level_name,
                swept=True,
                reclaimed=False,
                wick_ratio=wick_ratio,
                close_position=close_position,
                volume_ok=volume_ok,
                strong_wick=strong_wick,
                confirmation=False,
                micro_bos=micro_bos,
                close_settled_beyond_level=True,
                continued_breakout=False,
                strong_trend_against=strong_trend_against,
                touch_count=touch_count,
                level_volume_score=level_volume_score,
                sweep_extreme=sweep_extreme,
                require_reclaim=require_reclaim,
            )

        if near_level:
            return SweepSetup(
                direction=direction,
                status="watchlist",
                status_reason=(
                    "Price is testing previous swing low; waiting for liquidity sweep and reclaim"
                    if direction == "LONG"
                    else "Price is testing previous swing high; waiting for liquidity sweep and rejection"
                ),
                level=level,
                level_name=level_name,
                swept=False,
                reclaimed=False,
                wick_ratio=wick_ratio,
                close_position=close_position,
                volume_ok=volume_ok,
                strong_wick=strong_wick,
                confirmation=False,
                micro_bos=False,
                close_settled_beyond_level=False,
                continued_breakout=False,
                strong_trend_against=strong_trend_against,
                touch_count=touch_count,
                level_volume_score=level_volume_score,
                sweep_extreme=sweep_extreme,
                require_reclaim=require_reclaim,
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

        liquidity_score += 20
        reasons.append(f"Level quality: {setup.level_name} from 20-50 candle structure")

        if setup.touch_count >= min_level_retests:
            liquidity_score += 10
            reasons.append("Level has equal-high/low style retests")

        if setup.level_volume_score is not None and setup.level_volume_score >= 1.2:
            liquidity_score += 5
            reasons.append(f"Volume accumulated near level: {setup.level_volume_score:.2f}x average")

        if setup.swept and setup.reclaimed:
            liquidity_score += 20
            reasons.append("Price swept liquidity and closed back inside the range")
        elif setup.swept:
            liquidity_score += 20
            reasons.append("Price swept visible liquidity")
            risks.append("Sweep has not reclaimed the level yet")
        else:
            liquidity_score += 15
            reasons.append("Price is close to visible liquidity")

        if setup.swept and setup.reclaimed and features.oi_change is not None:
            oi_flush_threshold = _numeric_param(params, "oi_flush_threshold", DEFAULT_OI_FLUSH_THRESHOLD)
            if features.oi_change <= oi_flush_threshold:
                oi_bonus = int(_numeric_param(params, "oi_flush_bonus", DEFAULT_OI_FLUSH_BONUS))
                orderbook_score += oi_bonus
                reasons.append(f"Open interest flushed during reclaim: {features.oi_change:.2%}")

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
        target_sources: Mapping[str, str],
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
            }
        )
        entry = trade_plan.entry.model_copy(
            update={
                "source": "liquidity_reclaim" if setup.reclaimed else "liquidity_sweep_watch",
                "metadata": entry_metadata,
            }
        )
        targets = [
            target.model_copy(
                update={
                    "source": target_sources.get(target.label, target.source),
                    "metadata": {
                        **target.metadata,
                        "target_model": "range_midpoint_opposite_boundary",
                        "swept_level": setup.level,
                    },
                }
            )
            for target in trade_plan.targets
        ]
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
                },
            }
        ) if trade_plan.invalidation is not None else None
        enriched_plan = trade_plan.model_copy(
            update={
                "entry": entry,
                "targets": targets,
                "invalidation": invalidation,
                "metadata": {
                    **trade_plan.metadata,
                    "target_model": "range_midpoint_opposite_boundary",
                    "strong_trend_against": setup.strong_trend_against,
                },
            },
            deep=True,
        )
        return signal.model_copy(update={"trade_plan": enriched_plan})


def _candidate_priority(setup: SweepSetup) -> tuple[int, float, bool, int]:
    status_rank = {"actionable": 3, "ready": 2, "watchlist": 1}.get(setup.status, 0)
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
