# BACKEND

Codex guide for the current FastAPI backend. Use this file before changing backend behavior.

## Stack

- FastAPI app: `backend/app/main.py`
- Routes: `backend/app/api/v1/`
- Schemas: `backend/app/schemas/`
- Services: `backend/app/services/`
- Repositories: `backend/app/repositories/`
- Models: `backend/app/models/`
- Tests: `backend/tests/`
- Runtime dependencies: FastAPI, Uvicorn/Gunicorn, Pydantic, SQLAlchemy, Alembic, Redis, ClickHouse, NATS client package, httpx, OpenTelemetry, Prometheus.

## Storage And Messaging

- PostgreSQL is the durable application store. Use SQLAlchemy models in `backend/app/models/` and repositories in `backend/app/repositories/`.
- Alembic owns schema evolution. Migrations live in `backend/alembic/versions/`.
- Redis is used for hot signal state, notification streams, Pub/Sub fanout, and realtime delivery bridge. See `backend/app/services/signal_service.py`, `backend/app/services/notification_service.py`, and `backend/app/services/message_broker.py`.
- ClickHouse stores market ticks, candles, features, signal analytics, backtest/strategy analytics. See `infra/clickhouse/init/` and `backend/app/core/clickhouse_client.py`.
- `outbox_events` is the durable event log for app events. Writers currently include signal and virtual trade persistence paths. See `backend/app/models/outbox.py`, `backend/app/repositories/signal_repository.py`, and `backend/app/services/trade_repository.py`.
- NATS JetStream is provisioned by config and infra through `NATS_URL`, `infra/docker-compose.yml`, and Helm values. Do not claim a runtime NATS publisher unless you add and test one; new durable publishing should consume `outbox_events` and mark publish status.
- Realtime delivery uses Redis Pub/Sub plus FastAPI WebSocket/SSE endpoints. See `backend/app/api/v1/realtime.py`, `backend/app/services/realtime_gateway.py`, `backend/app/services/realtime_events.py`.

## API Areas

- Radar and scanner: `backend/app/api/v1/radar.py`
- Signals and signal actions: `backend/app/api/v1/signals.py`
- Pending entry: `backend/app/api/v1/pending_entry.py`
- Trades and execution: `backend/app/api/v1/trades.py`
- Risk: `backend/app/api/v1/risk.py`
- Exchanges and connections: `backend/app/api/v1/exchanges.py`
- Market universe and candles: `backend/app/api/v1/market_universe.py`, `backend/app/api/v1/candles.py`
- Watchlists and alerts: `backend/app/api/v1/watchlists.py`
- Strategies and testing: `backend/app/api/v1/strategies.py`, `backend/app/api/v1/strategy_tests.py`, `backend/app/api/v1/strategy_lab.py`, `backend/app/api/v1/backtests.py`
- Notifications, users, billing, AI, analytics: matching files in `backend/app/api/v1/`

## Strategy Testing Runtime Contract

