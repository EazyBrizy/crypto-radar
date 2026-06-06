from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID, uuid4
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.strategy_tests import get_strategy_testing_service
from app.api.v1.router import api_router
from app.main import app
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignal,
    StrategyTestTrade,
)
from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult
from app.services.strategy_testing.service import StrategyTestingService


class StrategyTestingApiContractTest(unittest.TestCase):
    def test_run_request_accepts_matrix_inputs(self) -> None:
        request = _request()

        self.assertEqual(
            request.strategies,
            [
                "trend_pullback_continuation",
                "volatility_squeeze_breakout",
                "liquidity_sweep_reversal",
            ],
        )
        self.assertEqual(len(request.pairs), 2)
        self.assertEqual(request.pairs[0].exchange, "bybit")
        self.assertEqual(request.pairs[0].symbol, "BTCUSDT")
        self.assertEqual(request.timeframes, ["1h", "4h"])

    def test_end_at_must_be_after_start_at(self) -> None:
        request = _request()

        with self.assertRaises(ValidationError):
            StrategyTestRunRequest(
                **request.model_dump(exclude={"end_at"}),
                end_at=request.start_at,
            )

    def test_duplicate_strategies_and_timeframes_are_deduped(self) -> None:
        now = _now()

        request = StrategyTestRunRequest(
            strategies=[" breakout ", "breakout", " trend_pullback_continuation "],
            pairs=[StrategyTestPair(exchange="bybit", symbol="btcusdt")],
            timeframes=[" 1h ", "1h", "4h"],
            start_at=now,
            end_at=now + timedelta(days=1),
        )

        self.assertEqual(request.strategies, ["breakout", "trend_pullback_continuation"])
        self.assertEqual(request.timeframes, ["1h", "4h"])

    def test_tags_always_include_backtest(self) -> None:
        request = _request(tags=["research"])

        self.assertEqual(request.tags, ["research", "backtest"])

    def test_post_runs_accepts_matrix_request(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.post("/api/v1/strategy-tests/runs", json=_payload())
            list_response = client.get("/api/v1/strategy-tests/runs")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(list_response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "queued")
        self.assertIn("run_id", data)
        self.assertEqual(
            data["requested_matrix"]["strategies"],
            [
                "trend_pullback_continuation",
                "volatility_squeeze_breakout",
                "liquidity_sweep_reversal",
            ],
        )
        self.assertEqual(
            data["requested_matrix"]["pairs"],
            [
                {"exchange": "bybit", "symbol": "BTCUSDT"},
                {"exchange": "binance", "symbol": "ETHUSDT"},
            ],
        )
        self.assertEqual(data["requested_matrix"]["timeframes"], ["1h", "4h"])
        self.assertEqual(data["requested_matrix"]["scenario_count"], 12)
        self.assertEqual(list_response.json()[0]["run_id"], data["run_id"])
        self.assertEqual(list_response.json()[0]["status"], "completed")
        self.assertEqual(list_response.json()[0]["summary"]["scenario_count"], 12)

    def test_existing_backtests_route_remains_registered(self) -> None:
        route_paths = {route.path for route in api_router.routes}

        self.assertIn("/api/v1/backtests/run", route_paths)
        self.assertIn("/api/v1/backtests/results", route_paths)

    def test_get_strategy_test_signals_route_returns_signal_rows(self) -> None:
        run_store = _EphemeralStrategyTestRunStore()
        detail = run_store.create_run(_request())
        trade_store = _EphemeralStrategyTestTradeStore(signals=[_signal(detail.run.run_id)])
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=run_store,
            trade_store=trade_store,
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.get(f"/api/v1/strategy-tests/runs/{detail.run.run_id}/signals")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]["signal_id"], "signal-1")
        self.assertEqual(data[0]["outcome"], "no_entry")
        self.assertTrue(data[0]["no_entry"])


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _request(tags: list[str] | None = None) -> StrategyTestRunRequest:
    now = _now()
    request_kwargs = {
        "strategies": [
            "trend_pullback_continuation",
            "volatility_squeeze_breakout",
            "liquidity_sweep_reversal",
        ],
        "pairs": [
            StrategyTestPair(exchange=" BYBIT ", symbol=" btcusdt "),
            StrategyTestPair(exchange="BINANCE", symbol="ethusdt"),
        ],
        "timeframes": ["1h", "4h"],
        "start_at": now,
        "end_at": now + timedelta(days=30),
        "initial_capital": Decimal("1000"),
    }
    if tags is not None:
        request_kwargs["tags"] = tags
    return StrategyTestRunRequest(**request_kwargs)


