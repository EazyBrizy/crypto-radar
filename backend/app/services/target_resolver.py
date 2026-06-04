from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence, cast

from app.schemas.market import AlphaMarketContext, Features, LiquidityPoolFeatures
from app.schemas.trade_plan import TargetSource, TargetThesis
from app.services.risk_reward_plan import risk_reward_plan_service
from app.services.support_resistance import SupportResistanceSnapshot


MARKET_TARGET_SOURCES: set[TargetSource] = {
    "nearest_liquidity_pool",
    "previous_day_high",
    "previous_day_low",
    "session_high",
    "session_low",
    "range_midpoint",
    "range_opposite_boundary",
    "vwap",
    "vwap_deviation_band",
    "htf_support",
    "htf_resistance",
    "measured_move",
}
TargetDirection = Literal["LONG", "SHORT"]


class TargetResolverService:
    """Resolves market-explained target theses from already available context."""

    def resolve(
        self,
        *,
        direction: str,
        entry: float | None,
        stop_loss: float | None,
        features: Features,
        alpha_context: AlphaMarketContext | None = None,
        support_resistance_by_timeframe: Mapping[str, SupportResistanceSnapshot] | None = None,
        strategy_metadata: Mapping[str, Any] | None = None,
        allow_r_multiple_fallback: bool = False,
    ) -> list[TargetThesis]:
        normalized_direction = _normalize_direction(direction)
        if normalized_direction is None or entry is None or entry <= 0:
            return []

        metadata = dict(strategy_metadata or {})
        candidates: list[TargetThesis] = []
        candidates.extend(_liquidity_pool_targets(normalized_direction, entry, alpha_context))
        candidates.extend(_feature_level_targets(normalized_direction, entry, features))
        candidates.extend(
            _support_resistance_targets(
                normalized_direction,
                entry,
                support_resistance_by_timeframe or {},
            )
        )
        measured_move = _measured_move_price(
            normalized_direction,
            entry,
            features,
            metadata,
        )
        if measured_move is not None:
            candidates.append(
                _target_thesis(
                    source="measured_move",
                    price=measured_move,
                    direction=normalized_direction,
                    confidence=0.72,
                    priority=85,
                    close_percent=None,
                    requires_acceptance=True,
                    invalidation_hint="Acceptance fails back inside the originating range",
                    metadata={"source": "donchian_range", "requires_accepted_breakout": True},
                )
            )

        ordered = _dedupe_and_order(
            [
                _with_distance_metadata(
                    thesis,
                    direction=normalized_direction,
                    entry=entry,
                    stop_loss=stop_loss,
                )
                for thesis in candidates
                if _target_is_directional(normalized_direction, entry, thesis.price)
            ]
        )
        if ordered:
            return ordered
        if allow_r_multiple_fallback:
            return _risk_multiple_fallback_targets(
                direction=normalized_direction,
                entry=entry,
                stop_loss=stop_loss,
            )
        return []

    def thesis_for_target(
        self,
        *,
        target_price: float | None,
        target_source: str | None,
        direction: str,
        entry: float | None,
        stop_loss: float | None,
        resolved: Sequence[TargetThesis],
        close_percent: float | None = None,
    ) -> TargetThesis | None:
        normalized_direction = _normalize_direction(direction)
        if normalized_direction is None:
            return None
        source = _normalize_target_source(str(target_source) if target_source is not None else None)
        matching = [
            thesis
            for thesis in resolved
            if thesis.source == source
            and (
                target_price is None
                or thesis.price is None
                or abs(thesis.price - target_price) <= max(abs(target_price) * 0.0001, 1e-8)
            )
        ]
        if not matching and target_price is not None:
            matching = [
                thesis
                for thesis in resolved
                if thesis.price is not None
                and abs(thesis.price - target_price) <= max(abs(target_price) * 0.0001, 1e-8)
            ]
        if matching:
            thesis = matching[0]
            return thesis.model_copy(update={"close_percent": close_percent})
        if source is None or target_price is None or entry is None:
            return None
        if not _target_is_directional(normalized_direction, entry, target_price):
            return None
        confidence = 0.35 if source == "risk_multiple_fallback" else 0.55
        return _with_distance_metadata(
            _target_thesis(
                source=source,
                price=target_price,
                direction=normalized_direction,
                confidence=confidence,
                priority=10,
                close_percent=close_percent,
                metadata={"source": target_source or source},
            ),
            direction=normalized_direction,
            entry=entry,
            stop_loss=stop_loss,
        )


def _normalize_direction(direction: str) -> TargetDirection | None:
    normalized = direction.strip().upper()
    if normalized in {"LONG", "SHORT"}:
        return cast(TargetDirection, normalized)
    if normalized == "BUY":
        return "LONG"
    if normalized == "SELL":
        return "SHORT"
    return None


