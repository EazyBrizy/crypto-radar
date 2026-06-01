from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Mapping, Optional

from app.schemas.market import Features
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.strategies.common import build_signal, has_minimum_market_data, score_breakdown

STRATEGY_NAME = "trend_pullback_continuation"
MIN_VISIBLE_SETUP_SCORE = 45
ADX_TREND_MIN = 18.0
ADX_RISING_FLOOR = 15.0
ADX_RISING_BARS_MIN = 3
PULLBACK_ZONE_ATR = 1.0
APPROACH_ZONE_ATR = 1.8
LATE_ENTRY_EMA20_ATR = 1.5
DEFAULT_ENTRY_MODEL = "zone"
DEFAULT_TIME_STOP_BARS = 8
TRIGGER_VOLUME_MULTIPLIER = 1.1
MAX_ENTRY_CANDLE_ATR = 2.5
STOP_ATR_BUFFER = 0.5
FUNDING_WARNING_THRESHOLD = 0.00075
FUNDING_BLOCK_THRESHOLD = 0.0015
DEFAULT_CROWDED_OI_CHANGE_THRESHOLD = 0.02
DEFAULT_CROWDED_OI_PENALTY = 15


@dataclass(frozen=True)
class _TrendPullbackState:
    direction: Literal["LONG", "SHORT"]
    status: str
    reason: str
    trigger: bool
    near_pullback_zone: bool
    approaching_pullback_zone: bool
    rsi_cooled: bool
    pullback_volume_contracting: bool
    structure_intact: bool
    funding_warning: bool
    funding_extreme: bool
    crowded_oi: bool
    late_entry: bool
    entry_candle_too_large: bool
    nearest_ema: float | None
    entry_model: str
    overextension_atr: float


