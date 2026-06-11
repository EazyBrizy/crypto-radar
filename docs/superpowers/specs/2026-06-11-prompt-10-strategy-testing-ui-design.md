# Prompt 10 Strategy Testing UI Design

## Objective

Polish the Strategy Testing frontend so users explicitly choose between Historical Backtest and Forward Test, understand live forward status, and get a full final report after completion.

## Existing State

The code already has `StrategyTestType`, forward/backtest request tags, status/cancel/signal API methods, basic tabs, forward run table tests, and a live forward dashboard.

## Gaps To Close

- Forward mode should feel like a live isolated account run, not a frontend UI test.
- Forward mode should offer duration presets and hide `discovery` mode.
- Same-candle policy should be a primary Backtest setting, but only an advanced Forward setting.
- The panel should poll `/strategy-tests/runs/{run_id}/status` for selected running forward tests every 2.5s.
- Runs table should expose separate signals, trades, and PnL/equity columns instead of burying them in one summary cell.
- Running forward report should be labeled `Live report preview`.
- Conversion funnel should name the execution lifecycle stages: Signals, Gate Passed, Pending/Entered, Filled, Closed, Winners, Losers.
- EN/RU dictionary should include the requested strategy-testing labels.

## Non-Goals

- Do not change backend run execution semantics.
- Do not render forward test signals in the main radar.
- Do not add a new charting library; a compact table/grid is enough for the funnel.