- `strategy_test_runs` is represented by Alembic revisions, `backend/app/models/strategy_testing.py`, `backend/app/services/strategy_testing/schemas.py`, and `PostgresStrategyTestRunStore`.
- Run `test_type` is backend-owned and is either `historical_backtest` or `forward_virtual`.
- Run status values are `queued`, `running`, `completed`, `failed`, `cancelled`, and `stopping`.
- API responses include `summary`, `runtime_state`, and `last_heartbeat_at`; frontend code must display these values instead of reconstructing run state.
- `GET /api/v1/strategy-tests/runs/active` is the source of truth for run eligibility. It returns `active_run`, `can_run`, `disabled_reason_code`, `disabled_reason`, `is_stale`, `stale_threshold_seconds`, and `allowed_actions`.
- Active strategy-test runs are `queued`, `running`, and `stopping`. A run is stale only when the backend heartbeat/started/created timestamps exceed the backend stale threshold; the frontend must not duplicate this decision.
- `POST /api/v1/strategy-tests/runs/{run_id}/cancel` owns cancellation. Active runs transition through the store to `cancelled`; completed and failed runs reject cancellation with a conflict response.
- `mark_running`, `mark_completed`, `mark_failed`, `mark_stopping`, and `mark_cancelled` are the store boundary for status and heartbeat transitions.
- `historical_backtest` runs execute through `StrategyTestMatrixRunner` and `ProductionBacktestRunner`.
- `forward_virtual` runs start as backend-owned runtime runs: `StrategyTestingService.execute_run` marks them `running`, initializes `runtime_state.status="listening"`, and leaves processing to `ForwardStrategyTestRuntime`.
- `ForwardStrategyTestRuntime` consumes scanner ticks or `StrategySignal` objects, filters them by the requested strategy/pair/timeframe matrix, persists signals through `SignalService`, uses `SignalExecutionGateSnapshot` as the execution source of truth, and delegates virtual entries to `VirtualTradingService` or pending entries to `PendingEntryService`.
- `forward_virtual` must never place real orders. It records virtual trades and lightweight forward metrics into the existing strategy-test stores and updates `runtime_state` counters such as `processed_ticks`, `processed_signals`, `opened_trades`, `pending_entries_armed`, `trades_written`, and `metrics_written`.
- Closed-loop verification is split by ownership boundary: `backend/tests/test_trading_e2e_virtual_flow.py` covers signal pending-entry trigger to virtual trade lifecycle and PnL/journal state, `backend/tests/test_strategy_testing_e2e_flow.py` covers historical backtest trades/metrics to execution eligibility profiles, and `backend/tests/test_forward_strategy_test_runtime.py` covers forward virtual signal processing, heartbeat, runtime counters, and virtual trade writes.
- Tests may use fake providers, stores, scanners, and virtual trading adapters for external infrastructure, but they must still call the real backend services that own trade lifecycle, runtime state, metrics, and eligibility decisions.

## Backtest Execution Policy

- `ProductionBacktestRunner` keeps RiskGate in the entry path. Backtests must normalize strategy signals into production-compatible trade plans before RiskGate; they must not bypass risk, sizing, take-profit, stop, or lifecycle validation.
- The backtest normalizer reuses pipeline invalidation, exit-plan, risk/reward, trade-plan enrichment, and trade-plan completeness services. Legacy strategy fields are accepted only after they become a complete `TradePlan` with invalidation conditions and executable targets.
- `production_like` stays strict. `research_virtual` and `discovery` may record assumptions and warnings, but base price/stop/target invariants still belong to backend services.
- Backtest metrics and assumptions preserve diagnostics: `signals_seen`, `risk_rejections`, `execution_rejections`, `trade_plan_completion_warnings`, `risk_gate_blockers`, and `backtest_trade_plan_assumptions`.

## Signal Snapshot Serialization Boundary

- PostgreSQL, Redis, and realtime payloads store signal snapshots as JSON dictionaries. Backend service, execution-gate, lifecycle, and view code must normalize those dictionaries back into Pydantic snapshot models before reading fields such as `confirmation.checks` or `execution_gate.feed_kind`.
- `backend/app/services/signal_snapshot_normalization.py` is the shared boundary helper for old records, repository hydration, `model_copy` updates, and realtime/view rendering. Do not add scattered per-view `dict` accessors for the same snapshots.
- Signal lifecycle updates should emit typed snapshots such as `SignalConfirmationSnapshot`. Repositories serialize typed snapshots with `model_dump(mode="json")` before writing JSON fields.
- Realtime events must contain JSON-compatible dictionaries produced from backend schemas. Pydantic objects must not leak into WebSocket/SSE payloads.

## Core Services

- Signal service: `backend/app/services/signal_service.py`
  - Persists signals through `PostgresSignalRepository`.
  - Writes hot signal state to Redis.
  - Writes signal analytics events to ClickHouse.
  - Reconciles active pending entries when a signal trade plan changes.

- Pending entry: `backend/app/services/pending_entry.py`
  - Owns `pending_entry_intents`.
  - Stores accepted trade-plan snapshots, fingerprints, execution profile snapshots, idempotency keys, status transitions, cancellation, and reconfirmation.
  - Trigger processing is in `backend/app/services/pending_entry_trigger.py`.
  - Realtime events are published through `backend/app/services/pending_entry_events.py`.

- Virtual trading: `backend/app/services/virtual_trading/`, `backend/app/services/virtual_trading/execution_engine.py`, `backend/app/services/virtual_trading/simulation_model.py`, `backend/app/services/trade_repository.py`
  - Owns virtual account, positions, fills, status lifecycle, PnL, fees, slippage, partial fills, take-profit/stop handling, and trade journal persistence.
  - Legacy `backend/app/services/virtual_execution_engine.py` and `backend/app/services/virtual_simulation_model.py` are import shims only; new code must use the package path.

