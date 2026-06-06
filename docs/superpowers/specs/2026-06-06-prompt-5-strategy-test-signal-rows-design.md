# Prompt 5 Strategy Test Signal Rows Design

## Goal

Make the existing `strategy-tests` module a historical strategy tester that records every generated/evaluated signal event, not just virtual trade rows.

## Current State

- `strategy-tests` already owns the API, service, matrix runner, ClickHouse trade/metric store, report builder, and frontend panel/report.
- `ProductionBacktestRunner` sees generated `StrategySignal` objects and opens virtual trades, but only returns simulated trades plus aggregate counters.
- Metrics such as `signals_count`, `entry_touch_rate`, `expectancy_after_costs_r`, and rejection/no-entry rates are unavailable or derived from trade rows only.
- The frontend has runs/trades/reports, but no signal endpoint, conversion funnel, no-entry table, or advanced backtest params.

## Backend Design

Signal schema and storage:

- Add `StrategyTestSignal` as a Pydantic row model.
- Add `analytics.strategy_test_signals` DDL in the ClickHouse store and init SQL.
- Extend `ClickHouseStrategyTestStore` with `write_signals()` and `list_signals()`.
- Extend store protocols and the API with `GET /strategy-tests/runs/{run_id}/signals`.

Backtest event capture:

- Add `BacktestSignalEvent` and `signal_events` to `BacktestDetailedRunResult`.
- Capture an event for every generated strategy signal.
- Mark skipped selection, selected no-entry, risk rejection, execution rejection, filled, and final trade outcomes where the simulation can determine them.
- Keep event metadata small and JSON-serializable.

Strategy test runner:

- Convert backtest `signal_events` into `StrategyTestSignal` rows per scenario.
- Add `signals` to `StrategyTestScenarioResult` and `StrategyTestMatrixResult`.
- `StrategyTestingService.execute_run()` writes signals before metrics and computes metrics from both signals and trades.

Metrics and report:

- Add a metric context that includes trades and signals.
- Compute signal-aware rates from signal rows and trade PnL metrics from trade rows.
- Add groupings for `feed_kind` and `edge_status`.
- Add report sections for conversion funnel and signal/no-entry rows.

Frontend:

- Add `StrategyTestSignal` types and `strategyTestsApi.getSignals(runId)`.
- Rename mode labels to Russian labels from Prompt 5.
- Add advanced params controls and pass them through `request.params`.
- Render conversion funnel and signal/no-entry table in `StrategyTestReport`.

## Acceptance

- Signal rows are stored/read from ClickHouse and exposed through the strategy-tests API.
- Matrix/service summaries include signal counts and conversion counts.
- Signal-aware metrics use signal rows instead of reporting unavailable values when signals exist.
- Reports include a conversion funnel and signal/no-entry visibility.
- The existing strategy-tests frontend remains the primary UI/API; old `strategy_lab` is untouched.
