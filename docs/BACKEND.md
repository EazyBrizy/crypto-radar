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
- Strategy Testing API routes resolve the current user through `current_user_identity_service.resolve_from_request(request)`. Request body `user_id` is optional backward compatibility and is normalized to the resolved identity before service calls; query `user_id` is reserved for dev/admin compatibility and must not allow cross-user run access in production.
- API responses include `summary`, typed `runtime_state`, and `last_heartbeat_at`; frontend code must display these values instead of reconstructing run state.
- Historical `runtime_state` progress uses this production contract: `scenarios_total`, `scenarios_completed`, `scenarios_failed`, `current_scenario_index`, `current_scenario_key`, `current_scenario_bars_processed`, `current_scenario_bars_total`, `matrix_bars_processed`, `matrix_bars_total`, `bars_pct`, `elapsed_seconds`, `bars_per_second`, `eta_seconds`, `phase`, `last_progress_at`, `last_heartbeat_at`, `stale_threshold_seconds`, and `counters`.
- `runtime_state.counters` contains backend-owned `signals`, `execution_candidates`, `pending_armed`, `pending_entries`, `no_entry`, `filled`, `closed`, `risk_rejections`, and `execution_rejections`. Legacy top-level counter aliases may remain for compatibility, but new UI should prefer `counters`.
- `GET /api/v1/strategy-tests/runs/active` is the source of truth for run eligibility. It returns `active_run`, `can_run`, `disabled_reason_code`, `disabled_reason`, `is_stale`, `stale_threshold_seconds`, and `allowed_actions`.
- Active strategy-test runs are `queued`, `running`, and `stopping`. A run is stale only when the backend heartbeat/started/created timestamps exceed the backend stale threshold; the frontend must not duplicate this decision.
- Historical worker heartbeat is separate from progress events. The durable worker renews `last_heartbeat_at`/lease using `strategy_test_worker_heartbeat_seconds` and `strategy_test_lease_seconds`; progress callbacks update `runtime_state.last_progress_at` and visible `phase`.
- `POST /api/v1/strategy-tests/runs/{run_id}/cancel` owns cancellation. Active runs transition through the store to `cancelled`; completed and failed runs reject cancellation with a conflict response.
- `mark_running`, `mark_completed`, `mark_failed`, `mark_stopping`, and `mark_cancelled` are the store boundary for status and heartbeat transitions.
- `historical_backtest` runs execute through `StrategyTestMatrixRunner` and `ProductionBacktestRunner`.
- `POST /api/v1/strategy-tests/runs/estimate` is the backend-owned launch estimate for historical runs. It counts available historical candles from `HistoricalCandleProvider.count_candles(...)`, so totals are deduped by `(exchange, symbol, ts)` and reduced by the backend warmup policy. The response includes per-scenario bars, total bars, size level, and validation warnings for missing market data, failed counting, or raw rows that exceed deduped candles above the backend threshold.
- Historical run launch validation uses backend settings `strategy_test_max_bars_per_run` and `strategy_test_max_scenarios_per_run`. When deduped counts are available and the request exceeds a limit, the backend rejects the run before creating it. When counts are unavailable, the backend must not invent totals; runtime progress carries `matrix_bars_estimate_status="estimating_failed"` and warnings until a reliable total is available.
- Historical candle reads from ClickHouse must dedupe at query time with `argMax(..., tuple(created_at, ...))`, `GROUP BY exchange, symbol, ts`, and closed-candle timeframe filters. Do not rely on MergeTree ordering or background ReplacingMergeTree merges for backtest correctness.
- ClickHouse dedupe/summary queries must avoid same-level aggregate aliases that shadow raw column names. Use inner aliases such as `selected_*` or `dedup_created_at`, then project API field names from an outer `SELECT`; ClickHouse 25.x expands aliases inside the same `SELECT` and can otherwise produce nested aggregate errors.
- Historical scenario results are durable at scenario boundaries: `scenario_completed` writes trades, signal events, and scenario metric/summary rows to the strategy-test analytics store. The bar loop must not write per-bar/per-event analytics rows.
- Historical analytics writes must be idempotent by `run_id`, scenario key (`strategy/exchange/symbol/timeframe`), and trade/event/metric key. Retries, cancellation, and repeated completion callbacks should preserve already written rows without duplicating report data.
- Running, stopping, cancelled, and failed historical reports may be partial. Report generation reads completed scenario rows already in analytics storage and combines them with `runtime_state.partial_summary`; cancellation keeps completed scenario rows visible.
- `forward_virtual` runs start as backend-owned runtime runs: `StrategyTestingService.execute_run` marks them `running`, initializes `runtime_state.status="listening"`, and leaves processing to `ForwardStrategyTestRuntime`.
- `StrategyTestingService` is constructed per API request and by the durable `strategy-test-worker` process, but run state is not request-local. API routes only enqueue strategy-test runs; `backend/app/workers/strategy_test_worker.py` claims queued runs with a database lease and executes them through the same service/store boundaries.
- `ForwardStrategyTestRuntime` consumes scanner ticks or `StrategySignal` objects, filters them by the requested strategy/pair/timeframe matrix, persists signals through `SignalService`, uses `SignalExecutionGateSnapshot` as the execution source of truth, and delegates virtual entries to `VirtualTradingService` or pending entries to `PendingEntryService`.
- `forward_virtual` must never place real orders. It records virtual trades and lightweight forward metrics into the existing strategy-test stores and updates `runtime_state` counters such as `processed_ticks`, `processed_signals`, `opened_trades`, `pending_entries_armed`, `trades_written`, and `metrics_written`.
- `runtime_state.status="listening"` means the run is active and the runtime has either just started or is alive after receiving market data. `runtime_state.status="waiting_for_market_data"` means the worker heartbeat sees an active forward run with zero matching ticks; `runtime_state.last_heartbeat_reason` carries the display reason such as `waiting_for_market_data` or `no_matching_market_data`.
- Docker smoke coverage for this lifecycle is `scripts/smoke_strategy_tests.ps1` and the `scripts/smoke_strategy_tests.sh` wrapper. The smoke uses Docker Compose only: infra services come from `--profile infra`, migrations and seed helpers run inside the backend image, and `backend-dev` plus `strategy-test-worker` execute the API/worker chain. It intentionally seeds duplicate OHLCV timestamps and asserts deduped estimates, completed historical report/funnel/pagination, fresh heartbeat state, forward pending fill, and forward cancellation.
- Closed-loop verification is split by ownership boundary: `backend/tests/test_trading_e2e_virtual_flow.py` covers signal pending-entry trigger to virtual trade lifecycle and PnL/journal state, `backend/tests/test_strategy_testing_e2e_flow.py` covers historical backtest trades/metrics to execution eligibility profiles, `backend/tests/test_forward_strategy_test_runtime.py` covers forward virtual signal processing, heartbeat, runtime counters, and virtual trade writes, and `backend/tests/test_forward_strategy_test_app_integration.py` covers FastAPI lifespan wiring, shared stores, scanner tick forwarding, signal forwarding, and health exposure.
- Tests may use fake providers, stores, scanners, and virtual trading adapters for external infrastructure, but they must still call the real backend services that own trade lifecycle, runtime state, metrics, and eligibility decisions.

