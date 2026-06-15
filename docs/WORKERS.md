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

Strategy-test active-run state is backend-owned for `queued`, `running`, and `stopping` runs. Workers and services that execute strategy-test runs must update `strategy_test_runs.last_heartbeat_at` through the run store while a run is `running` or `stopping`; queued runs use `created_at` for stale recovery.

The active-run API applies stale policy to `queued`, `running`, and `stopping` from `last_heartbeat_at`, then `started_at`, then `created_at` using the backend stale threshold. Frontend code may display `is_stale` and `stale_threshold_seconds`, but it must not reimplement stale-run policy.

Strategy-test scenario execution delegates to `ProductionBacktestRunner`. `production_like` runs keep strict RiskGate behavior; `research_virtual` and `discovery` may surface backend warnings and assumptions, but trade-plan normalization, stale decisions, eligibility, risk, and PnL stay backend-owned.

Historical strategy-test progress is emitted as absolute counters for the current scenario and merged with the completed-scenario summary in `runtime_state.partial_summary`. `bars_processed`, `bars_total`, and `bars_pct` describe current scenario candle progress; `bars_per_second`, `elapsed_ms`, and `eta_seconds` are runtime estimates from the scenario start. `signals_seen` counts generated strategy signals. `execution_candidates` counts signals selected for execution consideration, including unresolved pending entries. `pending_armed` counts signals armed for historical pending-entry evaluation, while `pending_entries_count` is the current unresolved pending queue size. `entry_touched`/`touched` count signals whose entry zone or fill was reached; `filled` counts opened simulated trades; `closed` counts completed simulated trades. `no_entry` counts signal events that never opened a trade, and `not_selected` is the subset skipped by signal selection. `risk_rejections` and `execution_rejections` keep their existing RiskGate and virtual-execution meanings.

Historical strategy-test durability is scenario-boundary based. The service writes trades, signal events, and scenario metric/summary rows after `scenario_completed`, not for every bar or signal inside the loop. Writes are idempotent by `run_id`, scenario key (`strategy/exchange/symbol/timeframe`), and trade/event/metric key, so retries and repeated completion callbacks must not create report duplicates. `scenario_started`, `scenario_completed`, and `scenario_failed` update `runtime_state.scenario_status`, `current_scenario_key`, and `current_scenario_summary`; failures also store `last_error` and the partial summary available at the failure boundary.

Reports for `running`, `stopping`, `cancelled`, and `failed` historical runs are allowed to be partial. The report builder reads any completed scenario rows already written to the analytics store and combines them with `runtime_state.partial_summary`; cancelled runs keep completed-scenario trades/events even when later scenarios never finish.

`backend/app/services/strategy_testing/forward_runtime.py` owns `forward_virtual` processing. It selects active runs with `test_type="forward_virtual"` and `status="running"`, filters scanner ticks/signals by the requested matrix, persists strategy signals, uses `SignalExecutionGateSnapshot`, delegates virtual entry to `VirtualTradingService`, delegates pending entry arming to `PendingEntryService`, writes strategy-test trades, and merges `runtime_state` through the run store.

`backend/app/workers/forward_strategy_test_worker.py` is the minimal worker entrypoint. Its loop refreshes forward-run heartbeats and finalizes `stopping` runs as `cancelled`; market-data integrations can call `process_market_tick()` to feed scanner ticks into the runtime. `cancelled` runs are ignored by the runtime.

Forward runtime tests use fake stores, scanners, signal writers, and virtual trading adapters instead of real exchange credentials. The behavior under test is still backend-owned: active-run filtering, gate-driven action selection, virtual trade creation, strategy-test row writes, heartbeat updates, and cancellation of `stopping` runs.

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
