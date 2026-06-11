# WORKERS

Codex guide for backend background workers.

## Lifespan Ownership

Workers are created and started from `backend/app/main.py` lifespan. The app stores worker instances on `app.state` and stops them during shutdown.

Autostart flags default to disabled for local MVP safety:

- `CRYPTO_RADAR_SCANNER_ENABLED=false`
- `EXCHANGE_INSTRUMENT_SYNC_ENABLED=false`
- `DERIVATIVE_SNAPSHOT_SYNC_ENABLED=false`
- `ORDERBOOK_SNAPSHOT_SYNC_ENABLED=false`
- `REAL_POSITION_SYNC_ENABLED=false`

`SignalExpiryWorker` starts with the app because it only manages local signal lifecycle expiry.

## Scanner Runner

Main file: `backend/app/workers/signal_worker.py`

The scanner runner:

- chooses scanner pairs and applies max-pair limits;
- warms candle history;
- calls `MarketScanner` to fetch market data and generate strategy signals;
- persists signals through `SignalService`;
- runs same-market-direction dedup before notifications;
- sends `signal.execution_ready` notifications only when `execution_gate.feed_kind == "execution_signal"`;
- triggers active pending-entry intents;
- updates virtual positions and records signal outcomes/invalidation.

Start it manually with `POST /api/v1/radar/scanner/start` when autostart is disabled.

Execution-ready notifications must come from backend gate state. Legacy fallback paths must still require execution-candidate status, closed candle, and `settings.execution_min_score`.

## Strategy Test Runtime

Strategy-test active-run state is backend-owned. Workers and services that execute strategy-test runs must update `strategy_test_runs.last_heartbeat_at` through the run store while a run is `running` or `stopping`.

The active-run API decides whether a run is stale from `last_heartbeat_at`, `started_at`, and `created_at` using the backend stale threshold. Frontend code may display `is_stale` and `stale_threshold_seconds`, but it must not reimplement stale-run policy.

Strategy-test scenario execution delegates to `ProductionBacktestRunner`. `production_like` runs keep strict RiskGate behavior; `research_virtual` and `discovery` may surface backend warnings and assumptions, but trade-plan normalization, stale decisions, eligibility, risk, and PnL stay backend-owned.

## Signal Outcome Workers

- `backend/app/workers/signal_outcome_worker.py`: evaluates open signal outcomes against market movement and terminal pending-entry states.
- `backend/app/workers/strategy_performance_worker.py`: aggregates strategy performance metrics for edge and eligibility decisions.

Pending-entry terminal reason codes are part of performance input. `virtual_execution_rejected` contributes to execution rejection metrics; expiry-before-touch contributes to no-entry metrics; temporary failures should not close the outcome.

## Market Data Sync Workers

- `backend/app/workers/exchange_instrument_worker.py`: syncs exchange instrument rules.
- `backend/app/workers/derivative_snapshot_worker.py`: syncs derivative market snapshots.
- `backend/app/workers/orderbook_snapshot_worker.py`: syncs orderbook snapshots with a short TTL.

These workers are optional external sync jobs. Keep intervals, categories, TTLs, and limits in `backend/app/core/config.py`.

## Real Position Sync

`backend/app/workers/real_position_sync_worker.py` syncs live exchange position state when `REAL_POSITION_SYNC_ENABLED=true`.

Live order placement is still guarded separately by execution flags and exchange connection checks. Do not infer live placement safety from the sync worker being enabled.

## Change Rules

- Keep worker loops thin; move trading policy into services.
- Always gate scanner notifications with `SignalExecutionGateSnapshot`.
- Do not notify suppressed dedup candidates.
- Preserve idempotency and reason-code metadata for pending-entry and signal-outcome transitions.
- Add tests for worker notification, scanner lifecycle, and outcome behavior when worker logic changes.
