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
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
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
    ) -> BacktestDetailedRunResult:
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
    def __init__(self, fail_on: set[int] | None = None) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self._fail_on = fail_on or set()

    def run_scenario(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        request: StrategyTestRunRequest,
        strategy: str,
        pair: StrategyTestPair,
        timeframe: str,
    ) -> StrategyTestScenarioResult:
        _ = run_id, user_id, request
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
    ) -> StrategyTestMatrixResult:
        _ = request, run_id, user_uuid
        return self.result


class _RecordingTradeStore:
    def __init__(self) -> None:
        self.trades: list[StrategyTestTrade] = []

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.trades.extend(trades)


class _EphemeralRunStore:
    def __init__(self) -> None:
        self.detail: StrategyTestRunDetailResponse | None = None
        self.transitions: list[str] = []

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


if __name__ == "__main__":
    unittest.main()
