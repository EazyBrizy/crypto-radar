from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from app.services.strategy_performance_service import (
    StrategyPerformanceOutcome,
    StrategyPerformanceProfileQuery,
    StrategyPerformanceService,
    StrategyPerformanceSummary,
    build_daily_performance,
    score_bucket_for,
)


DAY = date(2026, 1, 2)
REGIME = "bullish:strong:aligned"


class FakePerformanceStore:
    def __init__(self, summaries: dict[tuple[object, ...], StrategyPerformanceSummary | None] | None = None) -> None:
        self.rows: list[object] = []
        self.queries: list[StrategyPerformanceProfileQuery] = []
        self.summaries = summaries or {}

    def ensure_schema(self) -> None:
        return None

    def write_daily(self, rows: list[object]) -> None:
        self.rows.extend(rows)

    def query_profile(self, query: StrategyPerformanceProfileQuery) -> StrategyPerformanceSummary | None:
        self.queries.append(query)
        return self.summaries.get(_query_key(query))


class EmptyOutcomeSource:
    def list_closed_outcomes(self, *, day: date) -> list[StrategyPerformanceOutcome]:
        return []


class StrategyPerformanceServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_daily_aggregation_from_synthetic_outcomes(self) -> None:
        rows = build_daily_performance(
            day=DAY,
            outcomes=[
                _outcome(status="tp2", outcome="win", realized_r=2.0, bars_to_entry=1, bars_to_outcome=4),
                _outcome(status="stop_loss", outcome="loss", realized_r=-1.0, bars_to_entry=2, bars_to_outcome=5),
                _outcome(status="invalidated", outcome="invalidated", realized_r=0.0, bars_to_entry=None),
            ],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.signals_count, 3)
        self.assertEqual(row.trades_count, 2)
        self.assertEqual(row.sample_size, 2)
        self.assertEqual(row.filled_count, 2)
        self.assertEqual(row.no_entry_count, 1)
        self.assertAlmostEqual(row.fill_rate, 2 / 3)
        self.assertAlmostEqual(row.no_entry_rate, 1 / 3)
        self.assertAlmostEqual(row.entry_touch_rate, 2 / 3)
        self.assertAlmostEqual(row.winrate, 0.5)
        self.assertAlmostEqual(row.tp1_rate, 0.5)
        self.assertAlmostEqual(row.tp2_rate, 0.5)
        self.assertAlmostEqual(row.stop_rate, 0.5)
        self.assertAlmostEqual(row.invalidation_rate, 1 / 3)

    def test_virtual_execution_rejections_are_not_counted_as_no_entry(self) -> None:
        rows = build_daily_performance(
            day=DAY,
            outcomes=[
                _outcome(status="tp1", outcome="win", realized_r=1.0, bars_to_entry=1),
                _outcome(
                    status="invalidated",
                    outcome="invalidated",
                    realized_r=0.0,
                    bars_to_entry=None,
                    pending_entry_reason_code="virtual_execution_rejected",
                ),
                _outcome(
                    status="expired",
                    outcome="expired",
                    realized_r=0.0,
                    bars_to_entry=None,
                    pending_entry_reason_code="pending_entry_expired_before_touch",
                ),
            ],
        )

        row = rows[0]
        self.assertEqual(row.signals_count, 3)
        self.assertEqual(row.filled_count, 1)
        self.assertEqual(row.execution_rejected_count, 1)
        self.assertEqual(row.no_entry_count, 1)
        self.assertAlmostEqual(row.execution_rejected_rate, 1 / 3)
        self.assertAlmostEqual(row.no_entry_rate, 1 / 3)

    def test_expectancy_and_profit_factor_calculation(self) -> None:
        row = build_daily_performance(
            day=DAY,
            outcomes=[
                _outcome(status="tp1", outcome="win", realized_r=1.5, bars_to_entry=1),
                _outcome(status="tp2", outcome="win", realized_r=2.0, bars_to_entry=1),
                _outcome(status="stop_loss", outcome="loss", realized_r=-1.0, bars_to_entry=1),
            ],
        )[0]

        self.assertAlmostEqual(row.avg_win_r, 1.75)
        self.assertAlmostEqual(row.avg_loss_r, -1.0)
        self.assertAlmostEqual(row.expectancy_r, (1.5 + 2.0 - 1.0) / 3)
        self.assertAlmostEqual(row.profit_factor or 0, 3.5)

    def test_score_bucket_assignment(self) -> None:
        self.assertEqual(score_bucket_for(0), "0-49")
        self.assertEqual(score_bucket_for(49.9), "0-49")
        self.assertEqual(score_bucket_for(50), "50-59")
        self.assertEqual(score_bucket_for(60), "60-69")
        self.assertEqual(score_bucket_for(70), "70-79")
        self.assertEqual(score_bucket_for(80), "80-89")
        self.assertEqual(score_bucket_for(90), "90-100")
        self.assertEqual(score_bucket_for(120), "90-100")

    def test_aggregate_daily_writes_rows_to_store(self) -> None:
        store = FakePerformanceStore()
        service = StrategyPerformanceService(
            outcome_source=EmptyOutcomeSource(),
            performance_store=store,  # type: ignore[arg-type]
            min_sample_size=3,
        )

        rows = service.aggregate_daily(day=DAY, outcomes=[_outcome()], write=True)

        self.assertEqual(store.rows, rows)
        self.assertEqual(rows[0].score_bucket, "80-89")

    async def test_edge_profile_falls_back_when_exact_sample_is_low(self) -> None:
        exact = _summary(sample_size=2, signals_count=2)
        fallback = _summary(sample_size=6, signals_count=8, expectancy_r=0.4)
        store = FakePerformanceStore(
            {
                (
                    "trend_pullback_continuation",
                    "bybit",
                    "BTCUSDT",
                    "15m",
                    REGIME,
                    "80-89",
                ): exact,
                ("trend_pullback_continuation", None, None, "15m", REGIME, None): fallback,
            }
        )
        service = StrategyPerformanceService(
            outcome_source=EmptyOutcomeSource(),
            performance_store=store,  # type: ignore[arg-type]
            min_sample_size=5,
        )

        profile = await service.get_edge_profile(
            strategy="trend_pullback_continuation",
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="15m",
            market_regime=REGIME,
            score=82,
        )

        self.assertEqual(profile.source, "strategy_timeframe_regime")
        self.assertEqual(profile.confidence, "medium")
        self.assertEqual(profile.sample_size, 6)
        self.assertEqual(len(store.queries), 2)

    async def test_low_global_sample_returns_low_confidence(self) -> None:
        store = FakePerformanceStore(
            {
                ("trend_pullback_continuation", None, None, None, None, None): _summary(
                    sample_size=3,
                    signals_count=4,
                )
            }
        )
        service = StrategyPerformanceService(
            outcome_source=EmptyOutcomeSource(),
            performance_store=store,  # type: ignore[arg-type]
            min_sample_size=5,
        )

        profile = await service.get_edge_profile(
            strategy="trend_pullback_continuation",
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="15m",
            market_regime=REGIME,
            score=82,
        )

        self.assertEqual(profile.source, "strategy_global")
        self.assertEqual(profile.confidence, "low")
        self.assertEqual(profile.sample_size, 3)

    async def test_no_data_returns_insufficient_sample_profile(self) -> None:
        service = StrategyPerformanceService(
            outcome_source=EmptyOutcomeSource(),
            performance_store=FakePerformanceStore(),  # type: ignore[arg-type]
            min_sample_size=5,
        )

        profile = await service.get_edge_profile(
            strategy="trend_pullback_continuation",
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="15m",
            market_regime=None,
            score=None,
        )

        self.assertEqual(profile.source, "none")
        self.assertEqual(profile.confidence, "insufficient_sample")
        self.assertEqual(profile.sample_size, 0)


