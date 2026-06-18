from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID, uuid4
import unittest

from app.schemas.backtest import BacktestRunResult
from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features
from app.core.config import settings
from app.services.backtest_runner import (
    BacktestDetailedRunResult,
    BacktestRunCancelled,
    DEFAULT_WARMUP_CANDLES,
    ProductionBacktestRunner,
)
from app.services.strategy_testing.assumptions import build_strategy_test_assumptions
from app.services.strategy_testing.matrix_runner import (
    StrategyTestMatrixResult,
    StrategyTestMatrixRunner,
    StrategyTestScenarioContext,
)
from app.services.strategy_testing.report_builder import StrategyTestReportBuilder
from app.services.strategy_testing.runner import StrategyTestScenarioResult, StrategyTestScenarioRunner
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestRuntimeState,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)
from app.services.strategy_testing.service import StrategyTestingService, _scenario_runtime_state


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")


class StrategyTestMatrixRunnerTest(unittest.TestCase):
    def test_runtime_state_schema_accepts_historical_progress_contract(self) -> None:
        state = StrategyTestRuntimeState.model_validate(
            {
                "scenarios_total": 16,
                "scenarios_completed": 2,
                "scenarios_failed": 1,
                "current_scenario_index": 3,
                "current_scenario_key": "s1::bybit::BTCUSDT::15m",
                "current_scenario_bars_processed": 49750,
                "current_scenario_bars_total": 86597,
                "matrix_bars_processed": 149750,
                "matrix_bars_total": 386597,
                "bars_pct": 38.74,
                "elapsed_seconds": 120.5,
                "bars_per_second": 1242.73,
                "eta_seconds": 190.4,
                "phase": "running_scenario",
                "last_progress_at": "2026-06-02T00:01:00+00:00",
                "last_heartbeat_at": "2026-06-02T00:01:05+00:00",
                "stale_threshold_seconds": 900,
                "counters": {
                    "signals": 30,
                    "execution_candidates": 20,
                    "pending_armed": 8,
                    "pending_entries": 2,
                    "no_entry": 4,
                    "filled": 3,
                    "closed": 2,
                    "risk_rejections": 1,
                    "execution_rejections": 5,
                },
            }
        )

        dumped = state.model_dump(mode="json")
        self.assertEqual(dumped["scenarios_total"], 16)
        self.assertEqual(dumped["current_scenario_bars_processed"], 49750)
        self.assertEqual(dumped["matrix_bars_processed"], 149750)
        self.assertEqual(dumped["counters"]["signals"], 30)

    def test_matrix_expands_three_strategies_ten_pairs_three_timeframes(self) -> None:
        request = _matrix_request(
            strategies=["s1", "s2", "s3"],
            pairs=[StrategyTestPair(exchange="bybit", symbol=f"COIN{index}USDT") for index in range(10)],
            timeframes=["1m", "5m", "1h"],
        )
        scenario_runner = _RecordingScenarioRunner()
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.scenario_count, 90)
        self.assertEqual(result.completed_scenarios, 90)
        self.assertEqual(len(scenario_runner.calls), 90)
        expected_calls = [
            (strategy, pair.exchange, pair.symbol, timeframe)
            for pair in request.pairs
            for timeframe in request.timeframes
            for strategy in request.strategies
        ]
        self.assertEqual(scenario_runner.calls, expected_calls)

    def test_matrix_prepares_market_data_once_per_pair_timeframe(self) -> None:
        request = _matrix_request(
            strategies=["s1", "s2", "s3"],
            pairs=[
                StrategyTestPair(exchange="bybit", symbol="BTCUSDT"),
                StrategyTestPair(exchange="bybit", symbol="ETHUSDT"),
            ],
            timeframes=["15m", "1h"],
        )
        scenario_runner = _RecordingScenarioRunner()
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.completed_scenarios, 12)
        self.assertEqual(
            scenario_runner.prepare_calls,
            [
                ("bybit", "BTCUSDT", "15m"),
                ("bybit", "BTCUSDT", "1h"),
                ("bybit", "ETHUSDT", "15m"),
                ("bybit", "ETHUSDT", "1h"),
            ],
        )
        self.assertEqual(
            scenario_runner.calls,
            [
                (strategy, pair.exchange, pair.symbol, timeframe)
                for pair in request.pairs
                for timeframe in request.timeframes
                for strategy in request.strategies
            ],
        )

    def test_matrix_marks_all_strategies_failed_when_market_data_prepare_fails(self) -> None:
        request = _matrix_request(
            strategies=["s1", "s2"],
            pairs=[
                StrategyTestPair(exchange="bybit", symbol="ETHUSDT"),
                StrategyTestPair(exchange="bybit", symbol="BTCUSDT"),
            ],
            timeframes=["15m"],
        )
        scenario_runner = _RecordingScenarioRunner(prepare_fail_on={("bybit", "ETHUSDT", "15m")})
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.completed_scenarios, 2)
        self.assertEqual(result.failed_scenarios, 2)
        self.assertEqual(
            scenario_runner.calls,
            [
                ("s1", "bybit", "BTCUSDT", "15m"),
                ("s2", "bybit", "BTCUSDT", "15m"),
            ],
        )
        self.assertEqual([error["symbol"] for error in result.errors], ["ETHUSDT", "ETHUSDT"])
        self.assertEqual({error["strategy"] for error in result.errors}, {"s1", "s2"})
        self.assertTrue(all("market data prepare failed" in error["error"] for error in result.errors))

    def test_matrix_records_failed_scenarios_in_diagnostics_summary(self) -> None:
        request = _matrix_request(
            strategies=["s1", "s2"],
            pairs=[StrategyTestPair(exchange="bybit", symbol="ETHUSDT")],
            timeframes=["15m"],
        )
        scenario_runner = _RecordingScenarioRunner(prepare_fail_on={("bybit", "ETHUSDT", "15m")})
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.completed_scenarios, 0)
        self.assertEqual(result.failed_scenarios, 2)
        self.assertEqual(len(result.scenario_summaries), 2)
        self.assertEqual({row["status"] for row in result.scenario_summaries}, {"failed"})
        self.assertEqual({row["strategy"] for row in result.scenario_summaries}, {"s1", "s2"})
        self.assertTrue(all(row["bars_total"] == 0 for row in result.scenario_summaries))
        self.assertTrue(all("market data prepare failed" in row["error"] for row in result.scenario_summaries))
        self.assertEqual(result.summary()["scenario_summaries"], result.scenario_summaries)

    def test_matrix_reports_market_data_prefetch_progress(self) -> None:
        request = _matrix_request(
            strategies=["s1"],
            pairs=[
                StrategyTestPair(exchange="bybit", symbol="BTCUSDT"),
                StrategyTestPair(exchange="bybit", symbol="ETHUSDT"),
            ],
            timeframes=["15m"],
        )
        scenario_runner = _RecordingScenarioRunner()
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)
        progress_updates: list[dict[str, Any]] = []

        matrix_runner.run_matrix(
            request=request,
            run_id=RUN_ID,
            user_uuid=USER_ID,
            on_scenario_progress=lambda _context, progress, _partial_summary: progress_updates.append(dict(progress)),
        )

        prefetch_updates = [
            update for update in progress_updates if update.get("phase") == "prefetching_market_data"
        ]
        self.assertGreaterEqual(len(prefetch_updates), 2)
        self.assertEqual(prefetch_updates[-1]["market_data_prefetch_total"], 2)
        self.assertEqual(prefetch_updates[-1]["market_data_prefetch_completed"], 2)
        self.assertEqual(prefetch_updates[-1]["market_data_prefetch_failed"], 0)
        self.assertIn(prefetch_updates[-1]["current_pair"], {"BTCUSDT", "ETHUSDT"})

    def test_matrix_does_not_count_all_pair_timeframes_before_processing(self) -> None:
        request = _matrix_request(
            strategies=["s1"],
            pairs=[
                StrategyTestPair(exchange="bybit", symbol="BTCUSDT"),
                StrategyTestPair(exchange="bybit", symbol="ETHUSDT"),
            ],
            timeframes=["15m", "1h"],
        )
        scenario_runner = _PreparingBarScenarioRunner(
            bars_per_pair_timeframe={
                ("bybit", "BTCUSDT", "15m"): 3,
                ("bybit", "BTCUSDT", "1h"): 4,
                ("bybit", "ETHUSDT", "15m"): 5,
                ("bybit", "ETHUSDT", "1h"): 6,
            }
        )
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.completed_scenarios, 4)
        self.assertEqual(scenario_runner.count_calls, [])
        self.assertEqual(
            scenario_runner.prepare_calls,
            [
                ("bybit", "BTCUSDT", "15m"),
                ("bybit", "BTCUSDT", "1h"),
                ("bybit", "ETHUSDT", "15m"),
                ("bybit", "ETHUSDT", "1h"),
            ],
        )

    def test_matrix_cancellation_stops_after_market_data_prepare(self) -> None:
        cancelled = False

        def cancel_after_prepare() -> None:
            nonlocal cancelled
            cancelled = True

        request = _matrix_request(
            strategies=["s1", "s2"],
            pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
            timeframes=["15m"],
        )
        scenario_runner = _RecordingScenarioRunner(on_prepare=cancel_after_prepare)
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(
            request=request,
            run_id=RUN_ID,
            user_uuid=USER_ID,
            is_cancelled=lambda: cancelled,
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(scenario_runner.prepare_calls, [("bybit", "BTCUSDT", "15m")])
        self.assertEqual(scenario_runner.calls, [])

    def test_matrix_skips_prepare_and_execution_for_completed_pair_timeframe_checkpoint(self) -> None:
        request = _matrix_request(
            strategies=["s1", "s2"],
            pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
            timeframes=["15m"],
        )
        scenario_runner = _RecordingScenarioRunner()
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(
            request=request,
            run_id=RUN_ID,
            user_uuid=USER_ID,
            completed_scenario_summaries={
                "s1::bybit::BTCUSDT::15m": {"signals_seen": 3, "trades_count": 1},
                "s2::bybit::BTCUSDT::15m": {"signals_seen": 4, "trades_count": 0},
            },
        )

        self.assertEqual(result.completed_scenarios, 2)
        self.assertEqual(scenario_runner.prepare_calls, [])
        self.assertEqual(scenario_runner.calls, [])
        self.assertEqual(result.summary()["signals_seen"], 7)

    def test_matrix_collects_partial_failures(self) -> None:
        request = _matrix_request(strategies=["s1", "s2"], pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")])
        scenario_runner = _RecordingScenarioRunner(fail_on={1})
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.completed_scenarios, 1)
        self.assertEqual(result.failed_scenarios, 1)
        self.assertFalse(result.all_failed)
        self.assertEqual(result.summary()["failed_scenarios"], 1)

    def test_matrix_marks_all_failed_when_every_scenario_errors(self) -> None:
        request = _matrix_request(strategies=["s1", "s2"], pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")])
        scenario_runner = _RecordingScenarioRunner(fail_on={0, 1})
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertTrue(result.all_failed)
        self.assertEqual(result.completed_scenarios, 0)
        self.assertEqual(result.failed_scenarios, 2)

    def test_matrix_builds_funnel_metrics_without_returning_signal_events(self) -> None:
        request = _matrix_request(strategies=["s1"], pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")])
        scenario_runner = _RecordingScenarioRunner(
            signal_events=[
                _signal_event("signal-1", entry_touched=True, filled=True, closed=True, outcome="win"),
                _signal_event("signal-2", no_entry=True, outcome="no_entry", funnel_stage="no_entry"),
            ]
        )
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.signal_events, [])
        self.assertEqual(result.summary()["signals_count"], 2)
        summary_metrics = {metric["code"]: metric for metric in result.summary()["summary_metrics"]}
        self.assertEqual(summary_metrics["signals_count"]["value"], 2)
        self.assertAlmostEqual(summary_metrics["entry_touch_rate"]["value"], 0.5)

    def test_matrix_summary_includes_slowest_scenarios(self) -> None:
        request = _matrix_request(strategies=["slow", "fast"])
        scenario_runner = _RecordingScenarioRunner(
            summary_overrides=[
                {"timings": {"bars_total": 100, "bars_per_second": 10.0, "total_ms": 10_000.0}},
                {"timings": {"bars_total": 100, "bars_per_second": 100.0, "total_ms": 1_000.0}},
            ]
        )
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        slowest = result.summary()["slowest_scenarios"]
        self.assertEqual(slowest[0]["strategy"], "slow")
        self.assertEqual(slowest[0]["total_ms"], 10_000.0)
        self.assertEqual(slowest[0]["bars_per_second"], 10.0)

    def test_matrix_reuses_candle_loads_for_same_pair_timeframe(self) -> None:
        candles = _historical_candles()
        provider = _CountingHistoricalCandleProvider(candles)
        backtest_runner = ProductionBacktestRunner(
            feature_engine=_SilentFeatureEngine(),  # type: ignore[arg-type]
            strategy_engine=_NoSignalStrategyEngine(),  # type: ignore[arg-type]
            historical_candle_provider=provider,
        )
        scenario_runner = StrategyTestScenarioRunner(backtest_runner)
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)
        request = _matrix_request(
            strategies=["trend_pullback_continuation", "volatility_squeeze_breakout"],
            params={"warmup_candles": 3, "rolling_window_candles": 3},
        )

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.completed_scenarios, 2)
        self.assertEqual(provider.load_calls, 1)

    def test_matrix_reports_progress_after_each_scenario(self) -> None:
        request = _matrix_request(strategies=["s1", "s2", "s3"])
        scenario_runner = _RecordingScenarioRunner()
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)
        completed: list[tuple[str, int, int]] = []

        result = matrix_runner.run_matrix(
            request=request,
            run_id=RUN_ID,
            user_uuid=USER_ID,
            on_scenario_completed=lambda context, _result, partial_summary: completed.append(
                (
                    context.strategy,
                    partial_summary["completed_scenarios"],
                    partial_summary["signals_seen"],
                )
            ),
        )

        self.assertEqual(result.completed_scenarios, 3)
        self.assertEqual(
            completed,
            [
                ("s1", 1, 1),
                ("s2", 2, 2),
                ("s3", 3, 3),
            ],
        )

    def test_matrix_logs_start_scenario_completion_and_finish(self) -> None:
        request = _matrix_request(strategies=["s1", "s2"])
        matrix_runner = StrategyTestMatrixRunner(_RecordingScenarioRunner())

        with self.assertLogs("app.services.strategy_testing.matrix_runner", level="INFO") as logs:
            result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(result.completed_scenarios, 2)
        log_output = "\n".join(logs.output)
        self.assertIn("Strategy test matrix started", log_output)
        self.assertIn(f"run_id={RUN_ID}", log_output)
        self.assertIn("scenario_count=2", log_output)
        self.assertIn("Strategy test matrix scenario completed", log_output)
        self.assertIn("scenario=1/2", log_output)
        self.assertIn("Strategy test matrix finished", log_output)
        self.assertIn("completed=2 failed=0", log_output)

    def test_matrix_progress_uses_matrix_wide_deduped_bar_total(self) -> None:
        request = _matrix_request(strategies=["s1", "s2"], timeframes=["15m"])
        scenario_runner = _PreparingBarScenarioRunner(bars_per_pair_timeframe={("bybit", "BTCUSDT", "15m"): 3})
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)
        progress_updates: list[tuple[int, int, int, int, int, int, int, int, int]] = []

        matrix_runner.run_matrix(
            request=request,
            run_id=RUN_ID,
            user_uuid=USER_ID,
            on_scenario_progress=lambda context, progress, _partial_summary: (
                progress_updates.append(
                    (
                        context.index,
                        progress["bars_processed"],
                        progress["bars_total"],
                        progress["scenario_bars_processed"],
                        progress["scenario_bars_total"],
                        progress["matrix_bars_processed"],
                        progress["matrix_bars_total"],
                        progress["current_scenario_bars_processed"],
                        progress["current_scenario_bars_total"],
                    )
                )
                if "scenario_bars_processed" in progress
                else None
            ),
        )

        self.assertEqual(
            progress_updates,
            [
                (1, 1, 6, 1, 3, 1, 6, 1, 3),
                (2, 4, 6, 1, 3, 4, 6, 1, 3),
            ],
        )
        self.assertEqual(scenario_runner.count_calls, [])
        self.assertEqual(scenario_runner.prepare_calls, [("bybit", "BTCUSDT", "15m")])

    def test_runtime_progress_sanitizes_eta_and_rates(self) -> None:
        context = StrategyTestScenarioContext(
            index=1,
            total=1,
            strategy="s1",
            pair=StrategyTestPair(exchange="bybit", symbol="BTCUSDT"),
            timeframe="15m",
        )

        state = _scenario_runtime_state(
            context=context,
            request=_matrix_request(strategies=["s1"], timeframes=["15m"]),
            phase="running_scenario",
            partial_summary={},
            progress={
                "bars_pct": -5,
                "bars_per_second": float("nan"),
                "eta_seconds": -12,
                "elapsed_seconds": -1,
            },
            scenario_status="running",
        )

        self.assertEqual(state["bars_pct"], 0.0)
        self.assertEqual(state["bars_per_second"], 0.0)
        self.assertEqual(state["eta_seconds"], 0.0)
        self.assertEqual(state["elapsed_seconds"], 0.0)

    def test_backtest_runner_cancels_inside_long_candle_loop(self) -> None:
        candles = _many_historical_candles(count=20)
        provider = _CountingHistoricalCandleProvider(candles)
        feature_engine = _CountingFeatureEngine()
        backtest_runner = ProductionBacktestRunner(
            feature_engine=feature_engine,  # type: ignore[arg-type]
            strategy_engine=_NoSignalStrategyEngine(),  # type: ignore[arg-type]
            historical_candle_provider=provider,
        )
        checks = 0

        def is_cancelled() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 2

        with self.assertRaises(BacktestRunCancelled):
            backtest_runner.run_detailed(
                _backtest_request(),
                mode="research_virtual",
                options={},
                is_cancelled=is_cancelled,
                progress_interval_bars=10_000,
            )

        self.assertLessEqual(feature_engine.calls, 1)

    def test_backtest_runner_prepare_market_data_ensures_without_loading_candles(self) -> None:
        provider = _CountingHistoricalCandleProvider(_historical_candles())
        backtest_runner = ProductionBacktestRunner(historical_candle_provider=provider)

        result = backtest_runner.prepare_market_data(
            _backtest_request(),
            mode="research_virtual",
            options={"warmup_candles": 3},
        )

        self.assertEqual(provider.ensure_calls, 1)
        self.assertEqual(provider.count_calls, 1)
        self.assertEqual(provider.load_calls, 0)
        self.assertEqual(result["candles_count"], 6)
        self.assertEqual(result["bars_total"], 3)

    def test_matrix_stops_before_next_scenario_when_cancelled(self) -> None:
        request = _matrix_request(strategies=["s1", "s2", "s3"])
        scenario_runner = _RecordingScenarioRunner()
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(
            request=request,
            run_id=RUN_ID,
            user_uuid=USER_ID,
            is_cancelled=lambda: len(scenario_runner.calls) >= 1,
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(result.completed_scenarios, 1)
        self.assertEqual(len(scenario_runner.calls), 1)

    def test_matrix_streams_large_scenario_result_without_returning_full_events(self) -> None:
        request = _matrix_request(strategies=["s1"])
        scenario_runner = _HighVolumeScenarioRunner(signal_events_count=150_000)
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)
        result_sink = _CapturingScenarioResultSink()

        result = matrix_runner.run_matrix(
            request=request,
            run_id=RUN_ID,
            user_uuid=USER_ID,
            scenario_result_sink=result_sink,
        )

        self.assertEqual(result.completed_scenarios, 1)
        self.assertEqual(result.signal_events, [])
        self.assertEqual(result.trades, [])
        self.assertEqual(result.summary()["signals_count"], 150_000)
        self.assertEqual(result_sink.signal_event_counts, [150_000])