def _liquidity_pool_targets(
    direction: TargetDirection,
    entry: float,
    alpha_context: AlphaMarketContext | None,
) -> list[TargetThesis]:
    if alpha_context is None:
        return []
    side = "above" if direction == "LONG" else "below"
    targets: list[TargetThesis] = []
    for pool in alpha_context.session_liquidity_pools:
        if pool.side != side or not _target_is_directional(direction, entry, pool.price):
            continue
        targets.append(_liquidity_pool_thesis(pool, direction))
    return targets


def _liquidity_pool_thesis(pool: LiquidityPoolFeatures, direction: TargetDirection) -> TargetThesis:
    strength = pool.strength if pool.strength is not None else 50.0
    confidence = max(0.4, min(0.92, strength / 100))
    priority = 95 + int(min(strength, 30) / 10)
    return _target_thesis(
        source="nearest_liquidity_pool",
        price=pool.price,
        direction=direction,
        confidence=confidence,
        priority=priority,
        close_percent=40.0,
        invalidation_hint="Liquidity pool rejects before first partial exit",
        metadata={
            "pool_name": pool.name,
            "pool_source": pool.source,
            "pool_side": pool.side,
            "pool_strength": pool.strength,
            **pool.metadata,
        },
    )


def _feature_level_targets(direction: TargetDirection, entry: float, features: Features) -> list[TargetThesis]:
    levels: list[tuple[TargetSource, float | None, float, int, float | None, str]] = []
    if direction == "LONG":
        levels.extend(
            [
                ("previous_day_high", features.previous_day_high, 0.78, 90, 60.0, "Previous day high liquidity"),
                ("session_high", features.session_high, 0.74, 84, 45.0, "Session high liquidity"),
                ("range_opposite_boundary", features.donchian_high_20, 0.70, 78, 60.0, "Opposite range boundary"),
                ("vwap_deviation_band", _vwap_deviation_band(features, direction), 0.62, 66, 30.0, "VWAP deviation band"),
                ("vwap", features.vwap, 0.58, 55, 30.0, "VWAP target"),
            ]
        )
    else:
        levels.extend(
            [
                ("previous_day_low", features.previous_day_low, 0.78, 90, 60.0, "Previous day low liquidity"),
                ("session_low", features.session_low, 0.74, 84, 45.0, "Session low liquidity"),
                ("range_opposite_boundary", features.donchian_low_20, 0.70, 78, 60.0, "Opposite range boundary"),
                ("vwap_deviation_band", _vwap_deviation_band(features, direction), 0.62, 66, 30.0, "VWAP deviation band"),
                ("vwap", features.vwap, 0.58, 55, 30.0, "VWAP target"),
            ]
        )

    midpoint = _range_midpoint(features)
    if midpoint is not None:
        levels.append(("range_midpoint", midpoint, 0.76, 88, 40.0, "Range midpoint"))

    return [
        _target_thesis(
            source=source,
            price=price,
            direction=direction,
            confidence=confidence,
            priority=priority,
            close_percent=close_percent,
            invalidation_hint=f"{label} fails as target magnet",
            metadata={"level_label": label},
        )
        for source, price, confidence, priority, close_percent, label in levels
        if price is not None and _target_is_directional(direction, entry, price)
    ]


def _support_resistance_targets(
    direction: TargetDirection,
    entry: float,
    snapshots: Mapping[str, SupportResistanceSnapshot],
) -> list[TargetThesis]:
    targets: list[TargetThesis] = []
    for timeframe, snapshot in snapshots.items():
        level = snapshot.nearest_obstacle(direction=direction.lower(), entry=entry, min_strength=0.0)
        if level is None:
            continue
        source: TargetSource = "htf_resistance" if direction == "LONG" else "htf_support"
        targets.append(
            _target_thesis(
                source=source,
                price=level.price,
                direction=direction,
                confidence=max(0.5, min(0.9, level.strength / 100)),
                priority=70 + int(min(level.strength, 30) / 10),
                close_percent=60.0,
                invalidation_hint=f"{timeframe} {level.kind} rejects the trade",
                metadata={
                    "timeframe": timeframe,
                    "level_kind": level.kind,
                    "level_strength": level.strength,
                    "retest_count": level.retest_count,
                    "source": level.source,
                },
            )
        )
    return targets


def _measured_move_price(
    direction: TargetDirection,
    entry: float,
    features: Features,
    metadata: Mapping[str, Any],
) -> float | None:
    accepted_score = _number_or_none(metadata.get("accepted_breakout_score"))
    accepted = bool(metadata.get("accepted_breakout") or metadata.get("accepted_breakout_confirmed"))
    accepted = accepted or (accepted_score is not None and accepted_score >= 0.55)
    entry_model = str(metadata.get("entry_model") or metadata.get("entry_source") or "")
    if not accepted and "breakout" not in entry_model:
        return None
    range_high = features.donchian_high_20
    range_low = features.donchian_low_20
    if range_high is None or range_low is None or range_high <= range_low:
        return None
    range_size = range_high - range_low
    price = range_high + range_size if direction == "LONG" else range_low - range_size
    return price if _target_is_directional(direction, entry, price) else None