def _outcome(
    *,
    status: str = "tp1",
    outcome: str = "win",
    realized_r: float = 1.0,
    bars_to_entry: int | None = 1,
    bars_to_outcome: int | None = 3,
    pending_entry_reason_code: str | None = None,
) -> StrategyPerformanceOutcome:
    return StrategyPerformanceOutcome(
        date=DAY,
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        strategy="trend_pullback_continuation",
        strategy_version="v1",
        market_regime=REGIME,
        score_bucket="80-89",
        direction="long",
        status=status,
        outcome=outcome,
        realized_r=realized_r,
        mfe_r=max(realized_r, 0.25),
        mae_r=min(realized_r, -0.25),
        bars_to_entry=bars_to_entry,
        bars_to_outcome=bars_to_outcome,
        fees_bps=2.0,
        slippage_bps=3.0,
        closed_at=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
        pending_entry_reason_code=pending_entry_reason_code,
    )


def _summary(
    *,
    sample_size: int,
    signals_count: int,
    expectancy_r: float = 0.2,
) -> StrategyPerformanceSummary:
    return StrategyPerformanceSummary(
        sample_size=sample_size,
        trades_count=sample_size,
        signals_count=signals_count,
        wins_count=max(sample_size - 1, 0),
        losses_count=1 if sample_size else 0,
        entry_touch_rate=sample_size / signals_count if signals_count else 0.0,
        winrate=0.5,
        tp1_rate=0.4,
        tp2_rate=0.2,
        stop_rate=0.2,
        invalidation_rate=0.0,
        avg_win_r=1.0,
        avg_loss_r=-1.0,
        expectancy_r=expectancy_r,
        profit_factor=2.0,
        max_drawdown_r=1.0,
        median_bars_to_entry=1.0,
        median_bars_to_outcome=3.0,
        avg_mfe_r=1.2,
        avg_mae_r=-0.4,
        fees_bps=2.0,
        slippage_bps=3.0,
    )


def _query_key(query: StrategyPerformanceProfileQuery) -> tuple[object, ...]:
    return (
        query.strategy,
        query.exchange,
        query.symbol,
        query.timeframe,
        query.market_regime,
        query.score_bucket,
    )


if __name__ == "__main__":
    unittest.main()