class StrategyTestAssumptionsTest(unittest.TestCase):
    def test_discovery_mode_disables_hard_risk_assumptions(self) -> None:
        assumptions = build_strategy_test_assumptions(**_assumption_kwargs("discovery"))

        self.assertFalse(assumptions.risk_gate_enabled)
        self.assertFalse(assumptions.rr_hard_gate_enabled)

    def test_research_virtual_disables_rr_hard_gate_assumption(self) -> None:
        assumptions = build_strategy_test_assumptions(**_assumption_kwargs("research_virtual"))

        self.assertFalse(assumptions.rr_hard_gate_enabled)
        self.assertTrue(assumptions.virtual_execution_enabled)

    def test_production_like_enables_risk_gate_assumptions(self) -> None:
        assumptions = build_strategy_test_assumptions(**_assumption_kwargs("production_like"))

        self.assertTrue(assumptions.risk_gate_enabled)
        self.assertTrue(assumptions.rr_hard_gate_enabled)

    def test_production_like_can_explicitly_disable_rr_hard_gate(self) -> None:
        kwargs = _assumption_kwargs("production_like")
        kwargs["params"] = {"rr_hard_gate_enabled": False}

        assumptions = build_strategy_test_assumptions(**kwargs)

        self.assertTrue(assumptions.risk_gate_enabled)
        self.assertFalse(assumptions.rr_hard_gate_enabled)