def _risk_multiple_fallback_targets(
    *,
    direction: TargetDirection,
    entry: float,
    stop_loss: float | None,
) -> list[TargetThesis]:
    if stop_loss is None:
        return []
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return []
    side = 1 if direction == "LONG" else -1
    return [
        _with_distance_metadata(
            _target_thesis(
                source="risk_multiple_fallback",
                price=entry + side * risk * multiple,
                direction=direction,
                confidence=0.3,
                priority=10 - index,
                close_percent=close_percent,
                metadata={"fallback_target_used": True, "r_multiple": multiple},
            ),
            direction=direction,
            entry=entry,
            stop_loss=stop_loss,
        )
        for index, (multiple, close_percent) in enumerate(((1.0, 40.0), (2.0, 60.0)))
    ]


def _target_thesis(
    *,
    source: TargetSource,
    price: float | None,
    direction: TargetDirection,
    confidence: float,
    priority: int,
    close_percent: float | None = None,
    requires_acceptance: bool = False,
    invalidation_hint: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TargetThesis:
    return TargetThesis(
        source=source,
        price=round(price, 8) if price is not None else None,
        direction=direction,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        priority=priority,
        close_percent=close_percent,
        requires_acceptance=requires_acceptance,
        invalidation_hint=invalidation_hint,
        metadata=dict(metadata or {}),
    )


def _with_distance_metadata(
    thesis: TargetThesis,
    *,
    direction: TargetDirection,
    entry: float,
    stop_loss: float | None,
) -> TargetThesis:
    metadata = dict(thesis.metadata)
    distance = _target_reward(direction, entry, thesis.price)
    metadata["distance"] = distance
    if stop_loss is not None:
        rr_calculation = risk_reward_plan_service.calculate_rr(
            entry,
            stop_loss,
            thesis.price,
            direction,
        )
        if rr_calculation.rr_value is not None:
            metadata["r_multiple"] = rr_calculation.rr_value
    return thesis.model_copy(update={"metadata": metadata})


def _dedupe_and_order(candidates: Sequence[TargetThesis]) -> list[TargetThesis]:
    best_by_key: dict[tuple[str, float | None], TargetThesis] = {}
    for thesis in candidates:
        key = (thesis.source, round(thesis.price, 8) if thesis.price is not None else None)
        existing = best_by_key.get(key)
        if existing is None or thesis.priority > existing.priority:
            best_by_key[key] = thesis
    return sorted(
        best_by_key.values(),
        key=lambda thesis: (
            -(thesis.priority),
            thesis.price is None,
            abs(float(thesis.metadata.get("distance") or 0.0)),
        ),
    )


def _normalize_target_source(value: str | None) -> TargetSource | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases: dict[str, TargetSource] = {
        "liquidity_pool": "nearest_liquidity_pool",
        "session_liquidity_pool": "nearest_liquidity_pool",
        "swing_high": "nearest_liquidity_pool",
        "swing_low": "nearest_liquidity_pool",
        "range_high": "range_opposite_boundary",
        "range_low": "range_opposite_boundary",
        "range_boundary": "range_opposite_boundary",
        "range_measured_move": "measured_move",
        "measured_move_runner": "measured_move",
        "r_multiple": "risk_multiple_fallback",
        "r_multiple_fallback": "risk_multiple_fallback",
        "fallback_r_multiple": "risk_multiple_fallback",
        "one_r": "risk_multiple_fallback",
        "two_r": "risk_multiple_fallback",
        "three_r": "risk_multiple_fallback",
        "ema20": "vwap",
        "ema50": "vwap",
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized in MARKET_TARGET_SOURCES or normalized == "risk_multiple_fallback":
        return cast(TargetSource, normalized)
    return None


def _target_is_directional(direction: TargetDirection, entry: float, price: float | None) -> bool:
    if price is None:
        return False
    if direction == "LONG":
        return price > entry
    return price < entry


def _target_reward(direction: TargetDirection, entry: float, price: float | None) -> float | None:
    if price is None:
        return None
    return price - entry if direction == "LONG" else entry - price


def _range_midpoint(features: Features) -> float | None:
    high = features.donchian_high_20 or features.swing_high or features.session_high
    low = features.donchian_low_20 or features.swing_low or features.session_low
    if high is None or low is None or high <= low:
        return None
    return (high + low) / 2


def _vwap_deviation_band(features: Features, direction: TargetDirection) -> float | None:
    if features.vwap is None:
        return None
    atr = features.atr_14 or 0.0
    if atr <= 0:
        return None
    return features.vwap + atr if direction == "LONG" else features.vwap - atr


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


target_resolver_service = TargetResolverService()
