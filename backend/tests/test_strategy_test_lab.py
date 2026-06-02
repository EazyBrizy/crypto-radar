from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4
import unittest

from app.api.v1.router import api_router
from app.schemas.backtest import BacktestResultResponse, BacktestRunRequest, BacktestRunResult
from app.schemas.strategy_lab import StrategyLabMatrixRequest
from app.services.backtest_runner import BacktestDetailedRunResult, BacktestSimulatedTrade
from app.services.strategy_test_lab import LAB_BACKTEST_MODE, StrategyTestLabService


USER_ID = UUID("22222222-2222-4222-8222-222222222222")


class StrategyTestLabTest(unittest.TestCase):
    def test_strategy_lab_expands_matrix_to_backtest_requests(self) -> None:
        runner = _RecordingRunner()
        service = StrategyTestLabService(runner)
        request = _matrix_request(
            strategies=["s1", "s2"],
            symbols=["BTCUSDT", "ETHUSDT"],
            timeframes=["1h", "4h"],
            fees_bps=Decimal("5"),
            warmup_bars=12,
            max_bars_in_trade=20,
        )

        result = service.run_matrix(request)

        self.assertEqual(result.scenario_count, 8)
        self.assertEqual(len(runner.calls), 8)
        first_call = runner.calls[0]
        self.assertEqual(first_call.request.strategy_code, "s1")
        self.assertEqual(first_call.request.exchange, "bybit")
        self.assertEqual(first_call.request.symbol, "BTCUSDT")
        self.assertEqual(first_call.request.timeframe, "1h")
        self.assertEqual(first_call.request.fee_rate, Decimal("0.0005"))
        self.assertEqual(first_call.request.params["warmup_candles"], 12)
        self.assertEqual(first_call.request.params["max_bars_in_trade"], 20)
        self.assertEqual(first_call.mode, LAB_BACKTEST_MODE)
        self.assertFalse(first_call.options["risk_gate_enabled"])
        self.assertFalse(first_call.options["rr_hard_gate_enabled"])
        self.assertEqual(first_call.options["tags"]["source"], "strategy_lab")
        self.assertEqual(first_call.options["tags"]["mode"], "baseline")
        self.assertEqual(first_call.options["tags"]["candle_state"], "closed")

    def test_strategy_lab_does_not_call_real_execution(self) -> None:
        service = StrategyTestLabService(_RecordingRunner())

        with patch(
            "app.services.execution_service.RealExecutionService.place_order",
            side_effect=AssertionError("Strategy Lab must not call real execution"),
        ):
            result = service.run_matrix(_matrix_request())

        self.assertEqual(result.completed_runs, 1)
        self.assertFalse(result.metadata["real_execution_side_effects"])

    def test_strategy_lab_aggregates_results_by_strategy_symbol_timeframe(self) -> None:
        runner = _RecordingRunner(
            {
                "s1": _ScenarioMetrics(trades_count=2, win_rate=0.5, fees=Decimal("1.5")),
                "s2": _ScenarioMetrics(trades_count=1, win_rate=1.0, fees=Decimal("0.5")),
            }
        )
        service = StrategyTestLabService(runner)
        request = _matrix_request(strategies=["s1", "s2"])

        result = service.run_matrix(request)

        self.assertEqual(result.overall_summary.total_trades, 3)
        self.assertAlmostEqual(result.overall_summary.win_rate or 0.0, 2 / 3)
        self.assertEqual(result.overall_summary.fees_paid, Decimal("2.0"))
        self.assertEqual(result.metrics_by_strategy["s1"].total_trades, 2)
        self.assertEqual(result.metrics_by_strategy["s2"].total_trades, 1)
        self.assertEqual(result.metrics_by_symbol["BTCUSDT"].total_trades, 3)
        self.assertEqual(result.metrics_by_timeframe["1h"].total_trades, 3)

    def test_strategy_lab_preserves_existing_backtest_endpoint(self) -> None:
        route_paths = {route.path for route in api_router.routes}

        self.assertIn("/api/v1/backtests/run", route_paths)
        self.assertIn("/api/v1/backtests/results", route_paths)
        self.assertIn("/api/v1/strategy-lab/run", route_paths)
        self.assertIn("/api/v1/strategy-lab/matrix", route_paths)

    def test_strategy_lab_handles_no_data_without_fake_metrics(self) -> None:
        no_data_result = StrategyTestLabService(_FailingRunner("no_historical_data: no closed candles")).run_matrix(
            _matrix_request()
        )
        insufficient_result = StrategyTestLabService(
            _FailingRunner("not_enough_data: 1 candles loaded")
        ).run_matrix(_matrix_request())

        no_data_item = no_data_result.runs[0]
        self.assertEqual(no_data_item.status, "no_data")
        self.assertEqual(no_data_result.no_data_runs, 1)
        self.assertEqual(no_data_result.overall_summary.status, "no_data")
        self.assertIsNone(no_data_item.summary.total_trades)
        self.assertIsNone(no_data_item.summary.win_rate)
        self.assertIsNone(no_data_item.summary.fees_paid)
        self.assertEqual(no_data_item.metrics, {})

        insufficient_item = insufficient_result.runs[0]
        self.assertEqual(insufficient_item.status, "insufficient_data")
        self.assertEqual(insufficient_result.insufficient_data_runs, 1)
        self.assertEqual(insufficient_result.overall_summary.status, "insufficient_data")
        self.assertIsNone(insufficient_item.summary.total_trades)
        self.assertEqual(insufficient_item.metrics, {})


@dataclass(frozen=True)
class _RunnerCall:
    request: BacktestRunRequest
    mode: str
    options: dict[str, Any]


@dataclass(frozen=True)
class _ScenarioMetrics:
    trades_count: int = 1
    win_rate: float = 1.0
    fees: Decimal = Decimal("0")