class StrategyTestScenarioRunnerTest(unittest.TestCase):
    def test_scenario_runner_builds_backtest_request_and_passes_assumptions(self) -> None:
        backtest_runner = _FakeBacktestRunner()
        scenario_runner = StrategyTestScenarioRunner(backtest_runner)  # type: ignore[arg-type]
        request = _matrix_request(mode="production_like", params={"warmup_candles": 5})
        pair = StrategyTestPair(exchange="bybit", symbol="BTCUSDT")

        scenario_runner.run_scenario(
            run_id=RUN_ID,
            user_id=USER_ID,
            request=request,
            strategy="volatility_squeeze_breakout",
            pair=pair,
            timeframe="1h",
        )

        call = backtest_runner.calls[0]
        self.assertEqual(call.request.strategy_code, "volatility_squeeze_breakout")
        self.assertEqual(call.request.exchange, "bybit")
        self.assertEqual(call.request.symbol, "BTCUSDT")
        self.assertEqual(call.request.timeframe, "1h")
        self.assertEqual(call.mode, "production_like")
        self.assertTrue(call.options["risk_gate_enabled"])

    def test_scenario_runner_prepare_market_data_uses_backtest_request_and_assumptions(self) -> None:
        backtest_runner = _FakeBacktestRunner()
        scenario_runner = StrategyTestScenarioRunner(backtest_runner)  # type: ignore[arg-type]
        request = _matrix_request(mode="production_like", params={"warmup_candles": 5})
        pair = StrategyTestPair(exchange="bybit", symbol="ETHUSDT")

        result = scenario_runner.prepare_market_data(
            request=request,
            pair=pair,
            timeframe="15m",
        )

        call = backtest_runner.prepare_calls[0]
        self.assertEqual(result["prepared"], True)
        self.assertEqual(call.request.strategy_code, "trend_pullback_continuation")
        self.assertEqual(call.request.exchange, "bybit")
        self.assertEqual(call.request.symbol, "ETHUSDT")
        self.assertEqual(call.request.timeframe, "15m")
        self.assertEqual(call.mode, "production_like")
        self.assertTrue(call.options["risk_gate_enabled"])


