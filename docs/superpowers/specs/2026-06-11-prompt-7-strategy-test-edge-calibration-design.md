# Prompt 7 Strategy Test Edge Calibration Design

## Goal

Strategy test runs can publish their historical backtest or forward virtual results into execution eligibility profiles. Edge calibration then reads those profiles so execution signals can move from unknown edge to positive, negative, or insufficient sample based on tested evidence.

## Design

Add a durable Postgres table `strategy_execution_eligibility_profiles` keyed by strategy, exchange, symbol scope, timeframe, market regime, score bucket, and direction. Strategy test signals and trades remain in ClickHouse; the new table stores the published calibration result and the run ids that produced it.

`backend/app/services/strategy_testing/eligibility_publisher.py` reads a completed run plus its ClickHouse signal/trade rows, groups rows by the eligibility key, computes metrics with the existing strategy-test metric registry, evaluates configured thresholds, and upserts eligible or blocked profiles. The publisher returns counts for updated, eligible, and blocked profiles.

`StrategyPerformanceService.get_edge_profile()` checks published strategy-test profiles before falling back to existing daily outcome performance. `EdgeCalibrationService` passes signal direction into that lookup and includes profile source/run ids in edge metadata. Existing execution gate behavior remains the authority: positive profiles can pass, insufficient or negative profiles block.

## API And UI

Add `POST /api/v1/strategy-tests/runs/{run_id}/calibration`. The Strategy Test report panel shows a `Use this run for calibration` action for completed runs and displays `Calibration profiles updated: N eligible, M blocked` after success. Signal details show the strategy-test edge source and run ids when edge metadata contains them.

## Verification

Backend tests cover positive and negative publisher profiles, model/migration shape, API route, edge calibration profile lookup, and execution gate behavior. Frontend tests cover the API path, report button/result, and SignalDetails edge source display.
