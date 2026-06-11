from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from app.schemas.signal import MarketRegimeSnapshot, RadarSignal
from app.schemas.strategy_performance import StrategyEdgeProfile
from app.services.edge_calibration import EdgeCalibrationService
from app.services.execution_strategy_registry import ExecutionStrategyEligibility


class FakeEdgeProfileProvider:
    def __init__(self, profile: StrategyEdgeProfile) -> None:
        self.profile = profile
        self.calls: list[dict[str, Any]] = []

    async def get_edge_profile(self, **kwargs: Any) -> StrategyEdgeProfile:
        self.calls.append(kwargs)
        return self.profile


class FakeEligibilityService:
    def __init__(self, reason_code: str = "fake_strategy_eligibility") -> None:
        self.reason_code = reason_code
        self.calls: list[Any] = []

    def evaluate(self, edge: Any, **kwargs: Any) -> ExecutionStrategyEligibility:
        _ = kwargs
        self.calls.append(edge)
        return ExecutionStrategyEligibility(
            eligible=False,
            reason_code=self.reason_code,
            reason="Fake eligibility service was used.",
            source="fake",
            metrics={"sample_size": edge.sample_size},
        )


class EdgeCalibrationServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_positive_edge_uses_profile_expectancy_after_costs(self) -> None:
        provider = FakeEdgeProfileProvider(
            _profile(
                source="exact",
                confidence="high",
                sample_size=80,
                signals_count=90,
                winrate=0.6,
                avg_win_r=1.5,
                avg_loss_r=-1.0,
                fees_bps=2.0,
                slippage_bps=3.0,
            )
        )
        service = EdgeCalibrationService(performance_service=provider, min_sample_size=50)

        snapshot = await service.evaluate_signal_edge(_signal())

        self.assertEqual(snapshot.status, "positive")
        self.assertEqual(snapshot.sample_size, 80)
        self.assertEqual(snapshot.min_sample_size, 50)
        self.assertAlmostEqual(snapshot.expectancy_r or 0, 0.5)
        self.assertAlmostEqual(snapshot.expectancy_after_costs_r or 0, 0.495)
        self.assertEqual(snapshot.source, "outcome")
        self.assertEqual(snapshot.score_bucket, "80-89")
        self.assertEqual(snapshot.metadata["profile_source"], "exact")
        self.assertEqual(snapshot.metadata["heuristic_score"], 82.0)
        self.assertTrue(snapshot.metadata["costs_converted_to_r"])
        self.assertEqual(provider.calls[0]["symbol"], "BTCUSDT")
        self.assertEqual(provider.calls[0]["market_regime"], "bullish:strong:aligned")
        self.assertEqual(provider.calls[0]["score"], 82.0)

    async def test_uses_injected_eligibility_service_for_strategy_metadata(self) -> None:
        provider = FakeEdgeProfileProvider(
            _profile(
                source="exact",
                confidence="high",
                sample_size=80,
                signals_count=90,
                winrate=0.6,
                avg_win_r=1.5,
                avg_loss_r=-1.0,
            )
        )
        eligibility_service = FakeEligibilityService()
        service = EdgeCalibrationService(
            performance_service=provider,
            min_sample_size=50,
            eligibility_service=eligibility_service,
        )

        snapshot = await service.evaluate_signal_edge(_signal())

        self.assertEqual(len(eligibility_service.calls), 1)
        self.assertEqual(eligibility_service.calls[0].sample_size, 80)
        self.assertEqual(snapshot.metadata["strategy_eligibility"]["reason_code"], "fake_strategy_eligibility")
        self.assertEqual(snapshot.metadata["strategy_eligibility"]["source"], "fake")

    async def test_default_eligibility_service_uses_registry_singleton(self) -> None:
        provider = FakeEdgeProfileProvider(
            _profile(
                source="exact",
                confidence="high",
                sample_size=80,
                signals_count=90,
                winrate=0.6,
                avg_win_r=1.5,
                avg_loss_r=-1.0,
            )
        )
        eligibility_service = FakeEligibilityService(reason_code="singleton_strategy_eligibility")
        with patch(
            "app.services.edge_calibration.execution_strategy_eligibility_service",
            eligibility_service,
            create=True,
        ):
            service = EdgeCalibrationService(performance_service=provider, min_sample_size=50)

        snapshot = await service.evaluate_signal_edge(_signal())

        self.assertEqual(len(eligibility_service.calls), 1)
        self.assertEqual(snapshot.metadata["strategy_eligibility"]["reason_code"], "singleton_strategy_eligibility")

    async def test_insufficient_sample_status_keeps_metrics(self) -> None:
        provider = FakeEdgeProfileProvider(
            _profile(
                source="strategy_global",
                confidence="low",
                sample_size=20,
                signals_count=25,
                winrate=0.65,
                avg_win_r=1.2,
                avg_loss_r=-1.0,
            )
        )
        service = EdgeCalibrationService(performance_service=provider, min_sample_size=50)

        snapshot = await service.evaluate_signal_edge(_signal())

        self.assertEqual(snapshot.status, "insufficient_sample")
        self.assertEqual(snapshot.sample_size, 20)
        self.assertAlmostEqual(snapshot.expectancy_after_costs_r or 0, 0.43)
        self.assertLess(snapshot.confidence_score, 0.4)

    async def test_no_profile_data_returns_unknown_edge(self) -> None:
        provider = FakeEdgeProfileProvider(
            _profile(
                source="none",
                confidence="insufficient_sample",
                sample_size=0,
                signals_count=0,
            )
        )
        service = EdgeCalibrationService(performance_service=provider, min_sample_size=50)

        snapshot = await service.evaluate_signal_edge(_signal())

        self.assertEqual(snapshot.status, "unknown")
        self.assertEqual(snapshot.sample_size, 0)
        self.assertEqual(snapshot.source, "none")

    async def test_regime_key_wins_over_legacy_direction_strength_alignment(self) -> None:
        provider = FakeEdgeProfileProvider(
            _profile(source="none", confidence="insufficient_sample", sample_size=0, signals_count=0)
        )
        service = EdgeCalibrationService(performance_service=provider, min_sample_size=50)
        signal = _signal().model_copy(
            update={
                "regime": MarketRegimeSnapshot(
                    primary_label="trend_up",
                    base_label="trend_up",
                    direction="bullish",
                    strength="strong",
                    alignment="aligned",
                    regime_key="trend_up:strong:aligned",
                )
            }
        )

        snapshot = await service.evaluate_signal_edge(signal)

        self.assertEqual(provider.calls[0]["market_regime"], "trend_up:strong:aligned")
        self.assertIsNone(snapshot.winrate)
        self.assertEqual(snapshot.confidence_score, 0.0)