class StrategyTestingServiceMatrixTest(unittest.TestCase):
    def test_service_default_matrix_runner_uses_shared_historical_provider(self) -> None:
        provider = _CountingHistoricalCandleProvider([])
        service = StrategyTestingService(
            run_store=_EphemeralRunStore(),
            trade_store=_RecordingTradeStore(),
            historical_candle_provider=provider,
        )

        scenario_runner = service._matrix_runner._scenario_runner  # type: ignore[attr-defined]
        backtest_runner = scenario_runner._backtest_runner  # type: ignore[attr-defined]

        self.assertIs(service._historical_candle_provider, provider)  # type: ignore[attr-defined]
        self.assertIs(backtest_runner._historical_candle_provider, provider)  # type: ignore[attr-defined]

    def test_service_marks_run_queued_running_completed_and_writes_trades(self) -> None:
        run_store = _EphemeralRunStore()
        trade_store = _RecordingTradeStore()
        matrix_runner = _StaticMatrixRunner(
            StrategyTestMatrixResult(
                run_id=RUN_ID,
                scenario_count=1,
                completed_scenarios=1,
                failed_scenarios=0,
                scenario_summaries=[{"signals_seen": 2, "risk_rejections": 0, "execution_rejections": 0}],
                trades=[_trade()],
                signal_events=[_signal_event("signal-1", entry_touched=True, filled=True)],
            )
        )
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=trade_store,
            matrix_runner=matrix_runner,  # type: ignore[arg-type]
        )

        response = service.create_run(_matrix_request())

        self.assertEqual(response.status, "completed")
        self.assertEqual(run_store.transitions, ["queued", "running", "completed"])
        self.assertEqual(len(trade_store.trades), 1)
        self.assertEqual(len(trade_store.signal_events), 1)
        self.assertGreater(len(trade_store.metrics), 0)
        self.assertIn("summary_metrics", response.summary)
        self.assertIn("signals_count", {metric["code"] for metric in response.summary["summary_metrics"]})
        self.assertIn("trades_count", {metric["code"] for metric in response.summary["summary_metrics"]})
        self.assertEqual(response.summary["scenario_count"], 1)

    def test_service_completes_partial_scenario_failure(self) -> None:
        service = StrategyTestingService(
            run_store=_EphemeralRunStore(),
            trade_store=_RecordingTradeStore(),
            matrix_runner=_StaticMatrixRunner(
                StrategyTestMatrixResult(
                    run_id=RUN_ID,
                    scenario_count=2,
                    completed_scenarios=1,
                    failed_scenarios=1,
                    scenario_summaries=[],
                    errors=[{"strategy": "s2", "error": "boom"}],
                )
            ),  # type: ignore[arg-type]
        )

        response = service.create_run(_matrix_request(strategies=["s1", "s2"]))

        self.assertEqual(response.status, "completed")
        self.assertEqual(response.summary["failed_scenarios"], 1)

    def test_service_marks_failed_when_all_scenarios_fail(self) -> None:
        service = StrategyTestingService(
            run_store=_EphemeralRunStore(),
            trade_store=_RecordingTradeStore(),
            matrix_runner=_StaticMatrixRunner(
                StrategyTestMatrixResult(
                    run_id=RUN_ID,
                    scenario_count=2,
                    completed_scenarios=0,
                    failed_scenarios=2,
                    errors=[{"strategy": "s1", "error": "historical data unavailable"}],
                )
            ),  # type: ignore[arg-type]
        )

        response = service.create_run(_matrix_request(strategies=["s1", "s2"]))

        self.assertEqual(response.status, "failed")
        self.assertIn("historical data unavailable", response.error or "")

    def test_service_calls_ensure_schema_before_each_result_write(self) -> None:
        trade_store = _SchemaRecordingTradeStore()
        service = StrategyTestingService(
            run_store=_EphemeralRunStore(),
            trade_store=trade_store,
            matrix_runner=_StaticMatrixRunner(
                StrategyTestMatrixResult(
                    run_id=RUN_ID,
                    scenario_count=1,
                    completed_scenarios=1,
                    failed_scenarios=0,
                    scenario_summaries=[{"signals_seen": 1, "risk_rejections": 0, "execution_rejections": 0}],
                    trades=[_trade()],
                    signal_events=[_signal_event("signal-1", entry_touched=True, filled=True)],
                )
            ),  # type: ignore[arg-type]
        )

        response = service.create_run(_matrix_request())

        self.assertEqual(response.status, "completed")
        self.assertEqual(
            trade_store.calls,
            [
                "ensure_schema",
                "write_trades",
                "ensure_schema",
                "write_signal_events",
                "ensure_schema",
                "write_metrics",
            ],
        )

    def test_service_marks_failed_and_keeps_partial_summary_when_result_write_fails(self) -> None:
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_FailingTradeStore(fail_on="write_metrics"),
            matrix_runner=_StaticMatrixRunner(
                StrategyTestMatrixResult(
                    run_id=RUN_ID,
                    scenario_count=1,
                    completed_scenarios=1,
                    failed_scenarios=0,
                    scenario_summaries=[{"signals_seen": 2, "risk_rejections": 0, "execution_rejections": 0}],
                    trades=[],
                )
            ),  # type: ignore[arg-type]
        )

        response = service.create_run(_matrix_request())

        self.assertEqual(response.status, "failed")
        self.assertIn("ClickHouse write failed", response.error or "")
        self.assertEqual(response.summary["completed_scenarios"], 1)
        self.assertEqual(response.summary["signals_seen"], 2)
        self.assertEqual(response.summary["trades_count"], 0)
        self.assertEqual(run_store.detail.run.runtime_state["phase"], "failed")  # type: ignore[union-attr]
        partial = run_store.detail.run.runtime_state["partial_summary"]  # type: ignore[union-attr]
        self.assertEqual(partial["completed_scenarios"], 1)
        self.assertEqual(partial["signals_seen"], 2)

    def test_service_completes_when_eligibility_profile_update_fails(self) -> None:
        run_store = _EphemeralRunStore()
        trade_store = _RecordingTradeStore()
        updater = _FailingEligibilityProfileUpdater()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=trade_store,
            matrix_runner=_StaticMatrixRunner(
                StrategyTestMatrixResult(
                    run_id=RUN_ID,
                    scenario_count=1,
                    completed_scenarios=1,
                    failed_scenarios=0,
                    scenario_summaries=[{"signals_seen": 2, "risk_rejections": 0, "execution_rejections": 0}],
                    trades=[_trade()],
                )
            ),  # type: ignore[arg-type]
            eligibility_profile_updater=updater,
        )

        with self.assertLogs("app.services.strategy_testing.service", level="WARNING") as logs:
            response = service.create_run(_matrix_request(params={"auto_publish_calibration": True}))

        self.assertEqual(response.status, "completed")
        self.assertEqual(run_store.transitions, ["queued", "running", "completed"])
        self.assertEqual(len(trade_store.trades), 1)
        self.assertGreater(len(trade_store.metrics), 0)
        self.assertEqual(len(updater.calls), 1)
        warnings = response.summary["warnings"]
        self.assertEqual(warnings[-1]["code"], "eligibility_profile_update_failed")
        self.assertIn("eligibility profile store unavailable", warnings[-1]["message"])
        self.assertIn("eligibility profile store unavailable", logs.output[0])

    def test_service_updates_runtime_state_after_each_matrix_scenario(self) -> None:
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=_CallbackMatrixRunner(),
        )

        response = service.create_run(_matrix_request(strategies=["s1", "s2", "s3"]))

        self.assertEqual(response.status, "completed")
        scenario_updates = [
            update
            for update in run_store.runtime_updates
            if update.get("phase") == "running_scenario" and update.get("scenario_completed")
        ]
        self.assertEqual([update["scenario_completed"] for update in scenario_updates], [1, 2, 3])
        self.assertEqual(scenario_updates[-1]["signals_seen"], 3)
        self.assertIsNotNone(scenario_updates[-1]["last_progress_at"])

    def test_service_records_scenario_started_status_in_runtime_state(self) -> None:
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=StrategyTestMatrixRunner(_RecordingScenarioRunner()),
        )

        response = service.create_run(_matrix_request(strategies=["s1"]))

        self.assertEqual(response.status, "completed")
        started = next(update for update in run_store.runtime_updates if update.get("scenario_status") == "started")
        self.assertEqual(started["phase"], "loading_candles")
        self.assertEqual(started["current_scenario_key"], "s1::bybit::BTCUSDT::1h")
        self.assertEqual(started["current_scenario_summary"]["status"], "started")

    def test_service_writes_completed_scenario_before_later_scenario_fails(self) -> None:
        run_store = _EphemeralRunStore()
        trade_store = _RecordingTradeStore()
        reports_after_first: list[Any] = []

        def capture_report() -> None:
            reports_after_first.append(
                StrategyTestReportBuilder(
                    run_store=run_store,
                    analytics_store=trade_store,
                ).build_report(RUN_ID)
            )

        service = StrategyTestingService(
            run_store=run_store,
            trade_store=trade_store,
            matrix_runner=_FirstScenarioPersistsThenFailsMatrixRunner(capture_report),
        )

        response = service.create_run(_matrix_request(strategies=["s1", "s2"]))

        self.assertEqual(response.status, "completed")
        self.assertEqual(response.summary["completed_scenarios"], 1)
        self.assertEqual(response.summary["failed_scenarios"], 1)
        self.assertEqual(len(trade_store.trades), 1)
        self.assertEqual(len(trade_store.signal_events), 1)
        self.assertEqual(reports_after_first[0].summary["status"], "running")
        self.assertEqual(reports_after_first[0].summary["completed_scenarios"], 1)
        self.assertEqual(reports_after_first[0].summary["trades_count"], 1)
        self.assertEqual(reports_after_first[0].summary["signals_count"], 1)
        trade_section = next(section for section in reports_after_first[0].sections if section.code == "trade_list")
        self.assertEqual(trade_section.metadata["rows_returned"], 1)

    def test_cancel_after_first_completed_scenario_keeps_written_rows(self) -> None:
        run_store = _EphemeralRunStore()
        trade_store = _RecordingTradeStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=trade_store,
            matrix_runner=_CancelAfterFirstScenarioMatrixRunner(run_store),
        )

        response = service.create_run(_matrix_request(strategies=["s1", "s2"]))
        report = StrategyTestReportBuilder(
            run_store=run_store,
            analytics_store=trade_store,
        ).build_report(RUN_ID)

        self.assertEqual(response.status, "cancelled")
        self.assertEqual(len(trade_store.trades), 1)
        self.assertEqual(len(trade_store.signal_events), 1)
        self.assertEqual(report.summary["status"], "cancelled")
        self.assertEqual(report.summary["completed_scenarios"], 1)
        self.assertEqual(report.summary["trades_count"], 1)
        self.assertEqual(report.summary["signals_count"], 1)

    def test_repeated_completion_callback_does_not_duplicate_scenario_rows(self) -> None:
        trade_store = _RecordingTradeStore()
        service = StrategyTestingService(
            run_store=_EphemeralRunStore(),
            trade_store=trade_store,
            matrix_runner=_RepeatedCompletionMatrixRunner(),
        )

        response = service.create_run(_matrix_request())

        self.assertEqual(response.status, "completed")
        self.assertEqual([trade.trade_id for trade in trade_store.trades], ["trade-1"])
        self.assertEqual([event.synthetic_signal_id for event in trade_store.signal_events], ["signal-1"])
        scenario_metric_keys = [
            (
                row.metadata.get("scenario_key"),
                row.strategy_code,
                row.exchange,
                row.symbol,
                row.timeframe,
                row.market_regime,
                row.score_bucket,
                row.direction,
                row.metric_code,
            )
            for row in trade_store.metrics
            if row.metadata.get("source") == "scenario_completed"
        ]
        self.assertEqual(len(scenario_metric_keys), len(set(scenario_metric_keys)))

    def test_high_volume_scenario_write_path_does_not_list_previous_analytics(self) -> None:
        trade_store = _ListFailingTradeStore()
        service = StrategyTestingService(
            run_store=_EphemeralRunStore(),
            trade_store=trade_store,
            matrix_runner=_SingleCallbackMatrixRunner(signal_events_count=150_000),
        )

        response = service.create_run(_matrix_request())

        self.assertEqual(response.status, "completed")
        self.assertEqual(len(trade_store.signal_events), 150_000)
        self.assertEqual(trade_store.list_trades_calls, 0)
        self.assertEqual(trade_store.list_signal_events_calls, 0)
        self.assertEqual(trade_store.list_metrics_calls, 0)

    def test_completed_scenario_checkpoint_is_not_executed_on_resume(self) -> None:
        run_store = _ScenarioCheckpointRunStore(
            completed_scenarios=[
                {
                    "scenario_key": "trend_pullback_continuation::bybit::BTCUSDT::1h",
                    "scenario_index": 1,
                    "status": "completed",
                    "strategy": "trend_pullback_continuation",
                    "exchange": "bybit",
                    "symbol": "BTCUSDT",
                    "timeframe": "1h",
                    "summary": {
                        "strategy": "trend_pullback_continuation",
                        "exchange": "bybit",
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "signals_seen": 12,
                        "trades_count": 2,
                        "risk_rejections": 0,
                        "execution_rejections": 0,
                    },
                }
            ]
        )
        scenario_runner = _RecordingScenarioRunner()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=StrategyTestMatrixRunner(scenario_runner),
        )

        response = service.create_run(_matrix_request())

        self.assertEqual(response.status, "completed")
        self.assertEqual(scenario_runner.calls, [])
        self.assertEqual(scenario_runner.prepare_calls, [])
        self.assertEqual(response.summary["completed_scenarios"], 1)
        self.assertEqual(response.summary["signals_seen"], 12)

    def test_service_merges_absolute_active_progress_without_double_counting(self) -> None:
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=_RepeatedProgressMatrixRunner(),
        )

        response = service.create_run(_matrix_request(strategies=["done", "active"]))

        self.assertEqual(response.status, "completed")
        progress_updates = [
            update for update in run_store.runtime_updates if update.get("bars_processed") == 10
        ]
        self.assertEqual(len(progress_updates), 2)
        for update in progress_updates:
            self.assertEqual(update["signals_seen"], 8)
            self.assertEqual(update["execution_candidates"], 6)
            self.assertEqual(update["pending_armed"], 3)
            self.assertEqual(update["entry_touched"], 2)
            self.assertEqual(update["filled"], 1)
            self.assertEqual(update["closed"], 1)
            self.assertEqual(update["no_entry"], 3)
            self.assertEqual(update["not_selected"], 2)
            self.assertEqual(update["pending_entries_count"], 4)
            partial = update["partial_summary"]
            self.assertEqual(partial["signals_seen"], 8)
            self.assertEqual(partial["execution_candidates"], 6)
            self.assertEqual(partial["no_entry"], 3)
            self.assertEqual(partial["not_selected"], 2)

    def test_cancel_running_run_moves_to_stopping_then_runner_marks_cancelled(self) -> None:
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=_CancellingMatrixRunner(run_store),
        )
        created = run_store.create_run(_matrix_request())
        run_store.mark_running(created.run.run_id)

        stopping = service.cancel_run(created.run.run_id)

        self.assertEqual(stopping.status, "stopping")
        cancelled = service.execute_run(created.run.run_id, _matrix_request())
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(run_store.detail.run.runtime_state["phase"], "cancelled")  # type: ignore[union-attr]

    def test_stale_running_run_allows_new_run_and_cancel_action(self) -> None:
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=_StaticMatrixRunner(StrategyTestMatrixResult(run_id=RUN_ID, scenario_count=1, completed_scenarios=1, failed_scenarios=0)),
        )
        created = run_store.create_run(_matrix_request())
        run_store.mark_running(created.run.run_id)
        assert run_store.detail is not None
        stale_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=settings.strategy_test_lease_seconds + 1)
        run_store.detail = StrategyTestRunDetailResponse(
            run=run_store.detail.run.model_copy(update={"last_heartbeat_at": stale_heartbeat})
        )

        active = service.get_active_run(user_id=str(USER_ID))

        self.assertTrue(active.is_stale)
        self.assertTrue(active.can_run)
        self.assertIn("cancel", active.allowed_actions)
        self.assertEqual(active.stale_threshold_seconds, settings.strategy_test_lease_seconds)

    def test_enqueue_historical_run_does_not_validate_bars_before_creating_run(self) -> None:
        old_max_bars = settings.strategy_test_max_bars_per_run
        settings.strategy_test_max_bars_per_run = 10
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            historical_candle_provider=_FixedCountHistoricalCandleProvider(candles_count=DEFAULT_WARMUP_CANDLES + 11),
        )

        try:
            response = service.enqueue_run(_matrix_request())
        finally:
            settings.strategy_test_max_bars_per_run = old_max_bars

        self.assertEqual(response.status, "queued")
        self.assertIsNotNone(run_store.detail)
        self.assertEqual(run_store.transitions, ["queued"])

    def test_execute_historical_run_validates_bars_limit_and_marks_failed(self) -> None:
        old_max_bars = settings.strategy_test_max_bars_per_run
        settings.strategy_test_max_bars_per_run = 10
        run_store = _EphemeralRunStore()
        matrix_runner = _RecordingStaticMatrixRunner(
            StrategyTestMatrixResult(run_id=RUN_ID, scenario_count=1, completed_scenarios=1, failed_scenarios=0)
        )
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            historical_candle_provider=_FixedCountHistoricalCandleProvider(candles_count=0),
            matrix_runner=matrix_runner,  # type: ignore[arg-type]
        )
        created = run_store.create_run(_matrix_request(params={"warmup_candles": 1}))

        try:
            response = service.execute_run(created.run.run_id)
        finally:
            settings.strategy_test_max_bars_per_run = old_max_bars

        self.assertEqual(response.status, "failed")
        self.assertIn("strategy_test_max_bars_per_run exceeded", response.error or "")
        self.assertEqual(matrix_runner.calls, 0)
        self.assertEqual(matrix_runner.calls, 0)
        self.assertEqual(run_store.transitions, ["queued", "failed"])
        self.assertEqual(run_store.detail.run.runtime_state["phase"], "failed")  # type: ignore[union-attr]
        self.assertIn("strategy_test_max_bars_per_run exceeded", run_store.detail.run.runtime_state["last_error"])  # type: ignore[union-attr]

    def test_enqueue_historical_run_validates_enqueued_scenario_limit_before_creating_run(self) -> None:
        old_max_scenarios = settings.strategy_test_max_enqueued_historical_scenarios_per_run
        settings.strategy_test_max_enqueued_historical_scenarios_per_run = 1
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            historical_candle_provider=_FixedCountHistoricalCandleProvider(candles_count=DEFAULT_WARMUP_CANDLES),
        )

        try:
            with self.assertRaisesRegex(ValueError, "strategy_test_max_enqueued_historical_scenarios_per_run"):
                service.enqueue_run(_matrix_request(strategies=["s1", "s2"]))
        finally:
            settings.strategy_test_max_enqueued_historical_scenarios_per_run = old_max_scenarios

        self.assertIsNone(run_store.detail)

    def test_service_marks_failed_with_runtime_last_error_when_scenario_errors(self) -> None:
        run_store = _EphemeralRunStore()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            matrix_runner=StrategyTestMatrixRunner(_RecordingScenarioRunner(fail_on={0})),
        )

        response = service.create_run(_matrix_request())

        self.assertEqual(response.status, "failed")
        self.assertIn("scenario 0 failed", response.error or "")
        self.assertEqual(run_store.detail.run.runtime_state["phase"], "failed")  # type: ignore[union-attr]
        self.assertIn("scenario 0 failed", run_store.detail.run.runtime_state["last_error"])  # type: ignore[union-attr]
        failed = next(update for update in run_store.runtime_updates if update.get("scenario_status") == "failed")
        self.assertIn("scenario 0 failed", failed["current_scenario_summary"]["error"])
        self.assertEqual(failed["current_scenario_summary"]["partial_summary"]["failed_scenarios"], 1)