class TrendPullbackContinuationStrategy:
    name = STRATEGY_NAME
    version = "1.0"
    required_data = [
        "ema_20",
        "ema_50",
        "ema_200",
        "rsi_14",
        "atr_14",
        "adx",
        "volume_spike",
        "previous_high",
        "previous_low",
    ]

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> List[StrategySignal]:
        strategy_params = params or {}
        if not has_minimum_market_data(features, min_history=200):
            return []

        setup = self._setup_state(features, strategy_params)
        if setup is None:
            return []

        scoring, reasons, risks = self._score(features, setup, strategy_params)
        atr = self._atr(features)
        entry = self._entry_anchor(features, setup)
        stop_loss = self._stop_loss(features, setup.direction, atr)
        take_profit_1, take_profit_2, target_sources = self._targets(
            features=features,
            direction=setup.direction,
            entry=entry,
            stop_loss=stop_loss,
            atr=atr,
        )

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
        if setup.trigger and setup.entry_model == "chase":
            signal = signal.model_copy(update={"entry_min": features.close, "entry_max": features.close})
        signal = self._enrich_trade_plan(
            signal=signal,
            setup=setup,
            target_sources=target_sources,
            params=strategy_params,
        )
        if signal.score < MIN_VISIBLE_SETUP_SCORE:
            return []
        return [
            signal.model_copy(
                update={
                    "status": setup.status,
                    "status_reason": setup.reason,
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
    ) -> _TrendPullbackState | None:
        if (
            features.ema_20 is None
            or features.ema_50 is None
            or features.ema_200 is None
            or features.rsi_14 is None
        ):
            return None

        direction = self._trend_direction(features)
        if direction is None:
            return None
        if not self._trend_strength_ok(features):
            return None
        if self._ema_stack_is_tangled(features):
            return None
        funding_extreme = self._funding_extremely_against(features, direction, params)
        if funding_extreme and features.oi_change is None:
            return None
        if self._two_sided_wicks_are_noisy(features):
            return None

        near_pullback_zone = self._near_pullback_zone(features)
        approaching_pullback_zone = self._approaching_pullback_zone(features)
        rsi_cooled = self._rsi_cooled(features, direction)
        pullback_volume_contracting = self._pullback_volume_contracting(features)
        structure_intact = self._structure_intact(features, direction)
        funding_warning = self._funding_against_warning(features, direction, params)
        crowded_oi = self._crowded_oi(features, params)
        trigger = self._trigger(features, direction)
        max_overextension_atr = _numeric_param(params, "max_overextension_atr", LATE_ENTRY_EMA20_ATR)
        late_entry = self._late_entry(features, max_overextension_atr)
        entry_candle_too_large = self._entry_candle_too_large(features, params)
        nearest_ema = self._nearest_pullback_ema(features)
        entry_model = _entry_model(params)

        if not structure_intact:
            return None

        if late_entry:
            return _TrendPullbackState(
                direction=direction,
                status="wait_for_pullback",
                reason=(
                    "Trend is confirmed, but entry is late: price is more than "
                    f"{max_overextension_atr:.2f} ATR from EMA20; wait for a fresh pullback"
                ),
                trigger=trigger,
                near_pullback_zone=near_pullback_zone,
                approaching_pullback_zone=approaching_pullback_zone,
                rsi_cooled=rsi_cooled,
                pullback_volume_contracting=pullback_volume_contracting,
                structure_intact=structure_intact,
                funding_warning=funding_warning,
                funding_extreme=funding_extreme,
                crowded_oi=crowded_oi,
                late_entry=late_entry,
                entry_candle_too_large=entry_candle_too_large,
                nearest_ema=nearest_ema,
                entry_model=entry_model,
                overextension_atr=max_overextension_atr,
            )

        if near_pullback_zone and rsi_cooled and pullback_volume_contracting and trigger:
            return _TrendPullbackState(
                direction=direction,
                status="actionable",
                reason="Pullback held the EMA20/EMA50 zone and trigger candle broke the previous candle with volume confirmation",
                trigger=True,
                near_pullback_zone=True,
                approaching_pullback_zone=True,
                rsi_cooled=True,
                pullback_volume_contracting=True,
                structure_intact=True,
                funding_warning=funding_warning,
                funding_extreme=funding_extreme,
                crowded_oi=crowded_oi,
                late_entry=False,
                entry_candle_too_large=entry_candle_too_large,
                nearest_ema=nearest_ema,
                entry_model=entry_model,
                overextension_atr=max_overextension_atr,
            )

        if near_pullback_zone:
            reason_parts = ["Price is in the EMA20/EMA50 pullback zone"]
            if not rsi_cooled:
                reason_parts.append("RSI has not cooled into the healthy pullback zone")
            if not pullback_volume_contracting:
                reason_parts.append("pullback volume is not contracting")
            if not trigger:
                reason_parts.append("waiting for previous high/low trigger and trigger volume")
            return _TrendPullbackState(
                direction=direction,
                status="ready",
                reason="; ".join(reason_parts),
                trigger=trigger,
                near_pullback_zone=True,
                approaching_pullback_zone=True,
                rsi_cooled=rsi_cooled,
                pullback_volume_contracting=pullback_volume_contracting,
                structure_intact=True,
                funding_warning=funding_warning,
                funding_extreme=funding_extreme,
                crowded_oi=crowded_oi,
                late_entry=False,
                entry_candle_too_large=entry_candle_too_large,
                nearest_ema=nearest_ema,
                entry_model=entry_model,
                overextension_atr=max_overextension_atr,
            )

        if approaching_pullback_zone:
            return _TrendPullbackState(
                direction=direction,
                status="watchlist",
                reason="Trend is intact and price is approaching the EMA20/EMA50 pullback zone",
                trigger=trigger,
                near_pullback_zone=False,
                approaching_pullback_zone=True,
                rsi_cooled=rsi_cooled,
                pullback_volume_contracting=pullback_volume_contracting,
                structure_intact=True,
                funding_warning=funding_warning,
                funding_extreme=funding_extreme,
                crowded_oi=crowded_oi,
                late_entry=False,
                entry_candle_too_large=entry_candle_too_large,
                nearest_ema=nearest_ema,
                entry_model=entry_model,
                overextension_atr=max_overextension_atr,
            )

        return _TrendPullbackState(
            direction=direction,
            status="wait_for_pullback",
            reason="Trend is confirmed, but there is no healthy pullback yet; wait for price to return to EMA20/EMA50",
            trigger=trigger,
            near_pullback_zone=False,
            approaching_pullback_zone=False,
            rsi_cooled=rsi_cooled,
            pullback_volume_contracting=pullback_volume_contracting,
            structure_intact=True,
            funding_warning=funding_warning,
            funding_extreme=funding_extreme,
            crowded_oi=crowded_oi,
            late_entry=False,
            entry_candle_too_large=entry_candle_too_large,
            nearest_ema=nearest_ema,
            entry_model=entry_model,
            overextension_atr=max_overextension_atr,
        )

    def _trend_direction(self, features: Features) -> Optional[Literal["LONG", "SHORT"]]:
        if features.ema_20 is None or features.ema_50 is None or features.ema_200 is None:
            return None
        if (
            features.close > features.ema_200
            and features.ema_50 > features.ema_200
            and features.ema_20 > features.ema_50
        ):
            return "LONG"
        if (
            features.close < features.ema_200
            and features.ema_50 < features.ema_200
            and features.ema_20 < features.ema_50
        ):
            return "SHORT"
        return None

    def _trend_strength_ok(self, features: Features) -> bool:
        if features.adx is not None and features.adx >= ADX_TREND_MIN:
            return True
        return bool(
            features.adx is not None
            and features.adx >= ADX_RISING_FLOOR
            and features.adx_rising_bars >= ADX_RISING_BARS_MIN
        )

    def _ema_stack_is_tangled(self, features: Features) -> bool:
        atr = self._atr(features)
        if features.ema_20 is None or features.ema_50 is None or features.ema_200 is None:
            return True
        return (
            abs(features.ema_20 - features.ema_50) < atr * 0.05
            and abs(features.ema_50 - features.ema_200) < atr * 0.1
        )

    def _funding_extremely_against(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        params: Mapping[str, Any],
    ) -> bool:
        if features.funding_rate is None:
            return False
        threshold = _numeric_param(params, "funding_block_threshold", FUNDING_BLOCK_THRESHOLD)
        if direction == "LONG":
            return features.funding_rate >= threshold
        return features.funding_rate <= -threshold

    def _funding_against_warning(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        params: Mapping[str, Any],
    ) -> bool:
        if features.funding_rate is None:
            return False
        threshold = _numeric_param(params, "funding_warning_threshold", FUNDING_WARNING_THRESHOLD)
        if direction == "LONG":
            return features.funding_rate >= threshold
        return features.funding_rate <= -threshold

    def _crowded_oi(self, features: Features, params: Mapping[str, Any]) -> bool:
        if features.oi_change is None:
            return False
        threshold = _numeric_param(
            params,
            "crowded_oi_change_threshold",
            DEFAULT_CROWDED_OI_CHANGE_THRESHOLD,
        )
        return features.oi_change >= threshold

    def _two_sided_wicks_are_noisy(self, features: Features) -> bool:
        return (features.upper_wick_ratio or 0.0) >= 0.35 and (features.lower_wick_ratio or 0.0) >= 0.35

    def _near_pullback_zone(self, features: Features) -> bool:
        atr = self._atr(features)
        return any(
            ema is not None and abs(features.close - ema) <= atr * PULLBACK_ZONE_ATR
            for ema in (features.ema_20, features.ema_50)
        )

    def _approaching_pullback_zone(self, features: Features) -> bool:
        atr = self._atr(features)
        return any(
            ema is not None and abs(features.close - ema) <= atr * APPROACH_ZONE_ATR
            for ema in (features.ema_20, features.ema_50)
        )

    def _nearest_pullback_ema(self, features: Features) -> float | None:
        candidates = [ema for ema in (features.ema_20, features.ema_50) if ema is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda ema: abs(features.close - ema))

    def _rsi_cooled(self, features: Features, direction: Literal["LONG", "SHORT"]) -> bool:
        if features.rsi_14 is None:
            return False
        if direction == "LONG":
            return 40 <= features.rsi_14 <= 55
        return 45 <= features.rsi_14 <= 60

    def _pullback_volume_contracting(self, features: Features) -> bool:
        if features.previous_volume is not None and features.volume_ma_20 > 0:
            return features.previous_volume <= features.volume_ma_20
        if self._trigger(features, "LONG") or self._trigger(features, "SHORT"):
            return True
        return features.volume_spike <= 1.0

    def _structure_intact(self, features: Features, direction: Literal["LONG", "SHORT"]) -> bool:
        if direction == "LONG":
            return features.swing_low is None or features.low >= features.swing_low
        return features.swing_high is None or features.high <= features.swing_high

    def _trigger(self, features: Features, direction: Literal["LONG", "SHORT"]) -> bool:
        volume_ok = features.volume_spike >= TRIGGER_VOLUME_MULTIPLIER
        if direction == "LONG":
            return (
                features.previous_high is not None
                and features.close > features.previous_high
                and features.close > features.open
                and volume_ok
            )
        return (
            features.previous_low is not None
            and features.close < features.previous_low
            and features.close < features.open
            and volume_ok
        )

    def _late_entry(self, features: Features, max_overextension_atr: float) -> bool:
        if features.ema_20 is None:
            return False
        return abs(features.close - features.ema_20) > self._atr(features) * max_overextension_atr

    def _entry_candle_too_large(self, features: Features, params: Mapping[str, Any]) -> bool:
        atr = self._atr(features)
        candle_range = max(features.high - features.low, 0.0)
        max_entry_candle_atr = _numeric_param(params, "max_entry_candle_atr", MAX_ENTRY_CANDLE_ATR)
        return candle_range > atr * max_entry_candle_atr

    def _entry_anchor(self, features: Features, setup: _TrendPullbackState) -> float:
        if setup.entry_model == "chase" and setup.trigger and not setup.entry_candle_too_large:
            return features.close
        return setup.nearest_ema or features.ema_20 or features.ema_50 or features.close

    def _targets(
        self,
        *,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        entry: float,
        stop_loss: float,
        atr: float,
    ) -> tuple[float, float, dict[str, str]]:
        risk = abs(entry - stop_loss)
        if risk <= 0:
            risk = max(atr, abs(entry) * 0.001, 1e-8)
        side = 1 if direction == "LONG" else -1
        one_r = entry + side * risk
        two_r = entry + side * risk * 2
        candidates = _directional_targets(
            direction,
            entry,
            (
                ("previous_high" if direction == "LONG" else "previous_low", features.previous_high if direction == "LONG" else features.previous_low),
                ("swing_high" if direction == "LONG" else "swing_low", features.swing_high if direction == "LONG" else features.swing_low),
                ("donchian_high_20" if direction == "LONG" else "donchian_low_20", features.donchian_high_20 if direction == "LONG" else features.donchian_low_20),
            ),
        )

        tp1 = one_r
        tp1_source = "one_r"
        for source, price in candidates:
            reward = _target_reward(direction, entry, price)
            if risk * 0.8 <= reward <= risk * 1.6:
                tp1 = price
                tp1_source = source
                break

        tp2 = two_r
        tp2_source = "two_r"
        minimum_tp2_reward = max(risk * 1.6, _target_reward(direction, entry, tp1) + risk * 0.4)
        for source, price in candidates:
            reward = _target_reward(direction, entry, price)
            if reward >= minimum_tp2_reward:
                tp2 = price
                tp2_source = source
                break
        if _target_reward(direction, entry, tp2) <= _target_reward(direction, entry, tp1):
            tp2 = entry + side * risk * 2
            tp2_source = "two_r"
        return tp1, tp2, {"TP1": tp1_source, "TP2": tp2_source}

    def _enrich_trade_plan(
        self,
        *,
        signal: StrategySignal,
        setup: _TrendPullbackState,
        target_sources: Mapping[str, str],
        params: Mapping[str, Any],
    ) -> StrategySignal:
        trade_plan = signal.trade_plan
        if trade_plan is None:
            return signal
        time_stop_bars = int(_numeric_param(params, "time_stop_bars", DEFAULT_TIME_STOP_BARS))
        entry_metadata = dict(trade_plan.entry.metadata)
        entry_metadata.update(
            {
                "entry_model": setup.entry_model,
                "entry_type": "ema_pullback_zone" if setup.entry_model != "chase" else "trigger_close",
                "nearest_ema": setup.nearest_ema,
                "overextension_atr_limit": setup.overextension_atr,
            }
        )
        entry = trade_plan.entry.model_copy(
            update={
                "source": "ema20_ema50_pullback_zone" if setup.entry_model != "chase" else "trigger_close",
                "metadata": entry_metadata,
            }
        )
        targets = [
            target.model_copy(
                update={
                    "source": target_sources.get(target.label, target.source),
                    "metadata": {
                        **target.metadata,
                        "entry_model": setup.entry_model,
                        "target_model": "structure_aware",
                    },
                }
            )
            for target in trade_plan.targets
        ]
        risk_metadata = dict(trade_plan.risk_rules.metadata)
        risk_metadata.update(
            {
                "time_stop_bars": time_stop_bars,
                "time_stop": "no_progress_to_TP1",
                "entry_model": setup.entry_model,
            }
        )
        risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})
        enriched_plan = trade_plan.model_copy(
            update={
                "entry": entry,
                "targets": targets,
                "risk_rules": risk_rules,
                "metadata": {
                    **trade_plan.metadata,
                    "entry_model": setup.entry_model,
                    "target_model": "structure_aware",
                },
            },
            deep=True,
        )
        return signal.model_copy(update={"trade_plan": enriched_plan})

    def _stop_loss(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        atr: float,
    ) -> float:
        if direction == "LONG":
            candidates = [value for value in (features.swing_low, features.ema_50, features.low) if value is not None]
            return min(candidates or [features.close]) - atr * STOP_ATR_BUFFER
        candidates = [value for value in (features.swing_high, features.ema_50, features.high) if value is not None]
        return max(candidates or [features.close]) + atr * STOP_ATR_BUFFER

    def _atr(self, features: Features) -> float:
        return features.atr_14 or max(abs(features.close) * 0.002, 1e-8)

    def _score(
        self,
        features: Features,
        setup: _TrendPullbackState,
        params: Mapping[str, Any],
    ) -> tuple[SignalScoreBreakdown, list[str], list[str]]:
        direction = setup.direction
        trend_score = 0
        volume_score = 0
        liquidity_score = 0
        volatility_score = 0
        overheat_penalty = 0
        reasons: list[str] = []
        risks: list[str] = []

        if direction == "LONG":
            if features.close > (features.ema_200 or features.close):
                trend_score += 20
                reasons.append("Price is above EMA200")
            if (features.ema_50 or 0) > (features.ema_200 or 0):
                trend_score += 15
                reasons.append("EMA50 is above EMA200")
            if (features.ema_20 or 0) > (features.ema_50 or 0):
                trend_score += 10
                reasons.append("EMA20 is above EMA50")
        else:
            if features.close < (features.ema_200 or features.close):
                trend_score += 20
                reasons.append("Price is below EMA200")
            if (features.ema_50 or 0) < (features.ema_200 or 0):
                trend_score += 15
                reasons.append("EMA50 is below EMA200")
            if (features.ema_20 or 0) < (features.ema_50 or 0):
                trend_score += 10
                reasons.append("EMA20 is below EMA50")

        if features.adx is not None and features.adx >= ADX_TREND_MIN:
            trend_score += 10
            reasons.append(f"ADX {features.adx:.1f} confirms trend strength")
        elif (
            features.adx is not None
            and features.adx >= ADX_RISING_FLOOR
            and features.adx_rising_bars >= ADX_RISING_BARS_MIN
        ):
            trend_score += 10
            reasons.append(f"ADX {features.adx:.1f} is rising across {features.adx_rising_bars} candles")

        if setup.near_pullback_zone:
            volatility_score += 15
            reasons.append("Price pulled back to the EMA20/EMA50 zone")
        else:
            risks.append("Price has not pulled back into the EMA20/EMA50 zone yet")

        if setup.pullback_volume_contracting:
            volume_score += 10
            reasons.append("Pullback volume is at or below average")
        else:
            risks.append("Pullback volume is not contracting")

        if setup.rsi_cooled and features.rsi_14 is not None:
            volatility_score += 10
            reasons.append(f"RSI {features.rsi_14:.1f} cooled without breaking momentum")
        elif features.rsi_14 is not None:
            risks.append(f"RSI {features.rsi_14:.1f} is outside the healthy pullback zone")

        if setup.trigger:
            liquidity_score += 10
            volume_score += 10
            trigger_side = "previous high" if direction == "LONG" else "previous low"
            reasons.append(f"Trigger candle broke the {trigger_side} with direction and volume")
        else:
            risks.append("Trigger is still missing: wait for previous high/low break with 1.1x volume")

        if setup.late_entry:
            overheat_penalty += 15
            risks.append(f"Entry is late: distance from EMA20 is above {setup.overextension_atr:.2f} ATR")
        if setup.entry_candle_too_large:
            overheat_penalty += 20
            risks.append("Entry candle range is above the configured ATR limit")
        if setup.funding_warning:
            overheat_penalty += 10
            risks.append("Funding is elevated against the planned direction")
        if setup.funding_extreme and setup.crowded_oi:
            crowded_penalty = int(
                _numeric_param(params, "crowded_oi_penalty", DEFAULT_CROWDED_OI_PENALTY)
            )
            overheat_penalty += crowded_penalty
            risks.append(
                "Extreme funding is paired with crowded open interest: "
                f"funding {features.funding_rate:.4%}, OI change {features.oi_change:.2%}"
            )

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


def _entry_model(params: Mapping[str, Any]) -> str:
    value = str(params.get("entry_model") or DEFAULT_ENTRY_MODEL).strip().lower()
    if value in {"chase", "trigger_close"}:
        return "chase"
    if value in {"retest", "zone", "pullback_zone"}:
        return "zone"
    return DEFAULT_ENTRY_MODEL


def _numeric_param(params: Mapping[str, Any], key: str, default: float) -> float:
    try:
        value = params.get(key)
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _directional_targets(
    direction: Literal["LONG", "SHORT"],
    entry: float,
    candidates: tuple[tuple[str, float | None], ...],
) -> list[tuple[str, float]]:
    valid = [
        (source, price)
        for source, price in candidates
        if price is not None and _target_reward(direction, entry, price) > 0
    ]
    return sorted(valid, key=lambda item: _target_reward(direction, entry, item[1]))


def _target_reward(direction: Literal["LONG", "SHORT"], entry: float, target: float) -> float:
    if direction == "LONG":
        return target - entry
    return entry - target