## Backtest Execution Policy

- `ProductionBacktestRunner` keeps RiskGate in the entry path. Backtests must normalize strategy signals into production-compatible trade plans before RiskGate; they must not bypass risk, sizing, take-profit, stop, or lifecycle validation.
- The backtest normalizer reuses pipeline invalidation, exit-plan, risk/reward, trade-plan enrichment, and trade-plan completeness services. Legacy strategy fields are accepted only after they become a complete `TradePlan` with invalidation conditions and executable targets.
- Mode semantics are explicit:
  - `discovery`: signal discovery only. It does not run virtual execution, does not arm historical pending entries, and produces no trades.
  - `research_virtual`: virtual execution is enabled, RiskGate/R:R hard blocks are converted to research warnings, and historical pending-entry replay is enabled by default.
  - `production_like`: virtual execution is enabled, RiskGate/R:R behavior stays strict, and historical pending-entry replay is enabled by default.
- Historical pending-entry replay applies to waiting-entry signals such as `wait_for_pullback` only when the signal has `execution_gate.can_arm_pending=true` and a valid entry zone. The replay arms a pending event, waits for a later candle to touch the entry zone, fills at the historical touch price, and then opens the simulated trade through the normal RiskGate and virtual execution path.
- `params.historical_pending_entries_enabled=false` disables historical pending-entry replay for `research_virtual` and `production_like`. `params.historical_pending_entries_enabled=null` or an omitted value uses the mode default. `preserve_legacy_backtest=true` always disables the new pending-entry logic.
- `params.historical_pending_max_wait_bars`, `params.pending_entry_max_wait_bars`, and `params.max_wait_bars` set the maximum number of closed bars to wait before a pending entry records `pending_entry_expired_before_touch`; the default is 12 bars.
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

