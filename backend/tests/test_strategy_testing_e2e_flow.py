from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from app.repositories.strategy_execution_eligibility import StrategyExecutionEligibilityProfileUpsert
from app.services.strategy_testing.eligibility_profiles import StrategyExecutionEligibilityProfileUpdater
from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult
from app.services.strategy_testing.report_builder import build_matrix_metric_results
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestMode,
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTrade,
)
from app.services.strategy_testing.service import StrategyTestingService


RUN_ID = UUID("77777777-7777-4777-8777-777777777777")
NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


class StrategyTestingE2EFlowTest(unittest.TestCase):
    def test_historical_backtest_writes_trades_metrics_and_updates_execution_profile(self) -> None:
        request = _request()
        run_store = _E2ERunStore(run_id=RUN_ID)
        trade_store = _RecordingStrategyTestTradeStore()
        profile_repository = _RecordingEligibilityProfileRepository()
        service = StrategyTestingService(
            run_store=run_store,
            trade_store=trade_store,
            matrix_runner=_DeterministicBacktestMatrixRunner(),
            eligibility_profile_updater=StrategyExecutionEligibilityProfileUpdater(
                repository=profile_repository,
            ),
        )

        completed = service.create_run(request)

        self.assertEqual(completed.run_id, RUN_ID)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.test_type, "historical_backtest")
        self.assertEqual(completed.summary["scenario_count"], 1)
        self.assertEqual(completed.summary["trades_count"], 60)
        self.assertEqual(completed.summary["completed_scenarios"], 1)
        self.assertEqual(run_store.statuses, ["queued", "running", "completed"])
        self.assertEqual(len(trade_store.trades), 60)
        self.assertGreater(len(trade_store.metrics), 0)
        self.assertTrue(
            any(
                row.metric_code == "expectancy_after_costs_r"
                and row.strategy_code == "trend_pullback_continuation"
                and row.exchange == "bybit"
                and row.symbol == "BTCUSDT"
                and row.timeframe == "15m"
                and row.market_regime == "trend"
                and row.score_bucket == "80-89"
                and row.direction == "long"
                for row in trade_store.metrics
            )
        )

        self.assertEqual(len(profile_repository.profiles), 1)
        profile = profile_repository.profiles[0]
        self.assertEqual(profile.strategy_code, "trend_pullback_continuation")
        self.assertEqual(profile.exchange, "bybit")
        self.assertEqual(profile.symbol_scope, "BTCUSDT")
        self.assertEqual(profile.timeframe, "15m")
        self.assertEqual(profile.market_regime, "trend")
        self.assertEqual(profile.score_bucket, "80-89")
        self.assertEqual(profile.direction, "long")
        self.assertEqual(profile.source, "historical_backtest")
        self.assertTrue(profile.eligible)
        self.assertEqual(profile.sample_size, 60)
        self.assertGreater(profile.expectancy_after_costs_r or 0.0, 0.05)
        self.assertGreater(profile.profit_factor or 0.0, 1.15)
        self.assertIn(str(RUN_ID), profile.run_ids)
        self.assertEqual(profile.reason_code, "strategy_eligibility_passed")


