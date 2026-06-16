from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.router import api_router
from app.api.v1.strategy_tests import get_strategy_testing_service
from app.main import app
from app.services.strategy_testing.matrix_runner import StrategyTestMatrixResult
from app.services.strategy_testing.metrics import MetricResult
from app.services.strategy_testing.schemas import (
    StrategyTestCalibrationResponse,
    StrategyTestMetricRow,
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestRuntimeState,
    StrategyTestSignalEvent,
    StrategyTestTrade,
    StrategyTestReport,
)
from app.services.strategy_testing.service import StrategyTestingService
from app.services.strategy_testing.eligibility_profiles import build_profile_upserts_from_metric_results


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

    def test_run_response_schema_exposes_worker_and_lease_fields(self) -> None:
        heartbeat = _now()

        response = StrategyTestRunResponse(
            run_id=uuid4(),
            status="running",
            test_type="historical_backtest",
            requested_matrix={},
            worker_id="strategy-worker-a",
            worker_attempt=2,
            claimed_at=heartbeat,
            lease_expires_at=heartbeat + timedelta(seconds=30),
        )
        payload = response.model_dump(mode="json")
        schema_properties = StrategyTestRunResponse.model_json_schema()["properties"]

        self.assertEqual(payload["worker_id"], "strategy-worker-a")
        self.assertEqual(payload["worker_attempt"], 2)
        self.assertEqual(payload["claimed_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(payload["lease_expires_at"], "2026-01-01T00:00:30Z")
        self.assertIn("worker_id", schema_properties)
        self.assertIn("worker_attempt", schema_properties)
        self.assertIn("claimed_at", schema_properties)
        self.assertIn("lease_expires_at", schema_properties)

    def test_runtime_state_schema_exposes_progress_and_forward_status_fields(self) -> None:
        state = StrategyTestRuntimeState(
            status="waiting_for_market_data",
            phase="running_scenario",
            matrix_bars_processed=120,
            matrix_bars_total=240,
            bars_pct=50,
            current_scenario_key="trend::bybit::BTCUSDT::1h",
            current_scenario_bars_processed=12,
            current_scenario_bars_total=24,
            last_heartbeat_reason="waiting_for_market_data",
            processed_ticks=0,
            processed_signals=0,
            opened_trades=0,
            trades_written=0,
            metrics_written=0,
        )
        payload = state.model_dump(mode="json")
        schema_properties = StrategyTestRuntimeState.model_json_schema()["properties"]

        self.assertEqual(payload["status"], "waiting_for_market_data")
        self.assertEqual(payload["matrix_bars_processed"], 120)
        self.assertEqual(payload["last_heartbeat_reason"], "waiting_for_market_data")
        for field_name in (
            "status",
            "last_heartbeat_reason",
            "processed_ticks",
            "processed_signals",
            "opened_trades",
            "trades_written",
            "metrics_written",
            "pending_entries",
        ):
            self.assertIn(field_name, schema_properties)

    def test_report_schema_exposes_completeness_calibration_gate_fields(self) -> None:
        report = StrategyTestReport(
            run_id=uuid4(),
            status="running",
            mode="research_virtual",
            is_partial=True,
            data_completeness="partial",
            generated_at=_now(),
            can_publish_calibration=False,
            calibration_disabled_reason_code="report_not_complete",
            calibration_disabled_reason="Strategy test report is still partial.",
        )
        payload = report.model_dump(mode="json")
        schema_properties = StrategyTestReport.model_json_schema()["properties"]

        self.assertFalse(payload["can_publish_calibration"])
        self.assertEqual(payload["calibration_disabled_reason_code"], "report_not_complete")
        self.assertEqual(payload["calibration_disabled_reason"], "Strategy test report is still partial.")
        self.assertIn("can_publish_calibration", schema_properties)
        self.assertIn("calibration_disabled_reason_code", schema_properties)
        self.assertIn("calibration_disabled_reason", schema_properties)

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
        self.assertEqual(data["runtime_state"]["phase"], "queued")
        self.assertEqual(data["runtime_state"]["scenario_total"], 12)
        self.assertEqual(data["runtime_state"]["scenario_completed"], 0)
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
        self.assertEqual(list_response.json()[0]["status"], "queued")
        self.assertEqual(list_response.json()[0]["test_type"], "historical_backtest")
        self.assertEqual(list_response.json()[0]["runtime_state"]["phase"], "queued")

    def test_post_runs_normalizes_payload_user_id_from_request_identity(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            response = client.post(
                "/api/v1/strategy-tests/runs",
                json={**_payload(), "user_id": "other_user"},
                headers={"x-auth-user-id": "usr_strategy_owner"},
            )
            list_response = client.get(
                "/api/v1/strategy-tests/runs",
                headers={"x-auth-user-id": "usr_strategy_owner"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["requested_matrix"]["user_id"], "usr_strategy_owner")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()[0]["requested_matrix"]["user_id"], "usr_strategy_owner")

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
        self.assertEqual(list_response.json()[0]["status"], "queued")
        self.assertEqual(list_response.json()[0]["test_type"], "forward_virtual")
        self.assertEqual(list_response.json()[0]["runtime_state"], {})

    def test_post_runs_only_enqueues_and_does_not_execute_in_background(self) -> None:
        service = _RecordingEnqueueOnlyService()
        app.dependency_overrides[get_strategy_testing_service] = lambda: service
        client = TestClient(app)

        try:
            response = client.post("/api/v1/strategy-tests/runs", json=_payload())
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(service.enqueue_calls, 1)
        self.assertEqual(service.execute_calls, 0)

    def test_completed_historical_run_does_not_publish_execution_calibration_by_default(self) -> None:
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
        self.assertEqual(updater.calls, [])

    def test_completed_historical_run_auto_publishes_calibration_only_with_flag(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        updater = _RecordingEligibilityProfileUpdater()
        service = StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_MetricStrategyTestMatrixRunner(),  # type: ignore[arg-type]
            eligibility_profile_updater=updater,
        )
        request = _request(params={"auto_publish_calibration": True})

        created = store.create_run(request)
        completed = service.execute_run(created.run.run_id, request)

        self.assertEqual(completed.status, "completed")
        self.assertEqual(len(updater.calls), 1)
        call = updater.calls[0]
        self.assertEqual(call["run_id"], created.run.run_id)
        self.assertEqual(call["request"].test_type, "historical_backtest")
        self.assertIn("expectancy_after_costs_r", {metric.code for metric in call["metrics"]})

    def test_execute_run_restores_request_from_persisted_matrix_when_request_omitted(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        runner = _RecordingMatrixRunner()
        service = StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=runner,  # type: ignore[arg-type]
            eligibility_profile_updater=_RecordingEligibilityProfileUpdater(),
        )
        request = _request(params={"auto_publish_calibration": False})
        created = store.create_run(request)

        completed = service.execute_run(created.run.run_id)

        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(runner.request)
        assert runner.request is not None
        self.assertEqual(runner.request.user_id, request.user_id)
        self.assertEqual(runner.request.test_type, "historical_backtest")
        self.assertEqual(runner.request.strategies, request.strategies)
        self.assertEqual(runner.request.pairs, request.pairs)
        self.assertEqual(runner.request.timeframes, request.timeframes)
        self.assertEqual(runner.request.start_at, request.start_at)
        self.assertEqual(runner.request.end_at, request.end_at)
        self.assertEqual(runner.request.mode, request.mode)
        self.assertEqual(runner.request.initial_capital, request.initial_capital)
        self.assertEqual(runner.request.fee_rate, request.fee_rate)
        self.assertEqual(runner.request.slippage_bps, request.slippage_bps)
        self.assertEqual(runner.request.same_candle_policy, request.same_candle_policy)
        self.assertEqual(runner.request.params, request.params)
        self.assertEqual(runner.request.metric_set, request.metric_set)
        self.assertEqual(runner.request.tags, request.tags)

    def test_calibration_endpoint_publishes_completed_run_profiles(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        updater = _RecordingEligibilityProfileUpdater()
        service = StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_MetricStrategyTestMatrixRunner(),  # type: ignore[arg-type]
            eligibility_profile_updater=updater,
        )
        app.dependency_overrides[get_strategy_testing_service] = lambda: service
        client = TestClient(app)
        created = store.create_run(_request())
        completed = service.execute_run(created.run.run_id, _request())

        try:
            response = client.post(
                f"/api/v1/strategy-tests/runs/{completed.run_id}/calibration",
                headers={"x-auth-user-id": "demo_user"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        parsed = StrategyTestCalibrationResponse(**data)
        self.assertEqual(parsed.run_id, completed.run_id)
        self.assertEqual(parsed.decision, "positive")
        self.assertEqual(parsed.profiles_count, 1)
        self.assertEqual(len(updater.calls), 1)
        profile = parsed.profiles[0]
        self.assertEqual(profile.strategy_code, "trend_pullback_continuation")
        self.assertEqual(profile.exchange, "bybit")
        self.assertEqual(profile.symbol_scope, "BTCUSDT")
        self.assertEqual(profile.sample_size, 80)
        self.assertEqual(profile.decision, "positive")
        self.assertTrue(profile.eligible)
        self.assertEqual(profile.source_run_id, completed.run_id)
        self.assertIn(str(completed.run_id), profile.run_ids)

    def test_calibration_endpoint_rejects_unfinished_run(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        service = StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_MetricStrategyTestMatrixRunner(),  # type: ignore[arg-type]
            eligibility_profile_updater=_RecordingEligibilityProfileUpdater(),
        )
        app.dependency_overrides[get_strategy_testing_service] = lambda: service
        client = TestClient(app)
        created = store.create_run(_request())

        try:
            response = client.post(
                f"/api/v1/strategy-tests/runs/{created.run.run_id}/calibration",
                headers={"x-auth-user-id": "demo_user"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 409)
        self.assertIn("completed", response.json()["detail"])

    def test_calibration_endpoint_marks_insufficient_sample_profiles(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        updater = _RecordingEligibilityProfileUpdater()
        service = StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_InsufficientSampleStrategyTestMatrixRunner(),  # type: ignore[arg-type]
            eligibility_profile_updater=updater,
        )
        app.dependency_overrides[get_strategy_testing_service] = lambda: service
        client = TestClient(app)
        created = store.create_run(_request())
        completed = service.execute_run(created.run.run_id, _request())

        try:
            response = client.post(
                f"/api/v1/strategy-tests/runs/{completed.run_id}/calibration",
                headers={"x-auth-user-id": "demo_user"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["decision"], "insufficient_sample")
        self.assertEqual(data["profiles"][0]["decision"], "insufficient_sample")
        self.assertFalse(data["profiles"][0]["eligible"])
        self.assertEqual(data["profiles"][0]["reason_code"], "strategy_eligibility_insufficient_sample")

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

    def test_active_run_endpoint_uses_request_identity_without_user_query(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        heartbeat = datetime.now(timezone.utc)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="running",
            test_type="forward_virtual",
            requested_matrix={"user_id": "usr_strategy_owner", "scenario_count": 1},
            summary={},
            runtime_state={"status": "listening"},
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
            response = client.get(
                "/api/v1/strategy-tests/runs/active",
                headers={"x-auth-user-id": "usr_strategy_owner"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_run"]["run_id"], str(active.run_id))
        self.assertFalse(response.json()["can_run"])

    def test_active_run_query_user_id_mismatch_is_rejected_in_production(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            with patch("app.api.v1.strategy_tests.settings.app_env", "production"):
                response = client.get(
                    "/api/v1/strategy-tests/runs/active?user_id=other_user",
                    headers={"x-auth-user-id": "usr_strategy_owner"},
                )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 403)

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

    def test_active_run_endpoint_allows_orphaned_stopping_run_after_cancel_refresh(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        cancel_requested_at = datetime.now(timezone.utc)
        stale_started_at = cancel_requested_at - timedelta(hours=1)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="stopping",
            test_type="historical_backtest",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={
                "last_error": None,
                "last_progress_at": cancel_requested_at.isoformat(),
            },
            created_at=stale_started_at,
            started_at=stale_started_at,
            last_heartbeat_at=cancel_requested_at,
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

    def test_estimate_endpoint_returns_deduped_bars_for_30_day_5m_15m_run(self) -> None:
        five_minute_candles = _expected_candles(days=30, timeframe_minutes=5)
        fifteen_minute_candles = _expected_candles(days=30, timeframe_minutes=15)
        duplicate_raw_rows = fifteen_minute_candles * 30 + 197
        service = StrategyTestingService(
            run_store=_EphemeralStrategyTestRunStore(),
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
            historical_candle_provider=_CountingEstimateCandleProvider(
                counts={
                    ("bybit", "BTCUSDT", "5m"): five_minute_candles,
                    ("bybit", "BTCUSDT", "15m"): fifteen_minute_candles,
                },
                raw_counts={
                    ("bybit", "BTCUSDT", "5m"): five_minute_candles,
                    ("bybit", "BTCUSDT", "15m"): duplicate_raw_rows,
                },
            ),
        )
        app.dependency_overrides[get_strategy_testing_service] = lambda: service
        client = TestClient(app)
        payload = {
            **_payload(),
            "strategies": ["trend_pullback_continuation"],
            "pairs": [{"exchange": "bybit", "symbol": "BTCUSDT"}],
            "timeframes": ["5m", "15m"],
        }

        try:
            response = client.post("/api/v1/strategy-tests/runs/estimate", json=payload)
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["scenario_count"], 2)
        self.assertGreater(data["total_bars"], 10_000)
        self.assertLess(data["total_bars"], 20_000)
        self.assertNotEqual(data["total_bars"], duplicate_raw_rows)
        self.assertEqual(
            [(item["timeframe"], item["bars_total"]) for item in data["scenarios"]],
            [
                ("5m", five_minute_candles - 200),
                ("15m", fifteen_minute_candles - 200),
            ],
        )
        self.assertEqual(data["warnings"][0]["code"], "market_data_duplicates")
        self.assertEqual(data["warnings"][0]["timeframe"], "15m")

    def test_estimate_service_warns_when_market_data_is_missing(self) -> None:
        service = StrategyTestingService(
            run_store=_EphemeralStrategyTestRunStore(),
            trade_store=_EphemeralStrategyTestTradeStore(),
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
            historical_candle_provider=_CountingEstimateCandleProvider(
                counts={("bybit", "BTCUSDT", "15m"): 0},
                raw_counts={("bybit", "BTCUSDT", "15m"): 0},
            ),
        )

        estimate = service.estimate_run(
            StrategyTestRunRequest(
                strategies=["trend_pullback_continuation"],
                pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
                timeframes=["15m"],
                start_at=_now() - timedelta(days=30),
                end_at=_now(),
            )
        )

        self.assertEqual(estimate.total_bars, 0)
        self.assertEqual(estimate.warnings[0].code, "market_data_missing")

    def test_cancel_run_endpoint_marks_running_run_stopping(self) -> None:
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
            response = client.post(
                f"/api/v1/strategy-tests/runs/{active.run_id}/cancel",
                headers={"x-auth-user-id": "demo_user"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "stopping")
        self.assertEqual(store.get_run(active.run_id).run.status, "stopping")  # type: ignore[union-attr]

    def test_cancel_run_endpoint_rejects_run_owned_by_another_user(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        heartbeat = datetime.now(timezone.utc)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="running",
            test_type="forward_virtual",
            requested_matrix={"user_id": "usr_strategy_owner", "scenario_count": 1},
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
            response = client.post(
                f"/api/v1/strategy-tests/runs/{active.run_id}/cancel",
                headers={"x-auth-user-id": "usr_intruder"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(store.get_run(active.run_id).run.status, "running")  # type: ignore[union-attr]

    def test_cancel_forward_run_becomes_cancelled_on_runtime_heartbeat(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        trade_store = _EphemeralStrategyTestTradeStore()
        heartbeat = datetime.now(timezone.utc)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="running",
            test_type="forward_virtual",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={"status": "listening"},
            created_at=heartbeat,
            started_at=heartbeat,
            last_heartbeat_at=heartbeat,
        )
        store.upsert(active)
        service = StrategyTestingService(
            run_store=store,
            trade_store=trade_store,
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        app.dependency_overrides[get_strategy_testing_service] = lambda: service
        client = TestClient(app)

        try:
            response = client.post(
                f"/api/v1/strategy-tests/runs/{active.run_id}/cancel",
                headers={"x-auth-user-id": "demo_user"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "stopping")

        heartbeat_result = service.heartbeat_forward_runs()

        final = store.get_run(active.run_id)
        self.assertEqual(heartbeat_result.cancelled_runs, 1)
        self.assertIsNotNone(final)
        self.assertEqual(final.run.status, "cancelled")  # type: ignore[union-attr]
        self.assertEqual(final.run.runtime_state["status"], "cancelled")  # type: ignore[union-attr]
        self.assertEqual(final.run.runtime_state["cancelled_reason"], "forward_runtime_stopping")  # type: ignore[union-attr]

    def test_cancel_run_endpoint_marks_stale_running_run_cancelled(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        stale_heartbeat = _now() - timedelta(hours=1)
        active = StrategyTestRunResponse(
            run_id=uuid4(),
            status="running",
            test_type="historical_backtest",
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
            response = client.post(
                f"/api/v1/strategy-tests/runs/{active.run_id}/cancel",
                headers={"x-auth-user-id": "demo_user"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(store.get_run(active.run_id).run.status, "cancelled")  # type: ignore[union-attr]

    def test_signal_events_and_funnel_endpoints_return_run_signal_funnel(self) -> None:
        store = _EphemeralStrategyTestRunStore()
        trade_store = _EphemeralStrategyTestTradeStore()
        run = StrategyTestRunResponse(
            run_id=uuid4(),
            status="completed",
            test_type="historical_backtest",
            requested_matrix={"user_id": "demo_user", "scenario_count": 1},
            summary={},
            runtime_state={},
            created_at=_now(),
        )
        store.upsert(run)
        trade_store.write_signal_events(
            [
                _signal_event(run.run_id, "signal-1", no_entry=True, outcome="no_entry", funnel_stage="no_entry"),
                _signal_event(run.run_id, "signal-2", entry_touched=True, filled=True, closed=True, outcome="win"),
            ]
        )
        app.dependency_overrides[get_strategy_testing_service] = lambda: StrategyTestingService(
            run_store=store,
            trade_store=trade_store,
            matrix_runner=_NoopStrategyTestMatrixRunner(),  # type: ignore[arg-type]
        )
        client = TestClient(app)

        try:
            signals_response = client.get(
                f"/api/v1/strategy-tests/runs/{run.run_id}/signals",
                headers={"x-auth-user-id": "demo_user"},
            )
            funnel_response = client.get(
                f"/api/v1/strategy-tests/runs/{run.run_id}/funnel",
                headers={"x-auth-user-id": "demo_user"},
            )
        finally:
            app.dependency_overrides.pop(get_strategy_testing_service, None)

        self.assertEqual(signals_response.status_code, 200)
        self.assertEqual(funnel_response.status_code, 200)
        self.assertEqual(len(signals_response.json()), 2)
        self.assertEqual(signals_response.json()[0]["synthetic_signal_id"], "signal-1")
        funnel = funnel_response.json()
        self.assertEqual(funnel["signals_count"], 2)
        self.assertEqual(funnel["no_entry"], 1)
        self.assertEqual(funnel["entry_touched"], 1)
        self.assertEqual(funnel["entry_touch_rate"], 0.5)

    def test_existing_backtests_route_remains_registered(self) -> None:
        route_paths = {route.path for route in api_router.routes}

        self.assertIn("/api/v1/backtests/run", route_paths)
        self.assertIn("/api/v1/backtests/results", route_paths)


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _expected_candles(*, days: int, timeframe_minutes: int) -> int:
    return days * 24 * 60 // timeframe_minutes


def _request(
    tags: list[str] | None = None,
    test_type: str = "historical_backtest",
    params: dict[str, Any] | None = None,
) -> StrategyTestRunRequest:
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
    if params is not None:
        request_kwargs["params"] = params
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

    def mark_failed(
        self,
        run_id: UUID,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        _ = error
        detail = self._mark(run_id, "failed")
        if summary is None:
            return detail
        updated = detail.run.model_copy(update={"summary": summary})
        detail = StrategyTestRunDetailResponse(run=updated)
        self._runs[run_id] = detail
        return detail

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
        self.signal_events: list[StrategyTestSignalEvent] = []
        self.metrics: list[StrategyTestMetricRow] = []

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.trades.extend(trades)

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        self.signal_events.extend(signal_events)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.metrics.extend(rows)

    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        return [trade for trade in self.trades if trade.run_id == run_id][offset : offset + limit]

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        return [event for event in self.signal_events if event.run_id == run_id][offset : offset + limit]


class _CountingEstimateCandleProvider:
    def __init__(
        self,
        *,
        counts: dict[tuple[str, str, str], int],
        raw_counts: dict[tuple[str, str, str], int] | None = None,
    ) -> None:
        self._counts = counts
        self._raw_counts = raw_counts or counts

    async def load_candles(self, **kwargs: Any) -> list[Any]:
        _ = kwargs
        return []

    async def count_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        _ = start_at, end_at
        return self._counts.get((exchange, symbol, timeframe), 0)

    async def count_raw_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        _ = start_at, end_at
        return self._raw_counts.get((exchange, symbol, timeframe), 0)


class _NoopStrategyTestMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = user_uuid, kwargs
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
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = request, user_uuid, kwargs
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
                MetricResult("no_entry_rate", "No Entry Rate", 0.20, 80, group),
                MetricResult("max_drawdown_r", "Max Drawdown R", 4.0, 80, group),
            ],
        )


class _RecordingMatrixRunner(_NoopStrategyTestMatrixRunner):
    def __init__(self) -> None:
        self.request: StrategyTestRunRequest | None = None

    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        self.request = request
        return super().run_matrix(request=request, run_id=run_id, user_uuid=user_uuid, **kwargs)


class _InsufficientSampleStrategyTestMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = request, user_uuid, kwargs
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
                MetricResult("trades_count", "Trades Count", 12, 12, group),
                MetricResult("expectancy_after_costs_r", "Expectancy After Costs R", 0.18, 12, group),
                MetricResult("profit_factor", "Profit Factor", 1.7, 12, group),
                MetricResult("entry_touch_rate", "Entry Touch Rate", 0.45, 12, group),
                MetricResult("no_entry_rate", "No Entry Rate", 0.20, 12, group),
            ],
        )


class _FailingStrategyTestMatrixRunner:
    def run_matrix(
        self,
        *,
        request: StrategyTestRunRequest,
        run_id: UUID,
        user_uuid: UUID,
        **kwargs: Any,
    ) -> StrategyTestMatrixResult:
        _ = request, run_id, user_uuid, kwargs
        raise AssertionError("forward_virtual must not use historical matrix runner")


class _RecordingEnqueueOnlyService:
    def __init__(self) -> None:
        self.enqueue_calls = 0
        self.execute_calls = 0

    def enqueue_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        self.enqueue_calls += 1
        return StrategyTestRunResponse(
            run_id=uuid4(),
            status="queued",
            test_type=request.test_type,
            requested_matrix=_requested_matrix(request),
            created_at=_now(),
        )

    def execute_run(self, run_id: UUID, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        _ = run_id, request
        self.execute_calls += 1
        raise AssertionError("POST /strategy-tests/runs must not execute strategy tests in FastAPI BackgroundTasks")


class _RecordingEligibilityProfileUpdater:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update_from_metric_results(
        self,
        *,
        run_id: UUID,
        request: StrategyTestRunRequest,
        metrics: Sequence[MetricResult],
    ) -> list[Any]:
        self.calls.append({"run_id": run_id, "request": request, "metrics": list(metrics)})
        return build_profile_upserts_from_metric_results(run_id=run_id, request=request, metrics=metrics)


def _signal_event(
    run_id: UUID,
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
        run_id=run_id,
        user_id=UUID("22222222-2222-4222-8222-222222222222"),
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
        event_time=_now(),
        candle_time=_now(),
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
        created_at=_now(),
    )


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