@dataclass(frozen=True)
class _BacktestCall:
    request: Any
    mode: str
    options: dict[str, Any]


class _FakeBacktestRunner:
    def __init__(self) -> None:
        self.calls: list[_BacktestCall] = []
        self.prepare_calls: list[_BacktestCall] = []

    def prepare_market_data(
        self,
        request: Any,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        _ = kwargs
        self.prepare_calls.append(_BacktestCall(request=request, mode=mode, options=options or {}))
        return {"prepared": True}

    def run_detailed(
        self,
        request: Any,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BacktestDetailedRunResult:
        _ = kwargs
        self.calls.append(_BacktestCall(request=request, mode=mode, options=options or {}))
        return BacktestDetailedRunResult(
            run_result=BacktestRunResult(status="completed", result=None),
            trades=[],
            signals_seen=0,
            risk_rejections=0,
            execution_rejections=0,
            assumptions=options or {},
        )


class _RecordingScenarioRunner:
    def __init__(
        self,
        fail_on: set[int] | None = None,
        prepare_fail_on: set[tuple[str, str, str]] | None = None,
        on_prepare: Any = None,
        signal_events: list[StrategyTestSignalEvent] | None = None,
        summary_overrides: list[dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.prepare_calls: list[tuple[str, str, str]] = []
        self._fail_on = fail_on or set()
        self._prepare_fail_on = prepare_fail_on or set()
        self._on_prepare = on_prepare
        self._signal_events = signal_events or []
        self._summary_overrides = summary_overrides or []

    def prepare_market_data(
        self,
        *,
        request: StrategyTestRunRequest,
        pair: StrategyTestPair,
        timeframe: str,
        is_cancelled: Any = None,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        _ = request, is_cancelled, on_progress
        key = (pair.exchange, pair.symbol, timeframe)
        self.prepare_calls.append(key)
        if self._on_prepare is not None:
            self._on_prepare()
        if key in self._prepare_fail_on:
            raise ValueError(f"market data prepare failed for {pair.symbol} {timeframe}")
        return {"candles_count": 42}

    def run_scenario(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        request: StrategyTestRunRequest,
        strategy: str,
        pair: StrategyTestPair,
        timeframe: str,
        is_cancelled: Any = None,
        on_progress: Any = None,
        candle_cache: Any = None,
        feature_cache: Any = None,
    ) -> StrategyTestScenarioResult:
        _ = run_id, user_id, request, is_cancelled, on_progress, candle_cache, feature_cache
        index = len(self.calls)
        self.calls.append((strategy, pair.exchange, pair.symbol, timeframe))
        if index in self._fail_on:
            raise ValueError(f"scenario {index} failed")
        summary = {
            "strategy": strategy,
            "exchange": pair.exchange,
            "symbol": pair.symbol,
            "timeframe": timeframe,
            "signals_seen": 1,
            "risk_rejections": 0,
            "execution_rejections": 0,
        }
        if index < len(self._summary_overrides):
            summary.update(self._summary_overrides[index])
        return StrategyTestScenarioResult(
            run_id=RUN_ID,
            strategy=strategy,
            pair=pair,
            timeframe=timeframe,
            summary=summary,
            trades=[],
            signal_events=list(self._signal_events),
        )


class _HighVolumeScenarioRunner:
    def __init__(self, *, signal_events_count: int) -> None:
        self.signal_events_count = signal_events_count

    def run_scenario(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        request: StrategyTestRunRequest,
        strategy: str,
        pair: StrategyTestPair,
        timeframe: str,
        **kwargs: Any,
    ) -> StrategyTestScenarioResult:
        _ = user_id, request, kwargs
        return StrategyTestScenarioResult(
            run_id=run_id,
            strategy=strategy,
            pair=pair,
            timeframe=timeframe,
            summary={
                "strategy": strategy,
                "exchange": pair.exchange,
                "symbol": pair.symbol,
                "timeframe": timeframe,
                "signals_seen": self.signal_events_count,
                "signals_count": self.signal_events_count,
                "execution_candidates": self.signal_events_count,
                "risk_rejections": 0,
                "execution_rejections": 0,
            },
            trades=[],
            signal_events=_signal_events(self.signal_events_count, strategy=strategy),
        )


class _CapturingScenarioResultSink:
    def __init__(self) -> None:
        self.signal_event_counts: list[int] = []

    def write_result(
        self,
        context: StrategyTestScenarioContext,
        result: StrategyTestScenarioResult,
        partial_summary: dict[str, Any],
    ) -> None:
        _ = context, partial_summary
        self.signal_event_counts.append(len(result.signal_events))


class _ProgressCountingScenarioRunner:
    def __init__(self, *, bars_per_pair_timeframe: dict[tuple[str, str, str], int]) -> None:
        self._bars_per_pair_timeframe = bars_per_pair_timeframe
        self.count_calls: list[tuple[str, str, str]] = []

    def count_scenario_bars(
        self,
        *,
        request: StrategyTestRunRequest,
        pair: StrategyTestPair,
        timeframe: str,
    ) -> int:
        _ = request
        key = (pair.exchange, pair.symbol, timeframe)
        self.count_calls.append(key)
        return self._bars_per_pair_timeframe[key]

    def run_scenario(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        request: StrategyTestRunRequest,
        strategy: str,
        pair: StrategyTestPair,
        timeframe: str,
        is_cancelled: Any = None,
        on_progress: Any = None,
        candle_cache: Any = None,
        feature_cache: Any = None,
    ) -> StrategyTestScenarioResult:
        _ = user_id, request, is_cancelled, candle_cache, feature_cache
        bars_total = self._bars_per_pair_timeframe[(pair.exchange, pair.symbol, timeframe)]
        if on_progress is not None:
            on_progress(
                {
                    "phase": "running_scenario",
                    "bars_processed": 1,
                    "bars_total": bars_total,
                    "signals_seen": 0,
                    "trades_count": 0,
                    "risk_rejections": 0,
                    "execution_rejections": 0,
                }
            )
        return StrategyTestScenarioResult(
            run_id=run_id,
            strategy=strategy,
            pair=pair,
            timeframe=timeframe,
            summary={
                "strategy": strategy,
                "exchange": pair.exchange,
                "symbol": pair.symbol,
                "timeframe": timeframe,
                "signals_seen": 0,
                "risk_rejections": 0,
                "execution_rejections": 0,
                "timings": {"bars_total": bars_total},
            },
            trades=[],
            signal_events=[],
        )


class _PreparingBarScenarioRunner(_ProgressCountingScenarioRunner):
    def __init__(self, *, bars_per_pair_timeframe: dict[tuple[str, str, str], int]) -> None:
        super().__init__(bars_per_pair_timeframe=bars_per_pair_timeframe)
        self.prepare_calls: list[tuple[str, str, str]] = []

    def prepare_market_data(
        self,
        *,
        request: StrategyTestRunRequest,
        pair: StrategyTestPair,
        timeframe: str,
        is_cancelled: Any = None,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        _ = request, is_cancelled, on_progress
        key = (pair.exchange, pair.symbol, timeframe)
        self.prepare_calls.append(key)
        return {"bars_total": self._bars_per_pair_timeframe[key]}


class _StaticMatrixRunner:
    def __init__(self, result: StrategyTestMatrixResult) -> None:
        self.result = result

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = request, run_id, user_uuid, kwargs
        return self.result


class _RecordingStaticMatrixRunner(_StaticMatrixRunner):
    def __init__(self, result: StrategyTestMatrixResult) -> None:
        super().__init__(result)
        self.calls = 0

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        self.calls += 1
        return super().run_matrix(request=request, run_id=run_id, user_uuid=user_uuid, **kwargs)


class _CallbackMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        on_scenario_started: Any = None,
        on_scenario_completed: Any = None,
        on_scenario_failed: Any = None,
        on_scenario_progress: Any = None,
        is_cancelled: Any = None,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = user_uuid, on_scenario_started, on_scenario_failed, on_scenario_progress, is_cancelled, kwargs
        completed = 0
        summaries: list[dict[str, Any]] = []
        for strategy in request.strategies:
            summary = {
                "strategy": strategy,
                "exchange": request.pairs[0].exchange,
                "symbol": request.pairs[0].symbol,
                "timeframe": request.timeframes[0],
                "signals_seen": 1,
                "risk_rejections": 0,
                "execution_rejections": 0,
            }
            completed += 1
            summaries.append(summary)
            partial = StrategyTestMatrixResult(
                run_id=run_id,
                scenario_count=len(request.strategies),
                completed_scenarios=completed,
                failed_scenarios=0,
                scenario_summaries=list(summaries),
            ).summary()
            if on_scenario_completed is not None:
                context = type(
                    "ScenarioContext",
                    (),
                    {
                        "strategy": strategy,
                        "exchange": request.pairs[0].exchange,
                        "symbol": request.pairs[0].symbol,
                        "timeframe": request.timeframes[0],
                    },
                )()
                on_scenario_completed(context, None, partial)
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=len(request.strategies),
            completed_scenarios=completed,
            failed_scenarios=0,
            scenario_summaries=summaries,
        )


class _RepeatedProgressMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        on_scenario_started: Any = None,
        on_scenario_completed: Any = None,
        on_scenario_failed: Any = None,
        on_scenario_progress: Any = None,
        is_cancelled: Any = None,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = user_uuid, on_scenario_started, on_scenario_completed, on_scenario_failed, is_cancelled, kwargs
        completed_summary = {
            "scenario_count": len(request.strategies),
            "completed_scenarios": 1,
            "failed_scenarios": 0,
            "trades_count": 1,
            "signals_seen": 3,
            "signals_count": 3,
            "execution_candidates": 2,
            "pending_armed": 1,
            "touched": 1,
            "entry_touched": 1,
            "filled": 1,
            "closed": 1,
            "no_entry": 1,
            "not_selected": 1,
            "risk_rejections": 0,
            "execution_rejections": 0,
            "errors": [],
            "scenarios": [],
        }
        progress = {
            "phase": "running_scenario",
            "bars_processed": 10,
            "bars_total": 40,
            "bars_pct": 25.0,
            "pending_entries_count": 4,
            "signals_seen": 5,
            "signals_count": 5,
            "execution_candidates": 4,
            "pending_armed": 2,
            "touched": 1,
            "entry_touched": 1,
            "filled": 0,
            "closed": 0,
            "no_entry": 2,
            "not_selected": 1,
            "trades_count": 0,
            "risk_rejections": 0,
            "execution_rejections": 0,
            "elapsed_ms": 1000.0,
            "bars_per_second": 10.0,
            "eta_seconds": 3.0,
        }
        if on_scenario_progress is not None:
            context = type(
                "ScenarioContext",
                (),
                {
                    "strategy": request.strategies[-1],
                    "exchange": request.pairs[0].exchange,
                    "symbol": request.pairs[0].symbol,
                    "timeframe": request.timeframes[0],
                },
            )()
            on_scenario_progress(context, progress, dict(completed_summary))
            on_scenario_progress(context, progress, dict(completed_summary))
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=len(request.strategies),
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[completed_summary],
        )


class _FirstScenarioPersistsThenFailsMatrixRunner:
    def __init__(self, after_first_completed: Any) -> None:
        self._after_first_completed = after_first_completed

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        on_scenario_started: Any = None,
        on_scenario_completed: Any = None,
        on_scenario_failed: Any = None,
        scenario_result_sink: Any = None,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = user_uuid, kwargs
        pair = request.pairs[0]
        first_context = StrategyTestScenarioContext(
            index=1,
            total=2,
            strategy=request.strategies[0],
            pair=pair,
            timeframe=request.timeframes[0],
        )
        if on_scenario_started is not None:
            on_scenario_started(first_context)
        first_result = _scenario_result(request.strategies[0])
        partial = StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=2,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[first_result.summary],
            trades=list(first_result.trades),
            signal_events=list(first_result.signal_events),
        ).summary()
        if scenario_result_sink is not None:
            scenario_result_sink.write_result(first_context, first_result, partial)
        if on_scenario_completed is not None:
            on_scenario_completed(first_context, first_result, partial)
        self._after_first_completed()

        second_context = StrategyTestScenarioContext(
            index=2,
            total=2,
            strategy=request.strategies[1],
            pair=pair,
            timeframe=request.timeframes[0],
        )
        if on_scenario_started is not None:
            on_scenario_started(second_context)
        exc = ValueError("scenario 1 failed")
        errors = [{"strategy": request.strategies[1], "error": str(exc)}]
        failed_partial = StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=2,
            completed_scenarios=1,
            failed_scenarios=1,
            scenario_summaries=[first_result.summary],
            errors=errors,
            trades=list(first_result.trades),
            signal_events=list(first_result.signal_events),
        ).summary()
        if on_scenario_failed is not None:
            on_scenario_failed(second_context, exc, failed_partial)
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=2,
            completed_scenarios=1,
            failed_scenarios=1,
            scenario_summaries=[first_result.summary],
            errors=errors,
            trades=list(first_result.trades),
            signal_events=list(first_result.signal_events),
        )


class _CancelAfterFirstScenarioMatrixRunner:
    def __init__(self, run_store: "_EphemeralRunStore") -> None:
        self._run_store = run_store

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        on_scenario_started: Any = None,
        on_scenario_completed: Any = None,
        is_cancelled: Any = None,
        scenario_result_sink: Any = None,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = user_uuid, kwargs
        context = StrategyTestScenarioContext(
            index=1,
            total=2,
            strategy=request.strategies[0],
            pair=request.pairs[0],
            timeframe=request.timeframes[0],
        )
        if on_scenario_started is not None:
            on_scenario_started(context)
        result = _scenario_result(request.strategies[0])
        partial = StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=2,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[result.summary],
            trades=list(result.trades),
            signal_events=list(result.signal_events),
        ).summary()
        if scenario_result_sink is not None:
            scenario_result_sink.write_result(context, result, partial)
        if on_scenario_completed is not None:
            on_scenario_completed(context, result, partial)
        self._run_store.mark_stopping(run_id)
        self.assert_cancelled(is_cancelled)
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=2,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[result.summary],
            trades=list(result.trades),
            signal_events=list(result.signal_events),
            cancelled=True,
        )

    @staticmethod
    def assert_cancelled(is_cancelled: Any) -> None:
        if is_cancelled is None or not is_cancelled():
            raise AssertionError("runner did not observe cancellation")


