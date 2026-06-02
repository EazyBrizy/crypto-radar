from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
import unittest

from app.schemas.backtest import BacktestResultResponse, BacktestRunRequest, BacktestRunResult
from app.services.backtest_runner import BacktestDetailedRunResult, BacktestSimulatedTrade
from app.services.strategy_test_lab import StrategyTestLabService
from app.strategies.breakout import STRATEGY_NAME as VOLATILITY_SQUEEZE_BREAKOUT
from app.strategies.liquidity_sweep import STRATEGY_NAME as LIQUIDITY_SWEEP_REVERSAL
from app.strategies.trend_pullback import STRATEGY_NAME as TREND_PULLBACK_CONTINUATION


def _load_baseline_module() -> Any:
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "run_strategy_baseline.py"
    spec = importlib.util.spec_from_file_location("run_strategy_baseline", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load baseline script")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_strategy_baseline"] = module
    spec.loader.exec_module(module)
    return module


BASELINE = _load_baseline_module()
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
CREATED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class StrategyBaselineConfigTest(unittest.TestCase):
    def test_baseline_config_contains_existing_strategies(self) -> None:
        expected = {
            LIQUIDITY_SWEEP_REVERSAL,
            VOLATILITY_SQUEEZE_BREAKOUT,
            TREND_PULLBACK_CONTINUATION,
        }

        self.assertEqual(set(BASELINE.BASELINE_STRATEGIES), expected)

    def test_baseline_script_does_not_fake_results_when_no_data(self) -> None:
        service = StrategyTestLabService(_FailingRunner("no_historical_data: no closed candles"))
        output = BASELINE.run_strategy_baseline(
            _config(strategies=(LIQUIDITY_SWEEP_REVERSAL,)),
            service=service,
            baseline_id="baseline-test",
            created_at=CREATED_AT,
            code_revision=None,
        )

        self.assertEqual(output["status"], "no_data")
        self.assertEqual(output["summary"]["no_data_runs"], 1)
        run = output["results"][0]
        self.assertEqual(run["status"], "no_data")
        self.assertTrue(all(value is None for value in run["metrics"].values()))

    def test_baseline_output_schema_is_stable(self) -> None:
        output = BASELINE.run_strategy_baseline(
            _config(strategies=(VOLATILITY_SQUEEZE_BREAKOUT,)),
            service=StrategyTestLabService(_RecordingRunner()),
            baseline_id="baseline-test",
            created_at=CREATED_AT,
            code_revision="abc123",
        )

        run = output["results"][0]
        self.assertEqual(
            set(output.keys()),
            {
                "baseline_id",
                "baseline_version",
                "run_id",
                "lab_run_ids",
                "created_at",
                "code_revision",
                "code_revision_available",
                "status",
                "tags",
                "config",
                "summary",
                "results",
            },
        )
        self.assertEqual(set(run["metrics"].keys()), set(BASELINE.BASELINE_METRIC_KEYS))
        self.assertEqual(run["metrics"]["trades_count"], 1)
        self.assertEqual(run["metrics"]["wins"], 1)
        self.assertEqual(run["metrics"]["losses"], 0)
        self.assertEqual(run["metrics"]["realized_pnl"], Decimal("10"))
        self.assertEqual(run["metrics"]["funding"], Decimal("0"))

    def test_baseline_tags_include_closed_candle_and_strategy(self) -> None:
        output = BASELINE.run_strategy_baseline(
            _config(strategies=(TREND_PULLBACK_CONTINUATION,)),
            service=StrategyTestLabService(_RecordingRunner()),
            baseline_id="baseline-test",
            created_at=CREATED_AT,
            code_revision="abc123",
        )

        tags = output["results"][0]["tags"]
        self.assertEqual(tags["source"], "baseline")
        self.assertEqual(tags["baseline_version"], BASELINE.BASELINE_VERSION)
        self.assertEqual(tags["strategy"], TREND_PULLBACK_CONTINUATION)
        self.assertEqual(tags["symbol"], "BTCUSDT")
        self.assertEqual(tags["timeframe"], "1h")
        self.assertEqual(tags["candle_state"], "closed")
        self.assertEqual(tags["code_revision"], "abc123")
        self.assertEqual(tags["created_at"], "2026-01-02T03:04:05Z")


@dataclass(frozen=True)
class _RunnerCall:
    request: BacktestRunRequest
    mode: str
    options: dict[str, Any]


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[_RunnerCall] = []

    def run_detailed(
        self,
        request: BacktestRunRequest,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
    ) -> BacktestDetailedRunResult:
        self.calls.append(_RunnerCall(request=request, mode=mode, options=options or {}))
        return _detailed_result(request)


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


def _config(
    *,
    strategies: tuple[str, ...],
) -> Any:
    return BASELINE.StrategyBaselineConfig(
        symbols=("BTCUSDT",),
        timeframes=("1h",),
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        initial_equity=Decimal("1000"),
        fees_bps=Decimal("10"),
        slippage_bps=Decimal("1"),
        warmup_bars=3,
        max_bars_in_trade=20,
        strategies=strategies,
    )


def _detailed_result(request: BacktestRunRequest) -> BacktestDetailedRunResult:
    trade = _trade(request)
    metrics = {
        "trades_count": 1,
        "wins": 1,
        "losses": 0,
        "winrate": 1.0,
        "profit_factor": None,
        "realized_pnl": Decimal("10"),
        "expectancy_r": 1.0,
        "max_drawdown_pct": 0.0,
        "avg_bars_in_trade": 3.0,
        "mfe_r_avg": 1.2,
        "mae_r_avg": 0.1,
        "tp1_rate": 1.0,
        "stop_rate": 0.0,
        "fees_total": Decimal("1"),
        "slippage_total": Decimal("0.1"),
        "funding_total": Decimal("0"),
        "risk_rejections": 2,
        "execution_rejections": 0,
    }
    result = BacktestResultResponse(
        run_id=uuid4(),
        user_id=USER_ID,
        strategy_code=request.strategy_code,
        strategy_version=request.strategy_version or "v1",
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_at=request.start_at,
        end_at=request.end_at,
        initial_capital=request.initial_capital,
        final_equity=Decimal("1010"),
        pnl=Decimal("10"),
        pnl_pct=1.0,
        max_drawdown_pct=0.0,
        trades_count=1,
        wins_count=1,
        losses_count=0,
        metrics=metrics,
        equity_curve=[],
        created_at=CREATED_AT,
    )
    return BacktestDetailedRunResult(
        run_result=BacktestRunResult(status="completed", result=result),
        trades=[trade],
        signals_seen=3,
        risk_rejections=2,
        execution_rejections=0,
        assumptions={"source": "strategy_lab"},
    )


def _trade(request: BacktestRunRequest) -> BacktestSimulatedTrade:
    now = request.start_at
    return BacktestSimulatedTrade(
        trade_id=f"trade-{request.strategy_code}",
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
        exit_price=Decimal("101"),
        stop_loss=Decimal("99"),
        targets=[{"label": "TP1", "price": Decimal("101"), "hit": True}],
        selected_rr=2.0,
        realized_r=1.0,
        pnl=Decimal("10"),
        pnl_pct=1.0,
        fees=Decimal("1"),
        slippage=Decimal("0.1"),
        mfe_r=1.2,
        mae_r=0.1,
        bars_to_entry=0,
        bars_in_trade=3,
        close_reason="take_profit",
        outcome="win",
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
