from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID, uuid4
import unittest

from fastapi.testclient import TestClient

from app.api.v1.strategy_tests import get_strategy_testing_service
from app.main import app
from app.services.strategy_testing.metrics import MetricRegistry, MetricResult, build_base_metric_registry
from app.services.strategy_testing.report_builder import StrategyTestReportBuilder
from app.services.strategy_testing.schemas import (
    StrategyTestReport,
    StrategyTestRunDetailResponse,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTrade,
)


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)

REQUIRED_SECTION_NAMES = {
    "Summary",
    "Strategy comparison",
    "Pair/timeframe breakdown",
    "Regime breakdown",
    "Score bucket breakdown",
    "Entry quality",
    "Exit quality",
    "MFE/MAE distribution",
    "Rejection analysis",
    "Trade list",
    "Recommended strategy adjustments",
}


class StrategyTestReportBuilderTest(unittest.TestCase):
    def test_report_contains_all_required_section_names(self) -> None:
        report = _builder([_trade("trade-1")]).build_report(RUN_ID)

        self.assertEqual({section.name for section in report.sections}, REQUIRED_SECTION_NAMES)

    def test_strategy_comparison_groups_by_strategy(self) -> None:
        report = _builder(
            [
                _trade("trade-1", strategy="trend_pullback_continuation"),
                _trade("trade-2", strategy="volatility_squeeze_breakout"),
            ]
        ).build_report(RUN_ID)

        section = _section(report, "Strategy comparison")
        strategies = {row["strategy"] for row in section.rows}

        self.assertEqual(strategies, {"trend_pullback_continuation", "volatility_squeeze_breakout"})

    def test_score_bucket_negative_expectancy_produces_candidate_adjustment(self) -> None:
        trades = [
            _trade(f"trade-{index}", strategy="trend_pullback_continuation", score_bucket="70-79", realized_r=-1.0)
            for index in range(1, 6)
        ]

        report = _builder(trades).build_report(RUN_ID)

        suggestions = [adjustment.suggested_change for adjustment in report.candidate_adjustments]
        self.assertTrue(any("score_bucket 70-79" in suggestion for suggestion in suggestions))

    def test_bullish_regime_short_stop_rate_produces_candidate_adjustment(self) -> None:
        trades = [
            _trade(
                f"trade-{index}",
                direction="short",
                market_regime="bullish_htf",
                realized_r=-1.0,
                close_reason="stop_loss",
            )
            for index in range(1, 6)
        ]

        report = _builder(trades).build_report(RUN_ID)

        self.assertTrue(
            any("Avoid short signals" in adjustment.suggested_change for adjustment in report.candidate_adjustments)
        )

    def test_empty_trades_report_does_not_crash_and_marks_insufficient_data(self) -> None:
        report = _builder([]).build_report(RUN_ID)

        self.assertEqual(report.trades_count, 0)
        self.assertIn("insufficient_data", report.warnings)
        self.assertEqual(report.candidate_adjustments, [])

    def test_report_uses_metric_registry(self) -> None:
        registry = _SpyMetricRegistry()
        report = _builder([_trade("trade-1"), _trade("trade-2", realized_r=-1.0)], registry=registry).build_report(RUN_ID)

        self.assertGreater(len(registry.compute_calls), 0)
        self.assertTrue(any(metric["code"] == "winrate" for metric in report.summary_metrics))

    def test_api_returns_404_for_unknown_run_id(self) -> None:
        app.dependency_overrides[get_strategy_testing_service] = lambda: _MissingReportService()
        client = TestClient(app)

        try:
            response = client.get(f"/api/v1/strategy-tests/reports/{uuid4()}")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 404)


class _SpyMetricRegistry:
    def __init__(self) -> None:
        self._registry = build_base_metric_registry()
        self.compute_calls: list[dict[str, Any]] = []

    def compute(
        self,
        trades: Sequence[StrategyTestTrade],
        metric_set: Sequence[str] | None = None,
        group_by: Sequence[str] | None = None,
    ) -> list[MetricResult]:
        self.compute_calls.append({"metric_set": list(metric_set or []), "group_by": list(group_by or [])})
        return self._registry.compute(trades, metric_set=metric_set, group_by=group_by)


