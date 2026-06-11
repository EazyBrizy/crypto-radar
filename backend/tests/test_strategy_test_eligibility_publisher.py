from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from app.services.strategy_testing.eligibility_publisher import StrategyTestEligibilityPublisher
from app.services.strategy_testing.schemas import (
    StrategyTestRunDetailResponse,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignal,
    StrategyTestTrade,
)


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 6, 11, 10, tzinfo=timezone.utc)


class StrategyTestEligibilityPublisherTest(unittest.TestCase):
    def test_strategy_test_eligibility_publisher_positive_profile(self) -> None:
        publisher = StrategyTestEligibilityPublisher(
            run_store=_RunStore(),
            analytics_store=_AnalyticsStore(
                signals=[_signal(f"signal-{index}", entry_touched=True, filled=True) for index in range(1, 6)],
                trades=[
                    _trade("trade-1", realized_r=1.4),
                    _trade("trade-2", realized_r=1.1),
                    _trade("trade-3", realized_r=1.0),
                    _trade("trade-4", realized_r=-0.5, close_reason="stop_loss"),
                    _trade("trade-5", realized_r=0.8),
                ],
            ),
            profile_store=_ProfileStore(),
            thresholds=_thresholds(min_sample_size=3),
        )

        result = publisher.publish_run(RUN_ID)

        self.assertEqual(result.profiles_updated, 1)
        self.assertEqual(result.eligible_count, 1)
        self.assertEqual(result.blocked_count, 0)
        profile = publisher.profile_store.profiles[0]  # type: ignore[attr-defined]
        self.assertTrue(profile.eligible)
        self.assertEqual(profile.source, "historical_backtest")
        self.assertEqual(profile.strategy_code, "trend_pullback_continuation")
        self.assertEqual(profile.exchange, "bybit")
        self.assertEqual(profile.symbol_scope, "BTCUSDT")
        self.assertEqual(profile.timeframe, "15m")
        self.assertEqual(profile.direction, "long")
        self.assertEqual(profile.run_ids, [str(RUN_ID)])
        self.assertEqual(profile.reason_code, "eligible")
        self.assertGreater(profile.expectancy_after_costs_r or 0, 0.05)

    def test_strategy_test_eligibility_publisher_negative_profile(self) -> None:
        publisher = StrategyTestEligibilityPublisher(
            run_store=_RunStore(test_type="forward_virtual"),
            analytics_store=_AnalyticsStore(
                signals=[_signal(f"signal-{index}", entry_touched=True, filled=True) for index in range(1, 5)],
                trades=[
                    _trade("trade-1", realized_r=-1.0, close_reason="stop_loss"),
                    _trade("trade-2", realized_r=-0.8, close_reason="stop_loss"),
                    _trade("trade-3", realized_r=0.2),
                    _trade("trade-4", realized_r=-0.5, close_reason="stop_loss"),
                ],
            ),
            profile_store=_ProfileStore(),
            thresholds=_thresholds(min_sample_size=3),
        )

        result = publisher.publish_run(RUN_ID)

        self.assertEqual(result.profiles_updated, 1)
        self.assertEqual(result.eligible_count, 0)
        self.assertEqual(result.blocked_count, 1)
        profile = publisher.profile_store.profiles[0]  # type: ignore[attr-defined]
        self.assertFalse(profile.eligible)
        self.assertEqual(profile.source, "forward_virtual")
        self.assertEqual(profile.reason_code, "expectancy_below_threshold")
        self.assertLess(profile.expectancy_after_costs_r or 0, 0.05)

    def test_publish_requires_completed_run(self) -> None:
        publisher = StrategyTestEligibilityPublisher(
            run_store=_RunStore(status="running"),
            analytics_store=_AnalyticsStore(signals=[], trades=[]),
            profile_store=_ProfileStore(),
            thresholds=_thresholds(min_sample_size=3),
        )

        with self.assertRaisesRegex(ValueError, "completed"):
            publisher.publish_run(RUN_ID)