class _RepeatedCompletionMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        on_scenario_started: Any = None,
        on_scenario_completed: Any = None,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = user_uuid, kwargs
        context = StrategyTestScenarioContext(
            index=1,
            total=1,
            strategy=request.strategies[0],
            pair=request.pairs[0],
            timeframe=request.timeframes[0],
        )
        if on_scenario_started is not None:
            on_scenario_started(context)
        result = _scenario_result(request.strategies[0])
        partial = StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=1,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[result.summary],
            trades=list(result.trades),
            signal_events=list(result.signal_events),
        ).summary()
        if on_scenario_completed is not None:
            on_scenario_completed(context, result, partial)
            on_scenario_completed(context, result, partial)
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=1,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[result.summary],
            trades=list(result.trades),
            signal_events=list(result.signal_events),
        )


class _SingleCallbackMatrixRunner:
    def __init__(self, *, signal_events_count: int) -> None:
        self.signal_events_count = signal_events_count

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        on_scenario_started: Any = None,
        on_scenario_completed: Any = None,
        scenario_result_sink: Any = None,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = user_uuid, kwargs
        context = StrategyTestScenarioContext(
            index=1,
            total=1,
            strategy=request.strategies[0],
            pair=request.pairs[0],
            timeframe=request.timeframes[0],
        )
        if on_scenario_started is not None:
            on_scenario_started(context)
        result = StrategyTestScenarioResult(
            run_id=run_id,
            strategy=context.strategy,
            pair=context.pair,
            timeframe=context.timeframe,
            summary={
                "strategy": context.strategy,
                "exchange": context.exchange,
                "symbol": context.symbol,
                "timeframe": context.timeframe,
                "signals_seen": self.signal_events_count,
                "signals_count": self.signal_events_count,
                "execution_candidates": self.signal_events_count,
                "risk_rejections": 0,
                "execution_rejections": 0,
            },
            trades=[],
            signal_events=_signal_events(self.signal_events_count, strategy=context.strategy),
        )
        partial = StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=1,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[result.summary],
        ).summary()
        if scenario_result_sink is not None:
            scenario_result_sink.write_result(context, result, partial)
        if on_scenario_completed is not None:
            on_scenario_completed(context, result, partial)
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=1,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[result.summary],
        )


