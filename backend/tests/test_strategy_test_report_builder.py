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
    StrategyTestFunnelResponse,
    StrategyTestMetricRow,
    StrategyTestReport,
    StrategyTestRunDetailResponse,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignalEvent,
    StrategyTestSignalEventsSummary,
    StrategyTestTrade,
    StrategyTestTradesSummary,
)


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)

REQUIRED_SECTION_NAMES = {
    "Summary",
    "Scenario diagnostics",
    "Signal funnel",
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

    def test_empty_analytics_report_uses_run_summary_funnel(self) -> None:
        report = _builder(
            [],
            summary={
                "scenario_count": 3,
                "completed_scenarios": 3,
                "failed_scenarios": 0,
                "trades_count": 0,
                "signals_seen": 4,
                "signals_count": 4,
                "execution_candidates": 3,
                "pending_armed": 2,
                "touched": 1,
                "entry_touched": 1,
                "filled": 0,
                "closed": 0,
                "no_entry": 3,
                "risk_rejections": 1,
                "execution_rejections": 1,
                "errors": [],
            },
        ).build_report(RUN_ID)

        self.assertEqual(report.trades_count, 0)
        self.assertEqual(report.summary["trades_count"], 0)
        self.assertEqual(report.summary["signals_count"], 4)
        self.assertEqual(report.summary["completed_scenarios"], 3)
        self.assertEqual(report.summary["pending_armed"], 2)
        self.assertEqual(report.summary["touched"], 1)
        self.assertEqual(report.summary["signal_funnel"]["signals_count"], 4)
        self.assertEqual(report.summary["signal_funnel"]["no_entry"], 3)
        self.assertTrue(any(metric["code"] == "trades_count" for metric in report.summary_metrics))

    def test_failed_run_report_uses_runtime_partial_summary_and_error(self) -> None:
        report = _builder(
            [],
            status="failed",
            error="ClickHouse write failed",
            runtime_state={
                "partial_summary": {
                    "scenario_count": 2,
                    "completed_scenarios": 1,
                    "failed_scenarios": 1,
                    "trades_count": 0,
                    "signals_seen": 5,
                    "signals_count": 5,
                    "execution_candidates": 4,
                    "pending_armed": 2,
                    "touched": 1,
                    "filled": 0,
                    "closed": 0,
                    "no_entry": 4,
                    "risk_rejections": 1,
                    "execution_rejections": 0,
                    "errors": [{"strategy": "s2", "error": "boom"}],
                },
                "last_error": "ClickHouse write failed",
            },
        ).build_report(RUN_ID)

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.summary["error"], "ClickHouse write failed")
        self.assertEqual(report.summary["partial_summary"]["completed_scenarios"], 1)
        self.assertEqual(report.summary["completed_scenarios"], 1)
        self.assertEqual(report.summary["failed_scenarios"], 1)
        self.assertEqual(report.summary["signals_count"], 5)

    def test_report_exposes_scenario_diagnostics_from_summary(self) -> None:
        report = _builder(
            [],
            summary={
                "scenario_count": 3,
                "completed_scenarios": 2,
                "failed_scenarios": 1,
                "errors": [{"strategy": "s3", "exchange": "bybit", "symbol": "ETHUSDT", "timeframe": "1h", "error": "no_historical_data"}],
                "scenarios": [
                    {
                        "strategy": "s1",
                        "exchange": "bybit",
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "status": "completed",
                        "bars_total": 1500,
                        "signals_seen": 0,
                        "signals_count": 0,
                        "trades_count": 0,
                    },
                    {
                        "strategy": "s2",
                        "exchange": "bybit",
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "status": "completed",
                        "bars_total": 1500,
                        "signals_seen": 4,
                        "signals_count": 4,
                        "execution_candidates": 3,
                        "entry_touched": 2,
                        "filled": 2,
                        "closed": 2,
                        "trades_count": 2,
                        "wins": 1,
                        "losses": 1,
                        "expectancy_r": 0.15,
                    },
                ],
            },
        ).build_report(RUN_ID)

        diagnostics = _section(report, "Scenario diagnostics")

        self.assertEqual(report.scenario_summaries, report.summary["scenario_summaries"])
        self.assertEqual(report.summary["scenarios_total"], 3)
        self.assertEqual(report.summary["scenarios_completed"], 2)
        self.assertEqual(report.summary["scenarios_failed"], 1)
        self.assertEqual(report.summary["errors_count"], 1)
        self.assertEqual(len(diagnostics.rows), 3)
        self.assertEqual([row["status"] for row in diagnostics.rows], ["completed", "completed", "failed"])
        self.assertEqual(diagnostics.rows[0]["signals_count"], 0)
        self.assertEqual(diagnostics.rows[2]["error"], "no_historical_data")

    def test_report_marks_zero_signal_scenario_below_strategy_min_history(self) -> None:
        report = _builder(
            [],
            summary={
                "scenario_count": 1,
                "completed_scenarios": 1,
                "scenarios": [
                    {
                        "strategy": "trend_pullback_continuation",
                        "exchange": "bybit",
                        "symbol": "BTCUSDT",
                        "timeframe": "5m",
                        "status": "completed",
                        "bars_total": 33,
                        "signals_seen": 0,
                        "signals_count": 0,
                        "trades_count": 0,
                    },
                ],
            },
        ).build_report(RUN_ID)

        diagnostics = _section(report, "Scenario diagnostics")

        self.assertIn("market_data_below_strategy_min_history", report.warnings)
        self.assertIn("warnings", diagnostics.rows[0])
        self.assertTrue(
            any(
                str(warning).startswith("market_data_below_strategy_min_history")
                for warning in diagnostics.rows[0]["warnings"]
            )
        )

    def test_partial_report_uses_runtime_partial_scenario_diagnostics(self) -> None:
        report = _builder(
            [],
            status="running",
            runtime_state={
                "partial_summary": {
                    "scenario_count": 2,
                    "completed_scenarios": 1,
                    "failed_scenarios": 1,
                    "signals_count": 0,
                    "trades_count": 0,
                    "scenarios": [
                        {
                            "strategy": "s1",
                            "exchange": "bybit",
                            "symbol": "BTCUSDT",
                            "timeframe": "15m",
                            "status": "completed",
                            "bars_total": 900,
                            "signals_count": 0,
                            "trades_count": 0,
                        }
                    ],
                    "errors": [
                        {
                            "strategy": "s2",
                            "exchange": "bybit",
                            "symbol": "ETHUSDT",
                            "timeframe": "15m",
                            "error": "not_enough_data",
                        }
                    ],
                }
            },
        ).build_report(RUN_ID)

        diagnostics = _section(report, "Scenario diagnostics")

        self.assertTrue(report.is_partial)
        self.assertEqual(report.summary["scenario_summaries"][0]["status"], "completed")
        self.assertEqual(report.summary["scenario_summaries"][1]["status"], "failed")
        self.assertEqual(diagnostics.rows[1]["error"], "not_enough_data")

    def test_running_report_infers_completed_scenarios_from_written_rows(self) -> None:
        report = _builder(
            [_trade("trade-1", strategy="trend_pullback_continuation")],
            status="running",
            signal_events=[
                _signal_event("signal-1", entry_touched=True, filled=True, closed=True, outcome="win"),
            ],
        ).build_report(RUN_ID)

        self.assertEqual(report.status, "running")
        self.assertEqual(report.summary["completed_scenarios"], 1)
        self.assertEqual(report.summary["trades_count"], 1)
        self.assertEqual(report.summary["signals_count"], 1)
        self.assertTrue(report.is_partial)
        self.assertEqual(report.data_completeness, "partial")
        self.assertEqual(report.summary["data_completeness"], "partial")

    def test_completed_report_is_marked_complete(self) -> None:
        report = _builder([_trade("trade-1")]).build_report(RUN_ID)

        self.assertFalse(report.is_partial)
        self.assertEqual(report.data_completeness, "complete")
        self.assertEqual(report.summary["data_completeness"], "complete")

    def test_large_signal_report_uses_aggregate_summary_without_capped_event_list(self) -> None:
        signal_events = [_signal_event(f"signal-{index}") for index in range(10050)]
        analytics_store = _AnalyticsStore(
            [],
            signal_events,
            signal_summary=StrategyTestSignalEventsSummary(
                run_id=RUN_ID,
                signals_count=12050,
                execution_candidates=8000,
                entry_touched=5000,
                filled=4500,
                closed=4400,
                wins=2400,
                losses=2000,
                no_entry=3000,
                risk_rejected=250,
                execution_rejected=150,
                false_signals=3000,
                groups=[
                    {
                        "strategy_code": "trend_pullback_continuation",
                        "exchange": "bybit",
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "direction": "long",
                        "market_regime": "trend",
                        "score_bucket": "80-89",
                        "signals_count": 12050,
                        "execution_candidates": 8000,
                        "entry_touched": 5000,
                        "filled": 4500,
                        "closed": 4400,
                        "wins": 2400,
                        "losses": 2000,
                        "no_entry": 3000,
                        "risk_rejected": 250,
                        "execution_rejected": 150,
                        "false_signals": 3000,
                    }
                ],
            ),
        )

        report = _builder([], analytics_store=analytics_store).build_report(RUN_ID)

        self.assertEqual(report.summary["signals_count"], 12050)
        self.assertEqual(report.summary["signal_funnel"]["signals_count"], 12050)
        self.assertEqual(analytics_store.list_signal_events_calls, 0)
        self.assertEqual(analytics_store.list_signal_event_samples_calls, 1)
        self.assertEqual(analytics_store.summarize_funnel_calls, 0)

    def test_completed_report_uses_persisted_metric_rows(self) -> None:
        registry = _SpyMetricRegistry()
        analytics_store = _AnalyticsStore(
            [],
            metric_rows=[
                _metric_row("signals_count", 12050, sample_size=12050),
                _metric_row("trades_count", 40, sample_size=40),
                _metric_row(
                    "expectancy_after_costs_r",
                    0.24,
                    group={
                        "strategy": "trend_pullback_continuation",
                        "exchange": "bybit",
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "regime": "trend",
                        "score_bucket": "80-89",
                        "direction": "long",
                    },
                    sample_size=40,
                ),
            ],
            signal_summary=StrategyTestSignalEventsSummary(
                run_id=RUN_ID,
                signals_count=12050,
                execution_candidates=8000,
                entry_touched=5000,
                no_entry=3000,
            ),
            trade_summary=StrategyTestTradesSummary(
                run_id=RUN_ID,
                trades_count=40,
                executed_trades_count=40,
                wins=28,
                losses=12,
                realized_r_sum=9.6,
                realized_r_count=40,
            ),
        )

        report = _builder([], analytics_store=analytics_store, registry=registry).build_report(RUN_ID)

        self.assertEqual(analytics_store.list_report_metric_rows_calls, 1)
        self.assertEqual(analytics_store.list_metric_rows_calls, 0)
        self.assertEqual(registry.compute_calls, [])
        self.assertEqual(report.summary["signals_count"], 12050)
        self.assertEqual(report.trades_count, 40)
        self.assertNotIn("insufficient_data", report.warnings)
        self.assertNotIn("signal_events_capped", report.warnings)
        self.assertTrue(any(metric["code"] == "signals_count" and metric["value"] == 12050 for metric in report.summary_metrics))
        self.assertTrue(
            any(
                metric["code"] == "expectancy_after_costs_r"
                and metric["group"].get("strategy") == "trend_pullback_continuation"
                for metric in report.grouped_metrics
            )
        )

    def test_completed_report_prefers_report_metric_rows_and_compacts_metric_payload(self) -> None:
        metric_rows = [
            _metric_row("signals_count", 12050, sample_size=12050),
            _metric_row("trades_count", 40, sample_size=40),
            *[
                _metric_row(
                    "expectancy_after_costs_r",
                    0.1,
                    group={
                        "strategy": "trend_pullback_continuation",
                        "exchange": "bybit",
                        "symbol": f"PAIR{index}USDT",
                        "timeframe": "1h",
                        "regime": "trend",
                        "score_bucket": "80-89",
                        "direction": "long",
                    },
                    sample_size=1,
                )
                for index in range(120)
            ],
        ]
        analytics_store = _AnalyticsStore(
            [],
            metric_rows=metric_rows,
            signal_summary=StrategyTestSignalEventsSummary(
                run_id=RUN_ID,
                signals_count=12050,
                execution_candidates=8000,
                entry_touched=5000,
                no_entry=3000,
            ),
            trade_summary=StrategyTestTradesSummary(
                run_id=RUN_ID,
                trades_count=40,
                executed_trades_count=40,
                wins=28,
                losses=12,
                realized_r_sum=9.6,
                realized_r_count=40,
            ),
        )

        report = _builder([], analytics_store=analytics_store).build_report(RUN_ID)

        self.assertEqual(analytics_store.list_report_metric_rows_calls, 1)
        self.assertEqual(analytics_store.list_metric_rows_calls, 0)
        self.assertLess(len(report.metrics), len(metric_rows))
        self.assertEqual(report.metrics, report.summary_metrics)
        self.assertLessEqual(len(report.grouped_metrics), 50)

    def test_completed_report_summary_prefers_aggregate_counts_over_persisted_all_metric_rows(self) -> None:
        analytics_store = _AnalyticsStore(
            [],
            metric_rows=[
                _metric_row("signals_count", 437, sample_size=437),
                _metric_row("trades_count", 1, sample_size=1),
                _metric_row("expectancy_r", 0.1, sample_size=1),
                _metric_row(
                    "expectancy_after_costs_r",
                    0.2,
                    group={
                        "strategy": "trend_pullback_continuation",
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                    },
                    sample_size=4,
                ),
            ],
            signal_summary=StrategyTestSignalEventsSummary(
                run_id=RUN_ID,
                signals_count=4775,
                execution_candidates=10,
                entry_touched=8,
                filled=6,
                closed=5,
                no_entry=2,
            ),
            trade_summary=StrategyTestTradesSummary(
                run_id=RUN_ID,
                trades_count=60,
                executed_trades_count=60,
                wins=30,
                losses=30,
                realized_r_sum=12.0,
                realized_r_count=60,
                pnl_total=100.0,
                fees_total=2.0,
                slippage_total=1.0,
            ),
        )

        report = _builder([], analytics_store=analytics_store).build_report(RUN_ID)

        self.assertEqual(report.summary["signals_count"], 4775)
        self.assertEqual(report.summary["trades_count"], 60)
        self.assertEqual(report.trades_count, 60)
        self.assertEqual(report.summary["expectancy_r"], 0.2)
        self.assertTrue(
            any(
                metric["code"] == "expectancy_after_costs_r"
                and metric["group"].get("symbol") == "BTCUSDT"
                for metric in report.grouped_metrics
            )
        )

    def test_duplicate_event_keys_are_not_double_counted_when_aggregate_is_available(self) -> None:
        duplicate_events = [
            _signal_event("signal-1", no_entry=True, outcome="no_entry", funnel_stage="no_entry"),
            _signal_event("signal-1", no_entry=True, outcome="no_entry", funnel_stage="no_entry"),
        ]
        analytics_store = _AnalyticsStore(
            [],
            duplicate_events,
            signal_summary=StrategyTestSignalEventsSummary(
                run_id=RUN_ID,
                signals_count=1,
                execution_candidates=1,
                no_entry=1,
                false_signals=1,
            ),
        )

        report = _builder([], analytics_store=analytics_store).build_report(RUN_ID)

        self.assertEqual(report.summary["signals_count"], 1)
        self.assertEqual(report.summary["signal_funnel"]["no_entry"], 1)
        self.assertEqual(analytics_store.list_signal_events_calls, 0)

    def test_forward_report_uses_durable_events_not_runtime_pending_snapshot(self) -> None:
        terminal_entries = [
            {"signal_id": f"terminal-{index}", "status": "expired", "reason_code": "entry_not_touched"}
            for index in range(200)
        ]
        analytics_store = _AnalyticsStore(
            [],
            [_signal_event("durable-1", no_entry=True, outcome="no_entry", funnel_stage="no_entry")],
            signal_summary=StrategyTestSignalEventsSummary(
                run_id=RUN_ID,
                signals_count=250,
                execution_candidates=250,
                no_entry=250,
                false_signals=250,
            ),
        )

        report = _builder(
            [],
            analytics_store=analytics_store,
            status="running",
            runtime_state={
                "status": "listening",
                "pending_entries": terminal_entries,
                "pending_entries_count": len(terminal_entries),
            },
        ).build_report(RUN_ID)

        self.assertEqual(report.summary["signals_count"], 250)
        self.assertEqual(report.summary["signal_funnel"]["no_entry"], 250)
        self.assertEqual(report.summary["pending_armed"], 0)
        self.assertNotIn("pending_entries", report.summary)
        self.assertEqual(analytics_store.list_signal_events_calls, 0)
        self.assertEqual(analytics_store.list_signal_event_samples_calls, 1)

    def test_signal_funnel_section_lists_no_entry_signals(self) -> None:
        report = _builder(
            [],
            signal_events=[
                _signal_event("signal-1", no_entry=True, outcome="no_entry", funnel_stage="no_entry"),
                _signal_event("signal-2", entry_touched=True, filled=True, closed=True, outcome="win"),
            ],
        ).build_report(RUN_ID)

        section = _section(report, "Signal funnel")

        self.assertEqual(report.summary["signals_count"], 2)
        self.assertEqual(section.summary["no_entry"], 1)
        self.assertEqual(section.rows[0]["synthetic_signal_id"], "signal-1")
        self.assertEqual(section.metadata["row_filter"], "no_entry")

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

    def test_api_returns_500_response_when_report_builder_crashes(self) -> None:
        app.dependency_overrides[get_strategy_testing_service] = lambda: _CrashingReportService()
        client = TestClient(app)

        try:
            response = client.get(f"/api/v1/strategy-tests/reports/{RUN_ID}")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Strategy test report failed")


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

    def compute_with_signals(
        self,
        trades: Sequence[StrategyTestTrade],
        *,
        signal_events: Sequence[StrategyTestSignalEvent] = (),
        metric_set: Sequence[str] | None = None,
        group_by: Sequence[str] | None = None,
    ) -> list[MetricResult]:
        self.compute_calls.append({"metric_set": list(metric_set or []), "group_by": list(group_by or [])})
        return self._registry.compute_with_signals(
            trades,
            signal_events=signal_events,
            metric_set=metric_set,
            group_by=group_by,
        )


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
    def __init__(
        self,
        trades: Sequence[StrategyTestTrade],
        signal_events: Sequence[StrategyTestSignalEvent] = (),
        *,
        metric_rows: Sequence[StrategyTestMetricRow] = (),
        signal_summary: StrategyTestSignalEventsSummary | None = None,
        trade_summary: StrategyTestTradesSummary | None = None,
    ) -> None:
        self._trades = list(trades)
        self._signal_events = list(signal_events)
        self._metric_rows = list(metric_rows)
        self._signal_summary = signal_summary
        self._trade_summary = trade_summary
        self.list_signal_events_calls = 0
        self.list_signal_event_samples_calls = 0
        self.list_metric_rows_calls = 0
        self.list_report_metric_rows_calls = 0
        self.summarize_funnel_calls = 0

    def list_trades(self, run_id: UUID) -> list[StrategyTestTrade]:
        _ = run_id
        return list(self._trades)

    def list_trade_samples(
        self,
        run_id: UUID,
        limit: int = 500,
        offset: int = 0,
    ) -> list[StrategyTestTrade]:
        _ = run_id
        return list(self._trades)[offset : offset + limit]

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        _ = run_id
        self.list_signal_events_calls += 1
        return list(self._signal_events)[offset : offset + limit]

    def list_signal_event_samples(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        _ = run_id
        self.list_signal_event_samples_calls += 1
        return list(self._signal_events)[offset : offset + limit]

    def list_metric_rows(self, run_id: UUID) -> list[StrategyTestMetricRow]:
        _ = run_id
        self.list_metric_rows_calls += 1
        return list(self._metric_rows)

    def list_report_metric_rows(self, run_id: UUID) -> list[StrategyTestMetricRow]:
        _ = run_id
        self.list_report_metric_rows_calls += 1
        return list(self._metric_rows)

    def summarize_signal_events(self, run_id: UUID) -> StrategyTestSignalEventsSummary:
        _ = run_id
        if self._signal_summary is None:
            raise NotImplementedError
        return self._signal_summary

    def summarize_trades(self, run_id: UUID) -> StrategyTestTradesSummary:
        _ = run_id
        if self._trade_summary is None:
            raise NotImplementedError
        return self._trade_summary

    def summarize_funnel(self, run_id: UUID) -> StrategyTestFunnelResponse:
        self.summarize_funnel_calls += 1
        summary = self.summarize_signal_events(run_id)
        return StrategyTestFunnelResponse(
            run_id=run_id,
            signals_count=summary.signals_count,
            execution_candidates=summary.execution_candidates,
            entry_touched=summary.entry_touched,
            filled=summary.filled,
            closed=summary.closed,
            wins=summary.wins,
            losses=summary.losses,
            no_entry=summary.no_entry,
            risk_rejected=summary.risk_rejected,
            execution_rejected=summary.execution_rejected,
            entry_touch_rate=summary.entry_touched / summary.signals_count if summary.signals_count else None,
            no_entry_rate=summary.no_entry / summary.signals_count if summary.signals_count else None,
            risk_rejection_rate=summary.risk_rejected / summary.signals_count if summary.signals_count else None,
            execution_rejection_rate=(
                summary.execution_rejected / summary.execution_candidates if summary.execution_candidates else None
            ),
            false_signal_rate=summary.false_signals / summary.signals_count if summary.signals_count else None,
        )


class _MissingReportService:
    def build_report(self, run_id: UUID, *, user_id: str | None = None) -> StrategyTestReport:
        _ = user_id
        raise ValueError(f"Strategy test run is not found: {run_id}")


class _CrashingReportService:
    def build_report(self, run_id: UUID, *, user_id: str | None = None) -> StrategyTestReport:
        _ = run_id, user_id
        raise RuntimeError("analytics store is unavailable")


def _builder(
    trades: Sequence[StrategyTestTrade],
    *,
    analytics_store: _AnalyticsStore | None = None,
    error: str | None = None,
    signal_events: Sequence[StrategyTestSignalEvent] = (),
    registry: MetricRegistry | _SpyMetricRegistry | None = None,
    runtime_state: dict[str, Any] | None = None,
    status: StrategyTestRunStatus = "completed",
    summary: dict[str, Any] | None = None,
) -> StrategyTestReportBuilder:
    detail = StrategyTestRunDetailResponse(
        run=StrategyTestRunResponse(
            run_id=RUN_ID,
            status=status,
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
            summary=dict(summary or {}),
            runtime_state=dict(runtime_state or {}),
            error=error,
        )
    )
    return StrategyTestReportBuilder(
        run_store=_RunStore(detail),
        analytics_store=analytics_store or _AnalyticsStore(trades, signal_events),
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


def _signal_event(
    synthetic_signal_id: str,
    *,
    entry_touched: bool = False,
    filled: bool = False,
    closed: bool = False,
    outcome: str | None = None,
    funnel_stage: str = "signal",
    no_entry: bool = False,
) -> StrategyTestSignalEvent:
    return StrategyTestSignalEvent(
        run_id=RUN_ID,
        user_id=USER_ID,
        mode="research_virtual",
        test_type="historical_backtest",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="long",
        signal_id=None,
        synthetic_signal_id=synthetic_signal_id,
        signal_key=f"trend_pullback_continuation:BTCUSDT:{synthetic_signal_id}",
        event_time=NOW,
        candle_time=NOW,
        signal_score=82.0,
        market_regime="trend",
        score_bucket="80-89",
        status="actionable",
        gate_status="passed",
        feed_kind="execution_signal",
        trigger_passed=True,
        trigger_reason_code=None,
        execution_candidate=True,
        entry_touched=entry_touched,
        filled=filled,
        closed=closed,
        outcome=outcome,
        funnel_stage=funnel_stage,
        risk_rejected=False,
        execution_rejected=False,
        no_entry=no_entry,
        rejection_reason_code=None,
        blocked_reason_code=None,
        selected_rr=2.0,
        entry_min=Decimal("100"),
        entry_max=Decimal("100"),
        stop_loss=Decimal("99"),
        features_snapshot={},
        trade_plan={},
        metadata={},
        tags=["backtest"],
        created_at=NOW,
    )


def _metric_row(
    metric_code: str,
    value: float | int | None,
    *,
    group: dict[str, str] | None = None,
    sample_size: int = 1,
) -> StrategyTestMetricRow:
    group = dict(group or {"all": "all"})
    return StrategyTestMetricRow(
        run_id=RUN_ID,
        user_id=USER_ID,
        mode="research_virtual",
        strategy_code=group.get("strategy", "all"),
        exchange=group.get("exchange", "all"),
        symbol=group.get("symbol", "all"),
        timeframe=group.get("timeframe", "all"),
        market_regime=group.get("regime", "all"),
        score_bucket=group.get("score_bucket", "all"),
        direction=group.get("direction", "all"),
        metric_code=metric_code,
        metric_value=float(value) if value is not None else None,
        sample_size=sample_size,
        metadata={},
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
