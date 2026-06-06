# Prompt 5 Strategy Test Signal Rows Implementation Plan

**Goal:** Extend existing `strategy-tests` with historical signal rows, signal-aware metrics, report sections, API, and frontend controls.

## Tasks

- [x] Add RED backend tests for signal schema/store/API/service metrics/report.
- [x] Add RED frontend tests for advanced params, conversion funnel, and signal table.
- [x] Add `StrategyTestSignal` schema, ClickHouse DDL, write/read store methods, and API route.
- [x] Add backtest `BacktestSignalEvent` capture and scenario/matrix signal aggregation.
- [x] Compute matrix/report metrics from signal rows plus trade rows.
- [x] Add report conversion funnel and signal/no-entry sections.
- [x] Update frontend types/API/panel/report rendering.
- [x] Run focused backend and frontend verification.
- [x] Commit with `feat: add strategy test signal rows`.
