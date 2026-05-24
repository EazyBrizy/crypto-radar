import logging
from typing import Dict, List, Literal, Optional, Tuple

from app.models.schemas import Features, StrategySignal

logger = logging.getLogger(__name__)

VOLUME_SPIKE_BREAKOUT = "volume_spike_breakout"
TREND_CONTINUATION = "trend_continuation"
MIN_VOLUME = 0.001
MIN_VOLATILITY = 1e-5
CONFIDENCE_MIN = 0.5
CONFIDENCE_MAX = 0.9


class StrategyEngine:
    """Generates trading signals from computed features."""

    def __init__(self) -> None:
        self._last_price_change: Dict[str, float] = {}

    def _adaptive_thresholds(self, features: Features) -> Tuple[float, float]:
        volume_threshold = max(2.0, features.volatility * 50000)
        price_threshold = max(0.0002, features.volatility * 2)
        return volume_threshold, price_threshold

    def _filter_reject_reason(self, features: Features) -> Optional[str]:
        if features.volume < MIN_VOLUME:
            return "volume below minimum"
        if features.volatility < MIN_VOLATILITY:
            return "volatility below minimum"
        return None

    def _momentum_reject_reason(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
    ) -> Optional[str]:
        if direction == "LONG" and features.price_change_1m <= 0:
            return "momentum not positive for LONG"
        if direction == "SHORT" and features.price_change_1m >= 0:
            return "momentum not negative for SHORT"

        previous = self._last_price_change.get(features.symbol)
        if previous is not None:
            if direction == "LONG" and previous <= 0:
                return "previous price_change not aligned for LONG"
            if direction == "SHORT" and previous >= 0:
                return "previous price_change not aligned for SHORT"
        return None

    def _build_confidence(
        self,
        features: Features,
        volume_threshold: float,
        price_threshold: float,
    ) -> float:
        confidence = 0.5
        if features.volume_spike > volume_threshold * 1.5:
            confidence += 0.1
        if abs(features.price_change_1m) > price_threshold * 1.5:
            confidence += 0.1
        if features.volatility > price_threshold:
            confidence += 0.1
        return min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, confidence))

    async def generate_signals(self, features: Features) -> List[StrategySignal]:
        volume_threshold, price_threshold = self._adaptive_thresholds(features)

        reject_reason = self._filter_reject_reason(features)
        if reject_reason is not None:
        #    logger.info(
        #        "Signal rejected for %s (filters): %s "
        #        "[volume_thr=%.4f price_thr=%.6f]",
        #        features.symbol,
        #        reject_reason,
        #        volume_threshold,
        #        price_threshold,
        #    )
            self._last_price_change[features.symbol] = features.price_change_1m
            return []

        signals: List[StrategySignal] = []
        signals.extend(
            self._volume_spike_breakout(features, volume_threshold, price_threshold)
        )
        signals.extend(
            self._trend_continuation(features, volume_threshold, price_threshold)
        )

        self._last_price_change[features.symbol] = features.price_change_1m
        return signals

    def _volume_spike_breakout(
        self,
        features: Features,
        volume_threshold: float,
        price_threshold: float,
    ) -> List[StrategySignal]:
        direction: Optional[Literal["LONG", "SHORT"]] = None
        if (
            features.volume_spike > volume_threshold
            and features.price_change_1m > price_threshold
        ):
            direction = "LONG"
        elif (
            features.volume_spike > volume_threshold
            and features.price_change_1m < -price_threshold
        ):
            direction = "SHORT"

        if direction is None:
            return []

        momentum_reason = self._momentum_reject_reason(features, direction)
        if momentum_reason is not None:
            logger.info(
                "Signal rejected for %s (%s): %s "
                "[volume_thr=%.4f price_thr=%.6f]",
                features.symbol,
                VOLUME_SPIKE_BREAKOUT,
                momentum_reason,
                volume_threshold,
                price_threshold,
            )
            return []

        confidence = self._build_confidence(
            features, volume_threshold, price_threshold
        )
        signal = StrategySignal(
            symbol=features.symbol,
            strategy=VOLUME_SPIKE_BREAKOUT,
            direction=direction,
            confidence=confidence,
            timestamp=features.timestamp,
        )
        logger.info(
            "Signal accepted: %s %s %s confidence=%.2f "
            "[volume_thr=%.4f price_thr=%.6f]",
            signal.symbol,
            signal.strategy,
            signal.direction,
            signal.confidence,
            volume_threshold,
            price_threshold,
        )
        return [signal]

    def _trend_continuation(
        self,
        features: Features,
        volume_threshold: float,
        price_threshold: float,
    ) -> List[StrategySignal]:
        volatility_threshold = max(MIN_VOLATILITY, price_threshold)
        direction: Optional[Literal["LONG", "SHORT"]] = None
        if (
            features.price_change_1m > price_threshold
            and features.volatility > volatility_threshold
        ):
            direction = "LONG"
        elif (
            features.price_change_1m < -price_threshold
            and features.volatility > volatility_threshold
        ):
            direction = "SHORT"

        if direction is None:
            return []

        momentum_reason = self._momentum_reject_reason(features, direction)
        if momentum_reason is not None:
            logger.info(
                "Signal rejected for %s (%s): %s "
                "[volume_thr=%.4f price_thr=%.6f]",
                features.symbol,
                TREND_CONTINUATION,
                momentum_reason,
                volume_threshold,
                price_threshold,
            )
            return []

        confidence = self._build_confidence(
            features, volume_threshold, price_threshold
        )
        signal = StrategySignal(
            symbol=features.symbol,
            strategy=TREND_CONTINUATION,
            direction=direction,
            confidence=confidence,
            timestamp=features.timestamp,
        )
        logger.info(
            "Signal accepted: %s %s %s confidence=%.2f "
            "[volume_thr=%.4f price_thr=%.6f]",
            signal.symbol,
            signal.strategy,
            signal.direction,
            signal.confidence,
            volume_threshold,
            price_threshold,
        )
        return [signal]
