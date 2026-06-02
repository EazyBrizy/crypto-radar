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

## Signal Selection Defaults

Strategy Test Lab scenarios can override backtest signal selection through
`params`, but the lab sets mode-aware defaults:

- `discovery` and `research_virtual`: `signal_selection_policy =
  "all_non_overlapping"`, `max_concurrent_positions = 10`, and
  `max_positions_per_symbol = 1`;
- `production_like`: `signal_selection_policy = "first_actionable"` and
  `max_concurrent_positions = 1`.

Supported policies are `first_actionable`, `highest_score`,
`all_non_overlapping`, and `all_signals`. Position constraints also include
`cooldown_bars_after_close` and `allow_opposite_signal_flip`. These controls
affect only simulated Strategy Test Lab/backtest positions; they must not write
to live orders, live positions, portfolio balances, or risk state.

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

Strategy Testing metrics are emitted through `MetricRegistry` in
`backend/app/services/strategy_testing/metrics.py`. Each metric is registered
as a `MetricDefinition` with:

- stable `code`, `label`, and `description`;
- supported grouping keys;
- a small deterministic calculator over `Sequence[StrategyTestTrade]`;
- `min_sample_size`.

The registry returns `MetricResult` rows with `code`, `label`, `value`,
`sample_size`, `group`, and `warnings`. Calculators must not read or write the
database. If a metric cannot be computed from current `StrategyTestTrade` rows,
it must return `None` with an explicit warning rather than synthetic data. For
example, `funding_total` is `0` only when explicit funding cost metadata is
tracked as zero; otherwise it returns `None` with `funding_not_modeled`.

Supported grouping keys are:

- `strategy` -> `strategy_code`
- `symbol` -> `symbol`
- `timeframe` -> `timeframe`
- `regime` -> `market_regime`
- `score_bucket` -> `score_bucket`
- `direction` -> `direction`

The matrix summary computes registry metrics for:

- all trades;
- `strategy`;
- `strategy/symbol/timeframe`;
- `strategy/regime`;
- `strategy/score_bucket`;
- `strategy/direction`.

Base metric codes:

- `trades_count`
- `signals_count`
- `entry_touch_rate`
- `winrate`
- `avg_win_r`
- `avg_loss_r`
- `expectancy_r`
- `expectancy_after_costs_r`
- `profit_factor`
- `max_drawdown_r`
- `max_drawdown_pct`
- `tp1_rate`
- `tp2_rate`
- `stop_rate`
- `invalidation_rate`
- `time_stop_rate`
- `avg_mfe_r`
- `avg_mae_r`
- `median_bars_to_entry`
- `median_bars_to_outcome`
- `avg_bars_in_trade`
- `fees_total`
- `slippage_total`
- `funding_total`
- `risk_rejection_rate`
- `execution_rejection_rate`
- `false_signal_rate`

To add a new metric in a future patch:

1. Add a small typed calculator in `metrics.py`.
2. Register a new `MetricDefinition` in `base_metric_definitions()`.
3. Add tests for the calculator, grouping behavior, and empty-sample behavior.
4. Update this document if the metric becomes part of the base set.

The matrix runner and report builder consume registry output, so adding a
metric does not require editing the runner unless a new grouping dimension or
new source data is introduced.

Small-sample metrics must be labeled through warnings/confidence and must not
be presented as production permission.

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
