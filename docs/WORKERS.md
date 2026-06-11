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

The scanner may keep an in-memory same-process notification pre-filter, but `NotificationService` owns execution-notification idempotency. Duplicate notifications for the same user, exchange, symbol, direction, `execution_signal`, and time bucket are suppressed with Redis `SET NX EX` using `settings.notification_dedup_window_seconds`; if Redis is unavailable, the service logs a warning and falls back to service-local memory.

## Signal Expiry

`SignalExpiryWorker` starts with the app and manages local signal lifecycle expiry. It should only transition stale signals through backend services/repositories and preserve terminal status/reason metadata. It is not an execution worker and must not place orders.

## Signal Outcome Workers

- `backend/app/workers/signal_outcome_worker.py`: evaluates open signal outcomes against market movement and terminal pending-entry states.
- `backend/app/workers/strategy_performance_worker.py`: aggregates strategy performance metrics for edge and eligibility decisions.

Pending-entry terminal reason codes are part of performance input. `virtual_execution_rejected` contributes to execution rejection metrics; expiry-before-touch contributes to no-entry metrics; temporary failures should not close the outcome.

## Strategy Forward Test Worker

`backend/app/workers/strategy_forward_test_worker.py` advances `forward_virtual` strategy-test runs in the background when `STRATEGY_FORWARD_TEST_WORKER_ENABLED=true`.

Forward tests:

- use isolated virtual accounts and strategy-test storage;
- update run status and live counters for polling through `/api/v1/strategy-tests/runs/{run_id}/status`;
- persist strategy-test signals, trades, metrics, and reports through the strategy-testing services;
- support cancellation/stopping lifecycle for running tests;
- must never place real orders, arm real pending entries, or mutate the main radar feed as if forward-test signals were production scanner signals.

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
- Keep execution notification idempotency in `NotificationService`, not only in worker memory.
- Keep forward virtual tests isolated from real order placement and main radar execution state.
- Preserve idempotency and reason-code metadata for pending-entry and signal-outcome transitions.
- Add tests for worker notification, scanner lifecycle, and outcome behavior when worker logic changes.