class _CancellingMatrixRunner:
    def __init__(self, run_store: "_EphemeralRunStore") -> None:
        self._run_store = run_store

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        is_cancelled: Any = None,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = request, user_uuid, kwargs
        self._run_store.mark_stopping(run_id)
        if is_cancelled is not None and is_cancelled():
            return StrategyTestMatrixResult(
                run_id=run_id,
                scenario_count=1,
                completed_scenarios=0,
                failed_scenarios=0,
                cancelled=True,
            )
        raise AssertionError("runner did not observe cancellation")


class _RecordingTradeStore:
    def __init__(self) -> None:
        self.trades: list[StrategyTestTrade] = []
        self.signal_events: list[StrategyTestSignalEvent] = []
        self.metrics: list[StrategyTestMetricRow] = []

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.trades.extend(trades)

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        self.signal_events.extend(signal_events)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.metrics.extend(rows)

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        rows = [trade for trade in self.trades if trade.run_id == run_id]
        return rows[offset : offset + limit]

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        rows = [event for event in self.signal_events if event.run_id == run_id]
        return rows[offset : offset + limit]

    def list_metrics(self, run_id: UUID) -> list[StrategyTestMetricRow]:
        return [row for row in self.metrics if row.run_id == run_id]


class _ListFailingTradeStore(_RecordingTradeStore):
    def __init__(self) -> None:
        super().__init__()
        self.list_trades_calls = 0
        self.list_signal_events_calls = 0
        self.list_metrics_calls = 0

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        _ = run_id, limit, offset
        self.list_trades_calls += 1
        raise AssertionError("write path must not list existing trades")

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        _ = run_id, limit, offset
        self.list_signal_events_calls += 1
        raise AssertionError("write path must not list existing signal events")

    def list_metrics(self, run_id: UUID) -> list[StrategyTestMetricRow]:
        _ = run_id
        self.list_metrics_calls += 1
        raise AssertionError("write path must not list existing metrics")