- Real execution: `backend/app/services/execution_service.py`
  - Builds execution plans only after backend risk checks and exchange readiness checks.
  - Default adapter is dry-run.
  - Live Bybit placement is guarded by backend flags, connection environment, account snapshots, instrument rules, idempotency, and protective-order validation.
  - Real pending execution from scanner tick triggers is not implemented; pending-entry trigger automation is virtual-only.

- Risk: `backend/app/services/risk_gate.py`, `backend/app/services/risk_management.py`, `backend/app/services/risk_state.py`, `backend/app/services/risk_preview.py`
  - Owns position sizing, stop/take-profit plans, R:R gates, leverage/margin checks, market data quality checks, daily/open/correlated risk, protection state, and audit records.

- Exchange connections: `backend/app/services/exchange_connection_service.py`, `backend/app/models/exchange_connection.py`
  - Owns encrypted/sanitized connection metadata, testnet/mainnet flags, order placement mode, soft delete, wallet balance, account snapshots, fee/rule sync.

- Market scanner: `backend/app/services/market_scanner.py`, `backend/app/workers/signal_worker.py`
  - Ingests Bybit market data, warms candle history, builds features, runs strategies, persists market data, updates virtual positions, triggers pending entries, processes signal outcomes and invalidation.

- Execution readiness: `backend/app/services/signal_execution_gate.py`, `backend/app/services/signal_deduplication.py`, `backend/app/services/execution_strategy_registry.py`, `backend/app/services/edge_calibration.py`
  - `SignalExecutionGateSnapshot` is the canonical contract for whether a signal can notify, enter now, arm pending entry, and appear in the execution feed.
  - Write-side deduplication compares open signals by exchange, normalized symbol, and direction before notification. Suppressed/replaced decisions are stored in signal metadata.
  - Edge and strategy eligibility are attached before gate evaluation. `ExecutionStrategyEligibilityService` reads `strategy_execution_eligibility_profiles` first and falls back to `SignalEdgeSnapshot` only when no persisted profile exists for the execution key. Strict walk-forward eligibility is controlled by backend settings.

- Outcomes and diagnostics: `backend/app/services/signal_outcome_service.py`, `backend/app/domain/pending_entry_reason.py`
  - Pending-entry terminal outcomes preserve reason codes for no-entry, virtual rejection, temporary failure, and expiry-before-touch cases.
  - Strategy performance metrics consume those reason codes so execution-rejected and no-entry rates stay separate.

## Execution Pipeline

The scanner execution path is:

1. `MarketScanner` builds market data and features.
2. `StrategyEngine` runs strategy modules and passes candidates through `StrategySignalPipeline`.
3. The pipeline attaches trigger, trade-plan, decision, no-trade, and risk/reward snapshots.
4. `edge_calibration_service` and `ExecutionStrategyEligibilityService` attach edge and eligibility metadata.
5. `SignalExecutionGateService` classifies the signal as `execution_signal`, `watchlist`, `market_idea`, or `blocked`.
6. `SignalDeduplicationService` decides keep, suppress, or replace for same market direction.
7. `SignalService` persists the signal, Redis hot state, analytics events, and outbox events.
8. `NotificationService` emits `signal.execution_ready` only for backend-approved execution signals.

Important rules:

- Closed-candle confirmation is required when `settings.execution_closed_candle_only` is enabled. Open/forming candles may appear only as preview/watchlist/blocked state with a `forming_candle` reason.
- Execution candidates must have a passed trigger snapshot. Missing or failed triggers produce `trigger_not_confirmed`.
- The execution gate owns all action booleans: `can_notify`, `can_enter_now`, `can_arm_pending`, and `can_show_in_execution_feed`.
- Edge gates use backend thresholds for expectancy after costs, profit factor, entry-touch rate, and no-entry rate.
- Strategy eligibility metadata comes from persisted strategy-test eligibility profiles when available. It is advisory unless `settings.execution_require_walk_forward_edge` is enabled, then it becomes a hard blocker.
- Pending-entry trigger automation is virtual-only. Real pending execution must remain disabled unless a separately tested real execution path is added.

## Background Workers

