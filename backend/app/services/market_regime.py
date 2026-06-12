from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.schemas.market import AlphaMarketContext, Features
from app.schemas.signal import (
    MarketRegimeCandidate,
    MarketRegimeLabel,
    MarketRegimeSnapshot,
    SignalLayerCheck,
    StrategySignal,
)


DEFAULT_MAJOR_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
BASE_LABELS: tuple[MarketRegimeLabel, ...] = ("trend_up", "trend_down", "range", "chop")
VOLATILITY_LABELS: tuple[MarketRegimeLabel, ...] = (
    "volatility_compression",
    "volatility_expansion",
    "post_impulse",
)
EVENT_LABELS: tuple[MarketRegimeLabel, ...] = (
    "liquidity_sweep_zone",
    "news_pump",
    "liquidity_vacuum",
    "market_wide_risk_off",
)
ALL_LABELS: tuple[MarketRegimeLabel, ...] = (
    "trend_up",
    "trend_down",
    "range",
    "chop",
    "volatility_compression",
    "volatility_expansion",
    "post_impulse",
    "liquidity_sweep_zone",
    "news_pump",
    "liquidity_vacuum",
    "market_wide_risk_off",
    "unknown",
)
PRIMARY_PRIORITY: tuple[MarketRegimeLabel, ...] = (
    "market_wide_risk_off",
    "liquidity_vacuum",
    "news_pump",
    "post_impulse",
    "liquidity_sweep_zone",
    "volatility_expansion",
    "volatility_compression",
    "chop",
    "range",
    "trend_up",
    "trend_down",
    "unknown",
)
TREND_STRATEGIES = {"trend_pullback_continuation"}


@dataclass(frozen=True)
class MarketQualityInput:
    volume_24h_quote: float | None = None
    spread_bps: float | None = None
    source: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketWideRegimeContext:
    exchange: str
    timeframe: str
    majors: Mapping[str, Features] = field(default_factory=dict)
    major_symbols: tuple[str, ...] = DEFAULT_MAJOR_SYMBOLS
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: tuple[str, ...] = ()

    @property
    def available_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.majors))

    @property
    def sufficient_data(self) -> bool:
        return len(self.majors) >= 2


class MarketRegimeContextStore:
    def __init__(self, major_symbols: tuple[str, ...] = DEFAULT_MAJOR_SYMBOLS) -> None:
        self._major_symbols = tuple(symbol.upper() for symbol in major_symbols)
        self._features: dict[tuple[str, str, str], Features] = {}

    def update_features(self, features: Features) -> None:
        self._features[_feature_key(features.exchange, features.symbol, features.timeframe)] = features

    def market_wide_context(self, exchange: str, timeframe: str) -> MarketWideRegimeContext:
        normalized_exchange = exchange.strip().lower()
        normalized_timeframe = timeframe.strip()
        majors: dict[str, Features] = {}
        for symbol in self._major_symbols:
            features = self._features.get((normalized_exchange, symbol, normalized_timeframe))
            if features is not None:
                majors[symbol] = features
        warnings: list[str] = []
        if len(majors) < 2:
            warnings.append("market_wide_context_insufficient_major_symbols")
        return MarketWideRegimeContext(
            exchange=normalized_exchange,
            timeframe=normalized_timeframe,
            majors=majors,
            major_symbols=self._major_symbols,
            warnings=tuple(warnings),
        )