class _SchemaRecordingTradeStore(_RecordingTradeStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def ensure_schema(self) -> None:
        self.calls.append("ensure_schema")

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.calls.append("write_trades")
        super().write_trades(trades)

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        self.calls.append("write_signal_events")
        super().write_signal_events(signal_events)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.calls.append("write_metrics")
        super().write_metrics(rows)


class _FailingTradeStore(_RecordingTradeStore):
    def __init__(self, *, fail_on: str) -> None:
        super().__init__()
        self._fail_on = fail_on

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        if self._fail_on == "write_trades":
            raise RuntimeError("ClickHouse write failed")
        super().write_trades(trades)

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        if self._fail_on == "write_signal_events":
            raise RuntimeError("ClickHouse write failed")
        super().write_signal_events(signal_events)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        if self._fail_on == "write_metrics":
            raise RuntimeError("ClickHouse write failed")
        super().write_metrics(rows)


class _FailingEligibilityProfileUpdater:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update_from_metric_results(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        raise RuntimeError("eligibility profile store unavailable")


class _EphemeralRunStore:
    def __init__(self) -> None:
        self.detail: StrategyTestRunDetailResponse | None = None
        self.transitions: list[str] = []
        self.runtime_updates: list[dict[str, Any]] = []

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        run = StrategyTestRunResponse(
            run_id=RUN_ID,
            status="queued",
            requested_matrix=_requested_matrix(request),
        )
        self.detail = StrategyTestRunDetailResponse(run=run)
        self.transitions.append("queued")
        return self.detail

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        _ = user_id, limit, status
        return [self.detail] if self.detail is not None else []

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        _ = run_id
        return self.detail

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        _ = run_id
        self.transitions.append("running")
        return self._mark("running")

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        _ = run_id
        self.transitions.append("completed")
        return self._mark("completed", summary=summary)

    def mark_failed(
        self,
        run_id: UUID,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        _ = run_id
        self.transitions.append("failed")
        return self._mark("failed", summary=summary, error=error)

    def mark_stopping(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        _ = run_id
        self.transitions.append("stopping")
        return self._mark("stopping")

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        _ = run_id
        self.transitions.append("cancelled")
        return self._mark("cancelled")

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        _ = run_id, heartbeat
        assert self.detail is not None
        self.runtime_updates.append(dict(runtime_state))
        run = self.detail.run.model_copy(
            update={"runtime_state": {**self.detail.run.runtime_state, **runtime_state}}
        )
        self.detail = StrategyTestRunDetailResponse(run=run)
        return self.detail

    def _mark(
        self,
        status: StrategyTestRunStatus,
        *,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> StrategyTestRunDetailResponse:
        assert self.detail is not None
        run = self.detail.run.model_copy(update={"status": status, "summary": summary or {}, "error": error})
        self.detail = StrategyTestRunDetailResponse(run=run)
        return self.detail


@dataclass
class _ScenarioCheckpoint:
    scenario_key: str
    scenario_index: int
    status: str
    strategy_code: str
    exchange: str
    symbol: str
    timeframe: str
    summary: dict[str, Any]
    bars_total: int = 0
    bars_processed: int = 0
    error: str | None = None


class _ScenarioCheckpointRunStore(_EphemeralRunStore):
    def __init__(self, completed_scenarios: Sequence[dict[str, Any]]) -> None:
        super().__init__()
        self._scenarios = {
            str(item["scenario_key"]): _ScenarioCheckpoint(
                scenario_key=str(item["scenario_key"]),
                scenario_index=int(item["scenario_index"]),
                status=str(item["status"]),
                strategy_code=str(item["strategy"]),
                exchange=str(item["exchange"]),
                symbol=str(item["symbol"]),
                timeframe=str(item["timeframe"]),
                summary=dict(item["summary"]),
            )
            for item in completed_scenarios
        }

    def list_scenarios(self, run_id: UUID) -> list[_ScenarioCheckpoint]:
        _ = run_id
        return sorted(self._scenarios.values(), key=lambda scenario: scenario.scenario_index)

    def completed_scenario_keys(self, run_id: UUID) -> set[str]:
        _ = run_id
        return {
            scenario.scenario_key
            for scenario in self._scenarios.values()
            if scenario.status == "completed"
        }

    def mark_scenario_running(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        scenario_index: int,
        strategy_code: str,
        exchange: str,
        symbol: str,
        timeframe: str,
        bars_total: int | None = None,
    ) -> _ScenarioCheckpoint:
        _ = run_id
        scenario = _ScenarioCheckpoint(
            scenario_key=scenario_key,
            scenario_index=scenario_index,
            status="running",
            strategy_code=strategy_code,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            summary={},
            bars_total=bars_total or 0,
        )
        self._scenarios[scenario_key] = scenario
        return scenario

    def mark_scenario_completed(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        summary: dict[str, Any],
        bars_processed: int | None = None,
        result_written_at: datetime | None = None,
    ) -> _ScenarioCheckpoint:
        _ = run_id, result_written_at
        scenario = self._scenarios[scenario_key]
        scenario.status = "completed"
        scenario.summary = dict(summary)
        scenario.bars_processed = bars_processed or scenario.bars_processed
        return scenario

    def mark_scenario_failed(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> _ScenarioCheckpoint:
        _ = run_id
        scenario = self._scenarios[scenario_key]
        scenario.status = "failed"
        scenario.error = error
        scenario.summary = dict(summary or {})
        return scenario


def _matrix_request(
    *,
    strategies: list[str] | None = None,
    pairs: list[StrategyTestPair] | None = None,
    timeframes: list[str] | None = None,
    mode: str = "research_virtual",
    params: dict[str, Any] | None = None,
) -> StrategyTestRunRequest:
    start_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return StrategyTestRunRequest(
        user_id=str(USER_ID),
        strategies=strategies or ["trend_pullback_continuation"],
        pairs=pairs or [StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
        timeframes=timeframes or ["1h"],
        start_at=start_at,
        end_at=start_at + timedelta(days=1),
        mode=mode,  # type: ignore[arg-type]
        initial_capital=Decimal("1000"),
        fee_rate=Decimal("0.001"),
        slippage_bps=Decimal("0"),
        params=params or {},
    )


class _CountingHistoricalCandleProvider:
    def __init__(self, candles: list[OHLCVCandle]) -> None:
        self._candles = candles
        self.ensure_calls = 0
        self.load_calls = 0
        self.count_calls = 0

    async def ensure_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> None:
        _ = exchange, symbol, timeframe, start_at, end_at
        self.ensure_calls += 1

    async def load_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[OHLCVCandle]:
        _ = exchange, symbol, timeframe, start_at, end_at
        self.load_calls += 1
        return list(self._candles)

    async def count_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        _ = exchange, symbol, timeframe, start_at, end_at
        self.count_calls += 1
        return len({candle.open_time for candle in self._candles if candle.is_closed})


class _FixedCountHistoricalCandleProvider:
    def __init__(self, *, candles_count: int) -> None:
        self._candles_count = candles_count

    async def count_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        _ = exchange, symbol, timeframe, start_at, end_at
        return self._candles_count


class _SilentFeatureEngine:
    def process_candles(self, candles: list[OHLCVCandle]) -> Features:
        latest = candles[-1]
        previous = candles[-2] if len(candles) > 1 else None
        return Features(
            exchange=latest.exchange,
            symbol=latest.symbol,
            timeframe=latest.timeframe,
            timestamp=latest.close_time,
            price=latest.close,
            open=latest.open,
            high=latest.high,
            low=latest.low,
            close=latest.close,
            price_change_1m=0.0,
            previous_open=previous.open if previous is not None else None,
            previous_high=previous.high if previous is not None else None,
            previous_low=previous.low if previous is not None else None,
            previous_close=previous.close if previous is not None else None,
            previous_volume=previous.volume if previous is not None else None,
            volume=latest.volume,
            volume_spike=1.0,
            volume_ma_20=latest.volume,
            volatility=1.0,
            history_length=len(candles),
            atr_14=1.0,
        )


class _CountingFeatureEngine(_SilentFeatureEngine):
    def __init__(self) -> None:
        self.calls = 0

    def process_candles(self, candles: list[OHLCVCandle]) -> Features:
        self.calls += 1
        return super().process_candles(candles)


class _NoSignalStrategyEngine:
    async def generate_signals(self, features: Features, **kwargs: Any) -> list[Any]:
        _ = features, kwargs
        return []


def _historical_candles() -> list[OHLCVCandle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles: list[OHLCVCandle] = []
    for index in range(6):
        open_time = int((start + timedelta(hours=index)).timestamp() * 1000)
        candles.append(
            OHLCVCandle(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="1h",
                open_time=open_time,
                close_time=open_time + 3_599_999,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=100.0,
                trades=10,
                is_closed=True,
            )
        )
    return candles


def _many_historical_candles(*, count: int) -> list[OHLCVCandle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles: list[OHLCVCandle] = []
    for index in range(count):
        open_time = int((start + timedelta(hours=index)).timestamp() * 1000)
        candles.append(
            OHLCVCandle(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="1h",
                open_time=open_time,
                close_time=open_time + 3_599_999,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=100.0,
                trades=10,
                is_closed=True,
            )
        )
    return candles


def _backtest_request() -> Any:
    request = _matrix_request(
        strategies=["trend_pullback_continuation"],
        params={"warmup_candles": 3, "rolling_window_candles": 3},
    )
    from app.services.strategy_testing.runner import _backtest_request_from_scenario

    return _backtest_request_from_scenario(
        request=request,
        strategy="trend_pullback_continuation",
        pair=request.pairs[0],
        timeframe=request.timeframes[0],
    )


def _assumption_kwargs(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "fee_rate": Decimal("0.001"),
        "slippage_bps": Decimal("0"),
        "same_candle_policy": "stop_first",
        "initial_capital": Decimal("1000"),
        "params": {},
    }


def _requested_matrix(request: StrategyTestRunRequest) -> dict[str, Any]:
    return {
        "user_id": request.user_id,
        "test_type": request.test_type,
        "mode": request.mode,
        "strategies": list(request.strategies),
        "pairs": [pair.model_dump() for pair in request.pairs],
        "timeframes": list(request.timeframes),
        "start_at": request.start_at,
        "end_at": request.end_at,
        "initial_capital": request.initial_capital,
        "fee_rate": request.fee_rate,
        "slippage_bps": request.slippage_bps,
        "same_candle_policy": request.same_candle_policy,
        "params": request.params,
        "metric_set": request.metric_set,
        "tags": request.tags,
        "scenario_count": len(request.strategies) * len(request.pairs) * len(request.timeframes),
    }


def _trade() -> StrategyTestTrade:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return StrategyTestTrade(
        run_id=RUN_ID,
        trade_id="trade-1",
        user_id=USER_ID,
        mode="research_virtual",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="long",
        signal_score=80.0,
        market_regime="unknown",
        score_bucket="80-89",
        entry_time=now,
        exit_time=now + timedelta(hours=1),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        stop_loss=Decimal("99"),
        targets=[],
        selected_rr=1.0,
        realized_r=1.0,
        pnl=Decimal("10"),
        pnl_pct=1.0,
        fees=Decimal("0.1"),
        slippage=Decimal("0"),
        close_reason="take_profit",
        outcome="win",
        tags=["backtest"],
        created_at=now,
    )


def _scenario_result(strategy: str) -> StrategyTestScenarioResult:
    trade = _trade().model_copy(update={"strategy_code": strategy})
    event = _signal_event("signal-1", entry_touched=True, filled=True).model_copy(update={"strategy_code": strategy})
    return StrategyTestScenarioResult(
        run_id=RUN_ID,
        strategy=strategy,
        pair=StrategyTestPair(exchange="bybit", symbol="BTCUSDT"),
        timeframe="1h",
        summary={
            "strategy": strategy,
            "exchange": "bybit",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "signals_seen": 1,
            "risk_rejections": 0,
            "execution_rejections": 0,
        },
        trades=[trade],
        signal_events=[event],
    )


def _signal_events(count: int, *, strategy: str) -> list[StrategyTestSignalEvent]:
    base = _signal_event("signal-0").model_copy(update={"strategy_code": strategy})
    return [
        base.model_copy(
            update={
                "synthetic_signal_id": f"signal-{index}",
                "signal_key": f"{strategy}:BTCUSDT:signal-{index}",
            }
        )
        for index in range(count)
    ]


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
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
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
        event_time=now,
        candle_time=now,
        signal_score=80.0,
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
        features_snapshot={"source": "test"},
        trade_plan={"entry": {"price": "100"}},
        metadata={},
        tags=["backtest"],
        created_at=now,
    )


if __name__ == "__main__":
    unittest.main()