- Scanner runner: `backend/app/workers/signal_worker.py`
- Forward strategy-test worker: `backend/app/workers/forward_strategy_test_worker.py`
- Derivative snapshots: `backend/app/workers/derivative_snapshot_worker.py`
- Exchange instrument rules: `backend/app/workers/exchange_instrument_worker.py`
- Orderbook snapshots: `backend/app/workers/orderbook_snapshot_worker.py`
- Real position sync: `backend/app/workers/real_position_sync_worker.py`
- Strategy performance: `backend/app/workers/strategy_performance_worker.py`
- Signal outcomes: `backend/app/workers/signal_outcome_worker.py`

Workers are started from `backend/app/main.py` lifespan according to settings. Local MVP defaults keep scanner autostart and optional external sync workers disabled:

- `CRYPTO_RADAR_SCANNER_ENABLED=false`
- `EXCHANGE_INSTRUMENT_SYNC_ENABLED=false`
- `DERIVATIVE_SNAPSHOT_SYNC_ENABLED=false`
- `ORDERBOOK_SNAPSHOT_SYNC_ENABLED=false`
- `REAL_POSITION_SYNC_ENABLED=false`
- `MAX_SCANNER_PAIRS=20`
- `SCANNER_WARMUP_CONCURRENCY=2`

Start the scanner explicitly with `POST /api/v1/radar/scanner/start` after `/health` and `/api/v1/radar/status` are healthy.

## Data Ownership Rules

- Backend owns every trading calculation and lifecycle transition.
- Frontend may request actions such as confirm virtual, confirm real, arm/cancel/reconfirm pending entry, reject signal, update settings, or sync exchange data.
- Do not trust frontend-provided sizing, risk, PnL, execution readiness, or account state without backend validation.
- Never bypass `RiskGateService` for virtual or real entry paths.
- Never send live orders unless all live safety flags, exchange connection checks, account snapshot checks, and protective-order checks pass.

## Known fix 6.0 regressions

Baseline captured on 2026-06-11 before runtime changes. The documented project command is `PYTHONPATH=backend:. python -m pytest backend/tests -q`; in this workspace plain `python`, `py -3.12`, and the local `.venv` launchers are unavailable or point to a missing Python 3.12 install, so the same pytest command was executed with the bundled Codex Python and `PYTHONPATH=backend;.` on Windows.

Baseline result:

- Full backend suite: `14 failed, 938 passed, 49 warnings, 4 subtests passed`.
- `backend/tests/test_backtest_runner.py`: 4 failed, 6 passed.
- `backend/tests/test_strategy_test_signal_selection.py`: 6 failed, 3 passed.
- `backend/tests/test_signal_lifecycle_worker.py`: 2 failed, 5 passed.
- `backend/tests/test_virtual_trading_api_realtime_smoke.py`: 1 failed.
- `backend/tests/test_trading_e2e_virtual_flow.py`: 3 passed.

Failure groups and likely root cause:

- Backtest runner and strategy-test signal selection produce zero trades where tests expect opened positions. The common symptom is empty `trades_count`, empty `metrics["by_entry_model"]`, and empty selected trades. This matches the fix 6.0 RiskGate/trade-plan completeness regression: synthetic strategy signals are reaching execution without a complete normalized trade plan/invalidation contract.
- `backend/tests/test_pipeline_contract.py::PipelineContractTest::test_architecture_project_contains_contract_topics` fails because `docs/architectureproject.md` is missing.
- Signal lifecycle realtime publishing fails in `backend/app/services/signal_views.py` because old or test-created signals can carry `confirmation` as a `dict`, while `_rr_metadata_sources` expects a typed object with `.checks`.
- Virtual trading API realtime smoke fails because the test helper `_radar_signal()` does not accept `execution_gate`, while the strategy signal upsert path forwards `signal.execution_gate`.
- Baseline found a case-sensitive docs mismatch: README and `docs/PROJECT_STRUCTURE.md` referenced `docs/FRONTEND.md`, while the frontend guide filename used lowercase casing.

No runtime logic was changed for this baseline.

## Change Rules

- Route handlers should stay thin: validate request, call service, return schema.
- Prefer repository boundaries for PostgreSQL writes.
- Update Pydantic schemas with API changes and regenerate frontend OpenAPI types.
- Add Alembic migrations for model/table/index/constraint changes.
- Keep tests focused on behavior and contracts. Existing tests under `backend/tests/` are the best map for expected behavior.
