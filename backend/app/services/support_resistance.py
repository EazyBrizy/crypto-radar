from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.schemas.candle import OHLCVCandle

DEFAULT_EXTREMA_WINDOW = 2
DEFAULT_LEVEL_TOLERANCE_ATR = 0.35
DEFAULT_MAX_LEVEL_AGE_CANDLES = 200
DEFAULT_MAX_LEVELS = 12


@dataclass(frozen=True)
class SupportResistanceLevel:
    kind: str
    price: float
    retest_count: int
    age_candles: int
    first_seen_index: int
    last_seen_index: int
    volume_score: float
    freshness_score: float
    strength: float
    source: str = "local_extrema"


@dataclass(frozen=True)
class SupportResistanceSnapshot:
    exchange: str
    symbol: str
    timeframe: str
    atr: float | None
    levels: tuple[SupportResistanceLevel, ...]

    def nearest_obstacle(
        self,
        *,
        direction: str,
        entry: float,
        min_strength: float = 0.0,
    ) -> SupportResistanceLevel | None:
        normalized_direction = direction.strip().lower()
        if normalized_direction == "long":
            candidates = [
                level
                for level in self.levels
                if level.kind == "resistance"
                and level.price > entry
                and level.strength >= min_strength
            ]
            return min(candidates, key=lambda level: level.price, default=None)
        if normalized_direction == "short":
            candidates = [
                level
                for level in self.levels
                if level.kind == "support"
                and level.price < entry
                and level.strength >= min_strength
            ]
            return max(candidates, key=lambda level: level.price, default=None)
        return None


class SupportResistanceService:
    def build_snapshot(
        self,
        candles: Sequence[OHLCVCandle],
        *,
        atr: float | None = None,
        extrema_window: int = DEFAULT_EXTREMA_WINDOW,
        level_tolerance_atr: float = DEFAULT_LEVEL_TOLERANCE_ATR,
        max_level_age_candles: int = DEFAULT_MAX_LEVEL_AGE_CANDLES,
        max_levels: int = DEFAULT_MAX_LEVELS,
    ) -> SupportResistanceSnapshot | None:
        ordered = sorted(candles, key=lambda candle: candle.open_time)
        if not ordered:
            return None
        exchange = ordered[-1].exchange
        symbol = ordered[-1].symbol
        timeframe = ordered[-1].timeframe
        if len(ordered) < extrema_window * 2 + 3:
            return SupportResistanceSnapshot(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                atr=atr,
                levels=(),
            )

        effective_atr = atr if atr is not None and atr > 0 else _average_true_range(ordered)
        close = ordered[-1].close
        tolerance = max(
            (effective_atr or close * 0.005) * level_tolerance_atr,
            close * 0.0005,
        )
        average_volume = _average_volume(ordered)
        candidates = _local_extrema(ordered, extrema_window)
        levels = _cluster_levels(
            candidates,
            latest_index=len(ordered) - 1,
            tolerance=tolerance,
            average_volume=average_volume,
            max_level_age_candles=max_level_age_candles,
        )
        strongest = sorted(
            levels,
            key=lambda level: (level.strength, level.retest_count, -level.age_candles),
            reverse=True,
        )[:max_levels]
        return SupportResistanceSnapshot(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            atr=effective_atr,
            levels=tuple(strongest),
        )


def _local_extrema(
    candles: Sequence[OHLCVCandle],
    window: int,
) -> list[tuple[str, float, int, float]]:
    candidates: list[tuple[str, float, int, float]] = []
    for index in range(window, len(candles) - window):
        candle = candles[index]
        neighbors = [*candles[index - window:index], *candles[index + 1:index + window + 1]]
        if not neighbors:
            continue
        neighbor_high = max(item.high for item in neighbors)
        neighbor_low = min(item.low for item in neighbors)
        if candle.high >= neighbor_high and candle.high > candles[index - 1].high and candle.high > candles[index + 1].high:
            candidates.append(("resistance", candle.high, index, candle.volume))
        if candle.low <= neighbor_low and candle.low < candles[index - 1].low and candle.low < candles[index + 1].low:
            candidates.append(("support", candle.low, index, candle.volume))
    return candidates