class _RecordingRunner:
    def __init__(self, metrics_by_strategy: dict[str, _ScenarioMetrics] | None = None) -> None:
        self.calls: list[_RunnerCall] = []
        self._metrics_by_strategy = metrics_by_strategy or {}

    def run_detailed(
        self,
        request: BacktestRunRequest,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
    ) -> BacktestDetailedRunResult:
        self.calls.append(_RunnerCall(request=request, mode=mode, options=options or {}))
        scenario_metrics = self._metrics_by_strategy.get(request.strategy_code, _ScenarioMetrics())
        return _detailed_result(request, scenario_metrics)


class _FailingRunner:
    def __init__(self, error: str) -> None:
        self.error = error

    def run_detailed(
        self,
        request: BacktestRunRequest,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
    ) -> BacktestDetailedRunResult:
        _ = request, mode, options
        raise ValueError(self.error)


def _matrix_request(
    *,
    strategies: list[str] | None = None,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    fees_bps: Decimal = Decimal("10"),
    warmup_bars: int = 3,
    max_bars_in_trade: int | None = None,
) -> StrategyLabMatrixRequest:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return StrategyLabMatrixRequest(
        user_id=str(USER_ID),
        exchange="bybit",
        strategies=strategies or ["s1"],
        symbols=symbols or ["BTCUSDT"],
        timeframes=timeframes or ["1h"],
        start_time=start,
        end_time=start + timedelta(days=1),
        initial_equity=Decimal("1000"),
        fees_bps=fees_bps,
        slippage_bps=Decimal("1"),
        max_bars_in_trade=max_bars_in_trade,
        warmup_bars=warmup_bars,
        mode="baseline",
        label="lab-test",
        tags={"owner": "tests"},
    )


def _detailed_result(
    request: BacktestRunRequest,
    scenario_metrics: _ScenarioMetrics,
) -> BacktestDetailedRunResult:
    trades = [
        _trade(
            request=request,
            index=index,
            realized_r=1.0 if index < round(scenario_metrics.trades_count * scenario_metrics.win_rate) else -1.0,
            fees=scenario_metrics.fees / max(scenario_metrics.trades_count, 1),
        )
        for index in range(scenario_metrics.trades_count)
    ]
    metrics = {
        "trades_count": scenario_metrics.trades_count,
        "winrate": scenario_metrics.win_rate,
        "profit_factor": 2.0,
        "expectancy_r": sum(trade.realized_r or 0.0 for trade in trades) / len(trades) if trades else 0.0,
        "max_drawdown_pct": 1.0,
        "avg_bars_in_trade": 3.0 if trades else 0.0,
        "stop_rate": 0.0,
        "tp1_rate": scenario_metrics.win_rate,
        "fees_total": scenario_metrics.fees,
        "slippage_total": Decimal("0.1"),
    }
    result = BacktestResultResponse(
        run_id=uuid4(),
        user_id=UUID(request.user_id),
        strategy_code=request.strategy_code,
        strategy_version=request.strategy_version or "v1",
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_at=request.start_at,
        end_at=request.end_at,
        initial_capital=request.initial_capital,
        final_equity=request.initial_capital,
        pnl=Decimal("0"),
        pnl_pct=0.0,
        max_drawdown_pct=1.0,
        trades_count=scenario_metrics.trades_count,
        wins_count=round(scenario_metrics.trades_count * scenario_metrics.win_rate),
        losses_count=scenario_metrics.trades_count
        - round(scenario_metrics.trades_count * scenario_metrics.win_rate),
        metrics=metrics,
        equity_curve=[],
        created_at=datetime.now(timezone.utc),
    )
    return BacktestDetailedRunResult(
        run_result=BacktestRunResult(status="completed", result=result),
        trades=trades,
        signals_seen=scenario_metrics.trades_count,
        risk_rejections=1,
        execution_rejections=0,
        assumptions={"source": "strategy_lab"},
    )


def _trade(
    *,
    request: BacktestRunRequest,
    index: int,
    realized_r: float,
    fees: Decimal,
) -> BacktestSimulatedTrade:
    now = request.start_at + timedelta(hours=index)
    return BacktestSimulatedTrade(
        trade_id=f"trade-{request.strategy_code}-{index}",
        strategy_code=request.strategy_code,
        strategy_version=request.strategy_version or "v1",
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
        direction="long",
        signal_score=80.0,
        market_regime="unknown",
        score_bucket="80-89",
        entry_time=now,
        exit_time=now + timedelta(hours=1),
        entry_price=Decimal("100"),
        exit_price=Decimal("101") if realized_r > 0 else Decimal("99"),
        stop_loss=Decimal("99"),
        targets=[
            {"label": "TP1", "price": Decimal("101"), "hit": realized_r > 0},
            {"label": "TP2", "price": Decimal("102"), "hit": realized_r > 0},
        ],
        selected_rr=2.0,
        realized_r=realized_r,
        pnl=Decimal("10") if realized_r > 0 else Decimal("-10"),
        pnl_pct=1.0 if realized_r > 0 else -1.0,
        fees=fees,
        slippage=Decimal("0.1"),
        mfe_r=1.0,
        mae_r=0.2,
        bars_to_entry=0,
        bars_in_trade=3,
        close_reason="take_profit" if realized_r > 0 else "stop_loss",
        outcome="win" if realized_r > 0 else "loss",
        risk_rejected=False,
        execution_rejected=False,
        warnings=[],
        features_snapshot={"trade_plan": {"metadata": {"fallback_used": False}}},
        trade_plan={"metadata": {"fallback_used": False, "trade_plan_complete": True}},
        tags=["backtest"],
        created_at=now,
    )


if __name__ == "__main__":
    unittest.main()