class MarketRegimeService:
    def evaluate_for_signal(
        self,
        *,
        signal: StrategySignal,
        signal_features: Features,
        context_features: Features | None = None,
        context_features_by_timeframe: Mapping[str, Features] | None = None,
        alpha_context: AlphaMarketContext | None = None,
        market_quality: MarketQualityInput | None = None,
        market_wide_context: MarketWideRegimeContext | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> MarketRegimeSnapshot:
        snapshot = self.classify(
            features=signal_features,
            context_features=context_features,
            alpha_context=alpha_context,
            market_quality=market_quality,
            market_wide_context=market_wide_context,
            settings=settings,
        )
        alignment = _alignment(signal.direction.lower(), snapshot.direction)
        signal_aligned_snapshot = snapshot.model_copy(update={"alignment": alignment})
        adjustment = _score_adjustment(signal, signal_aligned_snapshot, settings or {})
        compatibility = _strategy_regime_compatibility_check(
            signal=signal,
            snapshot=snapshot,
            alignment=alignment,
            settings=settings or {},
        )
        checks = [
            *_without_check(snapshot.checks, "strategy_regime_compatibility"),
            SignalLayerCheck(
                name="regime_alignment",
                status="warning" if alignment == "against" else "passed",
                reason=(
                    f"{signal.direction.lower()} vs {snapshot.direction} "
                    f"{snapshot.context_timeframe or snapshot.signal_timeframe} ({snapshot.strength})"
                ),
                metadata={
                    "primary_label": snapshot.primary_label,
                    "base_label": snapshot.base_label,
                    "alignment": alignment,
                },
            ),
            SignalLayerCheck(
                name="regime_strength",
                status="warning" if alignment == "against" and snapshot.strength == "strong" else "passed",
                reason=f"Market regime strength is {snapshot.strength}",
                metadata={"strength": snapshot.strength, "confidence": snapshot.confidence},
            ),
            compatibility,
        ]
        compatibility_metadata = {**compatibility.metadata, "status": compatibility.status, "reason": compatibility.reason}
        return snapshot.model_copy(
            update={
                "alignment": alignment,
                "score_adjustment": adjustment,
                "checks": checks,
                "compatibility": compatibility_metadata,
                "regime_key": f"{snapshot.primary_label}:{snapshot.strength}:{alignment}",
            }
        )

    def classify(
        self,
        *,
        features: Features,
        context_features: Features | None = None,
        alpha_context: AlphaMarketContext | None = None,
        market_quality: MarketQualityInput | None = None,
        market_wide_context: MarketWideRegimeContext | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> MarketRegimeSnapshot:
        settings_map = dict(settings or {})
        regime_features = context_features or features
        candidates = self._candidates(
            features=features,
            regime_features=regime_features,
            alpha_context=alpha_context,
            market_quality=market_quality,
            market_wide_context=market_wide_context,
            settings=settings_map,
        )
        by_label = {candidate.label: candidate for candidate in candidates}
        labels = [label for label in PRIMARY_PRIORITY if by_label[label].detected and label != "unknown"]
        if not labels:
            labels = ["unknown"]
        primary_label = labels[0]
        base_label = _detected_label_by_score(by_label, ("chop", "range", "trend_up", "trend_down"))
        volatility_label = _first_detected(by_label, ("post_impulse", "volatility_expansion", "volatility_compression"))
        event_labels = [label for label in EVENT_LABELS if by_label[label].detected]
        primary_candidate = by_label[primary_label]
        direction = _direction_from_base_label(base_label)
        strength = _strength(
            label=primary_label,
            score=primary_candidate.score,
            confidence=primary_candidate.confidence,
            features=regime_features,
        )
        volatility_state = _volatility_state(volatility_label)
        structure_state = _structure_state(base_label)
        regime_type = _legacy_regime_type(primary_label, base_label, volatility_label)
        checks = self._checks(
            features=features,
            candidates=candidates,
            market_wide_context=market_wide_context,
        )
        confidence = 0.0 if primary_label == "unknown" else primary_candidate.confidence
        metadata = _classification_metadata(
            features=features,
            regime_features=regime_features,
            market_quality=market_quality,
            alpha_context=alpha_context,
            market_wide_context=market_wide_context,
        )
        if volatility_label != "unknown":
            metadata.update(by_label[volatility_label].metadata)
        metadata["primary_candidate"] = primary_candidate.model_dump(mode="json")
        return MarketRegimeSnapshot(
            signal_timeframe=features.timeframe,
            context_timeframe=context_features.timeframe if context_features is not None else None,
            direction=direction,
            strength=strength,
            alignment="unknown",
            regime_type=regime_type,
            volatility_state=volatility_state,
            structure_state=structure_state,
            compatibility={},
            score_adjustment=_base_score_adjustment(primary_label),
            checks=checks,
            primary_label=primary_label,
            labels=labels,
            base_label=base_label,
            volatility_label=volatility_label,
            event_labels=event_labels,
            confidence=round(confidence, 4),
            candidates=candidates,
            regime_key=f"{primary_label}:{strength}:unknown",
            metadata=metadata,
        )

    def _candidates(
        self,
        *,
        features: Features,
        regime_features: Features,
        alpha_context: AlphaMarketContext | None,
        market_quality: MarketQualityInput | None,
        market_wide_context: MarketWideRegimeContext | None,
        settings: Mapping[str, Any],
    ) -> list[MarketRegimeCandidate]:
        if features.history_length < int(_setting(settings, "min_regime_history", 30)):
            return [
                _candidate(
                    label,
                    100.0 if label == "unknown" else 0.0,
                    detected=(label == "unknown"),
                    reason="Insufficient candle history for market-regime classification",
                    metadata={"history_length": features.history_length},
                )
                for label in ALL_LABELS
            ]

        scorers: dict[MarketRegimeLabel, tuple[float, str, dict[str, Any], float]] = {
            "trend_up": _score_trend_up(regime_features, settings),
            "trend_down": _score_trend_down(regime_features, settings),
            "range": _score_range(regime_features, settings),
            "chop": _score_chop(regime_features, settings),
            "volatility_compression": _score_volatility_compression(features, settings),
            "volatility_expansion": _score_volatility_expansion(features, alpha_context, settings),
            "post_impulse": _score_post_impulse(features, settings),
            "liquidity_sweep_zone": _score_liquidity_sweep_zone(features, alpha_context, settings),
            "news_pump": _score_news_pump(features, alpha_context, market_quality, settings),
            "liquidity_vacuum": _score_liquidity_vacuum(features, alpha_context, market_quality, settings),
            "market_wide_risk_off": _score_market_wide_risk_off(market_wide_context, settings),
        }
        result: list[MarketRegimeCandidate] = []
        detected_any = False
        for label in ALL_LABELS:
            if label == "unknown":
                continue
            score, reason, metadata, detect_at = scorers[label]
            detected = score >= detect_at
            detected_any = detected_any or detected
            result.append(
                _candidate(
                    label,
                    score,
                    detected=detected,
                    reason=reason,
                    metadata={**metadata, "detect_at": detect_at},
                )
            )
        result.append(
            _candidate(
                "unknown",
                100.0 if not detected_any else 0.0,
                detected=not detected_any,
                reason="No market-regime candidate crossed its detection threshold",
                metadata={"detected_any": detected_any},
            )
        )
        return result

    def _checks(
        self,
        *,
        features: Features,
        candidates: list[MarketRegimeCandidate],
        market_wide_context: MarketWideRegimeContext | None,
    ) -> list[SignalLayerCheck]:
        checks: list[SignalLayerCheck] = [
            SignalLayerCheck(
                name="market_regime_history",
                status="passed" if features.history_length >= 50 else "warning",
                score=features.history_length,
                reason=f"{features.history_length} candles available for market-regime classification",
            )
        ]
        for candidate in candidates:
            if candidate.label == "unknown":
                continue
            status = "passed" if candidate.detected else "skipped"
            if candidate.label in EVENT_LABELS and candidate.detected:
                status = "failed" if candidate.label in {"liquidity_vacuum", "news_pump"} else "warning"
            checks.append(
                SignalLayerCheck(
                    name=candidate.label,
                    status=status,
                    score=round(candidate.score, 3),
                    reason=candidate.reason,
                    metadata={
                        **dict(candidate.metadata),
                        "confidence": candidate.confidence,
                        "detected": candidate.detected,
                    },
                )
            )
        checks.append(_ema200_chop_check(features))
        if market_wide_context is None or not market_wide_context.sufficient_data:
            available = 0 if market_wide_context is None else len(market_wide_context.majors)
            checks.append(
                SignalLayerCheck(
                    name="market_wide_risk_off_context",
                    status="skipped",
                    reason="Not enough major-symbol context for market-wide risk-off classification",
                    metadata={"available_major_symbols": available, "required_major_symbols": 2},
                )
            )
        return checks


def _score_trend_up(features: Features, settings: Mapping[str, Any]) -> tuple[float, str, dict[str, Any], float]:
    trend_adx_min = float(_setting(settings, "trend_adx_min", 22.0))
    score = 0.0
    checks: dict[str, bool | None] = {}
    checks["close_above_ema200"] = _above(features.close, features.ema_200)
    checks["ema_stack"] = _ordered(features.ema_20, features.ema_50, features.ema_200, descending=True)
    checks["close_above_ema50"] = _above(features.close, features.ema_50)
    checks["adx_trend"] = features.adx is not None and features.adx >= trend_adx_min
    checks["adx_rising"] = bool(features.adx_rising or (features.adx_slope_5 is not None and features.adx_slope_5 > 0))
    checks["close_above_vwap"] = True if features.vwap is None else features.close > features.vwap
    score += 20 if checks["close_above_ema200"] else 0
    score += 25 if checks["ema_stack"] else 0
    score += 15 if checks["close_above_ema50"] else 0
    score += 20 if checks["adx_trend"] else 0
    score += 10 if checks["adx_rising"] else 0
    score += 10 if checks["close_above_vwap"] else 0
    return score, "Bullish trend evidence from EMA stack, ADX, and VWAP context", checks, float(
        _setting(settings, "trend_detect_score", 65.0)
    )


def _score_trend_down(features: Features, settings: Mapping[str, Any]) -> tuple[float, str, dict[str, Any], float]:
    trend_adx_min = float(_setting(settings, "trend_adx_min", 22.0))
    score = 0.0
    checks: dict[str, bool | None] = {}
    checks["close_below_ema200"] = _below(features.close, features.ema_200)
    checks["ema_stack"] = _ordered(features.ema_20, features.ema_50, features.ema_200, descending=False)
    checks["close_below_ema50"] = _below(features.close, features.ema_50)
    checks["adx_trend"] = features.adx is not None and features.adx >= trend_adx_min
    checks["adx_rising"] = bool(features.adx_rising or (features.adx_slope_5 is not None and features.adx_slope_5 < 0))
    checks["close_below_vwap"] = True if features.vwap is None else features.close < features.vwap
    score += 20 if checks["close_below_ema200"] else 0
    score += 25 if checks["ema_stack"] else 0
    score += 15 if checks["close_below_ema50"] else 0
    score += 20 if checks["adx_trend"] else 0
    score += 10 if checks["adx_rising"] else 0
    score += 10 if checks["close_below_vwap"] else 0
    return score, "Bearish trend evidence from EMA stack, ADX, and VWAP context", checks, float(
        _setting(settings, "trend_detect_score", 65.0)
    )


def _score_range(features: Features, settings: Mapping[str, Any]) -> tuple[float, str, dict[str, Any], float]:
    range_adx_max = float(_setting(settings, "range_adx_max", 18.0))
    compression_threshold = float(_setting(settings, "compression_bb_width_percentile", 15.0))
    inside_donchian = _inside(features.close, features.donchian_low_20, features.donchian_high_20)
    normal_bb = (
        features.bb_width_percentile is not None
        and compression_threshold < features.bb_width_percentile <= float(_setting(settings, "range_bb_width_upper", 75.0))
    )
    readable_range = features.range_20_atr is not None and 1.0 <= features.range_20_atr <= 5.5
    swing_touches = features.swing_high_touch_count + features.swing_low_touch_count >= 2
    checks = {
        "low_adx": features.adx is not None and features.adx <= range_adx_max,
        "inside_donchian": inside_donchian,
        "normal_bb_width": normal_bb,
        "swing_touches": swing_touches,
        "readable_range_atr": readable_range,
    }
    score = (
        (25 if checks["low_adx"] else 0)
        + (25 if checks["inside_donchian"] else 0)
        + (20 if checks["normal_bb_width"] else 0)
        + (10 if checks["swing_touches"] else 0)
        + (20 if checks["readable_range_atr"] else 0)
    )
    if not checks["low_adx"]:
        score = min(score, 55.0)
    return score, "Range evidence from low ADX, Donchian containment, and readable width", checks, float(
        _setting(settings, "range_detect_score", 60.0)
    )


def _score_chop(features: Features, settings: Mapping[str, Any]) -> tuple[float, str, dict[str, Any], float]:
    chop_score = features.ema_200_chop_score or 0.0
    cross_count = features.ema_200_cross_count_50 or 0
    near_ratio = features.ema_200_near_ratio_50 or 0.0
    wick_noise = (features.upper_wick_ratio or 0.0) + (features.lower_wick_ratio or 0.0)
    low_adx = features.adx is not None and features.adx <= 18
    score = min(50.0, chop_score * 0.7)
    score += min(25.0, cross_count * 7.5)
    score += 15.0 if near_ratio >= 0.35 else 0.0
    score += 10.0 if low_adx else 0.0
    score += 10.0 if wick_noise >= 0.75 else 0.0
    metadata = {
        "ema_200_chop_score": features.ema_200_chop_score,
        "ema_200_cross_count_50": cross_count,
        "ema_200_near_ratio_50": features.ema_200_near_ratio_50,
        "wick_noise": wick_noise,
        "low_adx": low_adx,
        "severe": chop_score >= 70 or cross_count >= 4,
    }
    return score, "Chop evidence from EMA200 crossings, near-ratio, ADX, and candle noise", metadata, float(
        _setting(settings, "chop_detect_score", 55.0)
    )


def _score_volatility_compression(features: Features, settings: Mapping[str, Any]) -> tuple[float, str, dict[str, Any], float]:
    bb_threshold = float(_setting(settings, "compression_bb_width_percentile", 20.0))
    atr_ratio_threshold = float(_setting(settings, "compression_atr_ratio", 0.75))
    range_multiplier = float(_setting(settings, "compression_range_contraction_multiplier", 0.7))
    atr_ratio = _ratio(features.atr_14, features.atr_sma_50)
    range_contracting = (
        features.range_20 is not None
        and features.range_50_average is not None
        and features.range_20 <= features.range_50_average * range_multiplier
    )
    inside_donchian = _inside(features.close, features.donchian_low_20, features.donchian_high_20)
    checks = {
        "bb_width_compressed": features.bb_width_percentile is not None and features.bb_width_percentile <= bb_threshold,
        "atr_ratio_compressed": atr_ratio is not None and atr_ratio <= atr_ratio_threshold,
        "range_contracting": range_contracting,
        "range_20_atr": features.range_20_atr,
        "volume_normal": features.volume_spike <= float(_setting(settings, "compression_max_volume_spike", 1.25)),
        "inside_donchian": inside_donchian,
        "atr_ratio": atr_ratio,
    }
    score = (
        (25 if checks["bb_width_compressed"] else 0)
        + (25 if checks["atr_ratio_compressed"] else 0)
        + (20 if checks["range_contracting"] else 0)
        + (15 if checks["volume_normal"] else 0)
        + (15 if checks["inside_donchian"] else 0)
    )
    return score, "Volatility compression evidence from BB width, ATR ratio, range contraction, and normal volume", checks, float(
        _setting(settings, "compression_detect_score", 60.0)
    )


def _score_volatility_expansion(
    features: Features,
    alpha_context: AlphaMarketContext | None,
    settings: Mapping[str, Any],
) -> tuple[float, str, dict[str, Any], float]:
    atr_ratio = _ratio(features.atr_14, features.atr_sma_50)
    body_atr, _ = _candle_atr_values(features)
    breaks_high = features.donchian_high_20 is not None and features.close > features.donchian_high_20
    breaks_low = features.donchian_low_20 is not None and features.close < features.donchian_low_20
    oi_delta = _first_number(
        getattr(alpha_context, "oi_delta_5m", None),
        getattr(alpha_context, "oi_delta_15m", None),
        features.oi_change,
    )
    delta = _first_number(getattr(alpha_context, "aggressive_delta", None), getattr(alpha_context, "cvd_change", None))
    alpha_confirms = _abs_at_least(oi_delta, 0.08) or _abs_at_least(delta, 0.4)
    checks = {
        "atr_increasing": features.atr_increasing,
        "atr_ratio": atr_ratio,
        "atr_ratio_expanded": atr_ratio is not None and atr_ratio >= float(_setting(settings, "expansion_atr_ratio", 1.35)),
        "volume_expanded": features.volume_spike >= float(_setting(settings, "expansion_volume_spike", 2.0)),
        "body_atr": body_atr,
        "body_expanded": body_atr >= float(_setting(settings, "expansion_body_atr", 1.5)),
        "donchian_break": breaks_high or breaks_low,
        "alpha_confirms": alpha_confirms,
    }
    score = (
        (20 if checks["atr_increasing"] else 0)
        + (20 if checks["atr_ratio_expanded"] else 0)
        + (20 if checks["volume_expanded"] else 0)
        + (15 if checks["body_expanded"] else 0)
        + (15 if checks["donchian_break"] else 0)
        + (10 if checks["alpha_confirms"] else 0)
    )
    return score, "Volatility expansion evidence from ATR, volume, candle body, Donchian break, and alpha confirmation", checks, float(
        _setting(settings, "expansion_detect_score", 60.0)
    )


def _score_post_impulse(features: Features, settings: Mapping[str, Any]) -> tuple[float, str, dict[str, Any], float]:
    body_atr, range_atr = _candle_atr_values(features)
    previous_body_atr = _previous_body_atr(features)
    close_location = _close_location(features)
    previous_close_location = _previous_close_location(features)
    inside_or_retest = _inside_or_retest_after_previous_impulse(features)
    volume_confirms = features.volume_spike >= float(_setting(settings, "impulse_volume_spike", 2.0)) or (
        features.previous_volume is not None and features.previous_volume >= max(features.volume, 1.0) * 1.5
    )
    current_impulse = (
        body_atr >= float(_setting(settings, "impulse_body_atr", 2.5))
        and close_location >= 0.78
        and features.volume_spike >= float(_setting(settings, "current_impulse_volume_spike", 4.0))
    )
    previous_impulse = previous_body_atr >= float(_setting(settings, "impulse_body_atr", 2.5)) and previous_close_location >= 0.75
    score = 0.0
    score += 45 if current_impulse or previous_impulse else 0
    score += 20 if max(close_location, previous_close_location) >= 0.78 else 0
    score += 20 if volume_confirms else 0
    score += 25 if previous_impulse and inside_or_retest else 0
    impulse_direction = _impulse_direction(features, previous=previous_impulse and not current_impulse)
    metadata = {
        "body_atr": body_atr,
        "range_atr": range_atr,
        "previous_body_atr": previous_body_atr,
        "close_location": close_location,
        "previous_close_location": previous_close_location,
        "current_impulse": current_impulse,
        "previous_impulse": previous_impulse,
        "inside_or_retest": inside_or_retest,
        "volume_confirms": volume_confirms,
        "impulse_direction": impulse_direction,
    }
    return score, "Post-impulse evidence from current or previous large directional candle and retest behavior", metadata, float(
        _setting(settings, "post_impulse_detect_score", 60.0)
    )


def _score_liquidity_sweep_zone(
    features: Features,
    alpha_context: AlphaMarketContext | None,
    settings: Mapping[str, Any],
) -> tuple[float, str, dict[str, Any], float]:
    if alpha_context is None:
        return (
            0.0,
            "Alpha context is unavailable for liquidity-sweep-zone classification",
            {"alpha_context_available": False},
            float(_setting(settings, "liquidity_sweep_zone_detect_score", 60.0)),
        )

    max_pool_distance_pct = float(_setting(settings, "liquidity_sweep_zone_max_pool_distance_pct", 0.012))
    min_pool_strength = float(_setting(settings, "liquidity_sweep_zone_min_pool_strength", 0.65))
    max_liquidation_proximity = float(_setting(settings, "liquidity_sweep_zone_max_liquidation_proximity", 0.35))
    range_edge_atr = float(_setting(settings, "liquidity_sweep_zone_range_edge_atr", 0.6))
    pools = list(alpha_context.session_liquidity_pools or [])
    near_pool = any(
        pool.distance_pct is not None and abs(pool.distance_pct) <= max_pool_distance_pct
        for pool in pools
    )
    strong_pool = any((pool.strength or 0.0) >= min_pool_strength for pool in pools)
    sweep_through_book = alpha_context.sweep_through_book is True
    liquidation_near = (
        alpha_context.liquidation_proximity is not None
        and alpha_context.liquidation_proximity <= max_liquidation_proximity
    )
    liquidation_clusters = bool(alpha_context.liquidation_clusters)
    atr = features.atr_14 or 0.0
    range_edge_distance = min(
        (
            abs(features.close - level)
            for level in (features.donchian_high_20, features.donchian_low_20)
            if level is not None
        ),
        default=None,
    )
    near_range_edge = (
        range_edge_distance is not None
        and atr > 0
        and range_edge_distance <= atr * range_edge_atr
    )
    score = (
        (35 if sweep_through_book else 0)
        + (25 if near_pool else 0)
        + (15 if strong_pool else 0)
        + (15 if liquidation_near else 0)
        + (10 if liquidation_clusters else 0)
        + (10 if near_range_edge else 0)
    )
    metadata = {
        "alpha_context_available": True,
        "sweep_through_book": sweep_through_book,
        "near_liquidity_pool": near_pool,
        "strong_liquidity_pool": strong_pool,
        "liquidity_pool_count": len(pools),
        "liquidation_near": liquidation_near,
        "liquidation_clusters": liquidation_clusters,
        "near_range_edge": near_range_edge,
        "range_edge_distance": range_edge_distance,
        "max_pool_distance_pct": max_pool_distance_pct,
        "min_pool_strength": min_pool_strength,
        "max_liquidation_proximity": max_liquidation_proximity,
    }
    return score, "Liquidity-sweep-zone evidence from nearby pools, book sweep, and liquidation context", metadata, float(
        _setting(settings, "liquidity_sweep_zone_detect_score", 60.0)
    )


def _score_news_pump(
    features: Features,
    alpha_context: AlphaMarketContext | None,
    market_quality: MarketQualityInput | None,
    settings: Mapping[str, Any],
) -> tuple[float, str, dict[str, Any], float]:
    body_atr, range_atr = _candle_atr_values(features)
    price_move = abs(_safe_pct_change(features.open, features.close))
    oi_or_delta_extreme = (
        _abs_at_least(features.oi_change, 0.15)
        or _abs_at_least(getattr(alpha_context, "oi_delta_5m", None), 0.12)
        or _abs_at_least(getattr(alpha_context, "funding_pressure", None), 0.05)
        or _abs_at_least(getattr(alpha_context, "aggressive_delta", None), 0.65)
    )
    spread = _number_or_none(getattr(market_quality, "spread_bps", None))
    checks = {
        "volume_spike": features.volume_spike,
        "volume_extreme": features.volume_spike >= float(_setting(settings, "news_pump_volume_spike", 5.0)),
        "body_atr": body_atr,
        "body_extreme": body_atr >= float(_setting(settings, "news_pump_body_atr", 3.5)),
        "range_atr": range_atr,
        "price_move": price_move,
        "price_move_extreme": price_move >= float(_setting(settings, "news_pump_price_move", 0.04)),
        "spread_bps": spread,
        "spread_widening": spread is not None and spread >= float(_setting(settings, "news_pump_spread_bps", 35.0)),
        "oi_or_delta_extreme": oi_or_delta_extreme,
    }
    score = (
        (30 if checks["volume_extreme"] else 0)
        + (25 if checks["body_extreme"] else 0)
        + (20 if checks["price_move_extreme"] or range_atr >= 5.0 else 0)
        + (10 if checks["spread_widening"] else 0)
        + (15 if checks["oi_or_delta_extreme"] else 0)
    )
    return score, "News/pump event-risk evidence from extreme volume, body, price move, spread, and alpha stress", checks, float(
        _setting(settings, "news_pump_detect_score", 70.0)
    )


def _score_liquidity_vacuum(
    features: Features,
    alpha_context: AlphaMarketContext | None,
    market_quality: MarketQualityInput | None,
    settings: Mapping[str, Any],
) -> tuple[float, str, dict[str, Any], float]:
    spread = _number_or_none(getattr(market_quality, "spread_bps", None))
    volume_24h = _number_or_none(getattr(market_quality, "volume_24h_quote", None))
    bid_depth = _number_or_none(getattr(alpha_context, "bid_depth_usd", None))
    ask_depth = _number_or_none(getattr(alpha_context, "ask_depth_usd", None))
    min_depth = min((value for value in (bid_depth, ask_depth) if value is not None), default=None)
    imbalance = _number_or_none(getattr(alpha_context, "orderbook_imbalance", None))
    sweep = bool(getattr(alpha_context, "sweep_through_book", False))
    checks = {
        "spread_bps": spread,
        "spread_too_high": spread is not None and spread >= float(_setting(settings, "liquidity_vacuum_spread_bps", 50.0)),
        "min_depth_usd": min_depth,
        "depth_too_low": min_depth is not None and min_depth <= float(_setting(settings, "liquidity_vacuum_depth_usd", 50_000.0)),
        "orderbook_imbalance": imbalance,
        "imbalance_extreme": _abs_at_least(imbalance, float(_setting(settings, "liquidity_vacuum_imbalance", 0.8))),
        "sweep_through_book": sweep,
        "volume_24h_quote": volume_24h,
        "volume_too_low": volume_24h is not None and volume_24h <= float(_setting(settings, "liquidity_vacuum_volume_24h", 1_000_000.0)),
    }
    score = (
        (35 if checks["spread_too_high"] else 0)
        + (20 if checks["depth_too_low"] else 0)
        + (20 if checks["imbalance_extreme"] else 0)
        + (15 if checks["sweep_through_book"] else 0)
        + (20 if checks["volume_too_low"] else 0)
    )
    return score, "Liquidity vacuum evidence from spread, book depth, imbalance, sweep, and weak 24h volume", checks, float(
        _setting(settings, "liquidity_vacuum_detect_score", 60.0)
    )


def _score_market_wide_risk_off(
    market_wide_context: MarketWideRegimeContext | None,
    settings: Mapping[str, Any],
) -> tuple[float, str, dict[str, Any], float]:
    if market_wide_context is None or len(market_wide_context.majors) < 2:
        available = 0 if market_wide_context is None else len(market_wide_context.majors)
        return 0.0, "Market-wide context is unavailable or has fewer than two major symbols", {
            "available_major_symbols": available,
            "required_major_symbols": 2,
            "skipped": True,
        }, 60.0
    down_symbols: list[str] = []
    expansion_symbols: list[str] = []
    impulse_symbols: list[str] = []
    for symbol, features in market_wide_context.majors.items():
        trend_down_score, _, _, trend_detect = _score_trend_down(features, settings)
        expansion_score, _, _, expansion_detect = _score_volatility_expansion(features, None, settings)
        impulse_score, _, _, impulse_detect = _score_post_impulse(features, settings)
        if trend_down_score >= trend_detect:
            down_symbols.append(symbol)
        if expansion_score >= expansion_detect:
            expansion_symbols.append(symbol)
        if impulse_score >= impulse_detect and features.close < features.open:
            impulse_symbols.append(symbol)
    available = len(market_wide_context.majors)
    btc_eth_down = any(symbol in down_symbols for symbol in ("BTCUSDT", "ETHUSDT"))
    score = (len(down_symbols) / available) * 70.0
    score += min(15.0, len(expansion_symbols) * 7.5)
    score += min(15.0, len(impulse_symbols) * 7.5)
    score += 15.0 if btc_eth_down and len(down_symbols) >= 2 else 0.0
    metadata = {
        "available_major_symbols": available,
        "down_symbols": down_symbols,
        "expansion_symbols": expansion_symbols,
        "impulse_symbols": impulse_symbols,
        "btc_eth_down": btc_eth_down,
    }
    return score, "Market-wide risk-off evidence from major-symbol downside trend and volatility stress", metadata, float(
        _setting(settings, "market_wide_risk_off_detect_score", 60.0)
    )


def _candidate(
    label: MarketRegimeLabel,
    score: float,
    *,
    detected: bool,
    reason: str,
    metadata: Mapping[str, Any] | None = None,
) -> MarketRegimeCandidate:
    bounded_score = _clamp(score, 0.0, 100.0)
    return MarketRegimeCandidate(
        label=label,
        score=round(bounded_score, 3),
        confidence=round(bounded_score / 100.0, 4),
        detected=detected,
        reason=reason,
        metadata=dict(metadata or {}),
    )


def _detected_label_by_score(
    by_label: Mapping[MarketRegimeLabel, MarketRegimeCandidate],
    labels: tuple[MarketRegimeLabel, ...],
) -> MarketRegimeLabel:
    detected = [by_label[label] for label in labels if by_label[label].detected]
    if not detected:
        return "unknown"
    return max(detected, key=lambda candidate: (candidate.score, -labels.index(candidate.label))).label


def _first_detected(
    by_label: Mapping[MarketRegimeLabel, MarketRegimeCandidate],
    labels: tuple[MarketRegimeLabel, ...],
) -> MarketRegimeLabel:
    for label in labels:
        if by_label[label].detected:
            return label
    return "unknown"


def _direction_from_base_label(base_label: MarketRegimeLabel) -> str:
    if base_label == "trend_up":
        return "bullish"
    if base_label == "trend_down":
        return "bearish"
    if base_label in {"range", "chop"}:
        return "range"
    return "unknown"


def _strength(*, label: MarketRegimeLabel, score: float, confidence: float, features: Features) -> str:
    if label == "unknown" or confidence <= 0.05:
        return "unknown"
    if score >= 80 or (features.adx is not None and features.adx >= 30):
        return "strong"
    if score >= 55:
        return "normal"
    return "weak"


def _volatility_state(volatility_label: MarketRegimeLabel) -> str:
    if volatility_label == "volatility_compression":
        return "compression"
    if volatility_label in {"volatility_expansion", "post_impulse"}:
        return "expansion"
    return "unknown"


def _structure_state(base_label: MarketRegimeLabel) -> str:
    if base_label in {"trend_up", "trend_down"}:
        return "trend"
    if base_label in {"range", "chop"}:
        return base_label
    return "unknown"


def _legacy_regime_type(
    primary_label: MarketRegimeLabel,
    base_label: MarketRegimeLabel,
    volatility_label: MarketRegimeLabel,
) -> str:
    if primary_label in {"market_wide_risk_off", "liquidity_vacuum", "news_pump"}:
        if volatility_label != "unknown":
            return volatility_label
        if base_label != "unknown":
            return base_label
        return "unknown"
    if primary_label != "unknown":
        return primary_label
    if volatility_label != "unknown":
        return volatility_label
    return base_label


def _base_score_adjustment(primary_label: MarketRegimeLabel) -> int:
    return {
        "news_pump": -25,
        "liquidity_vacuum": -30,
        "market_wide_risk_off": -15,
        "post_impulse": -15,
    }.get(primary_label, 0)


def _score_adjustment(
    signal: StrategySignal,
    snapshot: MarketRegimeSnapshot,
    settings: Mapping[str, Any],
) -> int:
    adjustment = 0
    labels = set(snapshot.labels)
    if signal.strategy in TREND_STRATEGIES:
        if snapshot.alignment == "aligned" and snapshot.base_label in {"trend_up", "trend_down"}:
            adjustment += 10
        if snapshot.alignment == "against" and snapshot.strength == "strong":
            adjustment -= 25
        if "chop" in labels:
            adjustment -= 15
        if "range" in labels:
            adjustment -= 10
    else:
        if snapshot.alignment == "aligned" and snapshot.strength == "strong":
            adjustment += 8
        elif snapshot.alignment == "aligned":
            adjustment += 5
        elif snapshot.alignment == "against" and snapshot.strength == "strong":
            adjustment -= 25
        elif snapshot.alignment == "against":
            adjustment -= 12
    if signal.strategy == "volatility_squeeze_breakout":
        if "volatility_compression" in labels:
            adjustment += 10
        if "volatility_expansion" in labels:
            adjustment += 8
    if "post_impulse" in labels:
        adjustment -= 15
    if "news_pump" in labels:
        adjustment -= 25
    if "liquidity_vacuum" in labels:
        adjustment -= 30
    if "market_wide_risk_off" in labels and signal.direction.upper() == "LONG":
        if not _bool_setting(settings, "allow_long_in_market_wide_risk_off", False):
            adjustment -= 30
    return int(_clamp(adjustment, -75, 25))


def _strategy_regime_compatibility_check(
    *,
    signal: StrategySignal,
    snapshot: MarketRegimeSnapshot,
    alignment: str,
    settings: Mapping[str, Any],
) -> SignalLayerCheck:
    status = "passed"
    compatible = True
    reason_code = "strategy_regime_compatible"
    reason = "Strategy is compatible with the current market regime."
    labels = set(snapshot.labels)

    if "liquidity_vacuum" in labels:
        status = "failed"
        compatible = False
        reason_code = "liquidity_vacuum"
        reason = "Liquidity vacuum blocks fresh entries."
    elif "news_pump" in labels and not _bool_setting(settings, "allow_news_pump_mode", False):
        status = "failed"
        compatible = False
        reason_code = "news_pump_mode"
        reason = "News/pump mode blocks fresh entries."
    elif signal.strategy == "trend_pullback_continuation":
        if snapshot.base_label == "chop" or snapshot.structure_state == "chop":
            status = "failed"
            compatible = False
            reason_code = "strategy_regime_incompatible"
            reason = "Trend pullback is blocked in chop."
        elif snapshot.base_label == "range" and not _bool_setting(settings, "allow_range_pullback", False):
            status = "failed"
            compatible = False
            reason_code = "strategy_regime_incompatible"
            reason = "Trend pullback is blocked in range without allow_range_pullback=true."
        elif alignment == "against" and snapshot.strength == "strong":
            status = "failed"
            compatible = False
            reason_code = "strategy_regime_incompatible"
            reason = "Trend pullback is blocked against a strong higher-timeframe trend."
        elif not _trend_pullback_regime_matches(signal.direction.lower(), snapshot.regime_type, snapshot.direction):
            status = "warning"
            reason_code = "strategy_regime_watchlist"
            reason = "Trend pullback is waiting for clearer trend alignment."
    elif signal.strategy == "liquidity_sweep_reversal":
        if alignment == "against" and snapshot.strength == "strong":
            if _liquidity_sweep_strong_trend_requirements_met(signal):
                reason = "Liquidity sweep has absorption and reclaim evidence against the strong trend."
            else:
                status = "failed"
                compatible = False
                reason_code = "strategy_regime_incompatible"
                reason = "Liquidity sweep against a strong trend requires absorption and reclaim evidence."
        elif snapshot.base_label != "range":
            status = "warning"
            reason_code = "strategy_regime_watchlist"
            reason = "Liquidity sweep works best in range or liquidity-sweep-zone regimes."
    elif signal.strategy == "volatility_squeeze_breakout":
        if "post_impulse" in labels and not _breakout_retest_evidence_present(signal):
            status = "warning"
            reason_code = "strategy_regime_post_impulse_retest"
            reason = "Post-impulse breakout requires a retest before execution."
        elif "volatility_compression" not in labels and not _has_compression_evidence(snapshot):
            status = "failed"
            compatible = False
            reason_code = "strategy_regime_incompatible"
            reason = "Volatility squeeze breakout requires prior compression."

    metadata = {
        "reason_code": reason_code,
        "compatible": compatible,
        "strategy": signal.strategy,
        "direction": signal.direction.lower(),
        "regime_type": snapshot.regime_type,
        "primary_label": snapshot.primary_label,
        "labels": list(snapshot.labels),
        "base_label": snapshot.base_label,
        "volatility_label": snapshot.volatility_label,
        "event_labels": list(snapshot.event_labels),
        "volatility_state": snapshot.volatility_state,
        "structure_state": snapshot.structure_state,
        "trend_direction": snapshot.direction,
        "trend_strength": snapshot.strength,
        "alignment": alignment,
    }
    metadata[signal.strategy] = {
        "allowed": status != "failed",
        "compatible": compatible,
        "severity": "blocker" if status == "failed" else "warning" if status == "warning" else "info",
        "reason_code": reason_code,
        "reason": reason,
        "status": status,
        "strategy": signal.strategy,
    }
    return SignalLayerCheck(
        name="strategy_regime_compatibility",
        status=status,
        reason=reason,
        metadata=metadata,
    )


def _has_compression_evidence(snapshot: MarketRegimeSnapshot) -> bool:
    for candidate in snapshot.candidates:
        if candidate.label != "volatility_compression":
            continue
        metadata = candidate.metadata
        return bool(
            metadata.get("bb_width_compressed")
            or metadata.get("range_contracting")
            or (
                _number_or_none(metadata.get("range_20_atr")) is not None
                and (_number_or_none(metadata.get("range_20_atr")) or 999.0) <= 3.0
            )
        )
    return False


def _ema200_chop_check(features: Features) -> SignalLayerCheck:
    score = features.ema_200_chop_score
    if score is None:
        return SignalLayerCheck(
            name="ema200_chop",
            status="skipped",
            reason="EMA200 chop metrics are unavailable",
        )
    severe = score >= 70 or features.ema_200_cross_count_50 >= 4
    borderline = score >= 45 or features.ema_200_cross_count_50 >= 3
    status = "failed" if severe else "warning" if borderline else "passed"
    return SignalLayerCheck(
        name="ema200_chop",
        status=status,
        score=round(score, 3),
        reason=(
            f"EMA200 chop score {score:.1f}: {features.ema_200_cross_count_50} crosses in 50 candles, "
            f"near-ratio {_format_optional_ratio(features.ema_200_near_ratio_50)}, "
            f"slope {_format_optional_float(features.ema_200_slope_atr_20)} ATR"
        ),
        metadata={
            "cross_count_50": features.ema_200_cross_count_50,
            "near_ratio_50": features.ema_200_near_ratio_50,
            "slope_atr_20": features.ema_200_slope_atr_20,
            "chop_score": score,
            "severe": severe,
            "borderline": borderline,
        },
    )


def _classification_metadata(
    *,
    features: Features,
    regime_features: Features,
    market_quality: MarketQualityInput | None,
    alpha_context: AlphaMarketContext | None,
    market_wide_context: MarketWideRegimeContext | None,
) -> dict[str, Any]:
    atr_ratio = _ratio(features.atr_14, features.atr_sma_50)
    body_atr, range_atr = _candle_atr_values(features)
    return {
        "exchange": features.exchange,
        "symbol": features.symbol,
        "signal_timeframe": features.timeframe,
        "context_timeframe": regime_features.timeframe if regime_features is not features else None,
        "close": features.close,
        "ema_20": regime_features.ema_20,
        "ema_50": regime_features.ema_50,
        "ema_200": regime_features.ema_200,
        "adx": regime_features.adx,
        "atr_ratio": atr_ratio,
        "body_atr": body_atr,
        "range_atr": range_atr,
        "volume_spike": features.volume_spike,
        "spread_bps": getattr(market_quality, "spread_bps", None),
        "volume_24h_quote": getattr(market_quality, "volume_24h_quote", None),
        "alpha_available": alpha_context is not None,
        "market_wide_available_symbols": [] if market_wide_context is None else list(market_wide_context.available_symbols),
    }


def _without_check(checks: list[SignalLayerCheck], name: str) -> list[SignalLayerCheck]:
    return [check for check in checks if check.name != name]


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


def _trend_pullback_regime_matches(side: str, regime_type: str, direction: str) -> bool:
    return (
        (side == "long" and (regime_type == "trend_up" or direction == "bullish"))
        or (side == "short" and (regime_type == "trend_down" or direction == "bearish"))
    )


def _liquidity_sweep_strong_trend_requirements_met(signal: StrategySignal) -> bool:
    absorption_score = _trade_plan_metadata_number(signal, "absorption_score") or 0.0
    reclaim_score = _trade_plan_metadata_number(signal, "reclaim_score") or 0.0
    confirmation = bool(_trade_plan_metadata_bool(signal, "confirmation"))
    return absorption_score >= 0.5 and (confirmation or reclaim_score >= 0.5)


def _breakout_retest_evidence_present(signal: StrategySignal) -> bool:
    post_hold_score = _trade_plan_metadata_number(signal, "post_breakout_hold_score") or 0.0
    retest_quality_score = _trade_plan_metadata_number(signal, "retest_quality_score") or 0.0
    return max(post_hold_score, retest_quality_score) >= 0.65


def _trade_plan_metadata_number(signal: StrategySignal, key: str) -> float | None:
    value = _trade_plan_metadata_value(signal, key)
    return _number_or_none(value)


def _trade_plan_metadata_bool(signal: StrategySignal, key: str) -> bool | None:
    value = _trade_plan_metadata_value(signal, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else None


def _trade_plan_metadata_value(signal: StrategySignal, key: str) -> Any:
    trade_plan = signal.trade_plan
    if trade_plan is None:
        return None
    containers = [
        getattr(trade_plan, "metadata", {}),
        getattr(getattr(trade_plan, "entry", None), "metadata", {}),
        getattr(getattr(trade_plan, "risk_rules", None), "metadata", {}),
    ]
    for container in containers:
        if isinstance(container, Mapping) and key in container:
            return container[key]
    return None


def _candle_atr_values(features: Features) -> tuple[float, float]:
    atr = features.atr_14
    if atr is None or atr <= 0:
        return 0.0, 0.0
    body = abs(features.close - features.open)
    candle_range = max(features.high - features.low, 0.0)
    return body / atr, candle_range / atr


def _previous_body_atr(features: Features) -> float:
    if features.atr_14 is None or features.atr_14 <= 0:
        return 0.0
    if features.previous_open is None or features.previous_close is None:
        return 0.0
    return abs(features.previous_close - features.previous_open) / features.atr_14


def _close_location(features: Features) -> float:
    candle_range = max(features.high - features.low, 0.0)
    if candle_range <= 0:
        return 0.0
    if features.close >= features.open:
        return (features.close - features.low) / candle_range
    return (features.high - features.close) / candle_range


def _previous_close_location(features: Features) -> float:
    if features.previous_high is None or features.previous_low is None or features.previous_close is None:
        return 0.0
    candle_range = max(features.previous_high - features.previous_low, 0.0)
    if candle_range <= 0:
        return 0.0
    previous_open = features.previous_open if features.previous_open is not None else features.previous_close
    if features.previous_close >= previous_open:
        return (features.previous_close - features.previous_low) / candle_range
    return (features.previous_high - features.previous_close) / candle_range


def _inside_or_retest_after_previous_impulse(features: Features) -> bool:
    if features.previous_high is None or features.previous_low is None:
        return False
    current_range = max(features.high - features.low, 0.0)
    previous_range = max(features.previous_high - features.previous_low, 0.0)
    current_inside = features.high <= features.previous_high and features.low >= features.previous_low
    smaller = current_range <= previous_range * 0.6 if previous_range > 0 else False
    retesting = features.low <= features.previous_close <= features.high if features.previous_close is not None else False
    return current_inside or smaller or retesting


def _impulse_direction(features: Features, *, previous: bool) -> str | None:
    if previous and features.previous_open is not None and features.previous_close is not None:
        return "up" if features.previous_close >= features.previous_open else "down"
    if features.close == features.open:
        return None
    return "up" if features.close > features.open else "down"


def _ordered(a: float | None, b: float | None, c: float | None, *, descending: bool) -> bool:
    if a is None or b is None or c is None:
        return False
    return a >= b >= c if descending else a <= b <= c


def _above(value: float | None, threshold: float | None) -> bool:
    return value is not None and threshold is not None and value > threshold


def _below(value: float | None, threshold: float | None) -> bool:
    return value is not None and threshold is not None and value < threshold


def _inside(value: float, low: float | None, high: float | None) -> bool:
    if low is None or high is None:
        return False
    return min(low, high) <= value <= max(low, high)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _safe_pct_change(open_price: float, close_price: float) -> float:
    if open_price == 0:
        return 0.0
    return (close_price - open_price) / abs(open_price)


def _abs_at_least(value: Any, threshold: float) -> bool:
    number = _number_or_none(value)
    return number is not None and abs(number) >= threshold


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number_or_none(value)
        if number is not None:
            return number
    return None


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _setting(settings: Mapping[str, Any], key: str, default: float) -> Any:
    return settings.get(key, default)


def _bool_setting(settings: Mapping[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _feature_key(exchange: str, symbol: str, timeframe: str) -> tuple[str, str, str]:
    return (exchange.strip().lower(), symbol.strip().upper(), timeframe.strip())


def _format_optional_ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _format_optional_float(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


market_regime_service = MarketRegimeService()
market_regime_context_store = MarketRegimeContextStore()
