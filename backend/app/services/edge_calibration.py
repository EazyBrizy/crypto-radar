from __future__ import annotations

import logging
from typing import Any, Protocol

from app.schemas.signal import RadarSignal, SignalEdgeSnapshot, StrategySignal
from app.schemas.strategy_performance import StrategyEdgeProfile
from app.schemas.user import RiskManagementSettings
from app.services.strategy_performance_service import strategy_performance_service

logger = logging.getLogger(__name__)


class EdgeProfileProvider(Protocol):
    async def get_edge_profile(
        self,
        *,
        strategy: str,
        exchange: str,
        symbol: str,
        timeframe: str,
        market_regime: str | None,
        score: float | None,
    ) -> StrategyEdgeProfile:
        ...


class EdgeCalibrationService:
    def __init__(
        self,
        *,
        performance_service: EdgeProfileProvider | None = None,
        min_sample_size: int | None = None,
    ) -> None:
        self._performance_service = performance_service or strategy_performance_service
        self._min_sample_size = (
            RiskManagementSettings().edge_min_sample_size
            if min_sample_size is None
            else int(min_sample_size)
        )

    async def evaluate_signal_edge(
        self,
        signal: RadarSignal | StrategySignal,
    ) -> SignalEdgeSnapshot:
        market_regime = _market_regime(signal)
        score = float(signal.score) if signal.score is not None else None
        try:
            profile = await self._performance_service.get_edge_profile(
                strategy=signal.strategy,
                exchange=signal.exchange,
                symbol=_normalize_symbol(signal.symbol),
                timeframe=signal.timeframe,
                market_regime=market_regime,
                score=score,
            )
        except Exception as exc:
            logger.warning(
                "Signal edge profile lookup failed for %s:%s:%s:%s: %s",
                signal.exchange,
                signal.symbol,
                signal.timeframe,
                signal.strategy,
                exc,
            )
            return _unknown_snapshot(
                min_sample_size=self._min_sample_size,
                score=score,
                market_regime=market_regime,
                metadata={"error": str(exc)},
            )

        if profile.source == "none" or profile.signals_count == 0:
            return _unknown_snapshot(
                min_sample_size=self._min_sample_size,
                score=score,
                market_regime=market_regime,
                score_bucket=profile.score_bucket,
                metadata={
                    "profile_source": profile.source,
                    "profile_confidence": profile.confidence,
                },
            )

        expectancy_r = _expectancy_r(profile)
        estimated_costs_r, costs_metadata = _estimated_costs_r(profile, signal)
        expectancy_after_costs_r = expectancy_r - estimated_costs_r
        status = _edge_status(
            sample_size=profile.sample_size,
            min_sample_size=self._min_sample_size,
            expectancy_after_costs_r=expectancy_after_costs_r,
        )

        return SignalEdgeSnapshot(
            status=status,
            sample_size=profile.sample_size,
            min_sample_size=self._min_sample_size,
            winrate=profile.winrate,
            avg_win_r=profile.avg_win_r,
            avg_loss_r=profile.avg_loss_r,
            expectancy_r=expectancy_r,
            expectancy_after_costs_r=expectancy_after_costs_r,
            profit_factor=profile.profit_factor,
            confidence_score=_confidence_score(
                confidence=profile.confidence,
                sample_size=profile.sample_size,
                min_sample_size=self._min_sample_size,
            ),
            source="outcome",
            score_bucket=profile.score_bucket,
            metadata={
                "profile_source": profile.source,
                "profile_confidence": profile.confidence,
                "heuristic_score": score,
                "expected_value_r": expectancy_after_costs_r,
                "market_regime": market_regime,
                **costs_metadata,
            },
        )


def _unknown_snapshot(
    *,
    min_sample_size: int,
    score: float | None,
    market_regime: str | None,
    score_bucket: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SignalEdgeSnapshot:
    return SignalEdgeSnapshot(
        status="unknown",
        sample_size=0,
        min_sample_size=min_sample_size,
        confidence_score=0.0,
        source="none",
        score_bucket=score_bucket,
        metadata={
            "heuristic_score": score,
            "market_regime": market_regime,
            **(metadata or {}),
        },
    )


def _expectancy_r(profile: StrategyEdgeProfile) -> float:
    return profile.winrate * profile.avg_win_r - (1 - profile.winrate) * abs(profile.avg_loss_r)


def _estimated_costs_r(
    profile: StrategyEdgeProfile,
    signal: RadarSignal | StrategySignal,
) -> tuple[float, dict[str, Any]]:
    cost_bps = max(0.0, profile.fees_bps) + max(0.0, profile.slippage_bps)
    entry_price = _entry_price(signal)
    stop_loss = signal.stop_loss
    metadata: dict[str, Any] = {
        "fees_bps": profile.fees_bps,
        "slippage_bps": profile.slippage_bps,
        "estimated_costs_bps": cost_bps,
    }
    if cost_bps == 0:
        metadata["costs_converted_to_r"] = True
        metadata["estimated_costs_r"] = 0.0
        return 0.0, metadata
    if entry_price is None or stop_loss is None:
        metadata["costs_converted_to_r"] = False
        metadata["estimated_costs_r"] = 0.0
        return 0.0, metadata
    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit <= 0:
        metadata["costs_converted_to_r"] = False
        metadata["estimated_costs_r"] = 0.0
        return 0.0, metadata
    estimated_costs_r = entry_price * cost_bps / 10_000 / risk_per_unit
    metadata["costs_converted_to_r"] = True
    metadata["estimated_costs_r"] = estimated_costs_r
    return estimated_costs_r, metadata


def _edge_status(
    *,
    sample_size: int,
    min_sample_size: int,
    expectancy_after_costs_r: float,
) -> str:
    if sample_size < min_sample_size:
        return "insufficient_sample"
    return "positive" if expectancy_after_costs_r > 0 else "negative"


def _confidence_score(
    *,
    confidence: str,
    sample_size: int,
    min_sample_size: int,
) -> float:
    weight = {
        "high": 1.0,
        "medium": 0.8,
        "low": 0.4,
        "insufficient_sample": 0.0,
    }.get(confidence, 0.0)
    sample_factor = 1.0 if min_sample_size <= 0 else min(1.0, sample_size / min_sample_size)
    return round(max(0.0, min(1.0, weight * sample_factor)), 4)


def _market_regime(signal: RadarSignal | StrategySignal) -> str | None:
    regime = signal.regime
    if regime is None:
        return None
    direction = getattr(regime, "direction", None)
    strength = getattr(regime, "strength", None)
    alignment = getattr(regime, "alignment", None)
    if direction is None and isinstance(regime, dict):
        direction = regime.get("direction")
        strength = regime.get("strength")
        alignment = regime.get("alignment")
    if direction is None:
        return None
    return f"{direction}:{strength or 'unknown'}:{alignment or 'unknown'}"


def _entry_price(signal: RadarSignal | StrategySignal) -> float | None:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    return signal.entry_max


def _normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":PERP", "").upper()


edge_calibration_service = EdgeCalibrationService()
