# Strategy Testing v1

Strategy Testing is the Strategy Test Lab module for discovery, alpha research,
research-grade virtual lifecycle simulation, and production-like execution
simulation. It is separate from the legacy `/api/v1/backtests` runner and is
designed for matrix runs across markets, timeframes, strategy parameters, and
assumptions.

## Module Purpose

The module answers research questions without mutating live or virtual
portfolio state. It loads historical closed candles, derives features, runs
strategies, simulates outcomes or execution according to the requested mode,
and builds reproducible reports.

Supported modes:

- `discovery`: signal quality and entry/stop/target outcome research.
- `research_virtual`: virtual execution and lifecycle research with hard
  RR/risk rejection disabled and warnings/rejections reported separately.
- `production_like`: execution realism mode that routes decisions through
  configured production-style gates such as `RiskGate`.

Research modes are alpha/research evidence only. They do not grant real
execution permission.

## Backend Module Layout

```text
backend/app/services/strategy_testing/
  __init__.py
  schemas.py
  service.py
  runner.py
  matrix_runner.py
  metrics.py
  report_builder.py
  stores.py
  journal_adapter.py
  assumptions.py
```

Responsibilities:

- `schemas.py`: typed request, response, run, matrix, trade, metric, and report
  contracts.
- `service.py`: application service used by API routes.
- `runner.py`: single scenario execution for one expanded matrix scenario.
- `matrix_runner.py`: deterministic matrix expansion and orchestration.
- `metrics.py`: metrics registry and metric calculators.
- `report_builder.py`: report read-model assembly.
- `stores.py`: persistence boundary for Strategy Test Lab data.
- `journal_adapter.py`: journal projection for backtest trade visibility.
- `assumptions.py`: fill, cost, same-candle, and missing-data assumptions.

API routes must remain thin and call the service layer for all business logic.
Strategies must not perform database calls.

## API Endpoints

```text
POST /api/v1/strategy-tests/runs
GET  /api/v1/strategy-tests/runs
GET  /api/v1/strategy-tests/runs/{run_id}
GET  /api/v1/strategy-tests/runs/{run_id}/trades
GET  /api/v1/strategy-tests/reports
GET  /api/v1/strategy-tests/reports/{run_id}
```

`POST /api/v1/strategy-tests/runs` creates a Strategy Test Lab run from mode,
pairs, strategy codes, date range, parameters, and assumptions. List and detail
endpoints return run state, trades, and reports without exposing simulated
trades as live orders or positions.

## Frontend Entry

The frontend entry point is:

```text
Settings -> Strategy Testing
```

The page should make mode selection explicit so users can distinguish
research/alpha evidence from production-like execution realism.

## No-Lookahead Rules

Strategy tests must use only data available at the simulated decision time.

- Indicators for candle `N` may use candle `N` only after it is closed.
- Entries generated from candle `N` must not depend on candle `N + 1`.
- Higher-timeframe features must use the latest closed higher-timeframe candle
  available at the decision time.
- Funding, orderbook, liquidation, and derivative snapshots must be selected
  only when timestamped at or before the simulated decision.
- Missing live-only context must be omitted with metadata or simulated
  conservatively.

Silent future-data fills are forbidden.

## Same-Candle Policy

When entry, stop, and target can be touched inside the same candle, the run must
use a configured deterministic policy:

- `stop_first`: assume stop-loss happens before target.
- `target_first`: assume target happens before stop.
- `ignore_ambiguous`: exclude ambiguous same-candle outcomes from win scoring.

The default v1 policy is `stop_first`. Reports must expose the chosen policy.

## Metrics Registry

Strategy Testing metrics are emitted through a registry so every metric has a
stable name, calculation owner, unit, grouping dimensions, and confidence
semantics. Metric calculators should be small, typed, deterministic functions.

Expected registry groups include:

- summary performance;
- R-multiple distribution;
- drawdown;
- costs and slippage;
- lifecycle behavior;
- grouped performance by strategy, regime, score bucket, direction, exchange,
  symbol, and timeframe;
- warnings and rejection counts.

Small-sample metrics must be labeled `low` or `insufficient_sample` and must
not be presented as production permission.

## Journal Adapter Boundary

backtest trades must not pollute live/virtual portfolio risk state.

Strict rules:

- no inserts into `orders` for backtest trades;
- no inserts into `positions` for backtest trades;
- no updates to portfolio balances for backtest trades;
- no updates to `risk_state` for backtest trades;
- journal visibility must come from `StrategyTestJournalAdapter`;
- journal projections must carry `source/tag = backtest` and `run_id`
  metadata.

The journal adapter is a projection boundary only. It lets users inspect
Strategy Test Lab trades in journal-style views without turning simulated
events into executable, live, or virtual portfolio state.
