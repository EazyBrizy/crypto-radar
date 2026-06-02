from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Mapping, Optional

from app.schemas.market import AlphaMarketContext, Features, LiquidityPoolFeatures
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.services.support_resistance import SupportResistanceSnapshot
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
DEFAULT_REQUIRE_STRUCTURAL_ZONE = False
DEFAULT_REQUIRE_DELTA_CONFIRMATION = False
DEFAULT_REQUIRE_ABSORPTION_OR_RECLAIM = True
DEFAULT_MIN_ZONE_QUALITY_SCORE = 0.35
DEFAULT_MIN_CONTINUATION_SCORE = 0.45
DEFAULT_MIN_ABSORPTION_SCORE = 0.35
DEFAULT_MAX_EXHAUSTION_SCORE = 0.70
DEFAULT_MIN_HTF_TARGET_DISTANCE_R = 0.0
DEFAULT_CROWDED_FUNDING_PRESSURE_THRESHOLD = 1.0
DEFAULT_VOLUME_CLIMAX_SPIKE = 3.0
DEFAULT_EXHAUSTION_DISTANCE_ATR = 2.2
DEFAULT_IMPULSE_BODY_ATR = 1.1
DEFAULT_CONSECUTIVE_IMPULSE_CANDLES = 3

StructuralPullbackZoneSource = Literal[
    "vwap",
    "vwap_deviation",
    "liquidity_pool",
    "imbalance",
    "ema20",
    "ema50",
    "range_boundary",
    "htf_support_resistance",
]


@dataclass(frozen=True)
class StructuralPullbackZone:
    source: StructuralPullbackZoneSource
    price: float
    distance_atr: float
    quality_score: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ContinuationAssessment:
    score: float
    reclaimed: bool
    absorption_confirmed: bool
    delta_confirmed: bool
    volume_confirmed: bool
    required_delta_missing: bool
    required_reclaim_or_absorption_missing: bool
    reasons: tuple[str, ...]
    missing_alpha_sources: tuple[str, ...]

    @property
    def confirmed(self) -> bool:
        return (
            not self.required_delta_missing
            and not self.required_reclaim_or_absorption_missing
        )


@dataclass(frozen=True)
class ExhaustionAssessment:
    score: float
    reasons: tuple[str, ...]
    max_score: float

    @property
    def severe(self) -> bool:
        return self.score > self.max_score


@dataclass(frozen=True)
class CrowdedTradeAssessment:
    score: float
    funding_warning: bool
    funding_extreme: bool
    crowded_oi: bool
    hard_block: bool
    funding_rate: float | None
    funding_pressure: float | None
    oi_delta: float | None
    reasons: tuple[str, ...]
    alpha_context_used: bool

    @property
    def crowded(self) -> bool:
        return self.funding_extreme and self.crowded_oi