class _E2ERunStore:
    def __init__(self, *, run_id: UUID) -> None:
        self._run_id = run_id
        self._runs: dict[UUID, StrategyTestRunDetailResponse] = {}
        self.statuses: list[str] = []

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        run = StrategyTestRunResponse(
            run_id=self._run_id,
            status="queued",
            test_type=request.test_type,
            requested_matrix=_requested_matrix(request),
            created_at=NOW,
        )
        detail = StrategyTestRunDetailResponse(run=run)
        self._runs[run.run_id] = detail
        self.statuses.append("queued")
        return detail

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        runs = list(self._runs.values())
        if user_id is not None:
            runs = [detail for detail in runs if detail.run.requested_matrix["user_id"] == user_id]
        if status is not None:
            runs = [detail for detail in runs if detail.run.status == status]
        return runs[:limit]

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        return self._runs.get(run_id)

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._update_run(
            run_id,
            status="running",
            started_at=NOW,
            last_heartbeat_at=NOW,
        )

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        return self._update_run(
            run_id,
            status="completed",
            summary=dict(summary or {}),
            finished_at=NOW + timedelta(seconds=5),
            last_heartbeat_at=NOW + timedelta(seconds=5),
        )

    def mark_failed(self, run_id: UUID, error: str) -> StrategyTestRunDetailResponse:
        return self._update_run(
            run_id,
            status="failed",
            error=error,
            finished_at=NOW + timedelta(seconds=5),
            last_heartbeat_at=NOW + timedelta(seconds=5),
        )

    def mark_stopping(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._update_run(run_id, status="stopping", last_heartbeat_at=NOW)

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._update_run(
            run_id,
            status="cancelled",
            finished_at=NOW + timedelta(seconds=5),
            last_heartbeat_at=NOW + timedelta(seconds=5),
        )

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        update: dict[str, Any] = {
            "runtime_state": {**detail.run.runtime_state, **runtime_state},
        }
        if heartbeat:
            update["last_heartbeat_at"] = NOW
        updated = detail.run.model_copy(update=update)
        detail = StrategyTestRunDetailResponse(run=updated)
        self._runs[run_id] = detail
        return detail

    def _update_run(self, run_id: UUID, **updates: Any) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated = detail.run.model_copy(update=updates)
        detail = StrategyTestRunDetailResponse(run=updated)
        self._runs[run_id] = detail
        status = updates.get("status")
        if isinstance(status, str):
            self.statuses.append(status)
        return detail


class _RecordingStrategyTestTradeStore:
    def __init__(self) -> None:
        self.trades: list[StrategyTestTrade] = []
        self.metrics: list[StrategyTestMetricRow] = []

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.trades.extend(trades)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.metrics.extend(rows)

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        _ = limit, offset
        return [trade for trade in self.trades if trade.run_id == run_id]


class _RecordingEligibilityProfileRepository:
    def __init__(self) -> None:
        self.profiles: list[StrategyExecutionEligibilityProfileUpsert] = []

    def upsert_profile(
        self,
        profile: StrategyExecutionEligibilityProfileUpsert,
    ) -> StrategyExecutionEligibilityProfileUpsert:
        self.profiles.append(profile)
        return profile


class _DeterministicBacktestMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
    ) -> StrategyTestMatrixResult:
        trades = _profitable_trade_sample(
            run_id=run_id,
            user_uuid=user_uuid,
            mode=request.mode,
        )
        metrics = build_matrix_metric_results(trades, metric_set=request.metric_set)
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=1,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[
                {
                    "strategy": "trend_pullback_continuation",
                    "exchange": "bybit",
                    "symbol": "BTCUSDT",
                    "timeframe": "15m",
                    "signals_seen": 60,
                    "risk_rejections": 0,
                    "execution_rejections": 0,
                }
            ],
            trades=trades,
            metrics=metrics,
        )


def _request() -> StrategyTestRunRequest:
    return StrategyTestRunRequest(
        user_id="e2e_user",
        test_type="historical_backtest",
        strategies=["trend_pullback_continuation"],
        pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
        timeframes=["15m"],
        start_at=NOW - timedelta(days=30),
        end_at=NOW,
        mode="research_virtual",
        initial_capital=Decimal("1000"),
        fee_rate=Decimal("0.001"),
        slippage_bps=Decimal("0"),
        tags=["backtest", "e2e"],
    )


def _profitable_trade_sample(
    *,
    run_id: UUID,
    user_uuid: UUID,
    mode: StrategyTestMode,
) -> list[StrategyTestTrade]:
    trades: list[StrategyTestTrade] = []
    for index in range(60):
        won = index % 3 != 0
        realized_r = 1.0 if won else -0.5
        entry_time = NOW - timedelta(days=2) + timedelta(minutes=index * 15)
        trades.append(
            StrategyTestTrade(
                run_id=run_id,
                trade_id=f"trade_{index + 1}",
                user_id=user_uuid,
                mode=mode,
                strategy_code="trend_pullback_continuation",
                strategy_version="1.0.0",
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="15m",
                direction="long",
                signal_score=82.0,
                market_regime="trend",
                score_bucket="80-89",
                entry_time=entry_time,
                exit_time=entry_time + timedelta(minutes=45),
                entry_price=Decimal("100"),
                exit_price=Decimal("110") if won else Decimal("95"),
                stop_loss=Decimal("95"),
                targets=[{"price": "110", "rr": 2.0}],
                selected_rr=2.0,
                realized_r=realized_r,
                pnl=Decimal("10") if won else Decimal("-5"),
                pnl_pct=10.0 if won else -5.0,
                fees=Decimal("0.10"),
                slippage=Decimal("0.00"),
                mfe_r=1.2 if won else 0.2,
                mae_r=-0.1 if won else -0.5,
                bars_to_entry=1,
                bars_in_trade=3,
                close_reason="take_profit" if won else "stop_loss",
                outcome="win" if won else "loss",
                risk_rejected=False,
                execution_rejected=False,
                warnings=[],
                features_snapshot={"source": "deterministic_e2e"},
                trade_plan={"entry": {"price": "100"}, "source": "backend"},
                tags=["backtest", "e2e"],
                created_at=entry_time,
            )
        )
    return trades


def _requested_matrix(request: StrategyTestRunRequest) -> dict[str, Any]:
    return {
        "user_id": request.user_id,
        "test_type": request.test_type,
        "mode": request.mode,
        "strategies": request.strategies,
        "pairs": [pair.model_dump(mode="json") for pair in request.pairs],
        "timeframes": request.timeframes,
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


if __name__ == "__main__":
    unittest.main()