- The default `radar_display_mode` is `all_market_opportunities`; clients must request
  `execution_ready` explicitly when they want the execution-only feed.
- Closed-candle confirmation is required when `settings.execution_closed_candle_only` is enabled. Open/forming candles may appear only as preview/watchlist/blocked state with a `forming_candle` reason.
- Execution candidates must have a passed trigger snapshot. Missing or failed triggers produce `trigger_not_confirmed`.
- The execution gate owns all action booleans: `can_notify`, `can_enter_now`, `can_arm_pending`, and `can_show_in_execution_feed`.
- Edge gates use backend thresholds for expectancy after costs, profit factor, entry-touch rate, and no-entry rate.
- Strategy eligibility metadata comes from persisted strategy-test eligibility profiles when available. It is advisory unless `settings.execution_require_walk_forward_edge` is enabled, then it becomes a hard blocker.
- Pending-entry trigger automation is virtual-only. Real pending execution must remain disabled unless a separately tested real execution path is added.
- Pending-entry expiration checks use the service-level UTC clock (`_utc_now()`), so tests can patch current time without disabling expiration product logic.

## Background Workers

- Scanner runner: `backend/app/workers/signal_worker.py`
- Durable strategy-test worker: `backend/app/workers/strategy_test_worker.py`
- Forward strategy-test runtime adapter: `backend/app/workers/forward_strategy_test_worker.py`
- Derivative snapshots: `backend/app/workers/derivative_snapshot_worker.py`
- Exchange instrument rules: `backend/app/workers/exchange_instrument_worker.py`
- Orderbook snapshots: `backend/app/workers/orderbook_snapshot_worker.py`
- Real position sync: `backend/app/workers/real_position_sync_worker.py`
- Strategy performance: `backend/app/workers/strategy_performance_worker.py`
- Signal outcomes: `backend/app/workers/signal_outcome_worker.py`

FastAPI lifespan starts only API-local scanner, expiry, and optional sync workers according to settings. The forward strategy-test loop is not started from FastAPI lifespan; the durable `strategy-test-worker` Docker service owns queued run claims, forward run startup, and forward heartbeats through database leases. The FastAPI `/health` root endpoint reports no in-process forward worker by default (`forward_strategy_test_running=false`) and exposes DB-readable `strategy_test_worker` lease state instead of process-local loop state.

Local MVP defaults keep scanner autostart and optional external sync workers disabled:

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

## Local Test Runtime

Use the repository-managed backend virtual environment for local tests. The setup script installs
uv-managed Python 3.12 into `.uv-python`, recreates the root `.venv`, and installs
`backend/requirements-dev.txt`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_backend.ps1
```

`pyproject.toml` configures pytest with `pythonpath = ["backend", "."]`, so tests do not need a
manual `PYTHONPATH` or a Codex bundled Python fallback.

## Change Rules

- Route handlers should stay thin: validate request, call service, return schema.
- Prefer repository boundaries for PostgreSQL writes.
- Update Pydantic schemas with API changes and regenerate frontend OpenAPI types.
- Add Alembic migrations for model/table/index/constraint changes.
- Keep tests focused on behavior and contracts. Existing tests under `backend/tests/` are the best map for expected behavior.