@dataclass(frozen=True)
class HtfTargetAssessment:
    price: float | None
    source: str | None
    distance_r: float | None
    too_close: bool
    min_distance_r: float


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
    structural_zone: StructuralPullbackZone | None
    continuation: ContinuationAssessment
    exhaustion: ExhaustionAssessment
    crowding: CrowdedTradeAssessment
    htf_target: HtfTargetAssessment
    entry_model: str
    overextension_atr: float
    structural_zone_required: bool
    structural_zone_ok: bool
    alpha_context_used: bool
    missing_alpha_sources: tuple[str, ...]


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
            setup=setup,
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
        if self._two_sided_wicks_are_noisy(features):
            return None

        alpha_context = _alpha_context_param(params)
        support_resistance = _primary_support_resistance_param(params, features.timeframe)
        zones = _structural_pullback_zones(
            features=features,
            direction=direction,
            params=params,
            alpha_context=alpha_context,
            support_resistance=support_resistance,
        )
        structural_zone_required = _bool_param(
            params,
            "require_structural_zone",
            DEFAULT_REQUIRE_STRUCTURAL_ZONE,
        )
        min_zone_quality_score = _numeric_param(
            params,
            "min_zone_quality_score",
            DEFAULT_MIN_ZONE_QUALITY_SCORE,
        )
        structural_zone = _best_pullback_zone(zones)
        structural_zone_ok = (
            structural_zone is not None
            and structural_zone.quality_score >= min_zone_quality_score
            and (
                not structural_zone_required
                or structural_zone.source not in {"ema20", "ema50"}
            )
        )
        near_pullback_zone = self._near_pullback_zone(features) or _zone_within_atr(
            structural_zone,
            PULLBACK_ZONE_ATR,
        )
        approaching_pullback_zone = self._approaching_pullback_zone(features) or _zone_within_atr(
            structural_zone,
            APPROACH_ZONE_ATR,
        )
        rsi_cooled = self._rsi_cooled(features, direction)
        pullback_volume_contracting = self._pullback_volume_contracting(features)
        structure_intact = self._structure_intact(features, direction)
        trigger = self._trigger(features, direction)
        continuation = _continuation_assessment(
            features=features,
            direction=direction,
            zone=structural_zone,
            trigger=trigger,
            near_pullback_zone=near_pullback_zone,
            alpha_context=alpha_context,
            params=params,
        )
        crowding = _crowded_trade_assessment(
            features=features,
            direction=direction,
            params=params,
            alpha_context=alpha_context,
        )
        max_overextension_atr = _numeric_param(params, "max_overextension_atr", LATE_ENTRY_EMA20_ATR)
        late_entry = self._late_entry(features, max_overextension_atr)
        entry_candle_too_large = self._entry_candle_too_large(features, params)
        nearest_ema = self._nearest_pullback_ema(features)
        entry_model = _entry_model(params)
        exhaustion = _exhaustion_assessment(
            features=features,
            direction=direction,
            params=params,
            alpha_context=alpha_context,
            crowding=crowding,
            nearest_ema=nearest_ema,
        )
        entry_for_target = structural_zone.price if structural_zone is not None else nearest_ema or features.close
        stop_for_target = self._stop_loss(features, direction, self._atr(features))
        htf_target = _htf_target_assessment(
            features=features,
            direction=direction,
            params=params,
            alpha_context=alpha_context,
            support_resistance=support_resistance,
            entry=entry_for_target,
            stop_loss=stop_for_target,
        )
        missing_alpha_sources = _missing_alpha_sources(alpha_context)

        def build_state(status: str, reason: str) -> _TrendPullbackState:
            return _TrendPullbackState(
                direction=direction,
                status=status,
                reason=reason,
                trigger=trigger,
                near_pullback_zone=near_pullback_zone,
                approaching_pullback_zone=approaching_pullback_zone,
                rsi_cooled=rsi_cooled,
                pullback_volume_contracting=pullback_volume_contracting,
                structure_intact=structure_intact,
                funding_warning=crowding.funding_warning,
                funding_extreme=crowding.funding_extreme,
                crowded_oi=crowding.crowded_oi,
                late_entry=late_entry,
                entry_candle_too_large=entry_candle_too_large,
                nearest_ema=nearest_ema,
                structural_zone=structural_zone,
                continuation=continuation,
                exhaustion=exhaustion,
                crowding=crowding,
                htf_target=htf_target,
                entry_model=entry_model,
                overextension_atr=max_overextension_atr,
                structural_zone_required=structural_zone_required,
                structural_zone_ok=structural_zone_ok,
                alpha_context_used=alpha_context is not None,
                missing_alpha_sources=missing_alpha_sources,
            )

        if not structure_intact:
            return None

        if crowding.hard_block:
            return build_state(
                "rejected",
                "Crowded funding/open-interest pressure is configured as a hard trend-pullback block",
            )

        if exhaustion.severe:
            return build_state(
                "watchlist",
                (
                    f"Trend exhaustion score {exhaustion.score:.2f} is above "
                    f"{exhaustion.max_score:.2f}; wait for a cleaner structural pullback"
                ),
            )

        if htf_target.too_close:
            distance = htf_target.distance_r if htf_target.distance_r is not None else 0.0
            return build_state(
                "watchlist",
                (
                    f"Nearest HTF/liquidity target is only {distance:.2f}R away; "
                    f"minimum is {htf_target.min_distance_r:.2f}R"
                ),
            )

        if late_entry:
            return build_state(
                "wait_for_pullback",
                (
                    "Trend is confirmed, but entry is late: price is more than "
                    f"{max_overextension_atr:.2f} ATR from EMA20; wait for a fresh pullback"
                ),
            )

        if structural_zone_required and not structural_zone_ok:
            return build_state(
                "watchlist",
                (
                    "Trend is intact, but pullback has no qualified VWAP/liquidity/HTF structural zone; "
                    "EMA-only context is kept as watchlist"
                ),
            )

        min_continuation_score = _numeric_param(
            params,
            "min_continuation_score",
            DEFAULT_MIN_CONTINUATION_SCORE,
        )
        continuation_confirmed = continuation.confirmed and continuation.score >= min_continuation_score

        if near_pullback_zone and rsi_cooled and pullback_volume_contracting and trigger and continuation_confirmed:
            zone_source = structural_zone.source if structural_zone is not None else "EMA/VWAP"
            return build_state(
                "actionable",
                (
                    f"Pullback held/reclaimed {zone_source} structure and trigger candle broke "
                    "the previous candle with volume/orderflow confirmation"
                ),
            )

        if near_pullback_zone:
            zone_label = (
                structural_zone.source.replace("_", " ")
                if structural_zone is not None
                else "EMA20/EMA50"
            )
            reason_parts = [f"Price is in the {zone_label} pullback zone"]
            if not rsi_cooled:
                reason_parts.append("RSI has not cooled into the healthy pullback zone")
            if not pullback_volume_contracting:
                reason_parts.append("pullback volume is not contracting")
            if not trigger:
                reason_parts.append("waiting for previous high/low trigger and trigger volume")
            if continuation.score < min_continuation_score:
                reason_parts.append(
                    f"continuation score {continuation.score:.2f} is below {min_continuation_score:.2f}"
                )
            if continuation.required_delta_missing:
                reason_parts.append("required delta confirmation is missing")
            if continuation.required_reclaim_or_absorption_missing:
                reason_parts.append("waiting for absorption or reclaim confirmation")
            return build_state("ready", "; ".join(reason_parts))

        if approaching_pullback_zone:
            zone_label = (
                structural_zone.source.replace("_", " ")
                if structural_zone is not None
                else "EMA20/EMA50"
            )
            return build_state(
                "watchlist",
                f"Trend is intact and price is approaching the {zone_label} pullback zone",
            )

        return build_state(
            "wait_for_pullback",
            (
                "Trend is confirmed, but there is no healthy structural pullback yet; "
                "wait for price to return to VWAP/liquidity/HTF/EMA zone"
            ),
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
        if setup.structural_zone is not None:
            return setup.structural_zone.price
        return setup.nearest_ema or features.ema_20 or features.ema_50 or features.close

    def _targets(
        self,
        *,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        entry: float,
        stop_loss: float,
        atr: float,
        setup: _TrendPullbackState,
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
                (
                    setup.htf_target.source or "htf_support_resistance",
                    setup.htf_target.price,
                ),
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
        zone_metadata = _zone_metadata(setup.structural_zone)
        trend_metadata = {
            "structural_pullback_zone": zone_metadata,
            "structural_zone_source": setup.structural_zone.source if setup.structural_zone else None,
            "structural_zone_price": setup.structural_zone.price if setup.structural_zone else None,
            "structural_zone_quality_score": (
                setup.structural_zone.quality_score if setup.structural_zone else None
            ),
            "require_structural_zone": setup.structural_zone_required,
            "structural_zone_ok": setup.structural_zone_ok,
            "continuation_score": setup.continuation.score,
            "min_continuation_score": _numeric_param(
                params,
                "min_continuation_score",
                DEFAULT_MIN_CONTINUATION_SCORE,
            ),
            "delta_confirmed": setup.continuation.delta_confirmed,
            "absorption_confirmed": setup.continuation.absorption_confirmed,
            "reclaimed_pullback_zone": setup.continuation.reclaimed,
            "exhaustion_score": setup.exhaustion.score,
            "exhaustion_reasons": list(setup.exhaustion.reasons),
            "max_exhaustion_score": setup.exhaustion.max_score,
            "crowded_trade_score": setup.crowding.score,
            "crowded_trade_reasons": list(setup.crowding.reasons),
            "crowded_trade_hard_block": setup.crowding.hard_block,
            "funding_pressure": setup.crowding.funding_pressure,
            "funding_rate": setup.crowding.funding_rate,
            "oi_delta": setup.crowding.oi_delta,
            "crowded_oi": setup.crowding.crowded_oi,
            "nearest_htf_target": setup.htf_target.price,
            "nearest_htf_target_source": setup.htf_target.source,
            "nearest_htf_target_distance_r": setup.htf_target.distance_r,
            "min_htf_target_distance_r": setup.htf_target.min_distance_r,
            "alpha_context_used": setup.alpha_context_used,
            "missing_alpha_sources": list(setup.missing_alpha_sources),
        }
        entry_metadata = dict(trade_plan.entry.metadata)
        entry_metadata.update(
            {
                "entry_model": setup.entry_model,
                "entry_type": (
                    "structural_pullback_zone"
                    if setup.entry_model != "chase"
                    else "trigger_close"
                ),
                "nearest_ema": setup.nearest_ema,
                "overextension_atr_limit": setup.overextension_atr,
                **trend_metadata,
            }
        )
        entry_source = _entry_source(setup)
        entry = trade_plan.entry.model_copy(
            update={
                "source": entry_source,
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
                        "nearest_htf_target": setup.htf_target.price,
                        "nearest_htf_target_source": setup.htf_target.source,
                        "nearest_htf_target_distance_r": setup.htf_target.distance_r,
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
                **trend_metadata,
            }
        )
        risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})
        invalidation = trade_plan.invalidation
        if invalidation is not None:
            invalidation_conditions = [
                *invalidation.conditions,
                "Loss of structural pullback zone",
                "Close accepts back through VWAP/zone against continuation",
                "Break of swing invalidation level",
            ]
            if setup.structural_zone is not None and setup.structural_zone.source in {"ema20", "ema50"}:
                invalidation_conditions.append("Loss of EMA pullback fallback zone")
            invalidation = invalidation.model_copy(
                update={
                    "conditions": list(dict.fromkeys(invalidation_conditions)),
                    "metadata": {
                        **invalidation.metadata,
                        "source": "structural_pullback_invalidation",
                        "structural_invalidation": True,
                        **trend_metadata,
                    },
                }
            )
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
                    "target_model": "structure_aware",
                    "trend_pullback_score_breakdown": trend_metadata,
                    "target_source": setup.htf_target.source or trade_plan.metadata.get("target_source"),
                    "target_thesis": (
                        f"Nearest continuation liquidity/HTF target from {setup.htf_target.source}"
                        if setup.htf_target.source is not None
                        else "Structure-aware continuation targets"
                    ),
                    **trend_metadata,
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
        orderbook_score = 0
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

        if setup.structural_zone is not None:
            zone_points = int(round(setup.structural_zone.quality_score * 20))
            liquidity_score += zone_points
            reasons.append(
                "Structural pullback zone "
                f"{setup.structural_zone.source} at {setup.structural_zone.price:.8f} "
                f"quality {setup.structural_zone.quality_score:.2f}"
            )
            if setup.structural_zone.source in {"ema20", "ema50"}:
                volatility_score += 8
                if setup.structural_zone_required:
                    overheat_penalty += 10
                    risks.append("EMA-only pullback zone is not enough for require_structural_zone=true")
            else:
                volatility_score += 12
        else:
            risks.append("No VWAP/liquidity/HTF/EMA pullback zone was found")

        if setup.near_pullback_zone:
            volatility_score += 10
            reasons.append("Price pulled back into the selected structural zone")
        else:
            risks.append("Price has not pulled back into a qualified structural zone yet")

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

        continuation_points = int(round(setup.continuation.score * 15))
        orderbook_score += continuation_points
        if setup.continuation.reasons:
            reasons.extend(setup.continuation.reasons)
        if setup.continuation.required_delta_missing:
            risks.append("Required delta confirmation is missing for continuation")
        if setup.continuation.required_reclaim_or_absorption_missing:
            risks.append("Continuation needs absorption or reclaim confirmation")

        if setup.htf_target.distance_r is not None:
            reasons.append(
                f"Nearest HTF/liquidity target distance preview: {setup.htf_target.distance_r:.2f}R"
            )
            if setup.htf_target.too_close:
                overheat_penalty += 20
                risks.append(
                    "Nearest HTF/liquidity target is too close for the configured trend-pullback threshold"
                )

        if setup.late_entry:
            overheat_penalty += 15
            risks.append(f"Entry is late: distance from EMA20 is above {setup.overextension_atr:.2f} ATR")
        if setup.entry_candle_too_large:
            overheat_penalty += 20
            risks.append("Entry candle range is above the configured ATR limit")
        if setup.crowding.reasons:
            risks.extend(setup.crowding.reasons)
        if setup.funding_warning:
            overheat_penalty += 8
        if setup.funding_extreme:
            overheat_penalty += 8
        if setup.crowding.crowded:
            crowded_penalty = int(
                _numeric_param(params, "crowded_oi_penalty", DEFAULT_CROWDED_OI_PENALTY)
            )
            overheat_penalty += crowded_penalty
        if setup.exhaustion.reasons:
            risks.extend(setup.exhaustion.reasons)
            overheat_penalty += int(round(setup.exhaustion.score * 25))

        return (
            score_breakdown(
                trend_score=trend_score,
                volume_score=volume_score,
                liquidity_score=liquidity_score,
                orderbook_score=orderbook_score,
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


def _bool_param(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _optional_int_param(params: Mapping[str, Any], key: str) -> int | None:
    try:
        value = params.get(key)
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _alpha_context_param(params: Mapping[str, Any]) -> AlphaMarketContext | None:
    value = params.get("alpha_context")
    return value if isinstance(value, AlphaMarketContext) else None


def _support_resistance_by_timeframe_param(params: Mapping[str, Any]) -> dict[str, SupportResistanceSnapshot]:
    value = params.get("support_resistance_by_timeframe")
    if not isinstance(value, Mapping):
        return {}
    return {
        str(timeframe): snapshot
        for timeframe, snapshot in value.items()
        if isinstance(snapshot, SupportResistanceSnapshot)
    }


def _primary_support_resistance_param(
    params: Mapping[str, Any],
    signal_timeframe: str,
) -> SupportResistanceSnapshot | None:
    snapshots = _support_resistance_by_timeframe_param(params)
    if not snapshots:
        return None
    expected = _context_timeframe_for(signal_timeframe, params)
    if expected is not None and expected in snapshots:
        return snapshots[expected]
    return next(iter(snapshots.values()))


def _context_timeframe_for(timeframe: str, params: Mapping[str, Any]) -> str | None:
    raw_map = params.get("context_timeframe_map")
    if isinstance(raw_map, Mapping):
        raw_value = raw_map.get(timeframe)
        if raw_value is not None:
            value = str(raw_value).strip().lower()
            if value:
                return value
    return {
        "1m": "15m",
        "5m": "1h",
        "15m": "1h",
        "1h": "4h",
        "4h": "1d",
    }.get(timeframe)


def _missing_alpha_sources(alpha_context: AlphaMarketContext | None) -> tuple[str, ...]:
    if alpha_context is None:
        return ("alpha_context",)
    raw_missing = alpha_context.data_quality.get("missing_sources")
    missing = [str(item) for item in raw_missing] if isinstance(raw_missing, list) else []
    if alpha_context.aggressive_delta is None and alpha_context.cvd_change is None:
        missing.append("delta")
    if alpha_context.oi_delta_5m is None and alpha_context.oi_delta_15m is None:
        missing.append("open_interest")
    if alpha_context.vwap_acceptance is None and alpha_context.vwap_deviation is None:
        missing.append("vwap_acceptance")
    return tuple(dict.fromkeys(missing))


def _structural_pullback_zones(
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    params: Mapping[str, Any],
    alpha_context: AlphaMarketContext | None,
    support_resistance: SupportResistanceSnapshot | None,
) -> list[StructuralPullbackZone]:
    atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
    zones: list[StructuralPullbackZone] = []
    _append_vwap_zones(zones, features, direction, atr, alpha_context)
    _append_liquidity_zones(zones, features, direction, atr, alpha_context)
    _append_htf_zones(zones, features, direction, atr, support_resistance)
    _append_imbalance_zone(zones, features, direction, atr, alpha_context)
    _append_ema_zones(zones, features, direction, atr)
    return _dedupe_zones(zones)


def _append_vwap_zones(
    zones: list[StructuralPullbackZone],
    features: Features,
    direction: Literal["LONG", "SHORT"],
    atr: float,
    alpha_context: AlphaMarketContext | None,
) -> None:
    if features.vwap is None or features.vwap <= 0:
        return
    acceptance = alpha_context.vwap_acceptance if alpha_context is not None else None
    deviation = alpha_context.vwap_deviation if alpha_context is not None else None
    source: StructuralPullbackZoneSource = "vwap_deviation" if deviation is not None else "vwap"
    quality = 0.55
    if acceptance in {"at_vwap", "above_vwap"} and direction == "LONG":
        quality += 0.15
    if acceptance in {"at_vwap", "below_vwap"} and direction == "SHORT":
        quality += 0.15
    if deviation is not None and abs(deviation) <= 0.004:
        quality += 0.10
    _append_zone_if_usable(
        zones,
        features=features,
        direction=direction,
        atr=atr,
        source=source,
        price=features.vwap,
        quality=quality,
        metadata={
            "vwap_acceptance": acceptance,
            "vwap_deviation": deviation,
        },
    )


def _append_liquidity_zones(
    zones: list[StructuralPullbackZone],
    features: Features,
    direction: Literal["LONG", "SHORT"],
    atr: float,
    alpha_context: AlphaMarketContext | None,
) -> None:
    if direction == "LONG":
        raw_levels = (
            ("session_low", features.session_low, 0.50),
            ("previous_day_low", features.previous_day_low, 0.58),
            ("previous_day_high_reclaim", features.previous_day_high, 0.60),
            ("range_boundary", features.donchian_low_20, 0.48),
            ("swing_low", features.swing_low, 0.45),
        )
        pool_side = "below"
    else:
        raw_levels = (
            ("session_high", features.session_high, 0.50),
            ("previous_day_high", features.previous_day_high, 0.58),
            ("previous_day_low_reclaim", features.previous_day_low, 0.60),
            ("range_boundary", features.donchian_high_20, 0.48),
            ("swing_high", features.swing_high, 0.45),
        )
        pool_side = "above"

    for name, price, base_quality in raw_levels:
        quality = base_quality
        if name.startswith("swing"):
            touch_count = features.swing_low_touch_count if direction == "LONG" else features.swing_high_touch_count
            volume_score = features.swing_low_volume_score if direction == "LONG" else features.swing_high_volume_score
            quality += min(0.15, touch_count * 0.03)
            if volume_score is not None:
                quality += min(0.10, max(0.0, volume_score - 1.0) * 0.05)
        source: StructuralPullbackZoneSource = "range_boundary" if name == "range_boundary" else "liquidity_pool"
        _append_zone_if_usable(
            zones,
            features=features,
            direction=direction,
            atr=atr,
            source=source,
            price=price,
            quality=quality,
            metadata={"level_name": name},
        )

    if alpha_context is None:
        return
    for pool in alpha_context.session_liquidity_pools:
        if pool.side != pool_side:
            continue
        zone = _zone_from_liquidity_pool(pool, features, direction, atr)
        if zone is not None:
            zones.append(zone)


def _zone_from_liquidity_pool(
    pool: LiquidityPoolFeatures,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    atr: float,
) -> StructuralPullbackZone | None:
    quality = 0.55
    if pool.strength is not None:
        quality += min(0.20, pool.strength / 500)
    return _zone_if_usable(
        features=features,
        direction=direction,
        atr=atr,
        source="liquidity_pool",
        price=pool.price,
        quality=quality,
        metadata={
            "level_name": pool.name,
            "pool_source": pool.source,
            "pool_strength": pool.strength,
            "pool_side": pool.side,
        },
    )


def _append_htf_zones(
    zones: list[StructuralPullbackZone],
    features: Features,
    direction: Literal["LONG", "SHORT"],
    atr: float,
    support_resistance: SupportResistanceSnapshot | None,
) -> None:
    if support_resistance is None:
        return
    desired_kind = "support" if direction == "LONG" else "resistance"
    for level in support_resistance.levels:
        if level.kind != desired_kind:
            continue
        quality = 0.50 + min(0.25, level.strength / 400)
        _append_zone_if_usable(
            zones,
            features=features,
            direction=direction,
            atr=atr,
            source="htf_support_resistance",
            price=level.price,
            quality=quality,
            metadata={
                "context_timeframe": support_resistance.timeframe,
                "level_kind": level.kind,
                "strength": level.strength,
                "retest_count": level.retest_count,
                "age_candles": level.age_candles,
            },
        )


def _append_imbalance_zone(
    zones: list[StructuralPullbackZone],
    features: Features,
    direction: Literal["LONG", "SHORT"],
    atr: float,
    alpha_context: AlphaMarketContext | None,
) -> None:
    if alpha_context is None or alpha_context.depth_wall_price is None:
        return
    wall_supports_direction = (
        direction == "LONG" and alpha_context.depth_wall_side == "bid"
    ) or (
        direction == "SHORT" and alpha_context.depth_wall_side == "ask"
    )
    if not wall_supports_direction:
        return
    quality = 0.45
    if alpha_context.orderbook_imbalance is not None:
        quality += min(0.20, abs(alpha_context.orderbook_imbalance) * 0.20)
    if alpha_context.absorption_score is not None:
        quality += min(0.20, alpha_context.absorption_score * 0.20)
    _append_zone_if_usable(
        zones,
        features=features,
        direction=direction,
        atr=atr,
        source="imbalance",
        price=alpha_context.depth_wall_price,
        quality=quality,
        metadata={
            "depth_wall_side": alpha_context.depth_wall_side,
            "orderbook_imbalance": alpha_context.orderbook_imbalance,
            "absorption_score": alpha_context.absorption_score,
        },
    )


def _append_ema_zones(
    zones: list[StructuralPullbackZone],
    features: Features,
    direction: Literal["LONG", "SHORT"],
    atr: float,
) -> None:
    _append_zone_if_usable(
        zones,
        features=features,
        direction=direction,
        atr=atr,
        source="ema20",
        price=features.ema_20,
        quality=0.40,
        metadata={"fallback_context": True},
    )
    _append_zone_if_usable(
        zones,
        features=features,
        direction=direction,
        atr=atr,
        source="ema50",
        price=features.ema_50,
        quality=0.36,
        metadata={"fallback_context": True},
    )


def _append_zone_if_usable(
    zones: list[StructuralPullbackZone],
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    atr: float,
    source: StructuralPullbackZoneSource,
    price: float | None,
    quality: float,
    metadata: dict[str, Any],
) -> None:
    zone = _zone_if_usable(
        features=features,
        direction=direction,
        atr=atr,
        source=source,
        price=price,
        quality=quality,
        metadata=metadata,
    )
    if zone is not None:
        zones.append(zone)


def _zone_if_usable(
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    atr: float,
    source: StructuralPullbackZoneSource,
    price: float | None,
    quality: float,
    metadata: dict[str, Any],
) -> StructuralPullbackZone | None:
    if price is None or price <= 0:
        return None
    if not _zone_on_pullback_side(features, direction, price, atr):
        return None
    distance_atr = abs(features.close - price) / atr if atr > 0 else 0.0
    if distance_atr > APPROACH_ZONE_ATR:
        return None
    return StructuralPullbackZone(
        source=source,
        price=price,
        distance_atr=round(distance_atr, 4),
        quality_score=round(max(0.0, min(1.0, quality)), 4),
        metadata=metadata,
    )


def _zone_on_pullback_side(
    features: Features,
    direction: Literal["LONG", "SHORT"],
    price: float,
    atr: float,
) -> bool:
    tolerance = max(atr * 0.25, abs(price) * 0.0005)
    if direction == "LONG":
        return price <= features.close + tolerance
    return price >= features.close - tolerance


def _dedupe_zones(zones: list[StructuralPullbackZone]) -> list[StructuralPullbackZone]:
    by_key: dict[tuple[str, float], StructuralPullbackZone] = {}
    for zone in zones:
        key = (zone.source, round(zone.price, 8))
        existing = by_key.get(key)
        if existing is None or zone.quality_score > existing.quality_score:
            by_key[key] = zone
    return list(by_key.values())


def _best_pullback_zone(zones: list[StructuralPullbackZone]) -> StructuralPullbackZone | None:
    if not zones:
        return None
    priority: dict[str, int] = {
        "vwap": 0,
        "vwap_deviation": 0,
        "liquidity_pool": 1,
        "range_boundary": 1,
        "htf_support_resistance": 2,
        "imbalance": 3,
        "ema20": 4,
        "ema50": 5,
    }
    return min(
        zones,
        key=lambda zone: (
            priority.get(zone.source, 99),
            -zone.quality_score,
            zone.distance_atr,
        ),
    )


def _zone_within_atr(zone: StructuralPullbackZone | None, limit_atr: float) -> bool:
    return zone is not None and zone.distance_atr <= limit_atr


def _continuation_assessment(
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    zone: StructuralPullbackZone | None,
    trigger: bool,
    near_pullback_zone: bool,
    alpha_context: AlphaMarketContext | None,
    params: Mapping[str, Any],
) -> ContinuationAssessment:
    require_delta = _bool_param(
        params,
        "require_delta_confirmation",
        DEFAULT_REQUIRE_DELTA_CONFIRMATION,
    )
    require_absorption_or_reclaim = _bool_param(
        params,
        "require_absorption_or_reclaim",
        DEFAULT_REQUIRE_ABSORPTION_OR_RECLAIM,
    )
    reclaimed = _zone_reclaimed(features, direction, zone, alpha_context)
    absorption_confirmed = _absorption_confirms(direction, alpha_context, params)
    delta_confirmed = _delta_confirms(direction, alpha_context)
    volume_confirmed = features.volume_spike >= TRIGGER_VOLUME_MULTIPLIER
    score = 0.0
    reasons: list[str] = []
    if near_pullback_zone:
        score += 0.20
    if reclaimed:
        score += 0.25
        reasons.append("Pullback zone was reclaimed/accepted in continuation direction")
    if absorption_confirmed:
        score += 0.20
        reasons.append("Absorption/orderbook evidence supports continuation")
    if delta_confirmed:
        score += 0.20
        reasons.append("Delta/CVD confirms continuation")
    if trigger:
        score += 0.10
    if volume_confirmed:
        score += 0.05
    required_delta_missing = require_delta and not delta_confirmed
    required_reclaim_missing = require_absorption_or_reclaim and not (reclaimed or absorption_confirmed)
    return ContinuationAssessment(
        score=round(max(0.0, min(1.0, score)), 4),
        reclaimed=reclaimed,
        absorption_confirmed=absorption_confirmed,
        delta_confirmed=delta_confirmed,
        volume_confirmed=volume_confirmed,
        required_delta_missing=required_delta_missing,
        required_reclaim_or_absorption_missing=required_reclaim_missing,
        reasons=tuple(reasons),
        missing_alpha_sources=_missing_alpha_sources(alpha_context),
    )


def _zone_reclaimed(
    features: Features,
    direction: Literal["LONG", "SHORT"],
    zone: StructuralPullbackZone | None,
    alpha_context: AlphaMarketContext | None,
) -> bool:
    if zone is None:
        return False
    atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
    tolerance = max(atr * 0.10, abs(zone.price) * 0.0005)
    if direction == "LONG":
        if alpha_context is not None and alpha_context.vwap_acceptance == "above_vwap" and zone.source.startswith("vwap"):
            return True
        return features.low <= zone.price + tolerance and features.close >= zone.price
    if alpha_context is not None and alpha_context.vwap_acceptance == "below_vwap" and zone.source.startswith("vwap"):
        return True
    return features.high >= zone.price - tolerance and features.close <= zone.price


def _absorption_confirms(
    direction: Literal["LONG", "SHORT"],
    alpha_context: AlphaMarketContext | None,
    params: Mapping[str, Any],
) -> bool:
    if alpha_context is None or alpha_context.absorption_score is None:
        return False
    min_score = _numeric_param(params, "min_absorption_score", DEFAULT_MIN_ABSORPTION_SCORE)
    if alpha_context.absorption_score < min_score:
        return False
    if direction == "LONG":
        return alpha_context.depth_wall_side in {"bid", "none", None} or (alpha_context.orderbook_imbalance or 0.0) >= 0
    return alpha_context.depth_wall_side in {"ask", "none", None} or (alpha_context.orderbook_imbalance or 0.0) <= 0


def _delta_confirms(
    direction: Literal["LONG", "SHORT"],
    alpha_context: AlphaMarketContext | None,
) -> bool:
    if alpha_context is None:
        return False
    if direction == "LONG":
        return bool(
            (alpha_context.aggressive_delta is not None and alpha_context.aggressive_delta > 0)
            or (alpha_context.cvd_change is not None and alpha_context.cvd_change > 0)
            or alpha_context.delta_divergence == "bullish_divergence"
        )
    return bool(
        (alpha_context.aggressive_delta is not None and alpha_context.aggressive_delta < 0)
        or (alpha_context.cvd_change is not None and alpha_context.cvd_change < 0)
        or alpha_context.delta_divergence == "bearish_divergence"
    )


def _crowded_trade_assessment(
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    params: Mapping[str, Any],
    alpha_context: AlphaMarketContext | None,
) -> CrowdedTradeAssessment:
    funding_rate = (
        alpha_context.funding_rate
        if alpha_context is not None and alpha_context.funding_rate is not None
        else features.funding_rate
    )
    funding_pressure = alpha_context.funding_pressure if alpha_context is not None else None
    if funding_pressure is None and funding_rate is not None:
        block_threshold = _numeric_param(params, "funding_block_threshold", FUNDING_BLOCK_THRESHOLD)
        if block_threshold > 0:
            funding_pressure = funding_rate / block_threshold
    oi_delta = None
    if alpha_context is not None:
        oi_delta = alpha_context.oi_delta_15m if alpha_context.oi_delta_15m is not None else alpha_context.oi_delta_5m
    if oi_delta is None:
        oi_delta = features.oi_change

    warning_threshold = _numeric_param(params, "funding_warning_threshold", FUNDING_WARNING_THRESHOLD)
    block_threshold = _numeric_param(params, "funding_block_threshold", FUNDING_BLOCK_THRESHOLD)
    pressure_threshold = _numeric_param(
        params,
        "crowded_funding_pressure_threshold",
        DEFAULT_CROWDED_FUNDING_PRESSURE_THRESHOLD,
    )
    against_rate = 0.0 if funding_rate is None else funding_rate if direction == "LONG" else -funding_rate
    against_pressure = (
        0.0
        if funding_pressure is None
        else funding_pressure
        if direction == "LONG"
        else -funding_pressure
    )
    funding_warning = against_rate >= warning_threshold or against_pressure >= pressure_threshold * 0.5
    funding_extreme = against_rate >= block_threshold or against_pressure >= pressure_threshold
    oi_threshold = _numeric_param(
        params,
        "crowded_oi_change_threshold",
        DEFAULT_CROWDED_OI_CHANGE_THRESHOLD,
    )
    crowded_oi = oi_delta is not None and oi_delta >= oi_threshold
    reasons: list[str] = []
    score = 0.0
    if funding_warning:
        score += 0.25
        reasons.append("Funding pressure is elevated in the trade direction")
    if funding_extreme:
        score += 0.30
        reasons.append("Funding pressure is extreme in the trade direction")
    if crowded_oi:
        score += 0.25
        reasons.append(f"Open interest is crowded: {oi_delta:.2%}")
    if funding_extreme and crowded_oi:
        score += 0.20
        reasons.append("Extreme funding is paired with crowded open interest")
    hard_block = (
        _bool_param(params, "block_crowded_funding_oi", False)
        or _bool_param(params, "hard_fail_crowded_funding_oi", False)
    ) and funding_extreme and crowded_oi
    return CrowdedTradeAssessment(
        score=round(max(0.0, min(1.0, score)), 4),
        funding_warning=funding_warning,
        funding_extreme=funding_extreme,
        crowded_oi=crowded_oi,
        hard_block=hard_block,
        funding_rate=funding_rate,
        funding_pressure=funding_pressure,
        oi_delta=oi_delta,
        reasons=tuple(reasons),
        alpha_context_used=alpha_context is not None,
    )


def _exhaustion_assessment(
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    params: Mapping[str, Any],
    alpha_context: AlphaMarketContext | None,
    crowding: CrowdedTradeAssessment,
    nearest_ema: float | None,
) -> ExhaustionAssessment:
    atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
    max_score = _numeric_param(params, "max_exhaustion_score", DEFAULT_MAX_EXHAUSTION_SCORE)
    score = 0.0
    reasons: list[str] = []
    references = [value for value in (features.vwap, nearest_ema, features.ema_20, features.ema_50) if value is not None]
    if references:
        distance_atr = min(abs(features.close - value) / atr for value in references)
        limit = _numeric_param(params, "exhaustion_distance_atr", DEFAULT_EXHAUSTION_DISTANCE_ATR)
        if distance_atr >= limit:
            score += 0.25
            reasons.append(f"Price is {distance_atr:.2f} ATR from nearest VWAP/EMA reference")

    body_atr = abs(features.close - features.open) / atr if atr > 0 else 0.0
    if body_atr >= _numeric_param(params, "impulse_body_atr", DEFAULT_IMPULSE_BODY_ATR):
        directional_body = (direction == "LONG" and features.close > features.open) or (
            direction == "SHORT" and features.close < features.open
        )
        if directional_body:
            score += 0.15
            reasons.append(f"Current impulse body is {body_atr:.2f} ATR")

    impulse_count = _optional_int_param(params, "consecutive_impulse_candles")
    if impulse_count is not None and impulse_count >= DEFAULT_CONSECUTIVE_IMPULSE_CANDLES:
        score += 0.20
        reasons.append(f"{impulse_count} consecutive impulse candles before continuation")

    volume_climax = _numeric_param(params, "volume_climax_spike", DEFAULT_VOLUME_CLIMAX_SPIKE)
    if features.volume_spike >= volume_climax:
        score += 0.20
        reasons.append(f"Volume climax: {features.volume_spike:.2f}x average")

    if alpha_context is not None:
        if direction == "LONG" and alpha_context.delta_divergence == "bearish_divergence":
            score += 0.20
            reasons.append("Bearish CVD/price divergence against long continuation")
        if direction == "SHORT" and alpha_context.delta_divergence == "bullish_divergence":
            score += 0.20
            reasons.append("Bullish CVD/price divergence against short continuation")
        new_high = features.previous_high is not None and features.high > features.previous_high
        new_low = features.previous_low is not None and features.low < features.previous_low
        if direction == "LONG" and new_high and _delta_declines(alpha_context):
            score += 0.20
            reasons.append("Delta declines while price makes a new high")
        if direction == "SHORT" and new_low and _delta_rises(alpha_context):
            score += 0.20
            reasons.append("Delta rises while price makes a new low")

    if crowding.funding_extreme:
        score += 0.15
    if crowding.crowded_oi:
        score += 0.15
    return ExhaustionAssessment(
        score=round(max(0.0, min(1.0, score)), 4),
        reasons=tuple(reasons),
        max_score=max_score,
    )


def _delta_declines(alpha_context: AlphaMarketContext) -> bool:
    return bool(
        (alpha_context.cvd_change is not None and alpha_context.cvd_change <= 0)
        or (alpha_context.aggressive_delta is not None and alpha_context.aggressive_delta <= 0)
    )


def _delta_rises(alpha_context: AlphaMarketContext) -> bool:
    return bool(
        (alpha_context.cvd_change is not None and alpha_context.cvd_change >= 0)
        or (alpha_context.aggressive_delta is not None and alpha_context.aggressive_delta >= 0)
    )


def _htf_target_assessment(
    *,
    features: Features,
    direction: Literal["LONG", "SHORT"],
    params: Mapping[str, Any],
    alpha_context: AlphaMarketContext | None,
    support_resistance: SupportResistanceSnapshot | None,
    entry: float,
    stop_loss: float,
) -> HtfTargetAssessment:
    min_distance = _numeric_param(params, "min_htf_target_distance_r", DEFAULT_MIN_HTF_TARGET_DISTANCE_R)
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return HtfTargetAssessment(None, None, None, False, min_distance)
    candidates: list[tuple[str, float | None]] = []
    if direction == "LONG":
        candidates.extend(
            [
                ("previous_high", features.previous_high),
                ("swing_high", features.swing_high),
                ("session_high", features.session_high),
                ("previous_day_high", features.previous_day_high),
                ("donchian_high_20", features.donchian_high_20),
            ]
        )
        pool_side = "above"
    else:
        candidates.extend(
            [
                ("previous_low", features.previous_low),
                ("swing_low", features.swing_low),
                ("session_low", features.session_low),
                ("previous_day_low", features.previous_day_low),
                ("donchian_low_20", features.donchian_low_20),
            ]
        )
        pool_side = "below"
    if alpha_context is not None:
        for pool in alpha_context.session_liquidity_pools:
            if pool.side == pool_side:
                candidates.append((f"liquidity_pool_{pool.name}", pool.price))
    if support_resistance is not None:
        level = support_resistance.nearest_obstacle(
            direction=direction,
            entry=entry,
            min_strength=0.0,
        )
        if level is not None:
            candidates.append((f"htf_{support_resistance.timeframe}_{level.kind}", level.price))
    directional = _directional_targets(direction, entry, tuple(candidates))
    if not directional:
        return HtfTargetAssessment(None, None, None, False, min_distance)
    source, price = directional[0]
    distance_r = _target_reward(direction, entry, price) / risk
    return HtfTargetAssessment(
        price=price,
        source=source,
        distance_r=round(distance_r, 4),
        too_close=min_distance > 0 and distance_r < min_distance,
        min_distance_r=min_distance,
    )


def _zone_metadata(zone: StructuralPullbackZone | None) -> dict[str, Any] | None:
    if zone is None:
        return None
    return {
        "source": zone.source,
        "price": zone.price,
        "distance_atr": zone.distance_atr,
        "quality_score": zone.quality_score,
        "metadata": dict(zone.metadata),
    }


def _entry_source(setup: _TrendPullbackState) -> str:
    if setup.entry_model == "chase":
        return "trigger_close"
    if setup.structural_zone is None:
        return "ema20_ema50_pullback_zone"
    if setup.structural_zone.source in {"ema20", "ema50"}:
        return "ema20_ema50_pullback_zone"
    return f"{setup.structural_zone.source}_pullback_zone"


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