class _RunStore:
    def __init__(self, *, status: StrategyTestRunStatus = "completed", test_type: str = "historical_backtest") -> None:
        self.status = status
        self.test_type = test_type

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        if run_id != RUN_ID:
            return None
        return StrategyTestRunDetailResponse(
            run=StrategyTestRunResponse(
                run_id=run_id,
                status=self.status,
                requested_matrix={
                    "test_type": self.test_type,
                    "mode": "research_virtual",
                    "strategies": ["trend_pullback_continuation"],
                    "pairs": [{"exchange": "bybit", "symbol": "BTCUSDT"}],
                    "timeframes": ["15m"],
                    "start_at": NOW - timedelta(days=5),
                    "end_at": NOW,
                    "scenario_count": 1,
                },
                summary={},
            )
        )


class _AnalyticsStore:
    def __init__(self, *, signals: Sequence[StrategyTestSignal], trades: Sequence[StrategyTestTrade]) -> None:
        self._signals = list(signals)
        self._trades = list(trades)

    def list_signals(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestSignal]:
        _ = run_id, limit, offset
        return list(self._signals)

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        _ = run_id, limit, offset
        return list(self._trades)


class _ProfileStore:
    def __init__(self) -> None:
        self.profiles: list[Any] = []

    def upsert_profiles(self, profiles: Sequence[Any]) -> list[Any]:
        self.profiles = list(profiles)
        return self.profiles


def _signal(
    signal_id: str,
    *,
    entry_touched: bool,
    filled: bool,
    no_entry: bool = False,
) -> StrategyTestSignal:
    offset = int(signal_id.rsplit("-", 1)[-1])
    return StrategyTestSignal(
        run_id=RUN_ID,
        user_id=USER_ID,
        mode="research_virtual",
        scenario_id="trend_pullback_continuation:bybit:BTCUSDT:15m",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        direction="long",
        signal_id=signal_id,
        signal_time=NOW + timedelta(minutes=offset),
        signal_score=82.0,
        feed_kind="execution_signal",
        gate_status="passed",
        status="actionable",
        trigger_passed=True,
        edge_status="unknown",
        selected_rr=1.5,
        entry_min=Decimal("100"),
        entry_max=Decimal("101"),
        stop_loss=Decimal("98"),
        target_1=Decimal("104"),
        outcome="filled" if filled else "no_entry",
        outcome_reason="" if filled else "entry_not_touched",
        entry_touched=entry_touched,
        filled=filled,
        no_entry=no_entry,
        created_at=NOW + timedelta(minutes=offset),
        metadata={"market_regime": "trend_up", "score_bucket": "80-89"},
    )


def _trade(
    trade_id: str,
    *,
    realized_r: float,
    close_reason: str = "take_profit",
) -> StrategyTestTrade:
    offset = int(trade_id.rsplit("-", 1)[-1])
    entry_time = NOW + timedelta(minutes=offset)
    return StrategyTestTrade(
        run_id=RUN_ID,
        trade_id=trade_id,
        user_id=USER_ID,
        mode="research_virtual",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        direction="long",
        signal_score=82.0,
        market_regime="trend_up",
        score_bucket="80-89",
        entry_time=entry_time,
        exit_time=entry_time + timedelta(minutes=15),
        entry_price=Decimal("100"),
        exit_price=Decimal("104"),
        stop_loss=Decimal("98"),
        targets=[{"label": "TP1", "price": "104", "hit": realized_r > 0}],
        selected_rr=1.5,
        realized_r=realized_r,
        pnl=Decimal(str(realized_r * 10)),
        pnl_pct=realized_r / 100,
        fees=Decimal("0"),
        slippage=Decimal("0"),
        mfe_r=max(realized_r, 0.2),
        mae_r=min(realized_r, -0.2),
        bars_to_entry=1,
        bars_in_trade=3,
        close_reason=close_reason,
        outcome="win" if realized_r > 0 else "loss",
        warnings=[],
        features_snapshot={},
        trade_plan={},
        tags=["backtest"],
        created_at=entry_time,
    )


def _thresholds(*, min_sample_size: int) -> dict[str, float | int]:
    return {
        "min_sample_size": min_sample_size,
        "min_expectancy_after_costs_r": 0.05,
        "min_profit_factor": 1.1,
        "min_entry_touch_rate": 0.5,
        "max_no_entry_rate": 0.5,
        "max_drawdown_r": 5.0,
    }


if __name__ == "__main__":
    unittest.main()
