from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.router import api_router
from app.api.v1.strategy_tests import get_strategy_testing_service
from app.main import app
from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult
from app.services.strategy_testing.metrics import MetricResult
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTrade,
)
from app.services.strategy_testing.service import StrategyTestingService


class StrategyTestingApiContractTest(unittest.TestCase):
    def test_run_request_accepts_matrix_inputs(self) -> None:
        request = _request()

        self.assertEqual(request.test_type, "historical_backtest")
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

    def test_run_request_accepts_forward_virtual_test_type(self) -> None:
        request = _request(test_type="forward_virtual")

        self.assertEqual(request.test_type, "forward_virtual")

    def test_run_response_exposes_forward_runtime_fields_and_statuses(self) -> None:
        heartbeat = _now()

        response = StrategyTestRunResponse(
            run_id=uuid4(),
            status="stopping",
            test_type="forward_virtual",
            requested_matrix={},
            summary={"scenario_count": 1},
            runtime_state={"processed_candles": 3},
            last_heartbeat_at=heartbeat,
        )

        payload = response.model_dump(mode="json")

        self.assertEqual(payload["status"], "stopping")
        self.assertEqual(payload["test_type"], "forward_virtual")
        self.assertEqual(payload["summary"], {"scenario_count": 1})
        self.assertEqual(payload["runtime_state"], {"processed_candles": 3})
        self.assertEqual(payload["last_heartbeat_at"], "2026-01-01T00:00:00Z")

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
        self.assertEqual(data["test_type"], "historical_backtest")
        self.assertEqual(data["runtime_state"], {})
        self.assertIsNone(data["last_heartbeat_at"])
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
        self.assertEqual(data["requested_matrix"]["test_type"], "historical_backtest")
        self.assertEqual(data["requested_matrix"]["scenario_count"], 12)
        self.assertEqual(list_response.json()[0]["run_id"], data["run_id"])
        self.assertEqual(list_response.json()[0]["status"], "completed")
        self.assertEqual(list_response.json()[0]["test_type"], "historical_backtest")
        self.assertEqual(list_response.json()[0]["summary"]["scenario_count"], 12)

    def test_post_forward_virtual_run_starts_runtime_without_historical_matrix(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_FailingStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.post(
                "/api/v1/strategy-tests/runs",
                json={**_payload(), "test_type": "forward_virtual"},
            )
            list_response = client.get("/api/v1/strategy-tests/runs")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(response.json()["test_type"], "forward_virtual")
        self.assertEqual(list_response.json()[0]["status"], "running")
        self.assertEqual(list_response.json()[0]["test_type"], "forward_virtual")
        self.assertEqual(list_response.json()[0]["runtime_state"]["status"], "listening")
        self.assertEqual(list_response.json()[0]["runtime_state"]["processed_signals"], 0)

    def test_completed_historical_run_updates_execution_eligibility_profiles(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        updater = _RecordingEligibilityProfileUpdater()
        service = StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_MetricStrategyTestMatrixRunner(),  # type: ignore[arg-type]
            eligibility_profile_updater=updater,
        )

        created = store.create_run(_request())
        completed = service.execute_run(created.run.run_id, _request())

        self.assertEqual(completed.status, "completed")
        self.assertEqual(len(updater.calls), 1)
        call = updater.calls[0]
        self.assertEqual(call["run_id"], created.run.run_id)
        self.assertEqual(call["request"].test_type, "historical_backtest")
        self.assertIn("expectancy_after_costs_r", {metric.code for metric in call["metrics"]})

    def test_active_run_endpoint_returns_backend_gate_state(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        heartbeat = datetime.now(timezone.utc)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="running",
            test_type="forward_virtual",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={"processed_candles": 1},
            created_at=heartbeat,
            started_at=heartbeat,
            last_heartbeat_at=heartbeat,
        )
        store.upsert(active)
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.get("/api/v1/strategy-tests/runs/active?user_id=demo_user")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["can_run"])
        self.assertEqual(data["disabled_reason_code"], "active_strategy_test_run")
        self.assertIn(str(active.run_id), data["disabled_reason"])
        self.assertFalse(data["is_stale"])
        self.assertEqual(data["active_run"]["run_id"], str(active.run_id))
        self.assertIn("refresh", data["allowed_actions"])
        self.assertIn("cancel", data["allowed_actions"])

    def test_active_run_endpoint_allows_run_when_active_run_is_stale(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        stale_started_at = _now() - timedelta(hours=1)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="running",
            test_type="forward_virtual",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={},
            created_at=stale_started_at,
            started_at=stale_started_at,
            last_heartbeat_at=stale_started_at,
        )
        store.upsert(active)
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.get("/api/v1/strategy-tests/runs/active?user_id=demo_user")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["can_run"])
        self.assertTrue(data["is_stale"])
        self.assertEqual(data["disabled_reason_code"], None)
        self.assertIn("cancel", data["allowed_actions"])

    def test_active_run_endpoint_allows_run_when_queued_run_is_stale(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        stale_created_at = _now() - timedelta(hours=1)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="queued",
            test_type="historical_backtest",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={},
            created_at=stale_created_at,
        )
        store.upsert(active)
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.get("/api/v1/strategy-tests/runs/active?user_id=demo_user")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["can_run"])
        self.assertTrue(data["is_stale"])
        self.assertEqual(data["disabled_reason_code"], None)
        self.assertEqual(data["active_run"]["run_id"], str(active.run_id))
        self.assertIn("cancel", data["allowed_actions"])

    def test_active_run_endpoint_blocks_when_queued_run_is_fresh(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        heartbeat = datetime.now(timezone.utc)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="queued",
            test_type="historical_backtest",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={},
            created_at=heartbeat,
        )
        store.upsert(active)
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.get("/api/v1/strategy-tests/runs/active?user_id=demo_user")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["can_run"])
        self.assertFalse(data["is_stale"])
        self.assertEqual(data["disabled_reason_code"], "active_strategy_test_run")
        self.assertEqual(data["active_run"]["run_id"], str(active.run_id))
        self.assertIn("cancel", data["allowed_actions"])

    def test_active_run_endpoint_allows_run_when_stopping_run_is_stale(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        stale_heartbeat = _now() - timedelta(hours=1)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="stopping",
            test_type="forward_virtual",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={},
            created_at=stale_heartbeat,
            started_at=stale_heartbeat,
            last_heartbeat_at=stale_heartbeat,
        )
        store.upsert(active)
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.get("/api/v1/strategy-tests/runs/active?user_id=demo_user")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["can_run"])
        self.assertTrue(data["is_stale"])
        self.assertEqual(data["disabled_reason_code"], None)
        self.assertEqual(data["active_run"]["run_id"], str(active.run_id))

    def test_active_run_endpoint_blocks_when_stopping_run_is_fresh(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        heartbeat = datetime.now(timezone.utc)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="stopping",
            test_type="forward_virtual",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={},
            created_at=heartbeat,
            started_at=heartbeat,
            last_heartbeat_at=heartbeat,
        )
        store.upsert(active)
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.get("/api/v1/strategy-tests/runs/active?user_id=demo_user")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["can_run"])
        self.assertFalse(data["is_stale"])
        self.assertEqual(data["disabled_reason_code"], "active_strategy_test_run")
        self.assertEqual(data["active_run"]["run_id"], str(active.run_id))

    def test_cancel_run_endpoint_marks_active_run_cancelled(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        heartbeat = datetime.now(timezone.utc)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="running",
            test_type="forward_virtual",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={},
            created_at=heartbeat,
            started_at=heartbeat,
            last_heartbeat_at=heartbeat,
        )
        store.upsert(active)
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.post(f"/api/v1/strategy-tests/runs/{active.run_id}/cancel")
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(store.get_run(active.run_id).run.status, "cancelled")  # type: ignore[union-attr]

    def test_existing_backtests_route_remains_registered(self) -> None:
        route_paths = {route.path for route in api_router.routes}

        self.assertIn("/api/v1/backtests/run", route_paths)
        self.assertIn("/api/v1/backtests/results", route_paths)


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _request(tags: list[str] | None = None, test_type: str = "historical_backtest") -> StrategyTestRunRequest:
    now = _now()
    request_kwargs = {
        "test_type": test_type,
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
            test_type=request.test_type,
            requested_matrix=_requested_matrix(request),
        )
        detail = StrategyTestRunDetailResponse(run=run)
        self._runs[run.run_id] = detail
        return detail

    def upsert(self, run: StrategyTestRunResponse) -> None:
        self._runs[run.run_id] = StrategyTestRunDetailResponse(run=run)

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

    def mark_stopping(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "stopping")

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        return self._mark(run_id, "cancelled")

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
            update["last_heartbeat_at"] = _now()
        detail = StrategyTestRunDetailResponse(run=detail.run.model_copy(update=update))
        self._runs[run_id] = detail
        return detail

    def _mark(self, run_id: UUID, status: StrategyTestRunStatus) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated = detail.run.model_copy(update={"status": status})
        detail = StrategyTestRunDetailResponse(run=updated)
        self._runs[run_id] = detail
        return detail


