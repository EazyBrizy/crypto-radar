from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID, uuid4
import unittest

from app.schemas.backtest import BacktestRunResult
from app.services.backtest_runner import BacktestDetailedRunResult
from app.services.strategy_testing.assumptions import build_strategy_test_assumptions
from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult, StrategyTestMatrixRunner
from app.services.strategy_testing.runner import StrategyTestScenarioResult, StrategyTestScenarioRunner
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)
from app.services.strategy_testing.service import StrategyTestingService


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")


class StrategyTestMatrixRunnerTest(unittest.TestCase):
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
            for strategy in request.strategies
            for pair in request.pairs
            for timeframe in request.timeframes
        ]
        self.assertEqual(scenario_runner.calls, expected_calls)

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

    def test_matrix_collects_signal_events_and_builds_funnel_metrics(self) -> None:
        request = _matrix_request(strategies=["s1"], pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")])
        scenario_runner = _RecordingScenarioRunner(
            signal_events=[
                _signal_event("signal-1", entry_touched=True, filled=True, closed=True, outcome="win"),
                _signal_event("signal-2", no_entry=True, outcome="no_entry", funnel_stage="no_entry"),
            ]
        )
        matrix_runner = StrategyTestMatrixRunner(scenario_runner)

        result = matrix_runner.run_matrix(request=request, run_id=RUN_ID, user_uuid=USER_ID)

        self.assertEqual(len(result.signal_events), 2)
        self.assertEqual(result.summary()["signals_count"], 2)
        summary_metrics = {metric["code"]: metric for metric in result.summary()["summary_metrics"]}
        self.assertEqual(summary_metrics["signals_count"]["value"], 2)
        self.assertAlmostEqual(summary_metrics["entry_touch_rate"]["value"], 0.5)

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


class StrategyTestingServiceMatrixTest(unittest.TestCase):
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


@dataclass(frozen=True)
class _BacktestCall:
    request: Any
    mode: str
    options: dict[str, Any]


class _FakeBacktestRunner:
    def __init__(self) -> None:
        self.calls: list[_BacktestCall] = []

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
        signal_events: list[StrategyTestSignalEvent] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self._fail_on = fail_on or set()
        self._signal_events = signal_events or []

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
    ) -> StrategyTestScenarioResult:
        _ = run_id, user_id, request, is_cancelled, on_progress
        index = len(self.calls)
        self.calls.append((strategy, pair.exchange, pair.symbol, timeframe))
        if index in self._fail_on:
            raise ValueError(f"scenario {index} failed")
        return StrategyTestScenarioResult(
            run_id=RUN_ID,
            strategy=strategy,
            pair=pair,
            timeframe=timeframe,
            summary={
                "strategy": strategy,
                "exchange": pair.exchange,
                "symbol": pair.symbol,
                "timeframe": timeframe,
                "signals_seen": 1,
                "risk_rejections": 0,
                "execution_rejections": 0,
            },
            trades=[],
            signal_events=list(self._signal_events),
        )


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
    ) -> StrategyTestMatrixResult:
        _ = user_uuid, on_scenario_started, on_scenario_failed, on_scenario_progress, is_cancelled
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

    def mark_failed(self, run_id: UUID, error: str) -> StrategyTestRunDetailResponse:
        _ = run_id
        self.transitions.append("failed")
        return self._mark("failed", error=error)

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
        "mode": request.mode,
        "strategies": list(request.strategies),
        "pairs": [pair.model_dump() for pair in request.pairs],
        "timeframes": list(request.timeframes),
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