def _cluster_levels(
    candidates: Sequence[tuple[str, float, int, float]],
    *,
    latest_index: int,
    tolerance: float,
    average_volume: float,
    max_level_age_candles: int,
) -> list[SupportResistanceLevel]:
    levels: list[SupportResistanceLevel] = []
    for kind in ("support", "resistance"):
        clusters: list[dict[str, float | int]] = []
        for _, price, index, volume in sorted(
            (candidate for candidate in candidates if candidate[0] == kind),
            key=lambda candidate: candidate[1],
        ):
            cluster = _nearest_cluster(clusters, price, tolerance)
            if cluster is None:
                clusters.append(
                    {
                        "weighted_price": price * max(volume, 1.0),
                        "weight": max(volume, 1.0),
                        "touches": 1,
                        "first_index": index,
                        "last_index": index,
                        "volume": volume,
                    }
                )
                continue
            weight = max(volume, 1.0)
            cluster["weighted_price"] = float(cluster["weighted_price"]) + price * weight
            cluster["weight"] = float(cluster["weight"]) + weight
            cluster["touches"] = int(cluster["touches"]) + 1
            cluster["first_index"] = min(int(cluster["first_index"]), index)
            cluster["last_index"] = max(int(cluster["last_index"]), index)
            cluster["volume"] = float(cluster["volume"]) + volume

        for cluster in clusters:
            weight = float(cluster["weight"]) or 1.0
            touches = int(cluster["touches"])
            age_candles = max(0, latest_index - int(cluster["last_index"]))
            freshness_score = max(0.0, 1.0 - age_candles / max(max_level_age_candles, 1))
            volume_per_touch = float(cluster["volume"]) / max(touches, 1)
            volume_score = volume_per_touch / average_volume if average_volume > 0 else 1.0
            touch_score = min(1.0, touches / 4)
            capped_volume_score = min(1.0, volume_score / 2)
            strength = round(touch_score * 55 + freshness_score * 25 + capped_volume_score * 20, 2)
            levels.append(
                SupportResistanceLevel(
                    kind=kind,
                    price=round(float(cluster["weighted_price"]) / weight, 8),
                    retest_count=max(0, touches - 1),
                    age_candles=age_candles,
                    first_seen_index=int(cluster["first_index"]),
                    last_seen_index=int(cluster["last_index"]),
                    volume_score=round(volume_score, 3),
                    freshness_score=round(freshness_score, 3),
                    strength=strength,
                )
            )
    return levels


def _nearest_cluster(
    clusters: Sequence[dict[str, float | int]],
    price: float,
    tolerance: float,
) -> dict[str, float | int] | None:
    eligible = [
        cluster
        for cluster in clusters
        if abs(price - float(cluster["weighted_price"]) / max(float(cluster["weight"]), 1.0)) <= tolerance
    ]
    return min(
        eligible,
        key=lambda cluster: abs(price - float(cluster["weighted_price"]) / max(float(cluster["weight"]), 1.0)),
        default=None,
    )


def _average_true_range(candles: Sequence[OHLCVCandle], period: int = 14) -> float | None:
    if len(candles) < 2:
        return None
    recent = list(candles[-(period + 1):])
    true_ranges: list[float] = []
    for previous, current in zip(recent[:-1], recent[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    if not true_ranges:
        return None
    return sum(true_ranges) / len(true_ranges)


def _average_volume(candles: Sequence[OHLCVCandle], period: int = 50) -> float:
    values = [max(candle.volume, 0.0) for candle in candles[-period:]]
    if not values:
        return 0.0
    return sum(values) / len(values)


support_resistance_service = SupportResistanceService()