class _EphemeralStrategyTestTradeStore:
    def __init__(self) -> None:
        self.trades: list[StrategyTestTrade] = []
        self.metrics: list[StrategyTestMetricRow] = []

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.trades.extend(trades)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.metrics.extend(rows)


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
            trades=[],
        )


class _MetricStrategyTestMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
    ) -> StrategyTestMatrixResult:
        _ = request, user_uuid
        group = {
            "strategy": "trend_pullback_continuation",
            "exchange": "bybit",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "regime": "trend",
            "score_bucket": "80-89",
            "direction": "long",
        }
        return StrategyTestMatrixResult(
            run_id=run_id,
            scenario_count=1,
            completed_scenarios=1,
            failed_scenarios=0,
            scenario_summaries=[],
            trades=[],
            metrics=[
                MetricResult("trades_count", "Trades Count", 80, 80, group),
                MetricResult("expectancy_after_costs_r", "Expectancy After Costs R", 0.18, 80, group),
                MetricResult("profit_factor", "Profit Factor", 1.7, 80, group),
                MetricResult("entry_touch_rate", "Entry Touch Rate", 0.45, 80, group),
                MetricResult("max_drawdown_r", "Max Drawdown R", 4.0, 80, group),
            ],
        )


class _FailingStrategyTestMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
    ) -> StrategyTestMatrixResult:
        _ = request, run_id, user_uuid
        raise AssertionError("forward_virtual must not use historical matrix runner")


class _RecordingEligibilityProfileUpdater:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update_from_metric_results(
        self,
        *,
        run_id: UUID,
        request: StrategyTestRunRequest,
        metrics: Sequence[MetricResult],
    ) -> None:
        self.calls.append({"run_id": run_id, "request": request, "metrics": list(metrics)})


def _requested_matrix(request: StrategyTestRunRequest) -> dict[str, Any]:
    return {
        "user_id": request.user_id,
        "test_type": request.test_type,
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


if __name__ == "__main__":
    unittest.main()