def _payload() -> dict[str, object]:
    now = _now()
    return {
        "strategies": [
            "trend_pullback_continuation",
            "volatility_squeeze_breakout",
            "liquidity_sweep_reversal",
        ],
        "pairs": [
            {"exchange": " BYBIT ", "symbol": " btcusdt "},
            {"exchange": "binance", "symbol": "ETHUSDT"},
        ],
        "timeframes": ["1h", "4h"],
        "start_at": now.isoformat(),
        "end_at": (now + timedelta(days=30)).isoformat(),
        "mode": "research_virtual",
        "initial_capital": "1000",
        "fee_rate": "0.001",
        "slippage_bps": "0",
        "params": {"risk": "standard"},
    }


class _EphemeralStrategyTestRunStore:
    def __init__(self) -> None:
        self._runs: dict[UUID, StrategyTestRunDetailResponse] = {}

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        run = StrategyTestRunResponse(
            run_id=uuid4(),
            status="queued",
            requested_matrix=_requested_matrix(request),
        )
        detail = StrategyTestRunDetailResponse(run=run)
        self._runs[run.run_id] = detail
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
        return self._mark(run_id, "running")

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        detail = self._mark(run_id, "completed")
        if summary is None:
            return detail
        updated = detail.run.model_copy(update={"summary": summary})
        detail = StrategyTestRunDetailResponse(run=updated)
        self._runs[run_id] = detail
        return detail

    def mark_failed(self, run_id: UUID, error: str) -> StrategyTestRunDetailResponse:
        _ = error
        return self._mark(run_id, "failed")

    def _mark(self, run_id: UUID, status: StrategyTestRunStatus) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated = detail.run.model_copy(update={"status": status})
        detail = StrategyTestRunDetailResponse(run=updated)
        self._runs[run_id] = detail
        return detail


class _EphemeralStrategyTestTradeStore:
    def __init__(self, signals: Sequence[StrategyTestSignal] | None = None) -> None:
        self.trades: list[StrategyTestTrade] = []
        self.signals: list[StrategyTestSignal] = list(signals or [])
        self.metrics: list[StrategyTestMetricRow] = []

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.trades.extend(trades)

    def write_signals(self, signals: Sequence[StrategyTestSignal]) -> None:
        self.signals.extend(signals)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.metrics.extend(rows)

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        _ = run_id, limit, offset
        return list(self.trades)

    def list_signals(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestSignal]:
        _ = run_id, limit, offset
        return list(self.signals)


class _NoopStrategyTestMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
    ) -> StrategyTestMatrixResult:
        _ = user_uuid
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=len(request.strategies) * len(request.pairs) * len(request.timeframes),
            completed_scenarios=len(request.strategies) * len(request.pairs) * len(request.timeframes),
            failed_scenarios=0,
            scenario_summaries=[],
            signals=[],
            trades=[],
        )


def _requested_matrix(request: StrategyTestRunRequest) -> dict[str, Any]:
    return {
        "user_id": request.user_id,
        "mode": request.mode,
        "strategies": request.strategies,
        "pairs": [pair.model_dump() for pair in request.pairs],
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


def _signal(run_id: UUID) -> StrategyTestSignal:
    now = _now()
    return StrategyTestSignal(
        run_id=run_id,
        user_id=UUID("22222222-2222-4222-8222-222222222222"),
        mode="research_virtual",
        scenario_id="trend_pullback_continuation:bybit:BTCUSDT:1h",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="long",
        signal_id="signal-1",
        signal_time=now,
        signal_score=80.0,
        feed_kind="execution_signal",
        gate_status="passed",
        status="actionable",
        trigger_passed=True,
        edge_status="positive",
        selected_rr=1.0,
        entry_min=Decimal("100"),
        entry_max=Decimal("101"),
        stop_loss=Decimal("99"),
        target_1=Decimal("102"),
        outcome="no_entry",
        outcome_reason="entry_not_touched",
        entry_touched=False,
        filled=False,
        risk_rejected=False,
        execution_rejected=False,
        no_entry=True,
        bars_to_entry=None,
        bars_to_outcome=3,
        metadata={"source": "api-test"},
        created_at=now,
    )


if __name__ == "__main__":
    unittest.main()