def _signal() -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="edge_sig",
        symbol="BTC/USDT:PERP",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        score=82,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=90.0,
        take_profit_1=120.0,
        take_profit_2=130.0,
        regime=MarketRegimeSnapshot(
            direction="bullish",
            strength="strong",
            alignment="aligned",
        ),
        created_at=now,
        updated_at=now,
    )


def _profile(
    *,
    source: str,
    confidence: str,
    sample_size: int,
    signals_count: int,
    winrate: float = 0.0,
    avg_win_r: float = 0.0,
    avg_loss_r: float = 0.0,
    fees_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> StrategyEdgeProfile:
    return StrategyEdgeProfile(
        strategy="trend_pullback_continuation",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        market_regime="bullish:strong:aligned",
        score_bucket="80-89",
        source=source,
        confidence=confidence,
        sample_size=sample_size,
        trades_count=sample_size,
        signals_count=signals_count,
        wins_count=int(sample_size * winrate),
        losses_count=sample_size - int(sample_size * winrate),
        entry_touch_rate=sample_size / signals_count if signals_count else 0.0,
        winrate=winrate,
        tp1_rate=0.4,
        tp2_rate=0.2,
        stop_rate=0.2,
        invalidation_rate=0.0,
        avg_win_r=avg_win_r,
        avg_loss_r=avg_loss_r,
        expectancy_r=0.0,
        profit_factor=1.5 if sample_size else None,
        max_drawdown_r=1.0,
        median_bars_to_entry=1.0 if sample_size else None,
        median_bars_to_outcome=3.0 if sample_size else None,
        avg_mfe_r=1.0,
        avg_mae_r=-0.4,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
    )


if __name__ == "__main__":
    unittest.main()
