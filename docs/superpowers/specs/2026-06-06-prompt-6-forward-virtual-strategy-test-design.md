# Prompt 6 Forward Virtual Strategy Test Design

## Scope

Build `forward_virtual` strategy-test runs as isolated virtual simulations owned by strategy-testing, not radar, notifications, or real order flow. Historical backtests keep their current background-task path. Forward runs are queued through the same API, picked up by a worker, advanced from live closed candles, and exposed through status counters plus the existing final report.

## Architecture

The implementation extends the existing strategy-test contract instead of adding a parallel lab. `StrategyTestRunRequest` gains `test_type`, run statuses gain `stopping` and `cancelled`, and `StrategyTestRunResponse.summary` becomes persisted state for polling. `strategy_test_runs` gains `test_type`, `summary`, `runtime_state`, and `last_heartbeat_at`.

`StrategyForwardTestRunner` is an injectable state machine. It reads closed candles from a provider seam, generates strategy signals through the existing strategy engine path where possible, evaluates only isolated in-run pending entries/positions, and writes `StrategyTestSignal`/`StrategyTestTrade` rows to the same ClickHouse store introduced in Prompt 5. It does not call `SignalService.upsert_strategy_signal`, does not use normal `NotificationService`, and does not touch real virtual trading tables.

The first production-safe behavior is resumability-minimal: if a worker restart finds a running forward run whose `runtime_state` cannot be resumed, it marks the run failed with `worker_restart_not_resumable`. Tests use fake candle/signal providers so behavior is deterministic.

## API

`POST /strategy-tests/runs` accepts `test_type`. Historical requests keep `tags=["backtest"]`; forward requests include `forward_test` and are only enqueued. New endpoints:

- `GET /strategy-tests/runs/{run_id}/status` returns the run response with live summary counters.
- `POST /strategy-tests/runs/{run_id}/cancel` marks running/queued forward runs as `stopping` then `cancelled`, closing isolated positions according to `close_at_market_on_cancel=true` by default.

`GET /signals` and `/reports` continue to work for both test types.

## Forward Runtime

Forward runtime state tracks seen candle keys, signal dedup keys, pending entries, open positions, closed trade ids, current equity, realized/unrealized PnL, and timestamps for the latest tick/signal. `discovery` records signals only. `research_virtual` auto-enters eligible virtual signals with relaxed test execution. `production_like` requires production-like gate/risk pass before opening isolated virtual positions.

Pending entries expire to `no_entry`. Open isolated positions are advanced by closed candles and converted to strategy-test trade rows when terminal. Summary counters include signals, candidates, blocked signals, pending, entry touched, filled/closed trades, no-entry, risk/execution rejections, open positions, current equity, realized/unrealized PnL, and latest timestamps.

## Frontend

`StrategyTestingPanel` adds Backtest/Forward tabs. Backtest keeps the historical form. Forward defaults `start_at` to now, uses future duration presets, sends `test_type="forward_virtual"` and `tags=["forward_test"]`, and shows isolated virtual-account language. Runs table shows test type and live counters. Report shows a live dashboard for running forward runs and the full report after completion.

## Testing

Backend tests cover request defaults/tags, persisted run state, enqueue/status/cancel API, runner isolation from radar, signal rows, auto-entry, pending expiry, stop-loss close, cancel, and summary counters. Frontend tests cover the tabs, forward request payload, running counters, live dashboard, and API paths.