class _RunStore:
    def __init__(self, detail: StrategyTestRunDetailResponse) -> None:
        self._detail = detail

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        if run_id != self._detail.run.run_id:
            return None
        return self._detail

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        _ = user_id, status
        return [self._detail][:limit]


class _AnalyticsStore:
    def __init__(self, trades: Sequence[StrategyTestTrade]) -> None:
        self._trades = list(trades)

    def list_trades(self, run_id: UUID) -> list[StrategyTestTrade]:
        _ = run_id
        return list(self._trades)


class _MissingReportService:
    def build_report(self, run_id: UUID) -> StrategyTestReport:
        raise ValueError(f"Strategy test run is not found: {run_id}")


def _builder(
    trades: Sequence[StrategyTestTrade],
    *,
    registry: MetricRegistry | _SpyMetricRegistry | None = None,
) -> StrategyTestReportBuilder:
    detail = StrategyTestRunDetailResponse(
        run=StrategyTestRunResponse(
            run_id=RUN_ID,
            status="completed",
            requested_matrix={
                "user_id": "demo_user",
                "mode": "research_virtual",
                "strategies": ["trend_pullback_continuation", "volatility_squeeze_breakout"],
                "pairs": [{"exchange": "bybit", "symbol": "BTCUSDT"}],
                "timeframes": ["1h"],
                "start_at": NOW,
                "end_at": NOW + timedelta(days=1),
                "initial_capital": "1000",
                "fee_rate": "0.001",
                "slippage_bps": "0",
                "same_candle_policy": "stop_first",
                "params": {},
                "scenario_count": 2,
            },
        )
    )
    return StrategyTestReportBuilder(
        run_store=_RunStore(detail),
        analytics_store=_AnalyticsStore(trades),
        metric_registry=registry,  # type: ignore[arg-type]
    )


def _section(report: StrategyTestReport, name: str):
    return next(section for section in report.sections if section.name == name)


def _trade(
    trade_id: str,
    *,
    strategy: str = "trend_pullback_continuation",
    score_bucket: str = "80-89",
    timeframe: str = "1h",
    direction: str = "long",
    market_regime: str = "trend",
    realized_r: float | None = 1.0,
    close_reason: str | None = None,
) -> StrategyTestTrade:
    offset = int(trade_id.rsplit("-", 1)[-1])
    entry_time = NOW + timedelta(hours=offset)
    return StrategyTestTrade(
        run_id=RUN_ID,
        trade_id=trade_id,
        user_id=USER_ID,
        mode="research_virtual",
        strategy_code=strategy,
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe=timeframe,
        direction=direction,
        signal_score=80.0,
        market_regime=market_regime,
        score_bucket=score_bucket,
        entry_time=entry_time,
        exit_time=entry_time + timedelta(hours=1),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        stop_loss=Decimal("99"),
        targets=[
            {"label": "TP1", "price": "101", "hit": bool(realized_r is not None and realized_r > 0)},
            {"label": "TP2", "price": "102", "hit": False},
        ],
        selected_rr=1.0,
        realized_r=realized_r,
        pnl=Decimal("10") if realized_r is None else Decimal(str(realized_r * 10)),
        pnl_pct=0.01 if realized_r is None else realized_r / 100,
        fees=Decimal("0.1"),
        slippage=Decimal("0.05"),
        mfe_r=1.2 if realized_r is not None and realized_r > 0 else 0.2,
        mae_r=-0.2 if realized_r is not None and realized_r > 0 else -0.9,
        bars_to_entry=1,
        bars_in_trade=3,
        close_reason=close_reason or ("stop_loss" if realized_r is not None and realized_r < 0 else "take_profit"),
        outcome="loss" if realized_r is not None and realized_r < 0 else "win",
        risk_rejected=False,
        execution_rejected=False,
        warnings=[],
        features_snapshot={},
        trade_plan={},
        tags=["backtest"],
        created_at=entry_time + timedelta(hours=1),
    )


if __name__ == "__main__":
    unittest.main()
